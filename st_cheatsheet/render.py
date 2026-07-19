"""Terminal rendering with `rich`.

Everything user-visible in the CLI is produced here, so the CLI module stays a thin
argument-parsing shell and the renderers can be exercised directly in tests by
pointing a :class:`rich.console.Console` at a string buffer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Sequence

from rich.console import Console, Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from .loader import Dataset
from .model import CATEGORY_DESCRIPTIONS, FunctionEntry
from .search import SearchResult

if TYPE_CHECKING:  # pragma: no cover - import kept lazy so `verify` stays optional
    from .verify import Outcome, VerifyReport

__all__ = [
    "SNIPPET_KINDS",
    "render_card",
    "render_categories",
    "render_list",
    "render_results",
    "render_verify",
]

#: Snippet names accepted by ``--snippet`` and by :meth:`Example.snippet`.
SNIPPET_KINDS: tuple[str, ...] = ("sql", "psycopg", "geoalchemy")

_SYNTAX_THEME = "ansi_dark"


def _code(text: str, lexer: str) -> Syntax:
    """Return a syntax-highlighted, unnumbered code block."""
    return Syntax(text.rstrip(), lexer, theme=_SYNTAX_THEME, word_wrap=True, background_color="default")


def _heading(text: str) -> Text:
    """Return a section heading for use inside a card."""
    return Text(text, style="bold cyan")


def _index_summary(entry: FunctionEntry) -> Text:
    """Return a one-line, colour-coded index verdict."""
    usage = entry.index_usage
    if not usage.gist:
        return Text("no GiST acceleration", style="bold red")
    parts: list[str] = ["GiST-indexable"]
    parts.append("sargable" if usage.sargable else "needs rewriting to be sargable")
    if usage.needs_bbox_prefilter:
        parts.append("requires an && prefilter")
    return Text(" - ".join(parts), style="bold green")


def render_card(entry: FunctionEntry) -> RenderableType:
    """Return the full reference card for one entry."""
    body: list[RenderableType] = []

    body.append(_heading("Signature"))
    body.append(Padding(_code("\n".join(entry.signatures), "sql"), (0, 0, 1, 2)))

    body.append(_heading("Summary"))
    body.append(Padding(Text(entry.summary), (0, 0, 1, 2)))

    meta = Table.grid(padding=(0, 2))
    meta.add_column(style="dim")
    meta.add_column()
    meta.add_row("Category", entry.category)
    meta.add_row("Returns", entry.returns)
    meta.add_row("Since", f"PostGIS {entry.since}")
    meta.add_row("Index", _index_summary(entry))
    if entry.tags:
        meta.add_row("Tags", ", ".join(entry.tags))
    body.append(Padding(meta, (0, 0, 1, 2)))

    if entry.arguments:
        body.append(_heading("Arguments"))
        args = Table(show_edge=False, box=None, padding=(0, 2))
        args.add_column("name", style="bold")
        args.add_column("type", style="magenta")
        args.add_column("description")
        for argument in entry.arguments:
            label = f"{argument.name} (optional)" if argument.optional else argument.name
            args.add_row(label, argument.type, argument.description)
        body.append(Padding(args, (0, 0, 1, 2)))

    body.append(_heading("SQL"))
    body.append(Padding(_code(entry.example.sql, "sql"), (0, 0, 0, 2)))
    body.append(Padding(Text("Result", style="dim"), (0, 0, 0, 2)))
    # Rendered as Syntax, not Text: psql output is column-aligned, and only a code
    # renderable preserves its leading whitespace verbatim.
    body.append(Padding(_code(entry.example.result, "text"), (0, 0, 1, 2)))

    body.append(_heading("psycopg"))
    body.append(Padding(_code(entry.example.psycopg, "python"), (0, 0, 1, 2)))

    body.append(_heading("GeoAlchemy2"))
    body.append(Padding(_code(entry.example.geoalchemy, "python"), (0, 0, 1, 2)))

    body.append(_heading("SRID notes"))
    body.append(Padding(Text(entry.srid_notes), (0, 0, 1, 2)))

    body.append(_heading("Index usage"))
    body.append(Padding(Text(entry.index_usage.notes), (0, 0, 1, 2)))

    body.append(_heading("Common mistakes"))
    # A two-column grid rather than one Text block, so that wrapped lines hang-indent
    # under the text instead of running back under the bullet.
    mistakes = Table.grid(padding=(0, 1))
    mistakes.add_column(style="yellow", no_wrap=True, vertical="top")
    mistakes.add_column(overflow="fold")
    for mistake in entry.common_mistakes:
        mistakes.add_row("-", mistake)
    body.append(Padding(mistakes, (0, 0, 1, 2)))

    if entry.see_also:
        body.append(Text.assemble(("See also  ", "bold cyan"), (", ".join(entry.see_also), "")))
    if entry.docs_url:
        body.append(Text.assemble(("Guide     ", "bold cyan"), (entry.docs_url, "underline blue")))

    return Panel(
        Group(*body),
        title=Text(entry.name, style="bold white"),
        title_align="left",
        border_style="cyan",
        padding=(1, 2),
    )


def render_results(results: Sequence[SearchResult], *, query: str) -> RenderableType:
    """Return a ranked results table for a search."""
    if not results:
        return Text(f"No matches for {query!r}. Try `list` or `categories`.", style="yellow")

    table = Table(title=f"{len(results)} match(es) for {query!r}", title_justify="left", expand=True)
    table.add_column("name", style="bold", no_wrap=True)
    table.add_column("category", style="magenta", no_wrap=True)
    table.add_column("idx", justify="center", no_wrap=True)
    # ratio=1 makes summary the only flexible column, so the fixed ones keep their width.
    table.add_column("summary", no_wrap=True, overflow="ellipsis", ratio=1)
    table.add_column("matched", style="dim", no_wrap=True)

    for result in results:
        entry = result.entry
        table.add_row(
            entry.name,
            entry.category,
            Text("yes", style="green") if entry.index_usage.gist else Text("no", style="red"),
            _first_sentence(entry.summary),
            result.reason,
        )
    return table


def render_list(dataset: Dataset) -> RenderableType:
    """Return a compact table of every entry in the dataset."""
    table = Table(title=f"{len(dataset)} entries", title_justify="left", expand=True)
    table.add_column("name", style="bold", no_wrap=True)
    table.add_column("category", style="magenta", no_wrap=True)
    table.add_column("since", no_wrap=True, max_width=12, overflow="ellipsis")
    table.add_column("returns", style="dim", no_wrap=True, max_width=18, overflow="ellipsis")
    # One line per entry: a listing is for scanning, `show` is for reading.
    table.add_column("summary", no_wrap=True, overflow="ellipsis", ratio=1)
    for entry in dataset:
        table.add_row(
            entry.name, entry.category, entry.since, entry.returns, _first_sentence(entry.summary)
        )
    return table


def render_categories(dataset: Dataset) -> RenderableType:
    """Return a table of categories with counts and descriptions."""
    table = Table(title="Categories", title_justify="left", expand=True)
    table.add_column("category", style="bold magenta", no_wrap=True)
    table.add_column("n", justify="right", no_wrap=True)
    table.add_column("description")
    for category, count in dataset.categories().items():
        table.add_row(category, str(count), CATEGORY_DESCRIPTIONS[category])
    return table


def render_problems(problems: Iterable[str]) -> RenderableType:
    """Return a rendering of validator problems."""
    listed = list(problems)
    if not listed:
        return Text("dataset is valid", style="bold green")
    text = Text()
    for problem in listed:
        text.append("  x ", style="bold red")
        text.append(f"{problem}\n")
    text.append(f"\n{len(listed)} problem(s)", style="bold red")
    return text


#: Colour per verify status, ordered as the summary line prints them.
_STATUS_STYLES: dict[str, str] = {
    "matched": "green",
    "mismatched": "bold red",
    "failed": "bold red",
    "since-suspect": "bold yellow",
    "skipped": "dim",
}


def _render_outcome_detail(outcome: "Outcome") -> RenderableType:
    """Return one outcome as a heading plus, when useful, an expected/actual diff."""
    body: list[RenderableType] = [
        Text.assemble(
            (outcome.name, "bold"),
            ("  ", ""),
            (outcome.detail, _STATUS_STYLES.get(outcome.status, "")),
        )
    ]
    if outcome.expected:
        body.append(Padding(Text("expected", style="dim"), (0, 0, 0, 2)))
        body.append(Padding(_code(outcome.expected, "text"), (0, 0, 0, 4)))
    if outcome.actual and (outcome.expected or outcome.status != "skipped"):
        body.append(Padding(Text("actual", style="dim"), (0, 0, 0, 2)))
        body.append(Padding(_code(outcome.actual, "text"), (0, 0, 1, 4)))
    return Group(*body)


def render_verify(report: "VerifyReport", *, verbose: bool = False) -> RenderableType:
    """Return the full ``verify`` report: server banner, problems, then a tally."""
    body: list[RenderableType] = [
        Text.assemble(("server  ", "bold cyan"), (str(report.server), "")),
        Text(""),
    ]

    # Problems first and in severity order: a long run should put the thing you need
    # to act on at the point where reading starts, not scrolled off the top.
    for status, heading in (
        ("mismatched", "Mismatched (the stated result is wrong here)"),
        ("failed", "Failed to execute"),
        ("since-suspect", "Suspect 'since' values (ran on an older server than claimed)"),
    ):
        outcomes = report.by_status(status)
        if not outcomes:
            continue
        body.append(_heading(heading))
        for outcome in outcomes:
            body.append(Padding(_render_outcome_detail(outcome), (0, 0, 0, 2)))
        body.append(Text(""))

    skipped = report.by_status("skipped")
    if skipped and verbose:
        body.append(_heading("Skipped"))
        for outcome in skipped:
            body.append(Padding(_render_outcome_detail(outcome), (0, 0, 0, 2)))
        body.append(Text(""))

    counts = report.counts()
    tally = Text()
    for status, count in counts.items():
        if tally:
            tally.append("  ")
        tally.append(f"{status} {count}", style=_STATUS_STYLES.get(status, "") if count else "dim")
    body.append(tally)

    total = sum(counts.values())
    verdict = (
        Text(f"{total} entries verified against PostGIS {report.server.postgis}", style="bold green")
        if not report.failures
        else Text(f"{len(report.failures)} entry/entries need attention", style="bold red")
    )
    body.append(verdict)
    return Group(*body)


def _first_sentence(summary: str) -> str:
    """Return the first sentence of a summary, for table display."""
    collapsed = " ".join(summary.split())
    head, separator, _ = collapsed.partition(". ")
    return head + separator.strip() if separator else collapsed


def make_console(*, no_color: bool = False, width: int | None = None) -> Console:
    """Return a configured :class:`~rich.console.Console`."""
    return Console(no_color=no_color, width=width, highlight=False, soft_wrap=False)
