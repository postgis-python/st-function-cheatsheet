"""Static site generator: one self-contained, offline-safe HTML file.

Design decisions worth knowing before editing this module:

* **Every card is rendered server-side.** The client script only hides, reorders and
  highlights nodes that already exist, so the page is readable, printable and
  deep-linkable with JavaScript disabled.
* **Nothing is fetched at runtime.** CSS and JS are inlined from ``templates/`` and the
  dataset is embedded as a JSON island. :func:`assert_offline_safe` enforces this and is
  asserted by the test suite.
* **Templating is plain token substitution**, not ``str.format`` or f-strings, because
  the CSS and JS bodies are full of braces.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from .loader import Dataset
from .model import CATEGORY_DESCRIPTIONS, FunctionEntry, slugify

__all__ = ["BuildError", "assert_offline_safe", "build_page", "write_site"]

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

#: Any occurrence of these in the output would mean a runtime network request.
_FORBIDDEN_SCHEMES = ("http://", "https://")

_SNIPPET_LABELS = (
    ("sql", "SQL"),
    ("psycopg", "psycopg"),
    ("geoalchemy", "GeoAlchemy2"),
)


class BuildError(RuntimeError):
    """Raised when the page cannot be generated or fails its offline-safety check."""


def _read_template(name: str) -> str:
    """Read one file from the bundled ``templates/`` directory."""
    path = TEMPLATE_DIR / name
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BuildError(f"missing template {path}: {exc}") from exc


def _substitute(template: str, values: dict[str, str]) -> str:
    """Replace ``{{TOKEN}}`` placeholders, erroring on any left behind."""
    rendered = template
    for token, value in values.items():
        rendered = rendered.replace("{{" + token + "}}", value)
    if "{{" in rendered:
        start = rendered.index("{{")
        raise BuildError(f"unsubstituted template token near: {rendered[start:start + 40]!r}")
    return rendered


def _snippet_block(kind: str, label: str, code: str, entry_name: str) -> str:
    """Render one copy-to-clipboard code block."""
    aria = escape(f"Copy the {label} example for {entry_name}")
    return (
        f'<div class="snippet" data-kind="{kind}">'
        f"<pre><code>{escape(code)}</code></pre>"
        f'<button type="button" class="copy" data-label="copy" aria-label="{aria}">copy</button>'
        "</div>"
    )


def _arguments_table(entry: FunctionEntry) -> str:
    """Render the argument table, or an empty string when there are no arguments."""
    if not entry.arguments:
        return ""
    rows = "".join(
        "<tr>"
        f"<td>{escape(argument.name)}</td>"
        f"<td>{escape(argument.type)}</td>"
        f"<td>{escape(argument.description)}"
        + (' <em class="pill">optional</em>' if argument.optional else "")
        + "</td></tr>"
        for argument in entry.arguments
    )
    return (
        "<h3>Arguments</h3>"
        '<table class="args"><thead><tr><th scope="col">name</th>'
        '<th scope="col">type</th><th scope="col">description</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )


def _index_pill(entry: FunctionEntry) -> str:
    """Render the GiST badge shown in the card header."""
    if entry.index_usage.gist:
        text = "GiST" if entry.index_usage.sargable else "GiST (rewrite needed)"
        return f'<span class="pill pill--gist">{escape(text)}</span>'
    return '<span class="pill pill--nogist">no index</span>'


def render_card(entry: FunctionEntry) -> str:
    """Render one function as a semantic ``<article>``."""
    parts: list[str] = [
        f'<article class="card" id="{entry.slug}" tabindex="-1" '
        f'aria-labelledby="h-{entry.slug}" data-category="{escape(entry.category)}" '
        f'data-gist="{"true" if entry.index_usage.gist else "false"}">',
        '<div class="card__head">',
        f'<h2 class="card__name" id="h-{entry.slug}">'
        f'<a href="#{entry.slug}">{escape(entry.name)}</a></h2>',
        f'<span class="pill">{escape(entry.category)}</span>',
        _index_pill(entry),
        f'<span class="pill">since {escape(entry.since)}</span>',
        f'<span class="pill">&rarr; {escape(entry.returns)}</span>',
        "</div>",
        f'<p class="sig">{escape(chr(10).join(entry.signatures))}</p>',
        f'<p class="summary">{escape(entry.summary)}</p>',
        _arguments_table(entry),
    ]

    for kind, label in _SNIPPET_LABELS:
        parts.append(f"<h3>{label}</h3>")
        parts.append(_snippet_block(kind, label, entry.example.snippet(kind), entry.name))
        if kind == "sql":
            parts.append("<h3>Result</h3>")
            parts.append(
                '<div class="snippet snippet--result">'
                f"<pre><code>{escape(entry.example.result)}</code></pre></div>"
            )

    parts.append("<h3>SRID notes</h3>")
    parts.append(f'<p class="note">{escape(entry.srid_notes)}</p>')
    parts.append("<h3>Index usage</h3>")
    parts.append(f'<p class="note">{escape(entry.index_usage.notes)}</p>')

    parts.append("<h3>Common mistakes</h3>")
    mistakes = "".join(f"<li>{escape(item)}</li>" for item in entry.common_mistakes)
    parts.append(f'<ul class="mistakes">{mistakes}</ul>')

    if entry.see_also:
        links = ", ".join(
            f'<a href="#{slugify(name)}">{escape(name)}</a>' for name in entry.see_also
        )
        parts.append(f'<p class="xref">See also: {links}</p>')

    if entry.docs_url:
        parts.append(
            f'<a class="guide" href="{escape(entry.docs_url)}" rel="noopener">'
            "Deeper guide on postgis-python.com &rarr;</a>"
        )

    parts.append("</article>")
    return "".join(parts)


def _index_items(dataset: Dataset) -> str:
    """Render the sidebar list, with a heading row before each category run."""
    rows: list[str] = []
    seen: set[str] = set()
    for entry in dataset:
        if entry.category not in seen:
            seen.add(entry.category)
            title = escape(CATEGORY_DESCRIPTIONS[entry.category])
            rows.append(
                f'<li class="index__group" data-category="{escape(entry.category)}" '
                f'role="presentation" title="{title}">{escape(entry.category)}</li>'
            )
        flag = '<span class="idx-flag" aria-label="GiST indexable">idx</span>' if entry.index_usage.gist else ""
        rows.append(
            f'<li id="nav-{entry.slug}" role="option" aria-selected="false">'
            f'<a href="#{entry.slug}" tabindex="-1">'
            f"<span>{escape(entry.name)}</span>{flag}</a></li>"
        )
    return "\n".join(rows)


def _category_options(dataset: Dataset) -> str:
    """Render the ``<option>`` list for the category filter."""
    return "\n".join(
        f'<option value="{escape(category)}">{escape(category)} ({count})</option>'
        for category, count in dataset.categories().items()
    )


def _client_data(dataset: Dataset) -> str:
    """Return the JSON island: only the fields the client script actually reads."""
    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "entries": [
            {
                "name": entry.name,
                "slug": entry.slug,
                "category": entry.category,
                "summary": entry.summary,
                "tags": [tag.lower() for tag in entry.tags],
                "gist": entry.index_usage.gist,
            }
            for entry in dataset
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # Prevent an embedded "</script>" in any summary from terminating the tag.
    return encoded.replace("</", "<\\/")


def assert_offline_safe(html: str) -> None:
    """Raise :class:`BuildError` if the page would make a network request.

    Absolute URLs are permitted only inside ``href`` attributes (the documentation
    deep links), because a link is user-initiated navigation, not an asset fetch.
    """
    for scheme in _FORBIDDEN_SCHEMES:
        position = 0
        while True:
            position = html.find(scheme, position)
            if position == -1:
                break
            preceding = html[max(0, position - 8) : position]
            if not preceding.endswith('href="'):
                context = html[max(0, position - 60) : position + 60]
                raise BuildError(f"external asset reference in generated page: ...{context}...")
            position += len(scheme)

    for marker in ("<link ", "<img ", "srcset=", "@import"):
        if marker in html:
            raise BuildError(f"generated page contains {marker!r}, which may load a remote asset")


def build_page(dataset: Dataset, *, title: str = "PostGIS ST_* cheatsheet") -> str:
    """Render the complete single-file page for ``dataset``.

    :raises BuildError: if the dataset is empty, a template is missing, or the result
        fails :func:`assert_offline_safe`.
    """
    if not len(dataset):
        raise BuildError("refusing to build a page from an empty dataset")

    html = _substitute(
        _read_template("page.html"),
        {
            "TITLE": escape(title),
            "STYLE": _read_template("style.css"),
            "SCRIPT": _read_template("app.js"),
            "COUNT": str(len(dataset)),
            "CATEGORY_OPTIONS": _category_options(dataset),
            "INDEX_ITEMS": _index_items(dataset),
            "CARDS": "\n".join(render_card(entry) for entry in dataset),
            "DATA_JSON": _client_data(dataset),
            "GENERATED": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        },
    )
    assert_offline_safe(html)
    return html


def write_site(dataset: Dataset, out_dir: Path | str, *, title: str = "PostGIS ST_* cheatsheet") -> Path:
    """Build the page and write it to ``out_dir/index.html``, returning that path."""
    directory = Path(out_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "index.html"
        target.write_text(build_page(dataset, title=title), encoding="utf-8")
    except OSError as exc:
        raise BuildError(f"cannot write site to {directory}: {exc}") from exc
    return target

