"""CFB This weekend tab, end to end (Phase 18, plan 10): the sixth tab on the CFB page, its URL
state, picks, greyed filters, detail panel wiring and phone list, on the synthetic contract
fixture only (never vault data).

Fixture facts (18-01): week "5" is 2026-09-28..2026-10-04 (the current weekend), and Saturday
2026-10-03 holds merged index 11 (rated, played, 12:00), merged index 19 (the pending unrated
game, Ironpeak at Stonebridge 7:30 pm, crew persons 4 and 5) and nine scheduled rows. The shared
fixture's network ids are not real grid ids and it has no espn-plus network or tier-a booth, so
`_weekend_raw` builds those in the test: real network ids, an ESPN+ row, a Friday game and a
tier-a booth on the pending game. The clock is fixed to Saturday morning ET unless a test sets
its own.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from dark_checks import set_theme, settle
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

MORNING = "2026-10-03T09:00:00-04:00"
AFTERNOON = "2026-10-03T14:00:00-04:00"
# The pending unrated game (merged 19) is called by the tier-a booth added below.
LEAD = '[data-wk-id="g:cfb:t:19"]'
PLAYED = '[data-wk-id="g:cfb:t:11"]'
FOX_NOON = '[data-wk-id="g:cfb:scheduled:0"]'
TBD_KICKOFF = '[data-wk-id="g:cfb:scheduled:3"]'
RANKED = '[data-wk-id="g:cfb:scheduled:6"]'
FRIDAY_ROW = '[data-wk-id="g:cfb:scheduled:9"]'
ESPN_PLUS = "g:cfb:scheduled:10"

_REAL_IDS = ["espn", "fox", "acc-network", "cbs", "peacock"]


def _weekend_raw(fixture_raw: dict[str, Any], *, extra_tba: int = 0) -> dict[str, Any]:
    """The contract fixture with real network ids, an ESPN+ network, a tier-a disney booth on the
    pending game, a Friday fox game and an ESPN+ Saturday game (scheduled indexes 9 and 10)."""
    raw = copy.deepcopy(fixture_raw)
    nets = raw["lookups"]["networks"]
    for net, real in zip(nets, _REAL_IDS, strict=True):
        net["id"] = real
    nets.append({"id": "espn-plus", "name": "ESPN+", "family": "disney"})
    raw["lookups"]["booths"] = [
        {
            "family": "disney",
            "season": 2026,
            "pbp": 4,
            "analyst": 5,
            "rank": 1,
            "tier": "a",
            "lead_network": None,
        }
    ]
    raw["telecasts"]["booth"] = [None] * len(raw["telecasts"]["season"])
    raw["telecasts_unrated"]["booth"] = [None] * len(raw["telecasts_unrated"]["season"])
    raw["telecasts_unrated"]["booth"][7] = 0
    sched = raw["telecasts_scheduled"]

    def add(date: str, kickoff: str | None, network: int | None, away: int, home: int) -> None:
        row: dict[str, Any] = {
            "season": 2026,
            "date": date,
            "kickoff": kickoff,
            "time_slot": "prime" if kickoff else None,
            "away_team": away,
            "home_team": home,
            "neutral": False,
            "away_rank": None,
            "home_rank": None,
            "network": network,
            "outlets": [],
            "crew": [],
            "crew_source_url": None,
            "crew_source_label": None,
            "home_conference": 0,
            "away_conference": 3,
            "place": None,
            "week": "5",
        }
        assert row.keys() == sched.keys()
        for key, value in row.items():
            sched[key].append(value)

    add("2026-10-02", "2026-10-02T20:00:00-04:00", 1, 0, 2)  # 9: Friday, fox
    add("2026-10-03", "2026-10-03T18:00:00-04:00", 5, 3, 1)  # 10: Saturday, ESPN+
    for k in range(extra_tba):
        add("2026-10-03", None, None, 0, 1 + (k % 7))
    return raw


@pytest.fixture
def serve_weekend(
    fixture_raw: dict[str, Any],
) -> Callable[..., None]:
    def _serve(
        page: Page,
        *,
        now: str = MORNING,
        extra_tba: int = 0,
        tweak: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        raw = _weekend_raw(fixture_raw, extra_tba=extra_tba)
        if tweak is not None:
            tweak(raw)
        page.clock.set_fixed_time(now)
        page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))

    return _serve


@pytest.fixture
def wk(
    guarded_page: Page,
    serve_weekend: Callable[..., None],
    open_app: Callable[[Page, str], None],
) -> Callable[..., Page]:
    guarded_page.set_viewport_size({"width": 1440, "height": 900})

    def _open(query: str = "?view=weekend", **kw: Any) -> Page:
        serve_weekend(guarded_page, **kw)
        open_app(guarded_page, query)
        return guarded_page

    return _open


def _state(page: Page) -> dict[str, Any]:
    return page.evaluate("window.__testHooks.getState()")  # type: ignore[no-any-return]


def _url(page: Page) -> str:
    return page.evaluate("location.search")  # type: ignore[no-any-return]


def test_tab_is_the_sixth_and_selected_by_the_url(wk: Callable[..., Page]) -> None:
    page = wk()
    tabs = page.locator("#chart-tabs button[role=tab]")
    assert tabs.count() == 6
    last = tabs.nth(5)
    assert last.get_attribute("data-view") == "weekend"
    assert last.inner_text() == "This weekend"
    assert last.get_attribute("aria-selected") == "true"
    assert page.locator("#chart-title").inner_text() == "This weekend"
    assert page.locator("#weekend-panel").is_visible()
    assert page.locator("#chart").is_hidden()
    assert page.evaluate("window.__testHooks.lastPanel") == "weekend"


def test_subtitle_and_summary_line(wk: Callable[..., Page]) -> None:
    page = wk()
    assert page.locator("#chart-subtitle").inner_text() == "Week 5, Sat. Oct. 3, all times ET"
    # Saturday: 2 played rows (11, 19) + 10 scheduled on that day (index 9 is Friday).
    count = page.locator("#summary-count").inner_text()
    assert count.endswith(" of 12 games match")
    assert count.startswith("12 of")


def test_summary_line_survives_crossing_the_phone_width(wk: Callable[..., Page]) -> None:
    """26-10 critique: a second, topbar-only render on the phone-width change ran after the app
    render and put the all-games count ("N rated of M games") back over This weekend's count."""
    page = wk()
    before = page.locator("#summary-count").inner_text()
    assert before.endswith(" games match")
    for width in (390, 1440):
        page.set_viewport_size({"width": width, "height": 900})
        phone = "true" if width == 390 else "false"
        page.wait_for_function(f"window.matchMedia('(max-width: 480px)').matches === {phone}")
        page.wait_for_timeout(200)
        assert page.locator("#summary-count").inner_text() == before, width


def test_opening_the_tab_makes_no_request(
    guarded_page: Page,
    serve_weekend: Callable[..., None],
    open_app: Callable[[Page, str], None],
) -> None:
    serve_weekend(guarded_page)
    open_app(guarded_page, "")
    seen: list[str] = []
    guarded_page.on("request", lambda req: seen.append(req.url))
    guarded_page.locator("#tab-weekend").click()
    expect(guarded_page.locator("#weekend-panel .wk-grid")).to_be_visible()
    guarded_page.locator(".wk-step--prev").click()
    expect(guarded_page.locator("#chart-subtitle")).to_contain_text("Week 4")
    # Network marks are static same-origin images; no data, API or off-origin request is made
    # (the guard teardown also fails the test on any off-origin request).
    assert [u for u in seen if "/logos/" not in u] == []


def test_day_tabs_and_default_day(wk: Callable[..., Page]) -> None:
    page = wk()
    tabs = page.locator(".wk-days .wk-day")
    assert tabs.all_inner_texts() == ["Fri. Oct. 2 (1)", "Sat. Oct. 3 (12)"]
    assert page.locator(".wk-day[aria-selected=true]").inner_text() == "Sat. Oct. 3 (12)"
    page.locator(".wk-day", has_text="Fri.").click()
    assert _state(page)["day"] == "fri"
    assert _url(page) == "?view=weekend&day=fri"
    assert page.locator(FRIDAY_ROW).is_visible()
    assert page.locator("#chart-subtitle").inner_text() == "Week 5, Fri. Oct. 2, all times ET"


def test_cell_shows_two_lines_the_lead_star_and_crew_tba(wk: Callable[..., Page]) -> None:
    page = wk()
    lead = page.locator(LEAD)
    assert lead.locator(".wk-line1").inner_text().endswith("Ironpeak @ Stonebridge")
    booth = lead.locator(".wk-line2")
    assert "Rowan" in booth.inner_text()
    assert "Delgado" in booth.inner_text()
    assert lead.locator(".wk-star").count() == 1
    # A scheduled row has no crew and kickoff is still ahead (Saturday 9 am ET).
    assert page.locator(FOX_NOON).locator(".wk-line2").inner_text() == "Crew TBA"
    assert page.locator(FOX_NOON).locator(".wk-star").count() == 0


def test_same_kickoff_games_stack_in_sub_rows(wk: Callable[..., Page]) -> None:
    page = wk()
    tops = page.evaluate(
        """() => [...document.querySelectorAll('[data-row="fox"] .wk-cell')]
          .filter((c) => c.dataset.wkId.startsWith('g:cfb:scheduled:'))
          .map((c) => Math.round(c.getBoundingClientRect().top))"""
    )
    noon = tops[:3]
    assert len(set(noon)) == 3  # three 12:00 fox games, three sub-rows


def test_time_tba_strip_counts_and_collapses_at_seven(wk: Callable[..., Page]) -> None:
    page = wk()
    strip = page.locator(".wk-tba")
    assert strip.is_visible()
    # Scheduled 3 (no kickoff) and 4 (no network) sit in the strip, open under seven games.
    assert strip.locator(".wk-cell").count() == 2
    assert strip.locator(".wk-tba-head").get_attribute("aria-expanded") == "true"
    page = wk(extra_tba=5)
    assert page.locator(".wk-tba .wk-tba-head").get_attribute("aria-expanded") == "false"
    page.locator(".wk-tba .wk-tba-head").click()
    assert page.locator(".wk-tba .wk-cell").count() == 7


def test_espn_plus_game_goes_to_the_compact_table(wk: Callable[..., Page]) -> None:
    page = wk()
    table = page.locator(".wk-compact-table")
    assert table.is_visible()
    assert table.locator(".wk-crow").count() >= 1
    assert "ESPN+" in page.locator(".wk-compact").inner_text() or table.locator("img").count() > 0
    # The ESPN+ game never becomes a grid row.
    assert page.locator('[data-row="espn-plus"]').count() == 0


def test_announcers_pick_fades_and_rings_and_survives_a_tab_switch(
    wk: Callable[..., Page],
) -> None:
    page = wk()
    page.evaluate(
        "(id) => window.__testHooks.setState({ people: [id] })",
        page.evaluate("window.__testHooks.data.lookups.people[4].id"),
    )
    expect(page.locator(LEAD)).to_have_class(__import__("re").compile(r"is-match"))
    assert page.locator(FOX_NOON).evaluate("e => getComputedStyle(e).opacity") == "0.3"
    assert page.locator(LEAD).evaluate("e => getComputedStyle(e).opacity") == "1"
    ring = page.locator(LEAD).evaluate("e => getComputedStyle(e).boxShadow")
    assert "inset" in ring
    assert page.locator("#summary-count").inner_text() == "1 of 12 games match"
    # The pick carries to Crews and back.
    page.locator("#tab-crews").click()
    assert _state(page)["people"]
    page.locator("#tab-weekend").click()
    expect(page.locator(LEAD)).to_have_class(__import__("re").compile(r"is-match"))
    assert page.locator(FOX_NOON).evaluate("e => getComputedStyle(e).opacity") == "0.3"
    # Picks add a match count to each day tab.
    assert page.locator(".wk-day", has_text="Sat.").inner_text().endswith("(1)")


def test_networks_pick_fades_whole_rows(wk: Callable[..., Page]) -> None:
    page = wk()
    page.evaluate("window.__testHooks.setState({ networks: ['espn'] })")
    expect(page.locator('[data-row="fox"] .wk-cell').first).to_have_class(
        __import__("re").compile(r"is-faded")
    )
    assert page.locator('[data-row="fox"]').evaluate("e => getComputedStyle(e).opacity") in (
        "0.3",
        "1",
    )
    assert page.locator(LEAD).evaluate("e => getComputedStyle(e).opacity") == "1"


def test_unused_filters_are_greyed_with_a_hint(wk: Callable[..., Page]) -> None:
    page = wk()
    seasons = page.locator("#trigger-seasons")
    assert seasons.get_attribute("aria-disabled") == "true"
    assert seasons.get_attribute("title") == "This weekend shows one week; use the week stepper."
    for name in ("kickoff", "postseason", "game"):
        trigger = page.locator(f"#trigger-{name}")
        assert trigger.get_attribute("aria-disabled") == "true"
        assert trigger.get_attribute("title") == "Not used on This weekend"
    assert page.locator("#dots-toggle button[data-dots=hide]").get_attribute("aria-disabled") == (
        "true"
    )
    # Used filters stay live.
    assert page.locator("#trigger-announcers").get_attribute("aria-disabled") is None
    assert page.locator("#trigger-networks").get_attribute("aria-disabled") is None
    # A greyed trigger opens nothing, and the greying lifts on another tab.
    seasons.click(force=True)
    assert not page.evaluate("document.querySelector('#pop-seasons').matches(':popover-open')")
    page.locator("#tab-scatter").click()
    assert seasons.get_attribute("aria-disabled") is None
    assert seasons.get_attribute("popovertarget") == "pop-seasons"
    assert (
        page.locator("#dots-toggle button[data-dots=hide]").get_attribute("aria-disabled") is None
    )


def test_scheduled_cell_opens_the_panel_and_escape_returns_focus(wk: Callable[..., Page]) -> None:
    page = wk()
    cell = page.locator(FOX_NOON)
    cell.focus()
    cell.press("Enter")
    dialog = page.locator("#detail-panel, dialog[open]").first
    expect(dialog).to_be_visible()
    assert "Not played yet." in dialog.inner_text()
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    assert page.evaluate("document.activeElement.dataset.wkId") == "g:cfb:scheduled:0"


def test_escape_returns_focus_after_the_grid_rebuilds_under_the_panel(
    wk: Callable[..., Page],
) -> None:
    # 18-13 F21: the minute clock (and a resize) rebuild every cell while a panel is open; the
    # panel must still return focus to that game's new cell.
    page = wk()
    cell = page.locator(FOX_NOON)
    cell.focus()
    cell.press("Enter")
    expect(page.locator("dialog[open]")).to_be_visible()
    page.evaluate("window.__oldCell = document.querySelector('[data-wk-id=\"g:cfb:scheduled:0\"]')")
    page.set_viewport_size({"width": 1300, "height": 900})
    page.wait_for_function("!window.__oldCell.isConnected")
    page.keyboard.press("Escape")
    expect(page.locator("dialog[open]")).to_have_count(0)
    # The close event that restores focus is queued after the dialog closes.
    page.wait_for_function("document.activeElement?.dataset?.wkId === 'g:cfb:scheduled:0'")


def test_shipped_unplayed_cell_opens_with_its_crew_credit(wk: Callable[..., Page]) -> None:
    page = wk()
    cell = page.locator(LEAD)
    cell.focus()
    cell.press("Enter")
    dialog = page.locator("dialog[open]")
    expect(dialog).to_be_visible()
    text = dialog.inner_text()
    assert "Not played yet." in text
    assert "Pat Rowan" in text
    assert "Sam Delgado" in text
    page.keyboard.press("Escape")
    assert page.evaluate("document.activeElement.dataset.wkId") == "g:cfb:t:19"


def test_unplayed_cell_credits_an_awful_announcing_crew(wk: Callable[..., Page]) -> None:
    # Phase 27: an AA-sourced crew on an unplayed game is credited to its post, as a link.
    url = "https://awfulannouncing.com/college-football/example-week-announcing-schedule.html"

    def tweak(raw: dict[str, Any]) -> None:
        unrated = raw["telecasts_unrated"]
        unrated["crew_source_label"][-1] = "Awful Announcing"
        unrated["crew_source_url"][-1] = url

    page = wk(tweak=tweak)
    page.locator(LEAD).focus()
    page.locator(LEAD).press("Enter")
    dialog = page.locator("dialog[open]")
    expect(dialog).to_be_visible()
    link = dialog.locator("a", has_text="Crew source: Awful Announcing")
    assert link.count() == 1
    assert link.get_attribute("href") == url


def _panel_text(page: Page, selector: str) -> str:
    cell = page.locator(selector)
    cell.focus()
    cell.press("Enter")
    dialog = page.locator("dialog[open]")
    expect(dialog).to_be_visible()
    text = dialog.inner_text()
    page.keyboard.press("Escape")
    return text


def test_panel_after_kickoff_matches_the_crew_not_listed_cell(wk: Callable[..., Page]) -> None:
    # 18-13 F3: once a scheduled game kicks off its cell reads "Crew not listed", so its panel
    # no longer says "Not played yet." or "Crew TBA".
    page = wk(now=AFTERNOON)
    text = _panel_text(page, FOX_NOON)
    assert "Not played yet." not in text
    assert "Crew TBA" not in text
    assert "Crew not recorded" in text
    assert "viewership not posted yet" in text
    assert "null" not in text
    # The 3:30 pm game is still ahead.
    assert "Not played yet." in _panel_text(page, RANKED)


def test_rarely_rated_upcoming_game_opens_as_not_played(wk: Callable[..., Page]) -> None:
    # 18-13 F4: a 506-listed upcoming game on a rarely rated network has cause rarely_rated,
    # not pending; it is still unplayed before kickoff.
    def rarely(raw: dict[str, Any]) -> None:
        raw["telecasts_unrated"]["cause"][7] = "rarely_rated"

    page = wk(tweak=rarely)
    text = _panel_text(page, LEAD)
    assert "Not played yet." in text
    assert "rarely rated" not in text


def test_week_stepper_writes_week_and_stops_at_the_latest(wk: Callable[..., Page]) -> None:
    page = wk()
    next_button = page.locator(".wk-step--next")
    assert next_button.get_attribute("aria-disabled") == "true"
    assert next_button.get_attribute("title") == "Latest week"
    prev = page.locator(".wk-step--prev")
    assert prev.get_attribute("aria-label") == "Previous week, Week 4"
    prev.click()
    assert _url(page) == "?view=weekend&week=4"
    assert page.locator(".wk-week").inner_text() == "Week 4"
    assert page.locator("#chart-subtitle").inner_text().startswith("Week 4, Sat. Sept. 26")
    assert page.evaluate("document.activeElement.dataset.wkId") == "step:prev"
    assert page.locator(".wk-step--next").get_attribute("aria-disabled") is None
    page.locator(".wk-step--next").click()
    assert _url(page) == "?view=weekend"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("?view=weekend&day=fri", "?view=weekend&day=fri"),
        ("?view=weekend&day=sat", "?view=weekend"),
        ("?view=weekend&day=zzz", "?view=weekend"),
        ("?view=weekend&day=mon", "?view=weekend"),
        ("?view=weekend&week=5", "?view=weekend"),
        ("?view=weekend&week=99", "?view=weekend"),
        ("?view=weekend&week=abc", "?view=weekend"),
        ("?view=weekend&week=4", "?view=weekend&week=4"),
        ("?view=weekend&week=4&day=fri", "?view=weekend&week=4"),
    ],
)
def test_url_state_round_trips_and_drops_invalid_values(
    wk: Callable[..., Page], query: str, expected: str
) -> None:
    page = wk(query)
    assert _url(page) == expected


def test_week_and_day_belong_to_the_weekend_tab_only(wk: Callable[..., Page]) -> None:
    # 18-13 F16: week and day never ride along on another tab's URL, and reopening the tab
    # lands on the current weekend (18-UI-SPEC).
    page = wk("?view=weekend&week=4")
    assert "week=4" in _url(page)
    page.click("#chart-tabs button[data-view=scatter]")
    assert "week=" not in _url(page)
    page.click("#chart-tabs button[data-view=weekend]")
    assert page.locator(".wk-week").inner_text() == "Week 5"
    assert "week=" not in _url(page)
    page.goto(page.url.split("?")[0] + "?view=scatter&week=4&day=fri")
    page.wait_for_function("window.__testHooks && window.__testHooks.getState")
    assert "week=" not in _url(page) and "day=" not in _url(page)


def test_arrow_keys_rove_across_cells(wk: Callable[..., Page]) -> None:
    page = wk()
    first = page.locator('[data-row="fox"] .wk-cell').first
    first.focus()
    start = page.evaluate("document.activeElement.dataset.wkId")
    page.keyboard.press("ArrowDown")
    down = page.evaluate("document.activeElement.dataset.wkId")
    assert down != start
    page.keyboard.press("ArrowUp")
    assert page.evaluate("document.activeElement.dataset.wkId") == start


def test_now_line_and_crew_not_listed_follow_the_clock(wk: Callable[..., Page]) -> None:
    page = wk(now=AFTERNOON)
    assert page.locator(".wk-now").count() == 1
    # Kickoff 12:00 has passed and no crew is listed.
    assert page.locator(FOX_NOON).locator(".wk-line2").inner_text() == "Crew not listed"
    # The 3:30 pm game is still ahead.
    assert page.locator(RANKED).locator(".wk-line2").inner_text() == "Crew TBA"


def test_source_line_and_footer_credit(wk: Callable[..., Page]) -> None:
    page = wk()
    source = page.locator(".wk-source")
    text = source.inner_text()
    assert "CollegeFootballData.com" in text
    assert "506 Sports" in text
    assert "ESPN Press Room" in text
    assert source.locator("a").count() >= 3
    assert source.locator("a[href*=collegefootballdata]").count() >= 1
    assert "CollegeFootballData.com" in page.locator("#site-footer").inner_text()


def test_other_tabs_keep_their_counts(wk: Callable[..., Page]) -> None:
    page = wk("")
    assert page.evaluate("window.__testHooks.nGames") == 20
    page.locator("#tab-weekend").click()
    page.locator("#tab-scatter").click()
    assert page.evaluate("window.__testHooks.nGames") == 20
    # The pending unplayed game (19) stays in the data but is never drawn (v2.1).
    assert page.evaluate("window.__testHooks.getView().visibleCount") == 19


def test_dark_theme_has_no_light_boxes(wk: Callable[..., Page]) -> None:
    page = wk()
    set_theme(page, "dark")
    settle(page)
    offenders = page.evaluate(
        """() => {
          const lum = (r, g, b) => {
            const f = (v) => {
              v /= 255;
              return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
            };
            return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
          };
          const limit = lum(0x4a, 0x45, 0x3e);
          const out = [];
          for (const el of document.querySelectorAll('#weekend-panel *')) {
            if (el.closest('.wk-cell, .wk-item, .wk-rowhead img, svg')) continue;
            const m = /rgba?\\(([^)]+)\\)/.exec(getComputedStyle(el).backgroundColor);
            if (!m) continue;
            const p = m[1].split(',').map(parseFloat);
            if ((p.length > 3 ? p[3] : 1) < 0.5) continue;
            if (lum(p[0], p[1], p[2]) > limit) out.push(el.className + ' ' + m[0]);
          }
          return out;
        }"""
    )
    assert offenders == []
    # A known-crew cell uses a dark-theme family fill, not the light one.
    light_fill = "rgb(255, 255, 255)"
    assert page.locator(LEAD).evaluate("e => getComputedStyle(e).backgroundColor") != light_fill


def test_dark_ring_is_light(wk: Callable[..., Page]) -> None:
    page = wk()
    set_theme(page, "dark")
    page.evaluate(
        "(id) => window.__testHooks.setState({ people: [id] })",
        page.evaluate("window.__testHooks.data.lookups.people[4].id"),
    )
    ring = page.locator(LEAD).evaluate("e => getComputedStyle(e).boxShadow")
    assert "inset" in ring
    assert page.locator(LEAD).evaluate("e => getComputedStyle(e).opacity") == "1"


# ---- Phone (390px) ----


@pytest.fixture
def wk_phone(
    mobile_page: Page,
    serve_weekend: Callable[..., None],
    open_app: Callable[[Page, str], None],
) -> Callable[..., Page]:
    def _open(query: str = "?view=weekend", **kw: Any) -> Page:
        serve_weekend(mobile_page, **kw)
        open_app(mobile_page, query)
        return mobile_page

    return _open


def test_phone_list_groups_by_kickoff(wk_phone: Callable[..., Page]) -> None:
    page = wk_phone()
    assert page.locator("#weekend-panel .wk-grid").count() == 0
    groups = page.locator("#weekend-panel .wk-group")
    assert groups.count() >= 3
    heads = groups.evaluate_all(
        "g => g.map(e => e.querySelector('h3, .wk-group-title')?.textContent)"
    )
    assert heads[0] is not None
    items = page.locator("#weekend-panel .wk-item")
    assert items.count() >= 12
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")


def test_phone_pick_fades_items_and_item_opens_the_panel(wk_phone: Callable[..., Page]) -> None:
    page = wk_phone()
    page.evaluate(
        "(id) => window.__testHooks.setState({ people: [id] })",
        page.evaluate("window.__testHooks.data.lookups.people[4].id"),
    )
    lead = page.locator(f"#weekend-panel {LEAD}")
    assert lead.evaluate("e => getComputedStyle(e).opacity") == "1"
    assert (
        page.locator(f"#weekend-panel {FOX_NOON}").evaluate("e => getComputedStyle(e).opacity")
        == "0.3"
    )
    lead.tap()
    dialog = page.locator("dialog[open]")
    expect(dialog).to_be_visible()
    assert "Not played yet." in dialog.inner_text()


def test_phone_week_stepper_and_tabs_scroll(wk_phone: Callable[..., Page]) -> None:
    page = wk_phone()
    assert page.locator("#chart-tabs button[data-view=weekend]").is_visible()
    page.locator(".wk-step--prev").tap()
    assert _url(page) == "?view=weekend&week=4"
    assert page.locator(".wk-week").inner_text() == "Week 4"


def test_phone_dark_has_no_light_boxes(wk_phone: Callable[..., Page]) -> None:
    page = wk_phone()
    set_theme(page, "dark")
    settle(page)
    body = page.locator("#weekend-panel").evaluate("e => getComputedStyle(e).backgroundColor")
    assert body in ("rgba(0, 0, 0, 0)", "transparent") or body.startswith("rgb(")
    bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
    nums = [int(x) for x in bg.removeprefix("rgb(").removesuffix(")").split(",")[:3]]
    assert max(nums) < 120


# ---- v2.1 polish (18-UI-REVIEW items 4, 7, 8, 10; 18-REVIEW IN-02) ----


def test_legend_chip_row_is_hidden_on_this_weekend(wk: Callable[..., Page]) -> None:
    # 18-UI-REVIEW item 4: the chips are not in the Phase 18 contract and acted as a second,
    # undeclared Networks control; the Networks filter in the bar already fades rows here.
    page = wk()
    assert page.locator("#legend-row").is_hidden()
    page.locator("#tab-scatter").click()
    assert page.locator("#legend-row").is_visible()


def test_matched_games_section_is_hidden_on_this_weekend(wk: Callable[..., Page]) -> None:
    # 18-UI-REVIEW item 7 / 18-REVIEW IN-03: the table lists played games from the greyed
    # Seasons range and its empty state asks for a Game pick, which this tab greys out.
    page = wk()
    assert page.locator("#matched-games").is_hidden()
    page.locator("#tab-scatter").click()
    assert page.locator("#matched-games").is_visible()
    page.locator("#tab-weekend").click()
    assert page.locator("#matched-games").is_hidden()


_AP_KICKOFF = __import__("re").compile(
    r"^(Sun|Mon|Tue|Wed|Thu|Fri|Sat)\. "
    r"(Jan\.|Feb\.|March|April|May|June|July|Aug\.|Sept\.|Oct\.|Nov\.|Dec\.)"
    r" \d{1,2}, (\d{1,2}:\d{2} (am|pm) ET|Time TBA)$"
)


def _open_dialog(page: Page, selector: str) -> Any:
    cell = page.locator(selector)
    cell.focus()
    cell.press("Enter")
    dialog = page.locator("dialog[open]")
    expect(dialog).to_be_visible()
    return dialog


def test_weekend_panel_uses_ap_kickoff_and_the_one_crew_credit(wk: Callable[..., Page]) -> None:
    # 18-UI-REVIEW item 8 / 18-UI-SPEC: a panel opened from a cell writes the kickoff as the
    # view does (`Sat. Oct. 3, 7:30 pm ET`) and credits the crew as NFL does.
    page = wk()
    dialog = _open_dialog(page, LEAD)
    date_line = dialog.locator("#panel-body p").first.inner_text()
    assert date_line == "Sat. Oct. 3, 7:30 pm ET", date_line
    text = dialog.inner_text()
    assert "Crew from 506 Sports ↗" in text
    assert "View 506 Sports listing" not in text
    page.keyboard.press("Escape")
    dialog = _open_dialog(page, FOX_NOON)
    assert _AP_KICKOFF.match(dialog.locator("#panel-body p").first.inner_text())
    page.keyboard.press("Escape")
    dialog = _open_dialog(page, TBD_KICKOFF)
    assert dialog.locator("#panel-body p").first.inner_text() == "Sat. Oct. 3, Time TBA"
    page.keyboard.press("Escape")
    # The same played game opened from the Matched games table keeps the site's long form.
    page.locator("#tab-scatter").click()
    page.evaluate(
        "(id) => window.__testHooks.setState({ people: [id] })",
        page.evaluate("window.__testHooks.data.lookups.people[4].id"),
    )
    page.locator("#matched-games tr.row-link").first.click()
    expect(page.locator("dialog[open]")).to_be_visible()
    long_form = page.locator("dialog[open] #panel-body p").first.inner_text()
    assert not _AP_KICKOFF.match(long_form), long_form


def test_espn_press_room_crew_on_a_scheduled_row_carries_its_booth_tier(
    wk: Callable[..., Page],
) -> None:
    # 18-REVIEW IN-02: a scheduled game whose ESPN Press Room booth is the network's A booth
    # shows the lead star and is kept by a Booth A pick instead of fading.
    def tweak(raw: dict[str, Any]) -> None:
        sched = raw["telecasts_scheduled"]
        sched["network"][0] = 0  # espn, the disney family of the tier-a booth
        sched["crew"][0] = [
            {"person": 4, "role": "pbp", "feed": "main"},
            {"person": 5, "role": "analyst", "feed": "main"},
        ]
        sched["crew_source_url"][0] = "https://espnpressroom.com/us/press-releases/2026/x/"
        sched["crew_source_label"][0] = "ESPN Press Room"

    page = wk(tweak=tweak)
    cell = page.locator('[data-wk-id="g:cfb:scheduled:0"]')
    assert cell.locator(".wk-star").count() == 1
    assert "Rowan" in cell.locator(".wk-line2").inner_text()
    page.evaluate("window.__testHooks.setState({ booth: ['a'] })")
    assert cell.evaluate("e => getComputedStyle(e).opacity") == "1"
    assert page.locator(FOX_NOON).count() == 1
    assert page.locator(RANKED).evaluate("e => getComputedStyle(e).opacity") == "0.3"
    # A crew that matches no cited booth still has no tier.
    page.evaluate("window.__testHooks.setState({ booth: [] })")
    assert page.locator(RANKED).locator(".wk-star").count() == 0


def test_phone_has_no_dead_gap_above_the_day_tabs(wk_phone: Callable[..., Page]) -> None:
    # 18-UI-REVIEW item 10: the concealed chart tools kept a 28px row plus margins between the
    # subtitle and the day tabs on the phone.
    page = wk_phone()
    assert page.locator("#chart-tools").is_hidden()
    subtitle = page.locator("#chart-subtitle").bounding_box()
    tabs = page.locator(".wk-days").bounding_box()
    assert subtitle is not None and tabs is not None
    gap = tabs["y"] - (subtitle["y"] + subtitle["height"])
    assert gap <= 16, gap
    page.locator("#tab-scatter").click()
    assert page.locator("#chart-tools").is_visible()


def test_map_switch_round_trip(wk: Callable[..., Page]) -> None:
    """Phase 24-09: the Map segment mounts the weekend map and sets wview=map; Timeline drops it."""
    page = wk()
    day = page.locator(".wk-day[aria-selected=true]").inner_text()
    page.click('[data-wk-id="wview:map"]')
    page.wait_for_function("location.search.includes('wview=map')")
    assert page.locator(".wk-day[aria-selected=true]").inner_text() == day
    page.click('[data-wk-id="wview:timeline"]')
    page.wait_for_function("!location.search.includes('wview=map')")
    page.wait_for_selector(".wk-row")
    assert page.locator(".js-plotly-plot").count() == 0
