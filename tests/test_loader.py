"""Loader and cross-entry validation tests, including the full shipped dataset."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from st_cheatsheet.loader import Dataset, DatasetError, load_dataset, load_validated, validate_dataset
from st_cheatsheet.model import CATEGORIES, SchemaError

from .conftest import entry_dict, make_entry


def write_yaml(directory: Path, name: str, entries: list[dict]) -> Path:
    """Write ``entries`` as a YAML list into ``directory/name``."""
    path = directory / name
    path.write_text(yaml.safe_dump(entries, sort_keys=False), encoding="utf-8")
    return path


class TestLoading:
    def test_loads_entries_from_multiple_files(self, data_dir: Path) -> None:
        write_yaml(data_dir, "a.yaml", [entry_dict(name="ST_Area")])
        write_yaml(data_dir, "b.yaml", [entry_dict(name="ST_Buffer", category="processing")])
        dataset = load_dataset(data_dir)
        assert {entry.name for entry in dataset} == {"ST_Area", "ST_Buffer"}

    def test_entries_are_sorted_by_category_then_name(self, data_dir: Path) -> None:
        write_yaml(
            data_dir,
            "mixed.yaml",
            [
                entry_dict(name="ST_Zed", category="processing"),
                entry_dict(name="&&", category="operators"),
                entry_dict(name="ST_Alpha", category="processing"),
                entry_dict(name="ST_SRID", category="accessors"),
            ],
        )
        names = [entry.name for entry in load_dataset(data_dir)]
        # accessors < processing < operators in CATEGORIES order.
        assert names == ["ST_SRID", "ST_Alpha", "ST_Zed", "&&"]

    def test_empty_yaml_file_is_tolerated(self, data_dir: Path) -> None:
        (data_dir / "empty.yaml").write_text("", encoding="utf-8")
        write_yaml(data_dir, "real.yaml", [entry_dict()])
        assert len(load_dataset(data_dir)) == 1

    def test_missing_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(DatasetError, match="dataset directory not found"):
            load_dataset(tmp_path / "nope")

    def test_directory_without_yaml_raises(self, data_dir: Path) -> None:
        with pytest.raises(DatasetError, match="no \\*.yaml files"):
            load_dataset(data_dir)

    def test_malformed_yaml_raises(self, data_dir: Path) -> None:
        (data_dir / "bad.yaml").write_text("- name: [unclosed\n", encoding="utf-8")
        with pytest.raises(DatasetError, match="invalid YAML"):
            load_dataset(data_dir)

    def test_non_list_document_raises(self, data_dir: Path) -> None:
        (data_dir / "bad.yaml").write_text("name: ST_Area\n", encoding="utf-8")
        with pytest.raises(DatasetError, match="expected a top-level list"):
            load_dataset(data_dir)

    def test_schema_error_names_the_offending_file(self, data_dir: Path) -> None:
        raw = entry_dict()
        del raw["returns"]
        write_yaml(data_dir, "broken.yaml", [entry_dict(), raw])
        with pytest.raises(SchemaError, match="broken.yaml#1"):
            load_dataset(data_dir)


class TestDatasetOperations:
    def test_get_is_case_insensitive(self, tiny_dataset: Dataset) -> None:
        assert tiny_dataset.get("st_dwithin") is tiny_dataset.get("ST_DWithin")
        assert tiny_dataset.get("  ST_UNION  ").name == "ST_Union"

    def test_get_returns_none_for_unknown(self, tiny_dataset: Dataset) -> None:
        assert tiny_dataset.get("ST_Nope") is None

    def test_filter_by_category(self, tiny_dataset: Dataset) -> None:
        filtered = tiny_dataset.filter(category="processing")
        assert {entry.name for entry in filtered} == {"ST_Buffer", "ST_Union"}

    def test_filter_index_only_drops_non_gist_entries(self, tiny_dataset: Dataset) -> None:
        filtered = tiny_dataset.filter(index_only=True)
        assert "ST_Union" not in {entry.name for entry in filtered}
        assert all(entry.index_usage.gist for entry in filtered)

    def test_filters_compose(self, tiny_dataset: Dataset) -> None:
        filtered = tiny_dataset.filter(category="processing", index_only=True)
        assert [entry.name for entry in filtered] == ["ST_Buffer"]

    def test_categories_counts_in_canonical_order(self, tiny_dataset: Dataset) -> None:
        counts = tiny_dataset.categories()
        assert counts == {"relationships": 1, "processing": 2, "operators": 1}
        assert list(counts) == [c for c in CATEGORIES if c in counts]


class TestCrossEntryValidation:
    def test_clean_dataset_has_no_problems(self, tiny_dataset: Dataset) -> None:
        assert validate_dataset(tiny_dataset) == []

    def test_duplicate_names_are_reported(self) -> None:
        dataset = Dataset((make_entry(name="ST_Area"), make_entry(name="st_area")))
        problems = validate_dataset(dataset)
        assert any("duplicate entry name 'st_area'" in problem for problem in problems)

    def test_dangling_see_also_is_reported(self) -> None:
        dataset = Dataset((make_entry(name="ST_Area", see_also=["ST_Ghost"]),))
        problems = validate_dataset(dataset)
        assert problems == ["ST_Area: see_also references unknown entry 'ST_Ghost'"]

    def test_self_reference_is_reported(self) -> None:
        dataset = Dataset((make_entry(name="ST_Area", see_also=["ST_Area"]),))
        assert validate_dataset(dataset) == ["ST_Area: see_also references itself"]

    def test_load_validated_returns_both(self, data_dir: Path) -> None:
        write_yaml(data_dir, "x.yaml", [entry_dict(name="ST_Area", see_also=["ST_Nope"])])
        dataset, problems = load_validated(data_dir)
        assert len(dataset) == 1
        assert len(problems) == 1


class TestShippedDataset:
    """The real dataset is a first-class test subject: bad data must fail CI."""

    def test_it_loads_and_validates(self, real_dataset: Dataset) -> None:
        assert validate_dataset(real_dataset) == []

    def test_it_covers_at_least_sixty_functions(self, real_dataset: Dataset) -> None:
        assert len(real_dataset) >= 60

    @pytest.mark.parametrize(
        "name",
        [
            "&&", "<->", "<#>",
            "ST_DWithin", "ST_Intersects", "ST_Contains", "ST_Within", "ST_Covers",
            "ST_Distance", "ST_DistanceSphere", "ST_Transform", "ST_SetSRID",
            "ST_MakePoint", "ST_GeomFromText", "ST_GeomFromGeoJSON", "ST_AsGeoJSON",
            "ST_AsMVT", "ST_Buffer", "ST_Simplify", "ST_SimplifyPreserveTopology",
            "ST_Union", "ST_Collect", "ST_Subdivide", "ST_ClusterDBSCAN", "ST_Area",
            "ST_Length", "ST_Centroid", "ST_PointOnSurface", "ST_IsValid", "ST_MakeValid",
            "ST_ClosestPoint", "ST_LineLocatePoint", "ST_Segmentize", "ST_Expand",
            "ST_Envelope",
        ],
    )
    def test_required_entries_are_present(self, real_dataset: Dataset, name: str) -> None:
        assert real_dataset.get(name) is not None, f"{name} missing from the dataset"

    def test_every_category_is_populated(self, real_dataset: Dataset) -> None:
        assert set(real_dataset.categories()) == set(CATEGORIES)

    def test_slugs_are_unique(self, real_dataset: Dataset) -> None:
        slugs = [entry.slug for entry in real_dataset]
        assert len(slugs) == len(set(slugs))

    def test_docs_urls_point_at_the_documented_site(self, real_dataset: Dataset) -> None:
        for entry in real_dataset:
            if entry.docs_url is not None:
                assert entry.docs_url.startswith("https://www.postgis-python.com/")

    def test_sql_examples_look_like_sql(self, real_dataset: Dataset) -> None:
        for entry in real_dataset:
            upper = entry.example.sql.upper()
            assert "SELECT" in upper or "CREATE" in upper, entry.name

    def test_python_snippets_are_syntactically_valid(self, real_dataset: Dataset) -> None:
        import textwrap

        for entry in real_dataset:
            for kind in ("psycopg", "geoalchemy"):
                source = textwrap.dedent(entry.example.snippet(kind))
                try:
                    compile(source, f"<{entry.name}:{kind}>", "exec")
                except SyntaxError as exc:  # pragma: no cover - failure path
                    pytest.fail(f"{entry.name} {kind} snippet does not parse: {exc}")

    def test_index_flags_are_internally_consistent(self, real_dataset: Dataset) -> None:
        for entry in real_dataset:
            usage = entry.index_usage
            if not usage.gist:
                assert not usage.sargable, f"{entry.name}: sargable without GiST support"

    def test_summaries_are_substantial(self, real_dataset: Dataset) -> None:
        for entry in real_dataset:
            assert len(entry.summary.split()) >= 25, f"{entry.name} summary is too thin"
