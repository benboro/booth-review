"""Double-click / double-tap on the NFL legend chips (08 D-15), modeled on the CFB file.

Team-bar and scatter legends share `createOnlyDetector`: click toggles one chip,
two clicks on one chip show only it, a repeat restores all, keyboard clicks only
toggle, `detail` 3 does nothing, and a click between chips cancels a pending first
click. Synthetic fixtures only.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

SEGMENTS = [
    "solo_thursday",
    "solo_sunday",
    "solo_monday",
    "solo_holiday",
    "solo_other",
    "agotw",
    "cbs_national",
    "international_other",
]

_CLICKS = """
([sel, key, details]) => {
  for (const detail of details) {
    const chip = document.querySelector(`${sel} button[data-segment='${key}']`);
    chip.dispatchEvent(new MouseEvent('click', {bubbles: true, detail}));
  }
}
"""

_GAP_CLICK = """
(sel) => {
  document.querySelector(sel).dispatchEvent(new MouseEvent('click', {bubbles: true, detail: 1}));
}
"""

SPECIAL = "#nfl-view-special .legend-chips"
SCATTER = "#nfl-view-scatter .legend-chips"


@pytest.fixture
def app(nfl_guarded_page: Page, open_nfl_app: Callable[..., None]) -> Page:
    open_nfl_app(nfl_guarded_page)
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('special').drawn === true"
    )
    return nfl_guarded_page


def _hidden(page: Page) -> list[str]:
    return page.evaluate(  # type: ignore[no-any-return]
        "window.__nflTestHooks.getState().hiddenSegments"
    )


def _wait_hidden(page: Page, expected: list[str]) -> None:
    page.wait_for_function(
        "e => JSON.stringify(window.__nflTestHooks.getState().hiddenSegments) === JSON.stringify(e)",  # noqa: E501
        arg=expected,
    )


def _others(key: str) -> list[str]:
    return [k for k in SEGMENTS if k != key]


def _click(page: Page, sel: str, key: str, details: list[int]) -> None:
    page.evaluate(_CLICKS, [sel, key, details])


# ---------------------------------------------------------------- team bars


def test_single_click_toggles_one_segment(app: Page) -> None:
    _click(app, SPECIAL, "agotw", [1])
    _wait_hidden(app, ["agotw"])


def test_double_click_shows_only_one_and_repeat_restores(app: Page) -> None:
    _click(app, SPECIAL, "agotw", [1, 2])
    _wait_hidden(app, _others("agotw"))
    app.wait_for_timeout(50)
    _click(app, SPECIAL, "agotw", [1, 2])
    _wait_hidden(app, [])


def test_double_tap_within_300ms_shows_only_one(app: Page) -> None:
    _click(app, SPECIAL, "solo_monday", [1, 1])
    _wait_hidden(app, _others("solo_monday"))


def test_keyboard_clicks_only_toggle(app: Page) -> None:
    _click(app, SPECIAL, "agotw", [0, 0])
    _wait_hidden(app, [])  # toggled off then on, never "only"


def test_triple_click_is_ignored(app: Page) -> None:
    _click(app, SPECIAL, "agotw", [3])
    app.wait_for_timeout(100)
    assert _hidden(app) == []


def test_gap_click_cancels_pending_first_click(app: Page) -> None:
    _click(app, SPECIAL, "agotw", [1])
    _wait_hidden(app, ["agotw"])
    app.evaluate(_GAP_CLICK, SPECIAL)
    _click(app, SPECIAL, "agotw", [2])
    # The pending first click was dropped, so the second is a plain toggle.
    _wait_hidden(app, [])


def test_every_chip_has_the_hint(app: Page) -> None:
    hints = app.eval_on_selector_all(
        f"{SPECIAL} button[data-segment]",
        "els => els.map(e => [e.dataset.segment, e.title, e.getAttribute('aria-description')])",
    )
    assert len(hints) == 8
    for key, title, desc in hints:
        assert title == desc
        assert title.startswith("Double-click to show only ")
        assert key
    _click(app, SPECIAL, "agotw", [1, 2])
    _wait_hidden(app, _others("agotw"))
    sole = app.get_attribute(f"{SPECIAL} button[data-segment=agotw]", "title")
    assert sole == "Double-click to show all"


# ------------------------------------------------------------------ scatter


def _cats(page: Page) -> list[str]:
    return page.evaluate(  # type: ignore[no-any-return]
        "window.__nflTestHooks.getViewModel('scatter').hiddenCategories"
    )


def test_scatter_double_click_shows_only_one_category_and_repeat_restores(app: Page) -> None:
    app.evaluate("window.__nflTestHooks.setState({view: 'scatter'})")
    app.wait_for_selector(f"{SCATTER} button[data-category=agotw]")
    clicks = _CLICKS.replace("data-segment", "data-category")
    app.evaluate(clicks, [SCATTER, "agotw", [1, 2]])
    app.wait_for_function(
        "window.__nflTestHooks.getViewModel('scatter').hiddenCategories.length === 8"
    )
    assert "agotw" not in _cats(app)
    app.evaluate(clicks, [SCATTER, "agotw", [1, 2]])
    app.wait_for_function(
        "window.__nflTestHooks.getViewModel('scatter').hiddenCategories.length === 0"
    )
