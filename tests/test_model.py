"""Schema-level tests for :mod:`st_cheatsheet.model`."""

from __future__ import annotations

import pytest

from st_cheatsheet.model import Argument, Example, FunctionEntry, IndexUsage, SchemaError, slugify

from .conftest import entry_dict, make_entry


class TestFunctionEntry:
    def test_parses_a_complete_entry(self) -> None:
        entry = make_entry()
        assert entry.name == "ST_Example"
        assert entry.arguments[0].name == "a"
        assert entry.arguments[0].optional is False
        assert entry.index_usage.gist is True
        assert entry.docs_url is None

    @pytest.mark.parametrize(
        "field",
        ["name", "category", "signatures", "summary", "returns", "since", "example",
         "srid_notes", "index_usage", "common_mistakes"],
    )
    def test_missing_required_field_raises(self, field: str) -> None:
        raw = entry_dict()
        del raw[field]
        with pytest.raises(SchemaError, match=field):
            FunctionEntry.from_dict(raw)

    def test_unknown_field_is_rejected(self) -> None:
        with pytest.raises(SchemaError, match="unknown field"):
            FunctionEntry.from_dict(entry_dict(retruns="oops"))

    def test_unknown_category_is_rejected(self) -> None:
        with pytest.raises(SchemaError, match="unknown category 'raster'"):
            FunctionEntry.from_dict(entry_dict(category="raster"))

    def test_blank_summary_is_rejected(self) -> None:
        with pytest.raises(SchemaError, match="must not be empty"):
            FunctionEntry.from_dict(entry_dict(summary="   "))

    def test_signatures_must_be_non_empty(self) -> None:
        with pytest.raises(SchemaError, match="at least 1"):
            FunctionEntry.from_dict(entry_dict(signatures=[]))

    def test_at_least_two_common_mistakes_are_required(self) -> None:
        with pytest.raises(SchemaError, match="at least 2"):
            FunctionEntry.from_dict(entry_dict(common_mistakes=["only one"]))

    def test_wrong_type_is_reported_with_the_expected_type(self) -> None:
        with pytest.raises(SchemaError, match="must be str, got int"):
            FunctionEntry.from_dict(entry_dict(summary=12))

    def test_non_https_docs_url_is_rejected(self) -> None:
        with pytest.raises(SchemaError, match="docs_url"):
            FunctionEntry.from_dict(entry_dict(docs_url="http://example.com/"))

    def test_error_message_includes_source_and_name(self) -> None:
        with pytest.raises(SchemaError) as excinfo:
            FunctionEntry.from_dict(entry_dict(since=None), source="measurement.yaml#3")
        message = str(excinfo.value)
        assert "measurement.yaml#3" in message
        assert "ST_Example" in message

    def test_entry_must_be_a_mapping(self) -> None:
        with pytest.raises(SchemaError, match="must be a mapping"):
            FunctionEntry.from_dict(["not", "a", "mapping"])

    def test_to_dict_roundtrips_through_from_dict(self) -> None:
        entry = make_entry(docs_url="https://www.postgis-python.com/", see_also=["ST_Area"])
        rebuilt = FunctionEntry.from_dict(
            {key: value for key, value in entry.to_dict().items() if key != "slug"}
        )
        assert rebuilt == entry

    def test_search_text_is_lowercased_and_includes_tags(self) -> None:
        entry = make_entry(tags=["Radius", "PROXIMITY"])
        assert "radius" in entry.search_text
        assert "proximity" in entry.search_text
        assert entry.search_text == entry.search_text.lower()


class TestArgument:
    def test_optional_flag_must_be_boolean(self) -> None:
        raw = entry_dict()
        raw["arguments"][0]["optional"] = "yes"
        with pytest.raises(SchemaError, match="must be a boolean"):
            FunctionEntry.from_dict(raw)

    def test_unknown_argument_key_is_rejected(self) -> None:
        with pytest.raises(SchemaError, match="unknown field"):
            Argument.from_dict({"name": "a", "type": "geometry", "description": "d", "dflt": 1})

    def test_argument_must_be_a_mapping(self) -> None:
        with pytest.raises(SchemaError, match="must be a mapping"):
            Argument.from_dict("geometry a")


class TestExample:
    def test_snippet_returns_each_kind(self) -> None:
        example = make_entry().example
        assert example.snippet("sql").startswith("SELECT")
        assert "cur.execute" in example.snippet("psycopg")
        assert "select(" in example.snippet("geoalchemy")

    def test_unknown_snippet_kind_raises_keyerror(self) -> None:
        with pytest.raises(KeyError, match="unknown snippet kind"):
            make_entry().example.snippet("bash")

    def test_missing_result_is_rejected(self) -> None:
        raw = entry_dict()
        del raw["example"]["result"]
        with pytest.raises(SchemaError, match="result"):
            FunctionEntry.from_dict(raw)

    def test_leading_whitespace_is_preserved_in_results(self) -> None:
        """psql aligns the header over its column; stripping it corrupts the layout."""
        raw = entry_dict()
        raw["example"]["result"] = "     d\n-------\n 5.000\n"
        entry = FunctionEntry.from_dict(raw)
        assert entry.example.result == "     d\n-------\n 5.000"

    def test_snippet_indentation_is_preserved(self) -> None:
        raw = entry_dict()
        raw["example"]["psycopg"] = "with conn.cursor() as cur:\n    cur.execute(sql)\n"
        assert FunctionEntry.from_dict(raw).example.psycopg.endswith("    cur.execute(sql)")

    def test_whitespace_only_example_field_is_still_rejected(self) -> None:
        raw = entry_dict()
        raw["example"]["result"] = "   \n  \n"
        with pytest.raises(SchemaError, match="must not be empty"):
            FunctionEntry.from_dict(raw)

    def test_example_must_be_a_mapping(self) -> None:
        with pytest.raises(SchemaError, match="must be dict"):
            FunctionEntry.from_dict(entry_dict(example="SELECT 1"))


class TestIndexUsage:
    def test_flags_must_be_boolean(self) -> None:
        raw = entry_dict()
        raw["index_usage"]["gist"] = "true"
        with pytest.raises(SchemaError, match="index_usage.gist must be a boolean"):
            FunctionEntry.from_dict(raw)

    def test_missing_flag_is_reported(self) -> None:
        raw = entry_dict()
        del raw["index_usage"]["sargable"]
        with pytest.raises(SchemaError, match="missing 'sargable'"):
            FunctionEntry.from_dict(raw)

    def test_to_dict_is_complete(self) -> None:
        usage = IndexUsage(gist=True, sargable=False, needs_bbox_prefilter=True, notes="n")
        assert usage.to_dict() == {
            "gist": True,
            "sargable": False,
            "needs_bbox_prefilter": True,
            "notes": "n",
        }


class TestSlugify:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("ST_DWithin", "st_dwithin"),
            ("ST_AsMVT", "st_asmvt"),
            ("PostGIS_Full_Version", "postgis_full_version"),
            ("&&", "op-amp-amp"),
            ("<->", "op-lt-minus-gt"),
            ("<#>", "op-lt-hash-gt"),
            ("~", "op-tilde"),
            ("@", "op-at"),
        ],
    )
    def test_known_slugs(self, name: str, expected: str) -> None:
        assert slugify(name) == expected

    def test_operators_with_distinct_spellings_get_distinct_slugs(self) -> None:
        assert slugify("&&") != slugify("&&&")

    def test_entry_slug_matches_slugify(self) -> None:
        entry = make_entry(name="ST_MakeValid")
        assert entry.slug == slugify("ST_MakeValid") == "st_makevalid"


def test_example_dataclasses_are_frozen() -> None:
    example = Example(sql="a", result="b", psycopg="c", geoalchemy="d")
    with pytest.raises(AttributeError):
        example.sql = "changed"  # type: ignore[misc]
