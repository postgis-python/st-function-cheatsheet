# st-function-cheatsheet

A curated, example-driven reference for PostGIS `ST_*` functions and spatial operators —
usable from the terminal, as a single self-contained HTML page, or as structured data.

## What it does

Ships a hand-written dataset of **92 PostGIS functions and operators** in
`data/functions/*.yaml`. Every entry carries more than a signature:

- signature(s), return type, the PostGIS version it appeared in, and per-argument descriptions;
- a one-paragraph plain-English summary of *what it is for*, not just what it returns;
- a **SQL example together with the result it actually produces**;
- a **psycopg 3** snippet and a **GeoAlchemy2 / SQLAlchemy 2.0** snippet;
- `srid_notes` — the CRS gotchas: geometry vs geography, degrees vs metres, when you must
  `ST_Transform` and when transforming will silently destroy your index;
- `index_usage` — whether a GiST index can serve it, whether it is sargable as written, and
  whether you need an explicit `&&` prefilter;
- two or three `common_mistakes` per entry, and `see_also` cross-references.

Three interfaces read that one dataset:

| Command | Purpose |
| --- | --- |
| `python -m st_cheatsheet <query>` | ranked terminal search |
| `python -m st_cheatsheet show <name>` | full syntax-highlighted card |
| `python -m st_cheatsheet build --out dist/` | one self-contained, searchable HTML file |
| `python -m st_cheatsheet export --format json` | structured data for other tools |
| `python -m st_cheatsheet validate` | schema-check the dataset (CI-ready) |

## Why it exists

The official PostGIS reference is complete and accurate, and that is exactly the problem when
you are mid-query. It tells you that `ST_DWithin(geometry, geometry, double precision)` returns
a boolean. It does not lead with the three things that actually cost you an afternoon:

1. **The units are not what you assume.** `ST_DWithin(geom, point, 500)` on SRID 4326 means
   500 *degrees*, which matches the entire planet. The same call on `geography` means 500 metres.
   Nothing errors; you just get wrong results, or a query that returns everything.
2. **Whether it uses the index is a property of how you wrote it, not of the function.**
   `ST_Distance(a, b) < 500` and `ST_DWithin(a, b, 500)` are logically identical and differ by
   orders of magnitude in runtime, because only the second emits the `&&` bounding-box term that
   a GiST index can answer. `<->` is index-assisted in `ORDER BY ... LIMIT` and not in `WHERE`.
   `ST_Disjoint` cannot be index-assisted at all.
3. **The near-synonyms differ in exactly one case, and it is the case you have.** `ST_Contains`
   is false for a point on the boundary; `ST_Covers` is true. `ST_Centroid` can land outside a
   crescent-shaped polygon; `ST_PointOnSurface` cannot.

This tool front-loads those three things. Each entry is built around the SRID behaviour, the
index behaviour, and the mistakes people actually make — with a worked example whose printed
result you can check against your own database.

## Install

Cloned and run in place; there is no package to install.

```
git clone <this repo>
cd st-function-cheatsheet
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Python 3.10 or newer. Runtime dependencies are `PyYAML` and `rich`.
For the test suite, use `requirements-dev.txt` instead.

## Usage

### Search

A bare argument is treated as a query. Search covers name, summary and tags, and tolerates
typos:

```
$ python -m st_cheatsheet knn
4 match(es) for 'knn'
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ name            ┃ category      ┃ idx ┃ summary                                        ┃ matched ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━┩
│ <#>             │ operators     │ yes │ Returns the distance between the bounding box… │ tag     │
│ <->             │ operators     │ yes │ The KNN distance operator.                     │ tag     │
│ ST_DWithin      │ relationships │ yes │ Returns true when the two geometries are with… │ summary │
│ ST_ClosestPoint │ processing    │ no  │ Returns the point on the first geometry that … │ summary │
└─────────────────┴───────────────┴─────┴────────────────────────────────────────────────┴─────────┘
```

The `idx` column is the quick answer to "can this use my GiST index?". Misspellings still land:

```
$ python -m st_cheatsheet buffr
1 match(es) for 'buffr'
┏━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ name      ┃ category   ┃ idx ┃ summary                            ┃ matched          ┃
┡━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ ST_Buffer │ processing │ no  │ Returns a polygon covering every … │ fuzzy name (91%) │
└───────────┴────────────┴─────┴────────────────────────────────────┴──────────────────┘
```

An unknown name exits non-zero and suggests neighbours:

```
$ python -m st_cheatsheet show ST_Buffr
error: no entry named 'ST_Buffr'
did you mean: ST_Buffer, ST_Boundary?
$ echo $?
1
```

### Show a full card

```
$ python -m st_cheatsheet show '<->'
╭─ <-> ────────────────────────────────────────────────────────────────────────────────────╮
│                                                                                          │
│  Signature                                                                               │
│    geometry <-> geometry -> double precision                                             │
│    geography <-> geography -> double precision                                           │
│                                                                                          │
│  Summary                                                                                 │
│    The KNN distance operator. In an ORDER BY it lets a GiST index return rows in order   │
│    of increasing distance from a reference point, which is the only way to get a         │
│    nearest-neighbour query that does not read the whole table. Since PostGIS 2.2 on      │
│    PostgreSQL 9.5+ it returns true geometry-to-geometry distance, not box distance.      │
│                                                                                          │
│    Category  operators                                                                   │
│    Returns   double precision                                                            │
│    Since     PostGIS 2.0 (true distance since 2.2)                                       │
│    Index     GiST-indexable - sargable                                                   │
│    Tags      knn, nearest-neighbour, distance, order-by, index, operator                 │
│                                                                                          │
│  Arguments                                                                               │
│      name    type        description                                                     │
│      A       geometry    Left operand. For index use, this must be the indexed           │
│                          column.                                                         │
│      B       geometry    Right operand, normally a constant reference geometry.          │
│                                                                                          │
│  SQL                                                                                     │
│    SELECT ROUND(('POINT(0 0)'::geometry <-> 'POINT(3 4)'::geometry)::numeric, 3) AS d;   │
│    Result                                                                                │
│       d                                                                                  │
│    -------                                                                               │
│     5.000                                                                                │
│                                                                                          │
│  psycopg                                                                                 │
│    with conn.cursor() as cur:                                                            │
│        cur.execute(                                                                      │
│            """                                                                           │
│            SELECT id, name, geom <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS dist      │
│            FROM stops                                                                    │
│            ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)                      │
│            LIMIT 10                                                                      │
│            """,                                                                          │
│            (lon, lat, lon, lat),                                                         │
│        )                                                                                 │
│        nearest = cur.fetchall()                                                          │
│                                                                                          │
│  GeoAlchemy2                                                                             │
│    from sqlalchemy import select                                                         │
│    from geoalchemy2.functions import ST_MakePoint, ST_SetSRID                            │
│                                                                                          │
│    here = ST_SetSRID(ST_MakePoint(lon, lat), 4326)                                       │
│    stmt = select(Stop.id,                                                                │
│    Stop.name).order_by(Stop.geom.distance_centroid(here)).limit(10)                      │
│                                                                                          │
│  SRID notes                                                                              │
│    On geometry the result is in SRID units, so on 4326 you get degrees - useless as a    │
│    distance but perfectly valid as an ordering key at small extents. For metres either   │
│    cast both sides to geography (the geography <-> is also index-assisted) or store a    │
│    projected column. Ordering by degrees and ordering by metres differ noticeably at     │
│    high latitudes.                                                                       │
│                                                                                          │
│  Index usage                                                                             │
│    Index-assisted only in an ORDER BY with a LIMIT, where one side is a constant and     │
│    the other is the indexed column. Put it in a WHERE clause and you get a sequential    │
│    scan; use ST_DWithin there instead.                                                   │
│                                                                                          │
│  Common mistakes                                                                         │
│    - Using <-> in WHERE (geom <-> point < 1000). That is not index-assisted - use        │
│      ST_DWithin for a radius filter.                                                     │
│    - Omitting LIMIT, which makes the planner prefer a sort over the index scan and       │
│      reads every row.                                                                    │
│    - Reading the geometry result as metres on SRID 4326, where it is degrees.            │
│                                                                                          │
│  See also  <#>, ST_DWithin, ST_Distance, ST_ClosestPoint                                 │
│  Guide     https://www.postgis-python.com/mastering-core-spatial-query-patterns/         │
│                                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────╯
```

### Copy just the snippet

`--snippet` prints the raw text with no framing, so it pipes cleanly into an editor or the
clipboard:

```
$ python -m st_cheatsheet show ST_Subdivide --snippet geoalchemy
from sqlalchemy import select
from geoalchemy2.functions import ST_Subdivide

stmt = select(Country.id, ST_Subdivide(Country.geom, 128).label("part"))
```

```
$ python -m st_cheatsheet show ST_DWithin --snippet sql | pbcopy
```

### Browse by category, or by index behaviour

```
$ python -m st_cheatsheet categories
Categories
┏━━━━━━━━━━━━━━━━━┳━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ category        ┃   n ┃ description                                                              ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ constructors    │  10 │ Build geometry values from coordinates, text, binary or GeoJSON.         │
│ accessors       │  13 │ Inspect a geometry: type, dimension, SRID, coordinates, validity.        │
│ measurement     │  10 │ Distances, areas, lengths and perimeters.                                │
│ relationships   │  13 │ Boolean spatial predicates and the DE-9IM model behind them.             │
│ processing      │  19 │ Derive new geometries: buffers, unions, simplification, clustering.      │
│ editors         │   9 │ Modify an existing geometry in place: SRID, validity, densification.     │
│ output          │   8 │ Serialise geometry to text, JSON, binary or vector tiles.                │
│ operators       │   6 │ Bounding-box and KNN operators that drive index access.                  │
│ utility         │   4 │ Version, configuration and housekeeping helpers.                         │
└─────────────────┴─────┴──────────────────────────────────────────────────────────────────────────┘
```

`--index-only` narrows any listing to the functions a GiST index can actually serve — 17 of the
92, which is itself the useful lesson:

```
$ python -m st_cheatsheet list --index-only --category operators
6 entries
┏━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ name ┃ category  ┃ since        ┃ returns          ┃ summary                                     ┃
┡━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ &&   │ operators │ 1.0          │ boolean          │ Returns true when the 2D bounding boxes of… │
│ &&&  │ operators │ 2.0          │ boolean          │ The n-dimensional counterpart of &&: it re… │
│ <#>  │ operators │ 2.0          │ double precision │ Returns the distance between the bounding … │
│ <->  │ operators │ 2.0 (true d… │ double precision │ The KNN distance operator.                  │
│ @    │ operators │ 1.0          │ boolean          │ Returns true when the bounding box of A is… │
│ ~    │ operators │ 1.0          │ boolean          │ Returns true when the bounding box of A co… │
└──────┴───────────┴──────────────┴──────────────────┴─────────────────────────────────────────────┘
```

### Build the HTML page

```
$ python -m st_cheatsheet build --out dist/
wrote dist/index.html (490 kB, 92 functions, no external requests)
```

That is the one command that produces the page; build output is not committed. The result is a
**single file** you can open with `file://`, drop on an intranet, or commit to a wiki:

- instant client-side fuzzy search, category filter, and a "GiST-indexable only" toggle;
- keyboard navigation — <kbd>/</kbd> focuses search, arrows move through results,
  <kbd>Enter</kbd> jumps to the card, <kbd>Esc</kbd> clears;
- a deep-linkable `#fragment` per function, copy-to-clipboard on every snippet;
- light and dark via `prefers-color-scheme`, responsive down to phone width;
- **no external requests at all** — CSS, JS and data are inlined, and the build asserts it.

Every card is rendered server-side, so the page still reads, prints and deep-links with
JavaScript disabled; the script only filters and reorders nodes that already exist.

### Validate and export

```
$ python -m st_cheatsheet validate
dataset is valid
checked 92 entries across 9 categories
```

`validate` exits 1 on a bad dataset, which makes it a one-line CI gate. `export` emits the whole
structured dataset, honouring `--category` and `--index-only`:

```
$ python -m st_cheatsheet export --format json --category operators --out examples/operators.json
wrote examples/operators.json (6 functions)
```

`examples/` holds two such artefacts: [operators.json](examples/operators.json) (all six spatial
operators) and [gist-indexable.json](examples/gist-indexable.json) (every entry a GiST index can
serve). `--format ndjson` emits one compact object per line for streaming consumers.

## How it works

**The dataset is the product.** `data/functions/*.yaml` is hand-written, one file per category,
and the Python is a thin loader / searcher / renderer over it.

**Validation is two-phase.** Per-entry checks happen during parsing, in
`FunctionEntry.from_dict`: required fields, types, known category, at least one signature, at
least two common mistakes, `https://`-only `docs_url`, and — deliberately — rejection of *unknown*
keys, so that a typo like `retruns:` fails loudly instead of silently dropping content. Errors
name the file, index and function (`measurement.yaml#3 [ST_Area]: ...`). Cross-entry checks then
run over the whole set in `validate_dataset`: duplicate names, `see_also` targets that do not
resolve, and self-references. `build` refuses to run on a dataset that fails.

**Search ranking is explainable, not statistical.** Score bands, best first: exact name (an
`st_` prefix is optional, so `dwithin` matches `ST_DWithin`), name prefix, name substring, exact
tag, tag substring, summary substring, and finally a `difflib` similarity fallback above 0.62 to
catch typos. Ties break on shorter name, so `simplify` returns `ST_Simplify` before
`ST_SimplifyPreserveTopology`. Every result reports *why* it matched in the `matched` column.
The bands are spaced widely enough that no lower-band bonus can outrank a higher band.

**The HTML page embeds a JSON island** of just the fields the client needs (name, slug, category,
summary, tags, GiST flag) and reimplements the same band scoring in JavaScript, with a
subsequence matcher in place of `difflib`. Ranking therefore differs slightly between terminal
and page for typo-heavy queries; exact, prefix and substring behaviour is identical.

**Limitations, honestly:**

- **No database is consulted.** The `result` field of each example is authored, not executed at
  build time. Results were chosen to be independently verifiable (a 10×10 box has area 100;
  `LINESTRING(0 0, 3 4)` has length 5), and floating point is rounded in the SQL where the exact
  digits would be uncertain. Output that legitimately varies by installation — version strings,
  `ST_MemSize` byte counts, protobuf blobs — is presented as a comparison or a property rather
  than a fixed value.
- **Version numbers are conservative.** Where PostGIS documents no availability note, entries say
  `1.0` rather than guessing. Where a feature arrived later than the function, the `since` field
  says so inline (`2.0 (true distance since 2.2)`).
- **`index_usage` describes the common case.** Whether the planner *chooses* an index also depends
  on statistics, row counts and cost settings; the flags tell you whether the query is written so
  that it *can*, which is the part you control.
- **Coverage is curated, not exhaustive.** 92 entries covering the functions that carry real
  gotchas. Raster, topology and 3D-surface functions are out of scope.

## Configuration

There is no config file; behaviour is entirely by flag.

| Flag | Effect |
| --- | --- |
| `--data-dir DIR` | load a different dataset directory (useful for testing your own entries) |
| `--category NAME` | restrict to one of the nine categories |
| `--index-only` | only functions a GiST index can serve |
| `--snippet {sql,psycopg,geoalchemy}` | print one raw snippet from `show` |
| `--limit N` | cap search results (default 20) |
| `--format {json,ndjson}` | export shape |
| `--out PATH` | build/export destination |
| `--no-color`, `--width N` | force plain output or a fixed width, for piping and CI logs |

Exit codes: `0` success, `1` no results or validation failure, `2` usage error, `3` the dataset
could not be loaded or the site could not be built.

Adding an entry is a matter of appending to the relevant YAML file and running `validate`; the
schema is enforced, so an incomplete entry cannot reach the page.

## Testing

```
$ .venv/bin/pip install -r requirements-dev.txt
$ .venv/bin/python -m pytest
202 passed in 3.17s
```

The suite runs offline and needs no PostgreSQL, PostGIS, Docker or network. It covers:

- **the real shipped dataset** against the schema — bad data fails CI, including checks that every
  Python snippet actually compiles, that `see_also` resolves, that slugs are unique, and that no
  entry claims to be sargable without GiST support;
- search ranking and tie-breaking, including the typo fallback;
- snippet extraction, and preservation of the leading whitespace that keeps psql result columns
  aligned;
- the HTML builder — expected sections present, the embedded JSON parses, escaping of HTML
  metacharacters and of `</script>` inside prose, and an **offline-safety assertion** that no
  `http(s)://` reference appears outside an `href`;
- CLI exit codes for every command, including two real `python -m st_cheatsheet` subprocess runs.

## How the data was verified

Tests prove the dataset is *well-formed*. They cannot prove it is *true*, so it is worth being
explicit about where each field's authority comes from.

Every entry was checked field-by-field against its
[official PostGIS documentation page](https://postgis.net/docs/reference.html), which produced 24
corrections — mostly `since` versions (`Availability:` and `Changed:` mean different things, and
a rename is not an introduction) and missing overloads in signatures. Every stated SQL result was
recomputed by hand and none needed changing.

All 92 SQL examples have since been *executed* against a live PostGIS 3.4.3 / PostgreSQL 16
(GEOS 3.9.0, PROJ 7.2.1), each in its own rolled-back transaction. 90 reproduced their stated
result exactly. The two that did not are `PostGIS_Full_Version` and `PostGIS_GEOS_Version`, whose
stated output quotes a newer stack (GEOS 3.12.1, PROJ 9.4.0) than that test box runs; those are
environment artifacts, not errors, and were deliberately left alone. No example needed a
correction. The examples are written defensively — rounded magnitudes, feature counts and boolean
assertions rather than raw coordinate dumps — which is why GEOS-sensitive entries such as
`ST_Buffer`, `ST_ConcaveHull` and `ST_VoronoiPolygons` reproduce unchanged on an older GEOS.

What that verification can and cannot back:

- **Signatures, return types, `since` versions and documented behaviour** are doc-sourced. Where
  a page carries no `Availability:` line at all — common for functions predating PostGIS 1.0 —
  the value is a reasonable inference, not a citation.
- **`index_usage` and much of `srid_notes` are editorial.** The upstream pages mostly do not
  discuss GiST behaviour or sargability, so these reflect PostGIS practice rather than quotable
  documentation. They are the fields most worth confirming against `EXPLAIN` on your own version
  before you rely on them. The `gist: true` predicates and the `gist: false` markings on
  `ST_Disjoint` and `ST_Relate` have since been confirmed empirically with `EXPLAIN ANALYZE`
  against PostGIS 3.4.3 over a GiST-indexed fixture table. `ST_Equals` was previously marked
  conservatively on the grounds that its page, alone among the predicates, states no automatic
  bounding-box comparison; that marking turned out to be wrong. It carries the same
  `postgis_index_supportfn` as `ST_Intersects` and emits a `~=` (identical bounding box) index
  condition, so it is index-assisted and is now marked as such.
- **Claims that quote a literal error message** were dropped unless the wording could be
  confirmed, and the underlying lesson kept instead. An invented error string is worse than no
  error string, because it looks checkable.

If you find something wrong, an issue with the doc sentence that settles it is the fastest way to
get it fixed.

## Further reading

The `docs_url` on an entry points at a deeper guide for that specific topic. The ones referenced
by this dataset:

- [Mastering core spatial query patterns](https://www.postgis-python.com/mastering-core-spatial-query-patterns/)
  — the `&&` prefilter, `ST_DWithin` radius filters, KNN with `<->`, and spatial joins.
- [Advanced GiST indexing and optimization](https://www.postgis-python.com/advanced-gist-indexing-optimization/)
  — partial and composite indexes, index-only scans, reading `EXPLAIN (ANALYZE, BUFFERS)`, and
  when SP-GiST or BRIN beats GiST.
- [SQLAlchemy and GeoAlchemy2 integration workflows](https://www.postgis-python.com/sqlalchemy-and-geoalchemy-integration-workflows/)
  — model mapping, sessions, hybrid geometry properties, type coercion and async streaming.
- [Spatial schema migrations and evolution](https://www.postgis-python.com/spatial-schema-migrations-and-evolution/)
  — adding geometry columns to live tables, in-place SRID reprojection, concurrent index builds.
- [Spatial performance monitoring and observability](https://www.postgis-python.com/spatial-performance-monitoring-and-observability/)
  — `pg_stat_statements`, GiST bloat detection and autovacuum tuning.

## License

MIT — see [LICENSE](LICENSE).
