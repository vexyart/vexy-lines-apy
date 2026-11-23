# this_file: tests/test_print_guide.py
"""Check the published guide, including cross-links between its combined chapters."""

from html.parser import HTMLParser
from pathlib import Path


class GuideLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.chapters: list[str] = []
        self.fragments: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if anchor := attributes.get("id"):
            self.ids.append(anchor)
            if tag == "section" and "print-page" in attributes.get("class", "").split():
                self.chapters.append(anchor)
        if tag == "a" and (href := attributes.get("href")) and href.startswith("#") and len(href) > 1:
            self.fragments.add(href[1:])


def test_print_guide_contains_chapters_and_resolves_internal_links() -> None:
    root = Path(__file__).resolve().parents[1]
    guide = GuideLinks()
    guide.feed((root / "docs/print_page/index.html").read_text(encoding="utf-8"))
    chapters = {p.stem for p in (root / "src_docs").glob("*.md") if p.stem != "print_page"}
    assert set(guide.chapters) == chapters
    assert len(guide.ids) == len(set(guide.ids)), "Duplicate IDs make print links ambiguous"
    assert guide.fragments >= chapters
    assert not guide.fragments.difference(guide.ids), "Print links must resolve inside the combined guide"
