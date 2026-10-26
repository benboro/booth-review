"""NFL This weekend tab on the flag-on build (Phase 18, plan 11): the fifth tab, regional
sub-rows ordered by booth rank, the Time TBA strip, picks, greyed filters, panel, URL state, the
phone list, dark theme and the credits. Synthetic fixture only (week 5, Sunday 2026-10-11)."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from dark_checks import set_theme
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

# Sunday morning ET, before every week-5 kickoff.
NOW = "2026-10-11T09:00:00-04:00"
OpenNfl = Callable[..., None]


def _open(page: Page, open_nfl_app: OpenNfl, query: str = "") -> None:
    page.add_init_script(f"window.__nflWeekendNow = '{NOW}'")
    open_nfl_app(page, f"?sport=nfl&view=weekend{query}")
    page.wait_for_selector(".wk-root")


def _row_cells(page: Page, row: str) -> list[dict[str, Any]]:
    return page.evaluate(
        """(row) => [...document.querySelectorAll(`.wk-row[data-row="${row}"] .wk-cell`)]
        .map((c) => ({
          top: parseInt(c.style.top, 10), time: c.querySelector('.wk-time').textContent,
          match: c.querySelector('.wk-match').textContent,
          booth: c.querySelector('.wk-booth').textContent,
          star: !!c.querySelector('.wk-star'),
        })).sort((a, b) => a.top - b.top)""",
        row,
    )


def test_fifth_tab_after_scatter(nfl_guarded_page: Page, open_nfl_app: OpenNfl) -> None:
    open_nfl_app(nfl_guarded_page, "?sport=nfl")
    tabs = nfl_guarded_page.locator("#nfl-chart-tabs [role=tab]")
    assert tabs.all_inner_texts()[-2:] == ["Scatter", "This weekend"]
    assert tabs.count() == 5
    nfl_guarded_page.click("#nfl-tab-weekend")
    assert "view=weekend" in nfl_guarded_page.url
    assert nfl_guarded_page.locator("#nfl-view-weekend").is_visible()


def test_flag_off_build_has_no_nfl_weekend(guarded_page: Page, open_app: OpenNfl) -> None:
    open_app(guarded_page, "?sport=nfl&view=weekend")
    assert guarded_page.locator("#nfl-tab-weekend").count() == 0
    assert guarded_page.locator("#nfl-chart-tabs").count() == 0
    assert guarded_page.locator("#nfl-view-weekend").count() == 0


def test_sunday_is_default_day_and_subtitle(nfl_guarded_page: Page, open_nfl_app: OpenNfl) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    day = nfl_guarded_page.locator(".wk-day[aria-selected=true]")
    assert day.inner_text().startswith("Sun. Oct. 11")
    assert nfl_guarded_page.locator("#nfl-chart-subtitle").inner_text() == (
        "Week 5 · Sun. Oct. 11 · All times ET"
    )
    assert nfl_guarded_page.locator("#nfl-matched-games").is_hidden()


def test_cbs_window_is_four_sub_rows_by_booth_rank(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    cells = _row_cells(nfl_guarded_page, "cbs")
    assert [c["top"] for c in cells] == [0, 48, 96, 144]
    assert all(c["time"] == "1:00" for c in cells)
    # Rank 1 on top, rank 2 under it, the crewless games last; every crew visible.
    assert cells[0]["star"] is True
    assert cells[0]["booth"] == "Strand · Vale"
    assert cells[1]["booth"] == "Pryor · Reyes"
    assert [c["booth"] for c in cells[2:]] == ["Crew TBA", "Crew TBA"]


def test_fox_window_reuses_top_sub_rows(nfl_guarded_page: Page, open_nfl_app: OpenNfl) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    cells = _row_cells(nfl_guarded_page, "fox")
    assert [c["top"] for c in cells] == [0, 48]
    assert all(c["time"] == "4:25" for c in cells)


def test_snf_cell_on_nbc_and_wikipedia_credit(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    nbc = _row_cells(nfl_guarded_page, "nbc")
    assert len(nbc) == 1
    assert nbc[0]["time"] == "8:20"
    source = nfl_guarded_page.locator(".wk-source")
    text = source.inner_text()
    assert "nflverse" in text
    assert "506 Sports" in text
    assert "Networks: Wikipedia (CC BY-SA 4.0)" in text
    href = source.locator("a", has_text="Wikipedia").get_attribute("href")
    assert href == "https://en.wikipedia.org/wiki/2026_NFL_season"


def test_no_wikipedia_credit_without_a_slot_network(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl
) -> None:
    _open(nfl_guarded_page, open_nfl_app, "&week=3")
    assert nfl_guarded_page.locator(".wk-source").count() == 1
    assert "Wikipedia" not in nfl_guarded_page.locator(".wk-source").inner_text()


def test_time_and_network_tba_strip(nfl_guarded_page: Page, open_nfl_app: OpenNfl) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    strip = nfl_guarded_page.locator(".wk-tba")
    assert "(2)" in strip.locator(".wk-tba-title").inner_text()
    body = strip.locator(".wk-tba-body")
    assert body.is_visible()
    text = body.inner_text()
    assert "Time TBA" in text
    assert "Network TBA" in text
    assert "Mesa Comets @ Harbor City Gulls" in text


def test_team_pick_fades_cells_and_carries_to_crews(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    teams = page.evaluate("window.__nflTestHooks.getState().teams")
    assert teams == []
    team_id = page.evaluate(
        "(async () => { const r = await fetch('nfl-data.json'); const j = await r.json();"
        " return j.lookups.franchises.find((f) => f.name.includes('Granite Bay')).id; })()"
    )
    page.evaluate("(id) => window.__nflTestHooks.setState({ teams: [id] })", team_id)
    faded = page.locator(".wk-cell.is-faded").count()
    matched = page.locator(".wk-cell.is-match").count()
    assert matched >= 1
    assert faded >= 1
    assert faded + matched == page.locator(".wk-cell").count()
    assert "team=" in page.url
    page.click("#nfl-tab-crews")
    assert page.evaluate("window.__nflTestHooks.getState().teams") == [team_id]


def test_seasons_and_category_are_greyed(nfl_guarded_page: Page, open_nfl_app: OpenNfl) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    for key in ("seasons", "category"):
        trigger = page.locator(f"#nfl-trigger-{key}")
        assert trigger.get_attribute("aria-disabled") == "true"
        assert trigger.get_attribute("title") == "Not used on This weekend"
        trigger.click(force=True)
        assert not page.locator(f"#nfl-pop-{key}").evaluate("(n) => n.matches(':popover-open')")
    for key in ("announcers", "team", "booths"):
        assert page.locator(f"#nfl-trigger-{key}").get_attribute("aria-disabled") is None
    page.click("#nfl-tab-crews")
    assert page.locator("#nfl-trigger-seasons").get_attribute("aria-disabled") == "false"


def test_cell_opens_panel_not_played_yet(nfl_guarded_page: Page, open_nfl_app: OpenNfl) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    page.locator(".wk-row[data-row=cbs] .wk-cell").first.click()
    dialog = page.locator("dialog[open], [role=dialog]:visible").first
    dialog.wait_for()
    assert "Not played yet." in dialog.inner_text()


def test_escape_returns_focus_after_the_grid_rebuilds_under_the_panel(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl
) -> None:
    # 18-13 F21: a rebuild while the panel is open replaces the opener cell.
    page = nfl_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, open_nfl_app)
    cell = page.locator(".wk-row[data-row=cbs] .wk-cell").first
    wk_id = cell.get_attribute("data-wk-id")
    cell.focus()
    cell.press("Enter")
    page.locator("dialog[open]").first.wait_for()
    page.evaluate(
        "(id) => { window.__oldCell = [...document.querySelectorAll('[data-wk-id]')]"
        ".find((n) => n.dataset.wkId === id); }",
        wk_id,
    )
    page.set_viewport_size({"width": 1300, "height": 900})
    page.wait_for_function("!window.__oldCell.isConnected")
    page.keyboard.press("Escape")
    # The close event that restores focus is queued after the dialog closes.
    page.wait_for_function("(id) => document.activeElement?.dataset?.wkId === id", arg=wk_id)


def test_week_and_day_round_trip_and_invalid_dropped(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    assert "week=" not in page.url
    assert "day=" not in page.url
    page.click(".wk-step--prev")
    assert "week=4" in page.url
    assert page.locator(".wk-week").inner_text() == "Week 4"
    page.reload()
    page.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.ready === true")
    assert page.locator(".wk-week").inner_text() == "Week 4"
    # Week 1 has a Thursday and a Sunday; the Sunday default is omitted, Thursday is kept as the
    # weekday token both sports use (18-UI-SPEC; 18-13 F23).
    page.goto(page.url.split("?")[0] + "?sport=nfl&view=weekend&week=1&day=thu")
    page.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.ready === true")
    assert "week=1" in page.url
    assert "day=thu" in page.url
    assert page.locator(".wk-day[aria-selected=true]").inner_text().startswith("Thu.")
    page.click(".wk-day >> nth=1")
    assert "day=" not in page.url
    for bad in ("week=99", "week=abc", "week=6", "day=nope", "day=2026-09-10", "day=mon"):
        page.goto(page.url.split("?")[0] + f"?sport=nfl&view=weekend&{bad}")
        page.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.ready === true")
        key = bad.split("=")[0]
        assert f"{key}=" not in page.url
        assert page.locator(".wk-week").inner_text() == "Week 5"


def test_week_step_keeps_the_weekday_when_the_next_week_has_it(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl, nfl_fixture_raw: dict[str, Any]
) -> None:
    # 18-13 F22: stepping weeks keeps the selected weekday when the destination week has it.
    raw = copy.deepcopy(nfl_fixture_raw)
    games = raw["games"]
    k = next(
        i
        for i, (s, w) in enumerate(zip(games["season"], games["week"], strict=True))
        if s == 2026 and w == 2
    )
    games["date"][k] = "2026-09-17"  # a week-2 Thursday game
    page = nfl_guarded_page
    page.route("**/nfl-data.json*", lambda route: route.fulfill(json=raw))
    _open(page, open_nfl_app, "&week=1&day=thu")
    assert "day=thu" in page.url
    page.click(".wk-step--next")
    assert "week=2" in page.url
    assert "day=thu" in page.url
    assert page.locator(".wk-day[aria-selected=true]").inner_text().startswith("Thu. Sept. 17")
    page.click(".wk-step--next")
    assert "week=3" in page.url
    assert "day=" not in page.url


def test_reopening_the_tab_lands_on_the_current_weekend(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl
) -> None:
    # 18-13 F16: another tab never keeps the weekend's week.
    page = nfl_guarded_page
    _open(page, open_nfl_app, "&week=4")
    assert page.locator(".wk-week").inner_text() == "Week 4"
    page.click("#nfl-chart-tabs [role=tab] >> nth=0")
    assert "week=" not in page.url
    page.click("#nfl-tab-weekend")
    assert page.locator(".wk-week").inner_text() == "Week 5"
    assert "week=" not in page.url


def test_finished_season_shows_the_past_week_stamp(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl, nfl_fixture_raw: dict[str, Any]
) -> None:
    # 18-13 F17: after the season (no weekend stamp, no upcoming games) the tab shows the latest
    # played week, so its stamp is the past-week line, never "not posted yet ... Crew TBA".
    raw = copy.deepcopy(nfl_fixture_raw)
    raw["freshness"]["weekend"] = None
    raw["upcoming"] = {key: [] for key in raw["upcoming"]}
    page = nfl_guarded_page
    page.route("**/nfl-data.json*", lambda route: route.fulfill(json=raw))
    _open(page, open_nfl_app)
    assert page.locator(".wk-week").inner_text() == "Week 4"
    assert page.locator(".wk-stamp").inner_text() == "Crews: 506 Sports, as saved."
    assert page.locator(".wk-cell .wk-booth", has_text="Crew TBA").count() == 0


def test_upcoming_only_announcer_stays_out_of_the_shared_picker(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl, nfl_fixture_raw: dict[str, Any]
) -> None:
    # 18-13 F9: the Announcers list every NFL tab shares offers people on a played game only;
    # a person known only from an upcoming crew would zero every other tab.
    raw = copy.deepcopy(nfl_fixture_raw)
    people = raw["lookups"]["people"]
    idx = len(people)
    people.append({"id": "p-upcoming-only", "name": "Uma Upcoming"})
    raw["upcoming"]["crew"][0][0]["person"] = idx
    page = nfl_guarded_page
    page.route("**/nfl-data.json*", lambda route: route.fulfill(json=raw))
    open_nfl_app(page, "?sport=nfl")
    assert page.locator('li[data-person="p-upcoming-only"]').count() == 0
    assert page.locator("li[data-person]").count() > 0


def test_next_week_step_is_disabled_on_the_latest_week(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    assert nfl_guarded_page.locator(".wk-step--next").get_attribute("aria-disabled") == "true"


def test_phone_list_orders_cbs_rows_by_booth_rank(nfl_mobile_page: Page, nfl_site_url: str) -> None:
    page = nfl_mobile_page
    page.add_init_script(f"window.__nflWeekendNow = '{NOW}'")
    page.goto(f"{nfl_site_url}/index.html?sport=nfl&view=weekend")
    page.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.ready === true")
    page.wait_for_selector(".wk-root--list")
    one = page.locator(".wk-group[data-time='780'] .wk-item")
    texts = one.all_inner_texts()
    cbs = [t for t in texts if "CBS" in t or "Strand" in t or "Pryor" in t or "Crew TBA" in t]
    assert "Strand" in cbs[0]
    assert "Pryor" in cbs[1]
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")


def test_dark_theme_renders(nfl_guarded_page: Page, open_nfl_app: OpenNfl) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    # Known-crew fills are deepened to the same 7:1 white-text fill in both themes, so the
    # check is the page background instead (user sign-off 2026-10-26).
    light = page.evaluate("getComputedStyle(document.body).backgroundColor")
    set_theme(page, "dark")
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    assert page.locator(".wk-cell").count() == 10
    cell = page.locator(".wk-row[data-row=cbs] .wk-cell").first
    assert cell.evaluate("(n) => getComputedStyle(n).backgroundColor") not in (
        "",
        "rgba(0, 0, 0, 0)",
    )
    assert cell.evaluate("(n) => getComputedStyle(n).color") == "rgb(255, 255, 255)"
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") != light


def test_no_cfbd_text_on_the_nfl_page(nfl_guarded_page: Page, open_nfl_app: OpenNfl) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    text = page.locator("body").inner_text().lower()
    page.click(".wk-step--prev")
    text += page.locator("body").inner_text().lower()
    assert "collegefootballdata" not in text
    assert "cfbd" not in text
    assert page.locator("a[href*='collegefootballdata']").count() == 0


def test_keyboard_reaches_a_cell(nfl_guarded_page: Page, open_nfl_app: OpenNfl) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    page.locator(".wk-row[data-row=cbs] .wk-cell").first.focus()
    page.keyboard.press("ArrowDown")
    focused = page.evaluate("document.activeElement.querySelector('.wk-booth').textContent")
    assert focused == "Pryor · Reyes"
