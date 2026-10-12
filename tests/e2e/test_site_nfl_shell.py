# ruff: noqa: E501  (embedded JS lines and the UI copy's typographic characters)
"""999.5-10: the NFL mount module, mounted directly (app.js does not call it yet)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, Route

pytestmark = pytest.mark.e2e

_MOUNT_JS = """
async (search) => {
  document.body.dataset.sport = 'nfl';
  const m = await import('./sports/nfl/index.js');
  window.__nflMod = m;
  await m.mount({ footerEl: document.getElementById('site-footer'), search });
}
"""

_START_MOUNT_JS = """
(search) => {
  document.body.dataset.sport = 'nfl';
  window.__mountPromise = import('./sports/nfl/index.js').then((m) => {
    window.__nflMod = m;
    return m.mount({ footerEl: document.getElementById('site-footer'), search });
  });
}
"""


def _mount_nfl(page: Page, query: str = "?sport=nfl") -> None:
    """Mount the NFL side directly; `query` is passed explicitly because the CFB
    bootstrap may rewrite `location.search`."""
    page.evaluate(_MOUNT_JS, query)
    page.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.ready === true")


def _unmount_nfl(page: Page) -> None:
    page.evaluate("() => { window.__nflMod.unmount(); delete document.body.dataset.sport; }")


@pytest.fixture
def cfb(nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None]) -> Page:
    open_flagon_cfb(nfl_guarded_page)
    return nfl_guarded_page


def _display(page: Page, selector: str) -> str:
    return page.evaluate("(s) => getComputedStyle(document.querySelector(s)).display", selector)  # type: ignore[no-any-return]


# ---------------------------------------------------------------- footer


def test_footer_swap_and_restore(cfb: Page) -> None:
    before = cfb.evaluate("document.getElementById('site-footer').outerHTML")
    _mount_nfl(cfb)
    text = cfb.inner_text("#site-footer")
    assert "nflverse" in text
    assert "Wikipedia (CC BY-SA 4.0)" in text
    assert "506 Sports" in text
    assert "Schedules and scores" in text
    assert "CollegeFootballData" not in text
    links = cfb.eval_on_selector_all("#site-footer .credit-line a", "els => els.map(e => e.rel)")
    assert links and all(rel == "noopener noreferrer" for rel in links)
    _unmount_nfl(cfb)
    assert cfb.evaluate("document.getElementById('site-footer').outerHTML") == before


# ------------------------------------------------------------ load states


def test_loading_text_then_ready(cfb: Page) -> None:
    held: list[Route] = []
    cfb.route("**/nfl-data.json", lambda route: held.append(route))
    cfb.evaluate(_START_MOUNT_JS, "?sport=nfl")
    cfb.wait_for_selector("#nfl-chart-area .season-empty-note[role=status]")
    assert "Loading NFL data…" in cfb.inner_text("#nfl-chart-area")
    cfb.wait_for_function("window.__nflTestHooks")
    assert cfb.evaluate("window.__nflTestHooks.ready") is False
    held[0].continue_()
    cfb.wait_for_function("window.__nflTestHooks.ready === true")
    assert "Loading NFL data" not in cfb.inner_text("#nfl-chart-area")


def test_load_error_banner(cfb: Page) -> None:
    cfb.route("**/nfl-data.json", lambda route: route.fulfill(status=500, body="nope"))
    _mount_nfl(cfb)
    assert cfb.evaluate("window.__nflTestHooks.failed") is True
    banner = cfb.locator("#nfl-chart-area .error-banner[role=alert]")
    assert "Couldn't load the NFL data." in banner.inner_text()
    assert "You can still use the CFB view." in banner.inner_text()
    assert cfb.locator("#nfl-chart-tabs button[aria-disabled=true]").count() == 4
    assert "Nothing selected" in cfb.inner_text("#nfl-matched-games")


# ---------------------------------------------------------------- regions


def test_cfb_regions_hidden_while_mounted(cfb: Page) -> None:
    _mount_nfl(cfb)
    for sel in ("#toolbar", "#selection-bar", "#chart-area", "#matched-games"):
        assert _display(cfb, sel) == "none", sel
    for sel in ("#nfl-toolbar", "#nfl-selection-bar", "#nfl-chart-area", "#nfl-matched-games"):
        assert _display(cfb, sel) != "none", sel
    _unmount_nfl(cfb)
    for sel in ("#toolbar", "#selection-bar", "#chart-area", "#matched-games"):
        assert _display(cfb, sel) != "none", sel
    for sel in ("#nfl-toolbar", "#nfl-selection-bar", "#nfl-chart-area", "#nfl-matched-games"):
        assert _display(cfb, sel) == "none", sel


# ------------------------------------------------------- table and panel


def test_table_selection_and_panel(cfb: Page) -> None:
    _mount_nfl(cfb)
    assert "Nothing selected" in cfb.inner_text("#nfl-matched-games")
    cfb.evaluate(
        "window.__nflTestHooks.setState({ selection: { kind: 'test', key: 't', label: 'Test', games: [0, 1, 2] } })"
    )
    assert sorted(cfb.evaluate("window.__nflTestHooks.getTableIndexes()")) == [0, 1, 2]
    assert cfb.locator("#nfl-matched-games tbody tr").count() == 3
    assert cfb.locator("#nfl-clear-selection").is_visible()
    cfb.locator("#nfl-clear-selection").click()
    assert cfb.evaluate("window.__nflTestHooks.getTableIndexes()") == []

    cfb.focus("#nfl-tab-special")
    cfb.evaluate("window.__nflTestHooks.openGame(0)")
    assert cfb.evaluate("document.getElementById('nfl-detail-panel').open") is True
    cfb.keyboard.press("Escape")
    assert cfb.evaluate("document.getElementById('nfl-detail-panel').open") is False
    assert cfb.evaluate("document.activeElement.id") == "nfl-tab-special"


# --------------------------------------------------------- fetch and URL


def test_fetch_once_and_state_kept(cfb: Page) -> None:
    requests: list[str] = []
    cfb.on("request", lambda r: requests.append(r.url) if r.url.endswith("nfl-data.json") else None)
    _mount_nfl(cfb)
    cfb.evaluate("window.__nflTestHooks.setState({ view: 'fox' })")
    _unmount_nfl(cfb)
    _mount_nfl(cfb, "?sport=nfl")
    assert len(requests) == 1
    assert cfb.evaluate("window.__nflTestHooks.getState().view") == "fox"
    assert "view=fox" in cfb.url
    assert cfb.locator("#nfl-tab-fox").get_attribute("aria-selected") == "true"


def test_default_url(cfb: Page) -> None:
    _mount_nfl(cfb)
    assert cfb.url.endswith("?sport=nfl")


# ------------------------------------------------------------------- tabs


def test_tab_order_labels_and_default(cfb: Page) -> None:
    before = cfb.locator("#chart-tabs [role=tab]").count()
    _mount_nfl(cfb)
    tabs = cfb.locator("#nfl-chart-tabs [role=tab]")
    assert tabs.all_inner_texts() == [
        "Special games by team",
        "Fox crews",
        "AGOTW viewership",
        "Game scatter",
    ]
    assert cfb.locator("#nfl-tab-special").get_attribute("aria-selected") == "true"
    assert cfb.url.endswith("?sport=nfl")
    for view in ("special", "fox", "agotw", "scatter"):
        assert (
            cfb.locator(f"#nfl-view-{view}").get_attribute("aria-labelledby") == f"nfl-tab-{view}"
        )
    assert cfb.locator("#chart-tabs [role=tab]").count() == before


def test_tab_keyboard(cfb: Page) -> None:
    _mount_nfl(cfb)
    cfb.focus("#nfl-tab-special")
    cfb.keyboard.press("ArrowRight")
    assert cfb.evaluate("document.activeElement.id") == "nfl-tab-fox"
    assert cfb.locator("#nfl-tab-special").get_attribute("aria-selected") == "true"
    cfb.keyboard.press("Enter")
    assert cfb.locator("#nfl-tab-fox").get_attribute("aria-selected") == "true"
    assert "view=fox" in cfb.url
    assert cfb.locator("#nfl-view-fox").is_visible()
    assert not cfb.locator("#nfl-view-special").is_visible()
    cfb.keyboard.press("End")
    assert cfb.evaluate("document.activeElement.id") == "nfl-tab-scatter"
    cfb.keyboard.press("Home")
    assert cfb.evaluate("document.activeElement.id") == "nfl-tab-special"


@pytest.mark.parametrize(
    ("query", "tab"),
    [
        ("?sport=nfl&view=agotw", "agotw"),
        ("?sport=nfl&view=bogus", "special"),
    ],
)
def test_initial_view_from_search(cfb: Page, query: str, tab: str) -> None:
    _mount_nfl(cfb, query)
    state: Any = cfb.evaluate("window.__nflTestHooks.getState()")
    assert state["view"] == tab
    assert cfb.locator(f"#nfl-tab-{tab}").get_attribute("aria-selected") == "true"
    assert cfb.locator(f"#nfl-view-{tab}").is_visible()
    assert cfb.evaluate(f"window.__nflTestHooks.getViewModel('{tab}')")["view"] == tab
