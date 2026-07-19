"""Command-line interface.

Exit codes are part of the contract, so that the tool composes in shell pipelines and
CI jobs:

======  ============================================================
  0     success
  1     no results, or the dataset failed validation
  2     usage error (raised by argparse)
  3     the dataset could not be loaded or the site could not be built
======  ============================================================
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from rich.console import Console

from . import __version__
from .builder import BuildError, write_site
from .exporter import FORMATS, ExportError, export
from .loader import DEFAULT_DATA_DIR, Dataset, DatasetError, load_dataset, validate_dataset
from .model import CATEGORIES, SchemaError
from .render import (
    SNIPPET_KINDS,
    make_console,
    render_card,
    render_categories,
    render_list,
    render_problems,
    render_results,
)
from .search import search as run_search

__all__ = ["build_parser", "main"]

EXIT_OK = 0
EXIT_NO_RESULTS = 1
EXIT_DATASET = 3

#: Subcommands, used to decide whether a bare first argument is a query or a command.
_COMMANDS = ("search", "show", "list", "categories", "validate", "build", "export")


def build_parser() -> argparse.ArgumentParser:
    """Return the fully configured argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m st_cheatsheet",
        description="Example-driven reference for PostGIS ST_* functions and spatial operators.",
        epilog="A bare argument is treated as a search query: `python -m st_cheatsheet dwithin`.",
    )
    parser.add_argument("--version", action="version", version=f"st-cheatsheet {__version__}")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        metavar="DIR",
        help="directory of YAML entry files (default: the bundled data/functions)",
    )
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colour output")
    parser.add_argument(
        "--width", type=int, default=None, metavar="N", help="force a terminal width"
    )

    subparsers = parser.add_subparsers(dest="command")

    def add_filters(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "--category", choices=CATEGORIES, default=None, help="restrict to one category"
        )
        target.add_argument(
            "--index-only",
            action="store_true",
            help="only functions the planner can answer with a GiST index",
        )

    search_parser = subparsers.add_parser("search", help="fuzzy search across name, summary and tags")
    search_parser.add_argument("query", nargs="?", default="", help="search terms")
    search_parser.add_argument("--limit", type=int, default=20, metavar="N", help="max results (default 20)")
    add_filters(search_parser)

    show_parser = subparsers.add_parser("show", help="render the full card for one function")
    show_parser.add_argument("name", help="function or operator name, e.g. ST_DWithin or '&&'")
    show_parser.add_argument(
        "--snippet",
        choices=SNIPPET_KINDS,
        default=None,
        help="print only this snippet, unformatted, for piping into an editor",
    )

    list_parser = subparsers.add_parser("list", help="list every entry")
    add_filters(list_parser)

    subparsers.add_parser("categories", help="list categories with entry counts")
    subparsers.add_parser("validate", help="check the dataset against the schema")

    build_parser_ = subparsers.add_parser("build", help="generate the self-contained HTML page")
    build_parser_.add_argument(
        "--out", type=Path, default=Path("dist"), metavar="DIR", help="output directory (default: dist)"
    )
    build_parser_.add_argument(
        "--title", default="PostGIS ST_* cheatsheet", help="page title"
    )

    export_parser = subparsers.add_parser("export", help="dump the dataset as structured data")
    export_parser.add_argument("--format", choices=sorted(FORMATS), default="json", dest="fmt")
    export_parser.add_argument(
        "--out", type=Path, default=None, metavar="FILE", help="write to a file instead of stdout"
    )
    add_filters(export_parser)

    return parser


#: Global options that consume the following argv item, which must therefore not be
#: mistaken for a bare query (``--width 120 dwithin`` has one query, not two).
_VALUED_GLOBALS = frozenset({"--data-dir", "--width"})


def _normalise_argv(argv: Sequence[str]) -> list[str]:
    """Insert an implicit ``search`` subcommand for a bare query.

    ``python -m st_cheatsheet dwithin`` and ``... search dwithin`` are equivalent, but
    ``--flag``-leading argv is left alone so that ``--help`` and ``--version`` work,
    and option values are skipped rather than treated as the query.
    """
    arguments = list(argv)
    index = 0
    while index < len(arguments):
        item = arguments[index]
        if item.startswith("-"):
            # "--width=120" carries its own value; "--width 120" consumes the next item.
            index += 1 if "=" in item or item not in _VALUED_GLOBALS else 2
            continue
        if item in _COMMANDS:
            return arguments
        return arguments[:index] + ["search"] + arguments[index:]
    return arguments


def _load(args: argparse.Namespace, console: Console) -> Dataset | None:
    """Load the dataset, reporting failures on ``console``."""
    try:
        return load_dataset(args.data_dir)
    except (DatasetError, SchemaError) as exc:
        console.print(f"[bold red]error:[/] {exc}")
        return None


def _apply_filters(dataset: Dataset, args: argparse.Namespace) -> Dataset:
    """Apply ``--category`` / ``--index-only`` when the subcommand offers them."""
    return dataset.filter(
        category=getattr(args, "category", None), index_only=getattr(args, "index_only", False)
    )


def _cmd_search(dataset: Dataset, args: argparse.Namespace, console: Console) -> int:
    """Run a ranked search and print the results table."""
    results = run_search(_apply_filters(dataset, args), args.query, limit=max(1, args.limit))
    console.print(render_results(results, query=args.query))
    return EXIT_OK if results else EXIT_NO_RESULTS


def _cmd_show(dataset: Dataset, args: argparse.Namespace, console: Console) -> int:
    """Print one full card, or a single raw snippet with ``--snippet``."""
    entry = dataset.get(args.name)
    if entry is None:
        suggestions = run_search(dataset, args.name, limit=3)
        console.print(f"[bold red]error:[/] no entry named {args.name!r}")
        if suggestions:
            names = ", ".join(hit.entry.name for hit in suggestions)
            console.print(f"did you mean: {names}?")
        return EXIT_NO_RESULTS

    if args.snippet:
        # Raw, unstyled output: this is meant to be piped or copied verbatim.
        sys.stdout.write(entry.example.snippet(args.snippet).rstrip() + "\n")
        return EXIT_OK

    console.print(render_card(entry))
    return EXIT_OK


def _cmd_validate(dataset: Dataset, console: Console) -> int:
    """Report cross-entry validation problems."""
    problems = validate_dataset(dataset)
    console.print(render_problems(problems))
    if not problems:
        console.print(f"checked {len(dataset)} entries across {len(dataset.categories())} categories")
    return EXIT_NO_RESULTS if problems else EXIT_OK


def _cmd_build(dataset: Dataset, args: argparse.Namespace, console: Console) -> int:
    """Generate the single-file HTML page."""
    problems = validate_dataset(dataset)
    if problems:
        console.print("[bold red]error:[/] refusing to build an invalid dataset")
        console.print(render_problems(problems))
        return EXIT_NO_RESULTS
    try:
        target = write_site(dataset, args.out, title=args.title)
    except BuildError as exc:
        console.print(f"[bold red]error:[/] {exc}")
        return EXIT_DATASET
    size_kb = target.stat().st_size / 1024
    console.print(f"wrote [bold]{target}[/] ({size_kb:.0f} kB, {len(dataset)} functions, no external requests)")
    return EXIT_OK


def _cmd_export(dataset: Dataset, args: argparse.Namespace, console: Console) -> int:
    """Serialise the dataset to stdout or a file."""
    selected = _apply_filters(dataset, args)
    try:
        payload = export(selected, args.fmt)
    except ExportError as exc:
        console.print(f"[bold red]error:[/] {exc}")
        return EXIT_DATASET
    if args.out is None:
        sys.stdout.write(payload + "\n")
        return EXIT_OK
    try:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    except OSError as exc:
        console.print(f"[bold red]error:[/] cannot write {args.out}: {exc}")
        return EXIT_DATASET
    console.print(f"wrote [bold]{args.out}[/] ({len(selected)} functions)")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(_normalise_argv(sys.argv[1:] if argv is None else argv))
    console = make_console(no_color=args.no_color, width=args.width)

    if args.command is None:
        parser.print_help()
        return EXIT_OK

    dataset = _load(args, console)
    if dataset is None:
        return EXIT_DATASET

    if args.command == "search":
        return _cmd_search(dataset, args, console)
    if args.command == "show":
        return _cmd_show(dataset, args, console)
    if args.command == "list":
        console.print(render_list(_apply_filters(dataset, args)))
        return EXIT_OK
    if args.command == "categories":
        console.print(render_categories(dataset))
        return EXIT_OK
    if args.command == "validate":
        return _cmd_validate(dataset, console)
    if args.command == "build":
        return _cmd_build(dataset, args, console)
    return _cmd_export(dataset, args, console)
