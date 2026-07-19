"""Dataclass model for cheatsheet entries.

Every YAML document under ``data/functions/`` is parsed into a :class:`FunctionEntry`.
The model is deliberately strict: unknown keys, missing required fields and unknown
categories are all errors, so that malformed data fails in CI rather than silently
producing a half-empty reference card.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

__all__ = [
    "CATEGORIES",
    "CATEGORY_DESCRIPTIONS",
    "Argument",
    "Example",
    "FunctionEntry",
    "IndexUsage",
    "SchemaError",
]


CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "constructors": "Build geometry values from coordinates, text, binary or GeoJSON.",
    "accessors": "Inspect a geometry: type, dimension, SRID, coordinates, validity.",
    "measurement": "Distances, areas, lengths and perimeters.",
    "relationships": "Boolean spatial predicates and the DE-9IM model behind them.",
    "processing": "Derive new geometries: buffers, unions, simplification, clustering.",
    "editors": "Modify an existing geometry in place: SRID, validity, densification.",
    "output": "Serialise geometry to text, JSON, binary or vector tiles.",
    "operators": "Bounding-box and KNN operators that drive index access.",
    "utility": "Version, configuration and housekeeping helpers.",
}

#: Canonical category names. Data files are grouped one-per-category by convention,
#: but the loader does not enforce the filename/category correspondence.
CATEGORIES: tuple[str, ...] = tuple(CATEGORY_DESCRIPTIONS)


class SchemaError(ValueError):
    """Raised when a YAML document does not satisfy the entry schema.

    Carries the offending source path (when known) so the validator can report
    ``path: message`` without the caller re-wrapping every exception.
    """

    def __init__(self, message: str, *, source: str | None = None) -> None:
        self.source = source
        super().__init__(f"{source}: {message}" if source else message)


def _require(mapping: Mapping[str, Any], key: str, kind: type, *, source: str | None) -> Any:
    """Return ``mapping[key]``, raising :class:`SchemaError` unless it is a ``kind``."""
    if key not in mapping:
        raise SchemaError(f"missing required field {key!r}", source=source)
    value = mapping[key]
    if not isinstance(value, kind):
        got = type(value).__name__
        raise SchemaError(f"field {key!r} must be {kind.__name__}, got {got}", source=source)
    return value


def _require_text(mapping: Mapping[str, Any], key: str, *, source: str | None) -> str:
    """Return a non-blank string field."""
    value = _require(mapping, key, str, source=source).strip()
    if not value:
        raise SchemaError(f"field {key!r} must not be empty", source=source)
    return value


def _require_block(mapping: Mapping[str, Any], key: str, *, source: str | None) -> str:
    """Return a non-blank string field with its internal layout preserved.

    Unlike :func:`_require_text` this only trims trailing whitespace. Leading spaces
    are significant in psql result blocks, where the first line is the centred column
    header and stripping it would silently break the alignment.
    """
    value = _require(mapping, key, str, source=source)
    if not value.strip():
        raise SchemaError(f"field {key!r} must not be empty", source=source)
    return value.rstrip()


def _string_list(
    mapping: Mapping[str, Any],
    key: str,
    *,
    source: str | None,
    minimum: int = 0,
) -> list[str]:
    """Return a list-of-strings field, defaulting to ``[]`` when absent."""
    raw = mapping.get(key, [])
    if not isinstance(raw, list):
        raise SchemaError(f"field {key!r} must be a list", source=source)
    values: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str) or not item.strip():
            raise SchemaError(f"field {key!r}[{index}] must be a non-empty string", source=source)
        values.append(item.strip())
    if len(values) < minimum:
        raise SchemaError(
            f"field {key!r} needs at least {minimum} item(s), got {len(values)}", source=source
        )
    return values


def _reject_unknown(mapping: Mapping[str, Any], known: Iterable[str], *, source: str | None) -> None:
    """Raise if the mapping carries keys outside ``known`` (catches typos in data)."""
    unknown = sorted(set(mapping) - set(known))
    if unknown:
        raise SchemaError(f"unknown field(s): {', '.join(unknown)}", source=source)


@dataclass(frozen=True, slots=True)
class Argument:
    """One positional argument of a function signature."""

    name: str
    type: str
    description: str
    optional: bool = False

    @classmethod
    def from_dict(cls, raw: Any, *, source: str | None = None) -> "Argument":
        """Build an :class:`Argument` from a parsed YAML mapping."""
        if not isinstance(raw, Mapping):
            raise SchemaError("each argument must be a mapping", source=source)
        _reject_unknown(raw, ("name", "type", "description", "optional"), source=source)
        optional = raw.get("optional", False)
        if not isinstance(optional, bool):
            raise SchemaError("argument field 'optional' must be a boolean", source=source)
        return cls(
            name=_require_text(raw, "name", source=source),
            type=_require_text(raw, "type", source=source),
            description=_require_text(raw, "description", source=source),
            optional=optional,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping."""
        return {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "optional": self.optional,
        }


@dataclass(frozen=True, slots=True)
class Example:
    """A runnable snippet plus, for SQL, the result it actually produces."""

    sql: str
    result: str
    psycopg: str
    geoalchemy: str

    @classmethod
    def from_dict(cls, raw: Any, *, source: str | None = None) -> "Example":
        """Build an :class:`Example` from a parsed YAML mapping."""
        if not isinstance(raw, Mapping):
            raise SchemaError("field 'example' must be a mapping", source=source)
        _reject_unknown(raw, ("sql", "result", "psycopg", "geoalchemy"), source=source)
        return cls(
            sql=_require_block(raw, "sql", source=source),
            result=_require_block(raw, "result", source=source),
            psycopg=_require_block(raw, "psycopg", source=source),
            geoalchemy=_require_block(raw, "geoalchemy", source=source),
        )

    def snippet(self, kind: str) -> str:
        """Return one snippet by name.

        :param kind: one of ``sql``, ``psycopg``, ``geoalchemy``.
        :raises KeyError: if ``kind`` is not a known snippet name.
        """
        try:
            return {"sql": self.sql, "psycopg": self.psycopg, "geoalchemy": self.geoalchemy}[kind]
        except KeyError:
            raise KeyError(f"unknown snippet kind {kind!r}") from None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping."""
        return {
            "sql": self.sql,
            "result": self.result,
            "psycopg": self.psycopg,
            "geoalchemy": self.geoalchemy,
        }


@dataclass(frozen=True, slots=True)
class IndexUsage:
    """How (and whether) a function participates in GiST index access.

    :param gist: ``True`` when the planner can answer the call with a GiST index scan.
    :param sargable: ``True`` when the call is index-searchable as written, i.e. it does
        not have to be rewritten or prefixed with a separate bounding-box test.
    :param needs_bbox_prefilter: ``True`` when you must add an explicit ``&&`` term
        to get index access.
    :param notes: free-text explanation shown on the card.
    """

    gist: bool
    sargable: bool
    needs_bbox_prefilter: bool
    notes: str

    @classmethod
    def from_dict(cls, raw: Any, *, source: str | None = None) -> "IndexUsage":
        """Build an :class:`IndexUsage` from a parsed YAML mapping."""
        if not isinstance(raw, Mapping):
            raise SchemaError("field 'index_usage' must be a mapping", source=source)
        known = ("gist", "sargable", "needs_bbox_prefilter", "notes")
        _reject_unknown(raw, known, source=source)
        flags: dict[str, bool] = {}
        for key in known[:3]:
            if key not in raw:
                raise SchemaError(f"index_usage is missing {key!r}", source=source)
            value = raw[key]
            if not isinstance(value, bool):
                raise SchemaError(f"index_usage.{key} must be a boolean", source=source)
            flags[key] = value
        return cls(notes=_require_text(raw, "notes", source=source), **flags)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping."""
        return {
            "gist": self.gist,
            "sargable": self.sargable,
            "needs_bbox_prefilter": self.needs_bbox_prefilter,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class FunctionEntry:
    """A single ``ST_*`` function or spatial operator."""

    name: str
    category: str
    signatures: list[str]
    summary: str
    returns: str
    since: str
    arguments: list[Argument]
    example: Example
    srid_notes: str
    index_usage: IndexUsage
    common_mistakes: list[str]
    see_also: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    docs_url: str | None = None

    #: Fields accepted in a YAML document, in schema order.
    YAML_FIELDS = (
        "name",
        "category",
        "signatures",
        "summary",
        "returns",
        "since",
        "arguments",
        "example",
        "srid_notes",
        "index_usage",
        "common_mistakes",
        "see_also",
        "tags",
        "docs_url",
    )

    @classmethod
    def from_dict(cls, raw: Any, *, source: str | None = None) -> "FunctionEntry":
        """Build a :class:`FunctionEntry` from a parsed YAML mapping.

        :raises SchemaError: if any required field is missing or ill-typed.
        """
        if not isinstance(raw, Mapping):
            raise SchemaError("entry must be a mapping", source=source)
        _reject_unknown(raw, cls.YAML_FIELDS, source=source)

        name = _require_text(raw, "name", source=source)
        # Once the name is known, prefer it in error messages over a bare file path.
        source = f"{source} [{name}]" if source else name

        category = _require_text(raw, "category", source=source)
        if category not in CATEGORY_DESCRIPTIONS:
            valid = ", ".join(CATEGORIES)
            raise SchemaError(f"unknown category {category!r} (expected one of: {valid})", source=source)

        arguments_raw = raw.get("arguments", [])
        if not isinstance(arguments_raw, list):
            raise SchemaError("field 'arguments' must be a list", source=source)

        docs_url = raw.get("docs_url")
        if docs_url is not None:
            if not isinstance(docs_url, str) or not docs_url.startswith("https://"):
                raise SchemaError("field 'docs_url' must be an https:// string", source=source)

        return cls(
            name=name,
            category=category,
            signatures=_string_list(raw, "signatures", source=source, minimum=1),
            summary=_require_text(raw, "summary", source=source),
            returns=_require_text(raw, "returns", source=source),
            since=_require_text(raw, "since", source=source),
            arguments=[Argument.from_dict(item, source=source) for item in arguments_raw],
            example=Example.from_dict(_require(raw, "example", dict, source=source), source=source),
            srid_notes=_require_text(raw, "srid_notes", source=source),
            index_usage=IndexUsage.from_dict(
                _require(raw, "index_usage", dict, source=source), source=source
            ),
            common_mistakes=_string_list(raw, "common_mistakes", source=source, minimum=2),
            see_also=_string_list(raw, "see_also", source=source),
            tags=_string_list(raw, "tags", source=source),
            docs_url=docs_url,
        )

    @property
    def slug(self) -> str:
        """URL fragment identifying this entry on the generated page."""
        return slugify(self.name)

    @property
    def search_text(self) -> str:
        """Lower-cased haystack used by substring and fuzzy search."""
        return " ".join([self.name, self.summary, *self.tags, self.category]).lower()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping (used by ``export`` and the builder)."""
        return {
            "name": self.name,
            "slug": self.slug,
            "category": self.category,
            "signatures": list(self.signatures),
            "summary": self.summary,
            "returns": self.returns,
            "since": self.since,
            "arguments": [argument.to_dict() for argument in self.arguments],
            "example": self.example.to_dict(),
            "srid_notes": self.srid_notes,
            "index_usage": self.index_usage.to_dict(),
            "common_mistakes": list(self.common_mistakes),
            "see_also": list(self.see_also),
            "tags": list(self.tags),
            "docs_url": self.docs_url,
        }


def slugify(name: str) -> str:
    """Return a fragment-safe slug for a function or operator name.

    Operators have no alphanumerics at all, so their characters are spelled out::

        >>> slugify("ST_DWithin")
        'st_dwithin'
        >>> slugify("<->")
        'op-lt-minus-gt'
    """
    lowered = name.strip().lower()
    if lowered.replace("_", "").isalnum():
        return lowered
    spelling = {
        "<": "lt",
        ">": "gt",
        "-": "minus",
        "#": "hash",
        "&": "amp",
        "=": "eq",
        "|": "pipe",
        "~": "tilde",
        "@": "at",
        "!": "bang",
    }
    # Unlisted punctuation falls back to its code point, so distinct names can never
    # collapse onto the same fragment.
    parts = [spelling.get(char, f"c{ord(char)}") for char in lowered]
    return "op-" + "-".join(parts)

