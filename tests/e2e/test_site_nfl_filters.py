# ruff: noqa: E501  (embedded UI copy)
"""999.5-12: the NFL toolbar, its four filters, Clear all filters and the mobile sheet."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

TRIGGERS = ["Announcers", "Seasons", "Category", "Team"]
CFB_ONLY = ["Networks", "Role", "Conference", "Bowls/Playoffs", "Kickoff", "School", "Game"]


@pytest.fixture
def app(nfl_guarded_page: Page, open_nfl_app: Callable[..., None]) -> Page:
    open_nfl_app(nfl_guarded_page)
    return nfl_guarded_page


@pytest.fixture
def mobile(nfl_mobile_page: Page, open_nfl_app: Callable[..., None]) -> Page:
    open_nfl_app(nfl_mobile_page)
    return nfl_mobile_page


def _search(page: Page) -> str:
    return page.evaluate("location.search")  # type: ignore[no-any-return]


def _open(page: Page, key: str) -> None:
    page.click(f"#nfl-trigger-{key}")
    page.wait_for_selector(f"#nfl-pop-{key}:popover-open")


def test_trigger_order_and_labels(app: Page) -> None:
    labels = app.eval_on_selector_all(
        "#nfl-toolbar > button",
        "els => els.filter(e => e.offsetParent !== null).map(e => e.textContent.trim())",
    )
    assert labels == ["Clear all filters", *TRIGGERS]
    text = app.inner_text("#nfl-toolbar")
    for label in CFB_ONLY:
        assert label not in text
    for key in ("announcers", "seasons", "category", "team"):
        assert app.get_attribute(f"#nfl-trigger-{key}", "aria-haspopup") == "dialog"
        assert app.get_attribute(f"#nfl-trigger-{key}", "aria-expanded") == "false"


def test_announcers_search_pick_chip_and_remove(app: Page, nfl_site_dist: Path) -> None:
    cfb_people = json.loads((nfl_site_dist / "site-data.json").read_text(encoding="utf-8"))[
        "lookups"
    ]["people"]
    cfb_only = cfb_people[0]["name"]
    _open(app, "announcers")
    assert (
        app.get_attribute("#nfl-person-search-pop", "placeholder")
        == 'Search announcers — try "Joe Buck"'
    )
    app.fill("#nfl-person-search-pop", "ada qu")
    visible = app.locator("#nfl-person-results-pop > li:visible")
    assert visible.all_inner_texts() == ["Ada Quill"]
    app.fill("#nfl-person-search-pop", cfb_only)
    assert app.locator("#nfl-person-results-pop > li:visible").count() == 0
    app.fill("#nfl-person-search-pop", "ada")
    visible.first.click()
    assert "people=p00" in _search(app)
    chip = app.locator("#nfl-chips .chip")
    assert chip.count() == 1
    assert "Ada Quill" in chip.inner_text()
    assert app.get_attribute("#nfl-trigger-announcers", "data-active") == "true"
    app.click('#nfl-chips button[aria-label="Remove Ada Quill"]')
    assert _search(app) == "?sport=nfl"
    assert app.locator("#nfl-chips .chip").count() == 0


def test_no_compare_or_together_controls(app: Page) -> None:
    _open(app, "announcers")
    text = app.inner_text("#nfl-pop-announcers").lower()
    assert "compare" not in text
    assert "together" not in text


def test_seasons_range_writes_url(app: Page) -> None:
    _open(app, "seasons")
    app.select_option("#nfl-season-to-pop", "2025")
    assert _search(app) == "?sport=nfl&seasons=2024-2025"
    app.select_option("#nfl-season-to-pop", "2026")
    assert _search(app) == "?sport=nfl"
    app.select_option("#nfl-season-from-pop", "2026")
    assert "seasons=2026-2026" in _search(app)
    app.click("#nfl-pop-seasons .group-reset")
    assert _search(app) == "?sport=nfl"


def test_category_labels_and_url(app: Page) -> None:
    _open(app, "category")
    legends = app.locator("#nfl-pop-category legend").all_inner_texts()
    assert legends == ["Standalone slots", "Other special games"]
    labels = app.locator("#nfl-pop-category .check-row .option-name").all_inner_texts()
    assert labels == [
        "Thursday Night Football (TNF)",
        "Sunday Night Football (SNF)",
        "Monday Night Football (MNF)",
        "Thanksgiving",
        "Christmas",
        "Black Friday",
        "Saturday",
        "International (standalone slot)",
        "Other standalone slots",
        "AGOTW",
        "CBS national",
        "International (any slot)",
        "Flexed",
    ]
    app.check('#nfl-pop-category input[value="intl"]')
    assert _search(app) == "?sport=nfl&cat=intl"
    assert app.get_attribute("#nfl-trigger-category", "data-active") == "true"
    app.uncheck('#nfl-pop-category input[value="intl"]')
    assert _search(app) == "?sport=nfl"


def test_team_picks_write_url(app: Page) -> None:
    _open(app, "team")
    assert app.get_attribute("#nfl-team-search-pop", "placeholder") == "Search teams"
    app.fill("#nfl-team-search-pop", "gulls")
    assert app.locator("#nfl-pop-team .check-item:visible").count() == 1
    app.check('#nfl-pop-team input[value="f-gulls"]')
    assert "team=f-gulls" in _search(app)
    app.fill("#nfl-team-search-pop", "")
    app.check('#nfl-pop-team input[value="f-foxes"]')
    assert "team=f-foxes,f-gulls" in _search(app).replace("%2C", ",")


def test_clear_all_filters_resets_url(app: Page) -> None:
    app.evaluate(
        "window.__nflTestHooks.setState({ seasons: [2025, 2025], teams: ['f-gulls'], people: ['p00'], cats: ['agotw'] })"
    )
    assert _search(app) != "?sport=nfl"
    app.click("#nfl-clear-filters")
    assert _search(app) == "?sport=nfl"
    state = app.evaluate("window.__nflTestHooks.getState()")
    assert state["teams"] == [] and state["people"] == [] and state["cats"] == []


def test_keyboard_reaches_each_trigger_and_enter_opens(app: Page) -> None:
    app.focus("#nfl-clear-filters")
    for key in ("announcers", "seasons", "category", "team"):
        app.keyboard.press("Tab")
        assert app.evaluate("document.activeElement.id") == f"nfl-trigger-{key}"
    app.keyboard.press("Enter")
    app.wait_for_selector("#nfl-pop-team:popover-open")
    assert app.get_attribute("#nfl-trigger-team", "aria-expanded") == "true"
    app.keyboard.press("Escape")
    app.wait_for_selector("#nfl-pop-team:not(:popover-open)", state="attached")
    assert app.get_attribute("#nfl-trigger-team", "aria-expanded") == "false"


def test_popover_markup_is_text_only(app: Page) -> None:
    _open(app, "announcers")
    app.fill("#nfl-person-search-pop", "<img src=x onerror=alert(1)>")
    assert app.locator("#nfl-pop-announcers img").count() == 0


def test_no_console_errors_through_filter_use(app: Page) -> None:
    errors: list[str] = []
    app.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    _open(app, "category")
    app.check('#nfl-pop-category input[value="agotw"]')
    app.click("#nfl-clear-filters")
    assert errors == []


# ---------------------------------------------------------------- mobile


def test_mobile_only_filters_button_visible(mobile: Page) -> None:
    visible = mobile.eval_on_selector_all(
        "#nfl-toolbar > button",
        "els => els.filter(e => e.offsetParent !== null).map(e => e.id)",
    )
    assert visible == ["nfl-clear-filters", "nfl-filters-button"]
    assert mobile.inner_text("#nfl-filters-button") == "Filters"


def test_mobile_badge_counts_active_filters(mobile: Page) -> None:
    mobile.evaluate("window.__nflTestHooks.setState({ teams: ['f-gulls'], cats: ['agotw'] })")
    assert mobile.inner_text("#nfl-filters-button") == "Filters (2)"
    mobile.click("#nfl-clear-filters")
    assert mobile.inner_text("#nfl-filters-button") == "Filters"


def test_mobile_sheet_sections_url_and_close(mobile: Page) -> None:
    mobile.click("#nfl-filters-button")
    mobile.wait_for_selector("#nfl-filters-sheet:popover-open")
    assert mobile.get_attribute("#nfl-filters-button", "aria-expanded") == "true"
    headings = mobile.locator("#nfl-filters-sheet .sheet-body h3").all_inner_texts()
    assert headings == TRIGGERS
    mobile.select_option("#nfl-season-to-sheet", "2025")
    assert _search(mobile) == "?sport=nfl&seasons=2024-2025"
    assert mobile.inner_text("#nfl-filters-button") == "Filters (1)"
    mobile.click("#nfl-filters-sheet .nfl-sheet-clear")
    assert _search(mobile) == "?sport=nfl"
    mobile.click("#nfl-filters-show-results")
    mobile.wait_for_selector("#nfl-filters-sheet:not(:popover-open)", state="attached")


def test_mobile_sheet_controls_are_44px(mobile: Page) -> None:
    mobile.click("#nfl-filters-button")
    mobile.wait_for_selector("#nfl-filters-sheet:popover-open")
    small = mobile.evaluate(
        """() => {
          const sel = '#nfl-filters-sheet .sheet-body input:not([type=checkbox]), #nfl-filters-sheet select,'
            + ' #nfl-filters-sheet .group-reset, #nfl-filters-sheet .check-row,'
            + ' #nfl-filters-sheet .nfl-sheet-clear, #nfl-filters-show-results';
          return [...document.querySelectorAll(sel)]
            .filter((e) => e.offsetParent !== null)
            .map((e) => [e.id || e.className, e.getBoundingClientRect().height])
            .filter(([, h]) => h < 43.5);
        }"""
    )
    assert small == []


def test_announcer_list_is_one_tab_stop_with_arrow_keys(app: Page) -> None:
    """JS-WR-05: a roving tabindex, not one tab stop per announcer; arrows move between options."""
    _open(app, "announcers")
    options = "#nfl-person-results-pop > li"
    assert app.locator(f"{options}[tabindex='0']").count() == 1
    names = app.locator(f"{options}:visible .option-name").all_inner_texts()
    assert len(names) >= 3

    def active() -> str | None:
        return app.evaluate(  # type: ignore[no-any-return]
            "document.activeElement.matches('li[role=option]')"
            " ? document.activeElement.textContent : document.activeElement.id"
        )

    app.focus("#nfl-person-search-pop")
    app.keyboard.press("ArrowDown")
    assert active() == names[0]
    app.keyboard.press("ArrowDown")
    assert active() == names[1]
    assert app.locator(f"{options}[tabindex='0']").inner_text() == names[1]
    app.keyboard.press("End")
    assert active() == names[-1]
    app.keyboard.press("Home")
    assert active() == names[0]
    app.keyboard.press("ArrowUp")
    assert active() == "nfl-person-search-pop"
    # Tab from an option leaves the list in one step.
    app.keyboard.press("ArrowDown")
    app.keyboard.press("Tab")
    assert app.evaluate("document.activeElement.closest('#nfl-person-results-pop')") is None
    # aria-expanded follows whether any option is listed.
    assert app.get_attribute("#nfl-person-search-pop", "aria-expanded") == "true"
    app.fill("#nfl-person-search-pop", "zzzz no such announcer")
    assert app.get_attribute("#nfl-person-search-pop", "aria-expanded") == "false"
    app.fill("#nfl-person-search-pop", "ada")
    assert app.get_attribute("#nfl-person-search-pop", "aria-expanded") == "true"
    stop = app.locator(f"{options}[tabindex='0']")
    assert stop.count() == 1 and stop.is_visible()
