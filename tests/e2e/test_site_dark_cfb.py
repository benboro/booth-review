"""DARK-01 (17-05): the CFB charts, strips, controls, pills, legend and open panels in dark.

Each test flips the theme on a live page (no reload) and checks the colours the UI-SPEC
"Plotly theming (D-11)" table sets. Synthetic fixture only; the page guard fails any
request that leaves the origin.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from dark_checks import chart_layout, click_toggle, rgb, set_theme, white_box_offenders
from playwright.sync_api import Page
from test_site_chart import _hover_dot

pytestmark = pytest.mark.e2e

OpenApp = Callable[[Page, str], None]

PAGE_BG = "#1D1B18"
GRID = "#3A3632"
MUTED = "#A59E94"
SURFACE = "#26231F"
INK = "#ECE7DF"

_PALETTE_JS = """
async () => {
  const p = await import(new URL('./modules/palette.js', location.href).href);
  return { family: p.FAMILY_COLORS.dark, pillText: p.PILL_TEXT_COLOR.dark,
           mapFamily: p.MAP_FAMILY_COLORS.dark };
}
"""


def _palette(page: Page) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = page.evaluate(_PALETTE_JS)
    return result


def _assert_dark_frame(page: Page, selector: str = "#chart") -> None:
    lay = chart_layout(page, selector)
    assert lay["paper"] == PAGE_BG and lay["plot"] == PAGE_BG, lay
    assert lay["font"] == MUTED, lay
    assert lay["gridY"] == GRID, lay
    assert lay["tick"] == MUTED, lay
    assert lay["hoverBg"] == SURFACE and lay["hoverInk"] == INK, lay


def test_scatter_repaints_dark_after_toggle_click_and_keeps_zoom(
    guarded_page: Page, open_app: OpenApp
) -> None:
    open_app(guarded_page, "")
    before = chart_layout(guarded_page)
    click_toggle(guarded_page)
    assert guarded_page.evaluate("document.documentElement.dataset.theme") == "dark"
    _assert_dark_frame(guarded_page)
    after = chart_layout(guarded_page)
    assert after["xrange"] == before["xrange"] and after["yrange"] == before["yrange"]
    assert white_box_offenders(guarded_page) == []


def test_scatter_tooltip_is_dark_ink_on_surface(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, "")
    set_theme(guarded_page, "dark")
    _hover_dot(guarded_page, 0)
    tip = guarded_page.evaluate(
        "(() => { const t = document.getElementById('chart-tooltip');"
        " const s = getComputedStyle(t); return [s.backgroundColor, s.color]; })()"
    )
    assert tip == [rgb(SURFACE), rgb(INK)]
    assert white_box_offenders(guarded_page) == []


def test_strips_and_reset_zoom_in_dark(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, "")
    set_theme(guarded_page, "dark")
    shapes = chart_layout(guarded_page)["shapes"]
    assert any(s["type"] == "rect" and s["fill"] == SURFACE for s in shapes), shapes
    assert any(s["type"] == "line" and s["line"] == GRID for s in shapes), shapes
    label = guarded_page.evaluate(
        "(() => { const s = getComputedStyle(document.querySelector('.band-info'));"
        " return s.color; })()"
    )
    assert label == rgb(MUTED)
    reset = guarded_page.evaluate(
        "(() => { const s = getComputedStyle(document.getElementById('reset-zoom'));"
        " const r = getComputedStyle(document.documentElement);"
        " return [s.color, s.borderTopColor,"
        " r.getPropertyValue('--ink').trim(), r.getPropertyValue('--rule-strong').trim(),"
        " r.getPropertyValue('--disabled').trim()]; })()"
    )
    # At the home range Reset zoom is disabled, so its label takes --disabled.
    assert reset[0] == rgb(reset[4]) and reset[1] == rgb(reset[3]), reset
    assert white_box_offenders(guarded_page) == []


def test_excitement_strip_in_dark(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, "?axis=excitement")
    set_theme(guarded_page, "dark")
    shapes = chart_layout(guarded_page)["shapes"]
    assert any(s["type"] == "rect" and s["fill"] == SURFACE for s in shapes), shapes
    assert white_box_offenders(guarded_page) == []


def test_bars_and_butterfly_dark_tone_a_and_no_white_boxes(
    guarded_page: Page, open_app: OpenApp
) -> None:
    for query in ("?school=northfield&view=bars", "?school=northfield,lakeview&view=butterfly"):
        open_app(guarded_page, query)
        click_toggle(guarded_page)
        _assert_dark_frame(guarded_page, "#bars-chart")
        colors = guarded_page.evaluate(
            "Array.from(document.querySelectorAll('#bars-chart .trace.bars .point path'))"
            ".map(p => getComputedStyle(p).fill)"
        )
        family = {rgb(v) for v in _palette(guarded_page)["family"].values()}
        assert colors and any(c in family for c in colors), (query, colors)
        assert white_box_offenders(guarded_page) == []
        click_toggle(guarded_page)  # leave light for the next navigation


def test_legend_dots_pills_and_network_dots_repaint_without_reload(
    guarded_page: Page, open_app: OpenApp
) -> None:
    open_app(guarded_page, "?school=northfield")
    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    guarded_page.locator("#detail-panel").wait_for(state="visible")
    palette = _palette(guarded_page)
    set_theme(guarded_page, "dark")
    legend = guarded_page.evaluate(
        "Array.from(document.querySelectorAll('#legend-chips .legend-chip')).map(c =>"
        " [c.dataset.family, getComputedStyle(c.querySelector('.legend-dot')).backgroundColor])"
    )
    assert legend
    for family, color in legend:
        assert color == rgb(palette["family"][family]), (family, color)
    paints = guarded_page.evaluate(
        """Array.from(document.querySelectorAll(
            '#detail-panel .pill[data-family], #detail-panel .net-dot[data-family]'))
            .map(e => [e.className, e.dataset.family, getComputedStyle(e).backgroundColor,
                       getComputedStyle(e).color])"""
    )
    assert paints, "the open panel shows no family pill or dot"
    for cls, family, bg, fg in paints:
        assert bg == rgb(palette["family"][family]), (cls, family, bg)
        if "pill" in cls.split():
            assert fg == rgb(palette["pillText"][family]), (cls, family, fg)
    # Closing and reopening also shows dark.
    guarded_page.keyboard.press("Escape")
    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    again = guarded_page.evaluate(
        "Array.from(document.querySelectorAll('#detail-panel .pill[data-family]'))"
        ".map(e => [e.dataset.family, getComputedStyle(e).backgroundColor])"
    )
    for family, bg in again:
        assert bg == rgb(palette["family"][family])


def test_table_pills_repaint_without_reload(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, "?school=northfield")
    palette = _palette(guarded_page)
    set_theme(guarded_page, "dark")
    paints = guarded_page.evaluate(
        "Array.from(document.querySelectorAll('.pill[data-family]'))"
        ".map(e => [e.dataset.family, getComputedStyle(e).backgroundColor])"
    )
    for family, bg in paints:
        assert bg == rgb(palette["family"][family]), (family, bg)


def test_bars_counts_swatches_repaint(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, "?school=northfield&by=network&view=bars")
    guarded_page.locator("#bars-data summary").click()
    palette = _palette(guarded_page)
    set_theme(guarded_page, "dark")
    paints = guarded_page.evaluate(
        "Array.from(document.querySelectorAll('#bars-counts .pill[data-family],"
        " #bars-counts .net-dot[data-family]'))"
        ".map(e => [e.dataset.family, getComputedStyle(e).backgroundColor])"
    )
    assert paints, "the counts list shows no family pill or dot"
    for family, bg in paints:
        assert bg == rgb(palette["family"][family]), (family, bg)
