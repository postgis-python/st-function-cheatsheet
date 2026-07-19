"""Ranking behaviour of :mod:`st_cheatsheet.search`."""

from __future__ import annotations

import pytest

from st_cheatsheet.loader import Dataset
from st_cheatsheet.search import FUZZY_THRESHOLD, fuzzy_ratio, search

from .conftest import make_entry


def names(results) -> list[str]:
    """Return just the entry names of a result list, in rank order."""
    return [result.entry.name for result in results]


class TestRanking:
    def test_exact_name_wins(self, tiny_dataset: Dataset) -> None:
        results = search(tiny_dataset, "ST_Union")
        assert names(results)[0] == "ST_Union"
        assert results[0].reason == "exact name"

    def test_exact_match_ignores_case(self, tiny_dataset: Dataset) -> None:
        assert names(search(tiny_dataset, "st_buffer"))[0] == "ST_Buffer"

    def test_st_prefix_may_be_omitted(self, tiny_dataset: Dataset) -> None:
        results = search(tiny_dataset, "dwithin")
        assert names(results)[0] == "ST_DWithin"
        assert results[0].reason == "exact name"

    def test_prefix_outranks_substring(self) -> None:
        dataset = Dataset(
            (
                make_entry(name="ST_MakeValid", category="editors"),
                make_entry(name="ST_RemoveRepeatedPoints", category="editors", tags=["make"]),
            )
        )
        assert names(search(dataset, "make"))[0] == "ST_MakeValid"

    def test_shorter_name_breaks_a_tie(self) -> None:
        dataset = Dataset(
            (
                make_entry(name="ST_SimplifyPreserveTopology", category="processing"),
                make_entry(name="ST_Simplify", category="processing"),
            )
        )
        assert names(search(dataset, "simplify")) == ["ST_Simplify", "ST_SimplifyPreserveTopology"]

    def test_tag_match_ranks_below_name_match(self, tiny_dataset: Dataset) -> None:
        dataset = Dataset(
            (
                make_entry(name="ST_Buffer", category="processing"),
                make_entry(name="ST_Expand", category="processing", tags=["buffer"]),
            )
        )
        assert names(search(dataset, "buffer")) == ["ST_Buffer", "ST_Expand"]

    def test_summary_match_is_found(self, tiny_dataset: Dataset) -> None:
        results = search(tiny_dataset, "dissolved")
        assert names(results) == ["ST_Union"]
        assert results[0].reason == "summary"

    def test_typo_still_finds_the_function(self, tiny_dataset: Dataset) -> None:
        results = search(tiny_dataset, "buffr")
        assert names(results)[0] == "ST_Buffer"
        assert results[0].reason.startswith("fuzzy")

    def test_nonsense_query_returns_nothing(self, tiny_dataset: Dataset) -> None:
        assert search(tiny_dataset, "zzzqqqxxx") == []

    def test_operator_names_are_searchable(self, tiny_dataset: Dataset) -> None:
        assert names(search(tiny_dataset, "&&")) == ["&&"]

    def test_empty_query_returns_everything(self, tiny_dataset: Dataset) -> None:
        results = search(tiny_dataset, "   ")
        assert len(results) == len(tiny_dataset)
        assert all(result.score == 0.0 for result in results)

    def test_limit_truncates(self, tiny_dataset: Dataset) -> None:
        assert len(search(tiny_dataset, "", limit=2)) == 2
        assert len(search(tiny_dataset, "st_", limit=1)) == 1

    def test_scores_are_monotonically_non_increasing(self, tiny_dataset: Dataset) -> None:
        scores = [result.score for result in search(tiny_dataset, "st")]
        assert scores == sorted(scores, reverse=True)

    def test_search_accepts_a_plain_iterable(self, tiny_dataset: Dataset) -> None:
        results = search(list(tiny_dataset), "union")
        assert names(results) == ["ST_Union"]


class TestFuzzyRatio:
    @pytest.mark.parametrize(
        ("query", "candidate"),
        [("dwithin", "st_dwithin"), ("bufer", "st_buffer"), ("centroid", "st_centroid")],
    )
    def test_close_spellings_clear_the_threshold(self, query: str, candidate: str) -> None:
        assert fuzzy_ratio(query, candidate) >= FUZZY_THRESHOLD

    def test_identical_strings_score_one(self) -> None:
        assert fuzzy_ratio("ST_Area", "st_area") == pytest.approx(1.0)

    def test_unrelated_strings_score_low(self) -> None:
        assert fuzzy_ratio("qqqq", "st_transform") < FUZZY_THRESHOLD


class TestAgainstRealData:
    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("dwithin", "ST_DWithin"),
            ("transform", "ST_Transform"),
            ("makevalid", "ST_MakeValid"),
            ("asgeojson", "ST_AsGeoJSON"),
            ("centroid", "ST_Centroid"),
        ],
    )
    def test_common_lookups_hit_first(self, real_dataset: Dataset, query: str, expected: str) -> None:
        assert names(search(real_dataset, query))[0] == expected

    def test_topic_query_surfaces_relevant_entries(self, real_dataset: Dataset) -> None:
        found = names(search(real_dataset, "knn"))
        assert "<->" in found
