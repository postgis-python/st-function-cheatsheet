"""Ranked search over the cheatsheet dataset.

Scoring is deliberately simple and explainable rather than statistical: an exact
name match always wins, then name prefix, then name substring, then tag hits, then
summary hits, with a fuzzy similarity fallback so that typos ("ST_Bufer") still
find their target. Ties break on name length, so ``ST_Union`` outranks
``ST_UnaryUnion`` for the query ``union``.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Sequence

from .loader import Dataset
from .model import FunctionEntry

__all__ = ["SearchResult", "search", "fuzzy_ratio"]

# Score bands. The gaps are wide enough that no combination of lower-band bonuses
# can promote a result past a higher band.
_SCORE_EXACT = 1000.0
_SCORE_NAME_PREFIX = 700.0
_SCORE_NAME_SUBSTRING = 500.0
_SCORE_TAG_EXACT = 400.0
_SCORE_TAG_SUBSTRING = 300.0
_SCORE_SUMMARY = 200.0
_SCORE_FUZZY_BASE = 100.0

#: Minimum similarity for a fuzzy name match to count as a hit at all.
FUZZY_THRESHOLD = 0.62


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One scored hit, with the reason it matched."""

    entry: FunctionEntry
    score: float
    reason: str


def fuzzy_ratio(query: str, candidate: str) -> float:
    """Return a 0..1 similarity between two strings, ignoring case.

    Also tolerates the common habit of omitting the ``st_`` prefix, so that
    ``dwithin`` scores highly against ``st_dwithin``.
    """
    left, right = query.lower(), candidate.lower()
    direct = SequenceMatcher(None, left, right).ratio()
    if right.startswith("st_"):
        stripped = SequenceMatcher(None, left, right[3:]).ratio()
        return max(direct, stripped)
    return direct


def _score(entry: FunctionEntry, query: str) -> tuple[float, str] | None:
    """Score one entry against a normalised (lower-case, stripped) query."""
    name = entry.name.lower()
    bare = name[3:] if name.startswith("st_") else name

    if query in (name, bare):
        return _SCORE_EXACT, "exact name"
    if name.startswith(query) or bare.startswith(query):
        return _SCORE_NAME_PREFIX, "name prefix"
    if query in name:
        return _SCORE_NAME_SUBSTRING, "name substring"

    tags = [tag.lower() for tag in entry.tags]
    if query in tags:
        return _SCORE_TAG_EXACT, "tag"
    if any(query in tag for tag in tags):
        return _SCORE_TAG_SUBSTRING, "tag substring"

    if query in entry.summary.lower():
        return _SCORE_SUMMARY, "summary"

    ratio = fuzzy_ratio(query, name)
    if ratio >= FUZZY_THRESHOLD:
        return _SCORE_FUZZY_BASE * ratio, f"fuzzy name ({ratio:.0%})"
    return None


def search(
    entries: Dataset | Iterable[FunctionEntry],
    query: str,
    *,
    limit: int | None = None,
) -> list[SearchResult]:
    """Return ranked matches for ``query``, best first.

    An empty or whitespace-only query returns every entry unranked (score 0), which
    makes ``search(dataset, "")`` a convenient "list everything" call.

    :param limit: maximum number of results; ``None`` means unlimited.
    """
    candidates: Sequence[FunctionEntry] = tuple(entries)
    normalised = query.strip().lower()
    if not normalised:
        results = [SearchResult(entry, 0.0, "all") for entry in candidates]
        return results[:limit] if limit is not None else results

    hits: list[SearchResult] = []
    for entry in candidates:
        scored = _score(entry, normalised)
        if scored is not None:
            score, reason = scored
            hits.append(SearchResult(entry, score, reason))

    hits.sort(key=lambda hit: (-hit.score, len(hit.entry.name), hit.entry.name.lower()))
    return hits[:limit] if limit is not None else hits
