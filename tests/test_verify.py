"""Verification logic, exercised without a database.

The parts that need a live PostGIS are the two ``psycopg`` calls in
:func:`st_cheatsheet.verify.verify_dataset`; everything that decides *what a result
means* is pure and is tested here. A fake connection stands in for the driver so the
whole classification matrix - match, mismatch, unavailable, suspect ``since`` - runs
offline in CI.
"""

from __future__ import annotations

from typing import Any, Sequence

import pytest

from st_cheatsheet.loader import Dataset
from st_cheatsheet.model import SchemaError, VerifySpec
from st_cheatsheet.verify import (
    Outcome,
    ServerInfo,
    VerifyReport,
    example_floor,
    parse_result_block,
    parse_version,
    split_statements,
    verify_entry,
)

from .conftest import make_entry

SERVER = ServerInfo(postgis="3.4.3", geos="3.9.0-CAPI-1.16.2", postgresql="16.4")


class FakeCursor:
    """Minimal stand-in for a psycopg cursor.

    ``rows`` is the output the last statement should produce; ``error`` makes the
    execution raise instead. The double execution that the real code does to install
    text loaders is harmless here and is counted so the test can assert on it.
    """

    def __init__(self, columns: Sequence[str], rows: Sequence[Sequence[str]], error: Exception | None):
        self._columns = list(columns)
        self._rows = [list(row) for row in rows]
        self._error = error
        self.executed: list[str] = []
        self.adapters = self

    def register_loader(self, oid: Any, loader: Any) -> None:
        """Accept the loader registration the verifier performs."""

    @property
    def description(self) -> list[Any] | None:
        if not self._columns:
            return None
        return [type("Col", (), {"name": name, "type_code": 25})() for name in self._columns]

    def execute(self, statement: str) -> None:
        self.executed.append(statement)
        if self._error is not None:
            raise self._error

    def fetchall(self) -> list[list[Any]]:
        return [list(row) for row in self._rows]

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


class FakeConnection:
    """A connection that hands out one :class:`FakeCursor` and counts rollbacks."""

    def __init__(
        self,
        columns: Sequence[str] = (),
        rows: Sequence[Sequence[str]] = (),
        error: Exception | None = None,
    ) -> None:
        self.cursor_object = FakeCursor(columns, rows, error)
        self.rollbacks = 0

    def cursor(self) -> FakeCursor:
        return self.cursor_object

    def rollback(self) -> None:
        self.rollbacks += 1


@pytest.fixture
def undefined_function() -> Exception:
    """A psycopg error mimicking a missing function on an older server."""
    psycopg = pytest.importorskip("psycopg")
    return psycopg.errors.UndefinedFunction("function st_nope(geometry) does not exist")


class TestParseVersion:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("1.0", (1, 0)),
            ("3.4.3", (3, 4, 3)),
            ("1.5 (geography since 2.0)", (1, 5)),
            ("1.0 (renamed from ST_Estimated_Extent in 2.1)", (1, 0)),
            ("0.8.2 (Z and M support since 1.1.1)", (0, 8, 2)),
        ],
    )
    def test_reads_the_leading_version_only(self, text: str, expected: tuple[int, ...]) -> None:
        assert parse_version(text) == expected

    def test_returns_none_without_a_leading_number(self) -> None:
        assert parse_version("unreleased") is None

    def test_every_real_since_value_parses(self, real_dataset: Dataset) -> None:
        """A ``since`` the verifier cannot parse silently disables the version guard."""
        unparseable = [entry.name for entry in real_dataset if parse_version(entry.since) is None]
        assert unparseable == []


class TestSplitStatements:
    def test_single_statement(self) -> None:
        assert split_statements("SELECT 1;") == ["SELECT 1"]

    def test_multiple_statements(self) -> None:
        sql = "CREATE TABLE t (id int);\nINSERT INTO t VALUES (1);\nSELECT * FROM t;"
        assert len(split_statements(sql)) == 3

    def test_semicolon_inside_a_literal_does_not_split(self) -> None:
        assert split_statements("SELECT 'a;b' AS x;") == ["SELECT 'a;b' AS x"]

    def test_trailing_semicolon_is_optional(self) -> None:
        assert split_statements("SELECT 1") == ["SELECT 1"]


class TestParseResultBlock:
    def test_parses_columns_and_rows(self) -> None:
        parsed = parse_result_block(" a | b \n---+---\n 1 | 2 ")
        assert parsed is not None
        assert parsed.columns == ("a", "b")
        assert parsed.rows == (("1", "2"),)

    def test_empty_cell_is_preserved_as_null(self) -> None:
        parsed = parse_result_block(" plain | topo \n-------+------\n       | POLYGON")
        assert parsed is not None
        assert parsed.rows == (("", "POLYGON"),)

    def test_row_count_footer_is_ignored(self) -> None:
        parsed = parse_result_block(" n \n---\n 3 \n(1 row)")
        assert parsed is not None
        assert parsed.rows == (("3",),)

    def test_block_without_a_rule_is_unparseable(self) -> None:
        assert parse_result_block("just some prose") is None

    def test_wrapped_value_is_unparseable_rather_than_wrong(self) -> None:
        """A value split across lines has too few cells; that must not read as a mismatch."""
        assert parse_result_block(" banner \n---------\n a | b | c") is None

    def test_every_exact_entry_has_a_parseable_result(self, real_dataset: Dataset) -> None:
        """An unparseable block would be silently skipped, so no ``exact`` entry may have one."""
        broken = [
            entry.name
            for entry in real_dataset
            if not entry.verify.is_exempt and parse_result_block(entry.example.result) is None
        ]
        assert broken == []


class TestVerifySpecSchema:
    def test_default_is_exact_and_unexempt(self) -> None:
        entry = make_entry()
        assert entry.verify.mode == "exact"
        assert entry.verify.is_exempt is False

    def test_unknown_mode_is_rejected(self) -> None:
        with pytest.raises(SchemaError, match="not one of"):
            make_entry(verify={"mode": "whatever", "reason": "x"})

    def test_exemption_without_a_reason_is_rejected(self) -> None:
        with pytest.raises(SchemaError, match="needs a 'reason'"):
            make_entry(verify={"mode": "geos-sensitive"})

    def test_min_version_without_a_reason_is_rejected(self) -> None:
        with pytest.raises(SchemaError, match="needs a 'reason'"):
            make_entry(verify={"min_version": "3.2"})

    def test_non_numeric_min_version_is_rejected(self) -> None:
        with pytest.raises(SchemaError, match="dotted version"):
            make_entry(verify={"min_version": "3.2beta", "reason": "x"})

    def test_unknown_verify_key_is_rejected(self) -> None:
        with pytest.raises(SchemaError, match="unknown field"):
            make_entry(verify={"mode": "exact", "tolerance": 1})

    def test_spec_survives_a_round_trip(self) -> None:
        entry = make_entry(verify={"mode": "geos-sensitive", "reason": "GEOS varies"})
        assert entry.to_dict()["verify"]["mode"] == "geos-sensitive"

    def test_every_exemption_in_the_real_dataset_is_explained(self, real_dataset: Dataset) -> None:
        unexplained = [
            entry.name
            for entry in real_dataset
            if entry.verify.is_exempt and len(entry.verify.reason) < 40
        ]
        assert unexplained == []


class TestExampleFloor:
    def test_defaults_to_the_since_field(self) -> None:
        label, version = example_floor(make_entry(since="1.5 (geography since 2.0)"))
        assert (label, version) == ("1.5", (1, 5))

    def test_min_version_overrides_since(self) -> None:
        entry = make_entry(
            since="1.0 (srid argument since 3.2)",
            verify={"min_version": "3.2", "reason": "example uses the 3.2 srid form"},
        )
        assert example_floor(entry) == ("3.2", (3, 2))


class TestVerifyEntry:
    def test_matching_output_matches(self) -> None:
        entry = make_entry()
        connection = FakeConnection(["st_example"], [["0"]])
        assert verify_entry(connection, entry, SERVER).status == "matched"

    def test_differing_value_mismatches(self) -> None:
        entry = make_entry()
        outcome = verify_entry(FakeConnection(["st_example"], [["99"]]), entry, SERVER)
        assert outcome.status == "mismatched"
        assert "99" in outcome.actual
        assert outcome.is_failure

    def test_differing_column_name_mismatches(self) -> None:
        outcome = verify_entry(FakeConnection(["wrong"], [["0"]]), make_entry(), SERVER)
        assert outcome.status == "mismatched"

    def test_the_transaction_is_always_rolled_back(self) -> None:
        connection = FakeConnection(["st_example"], [["0"]])
        verify_entry(connection, make_entry(), SERVER)
        assert connection.rollbacks == 1

    def test_rollback_happens_even_when_the_statement_errors(
        self, undefined_function: Exception
    ) -> None:
        connection = FakeConnection(["st_example"], [], error=undefined_function)
        verify_entry(connection, make_entry(), SERVER)
        assert connection.rollbacks == 1

    def test_geos_sensitive_mismatch_is_skipped_not_failed(self) -> None:
        entry = make_entry(
            verify={"mode": "geos-sensitive", "reason": "output depends on the GEOS version"}
        )
        outcome = verify_entry(FakeConnection(["st_example"], [["99"]]), entry, SERVER)
        assert outcome.status == "skipped"
        assert not outcome.is_failure
        # The diff is still shown, so a human can see what actually changed.
        assert "99" in outcome.actual and "0" in outcome.expected

    def test_version_string_mode_ignores_the_value(self) -> None:
        entry = make_entry(verify={"mode": "version-string", "reason": "banner varies"})
        outcome = verify_entry(FakeConnection(["v"], [["POSTGIS=9.9"]]), entry, SERVER)
        assert outcome.status == "skipped"

    def test_version_string_mode_still_requires_output(self) -> None:
        entry = make_entry(verify={"mode": "version-string", "reason": "banner varies"})
        outcome = verify_entry(FakeConnection(["v"], [[""]]), entry, SERVER)
        assert outcome.status == "failed"

    def test_error_below_the_floor_is_skipped_as_unavailable(
        self, undefined_function: Exception
    ) -> None:
        entry = make_entry(since="3.9")
        outcome = verify_entry(
            FakeConnection(["st_example"], [], error=undefined_function), entry, SERVER
        )
        assert outcome.status == "skipped"
        assert "unavailable" in outcome.detail
        assert not outcome.is_failure

    def test_error_above_the_floor_is_a_real_failure(self, undefined_function: Exception) -> None:
        entry = make_entry(since="1.0")
        outcome = verify_entry(
            FakeConnection(["st_example"], [], error=undefined_function), entry, SERVER
        )
        assert outcome.status == "failed"
        assert outcome.is_failure

    def test_min_version_moves_the_unavailability_floor(
        self, undefined_function: Exception
    ) -> None:
        entry = make_entry(
            since="1.0",
            verify={"min_version": "3.9", "reason": "example uses a much newer overload"},
        )
        outcome = verify_entry(
            FakeConnection(["st_example"], [], error=undefined_function), entry, SERVER
        )
        assert outcome.status == "skipped"

    def test_matching_above_the_claimed_floor_is_since_suspect(self) -> None:
        """The whole point of the cross-check: it ran on a server older than claimed."""
        entry = make_entry(since="3.9")
        outcome = verify_entry(FakeConnection(["st_example"], [["0"]]), entry, SERVER)
        assert outcome.status == "since-suspect"
        assert "3.9" in outcome.detail and "3.4.3" in outcome.detail
        # A documentation bug, not a broken build.
        assert not outcome.is_failure

    def test_unparseable_result_block_is_skipped(self) -> None:
        entry = make_entry(example={**make_entry().example.to_dict(), "result": "prose only"})
        outcome = verify_entry(FakeConnection(["st_example"], [["0"]]), entry, SERVER)
        assert outcome.status == "skipped"


class TestVerifyReport:
    def _report(self, *outcomes: Outcome) -> VerifyReport:
        return VerifyReport(server=SERVER, outcomes=list(outcomes))

    def test_clean_run_exits_zero(self) -> None:
        report = self._report(Outcome("a", "matched"), Outcome("b", "skipped"))
        assert report.exit_code() == 0

    def test_mismatch_exits_non_zero(self) -> None:
        assert self._report(Outcome("a", "mismatched")).exit_code() == 1

    def test_failure_exits_non_zero(self) -> None:
        assert self._report(Outcome("a", "failed")).exit_code() == 1

    def test_since_suspect_is_advisory_by_default(self) -> None:
        report = self._report(Outcome("a", "since-suspect"))
        assert report.exit_code() == 0
        assert report.exit_code(strict_since=True) == 1

    def test_counts_cover_every_status(self) -> None:
        counts = self._report(Outcome("a", "matched")).counts()
        assert counts["matched"] == 1
        assert counts["mismatched"] == 0
        assert set(counts) >= {"matched", "mismatched", "failed", "since-suspect", "skipped"}


class TestVerifyCommandOffline:
    """The CLI paths reachable without a server."""

    def test_missing_dsn_exits_three(self, capsys: pytest.CaptureFixture[str], monkeypatch) -> None:
        from st_cheatsheet.cli import EXIT_DATASET, main

        monkeypatch.delenv("ST_CHEATSHEET_DSN", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        code = main(["--no-color", "--width", "120", "verify"])
        assert code == EXIT_DATASET
        assert "no DSN given" in capsys.readouterr().out

    def test_unreachable_server_exits_three(self, capsys: pytest.CaptureFixture[str]) -> None:
        from st_cheatsheet.cli import EXIT_DATASET, main

        pytest.importorskip("psycopg")
        code = main(
            [
                "--no-color",
                "--width",
                "120",
                "verify",
                "--dsn",
                "postgresql://nobody@127.0.0.1:1/none?connect_timeout=1",
            ]
        )
        assert code == EXIT_DATASET
        assert "cannot connect" in capsys.readouterr().out
