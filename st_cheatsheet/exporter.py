"""Serialisation of the dataset for consumption by other tools."""

from __future__ import annotations

import json
from typing import Callable

from .loader import Dataset

__all__ = ["FORMATS", "ExportError", "export"]


class ExportError(ValueError):
    """Raised when an unknown export format is requested."""


def _to_json(dataset: Dataset) -> str:
    """Pretty-printed JSON object with a top-level ``functions`` key."""
    document = {"count": len(dataset), "functions": dataset.to_list()}
    return json.dumps(document, indent=2, ensure_ascii=False)


def _to_ndjson(dataset: Dataset) -> str:
    """One compact JSON object per line, for streaming consumers."""
    return "\n".join(
        json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in dataset.to_list()
    )


#: Supported ``--format`` values.
FORMATS: dict[str, Callable[[Dataset], str]] = {"json": _to_json, "ndjson": _to_ndjson}


def export(dataset: Dataset, fmt: str) -> str:
    """Return ``dataset`` serialised in ``fmt``.

    :raises ExportError: if ``fmt`` is not one of :data:`FORMATS`.
    """
    try:
        serialiser = FORMATS[fmt]
    except KeyError:
        raise ExportError(f"unknown format {fmt!r} (expected one of: {', '.join(FORMATS)})") from None
    return serialiser(dataset)
