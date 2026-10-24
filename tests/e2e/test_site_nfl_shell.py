# ruff: noqa: E501, RUF001  (embedded JS lines and the UI copy's typographic characters)
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


_TRADEMARK_LINE = (
    "Network logos are trademarks of their owners, shown only to identify each network. "
    "Their use does not imply endorsement, and they are not covered by this site's MIT license."
)

_TYPE_LINE = (
    "Type: Crimson Text (copyright 2010 The Crimson Text Project Authors), "
    "Roboto (copyright 2011 The Roboto Project Authors) and "
    "Roboto Condensed (copyright 2011 Google Inc.), "
    "used under the SIL Open Font License 1.1."
)

_RT02_TEXT = (
    "Viewership: RatingsReference.com (CC BY 4.0), modified: filtered and joined with crew and "
    "game data · Schedules and win-probability measures: nflverse (CC BY 4.0), modified: "
    "derived and joined with crew and viewership data · Scheduling changes: Wikipedia "
    "(CC BY-SA 4.0) · Crews and networks: 506 Sports"
)

_BY = "https://creativecommons.org/licenses/by/4.0/"
_RT02_LINKS = [
    ("RatingsReference.com", "https://ratingsreference.com"),
    ("CC BY 4.0", _BY),
    ("nflverse", "https://nflverse.com"),
    ("CC BY 4.0", _BY),
    ("Wikipedia", "https://www.wikipedia.org"),
    ("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/"),
    ("506 Sports", "https://506sports.com"),
]


def _norm(text: str) -> str:
    return " ".join(text.split())


def _static_lines(page: Page) -> tuple[str, str, list[str]]:
    """RT-23 and RT-24 text and the RT-24 link targets, as the footer shows them now."""
    trademark = _norm(page.locator("#site-footer p.trademark-line").inner_text())
    type_line = _norm(page.locator("#site-footer p.type-line").inner_text())
    hrefs = page.locator("#site-footer p.type-line a").evaluate_all(
        "els => els.map(e => e.getAttribute('href'))"
    )
    return trademark, type_line, hrefs


def test_footer_swap_and_restore(cfb: Page) -> None:
    before = cfb.evaluate("document.getElementById('site-footer').outerHTML")
    lines_before = _static_lines(cfb)
    assert lines_before[0] == _TRADEMARK_LINE
    assert lines_before[1] == _TYPE_LINE
    _mount_nfl(cfb)
    # RT-02 in full: exact text, link text and targets, rel on every link.
    credit = cfb.locator("#site-footer .credit-line")
    assert _norm(credit.inner_text()) == _RT02_TEXT
    anchors = credit.locator("a")
    assert anchors.evaluate_all("els => els.map(e => [e.textContent, e.getAttribute('href')])") == [
        list(pair) for pair in _RT02_LINKS
    ]
    assert anchors.evaluate_all("els => els.map(e => e.rel)") == ["noopener noreferrer"] * 7
    text = cfb.inner_text("#site-footer")
    assert "Schedules and scores" in text
    # RT-03: no CFBD credit on NFL.
    assert "CollegeFootballData" not in text
    # RT-23 and RT-24 are untouched while NFL is mounted.
    assert _static_lines(cfb) == lines_before
    _unmount_nfl(cfb)
    assert cfb.evaluate("document.getElementById('site-footer').outerHTML") == before
    assert _static_lines(cfb) == lines_before


def test_footer_round_trip_through_the_sport_switch(cfb: Page) -> None:
    """RT-04: CFB -> NFL -> CFB restores the CFB footer, RT-23/24 present at every step."""
    before = cfb.evaluate("document.getElementById('site-footer').outerHTML")
    lines_before = _static_lines(cfb)
    cfb.click('#sport-switch button[data-sport="nfl"]')
    cfb.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.ready === true")
    assert _norm(cfb.locator("#site-footer .credit-line").inner_text()) == _RT02_TEXT
    assert "CollegeFootballData" not in cfb.inner_text("#site-footer")
    assert _static_lines(cfb) == lines_before
    cfb.click('#sport-switch button[data-sport="cfb"]')
    cfb.wait_for_function("document.body.dataset.sport === 'cfb'")
    assert cfb.evaluate("document.getElementById('site-footer').outerHTML") == before
    assert _static_lines(cfb) == lines_before


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
    cfb.evaluate("window.__nflTestHooks.setState({ view: 'crews' })")
    _unmount_nfl(cfb)
    _mount_nfl(cfb, "?sport=nfl")
    assert len(requests) == 1
    assert cfb.evaluate("window.__nflTestHooks.getState().view") == "crews"
    assert "view=crews" in cfb.url
    assert cfb.locator("#nfl-tab-crews").get_attribute("aria-selected") == "true"


def test_default_url(cfb: Page) -> None:
    _mount_nfl(cfb)
    assert cfb.url.endswith("?sport=nfl")


# ------------------------------------------------------------------- tabs


def test_tab_order_labels_and_default(cfb: Page) -> None:
    before = cfb.locator("#chart-tabs [role=tab]").count()
    _mount_nfl(cfb)
    tabs = cfb.locator("#nfl-chart-tabs [role=tab]")
    assert tabs.all_inner_texts() == [
        "Special games",
        "Crews",
        "Viewership",
        "Scatter",
    ]
    assert cfb.locator("#nfl-tab-special").get_attribute("aria-selected") == "true"
    assert cfb.url.endswith("?sport=nfl")
    for view in ("special", "crews", "viewership", "scatter"):
        assert (
            cfb.locator(f"#nfl-view-{view}").get_attribute("aria-labelledby") == f"nfl-tab-{view}"
        )
    assert cfb.locator("#chart-tabs [role=tab]").count() == before


def test_tab_keyboard(cfb: Page) -> None:
    _mount_nfl(cfb)
    cfb.focus("#nfl-tab-special")
    cfb.keyboard.press("ArrowRight")
    assert cfb.evaluate("document.activeElement.id") == "nfl-tab-crews"
    assert cfb.locator("#nfl-tab-special").get_attribute("aria-selected") == "true"
    cfb.keyboard.press("Enter")
    assert cfb.locator("#nfl-tab-crews").get_attribute("aria-selected") == "true"
    assert "view=crews" in cfb.url
    assert cfb.locator("#nfl-view-crews").is_visible()
    assert not cfb.locator("#nfl-view-special").is_visible()
    cfb.keyboard.press("End")
    assert cfb.evaluate("document.activeElement.id") == "nfl-tab-scatter"
    cfb.keyboard.press("Home")
    assert cfb.evaluate("document.activeElement.id") == "nfl-tab-special"


@pytest.mark.parametrize(
    ("query", "tab"),
    [
        ("?sport=nfl&view=crews", "crews"),
        ("?sport=nfl&view=viewership", "viewership"),
        ("?sport=nfl&view=fox", "crews"),
        ("?sport=nfl&view=agotw", "viewership"),
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
    if tab != "special" and "view=bogus" not in query:
        assert (
            f"view={tab}" in cfb.url and "view=fox" not in cfb.url and "view=agotw" not in cfb.url
        )


def test_headline_shows_count_and_season_range(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    nfl_fixture_raw: dict[str, Any],
) -> None:
    page = nfl_guarded_page
    open_nfl_app(page)
    seasons = nfl_fixture_raw["games"]["season"]
    lo, hi = min(seasons), max(seasons)
    expect = f"{len(seasons):,} games · {lo}–{hi}"
    page.wait_for_function(
        "t => document.querySelector('#nfl-headline')?.textContent === t", arg=expect
    )
    assert page.locator("#nfl-chart-area .module-head h2#nfl-headline").count() == 1
    inner = [s for s in seasons if lo <= s <= lo + 1]
    page.evaluate("p => window.__nflTestHooks.setState(p)", {"seasons": [lo, lo + 1]})
    want = f"{len(inner):,} {'game' if len(inner) == 1 else 'games'} · {lo}–{lo + 1}"
    page.wait_for_function(
        "t => document.querySelector('#nfl-headline').textContent === t", arg=want
    )
    # The headline is visible on every NFL view; Crews and Viewership title the module by tab label.
    page.evaluate("() => window.__nflTestHooks.setState({ seasons: null })")
    for view, title in (
        ("special", None),
        ("crews", "Crews"),
        ("viewership", "Viewership"),
        ("scatter", None),
    ):
        page.evaluate("v => window.__nflTestHooks.setState({ view: v })", view)
        assert page.locator("#nfl-headline").is_visible()
        text = page.locator("#nfl-headline").text_content() or ""
        if title is None:
            assert " games · " in text or " game · " in text
        else:
            assert text == title


def test_crews_subtitle_is_the_seasons_range(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    nfl_fixture_raw: dict[str, Any],
) -> None:
    page = nfl_guarded_page
    open_nfl_app(page, "?sport=nfl&view=crews")
    seasons = nfl_fixture_raw["games"]["season"]
    lo, hi = min(seasons), max(seasons)
    sub = page.locator("#nfl-chart-subtitle")
    page.wait_for_function(
        "t => document.querySelector('#nfl-chart-subtitle').textContent === t",
        arg=f"Seasons {lo}–{hi}",
    )
    page.evaluate("y => window.__nflTestHooks.setState({ seasons: [y, y] })", hi)
    page.wait_for_function(
        "t => document.querySelector('#nfl-chart-subtitle').textContent === t",
        arg=f"Season {hi}",
    )
    assert sub.count() == 1


# ------------------------------------------------- views load without errors


@pytest.mark.parametrize("view", ["crews", "viewership", "scatter", "special"])
def test_view_ready_without_console_errors(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], view: str
) -> None:
    page = nfl_guarded_page
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    open_nfl_app(page, f"?sport=nfl&view={view}" if view != "special" else "?sport=nfl")
    assert page.evaluate("window.__nflTestHooks.failed") is False
    assert page.locator(f"#nfl-view-{view}").is_visible()
    assert errors == []


# ------------------------------------------------------------ booth picks


def _first_booth(page: Page) -> tuple[str, str]:
    return page.evaluate(  # type: ignore[no-any-return]
        "() => { const c = window.__nflTestHooks.getBoothCatalog()[0]; return [c.key, c.label]; }"
    )


def test_booth_chip_caption_and_empty(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    open_nfl_app(page, "?sport=nfl&view=crews")
    key, label = _first_booth(page)
    page.evaluate("k => window.__nflTestHooks.setState({ booths: [k] })", key)
    chip = page.locator("#nfl-chips .chip")
    assert chip.count() == 1
    assert chip.locator(".chip-label").inner_text() == label
    assert "booths=" in page.url
    assert page.evaluate("window.__nflTestHooks.getTableIndexes().length") > 0
    # A season range with no games for the booth shows the filtered empty state.
    page.evaluate("window.__nflTestHooks.setState({ seasons: [2026, 2026] })")
    page.wait_for_function("window.__nflTestHooks.getTableIndexes().length === 0")
    empty = page.inner_text("#nfl-matched-games")
    assert f"No games match the current filters for {label}." in empty
    # The remove button clears the booth.
    page.evaluate("window.__nflTestHooks.setState({ seasons: [2024, 2026] })")
    page.locator("#nfl-chips .chip-remove").click()
    assert page.locator("#nfl-chips .chip").count() == 0
    assert page.evaluate("window.__nflTestHooks.getState().booths") == []


# ------------------------------------------------- selection row and filter bar


@pytest.mark.parametrize("view", ["special", "crews", "viewership", "scatter"])
def test_selection_row_and_booths_on_every_tab(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], view: str
) -> None:
    page = nfl_guarded_page
    open_nfl_app(page, f"?sport=nfl&view={view}")
    # The selection row is always rendered, with Clear all filters at its right end.
    row = page.locator("#nfl-selection-row")
    assert row.is_visible()
    clear = page.locator("#nfl-clear-filters")
    assert clear.is_visible()
    row_box, clear_box = row.bounding_box(), clear.bounding_box()
    assert row_box is not None and clear_box is not None
    assert clear_box["x"] + clear_box["width"] >= row_box["x"] + row_box["width"] - 1
    # Booths is visible on every NFL tab (D-11).
    assert page.locator("#nfl-trigger-booths").is_visible()
    # The module subtitle replaces the old tab hint.
    assert page.locator("#nfl-chart-subtitle").count() == 1
