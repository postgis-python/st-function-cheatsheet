"""Shared fixtures.

Two kinds of dataset are used across the suite:

* ``real_dataset`` - the actual shipped YAML, so that bad data fails CI;
* ``tiny_dataset`` / :func:`make_entry` - hand-built entries for behaviour tests that
  should not change every time a function is added to the reference.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from st_cheatsheet.loader import DEFAULT_DATA_DIR, Dataset, load_dataset
from st_cheatsheet.model import FunctionEntry

REPO_ROOT = Path(__file__).resolve().parent.parent

#: A complete, schema-valid entry used as the base for hand-built fixtures.
VALID_ENTRY: dict[str, Any] = {
    "name": "ST_Example",
    "category": "measurement",
    "signatures": ["ST_Example(geometry a) -> double precision"],
    "summary": "Returns an example measurement for the supplied geometry.",
    "returns": "double precision",
    "since": "2.0",
    "arguments": [{"name": "a", "type": "geometry", "description": "Input geometry."}],
    "example": {
        "sql": "SELECT ST_Example('POINT(0 0)'::geometry);",
        "result": " st_example \n------------\n          0",
        "psycopg": 'cur.execute("SELECT ST_Example(geom) FROM t")',
        "geoalchemy": "select(ST_Example(Thing.geom))",
    },
    "srid_notes": "Planar, in SRID units.",
    "index_usage": {
        "gist": True,
        "sargable": True,
        "needs_bbox_prefilter": False,
        "notes": "Uses the index directly.",
    },
    "common_mistakes": ["Assuming metres on 4326.", "Forgetting the SRID."],
    "see_also": [],
    "tags": ["example", "measurement"],
}


def entry_dict(**overrides: Any) -> dict[str, Any]:
    """Return a deep copy of :data:`VALID_ENTRY` with ``overrides`` applied."""
    raw = copy.deepcopy(VALID_ENTRY)
    raw.update(overrides)
    return raw


def make_entry(**overrides: Any) -> FunctionEntry:
    """Build a :class:`FunctionEntry` from :data:`VALID_ENTRY` plus ``overrides``."""
    return FunctionEntry.from_dict(entry_dict(**overrides))


@pytest.fixture(scope="session")
def real_dataset() -> Dataset:
    """The dataset actually shipped in ``data/functions``."""
    return load_dataset(DEFAULT_DATA_DIR)


@pytest.fixture
def tiny_dataset() -> Dataset:
    """A small, predictable dataset for search and rendering tests."""
    return Dataset(
        (
            make_entry(name="ST_Buffer", category="processing", tags=["buffer", "offset"]),
            make_entry(
                name="ST_DWithin",
                category="relationships",
                summary="True when two geometries are within a given distance of each other.",
                tags=["radius", "proximity"],
                see_also=["ST_Buffer"],
            ),
            make_entry(
                name="ST_Union",
                category="processing",
                summary="Merges geometries into a single dissolved geometry.",
                tags=["dissolve", "aggregate"],
                index_usage={
                    "gist": False,
                    "sargable": False,
                    "needs_bbox_prefilter": False,
                    "notes": "Aggregation, not a filter.",
                },
            ),
            make_entry(
                name="&&",
                category="operators",
                summary="Bounding box intersection test used by the GiST index.",
                tags=["bbox", "index"],
            ),
        )
    )


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """An empty directory for writing throwaway YAML datasets."""
    directory = tmp_path / "functions"
    directory.mkdir()
    return directory
