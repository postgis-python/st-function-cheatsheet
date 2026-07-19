"""HTML builder tests, including the offline-safety guarantee."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from st_cheatsheet.builder import BuildError, assert_offline_safe, build_page, render_card, write_site
from st_cheatsheet.loader import Dataset

from .conftest import make_entry


class _TagBalance(HTMLParser):
    """Minimal well-formedness check: every non-void tag is closed, in order."""

    VOID = {"meta", "link", "br", "hr", "img", "input", "source", "area", "col"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.VOID:
            return
        if not self.stack:
            self.errors.append(f"stray </{tag}>")
        elif self.stack[-1] != tag:
            self.errors.append(f"expected </{self.stack[-1]}>, got </{tag}>")
        else:
            self.stack.pop()


@pytest.fixture
def page(real_dataset: Dataset) -> str:
    """The generated page for the real dataset, built once per module use."""
    return build_page(real_dataset)


def embedded_data(html: str) -> dict:
    """Extract and parse the JSON island from a generated page."""
    match = re.search(
        r'<script id="cheatsheet-data" type="application/json">(.*?)</script>', html, re.S
    )
    assert match, "no JSON island found in the page"
    return json.loads(match.group(1).replace("<\\/", "</"))


class TestOfflineSafety:
    def test_generated_page_makes_no_external_requests(self, page: str) -> None:
        assert_offline_safe(page)

    def test_no_absolute_urls_outside_href(self, page: str) -> None:
        for match in re.finditer(r"https?://", page):
            preceding = page[max(0, match.start() - 8) : match.start()]
            assert preceding.endswith('href="'), page[match.start() - 60 : match.start() + 60]

    def test_no_link_script_src_or_img_tags(self, page: str) -> None:
        assert "<link " not in page
        assert "<img " not in page
        assert "src=" not in page

    def test_detects_an_injected_remote_stylesheet(self) -> None:
        with pytest.raises(BuildError, match="may load a remote asset"):
            assert_offline_safe('<html><link rel="stylesheet" href="/x.css"></html>')

    def test_detects_an_injected_remote_script(self) -> None:
        html = '<html><script src="https://cdn.example.com/a.js"></script></html>'
        with pytest.raises(BuildError, match="external asset reference"):
            assert_offline_safe(html)

    def test_documentation_links_are_allowed(self) -> None:
        assert_offline_safe('<a href="https://www.postgis-python.com/">guide</a>')


class TestPageStructure:
    def test_page_is_well_formed(self, page: str) -> None:
        parser = _TagBalance()
        parser.feed(page)
        assert parser.errors == []
        assert parser.stack == []

    def test_contains_the_expected_shell(self, page: str) -> None:
        for fragment in (
            "<!DOCTYPE html>",
            '<html lang="en">',
            'id="search"',
            'id="category"',
            'id="index-only"',
            'id="cards"',
            'id="index-list"',
            "GiST-indexable only",
        ):
            assert fragment in page, fragment

    def test_css_and_js_are_inlined(self, page: str) -> None:
        assert "prefers-color-scheme: dark" in page
        assert "__ST_CHEATSHEET__" in page
        assert "subsequenceScore" in page

    def test_every_entry_has_a_card_and_an_index_entry(self, page: str, real_dataset: Dataset) -> None:
        for entry in real_dataset:
            assert f'id="{entry.slug}"' in page, entry.name
            assert f'id="nav-{entry.slug}"' in page, entry.name

    def test_category_filter_lists_every_category(self, page: str, real_dataset: Dataset) -> None:
        for category, count in real_dataset.categories().items():
            assert f'<option value="{category}">{category} ({count})</option>' in page

    def test_see_also_links_resolve_to_a_card_on_the_page(self, page: str, real_dataset: Dataset) -> None:
        slugs = {entry.slug for entry in real_dataset}
        for entry in real_dataset:
            for reference in entry.see_also:
                target = real_dataset.get(reference)
                assert target is not None and target.slug in slugs

    def test_copy_buttons_exist_for_each_snippet(self, page: str, real_dataset: Dataset) -> None:
        assert page.count('class="copy"') == 3 * len(real_dataset)

    def test_accessibility_affordances_are_present(self, page: str) -> None:
        for fragment in ('class="skip-link"', 'aria-live="polite"', 'aria-label="Function index"',
                         'role="combobox"', 'aria-labelledby="h-'):
            assert fragment in page, fragment

    def test_combobox_targets_are_real_options(self, page: str, real_dataset: Dataset) -> None:
        """aria-activedescendant is only valid if it points at a role="option" node."""
        assert 'role="listbox"' in page
        assert page.count('role="option"') == len(real_dataset)


class TestEmbeddedData:
    def test_json_island_parses(self, page: str) -> None:
        data = embedded_data(page)
        assert isinstance(data["entries"], list)

    def test_island_matches_the_dataset(self, page: str, real_dataset: Dataset) -> None:
        data = embedded_data(page)
        assert [item["name"] for item in data["entries"]] == [e.name for e in real_dataset]
        assert all({"name", "slug", "category", "summary", "tags", "gist"} <= set(item)
                   for item in data["entries"])

    def test_island_tags_are_lowercased_for_client_matching(self, page: str) -> None:
        for item in embedded_data(page)["entries"]:
            assert all(tag == tag.lower() for tag in item["tags"])

    def test_script_close_sequences_are_escaped(self) -> None:
        dataset = Dataset((make_entry(summary="Ends a tag </script> inside prose safely."),))
        html = build_page(dataset)
        island = re.search(
            r'<script id="cheatsheet-data" type="application/json">(.*?)</script>', html, re.S
        )
        assert island and "</script>" not in island.group(1)
        assert json.loads(island.group(1).replace("<\\/", "</"))


class TestEscaping:
    def test_html_metacharacters_in_data_are_escaped(self) -> None:
        dataset = Dataset((make_entry(name="ST_Example", srid_notes='Use <b> & "quotes" carefully.'),))
        html = build_page(dataset)
        assert "Use &lt;b&gt; &amp; &quot;quotes&quot; carefully." in html

    def test_operator_names_render_escaped(self) -> None:
        dataset = Dataset((make_entry(name="&&", category="operators"),))
        html = build_page(dataset)
        assert 'id="op-amp-amp"' in html
        assert ">&amp;&amp;<" in html


class TestCardRendering:
    def test_card_shows_the_gist_badge(self) -> None:
        html = render_card(make_entry())
        assert 'class="pill pill--gist"' in html

    def test_card_shows_the_no_index_badge(self) -> None:
        entry = make_entry(index_usage={
            "gist": False, "sargable": False, "needs_bbox_prefilter": False, "notes": "n"
        })
        assert "no index" in render_card(entry)

    def test_card_omits_the_argument_table_when_there_are_none(self) -> None:
        assert "<h3>Arguments</h3>" not in render_card(make_entry(arguments=[]))

    def test_card_includes_the_sql_result(self) -> None:
        assert 'class="snippet snippet--result"' in render_card(make_entry())

    def test_card_links_the_guide_when_present(self) -> None:
        entry = make_entry(docs_url="https://www.postgis-python.com/advanced-gist-indexing-optimization/")
        assert "advanced-gist-indexing-optimization" in render_card(entry)


class TestWriteSite:
    def test_writes_index_html(self, tiny_dataset: Dataset, tmp_path: Path) -> None:
        target = write_site(tiny_dataset, tmp_path / "dist")
        assert target == tmp_path / "dist" / "index.html"
        assert target.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")

    def test_creates_nested_directories(self, tiny_dataset: Dataset, tmp_path: Path) -> None:
        target = write_site(tiny_dataset, tmp_path / "a" / "b" / "c")
        assert target.is_file()

    def test_custom_title_is_used_and_escaped(self, tiny_dataset: Dataset, tmp_path: Path) -> None:
        html = write_site(tiny_dataset, tmp_path, title="A & B").read_text(encoding="utf-8")
        assert "<title>A &amp; B</title>" in html

    def test_empty_dataset_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(BuildError, match="empty dataset"):
            write_site(Dataset(()), tmp_path)

    def test_unwritable_destination_reports_clearly(self, tiny_dataset: Dataset, tmp_path: Path) -> None:
        blocker = tmp_path / "blocked"
        blocker.write_text("not a directory", encoding="utf-8")
        with pytest.raises(BuildError, match="cannot write site"):
            write_site(tiny_dataset, blocker)
