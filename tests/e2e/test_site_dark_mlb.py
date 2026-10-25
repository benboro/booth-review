"""DARK-01 (17-05): the MLB charts, tables and detail panel repaint dark on a live flip.

Synthetic MLB fixture only; every flip is on a live page (no reload).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from dark_checks import chart_layout, click_toggle, rgb, set_theme, white_box_offenders
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

OpenMlb = Callable[..., None]

PAGE_BG = "#1D1B18"
GRID = "#3A3632"
MUTED = "#A59E94"
SURFACE = "#26231F"
INK = "#ECE7DF"


def test_mlb_scatter_repaints_dark_after_toggle_click(
    mlb_guarded_page: Page, open_mlb_app: OpenMlb
) -> None:
    open_mlb_app(mlb_guarded_page, "?sport=mlb&view=scatter")
    mlb_guarded_page.wait_for_function("window.__mlbTestHooks.getViewModel('scatter') !== null")
    sel = "#mlb-view-scatter .js-plotly-plot"
    mlb_guarded_page.locator(sel).first.wait_for(state="attached")
    before = chart_layout(mlb_guarded_page, sel)
    click_toggle(mlb_guarded_page)
    assert mlb_guarded_page.evaluate("document.documentElement.dataset.theme") == "dark"
    after = chart_layout(mlb_guarded_page, sel)
    assert after["paper"] == PAGE_BG and after["plot"] == PAGE_BG, after
    assert after["font"] in (MUTED, INK), after
    assert after["hoverBg"] == SURFACE and after["hoverInk"] == INK, after
    assert after["gridY"] == GRID, after
    assert after["xrange"] == before["xrange"] and after["yrange"] == before["yrange"]
    assert white_box_offenders(mlb_guarded_page) == []


@pytest.mark.parametrize("view", ["apple", "postseason"])
def test_mlb_table_views_have_no_white_boxes_in_dark(
    mlb_guarded_page: Page, open_mlb_app: OpenMlb, view: str
) -> None:
    open_mlb_app(mlb_guarded_page, f"?sport=mlb&view={view}")
    mlb_guarded_page.wait_for_function(f"window.__mlbTestHooks.getViewModel('{view}') !== null")
    click_toggle(mlb_guarded_page)
    assert mlb_guarded_page.evaluate("document.documentElement.dataset.theme") == "dark"
    bg = mlb_guarded_page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert bg == rgb(PAGE_BG)
    assert white_box_offenders(mlb_guarded_page) == []


def test_mlb_open_panel_repaints_on_flip_and_on_reopen(
    mlb_guarded_page: Page, open_mlb_app: OpenMlb
) -> None:
    open_mlb_app(mlb_guarded_page, "?sport=mlb&view=scatter")
    mlb_guarded_page.evaluate("window.__mlbTestHooks.openGame(0)")
    panel = mlb_guarded_page.locator("#mlb-detail-panel, #nfl-detail-panel").first
    panel.wait_for(state="visible")
    palette = mlb_guarded_page.evaluate(
        "import(new URL('./modules/palette.js', location.href).href)"
        ".then(p => ({family: p.FAMILY_COLORS.dark}))"
    )
    set_theme(mlb_guarded_page, "dark")
    js = (
        "Array.from(document.querySelectorAll('dialog[open] .net-dot[data-family],"
        " dialog[open] .pill[data-family]')).map(e => [e.dataset.family,"
        " getComputedStyle(e).backgroundColor])"
    )
    paints = mlb_guarded_page.evaluate(js)
    logos = mlb_guarded_page.evaluate(
        "Array.from(document.querySelectorAll('dialog[open] img.net-logo'))"
        ".map(i => i.getAttribute('src'))"
    )
    assert paints or logos, "the open MLB panel shows no network dot, pill or logo"
    for family, bg in paints:
        assert bg == rgb(palette["family"][family]), (family, bg)
    for src in logos:
        assert "/dark/" in src, src
    mlb_guarded_page.evaluate("window.__mlbTestHooks.closePanel()")
    mlb_guarded_page.evaluate("window.__mlbTestHooks.openGame(0)")
    for family, bg in mlb_guarded_page.evaluate(js):
        assert bg == rgb(palette["family"][family]), (family, bg)
