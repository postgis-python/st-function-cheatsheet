"""CLI behaviour and exit codes."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from st_cheatsheet.cli import EXIT_DATASET, EXIT_NO_RESULTS, EXIT_OK, main
from st_cheatsheet.cli import _normalise_argv

from .conftest import REPO_ROOT, entry_dict
from .test_loader import write_yaml

BASE = ["--no-color", "--width", "120"]


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str]:
    """Invoke the CLI in-process and return ``(exit_code, stdout)``."""
    code = main([*BASE, *args])
    return code, capsys.readouterr().out


class TestArgvNormalisation:
    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            (["dwithin"], ["search", "dwithin"]),
            (["search", "dwithin"], ["search", "dwithin"]),
            (["show", "ST_Area"], ["show", "ST_Area"]),
            (["--no-color", "buffer"], ["--no-color", "search", "buffer"]),
            (["--version"], ["--version"]),
            ([], []),
            (["list"], ["list"]),
        ],
    )
    def test_bare_query_gets_an_implicit_search(self, argv: list[str], expected: list[str]) -> None:
        assert _normalise_argv(argv) == expected


class TestSearchCommand:
    def test_bare_query_finds_a_function(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = run(capsys, "dwithin")
        assert code == EXIT_OK
        assert "ST_DWithin" in out

    def test_no_match_exits_one(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = run(capsys, "search", "zzzqqqnothing")
        assert code == EXIT_NO_RESULTS
        assert "No matches" in out

    def test_category_filter_restricts_results(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = run(capsys, "search", "st_", "--category", "output", "--limit", "50")
        assert code == EXIT_OK
        assert "ST_AsGeoJSON" in out
        assert "ST_Buffer" not in out

    def test_index_only_excludes_non_indexable_functions(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = run(capsys, "search", "", "--index-only", "--limit", "200")
        assert code == EXIT_OK
        assert "ST_DWithin" in out

    def test_invalid_category_is_a_usage_error(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            main([*BASE, "search", "x", "--category", "raster"])
        assert excinfo.value.code == 2


class TestShowCommand:
    def test_renders_a_full_card(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = run(capsys, "show", "ST_DWithin")
        assert code == EXIT_OK
        for section in ("Summary", "SRID notes", "Index usage", "Common mistakes", "GeoAlchemy2"):
            assert section in out

    def test_name_lookup_is_case_insensitive(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert run(capsys, "show", "st_dwithin")[0] == EXIT_OK

    def test_operator_lookup_works(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = run(capsys, "show", "&&")
        assert code == EXIT_OK
        assert "bounding box" in out.lower()

    def test_unknown_name_exits_one_and_suggests(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = run(capsys, "show", "ST_DWithinn")
        assert code == EXIT_NO_RESULTS
        assert "did you mean" in out
        assert "ST_DWithin" in out

    @pytest.mark.parametrize("kind", ["sql", "psycopg", "geoalchemy"])
    def test_snippet_prints_only_the_snippet(
        self, capsys: pytest.CaptureFixture[str], kind: str, real_dataset
    ) -> None:
        code, out = run(capsys, "show", "ST_DWithin", "--snippet", kind)
        assert code == EXIT_OK
        expected = real_dataset.get("ST_DWithin").example.snippet(kind).rstrip()
        assert out.strip("\n") == expected
        assert "Summary" not in out

    def test_invalid_snippet_kind_is_a_usage_error(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            main([*BASE, "show", "ST_Area", "--snippet", "bash"])
        assert excinfo.value.code == 2


class TestListAndCategories:
    def test_list_shows_every_entry(self, capsys: pytest.CaptureFixture[str], real_dataset) -> None:
        code, out = run(capsys, "list")
        assert code == EXIT_OK
        assert f"{len(real_dataset)} entries" in out

    def test_list_respects_filters(self, capsys: pytest.CaptureFixture[str], real_dataset) -> None:
        _, out = run(capsys, "list", "--category", "operators")
        expected = len(real_dataset.filter(category="operators"))
        assert f"{expected} entries" in out

    def test_categories_lists_all_categories(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = run(capsys, "categories")
        assert code == EXIT_OK
        assert "relationships" in out and "operators" in out


class TestValidateCommand:
    def test_real_dataset_validates(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = run(capsys, "validate")
        assert code == EXIT_OK
        assert "dataset is valid" in out

    def test_broken_dataset_exits_one(self, capsys: pytest.CaptureFixture[str], data_dir: Path) -> None:
        write_yaml(data_dir, "x.yaml", [entry_dict(name="ST_Area", see_also=["ST_Ghost"])])
        code, out = run(capsys, "--data-dir", str(data_dir), "validate")
        assert code == EXIT_NO_RESULTS
        assert "ST_Ghost" in out

    def test_unparseable_dataset_exits_three(
        self, capsys: pytest.CaptureFixture[str], data_dir: Path
    ) -> None:
        (data_dir / "bad.yaml").write_text("- name: [unclosed\n", encoding="utf-8")
        code, out = run(capsys, "--data-dir", str(data_dir), "validate")
        assert code == EXIT_DATASET
        assert "invalid YAML" in out

    def test_missing_data_dir_exits_three(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        code, out = run(capsys, "--data-dir", str(tmp_path / "gone"), "list")
        assert code == EXIT_DATASET
        assert "not found" in out


class TestBuildCommand:
    def test_builds_a_single_file(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        code, out = run(capsys, "build", "--out", str(tmp_path / "dist"))
        assert code == EXIT_OK
        produced = list((tmp_path / "dist").iterdir())
        assert [path.name for path in produced] == ["index.html"]
        assert "no external requests" in " ".join(out.split())

    def test_refuses_to_build_an_invalid_dataset(
        self, capsys: pytest.CaptureFixture[str], data_dir: Path, tmp_path: Path
    ) -> None:
        write_yaml(data_dir, "x.yaml", [entry_dict(name="ST_Area", see_also=["ST_Ghost"])])
        code, out = run(capsys, "--data-dir", str(data_dir), "build", "--out", str(tmp_path / "d"))
        assert code == EXIT_NO_RESULTS
        assert "refusing to build" in out
        assert not (tmp_path / "d").exists()


class TestExportCommand:
    def test_json_to_stdout_parses(self, capsys: pytest.CaptureFixture[str], real_dataset) -> None:
        code, out = run(capsys, "export", "--format", "json")
        assert code == EXIT_OK
        document = json.loads(out)
        assert document["count"] == len(real_dataset)
        assert document["functions"][0]["name"]

    def test_ndjson_yields_one_object_per_line(self, capsys: pytest.CaptureFixture[str], real_dataset) -> None:
        code, out = run(capsys, "export", "--format", "ndjson")
        assert code == EXIT_OK
        lines = [line for line in out.splitlines() if line.strip()]
        assert len(lines) == len(real_dataset)
        assert json.loads(lines[0])["name"]

    def test_filters_apply_to_export(self, capsys: pytest.CaptureFixture[str], real_dataset) -> None:
        code, out = run(capsys, "export", "--category", "operators")
        assert code == EXIT_OK
        assert json.loads(out)["count"] == len(real_dataset.filter(category="operators"))

    def test_export_to_file(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        target = tmp_path / "nested" / "out.json"
        code, out = run(capsys, "export", "--out", str(target))
        assert code == EXIT_OK
        assert json.loads(target.read_text(encoding="utf-8"))["count"] > 0
        assert "wrote" in out

    def test_unwritable_export_target_exits_three(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        blocker = tmp_path / "blocked"
        blocker.write_text("file", encoding="utf-8")
        code, out = run(capsys, "export", "--out", str(blocker / "out.json"))
        assert code == EXIT_DATASET
        assert "cannot write" in out


class TestProcessInvocation:
    """A couple of real subprocess runs, to prove `python -m st_cheatsheet` works."""

    def test_module_entry_point_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "st_cheatsheet", "--no-color", "show", "ST_Transform"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == EXIT_OK, result.stderr
        assert "ST_Transform" in result.stdout

    def test_module_entry_point_propagates_failure(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "st_cheatsheet", "--no-color", "zzzqqqnothing"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == EXIT_NO_RESULTS

    def test_no_command_prints_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = run(capsys)
        assert code == EXIT_OK
        assert "usage:" in out
