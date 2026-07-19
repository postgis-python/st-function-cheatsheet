"""Loading and validating the YAML dataset.

The dataset lives in ``data/functions/<category>.yaml``; each file holds a top-level
list of entry mappings. :func:`load_dataset` parses them into a :class:`Dataset`,
and :func:`validate_dataset` performs the cross-entry checks (duplicate names,
dangling ``see_also`` references) that a per-entry schema cannot express.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

import yaml

from .model import CATEGORIES, FunctionEntry, SchemaError

__all__ = [
    "DEFAULT_DATA_DIR",
    "Dataset",
    "DatasetError",
    "load_dataset",
    "validate_dataset",
]

#: Repository-relative default location of the dataset.
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "functions"


class DatasetError(RuntimeError):
    """Raised when the dataset cannot be read at all (missing or unparseable)."""


@dataclass(frozen=True, slots=True)
class Dataset:
    """An ordered, indexed collection of :class:`FunctionEntry` objects."""

    entries: tuple[FunctionEntry, ...]

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[FunctionEntry]:
        return iter(self.entries)

    @property
    def by_name(self) -> dict[str, FunctionEntry]:
        """Map of case-folded name to entry."""
        return {entry.name.lower(): entry for entry in self.entries}

    def get(self, name: str) -> FunctionEntry | None:
        """Return the entry named ``name`` (case-insensitive), or ``None``."""
        return self.by_name.get(name.strip().lower())

    def categories(self) -> dict[str, int]:
        """Return ``{category: entry count}`` in canonical category order."""
        counts = Counter(entry.category for entry in self.entries)
        return {category: counts[category] for category in CATEGORIES if counts[category]}

    def filter(self, *, category: str | None = None, index_only: bool = False) -> "Dataset":
        """Return a new dataset narrowed by category and/or GiST usability."""
        selected = [
            entry
            for entry in self.entries
            if (category is None or entry.category == category)
            and (not index_only or entry.index_usage.gist)
        ]
        return Dataset(tuple(selected))

    def to_list(self) -> list[dict[str, object]]:
        """Return the dataset as a list of JSON-serialisable mappings."""
        return [entry.to_dict() for entry in self.entries]


def _read_documents(path: Path) -> list[object]:
    """Parse one YAML file and return its top-level list of entries."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DatasetError(f"cannot read {path}: {exc}") from exc
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise DatasetError(f"invalid YAML in {path}: {exc}") from exc
    if parsed is None:
        return []
    if not isinstance(parsed, list):
        raise DatasetError(f"{path}: expected a top-level list of entries")
    return parsed


def load_dataset(data_dir: Path | str = DEFAULT_DATA_DIR) -> Dataset:
    """Load and schema-check every YAML file under ``data_dir``.

    Entries are sorted by category (canonical order) then name, so output is stable
    regardless of filesystem ordering.

    :raises DatasetError: if the directory is missing or a file is unparseable.
    :raises SchemaError: if an entry fails per-entry validation.
    """
    directory = Path(data_dir)
    if not directory.is_dir():
        raise DatasetError(f"dataset directory not found: {directory}")

    paths = sorted(directory.glob("*.yaml"))
    if not paths:
        raise DatasetError(f"no *.yaml files found in {directory}")

    entries: list[FunctionEntry] = []
    for path in paths:
        for index, raw in enumerate(_read_documents(path)):
            entries.append(FunctionEntry.from_dict(raw, source=f"{path.name}#{index}"))

    order = {category: position for position, category in enumerate(CATEGORIES)}
    entries.sort(key=lambda entry: (order[entry.category], entry.name.lower()))
    return Dataset(tuple(entries))


def validate_dataset(dataset: Dataset) -> list[str]:
    """Return a list of cross-entry problems; empty means the dataset is sound.

    Checks performed here (per-entry field checks happen during parsing):

    * no duplicate function names, case-insensitively;
    * every ``see_also`` target resolves to another entry;
    * no entry lists itself in ``see_also``.
    """
    problems: list[str] = []

    counts = Counter(entry.name.lower() for entry in dataset)
    for name, count in sorted(counts.items()):
        if count > 1:
            problems.append(f"duplicate entry name {name!r} appears {count} times")

    known = set(counts)
    for entry in dataset:
        for reference in entry.see_also:
            if reference.lower() == entry.name.lower():
                problems.append(f"{entry.name}: see_also references itself")
            elif reference.lower() not in known:
                problems.append(f"{entry.name}: see_also references unknown entry {reference!r}")

    return problems


def load_validated(data_dir: Path | str = DEFAULT_DATA_DIR) -> tuple[Dataset, Sequence[str]]:
    """Convenience wrapper returning ``(dataset, problems)``.

    Per-entry :class:`SchemaError` still propagates; only cross-entry problems are
    returned as data, because a caller may want to report all of them at once.
    """
    dataset = load_dataset(data_dir)
    return dataset, validate_dataset(dataset)

