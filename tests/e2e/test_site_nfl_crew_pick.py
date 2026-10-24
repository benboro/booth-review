"""Phase 15 plan 10: Crews picks, Raw/Adjusted rules and legacy links, end to end.

Drives the real filter bar (Announcers and Booths popovers) and the real Crews table rows to
prove D-04 (a row-made Booths pick yields to an Announcers pick; filter-bar picks intersect),
D-05 (a row click sets Booths to the catalog key) and the NFL-04 Crews mode rules. Synthetic
data only (`serve_nfl_crews`, tests/e2e/nfl_crews_fixture.py); no vault rows.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from nfl_crews_fixture import CASE_FILL_IN, CASE_MIXED_SEAT, CASE_TWO_ANALYSTS, CASE_ZERO_GAME
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

HOOKS = "window.__nflTestHooks"
VIEW = "#nfl-view-crews"
ROW = f"{VIEW} tr.crews-row"
TOOLS = "#nfl-chart-tools [data-tools-for='crews']"
CATALOG = str(CASE_TWO_ANALYSTS["catalog_key"])
PBP = str(CASE_TWO_ANALYSTS["pbp"])
KEY_A = f"fox:{PBP}.synth-an-two-a"
KEY_B = f"fox:{PBP}.synth-an-two-b"
BAR = "#nfl-reason-crews"


@pytest.fixture
def crews(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> Callable[[str], Page]:
    def go(query: str = "") -> Page:
        serve_nfl_crews(nfl_guarded_page)
        open_nfl_app(nfl_guarded_page, "?sport=nfl&view=crews" + query)
        nfl_guarded_page.wait_for_function(f"{HOOKS}.getViewModel('crews') !== null")
        _vm(nfl_guarded_page)
        return nfl_guarded_page

    return go


def _vm(page: Page) -> dict[str, Any]:
    page.wait_for_function(f"{HOOKS}.getViewModel('crews').drawn === true")
    return page.evaluate(f"{HOOKS}.getViewModel('crews')")  # type: ignore[no-any-return]


def _state(page: Page) -> dict[str, Any]:
    return page.evaluate(f"{HOOKS}.getState()")  # type: ignore[no-any-return]


def _status(page: Page) -> str:
    return (page.locator("#pick-status").text_content() or "").strip()


def _row(page: Page, key: str) -> Any:
    while page.locator(f"{ROW}[data-row-key='{key}']").count() == 0:
        more = page.locator(f"{VIEW} .nfl-crews-table > .crews-more")
        assert more.count() == 1, f"{key} is not in the table"
        more.click()
    return page.locator(f"{ROW}[data-row-key='{key}']")


def _open(page: Page, key: str) -> None:
    page.click(f"#nfl-trigger-{key}")
    page.wait_for_selector(f"#nfl-pop-{key}:popover-open")


def _close(page: Page) -> None:
    page.keyboard.press("Escape")
    page.wait_for_selector(".filter-popover:popover-open", state="detached")


def _filter_bar_booth(page: Page, key: str, search: str) -> None:
    _open(page, "booths")
    page.fill("#nfl-booth-search-pop", search)
    page.locator(f"#nfl-booth-results-pop li[data-booth='{key}']").click()
    _close(page)


def _filter_bar_person(page: Page, person: str, search: str) -> None:
    _open(page, "announcers")
    page.fill("#nfl-person-search-pop", search)
    page.locator(f"#nfl-person-results-pop li[data-person='{person}']").click()
    _close(page)


def _adjusted_btn(page: Page) -> Any:
    return page.locator(f"{TOOLS} [aria-label='Raw or adjusted'] button", has_text="Adjusted")


def _reason(page: Page, name: str) -> str:
    return page.evaluate(  # type: ignore[no-any-return]
        "n => import('./sports/nfl/mode.js').then((m) => m.REASONS[n])", name
    )


def _assert_forced_raw(page: Page, reason_name: str) -> None:
    page.wait_for_function(f"{HOOKS}.getViewModel('crews').mode === 'raw'")
    reason = _reason(page, reason_name)
    bar = page.locator(BAR)
    assert bar.inner_text() == reason
    assert _vm(page)["reason"] == reason
    adjusted = _adjusted_btn(page)
    assert adjusted.get_attribute("aria-disabled") == "true"
    assert adjusted.get_attribute("aria-describedby") == "nfl-reason-crews"
    assert "adj=1" in page.url


def _assert_adjusted(page: Page) -> None:
    page.wait_for_function(f"{HOOKS}.getViewModel('crews').mode === 'adjusted'")
    assert page.locator(BAR).is_hidden()
    adjusted = _adjusted_btn(page)
    assert adjusted.get_attribute("aria-disabled") is None
    assert adjusted.get_attribute("aria-pressed") == "true"
    assert "adj=1" in page.url


# ------------------------------------------------------------------ D-04, D-05


def test_row_click_sets_booths_and_announces(crews: Callable[[str], Page]) -> None:
    page = crews("&perseason=0")
    _filter_bar_person(page, "synth-an-two-a", "Synth An Two A")
    assert _state(page)["people"] == ["synth-an-two-a"]
    _row(page, KEY_A).locator("td.crews-name").click()
    page.wait_for_function(f"JSON.stringify({HOOKS}.getState().booths) === '[\"{CATALOG}\"]'")
    state = _state(page)
    assert state["people"] == []
    status = _status(page)
    assert status.startswith("Booths pick set to ") and status.endswith(
        ". Announcers pick cleared."
    )
    assert len(status) > len("Booths pick set to . Announcers pick cleared.")
    assert page.get_attribute("#nfl-trigger-booths", "data-active") == "true"
    assert page.get_attribute("#nfl-trigger-announcers", "data-active") != "true"
    assert "booths=" in page.url and "people=" not in page.url
    # The same row again clears the pick.
    _row(page, KEY_A).locator("td.crews-name").click()
    page.wait_for_function(f"{HOOKS}.getState().booths.length === 0")
    assert _status(page) == "Booths pick cleared."
    assert page.get_attribute("#nfl-trigger-booths", "data-active") != "true"


def test_lineup_only_row_click_leaves_picks_alone(crews: Callable[[str], Page]) -> None:
    """15-13 F4: a booth with no games is not in the catalog, so its row click is a no-op."""
    page = crews("&perseason=0")
    _filter_bar_person(page, CASE_ZERO_GAME["pbp"], "Synth Pbp Zero")
    before = _state(page)
    assert before["people"] == [CASE_ZERO_GAME["pbp"]] and before["booths"] == []
    status = _status(page)
    key = f"fox:{CASE_ZERO_GAME['pbp']}.{CASE_ZERO_GAME['analyst']}"
    _row(page, key).locator("td.crews-name").click()
    after = _state(page)
    assert after["people"] == before["people"] and after["booths"] == []
    assert _status(page) == status
    assert "booths=" not in page.url and "people=" + str(CASE_ZERO_GAME["pbp"]) in page.url


def test_announcer_in_filter_bar_clears_a_row_made_pick(crews: Callable[[str], Page]) -> None:
    page = crews("&perseason=0")
    _row(page, KEY_A).locator("td.crews-name").click()
    page.wait_for_function(f"{HOOKS}.getState().booths.length === 1")
    _filter_bar_person(page, "synth-an-two-a", "Synth An Two A")
    state = _state(page)
    assert state["booths"] == [] and state["people"] == ["synth-an-two-a"]
    name = page.locator("#nfl-chips .chip-label").first.inner_text()
    assert _status(page) == f"Announcers pick set to {name}. Booths pick cleared."
    assert "booths=" not in page.url and "people=synth-an-two-a" in page.url


def test_two_filter_bar_booths_mark_no_row(crews: Callable[[str], Page]) -> None:
    page = crews("&perseason=0")
    _filter_bar_booth(page, CATALOG, "Synth Pbp Two")
    other = next(
        e["key"] for e in page.evaluate(f"{HOOKS}.getBoothCatalog()") if e["key"] != CATALOG
    )
    _open(page, "booths")
    page.fill("#nfl-booth-search-pop", "")
    page.locator(f"#nfl-booth-results-pop li[data-booth='{other}']").click()
    _close(page)
    page.wait_for_function(f"{HOOKS}.getState().booths.length === 2")
    vm = _vm(page)
    assert not any(r["picked"] for r in vm["rows"])
    pressed = page.eval_on_selector_all(ROW, "els => els.map(e => e.getAttribute('aria-pressed'))")
    assert pressed and set(pressed) == {"false"}
    keys = {r["rowKey"] for r in vm["rows"]}
    assert {KEY_A, KEY_B} <= keys  # both analyst rows of the first booth remain
    assert any(k.startswith(other.split(":")[0] + ":") for k in keys)
    assert "booths=" in page.url


def test_filter_bar_booths_and_announcer_intersect_everywhere(
    crews: Callable[[str], Page],
) -> None:
    page = crews("&perseason=0")
    table = f"{HOOKS}.getTableIndexes()"
    _filter_bar_booth(page, CATALOG, "Synth Pbp Two")
    page.wait_for_function(f"{HOOKS}.getState().booths.length === 1")
    booth_only = sorted(page.evaluate(table))
    assert booth_only
    _filter_bar_person(page, "synth-an-two-a", "Synth An Two A")
    state = _state(page)
    # Both picks stay (the second is a filter-bar pick, so D-04 does not clear the first).
    assert state["booths"] == [CATALOG] and state["people"] == ["synth-an-two-a"]
    both = sorted(page.evaluate(table))
    assert both and set(both) < set(booth_only)
    # The Announcers pick alone is a superset of the intersection.
    page.evaluate(f"{HOOKS}.setState({{ booths: [] }})")
    page.wait_for_function(f"{HOOKS}.getState().booths.length === 0")
    people_only = sorted(page.evaluate(table))
    assert set(both) <= set(people_only)
    assert set(both) == set(booth_only) & set(people_only)
    page.evaluate(f"k => {HOOKS}.setState({{ booths: [k] }})", CATALOG)
    page.wait_for_function(f"{HOOKS}.getState().booths.length === 1")
    for view in ("special", "scatter"):
        page.evaluate(f"v => {HOOKS}.setState({{ view: v }})", view)
        page.wait_for_function(f"{HOOKS}.getState().view === '{view}'")
        with_both = page.evaluate(f"v => JSON.stringify({HOOKS}.getViewModel(v))", view)
        page.evaluate(f"{HOOKS}.setState({{ people: [] }})")
        page.wait_for_function(f"{HOOKS}.getState().people.length === 0")
        booth_vm = page.evaluate(f"v => JSON.stringify({HOOKS}.getViewModel(v))", view)
        assert with_both != booth_vm, view
        page.evaluate(f"{HOOKS}.setState({{ people: ['synth-an-two-a'] }})")
        page.wait_for_function(f"{HOOKS}.getState().people.length === 1")
    page.evaluate(f"{HOOKS}.setState({{ view: 'crews' }})")
    page.wait_for_function(f"{HOOKS}.getState().view === 'crews'")
    assert set(page.evaluate(table)) == set(both)
    assert "booths=" in page.url and "people=" in page.url


# ------------------------------------------------------------------ Raw / Adjusted


def test_row_filters_keep_adjusted(crews: Callable[[str], Page]) -> None:
    page = crews("&perseason=0&adj=1")
    _assert_adjusted(page)
    # A PBP-voice Announcers pick is a row filter.
    _filter_bar_person(page, PBP, "Synth Pbp Two")
    page.wait_for_function(f"{HOOKS}.getState().people.length === 1")
    _assert_adjusted(page)
    page.evaluate(f"{HOOKS}.setState({{ people: [] }})")
    # A Booths pick (from the filter bar) is a row filter.
    _filter_bar_booth(page, CATALOG, "Synth Pbp Two")
    page.wait_for_function(f"{HOOKS}.getState().booths.length === 1")
    _assert_adjusted(page)
    page.evaluate(f"{HOOKS}.setState({{ booths: [] }})")
    # Seasons narrowed is a row filter.
    lo, hi = _state(page)["seasons"]
    page.evaluate(f"s => {HOOKS}.setState({{ seasons: s }})", [hi, hi])
    page.wait_for_function(f"{HOOKS}.getState().seasons[0] === {hi}")
    _assert_adjusted(page)
    assert lo <= hi


@pytest.mark.parametrize(
    "person",
    [str(CASE_MIXED_SEAT["person"]), str(CASE_FILL_IN["fill_in"])],
    ids=["mixed-seat", "fill-in-analyst"],
)
def test_game_subset_picks_force_raw_with_reason(crews: Callable[[str], Page], person: str) -> None:
    page = crews("&perseason=0&adj=1")
    _assert_adjusted(page)
    # Category pick.
    _open(page, "category")
    page.check("#nfl-pop-category input[value='snf']")
    _close(page)
    page.wait_for_function(f"{HOOKS}.getState().cats.length === 1")
    _assert_forced_raw(page, "crewsSubset")
    page.evaluate(f"{HOOKS}.setState({{ cats: [] }})")
    _assert_adjusted(page)
    # An analyst-matching Announcers pick (a seat other than play-by-play on some row).
    _filter_bar_person(page, person, person.replace("-", " "))
    page.wait_for_function(f"{HOOKS}.getState().people.length === 1")
    _assert_forced_raw(page, "crewsSubset")
    page.evaluate(f"{HOOKS}.setState({{ people: [] }})")
    _assert_adjusted(page)


def test_team_pick_uses_the_team_reason(
    crews: Callable[[str], Page], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = crews("&perseason=0&adj=1")
    _assert_adjusted(page)
    team = nfl_fixture_raw["lookups"]["franchises"][0]["id"]
    page.evaluate(f"t => {HOOKS}.setState({{ teams: [t] }})", team)
    _assert_forced_raw(page, "crewsTeam")
    page.evaluate(f"{HOOKS}.setState({{ teams: [] }})")
    _assert_adjusted(page)


# ------------------------------------------------------------------ legacy links


def _legacy(page: Page, open_nfl_app: Callable[..., None], query: str) -> tuple[Any, str]:
    open_nfl_app(page, "?sport=nfl&view=crews" + query)
    page.wait_for_function(f"{HOOKS}.getViewModel('crews') !== null")
    _vm(page)
    return _state(page), page.evaluate("location.search")


def _seasons_control(page: Page) -> tuple[str, str]:
    _open(page, "seasons")
    pair = (
        page.input_value("#nfl-season-from-pop"),
        page.input_value("#nfl-season-to-pop"),
    )
    _close(page)
    return pair


def test_legacy_cseason_and_net_links(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    page = nfl_guarded_page
    serve_nfl_crews(page)
    state, search = _legacy(page, open_nfl_app, "")
    master = state["seasons"]
    lo, hi = master
    y = hi
    state, search = _legacy(page, open_nfl_app, f"&cseason={y}")
    assert state["seasons"] == [y, y] and f"seasons={y}-{y}" in search
    assert _seasons_control(page) == (str(y), str(y))
    for gone in ("cseason", "fseason", "net="):
        assert gone not in search
    state, search = _legacy(page, open_nfl_app, f"&fseason={y}")
    assert state["seasons"] == [y, y] and "fseason" not in search
    # 15-13 F11: a literal cseason* key is just an unknown key and must not suppress cseason.
    state, search = _legacy(page, open_nfl_app, f"&cseason*=1&cseason={y}")
    assert state["seasons"] == [y, y]
    state, search = _legacy(page, open_nfl_app, f"&seasons={lo}-{hi}&cseason={y}")
    assert state["seasons"] == [lo, hi] and "cseason" not in search
    assert _seasons_control(page) == (str(lo), str(hi))
    base_groups = {r["rowKey"].split(":")[0] for r in _vm(page)["rows"]}
    state, search = _legacy(page, open_nfl_app, "&net=cbs")
    assert state["seasons"] == master and "net=" not in search
    assert {r["rowKey"].split(":")[0] for r in _vm(page)["rows"]} == base_groups
    assert len(base_groups) > 1
