"""Execute every entry's SQL example against a live PostGIS and check the stated result.

The dataset claims two things that only a real server can settle: that each ``example.sql``
produces the ``example.result`` printed beside it, and that each function exists from the
``since`` version onwards. This module checks both.

Design notes:

* **One transaction per entry, always rolled back.** Examples are allowed to CREATE and
  INSERT (``ST_EstimatedExtent`` does), so each runs isolated and leaves nothing behind.
  The DSN may therefore point at a database you care about.
* **Values are compared as the server prints them.** After a first execution reveals the
  column types, a passthrough loader is registered for each type OID and the statement is
  re-run, so every value arrives as the exact string PostgreSQL's output function
  produces - ``t`` for true, not ``true``. That is what the ``result`` blocks contain.
* **Version sensitivity is data, not code.** Which entries cannot match everywhere is
  declared per-entry in :class:`~st_cheatsheet.model.VerifySpec`, so the verifier never
  hardcodes a function name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .loader import Dataset
from .model import FunctionEntry

__all__ = [
    "Outcome",
    "STATUSES",
    "ServerInfo",
    "VerifyReport",
    "parse_result_block",
    "parse_version",
    "split_statements",
    "verify_dataset",
]


class VerifyError(RuntimeError):
    """Raised when verification cannot start at all (no driver, no connection)."""


#: Outcome statuses, in report order. Only ``mismatched`` and ``failed`` are build
#: failures; ``since-suspect`` is a documentation bug, reported but not fatal by
#: default (see ``--strict-since``).
STATUSES: tuple[str, ...] = (
    "matched",
    "mismatched",
    "failed",
    "since-suspect",
    "skipped",
)


# ---------------------------------------------------------------------------
# Parsing helpers (pure, unit-testable without a database)
# ---------------------------------------------------------------------------

_VERSION_HEAD = re.compile(r"^(\d+(?:\.\d+)*)")
#: psql's row-count footer, e.g. ``(1 row)`` / ``(3 rows)``.
_ROW_COUNT = re.compile(r"^\(\d+ rows?\)$")


def parse_version(text: str) -> tuple[int, ...] | None:
    """Return the leading dotted version in ``text`` as a tuple of ints.

    ``since`` fields carry prose after the number - ``"1.5 (geography since 2.0)"`` -
    and only the leading number is the floor for the function existing at all::

        >>> parse_version("1.5 (geography since 2.0)")
        (1, 5)
        >>> parse_version("3.4.3")
        (3, 4, 3)
        >>> parse_version("unreleased") is None
        True
    """
    match = _VERSION_HEAD.match(text.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _compare_versions(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    """Compare two version tuples of possibly different length (1.5 == 1.5.0)."""
    width = max(len(left), len(right))
    padded_left = left + (0,) * (width - len(left))
    padded_right = right + (0,) * (width - len(right))
    return (padded_left > padded_right) - (padded_left < padded_right)


def split_statements(sql: str) -> list[str]:
    """Split a SQL snippet into individual statements on unquoted semicolons.

    Quoted text is respected so that a ``;`` inside a literal does not split the
    statement. Doubled quotes need no special case: the first closes the literal and
    the second immediately reopens it, which leaves the quoting state correct.
    """
    statements: list[str] = []
    buffer: list[str] = []
    quote: str | None = None

    for char in sql:
        if quote is not None:
            buffer.append(char)
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
            buffer.append(char)
            continue
        if char == ";":
            statements.append("".join(buffer))
            buffer = []
            continue
        buffer.append(char)

    statements.append("".join(buffer))
    return [statement.strip() for statement in statements if statement.strip()]


@dataclass(frozen=True, slots=True)
class ExpectedResult:
    """A ``result`` block parsed back into column names and cell values."""

    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


def parse_result_block(result: str) -> ExpectedResult | None:
    """Parse a psql-style result block into columns and rows.

    Returns ``None`` when the block does not have the expected header/rule/rows shape,
    or when a data row does not have one cell per column - which happens when a single
    value was wrapped across lines to fit the page. Callers treat ``None`` as
    "cannot compare", never as a mismatch.
    """
    lines = [line for line in result.splitlines() if line.strip()]
    rule_index = next(
        (
            index
            for index, line in enumerate(lines)
            if index > 0 and set(line.strip()) <= {"-", "+"} and "-" in line
        ),
        None,
    )
    if rule_index is None:
        return None

    columns = tuple(cell.strip() for cell in lines[rule_index - 1].split("|"))
    rows: list[tuple[str, ...]] = []
    for line in lines[rule_index + 1 :]:
        if _ROW_COUNT.match(line.strip()):
            continue
        cells = tuple(cell.strip() for cell in line.split("|"))
        if len(cells) != len(columns):
            return None
        rows.append(cells)
    if not rows:
        return None
    return ExpectedResult(columns=columns, rows=tuple(rows))


def format_rows(columns: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    """Return a compact one-line-per-row rendering, for showing a diff."""
    header = " | ".join(columns)
    body = "\n".join(" | ".join(cell for cell in row) for row in rows)
    return f"{header}\n{body}" if body else header


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ServerInfo:
    """What the server under test reports about itself."""

    postgis: str
    geos: str
    postgresql: str

    @property
    def postgis_version(self) -> tuple[int, ...]:
        """The PostGIS library version as a comparable tuple."""
        return parse_version(self.postgis) or ()

    def __str__(self) -> str:
        return f"PostGIS {self.postgis} / GEOS {self.geos} / {self.postgresql}"


@dataclass(frozen=True, slots=True)
class Outcome:
    """The verdict for one entry."""

    name: str
    status: str
    detail: str = ""
    expected: str = ""
    actual: str = ""

    @property
    def is_failure(self) -> bool:
        """``True`` for statuses that should fail a build."""
        return self.status in ("mismatched", "failed")


@dataclass(slots=True)
class VerifyReport:
    """Every :class:`Outcome` from one run, plus the server it ran against."""

    server: ServerInfo
    outcomes: list[Outcome] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        """Return ``{status: count}`` covering every status in :data:`STATUSES`."""
        tally = dict.fromkeys(STATUSES, 0)
        for outcome in self.outcomes:
            tally[outcome.status] = tally.get(outcome.status, 0) + 1
        return tally

    def by_status(self, status: str) -> list[Outcome]:
        """Return the outcomes with the given status."""
        return [outcome for outcome in self.outcomes if outcome.status == status]

    @property
    def failures(self) -> list[Outcome]:
        """Outcomes that should fail a build."""
        return [outcome for outcome in self.outcomes if outcome.is_failure]

    def exit_code(self, *, strict_since: bool = False) -> int:
        """Return ``0`` when the run is clean, ``1`` otherwise."""
        if self.failures:
            return 1
        if strict_since and self.by_status("since-suspect"):
            return 1
        return 0


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _import_psycopg() -> Any:
    """Import psycopg, turning the ImportError into an actionable message."""
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise VerifyError(
            "the 'verify' command needs psycopg 3 "
            "(add it with: pip install -r requirements-verify.txt)"
        ) from exc
    return psycopg


def _execute_as_text(cursor: Any, statement: str) -> tuple[list[str], list[list[str]]]:
    """Run ``statement`` and return ``(column names, rows)`` as printed strings.

    The statement is executed twice. The first run is only for ``cursor.description``:
    once the type OIDs are known, a passthrough text loader is registered for each, so
    the second run yields the server's own output-function text rather than a Python
    object rendered by psycopg. That distinction matters - a boolean prints as ``t``
    here and as ``True`` (or ``true``, if cast) any other way.
    """
    from psycopg.types.string import TextLoader

    cursor.execute(statement)
    if cursor.description is None:
        return [], []
    columns = [column.name for column in cursor.description]
    for column in cursor.description:
        cursor.adapters.register_loader(column.type_code, TextLoader)

    cursor.execute(statement)
    rows = [["" if value is None else str(value) for value in row] for row in cursor.fetchall()]
    return columns, rows


def _run_example(connection: Any, entry: FunctionEntry) -> tuple[list[str], list[list[str]]]:
    """Run every statement of an entry's example, returning the last one's output.

    Always rolls back: examples may create tables, and verification must not leave a
    trace in the target database.
    """
    statements = split_statements(entry.example.sql)
    if not statements:
        raise VerifyError("example.sql contains no statements")
    try:
        with connection.cursor() as cursor:
            for statement in statements[:-1]:
                cursor.execute(statement)
            return _execute_as_text(cursor, statements[-1])
    finally:
        connection.rollback()


def read_server_info(connection: Any) -> ServerInfo:
    """Return the PostGIS, GEOS and PostgreSQL versions of the connected server."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT postgis_lib_version(), postgis_geos_version(), current_setting('server_version')"
        )
        postgis, geos, postgresql = cursor.fetchone()
    connection.rollback()
    return ServerInfo(postgis=postgis, geos=geos, postgresql=postgresql)


def example_floor(entry: FunctionEntry) -> tuple[str, tuple[int, ...] | None]:
    """Return ``(label, version)`` for the lowest PostGIS the example can run on.

    Normally that is the leading token of ``since``. An entry may override it with
    ``verify.min_version`` when its example deliberately exercises an overload newer
    than the function itself - ``ST_Point`` documents ``since: 1.0`` but its example
    passes the SRID argument added in 3.2.
    """
    if entry.verify.min_version:
        return entry.verify.min_version, parse_version(entry.verify.min_version)
    label = entry.since.split(" ")[0]
    return label, parse_version(entry.since)


def _classify_error(entry: FunctionEntry, server: ServerInfo, error: Exception) -> Outcome:
    """Turn an execution failure into the right kind of outcome.

    An example that fails on a server older than its own declared floor is evidence
    *for* the dataset, not against it, so it is skipped as unavailable.
    """
    message = " ".join(str(error).split())
    label, floor = example_floor(entry)
    if floor is not None and server.postgis_version and _compare_versions(floor, server.postgis_version) > 0:
        return Outcome(
            entry.name,
            "skipped",
            detail=f"unavailable: example needs PostGIS {label} > server {server.postgis}",
        )
    return Outcome(entry.name, "failed", detail=message)


def _check_since(entry: FunctionEntry, server: ServerInfo) -> Outcome | None:
    """Report a ``since`` floor the server has just contradicted by running the example.

    The example ran on a server *older* than the entry claims to require, so either the
    ``since`` value is too high or the example does not exercise the version-gated part
    of the function. Either way the dataset is making a claim it cannot support.
    """
    label, floor = example_floor(entry)
    if floor is None or not server.postgis_version:
        return None
    if _compare_versions(floor, server.postgis_version) <= 0:
        return None
    return Outcome(
        entry.name,
        "since-suspect",
        detail=(
            f"claims PostGIS {label} but the example runs and matches "
            f"on PostGIS {server.postgis}"
        ),
    )


def verify_entry(connection: Any, entry: FunctionEntry, server: ServerInfo) -> Outcome:
    """Execute one entry's example and return its :class:`Outcome`."""
    psycopg = _import_psycopg()

    try:
        columns, rows = _run_example(connection, entry)
    except psycopg.Error as exc:
        return _classify_error(entry, server, exc)
    except VerifyError as exc:
        return Outcome(entry.name, "failed", detail=str(exc))

    actual = format_rows(columns, rows)

    if entry.verify.mode == "version-string":
        # The value is a version banner. Require only that it ran and said something.
        if not rows or not any(cell.strip() for row in rows for cell in row):
            return Outcome(entry.name, "failed", detail="version query returned nothing", actual=actual)
        return Outcome(
            entry.name,
            "skipped",
            detail=f"version-string: {entry.verify.reason}",
            actual=actual,
        )

    expected = parse_result_block(entry.example.result)
    if expected is None:
        return Outcome(
            entry.name,
            "skipped",
            detail="result block is not a comparable psql table",
            actual=actual,
        )

    expected_text = format_rows(expected.columns, expected.rows)
    matched = (
        tuple(columns) == expected.columns
        and tuple(tuple(row) for row in rows) == expected.rows
    )

    if matched:
        return _check_since(entry, server) or Outcome(entry.name, "matched")

    if entry.verify.mode == "geos-sensitive":
        return Outcome(
            entry.name,
            "skipped",
            detail=f"geos-sensitive (GEOS {server.geos}): {entry.verify.reason}",
            expected=expected_text,
            actual=actual,
        )

    return Outcome(
        entry.name,
        "mismatched",
        detail="output does not match the stated result",
        expected=expected_text,
        actual=actual,
    )


def verify_dataset(dataset: Dataset, dsn: str) -> VerifyReport:
    """Verify every entry in ``dataset`` against the server at ``dsn``.

    :raises VerifyError: if psycopg is missing or the server cannot be reached.
    """
    psycopg = _import_psycopg()
    try:
        connection = psycopg.connect(dsn, autocommit=False)
    except psycopg.Error as exc:
        raise VerifyError(f"cannot connect: {' '.join(str(exc).split())}") from exc

    with connection:
        try:
            server = read_server_info(connection)
        except psycopg.Error as exc:
            raise VerifyError(
                "the target database does not have PostGIS installed "
                f"(run CREATE EXTENSION postgis): {' '.join(str(exc).split())}"
            ) from exc
        report = VerifyReport(server=server)
        for entry in dataset:
            report.outcomes.append(verify_entry(connection, entry, server))
    return report
