"""D-11 booth tier wording (Phase 10, plan 10-07), proven on the synthetic booth overlay:
the model line, the custom tooltip, the Plotly-fallback hover text, the detail panel and
compare mode. Plain Other and untiered games show no line.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

EXPECTED = {
    8: "Lead ESPN/ABC crew, 2026",
    5: "Lead FOX crew, 2025",
    14: "Lead ESPN/ABC crew, 2021",
    9: "No. 2 FOX crew, 2026",
    13: "No. 2 ESPN/ABC crew, 2021",
    15: "Lead Conference Network crew, 2021",
    4: None,
    0: None,
}

_MODEL_JS = """
async ([i]) => {
  const { tooltipModel } = await import(new URL('./modules/tooltip.js', location.href).href);
  return tooltipModel(window.__testHooks.data, i, { axis: 'spread' }).boothLine;
}
"""

_SHOW_JS = """
async ([i]) => {
  const { showTooltip } = await import(new URL('./modules/tooltip.js', location.href).href);
  const opts = { axis: 'spread', theme: 'light', clientX: 200, clientY: 200 };
  showTooltip(window.__testHooks.data, i, { ...opts, selected: new Set() });
}
"""

_HOVER_JS = """
async ([i]) => {
  const { hoverText } = await import(new URL('./modules/chart.js', location.href).href);
  return hoverText(window.__testHooks.data, i, { axis: 'spread', y: 'viewers', theme: 'light' });
}
"""


def _open(
    page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    serve_booths(page)
    open_app(page, "")


@pytest.mark.parametrize(("index", "label"), sorted(EXPECTED.items()))
def test_tooltip_model_line(
    guarded_page: Page,
    serve_booths: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
    index: int,
    label: str | None,
) -> None:
    _open(guarded_page, serve_booths, open_app)
    assert guarded_page.evaluate(_MODEL_JS, [index]) == label


def test_tooltip_shows_lead_line(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    _open(guarded_page, serve_booths, open_app)
    guarded_page.evaluate(_SHOW_JS, [8])
    line = guarded_page.locator("#chart-tooltip .tooltip-booth")
    assert line.count() == 1
    assert line.text_content() == "Lead ESPN/ABC crew, 2026"


def test_conference_lead_in_tooltip_and_panel(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    _open(guarded_page, serve_booths, open_app)
    guarded_page.evaluate(_SHOW_JS, [15])
    tip = guarded_page.locator("#chart-tooltip .tooltip-booth")
    assert tip.text_content() == "Lead Conference Network crew, 2021"
    guarded_page.evaluate("window.__testHooks.openPanel(15)")
    panel = guarded_page.locator(".panel-booth")
    assert panel.count() == 1
    assert panel.text_content() == "Lead Conference Network crew, 2021"


def test_panel_shows_line(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    _open(guarded_page, serve_booths, open_app)
    guarded_page.evaluate("window.__testHooks.openPanel(8)")
    assert guarded_page.locator(".panel-booth").text_content() == "Lead ESPN/ABC crew, 2026"


@pytest.mark.parametrize("index", [4, 0])
def test_other_and_untiered_show_nothing(
    guarded_page: Page,
    serve_booths: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
    index: int,
) -> None:
    _open(guarded_page, serve_booths, open_app)
    guarded_page.evaluate(_SHOW_JS, [index])
    assert guarded_page.locator("#chart-tooltip .tooltip-booth").count() == 0
    guarded_page.evaluate(f"window.__testHooks.openPanel({index})")
    assert guarded_page.locator(".panel-booth").count() == 0


def test_fallback_hover_text_matches(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    _open(guarded_page, serve_booths, open_app)
    assert "No. 2 FOX crew, 2026" in guarded_page.evaluate(_HOVER_JS, [9])
    assert "crew, 20" not in guarded_page.evaluate(_HOVER_JS, [4])


def test_compare_mode_still_shows_line(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    _open(guarded_page, serve_booths, open_app)
    guarded_page.evaluate(
        "() => window.__testHooks.setState({ people: ['dale-harlow', 'casey-lund'] })"
    )
    guarded_page.evaluate(_SHOW_JS, [8])
    assert (
        guarded_page.locator("#chart-tooltip .tooltip-booth").text_content()
        == "Lead ESPN/ABC crew, 2026"
    )
    guarded_page.evaluate("window.__testHooks.openPanel(8)")
    assert guarded_page.locator(".panel-booth").text_content() == "Lead ESPN/ABC crew, 2026"
