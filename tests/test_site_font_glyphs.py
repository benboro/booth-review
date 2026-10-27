"""The shipped heading subset carries every glyph the serif slots need."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from booth_review.build.serif_glyph_set import SERIF_CODEPOINTS

REPO_ROOT = Path(__file__).resolve().parents[1]
WOFF2 = REPO_ROOT / "site" / "fonts" / "lm-roman-demi-latin-600-normal.woff2"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "contract"

UI_SPEC_CODEPOINTS = {
    *range(0x20, 0x7F),
    *range(0xA0, 0x180),
    0x2013,
    0x2014,
    0x2018,
    0x2019,
    0x201C,
    0x201D,
    0x2026,
    0x02BB,
}

# Latin Modern itself has no glyph for these four Latin Extended-A letters (kra, n with a
# preceding apostrophe, and the two T-with-stroke forms); no team or person name uses them.
SOURCE_LACKS = {0x0138, 0x0149, 0x0166, 0x0167}

SERIF_LOOKUPS = {
    "site-data.fixture.json": [
        "teams",
        "conferences",
        "bowls",
        "bowl_franchises",
        "rivalries",
        "venues",
        "people",
    ],
    "nfl-data.fixture.json": ["franchises", "team_names", "venues", "people"],
    "mlb-data.fixture.json": ["clubs", "team_names", "leagues", "people"],
}


@pytest.fixture(scope="module")
def cmap() -> dict[int, str]:
    return dict(TTFont(WOFF2).getBestCmap())


def test_cmap_equals_generated_codepoint_set(cmap: dict[int, str]) -> None:
    assert set(cmap) == SERIF_CODEPOINTS


def test_cmap_carries_every_ui_spec_codepoint(cmap: dict[int, str]) -> None:
    assert set(cmap) >= UI_SPEC_CODEPOINTS - SOURCE_LACKS
    assert not set(cmap) & SOURCE_LACKS


def test_okina_is_aliased_to_the_left_quote_glyph(cmap: dict[int, str]) -> None:
    assert cmap[0x02BB] == cmap[0x2018]


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


@pytest.mark.parametrize("fixture", sorted(SERIF_LOOKUPS))
def test_fixture_serif_names_are_covered(fixture: str) -> None:
    lookups = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))["lookups"]
    names = [s for key in SERIF_LOOKUPS[fixture] for s in _strings(lookups[key])]
    assert names
    assert {ord(ch) for name in names for ch in name} <= SERIF_CODEPOINTS


def test_static_page_headings_are_covered() -> None:
    texts = []
    for path in [REPO_ROOT / "site" / "index.html"]:
        for match in re.finditer(r"<h[123][^>]*>(.*?)</h[123]>", path.read_text(), re.S):
            texts.append(re.sub(r"<[^>]+>", "", match.group(1)))
    for path in [REPO_ROOT / "docs" / "methodology.md", REPO_ROOT / "docs" / "known-gaps.md"]:
        texts += [line.lstrip("# ") for line in path.read_text().splitlines() if line[:1] == "#"]
    assert {ord(ch) for text in texts for ch in text} <= SERIF_CODEPOINTS
