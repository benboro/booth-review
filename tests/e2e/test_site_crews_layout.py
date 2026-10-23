"""Crews table layout and style (V14-9, V14-10) at 1440, 1104, 1024, 768 and 390px.

Row and header heights hold on hover, focus, sort and mode switch; the module gaps measure
8px and 16px; only the 12/14/20px font sizes appear; numerics are right-aligned and tabular;
no vertical rules; every logo has alt, title, width and height. Synthetic data only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from conftest import element_height, logo_images, measure_gap
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

WIDTHS = [1440, 1104, 1024, 768, 390]

_HEIGHTS_JS = """
() => {
  const out = {};
  for (const tr of document.querySelectorAll('#crews-panel tbody tr.crews-row')) {
    out[tr.getAttribute('data-crew-key')] = Math.round(tr.getBoundingClientRect().height * 10) / 10;
  }
  const th = document.querySelector('#crews-panel thead tr');
  return { rows: out, head: Math.round(th.getBoundingClientRect().height * 10) / 10 };
}
"""

_FONTS_JS = """
() => [...new Set([...document.querySelectorAll('#crews-panel, #crews-panel *')]
  .filter((el) => el.offsetParent !== null || el.id === 'crews-panel')
  .filter((el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()))
  .map((el) => getComputedStyle(el).fontSize))]
"""

_NUMERIC_JS = """
() => [...document.querySelectorAll('#crews-panel td.num, #crews-panel th.num')].map((el) => {
  const cs = getComputedStyle(el);
  return { align: cs.textAlign, nums: cs.fontVariantNumeric };
})
"""

_NUMERIC_HEADS_JS = """
() => {
  const tbl = document.querySelector('#crews-panel table');
  const firstRow = tbl.tBodies[0].rows[0];
  return [...tbl.tHead.rows[0].cells].map((th, c) => ({
    num: firstRow.cells[c] && firstRow.cells[c].classList.contains('num'),
    align: getComputedStyle(th).textAlign,
    nums: getComputedStyle(th).fontVariantNumeric,
    text: th.textContent.trim(),
  }));
}
"""

# UI-SPEC phone layout: the pinned Crew or Person column keeps a 1px right divider (the only
# vertical rule allowed, at 480px and below).
_BORDERS_JS = """
() => [...document.querySelectorAll('#crews-panel th, #crews-panel td')].filter((el) => {
  if (window.innerWidth <= 480 && el.cellIndex === 1 && el.closest('tr').cells.length > 2) {
    return false;
  }
  const cs = getComputedStyle(el);
  return parseFloat(cs.borderLeftWidth) > 0 || parseFloat(cs.borderRightWidth) > 0;
}).length
"""


@pytest.fixture
def app(
    guarded_page: Page,
    serve_crews: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> Page:
    serve_crews(guarded_page)
    guarded_page.set_viewport_size({"width": 1440, "height": 900})
    open_app(guarded_page, "?view=crews")
    return guarded_page


def _at(page: Page, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    page.wait_for_timeout(200)


def _heights(page: Page) -> dict[str, Any]:
    out: dict[str, Any] = page.evaluate(_HEIGHTS_JS)
    return out


def _assert_same(before: dict[str, Any], after: dict[str, Any], what: str) -> None:
    assert after["head"] == before["head"], f"header height moved on {what}"
    for key, h in after["rows"].items():
        if key in before["rows"]:
            assert h == before["rows"][key], f"row {key} height moved on {what}"


@pytest.mark.parametrize("width", WIDTHS)
def test_heights_hold_on_hover_focus_sort_and_mode_switch(app: Page, width: int) -> None:
    _at(app, width)
    base = _heights(app)
    assert base["rows"], "Crews table rendered no rows"
    rows = app.locator("#crews-panel tbody tr.crews-row")

    rows.nth(1).hover()
    _assert_same(base, _heights(app), "hover")

    rows.nth(2).focus()
    _assert_same(base, _heights(app), "focus")

    app.locator("#crews-panel button[data-sort-key=viewers]").click()
    app.wait_for_timeout(100)
    sorted_h = _heights(app)
    assert sorted_h["head"] == base["head"], "header height moved on sort"
    _assert_same(base, sorted_h, "sort")

    app.locator("#crews-panel .crews-mode button[data-cmode=pbp]").click()
    app.locator("#crews-panel .crews-mode button[data-cmode=crew]").click()
    app.wait_for_timeout(100)
    back = _heights(app)
    assert back["head"] == base["head"], "header height moved on mode switch"
    _assert_same(sorted_h, back, "mode switch")


@pytest.mark.parametrize("width", WIDTHS)
def test_module_gaps_are_8_and_16(app: Page, width: int) -> None:
    _at(app, width)
    assert measure_gap(app, "#toolbar", "#selection-row") == pytest.approx(8, abs=0.5)
    assert measure_gap(app, "#chart-tabs", "#chart-module") == pytest.approx(16, abs=0.5)
    assert element_height(app, "#crews-panel") > 0


@pytest.mark.parametrize("width", WIDTHS)
def test_only_12_14_20_font_sizes(app: Page, width: int) -> None:
    _at(app, width)
    sizes: list[str] = app.evaluate(_FONTS_JS)
    assert sizes
    assert set(sizes) <= {"12px", "14px", "20px"}, sizes


@pytest.mark.parametrize("width", WIDTHS)
def test_numerics_right_aligned_tabular_and_no_vertical_rules(app: Page, width: int) -> None:
    _at(app, width)
    cells: list[dict[str, str]] = app.evaluate(_NUMERIC_JS)
    assert cells
    for c in cells:
        assert c["align"] in {"right", "end"}, c
        assert "tabular-nums" in c["nums"], c
    heads: list[dict[str, Any]] = app.evaluate(_NUMERIC_HEADS_JS)
    numeric_heads = [h for h in heads if h["num"]]
    assert numeric_heads
    for h in numeric_heads:
        assert h["align"] in {"right", "end"}, h
    assert app.evaluate(_BORDERS_JS) == 0


@pytest.mark.parametrize("width", WIDTHS)
def test_logo_images_carry_alt_title_and_size(app: Page, width: int) -> None:
    _at(app, width)
    attrs: list[dict[str, Any]] = app.evaluate(
        """() => [...document.querySelectorAll('#crews-panel img')].map((img) => ({
          alt: img.getAttribute('alt'), title: img.getAttribute('title'),
          w: img.getAttribute('width'), h: img.getAttribute('height') }))"""
    )
    # The Crews table carries no logo marks today; every img that does appear must be complete.
    for a in attrs:
        assert a["alt"], a
        assert a["title"], a
        assert a["w"], a
        assert a["h"], a
    assert len(logo_images(app, "#crews-panel")) == len(attrs)
    assert app.locator("#crews-panel tbody tr.crews-row").count() > 0


# -- 14-10: the +N count stays clear of wide network logos ------------------------------------

_PLUS_N_JS = """
async ([id, name, family]) => {
  const { networkMark } = await import('./modules/network.js');
  const td = document.querySelector('#crews-panel tbody tr.crews-row td.crews-network');
  td.className = 'crews-network has-more';
  td.replaceChildren(networkMark({ id, name, family }));
  const more = document.createElement('span');
  more.className = 'crews-more-nets caption';
  more.textContent = '+5';
  td.append(more);
  const cs = getComputedStyle(td);
  const content = td.getBoundingClientRect().right - parseFloat(cs.paddingRight);
  const mark = td.querySelector('.net-mark').getBoundingClientRect();
  const img = td.querySelector('img');
  const visual = img ? img.getBoundingClientRect() : mark;
  const m = more.getBoundingClientRect();
  return { imgRight: visual.right, markRight: mark.right, moreLeft: m.left, moreRight: m.right,
           contentRight: content, text: more.textContent, imgW: visual.width, imgH: visual.height,
           ratio: img ? img.naturalWidth / (img.naturalHeight || 1) : 0 };
}
"""

# The wide logos plus a text network that is cut with an ellipsis (Pac-12 has no vendored mark).
_WIDE_NETWORKS = [
    ("espn2", "ESPN2", "espn"),
    ("espn-plus", "ESPN+", "espn"),
    ("sec-network", "SEC Network", "espn"),
    ("cbs-sports-network", "CBS Sports Network", "cbs"),
    ("acc-network", "ACC Network", "espn"),
    ("espnews", "ESPNEWS", "espn"),
    ("pac-12-network", "Pac-12 Network", "other"),
]


@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize(("net_id", "name", "family"), _WIDE_NETWORKS)
def test_plus_n_count_never_overlaps_a_wide_logo(
    app: Page, width: int, net_id: str, name: str, family: str
) -> None:
    _at(app, width)
    m = app.evaluate(_PLUS_N_JS, [net_id, name, family])
    assert m["text"] == "+5"
    assert m["imgRight"] <= m["moreLeft"] + 0.5, f"{name}: the logo covers the +N count"
    assert m["moreRight"] <= m["contentRight"] + 0.5, f"{name}: the +N count is clipped"
    assert m["markRight"] <= m["moreLeft"] + 0.5


# -- 14-10: the sort glyph sits beside the label on right-aligned number heads ----------------

_GLYPH_JS = """
() => [...document.querySelectorAll('#crews-panel th.num')].map((th) => {
  const label = th.querySelector('.crews-sort-label');
  const glyph = th.querySelector('.sort-glyph').getBoundingClientRect();
  const lines = [...label.getClientRects()];
  const last = lines[lines.length - 1];
  const cs = getComputedStyle(th);
  const numRight = th.getBoundingClientRect().right - parseFloat(cs.paddingRight);
  return { text: label.textContent, lines: lines.length, gap: glyph.left - last.right,
           labelRight: last.right, numRight,
           dy: Math.abs((glyph.top + glyph.bottom) / 2 - (last.top + last.bottom) / 2) };
})
"""


@pytest.mark.parametrize("width", WIDTHS)
def test_sort_glyph_follows_the_label_on_number_heads(app: Page, width: int) -> None:
    _at(app, width)
    heads: list[dict[str, Any]] = app.evaluate(_GLYPH_JS)
    assert len(heads) >= 3
    for h in heads:
        assert 0 <= h["gap"] <= 8, f"{h['text']}: the sort glyph is {h['gap']}px from its label"
        assert h["dy"] <= 8, f"{h['text']}: the sort glyph is off the label's last line"
        edge = h["labelRight"] - h["numRight"]
        assert abs(edge) <= 1, f"{h['text']}: label is {edge}px off the numbers' edge"
