"""Module entry point: ``python -m st_cheatsheet``."""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":  # pragma: no cover - exercised via subprocess in tests
    sys.exit(main())
