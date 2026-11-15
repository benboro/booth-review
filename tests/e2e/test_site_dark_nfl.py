"""DARK-01 (17-05): the NFL charts and detail panel repaint dark on a live flip.

One test per view: open in light, click the real #theme-toggle (no reload), then check the
shared frame colours, zoom kept, and no white boxes. Synthetic NFL fixture only.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from dark_checks import chart_layout, click_toggle, rgb, set_theme, white_box_offenders
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

OpenNfl = Callable[..., None]

PAGE_BG = "#191D1C"
GRID = "#333A38"
MUTED = "#9EA8A4"
SURFACE = "#212625"
INK = "#E5EAE8"

_READY = {
    "teams": "window.__nflTestHooks.getViewModel('teams') !== null",
    "scatter": "window.__nflTestHooks.getViewModel('scatter') !== null",
    "viewership": "window.__nflTestHooks.getViewModel('viewership') !== null",
    "crews": "window.__nflTestHooks.getViewModel('crews') !== null",
}


@pytest.mark.parametrize("view", ["teams", "scatter", "viewership", "crews"])
def test_nfl_view_repaints_dark_after_toggle_click(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl, view: str
) -> None:
    open_nfl_app(nfl_guarded_page, f"?sport=nfl&view={view}")
    nfl_guarded_page.wait_for_function(_READY[view])
    sel = f"#nfl-view-{view} .js-plotly-plot"
    nfl_guarded_page.locator(sel).first.wait_for(state="attached")
    before = chart_layout(nfl_guarded_page, sel)
    click_toggle(nfl_guarded_page)
    assert nfl_guarded_page.evaluate("document.documentElement.dataset.theme") == "dark"
    after = chart_layout(nfl_guarded_page, sel)
    assert after["paper"] == PAGE_BG and after["plot"] == PAGE_BG, after
    assert after["font"] in (MUTED, INK), after  # NFL charts use ink for axis titles
    assert after["hoverBg"] == SURFACE and after["hoverInk"] == INK, after
    assert after["gridY"] == GRID, after
    assert after["xrange"] == before["xrange"] and after["yrange"] == before["yrange"]
    assert white_box_offenders(nfl_guarded_page) == []


def test_nfl_special_games_bars_repaint_dark_after_toggle_click(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl
) -> None:
    """The first tab with "Special games only" on (the old Special games bars)."""
    open_nfl_app(nfl_guarded_page, "?sport=nfl&special=1")
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('teams').mode === 'special'"
    )
    sel = "#nfl-view-teams .js-plotly-plot"
    nfl_guarded_page.locator(sel).first.wait_for(state="attached")
    before = chart_layout(nfl_guarded_page, sel)
    click_toggle(nfl_guarded_page)
    after = chart_layout(nfl_guarded_page, sel)
    assert after["paper"] == PAGE_BG and after["plot"] == PAGE_BG, after
    assert after["gridY"] == GRID, after
    assert after["xrange"] == before["xrange"] and after["yrange"] == before["yrange"]
    assert white_box_offenders(nfl_guarded_page) == []


def test_nfl_all_games_bars_take_the_dark_family_colours(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl
) -> None:
    """A live flip repaints the network groups and their chips in the dark family palette."""
    page = nfl_guarded_page
    open_nfl_app(page, "?sport=nfl")
    page.wait_for_function("window.__nflTestHooks.getViewModel('teams').drawn === true")
    click_toggle(page)
    page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
    got = page.evaluate(
        """async () => {
          const P = await import('./sports/nfl/palette.js');
          const gd = document.querySelector('#nfl-view-teams .nfl-chart > div');
          const solid = new Set(gd.data.filter(t => t.xaxis === 'x')
            .flatMap(t => t.marker.color.filter((c, k) => t.x[k] > 0 && c.startsWith('#'))));
          const chips = [...document.querySelectorAll('#nfl-view-teams .legend-chips button')]
            .map(b => [b.dataset.family, b.style.getPropertyValue('--mark')]);
          const want = chips.map(([f]) => [f, P.familyColor(f, 'dark')]);
          return { solid: [...solid], chips, want, light: P.familyColor('fox', 'light') }; }"""
    )
    assert got["chips"] == got["want"]
    assert set(got["solid"]) <= {color for _, color in got["want"]}
    assert got["light"] not in got["solid"]


@pytest.mark.parametrize("view", ["scatter", "viewership"])
def test_nfl_band_fill_follows_theme(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl, view: str
) -> None:
    open_nfl_app(nfl_guarded_page, f"?sport=nfl&view={view}")
    nfl_guarded_page.wait_for_function(_READY[view])
    sel = f"#nfl-view-{view} .js-plotly-plot"
    nfl_guarded_page.locator(sel).first.wait_for(state="attached")
    set_theme(nfl_guarded_page, "dark")
    fills = [s["fill"] for s in chart_layout(nfl_guarded_page, sel)["shapes"] if s["fill"]]
    # The warm dark band tint, never the light-theme grey.
    assert all(f != "rgba(156, 163, 175, 0.12)" for f in fills), fills
    assert not any("156, 163, 175" in f for f in fills), fills


def test_nfl_open_panel_repaints_on_flip_and_on_reopen(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl
) -> None:
    open_nfl_app(nfl_guarded_page, "?sport=nfl&view=scatter")
    nfl_guarded_page.evaluate("window.__nflTestHooks.openGame(0)")
    panel = nfl_guarded_page.locator("#nfl-detail-panel")
    panel.wait_for(state="visible")
    palette = nfl_guarded_page.evaluate(
        "import(new URL('./modules/palette.js', location.href).href)"
        ".then(p => ({family: p.FAMILY_COLORS.dark}))"
    )
    set_theme(nfl_guarded_page, "dark")
    js = (
        "Array.from(document.querySelectorAll('#nfl-detail-panel .net-dot[data-family],"
        " #nfl-detail-panel .pill[data-family]')).map(e => [e.dataset.family,"
        " getComputedStyle(e).backgroundColor])"
    )
    paints = nfl_guarded_page.evaluate(js)
    logos = nfl_guarded_page.evaluate(
        "Array.from(document.querySelectorAll('#nfl-detail-panel img.net-logo'))"
        ".map(i => i.getAttribute('src'))"
    )
    assert paints or logos, "the open NFL panel shows no network dot, pill or logo"
    for family, bg in paints:
        assert bg == rgb(palette["family"][family]), (family, bg)
    for src in logos:
        assert "/dark/" in src, src
    nfl_guarded_page.evaluate("window.__nflTestHooks.closePanel()")
    nfl_guarded_page.evaluate("window.__nflTestHooks.openGame(0)")
    for family, bg in nfl_guarded_page.evaluate(js):
        assert bg == rgb(palette["family"][family]), (family, bg)
