"""Layer 1 required-text guard (SHELL-07): build-time rows of 12-REQUIRED-TEXT.

One fixture build (NFL and MLB on) is parsed with html.parser and each row is
checked by exact text and link target, so a re-skin cannot drop a licence line
before the browser tests are rewritten.

Test to row map:
- RT-01 test_rt01_credit_line_and_links (credit line and four links, every page)
- RT-07 test_rt07_retrosheet_notice_in_methodology
- RT-20 test_rt20_excitement_caption_static_text_href_and_hidden
- RT-21 test_rt21_era_note_static_text_and_href
- RT-23 test_rt23_trademark_line_on_every_page
- RT-24 test_rt24_type_line_and_licence_files
- RT-04 support: test_footer_child_order (the NFL/MLB footer swap depends on it)
- README licence statements: test_readme_states_logo_and_font_licences

RT-22 is covered by tests/test_site_pages.py and tests/test_site_assembly_nfl.py.
Synthetic fixtures only; the build never reads a real .env.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path

import pytest

from booth_review.build.site_assembly import (
    assemble_site,
    load_mlb_site_payload,
    load_nfl_site_payload,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_SRC = REPO_ROOT / "site"
DOCS = REPO_ROOT / "docs"
CONTRACT = REPO_ROOT / "tests" / "fixtures" / "contract"
CFB_FIXTURE = CONTRACT / "site-data.fixture.json"
NFL_FIXTURE = CONTRACT / "nfl-data.fixture.json"
MLB_FIXTURE = CONTRACT / "mlb-data.fixture.json"

PAGES = ("index.html", "methodology.html", "coverage.html")

# The credit line holds exactly three span.credit-item blocks, separated in the source by a
# single "\n" and no <br> (checker gap 1); CSS puts each on its own line.
RT01_ITEMS = [
    "Viewership: RatingsReference.com (CC BY 4.0), modified: filtered and joined with "
    "crew and game data",
    "Crews: 506 Sports",
    "Data provided by CollegeFootballData.com",
]
RT01_HREFS = [
    "https://ratingsreference.com",
    "https://creativecommons.org/licenses/by/4.0/",
    "https://506sports.com",
    "https://collegefootballdata.com",
]
RT07_TEXT = (
    "The information used here was obtained free of charge from and is copyrighted by "
    "Retrosheet. Interested parties may contact Retrosheet at www.retrosheet.org"
)
RT20_TEXT = "2025+ excitement uses CFBD's new win-probability model; see methodology."
RT21_TEXT = (
    "Nielsen changed how it measures viewing in 2020, 2025, and 2026, so compare seasons "
    "with care; see methodology."
)
RT23_TEXT = (
    "Network logos are trademarks of their owners, shown only to identify each network. "
    "Their use does not imply endorsement, and they are not covered by this site's MIT license."
)
RT24_TEXT = (
    "Type: Latin Modern (copyright 2003, 2009 B. Jackowski and J. M. Nowacki), "
    "used under the GUST Font License; Roboto "
    "(copyright 2011 The Roboto Project Authors) and Roboto Condensed "
    "(copyright 2011 Google Inc.), used under the SIL Open Font License 1.1."
)
RT24_HREFS = [
    "fonts/GUST-FONT-LICENSE.txt",
    "fonts/OFL-roboto.txt",
    "fonts/OFL-roboto-condensed.txt",
]

_VOID = {"meta", "link", "br", "img", "input", "hr", "source", "path", "circle", "rect"}


class Node:
    """One element: tag, attributes, child elements and the text beneath it."""

    def __init__(self, tag: str, attrs: dict[str, str | None], parent: Node | None) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[Node] = []
        self._chunks: list[str] = []

    @property
    def classes(self) -> list[str]:
        return (self.attrs.get("class") or "").split()

    @property
    def text(self) -> str:
        parts: list[str] = []
        for chunk in self._chunks:
            parts.append(chunk if isinstance(chunk, str) else chunk.text)
        return re.sub(r"\s+", " ", "".join(parts)).strip()

    def walk(self) -> Iterator[Node]:
        yield self
        for child in self.children:
            yield from child.walk()

    def find(self, tag: str, cls: str | None = None) -> list[Node]:
        return [n for n in self.walk() if n.tag == tag and (cls is None or cls in n.classes)]

    def by_id(self, ident: str) -> Node:
        found = [n for n in self.walk() if n.attrs.get("id") == ident]
        assert len(found) == 1, f"expected one #{ident}, found {len(found)}"
        return found[0]

    def links(self) -> list[Node]:
        return [n for n in self.walk() if n.tag == "a"]


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self._stack: list[Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, dict(attrs), self._stack[-1])
        self._stack[-1].children.append(node)
        self._stack[-1]._chunks.append(node)  # type: ignore[arg-type]
        if tag not in _VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, dict(attrs), self._stack[-1])
        self._stack[-1].children.append(node)
        self._stack[-1]._chunks.append(node)  # type: ignore[arg-type]

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data: str) -> None:
        self._stack[-1]._chunks.append(data)


def parse(path: Path) -> Node:
    collector = _Collector()
    collector.feed(path.read_text(encoding="utf-8"))
    return collector.root


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    work = tmp_path_factory.mktemp("required_text")
    out = work / "out"
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(work)  # never read a real .env
        mp.delenv("CFBD_API_KEY", raising=False)
        assemble_site(
            source=CFB_FIXTURE,
            out_dir=out,
            site_src=SITE_SRC,
            docs=DOCS,
            nfl=True,
            nfl_payload=load_nfl_site_payload(NFL_FIXTURE),
            mlb=True,
            mlb_payload=load_mlb_site_payload(MLB_FIXTURE),
        )
    return out


def _footer(built: Path, page: str) -> Node:
    footers = parse(built / page).find("footer")
    assert len(footers) == 1, f"{page}: expected one footer"
    return footers[0]


@pytest.mark.parametrize("page", PAGES)
def test_rt01_credit_line_and_links(built: Path, page: str) -> None:
    credit = _footer(built, page).find("p", "credit-line")
    assert len(credit) == 1
    items = credit[0].find("span", "credit-item")
    assert [i.text for i in items] == RT01_ITEMS
    assert credit[0].find("br") == []
    assert credit[0].text == " ".join(RT01_ITEMS)
    anchors = credit[0].links()
    assert [a.attrs.get("href") for a in anchors] == RT01_HREFS
    assert all(a.attrs.get("rel") == "noopener noreferrer" for a in anchors)


def test_rt07_retrosheet_notice_in_methodology(built: Path) -> None:
    root = parse(built / "methodology.html")
    hits = [p for p in root.walk() if p.tag == "p" and RT07_TEXT in p.text]
    assert hits, "RT-07 Retrosheet credit line missing from methodology.html"


def test_rt20_excitement_caption_static_text_href_and_hidden(built: Path) -> None:
    node = parse(built / "index.html").by_id("excitement-caption")
    assert node.text == RT20_TEXT
    assert "hidden" in node.attrs
    assert [a.attrs.get("href") for a in node.links()] == [
        "methodology.html#the-2025-excitement-break"
    ]


def test_rt21_era_note_static_text_and_href(built: Path) -> None:
    node = parse(built / "index.html").by_id("era-note")
    assert node.text == RT21_TEXT
    assert [a.attrs.get("href") for a in node.links()] == ["methodology.html#measurement-eras"]


@pytest.mark.parametrize("page", PAGES)
def test_rt23_trademark_line_on_every_page(built: Path, page: str) -> None:
    footer = _footer(built, page)
    lines = footer.find("p", "trademark-line")
    assert len(lines) == 1
    assert lines[0].text == RT23_TEXT
    assert lines[0].parent is footer
    for other in ("freshness", "credit-line"):
        assert RT23_TEXT not in footer.find("p", other)[0].text


@pytest.mark.parametrize("page", PAGES)
def test_rt24_type_line_and_licence_files(built: Path, page: str) -> None:
    lines = _footer(built, page).find("p", "type-line")
    assert len(lines) == 1
    assert lines[0].text == RT24_TEXT
    hrefs = [a.attrs.get("href") for a in lines[0].links()]
    assert hrefs == RT24_HREFS
    for href in RT24_HREFS:
        target = built / href
        assert target.is_file(), f"{href} missing from the build output"
        assert target.stat().st_size > 0


@pytest.mark.parametrize("page", PAGES)
def test_footer_child_order(built: Path, page: str) -> None:
    footer = _footer(built, page)
    order = [(c.tag, c.classes[0] if c.classes else None) for c in footer.children]
    assert order == [
        ("nav", None),
        ("p", "freshness"),
        ("p", "credit-line"),
        ("p", "trademark-line"),
        ("p", "type-line"),
    ]


def test_readme_states_logo_and_font_licences() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "not covered by the MIT license" in readme
    assert "SIL Open Font License 1.1" in readme
