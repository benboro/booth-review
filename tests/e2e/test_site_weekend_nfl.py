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


def _open(page: Page, open_nfl_app: OpenNfl, query: str = "", now: str = NOW) -> None:
    page.add_init_script(f"window.__nflWeekendNow = '{now}'")
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


def test_one_page_per_week_with_no_day_tabs(nfl_guarded_page: Page, open_nfl_app: OpenNfl) -> None:
    """User 2026-11-09: the NFL weekend is one page per week, not split by day."""
    _open(nfl_guarded_page, open_nfl_app)
    assert nfl_guarded_page.locator(".wk-day").count() == 0
    assert nfl_guarded_page.locator("#nfl-chart-subtitle").inner_text() == "Week 5, all times ET"
    bands = nfl_guarded_page.locator(".wk-dayband-label").all_inner_texts()
    assert bands == ["Sun. Oct. 11"]
    assert nfl_guarded_page.locator("#nfl-matched-games").is_hidden()


def _week1_with_monday(nfl_fixture_raw: dict[str, Any]) -> dict[str, Any]:
    """Week 1 of the fixture (a Thursday and a Sunday) plus a week-2 game moved to its Monday."""
    raw = copy.deepcopy(nfl_fixture_raw)
    games = raw["games"]
    k = next(
        i
        for i, (s, w, d) in enumerate(
            zip(games["season"], games["week"], games["date"], strict=True)
        )
        if s == 2026 and w == 2 and d == "2026-09-20"
    )
    games["week"][k] = 1
    games["date"][k] = "2026-09-14"
    games["kickoff"][k] = "2026-09-14T20:15:00-04:00"
    return raw


def test_whole_week_stacks_thursday_above_sunday_above_monday(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl, nfl_fixture_raw: dict[str, Any]
) -> None:
    """User 2026-11-09: one timeline for the week, each day's rows under its own heading in
    date order, on one shared time axis."""
    page = nfl_guarded_page
    raw = _week1_with_monday(nfl_fixture_raw)
    page.route("**/nfl-data.json*", lambda route: route.fulfill(json=raw))
    _open(page, open_nfl_app, "&week=1")
    assert page.locator(".wk-dayband-label").all_inner_texts() == [
        "Thu. Sept. 10",
        "Sun. Sept. 13",
        "Mon. Sept. 14",
    ]
    assert page.locator(".wk-axis").count() == 1
    dates = page.evaluate(
        "() => [...document.querySelectorAll('.wk-row')].map((r) => r.dataset.date)"
    )
    assert dates == sorted(dates)
    assert dates[0] == "2026-09-10"
    assert dates[-1] == "2026-09-14"
    # Every game of the week is on the one page, and the summary counts them all.
    cells = page.locator(".wk-cell").count()
    assert page.locator("#nfl-summary").inner_text() == f"{cells} of {cells} games match"
    # The band labels stay put while the lane scrolls sideways.
    position = page.locator(".wk-dayband-label").first.evaluate(
        "(n) => getComputedStyle(n).position"
    )
    assert position == "sticky"


def test_phone_list_names_the_day_in_each_kickoff_group(
    nfl_mobile_page: Page, nfl_site_url: str, nfl_fixture_raw: dict[str, Any]
) -> None:
    """On a phone, the week's games group by day and kickoff, so Thursday's and Monday's night
    games never share a group."""
    page = nfl_mobile_page
    raw = _week1_with_monday(nfl_fixture_raw)
    page.route("**/nfl-data.json*", lambda route: route.fulfill(json=raw))
    page.add_init_script(f"window.__nflWeekendNow = '{NOW}'")
    page.goto(f"{nfl_site_url}/index.html?sport=nfl&view=weekend&week=1")
    page.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.ready === true")
    page.wait_for_selector(".wk-root--list")
    titles = page.locator(".wk-group[data-date] .wk-group-title").all_inner_texts()
    assert titles[0].startswith("Thu. Sept. 10, ")
    assert titles[-1] == "Mon. Sept. 14, 8:15 pm"
    dates = page.evaluate(
        "() => [...document.querySelectorAll('.wk-group[data-date]')].map((g) => g.dataset.date)"
    )
    assert dates == sorted(dates)


def test_cbs_window_is_four_sub_rows_by_booth_rank(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    cells = _row_cells(nfl_guarded_page, "cbs")
    assert [c["top"] for c in cells] == [0, 48, 96, 144]
    assert all(c["time"] == "1:00" for c in cells)
    # Rank 1 on top, rank 2 under it, the crewless games last; every crew visible.
    assert cells[0]["star"] is True
    assert cells[0]["booth"] == "Ivo Strand · Jun Vale"
    assert cells[1]["booth"] == "Ned Pryor · Opal Reyes"
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
    assert "networks: Wikipedia (CC BY-SA 4.0)" in text
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
    # The whole-week page names each strip game's day (it sits outside the day groups), and
    # every cell's accessible name carries its date.
    times = body.locator(".wk-time").all_inner_texts()
    assert times
    assert all(t.startswith("Sun. ") for t in times), times
    grid_label = nfl_guarded_page.locator(".wk-row .wk-cell").first.get_attribute("aria-label")
    assert (grid_label or "").startswith("Sun. Oct. 11, ")


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


def test_kicked_off_upcoming_game_panel_matches_its_cell(
    nfl_guarded_page: Page, open_nfl_app: OpenNfl
) -> None:
    # WR-01: past the 1:00 kickoffs, an upcoming row reads as played, as its cell does.
    page = nfl_guarded_page
    _open(page, open_nfl_app, now="2026-10-11T14:00:00-04:00")
    dialog = page.locator("dialog[open]").first
    cbs = page.locator(".wk-row[data-row=cbs] .wk-cell")
    bare = cbs.filter(has_text="Crew not listed").first
    bare.click()
    dialog.wait_for()
    text = dialog.inner_text()
    assert "Not played yet." not in text
    assert "Crew not listed." in text
    assert "Viewers: not available (not posted yet)" in text
    assert "Final score" not in text
    page.keyboard.press("Escape")
    crewed = cbs.filter(has=page.locator(".wk-star")).first
    crewed.click()
    dialog.wait_for()
    text = dialog.inner_text()
    assert "Not played yet." not in text
    assert "Crew from 506 Sports" in text
    page.keyboard.press("Escape")
    # The 4:25 window has not kicked off yet.
    page.locator(".wk-row[data-row=fox] .wk-cell").first.click()
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


def test_week_round_trip_and_invalid_dropped(nfl_guarded_page: Page, open_nfl_app: OpenNfl) -> None:
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
    # An old link's day is dropped: the page shows the whole week (user 2026-11-09).
    page.goto(page.url.split("?")[0] + "?sport=nfl&view=weekend&week=1&day=thu")
    page.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.ready === true")
    assert "week=1" in page.url
    assert "day=" not in page.url
    assert page.locator(".wk-dayband-label").count() == 2
    for bad in ("week=99", "week=abc", "week=6", "day=nope", "day=2026-09-10", "day=mon"):
        page.goto(page.url.split("?")[0] + f"?sport=nfl&view=weekend&{bad}")
        page.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.ready === true")
        key = bad.split("=")[0]
        assert f"{key}=" not in page.url
        assert page.locator(".wk-week").inner_text() == "Week 5"


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
    assert focused == "Ned Pryor · Opal Reyes"


# ---- v2.1 polish (18-UI-REVIEW items 6 and 8) ----


def test_summary_counts_the_weeks_games(nfl_guarded_page: Page, open_nfl_app: OpenNfl) -> None:
    # 18-UI-REVIEW item 6: the NFL summary was blank on This weekend, leaving a 60px band and
    # no "n of total games match" feedback under a pick.
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    cells = page.locator(".wk-cell").count()
    assert cells > 1
    assert page.locator("#nfl-summary").inner_text() == f"{cells} of {cells} games match"
    team_id = page.evaluate(
        "(async () => { const r = await fetch('nfl-data.json'); const j = await r.json();"
        " return j.lookups.franchises.find((f) => f.name.includes('Granite Bay')).id; })()"
    )
    page.evaluate("(id) => window.__nflTestHooks.setState({ teams: [id] })", team_id)
    matched = page.locator(".wk-cell.is-match").count()
    assert 1 <= matched < cells
    assert page.locator("#nfl-summary").inner_text() == f"{matched} of {cells} games match"


def test_weekend_panel_uses_the_ap_kickoff(nfl_guarded_page: Page, open_nfl_app: OpenNfl) -> None:
    # 18-UI-REVIEW item 8: the panel opened from a cell writes the kickoff as the view does.
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    page.locator(".wk-row[data-row=cbs] .wk-cell").first.click()
    dialog = page.locator("dialog[open]").first
    dialog.wait_for()
    assert dialog.locator("p").first.inner_text() == "Sun. Oct. 11, 1:00 pm ET"
    page.keyboard.press("Escape")
    # A Time TBA strip game has no clock.
    strip = page.locator(".wk-tba-body .wk-cell")
    if strip.count():
        strip.first.click()
        dialog.wait_for()
        assert dialog.locator("p").first.inner_text().endswith(", Time TBA")


def test_map_switch_round_trip(nfl_guarded_page: Page, open_nfl_app: OpenNfl) -> None:
    """Phase 24-09: the Map segment mounts the weekend map, sets wview=map and keeps the week;
    Timeline unmounts it and drops wview."""
    _open(nfl_guarded_page, open_nfl_app)
    week = nfl_guarded_page.locator(".wk-week").inner_text()
    nfl_guarded_page.click('[data-wk-id="wview:map"]')
    nfl_guarded_page.wait_for_function("location.search.includes('wview=map')")
    assert nfl_guarded_page.locator(".wk-week").inner_text() == week
    nfl_guarded_page.click('[data-wk-id="wview:timeline"]')
    nfl_guarded_page.wait_for_function("!location.search.includes('wview=map')")
    nfl_guarded_page.wait_for_selector(".wk-row")
    assert nfl_guarded_page.locator(".js-plotly-plot").count() == 0


def test_international_game_names_its_city(nfl_guarded_page: Page, open_nfl_app: OpenNfl) -> None:
    """An international game's matchup tooltip and accessible name say where it is played,
    and its panel's location line carries "(neutral site)"."""
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    match = page.locator(".wk-cell .wk-match[title]")
    assert match.count() == 1
    assert match.get_attribute("title") == "Played in Londonish, United Kingdom"
    cell = page.locator(".wk-cell:has(.wk-match[title])")
    assert "Played in Londonish, United Kingdom." in (cell.get_attribute("aria-label") or "")
    assert "Londonish" not in cell.inner_text()
    cell.click()
    dialog = page.locator("dialog[open]").first
    dialog.wait_for()
    assert (
        dialog.locator(".panel-location").text_content()
        == "Test Park, Londonish, United Kingdom (neutral site)"
    )
    # The fixture's slot is itself named International; only the separate flag goes.
    assert dialog.locator(".panel-facts").text_content() == "Slot: International."
