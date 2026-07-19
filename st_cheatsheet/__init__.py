"""A curated, example-driven reference for PostGIS ``ST_*`` functions and operators.

Three interfaces over one dataset:

* ``python -m st_cheatsheet <query>`` - terminal lookup with syntax-highlighted cards.
* ``python -m st_cheatsheet build`` - a single self-contained, searchable HTML file.
* ``python -m st_cheatsheet export`` - structured JSON for other tools.

The dataset in ``data/functions/*.yaml`` is the product; the code here loads it,
validates it, searches it and renders it.
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["__version__"]
