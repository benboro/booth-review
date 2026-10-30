"""Phase 15 plan 09: the NFL Crews tab on the shared table.

One pooled (or per-season) table of every network group's booths over the Seasons range,
Raw/Adjusted with the reason bar, sort, View more, expandable game lists, the row pick into
Booths, the notes and the chart of the first 25 rows. Synthetic data only: the table cases use
the Crews overlay (`serve_nfl_crews`, tests/e2e/nfl_crews_fixture.py); no vault rows.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import nfl_crews_fixture as fx
import pytest
from nfl_crews_fixture import CASE_FILL_IN, CASE_TWO_ANALYSTS, CASE_WINDOW, build_nfl_crews_raw
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

MINUS = "\u2212"
VIEW = "#nfl-view-crews"
TOOLS = "#nfl-chart-tools [data-tools-for='crews']"  # view tools sit in the module header (13-13)
GD = f"{VIEW} .nfl-chart > div"
ROW = f"{VIEW} tr.crews-row"
HEADS_POOLED = [
    "Booth",
    "Rank by season",
    "Network",
    "Games called",
    "Avg margin (pts)",
    "Avg excitement",
    "Avg viewers (rated games)",
]


def _open(page: Page, open_nfl_app: Callable[..., None], query: str = "") -> None:
    open_nfl_app(page, "?sport=nfl&view=crews" + query)
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews') !== null")


def _vm(page: Page) -> dict[str, Any]:
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').drawn === true")
    return page.evaluate("window.__nflTestHooks.getViewModel('crews')")  # type: ignore[no-any-return]


def _set(page: Page, patch: dict[str, Any]) -> None:
    page.evaluate("p => window.__nflTestHooks.setState(p)", patch)


def _state(page: Page) -> dict[str, Any]:
    return page.evaluate("window.__nflTestHooks.getState()")  # type: ignore[no-any-return]


def _emit(page: Page, event: str, k: int) -> None:
    page.evaluate(
        """([ev, k, sel]) => {
          const gd = document.querySelector(sel);
          gd.emit(ev, { points: [{ customdata: k }], event: { clientX: 300, clientY: 200 } });
        }""",
        [event, k, GD],
    )


def _tooltip(page: Page) -> list[str]:
    page.wait_for_function("!document.getElementById('chart-tooltip').hidden")
    return page.evaluate(  # type: ignore[no-any-return]
        "Array.from(document.getElementById('chart-tooltip').children).map(c => c.textContent)"
    )


def _keys(page: Page) -> list[str]:
    return page.eval_on_selector_all(  # type: ignore[no-any-return]
        ROW, "els => els.map(e => e.dataset.rowKey)"
    )


def _reveal(page: Page, row_key: str) -> None:
    """Click View more until the row is in the DOM."""
    while page.locator(f"{ROW}[data-row-key='{row_key}']").count() == 0:
        more = page.locator(f"{VIEW} .nfl-crews-table > .crews-more")
        assert more.count() == 1, f"{row_key} is not in the table"
        more.click()


def _row(page: Page, row_key: str) -> Any:
    _reveal(page, row_key)
    return page.locator(f"{ROW}[data-row-key='{row_key}']")


def _games_col(page: Page) -> list[int]:
    return [
        int(t)
        for t in page.eval_on_selector_all(
            ROW,
            """els => els.map(e => {
              const heads = [...e.closest('table').querySelectorAll('thead th')];
              const at = heads.findIndex(h => h.classList.contains('crews-col-games'));
              return e.children[at].textContent;
            })""",
        )
    ]


def _bucket(cell: dict[str, Any]) -> int:
    if cell["blank"] is not None or cell["mean"] is None:
        return 2
    return 1 if cell["flagged"] else 0


# ------------------------------------------------------------------ shell


def test_no_stepper_picker_or_coverage_line(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    assert page.locator(f"{VIEW} .season-stepper").count() == 0
    assert page.locator(f"{VIEW} .nfl-crews-network").count() == 0
    assert page.locator(f"{VIEW} .filter-trigger").count() == 0
    assert page.locator(f"{VIEW} .nfl-coverage").count() == 0
    assert "Crew listed for" not in page.locator(VIEW).inner_text()
    assert page.locator(f"{TOOLS} .season-stepper").count() == 0
    heads = [
        t.strip() for t in page.locator(f"{VIEW} thead th .crews-sort-label").all_inner_texts()
    ]
    assert "AGOTW" not in heads
    assert heads[0] == "Booth"
    assert heads[-6:] == HEADS_POOLED[1:]


def test_default_opens_per_season_newest_first(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    serve_nfl_crews(nfl_guarded_page)
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    assert vm["perSeason"] is True
    assert vm["sort"] == {"key": "season", "dir": "desc"}
    assert vm["columns"][:2] == ["Booth", "Season"]
    played = [r for r in vm["rows"] if r["gamesCount"]]
    seasons = [int(r["season"]) for r in played]
    assert seasons == sorted(seasons, reverse=True)
    # Zero-game (lineup-only) rows sink below every row with games, never leading.
    assert vm["rows"][: len(played)] == played and len(played) < len(vm["rows"])
    assert vm["totalRows"] >= fx.EXPECT_SEASON_ROWS
    assert vm["shown"] == 25
    cells = page.eval_on_selector_all(ROW, "els => els.map(e => e.children[2].textContent)")
    assert cells == [str(r["season"]) for r in vm["rows"][:25]]


def test_network_column_shows_the_group_with_a_title(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app, "&perseason=0")
    vm = _vm(page)
    first = page.locator(f"{ROW} td.crews-network").first
    assert first.get_attribute("title") == vm["rows"][0]["network"]["name"]
    assert first.locator(".net-mark").count() == 1


# ------------------------------------------------------------------ paging and sort


def test_view_more_pages_by_25(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    serve_nfl_crews(nfl_guarded_page)
    page = nfl_guarded_page
    _open(page, open_nfl_app, "&perseason=0")
    vm = _vm(page)
    assert vm["perSeason"] is False
    assert vm["totalRows"] == fx.EXPECT_POOLED_ROWS
    assert vm["shown"] == 25
    left = vm["totalRows"] - 25
    assert left > 0
    more = page.locator(f"{VIEW} .nfl-crews-table > .crews-more")
    step = min(25, left)
    assert more.inner_text() == f"View {step} more ({left} left)"
    assert (
        page.locator(f"{VIEW} .crews-count").inner_text()
        == f"Showing 25 of {vm['totalRows']} rows."
    )
    more.click()
    page.wait_for_function(f"document.querySelectorAll('{ROW}').length === {25 + step}")
    keys = _keys(page)
    assert page.evaluate("document.activeElement.dataset.rowKey") == keys[25]
    assert "expanded" not in page.url
    # A sort change puts the table back to 25 rows.
    page.locator(f"{VIEW} button[data-sort-key='exc']").click()
    page.wait_for_function(f"document.querySelectorAll('{ROW}').length === 25")


def test_one_season_range_disables_per_season_and_keeps_url_clean(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    seasons = _state(page)["seasons"]
    box = page.locator(f"{TOOLS} input.crews-perseason")
    assert box.is_enabled()
    assert box.is_checked()
    _set(page, {"seasons": [seasons[1], seasons[1]]})
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').perSeason === false")
    assert box.is_disabled()
    assert box.get_attribute("title") == "Needs two or more seasons in range"
    assert "perseason" not in page.url
    assert "Season" not in [
        t.strip() for t in page.locator(f"{VIEW} thead th .crews-sort-label").all_inner_texts()
    ]
    box_label = page.locator(f"{TOOLS} .crews-perseason-label")
    assert box_label.get_attribute("title") == "Needs two or more seasons in range"


def test_per_season_toggle_writes_url_and_resets_paging(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    serve_nfl_crews(nfl_guarded_page)
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    page.locator(f"{VIEW} .nfl-crews-table > .crews-more").click()
    page.wait_for_function(f"document.querySelectorAll('{ROW}').length > 25")
    page.locator(f"{TOOLS} input.crews-perseason").uncheck()
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').perSeason === false")
    assert "perseason=0" in page.url
    page.wait_for_function(f"document.querySelectorAll('{ROW}').length === 25")


def test_default_sort_is_games_when_pooled_and_heads_carry_aria_sort(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    serve_nfl_crews(nfl_guarded_page)
    page = nfl_guarded_page
    _open(page, open_nfl_app, "&perseason=0")
    vm = _vm(page)
    assert vm["sort"] == {"key": "games", "dir": "desc"}
    games = _games_col(page)
    assert games == sorted(games, reverse=True)
    heads = page.locator(f"{VIEW} thead th[aria-sort]")
    assert heads.count() == len(HEADS_POOLED)
    states = heads.evaluate_all("els => els.map(e => e.getAttribute('aria-sort'))")
    assert states.count("descending") == 1
    assert states.count("none") == len(HEADS_POOLED) - 1
    # Every head is a sortable button; a click writes the sort and flips it on the next click.
    for key in ("booth", "rank", "network", "games", "margin", "exc", "viewers"):
        assert page.locator(f"{VIEW} thead button[data-sort-key='{key}']").count() == 1


def test_metric_sorts_bucket_both_directions(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    serve_nfl_crews(nfl_guarded_page)
    page = nfl_guarded_page
    _open(page, open_nfl_app, "&perseason=0")
    _vm(page)
    for key in ("viewers", "exc", "margin"):
        head = page.locator(f"{VIEW} button[data-sort-key='{key}']")
        buckets: list[list[int]] = []
        for _ in range(2):
            head.click()
            page.wait_for_function(
                f"window.__nflTestHooks.getViewModel('crews').sort.key === '{key}'"
            )
            vm = _vm(page)
            buckets.append([_bucket(r[key]) for r in vm["rows"]])
            assert buckets[-1] == sorted(buckets[-1]), (key, vm["sort"])
        assert vm["sort"]["dir"] == "asc"
        assert max(buckets[0]) >= 1  # the overlay has flagged rows, so the buckets are exercised
        head.click()  # back to the default sort
        page.wait_for_function("window.__nflTestHooks.getViewModel('crews').sort.key === 'games'")


def test_csort_season_encode_and_decode_agree_nfl(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    """15-13 F10: csort=season is in the URL only with a Season column."""
    serve_nfl_crews(nfl_guarded_page)
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    page.locator(f"{VIEW} button[data-sort-key='season']").click()
    page.wait_for_function("window.__nflTestHooks.getState().csort?.key === 'season'")
    with_season = page.url
    assert "csort=season" in with_season
    open_nfl_app(page, "?" + page.url.split("?", 1)[1])
    _vm(page)
    assert _state(page)["csort"]["key"] == "season"
    assert page.url == with_season
    page.locator(f"{TOOLS} input.crews-perseason").uncheck()
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').perSeason === false")
    assert "csort" not in page.url
    pooled = page.url
    open_nfl_app(page, "?" + page.url.split("?", 1)[1])
    _vm(page)
    assert _state(page)["csort"] is None
    assert page.url == pooled


def test_csort_games_survives_widening_nfl(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    """P14-FU-2 NFL twin: a Games called click on a one-season range keeps csort=games."""
    serve_nfl_crews(nfl_guarded_page)
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    lo, hi = _state(page)["seasons"]
    _set(page, {"seasons": [hi, hi]})
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').perSeason === false")
    page.locator(f"{VIEW} button[data-sort-key='viewers']").click()
    page.wait_for_function("window.__nflTestHooks.getState().csort !== null")
    page.locator(f"{VIEW} button[data-sort-key='games']").click()
    page.wait_for_function("window.__nflTestHooks.getState().csort?.key === 'games'")
    assert "csort=games" in page.url
    _set(page, {"seasons": [lo, hi]})
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').perSeason === true")
    assert _state(page)["csort"] == {"key": "games", "dir": "desc"}
    assert "csort=games" in page.url
    games = _games_col(page)
    assert games == sorted(games, reverse=True)


# ------------------------------------------------------------------ cells


def test_flagged_and_era_cells(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    serve_nfl_crews(nfl_guarded_page)
    page = nfl_guarded_page
    _open(page, open_nfl_app, "&perseason=0")
    _vm(page)
    tag = page.locator(f"{ROW} td.is-low-n .crews-tag").first
    assert tag.inner_text() == "n < 8"
    assert tag.get_attribute("title") == "Fewer than 8 games have this figure"
    era = _row(page, "cbs:synth-pbp-era.synth-an-era")
    cell = era.locator("td").nth(len(HEADS_POOLED) - 1 + 1)  # chevron + 7 columns, viewers last
    assert cell.inner_text() == "see Per season"
    assert cell.get_attribute("title") == "Games span more than one Nielsen measurement era"


def test_adjusted_cells_print_signed_residual_with_se(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    serve_nfl_crews(nfl_guarded_page)
    page = nfl_guarded_page
    _open(page, open_nfl_app, "&perseason=0&adj=1")
    vm = _vm(page)
    assert vm["mode"] == "adjusted"
    pressed = page.locator(f"{TOOLS} [aria-label='Raw or adjusted'] [aria-pressed='true']")
    assert pressed.inner_text() == "Adjusted"
    texts = page.eval_on_selector_all(ROW, "els => els.map(e => e.children[5].textContent)")
    shown = [t for t in texts if t]
    assert shown
    assert all(
        re.fullmatch("[+" + MINUS + "]?" + r"\d+\.\d( ± \d+\.\d)?( n < 8)?", t) for t in shown
    ), shown
    assert any(t.startswith(MINUS) for t in shown) or any(t.startswith("+") for t in shown)


# ------------------------------------------------------------------ game lists


def test_game_list_view_more_announces_on_the_status_seat(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    """15-13 N1: the game-list View more writes to the NFL table's polite status seat."""
    serve_nfl_crews(nfl_guarded_page)
    page = nfl_guarded_page
    _open(page, open_nfl_app, "&perseason=0")
    _vm(page)
    two = f"fox:{CASE_TWO_ANALYSTS['pbp']}.synth-an-two-a"  # 18 games
    _row(page, two).locator(".crews-chevron").click()
    sub = page.locator(f"{VIEW} tr.crews-expanded[data-sub-for='{two}']")
    seat = page.locator(f"{VIEW} .crews-status")
    sub.locator(".crews-games-more").click()
    assert seat.text_content() == "8 more games shown, 0 left."


def test_game_list_ten_newest_first_with_tags(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    serve_nfl_crews(nfl_guarded_page)
    page = nfl_guarded_page
    _open(page, open_nfl_app, "&perseason=0")
    _vm(page)
    two = f"fox:{CASE_TWO_ANALYSTS['pbp']}.synth-an-two-a"  # 18 games over 2024-2025
    row = _row(page, two)
    row.locator(".crews-chevron").click()
    sub = page.locator(f"{VIEW} tr.crews-expanded[data-sub-for='{two}']")
    games = sub.locator("tr.crews-game")
    assert games.count() == 10
    heads = [h.strip() for h in sub.locator("table.crews-games thead th").all_inner_texts()]
    assert heads == ["Date", "Matchup", "Network", "Excitement", "Viewers"]
    excitement = [c.strip() for c in sub.locator("td.crews-game-exc").all_inner_texts()]
    assert len(excitement) == 10
    assert all(re.fullmatch(r"\d+\.\d", c) for c in excitement), excitement
    dates = sub.locator("td.crews-game-date").all_inner_texts()
    assert dates == sorted(dates, reverse=True)
    more = sub.locator(".crews-games-more")
    assert more.inner_text() == "View 8 more (8 left)"
    more.click()
    assert sub.locator("tr.crews-game").count() == 18
    assert sub.locator(".crews-games-more").count() == 0
    dates = sub.locator("td.crews-game-date").all_inner_texts()
    assert dates == sorted(dates, reverse=True)

    fill = f"nbc:{CASE_FILL_IN['pbp']}.{CASE_FILL_IN['analyst']}"
    _row(page, fill).locator(".crews-chevron").click()
    fsub = page.locator(f"{VIEW} tr.crews-expanded[data-sub-for='{fill}']")
    assert fsub.locator(".crews-tag", has_text="fill-in").count() == CASE_FILL_IN["fill_in_games"]
    assert fsub.locator(".crews-tag", has_text="window").count() == 0

    win = f"nbc:{CASE_WINDOW['pbp']}.{CASE_WINDOW['analyst']}"
    _row(page, win).locator(".crews-chevron").click()
    wsub = page.locator(f"{VIEW} tr.crews-expanded[data-sub-for='{win}']")
    assert wsub.locator(".crews-tag", has_text="window").count() == CASE_WINDOW["window_games"]
    tag = wsub.locator(".crews-tag", has_text="window").first
    assert tag.get_attribute("title") == "One figure covers every game in that Sunday window"


def test_enter_on_a_game_opens_the_panel_and_focus_returns(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    serve_nfl_crews(nfl_guarded_page)
    page = nfl_guarded_page
    _open(page, open_nfl_app, "&perseason=0")
    _vm(page)
    keys = _keys(page)
    _row(page, keys[0]).locator(".crews-chevron").click()
    game = page.locator(f"{VIEW} tr.crews-game").first
    game.focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("dialog[open]")
    page.keyboard.press("Escape")
    page.wait_for_selector("dialog[open]", state="detached")
    assert page.evaluate("document.activeElement.classList.contains('crews-game')")


# ------------------------------------------------------------------ row pick


def test_row_pick_narrows_to_the_booth_key_and_keeps_focus(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    serve_nfl_crews(nfl_guarded_page)
    page = nfl_guarded_page
    _open(page, open_nfl_app, "&perseason=0")
    vm = _vm(page)
    total = vm["totalRows"]
    key_a = f"fox:{CASE_TWO_ANALYSTS['pbp']}.synth-an-two-a"
    key_b = f"fox:{CASE_TWO_ANALYSTS['pbp']}.synth-an-two-b"
    catalog = str(CASE_TWO_ANALYSTS["catalog_key"])
    row = _row(page, key_a)
    row.focus()
    page.keyboard.press("Enter")
    page.wait_for_function(
        f"JSON.stringify(window.__nflTestHooks.getState().booths) === '[\"{catalog}\"]'"
    )
    vm = _vm(page)
    assert sorted(r["rowKey"] for r in vm["rows"]) == sorted([key_a, key_b])
    assert vm["totalRows"] == CASE_TWO_ANALYSTS["pooled_rows"]
    assert all(r["picked"] for r in vm["rows"])
    pressed = page.eval_on_selector_all(ROW, "els => els.map(e => e.getAttribute('aria-pressed'))")
    assert pressed == ["true", "true"]
    assert page.evaluate("document.activeElement.dataset.rowKey") == key_a
    picked_class = page.eval_on_selector_all(
        ROW, "els => els.map(e => e.classList.contains('is-picked'))"
    )
    assert picked_class == [True, True]
    # Pressing again restores every row.
    page.keyboard.press("Enter")
    page.wait_for_function("window.__nflTestHooks.getState().booths.length === 0")
    assert _vm(page)["totalRows"] == total
    pressed = page.eval_on_selector_all(ROW, "els => els.map(e => e.getAttribute('aria-pressed'))")
    assert set(pressed) == {"false"}


def test_row_click_picks_and_a_filter_bar_booths_pick_marks_the_same_rows(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    serve_nfl_crews(nfl_guarded_page)
    page = nfl_guarded_page
    _open(page, open_nfl_app, "&perseason=0")
    _vm(page)
    key_a = f"fox:{CASE_TWO_ANALYSTS['pbp']}.synth-an-two-a"
    _row(page, key_a).locator("td.crews-name").click()
    page.wait_for_function("window.__nflTestHooks.getState().booths.length === 1")
    vm = _vm(page)
    assert len(vm["rows"]) == 2
    # Booths no longer exactly that key: no row shows as picked.
    _set(page, {"booths": []})
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').rows.length > 2")
    assert not any(r["picked"] for r in _vm(page)["rows"])


# ------------------------------------------------------------------ Raw / Adjusted


def test_team_pick_forces_raw_with_reason_and_keeps_adj(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app, "&adj=1")
    vm = _vm(page)
    assert vm["mode"] == "adjusted"
    bar = page.locator("#nfl-reason-crews")
    assert bar.is_hidden()
    team = nfl_fixture_raw["lookups"]["franchises"][0]["id"]
    _set(page, {"teams": [team]})
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').mode === 'raw'")
    reason = page.evaluate("import('./sports/nfl/mode.js').then((m) => m.REASONS.crewsTeam)")
    assert bar.inner_text() == reason
    assert _vm(page)["reason"] == reason
    adjusted = page.locator(f"{TOOLS} [aria-label='Raw or adjusted'] button", has_text="Adjusted")
    assert adjusted.get_attribute("aria-disabled") == "true"
    assert adjusted.get_attribute("aria-describedby") == "nfl-reason-crews"
    assert "adj=1" in page.url
    adjusted.click(force=True)
    assert _vm(page)["mode"] == "raw"
    assert "adj=1" in page.url
    _set(page, {"teams": []})
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').mode === 'adjusted'")
    assert bar.is_hidden()
    assert adjusted.get_attribute("aria-disabled") is None


# ------------------------------------------------------------------ notes, chart


def test_rt17_rt19_notes_and_heads(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    serve_nfl_crews(nfl_guarded_page)
    page = nfl_guarded_page
    _open(page, open_nfl_app, "&perseason=0")
    vm = _vm(page)
    # Raw: the spread word appears nowhere in the view.
    assert "spread" not in page.locator(VIEW).inner_text().lower()
    notes = page.locator(f"{VIEW} .nfl-crews-notes")
    text = notes.inner_text()
    assert (
        "NFL excitement is GEI-style, built from win probability. It is not CFBD's "
        "excitementIndex; see methodology." in text
    )
    assert notes.locator("a").get_attribute("href") == "methodology.html#nfl-gei-style-excitement"
    assert "Avg viewers (rated games) mostly reflects which games a booth was assigned." in text
    assert "window-level" in text
    assert (
        page.locator(f"{VIEW} .crews-count").inner_text()
        == f"Showing {vm['shown']} of {vm['totalRows']} rows."
    )
    assert "Adjusted:" not in text
    assert "GEI" not in " ".join(
        page.locator(f"{VIEW} thead th, {VIEW} .segmented, {TOOLS}").all_inner_texts()
    )
    # The published-lineup note appears only when a shown row is published.
    published_shown = any(r["published"] for r in vm["rows"][: vm["shown"]])
    assert (page.locator(f"{VIEW} .nfl-published-note").count() == 1) == published_shown

    # Adjusted: the caption appears; the word stays out of the table, controls and heads.
    page.locator(f"{TOOLS} [aria-label='Raw or adjusted'] button", has_text="Adjusted").click()
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').mode === 'adjusted'")
    caption = notes.inner_text()
    assert "1.4 pts closer" in caption
    assert "plus or minus 1.96 standard errors" in caption
    outside = page.locator(f"{VIEW} .crews-table, {TOOLS}").all_inner_texts()
    assert all("spread" not in t.lower() for t in outside)
    title = lambda: page.evaluate(f"document.querySelector('{GD}').layout.xaxis.title.text")  # noqa: E731
    assert title() == "Final margin vs. what the spread predicted (points)"
    measure = page.locator(f"{VIEW} .nfl-crews-measure")
    measure.get_by_role("button", name="Excitement", exact=True).click()
    page.wait_for_function(
        "window.__nflTestHooks.getViewModel('crews').chart.metric === 'excitement'"
    )
    assert title() == "Excitement vs. what the spread predicted"
    vm = _vm(page)
    k = next(i for i, p in enumerate(vm["chart"]["points"]) if p["x"] is not None)
    _emit(page, "plotly_hover", k)
    lines = _tooltip(page)
    assert "than the spread predicted" in " ".join(lines) or "as the spread predicted" in " ".join(
        lines
    )
    assert any(line.startswith("±1.96 standard errors:") for line in lines)
    assert "spread:" not in " ".join(lines).lower()


def test_raw_hover_strings_and_axis_titles(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    assert vm["chart"]["metric"] == "margin"
    assert vm["chart"]["adjusted"] is False
    title = lambda: page.evaluate(f"document.querySelector('{GD}').layout.xaxis.title.text")  # noqa: E731
    assert title() == "Avg final margin (points)"
    k = next(i for i, p in enumerate(vm["chart"]["points"]) if p["x"] is not None)
    _emit(page, "plotly_hover", k)
    lines = _tooltip(page)
    assert any(line.startswith("Avg margin:") and line.endswith("pts") for line in lines)
    assert "spread" not in " ".join(lines).lower()
    measure = page.locator(f"{VIEW} .nfl-crews-measure")
    assert measure.get_attribute("aria-label") == "Chart measure"
    measure.get_by_role("button", name="Excitement", exact=True).click()
    page.wait_for_function(
        "window.__nflTestHooks.getViewModel('crews').chart.metric === 'excitement'"
    )
    assert title() == "Excitement"
    assert "GEI" not in title()
    vm = _vm(page)
    k = next(i for i, p in enumerate(vm["chart"]["points"]) if p["x"] is not None)
    _emit(page, "plotly_hover", k)
    assert any(
        line.startswith("Excitement:") and line.endswith("(GEI-style, not CFBD's index)")
        for line in _tooltip(page)
    )
    measure.get_by_role("button", name="Avg viewers").click()
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').chart.metric === 'viewers'")
    assert title() == "Avg viewers"
    vm = _vm(page)
    k = next(i for i, p in enumerate(vm["chart"]["points"]) if p["x"] is not None)
    _emit(page, "plotly_hover", k)
    assert any(" rated game" in line for line in _tooltip(page))


def test_chart_plots_first_25_rows_and_shrinks_to_fewer(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    serve_nfl_crews(nfl_guarded_page)
    page = nfl_guarded_page
    _open(page, open_nfl_app, "&perseason=0")
    vm = _vm(page)
    points = vm["chart"]["points"]
    assert len(points) == 25
    assert [p["rowKey"] for p in points] == [r["rowKey"] for r in vm["rows"][:25]]
    height = page.evaluate(f"document.querySelector('{GD}').layout.height")
    # Growing the table does not change what the chart plots.
    page.locator(f"{VIEW} .nfl-crews-table > .crews-more").click()
    page.wait_for_function(f"document.querySelectorAll('{ROW}').length > 25")
    assert len(_vm(page)["chart"]["points"]) == 25
    # Marks have no click action.
    assert page.evaluate(
        f"!(document.querySelector('{GD}')._ev && document.querySelector('{GD}')._ev._events"
        f" && document.querySelector('{GD}')._ev._events.plotly_click)"
    )
    # Fewer rows shrink the figure (user override of the UI-SPEC Q2 reserve, 2026-10-24):
    # 24px per row, and the chart container follows it.
    catalog = str(CASE_TWO_ANALYSTS["catalog_key"])
    _set(page, {"booths": [catalog]})
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').rows.length === 2")
    assert len(_vm(page)["chart"]["points"]) == 2
    small = page.evaluate(f"document.querySelector('{GD}').layout.height")
    assert height - small == (25 - 2) * 24
    box = page.evaluate(
        f"""() => {{
          const gd = document.querySelector('{GD}');
          return [gd.getBoundingClientRect().height,
                  gd.parentElement.getBoundingClientRect().height];
        }}"""
    )
    assert abs(box[0] - small) <= 1 and box[1] - box[0] <= 4


_YTICKS_JS = """(sel) => {
  const gd = document.querySelector(sel);
  const left = gd.getBoundingClientRect().left;
  return {
    text: gd.layout.yaxis.ticktext,
    clipped: [...gd.querySelectorAll('.yaxislayer-above .ytick text')]
      .filter((t) => t.getBoundingClientRect().left < left - 0.5).length,
    ticks: gd.querySelectorAll('.yaxislayer-above .ytick text').length,
  };
}"""


def test_desktop_chart_labels_show_the_full_name_and_season(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    """User fix 2026-10-24: no 30-character clip; the margin is sized from the text."""
    serve_nfl_crews(nfl_guarded_page)
    page = nfl_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, open_nfl_app)
    vm = _vm(page)
    got = page.evaluate(_YTICKS_JS, GD)
    want = [f"{r['names']}, {r['season']}" for r in vm["rows"][:25]]
    assert got["text"] == want
    assert any(len(s) > 30 for s in want)  # the old 30-character clip would have cut these
    assert not any("\u2026" in s for s in got["text"])
    assert got["ticks"] == len(want) and got["clipped"] == 0
    _set(page, {"perseason": False})
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').perSeason === false")
    vm = _vm(page)
    got = page.evaluate(_YTICKS_JS, GD)
    assert got["text"] == [r["names"] for r in vm["rows"][:25]]
    assert got["clipped"] == 0


def test_phone_chart_labels_are_last_names_with_the_season(
    nfl_mobile_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    """Phone labels read "Last / Last, YYYY"; pooled rows drop the season; a booth with no
    analyst shows the play-by-play last name alone."""
    serve_nfl_crews(nfl_mobile_page)
    page = nfl_mobile_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    got = page.evaluate(_YTICKS_JS, GD)
    assert got["clipped"] == 0 and got["ticks"] == len(got["text"])
    assert all(re.fullmatch(r"\S+ / \S+, \d{4}|\S+, \d{4}", s) for s in got["text"]), got["text"]
    seasons = [r["season"] for r in vm["rows"][:25]]
    assert [s.rsplit(", ", 1)[1] for s in got["text"]] == [str(s) for s in seasons]
    _set(page, {"perseason": False})
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').perSeason === false")
    pooled = page.evaluate(_YTICKS_JS, GD)
    assert pooled["clipped"] == 0
    assert all(re.fullmatch(r"\S+( / \S+)?", s) for s in pooled["text"]), pooled["text"]


def test_compact_label_last_names(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    got = page.evaluate(
        """async () => {
          const C = await import('./sports/nfl/views/crews-chart.js');
          const p = (name) => ({ name });
          return [
            C.compactLabel({ pbp: p('Jim Nantz'), analyst: p('Tony Romo'), season: 2025 }),
            C.compactLabel({ pbp: p('Jim Nantz'), analyst: p('Tony Romo'), season: null }),
            C.compactLabel({ pbp: p('Jim Nantz'), analyst: null, season: 2024 }),
            C.compactLabel({ pbp: p('Joe Buck'), analyst: p('Greg Olsen Jr.'), season: 2024 }),
            C.compactLabel({ pbp: null, analyst: p('Tony Romo'), season: null }),
            C.compactLabel({ pbp: p('Cher'), analyst: p('Tony Romo'), season: 2023 }),
            C.compactLabel({ pbp: null, analyst: null, names: '', season: null }),
          ];
        }"""
    )
    assert got == [
        "Nantz / Romo, 2025",
        "Nantz / Romo",
        "Nantz, 2024",
        "Buck / Olsen, 2024",
        "Romo",
        "Cher / Romo, 2023",
        "",
    ]


def test_hovering_a_chart_mark_lights_its_table_row(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app, "&perseason=0")
    vm = _vm(page)
    k = next(i for i, p in enumerate(vm["chart"]["points"]) if p["x"] is not None)
    _emit(page, "plotly_hover", k)
    key = vm["chart"]["points"][k]["rowKey"]
    assert page.locator(f"{ROW}.is-hover").get_attribute("data-row-key") == key
    _emit(page, "plotly_unhover", k)
    assert page.locator(f"{ROW}.is-hover").count() == 0


_HOVER_STATE_JS = """([sel, k]) => {
  const gd = document.querySelector(sel);
  const size = gd._fullLayout._size;
  const probe = document.createElement('i');
  const rgb = (v) => { probe.style.color = `var(${v})`; document.body.append(probe);
    const c = getComputedStyle(probe).color; probe.remove(); return c; };
  const band = [...gd.querySelectorAll('.layer-below .shapelayer path')]
    .map((p) => p.getBoundingClientRect())
    .filter((r) => r.width > 0 && r.height > 0);
  const ticks = [...gd.querySelectorAll('.yaxislayer-above .ytick text')];
  return {
    shapes: (gd.layout.shapes || []).filter((s) => s.name === 'row-band').length,
    bandWidths: band.map((r) => Math.round(r.width)),
    plotWidth: Math.round(size.w),
    weights: ticks.map((t) => getComputedStyle(t).fontWeight),
    fill: ticks[k] ? getComputedStyle(ticks[k]).fill : null,
    ink: rgb('--ink'),
  };
}"""


def test_hovering_a_chart_mark_lights_its_chart_row_and_table_row(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    """Hover bands the mark's row across the plot (--surface), bolds its label in --ink, and
    lights the table row with the table's own hover style; none of it picks a booth."""
    page = nfl_guarded_page
    _open(page, open_nfl_app, "&perseason=0")
    vm = _vm(page)
    k = next(i for i, p in enumerate(vm["chart"]["points"]) if p["x"] is not None)
    key = vm["chart"]["points"][k]["rowKey"]
    state_before, url_before = _state(page), page.url
    _emit(page, "plotly_hover", k)
    page.wait_for_function(
        "(sel) => (document.querySelector(sel).layout.shapes || [])"
        ".some((s) => s.name === 'row-band')",
        arg=GD,
    )
    page.wait_for_function(
        "([sel, k]) => [...document.querySelectorAll(sel + ' .yaxislayer-above .ytick text')]"
        "[k].style.fontWeight === '600'",
        arg=[GD, k],
    )
    got = page.evaluate(_HOVER_STATE_JS, [GD, k])
    assert got["shapes"] == 1
    assert got["bandWidths"] and abs(max(got["bandWidths"]) - got["plotWidth"]) <= 2, got
    assert [w for i, w in enumerate(got["weights"]) if w in ("600", "bold")] == [got["weights"][k]]
    assert got["weights"][k] in ("600", "bold") and got["fill"] == got["ink"], got
    row = page.locator(f"{ROW}[data-row-key='{key}']")
    assert "is-hover" in (row.get_attribute("class") or "")
    surface = page.evaluate(
        """() => { const i = document.createElement('i'); i.style.color = 'var(--surface)';
          document.body.append(i); const c = getComputedStyle(i).color; i.remove(); return c; }"""
    )
    assert row.evaluate("e => getComputedStyle(e).backgroundColor") == surface
    assert _state(page)["booths"] == state_before["booths"] and page.url == url_before
    _emit(page, "plotly_unhover", k)
    page.wait_for_function(
        "(sel) => !(document.querySelector(sel).layout.shapes || [])"
        ".some((s) => s.name === 'row-band')",
        arg=GD,
    )
    page.wait_for_function(
        "(sel) => [...document.querySelectorAll(sel + ' .yaxislayer-above .ytick text')]"
        ".every((t) => t.style.fontWeight === '')",
        arg=GD,
    )
    assert page.locator(f"{ROW}.is-hover").count() == 0
    assert _state(page)["booths"] == state_before["booths"] and page.url == url_before


_DRAW_JS = """async ([mobile, seasons]) => {
  const C = await import('./sports/nfl/views/crews-chart.js');
  const host = document.createElement('div');
  host.style.width = '900px';
  document.body.append(host);
  const gd = document.createElement('div');
  host.append(gd);
  const p = (name) => ({ name });
  const rows = seasons.map((season, i) => ({
    rowKey: `r${i}`, names: `Pbp${i} Name and Ana${i} Last`, season,
    pbp: p(`Pbp${i} Name`), analyst: p(`Ana${i} Last`), gamesCount: 3,
    margin: { mean: 3 + i, n: 3, flagged: false },
    adjusted: { margin: { resid: 1, se: 1, n: 3, flagged: false } },
  }));
  const items = C.chartModel(rows, { metric: 'margin', adjusted: false });
  C.drawCrewsChart({ gd, chart: host }, items,
    { metric: 'margin', adjusted: false, env: { mobile, hoverNone: false }, th: 'light' });
  await new Promise((r) => setTimeout(r, 300));
  const out = { text: gd.layout.yaxis.ticktext, title: gd.layout.xaxis.title.text };
  host.remove();
  return out;
}"""


@pytest.mark.parametrize("mobile", [False, True])
def test_chart_labels_drop_a_shared_season_into_the_axis_title(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], mobile: bool
) -> None:
    """Every plotted row from one season: names only on the labels, the season once in the
    axis title. Mixed seasons keep a season on each label and the title unchanged."""
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    shared = page.evaluate(_DRAW_JS, [mobile, [2025, 2025, 2025]])
    if mobile:
        assert shared["text"] == ["Name / Last"] * 3
    else:
        assert shared["text"] == [f"Pbp{i} Name and Ana{i} Last" for i in range(3)]
    assert shared["title"].endswith(", 2025"), shared
    mixed = page.evaluate(_DRAW_JS, [mobile, [2025, 2024, 2025]])
    assert all(t.endswith(("2024", "2025")) and ", " in t for t in mixed["text"]), mixed
    assert "\u00b7" not in mixed["title"], mixed
    pooled = page.evaluate(_DRAW_JS, [mobile, [None, None]])
    assert not any(t.endswith(("2024", "2025")) for t in pooled["text"]), pooled
    assert "\u00b7" not in pooled["title"], pooled


def test_chart_container_hugs_the_plot(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    """No blank band under the chart: the container follows the fixed figure height."""
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    got = page.evaluate(
        """(sel) => {
          const gd = document.querySelector(sel);
          const box = gd.parentElement.getBoundingClientRect();
          return box.bottom - gd.getBoundingClientRect().bottom;
        }""",
        GD,
    )
    assert got <= 4


def test_empty_state_has_standard_copy_and_reserved_height(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    serve_nfl_crews(nfl_guarded_page)
    page = nfl_guarded_page
    _open(page, open_nfl_app, "&perseason=0")
    _vm(page)
    # A Booths key with no row in the Seasons range leaves no rows.
    seasons = _state(page)["seasons"]
    _set(page, {"seasons": [seasons[1], seasons[1]], "booths": ["fox:synth-pbp-move"]})
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').totalRows === 0")
    note = page.locator(f"{VIEW} .season-empty-note")
    assert note.get_attribute("role") == "status"
    assert note.locator(".season-empty-title").inner_text() == "No games match these filters"
    assert (
        note.locator(".season-empty-hint").inner_text()
        == "Clear all filters, or widen the Seasons range."
    )
    assert note.bounding_box()["height"] >= 320  # type: ignore[index]
    assert page.locator(f"{VIEW} .nfl-chart").is_hidden()


# ------------------------------------------------------------------ phone and desktop


_CELL_JS = """(sel) => { const el = document.querySelector(sel); const cs = getComputedStyle(el);
  return { position: cs.position, bg: cs.backgroundColor }; }"""


def test_desktop_booth_column_has_no_pin(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    got = page.evaluate(_CELL_JS, f"{ROW} td.crews-name")
    assert got["position"] != "sticky"


def test_phone_booth_column_is_pinned_with_a_fill_and_heads_fit(
    nfl_mobile_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_mobile_page
    _open(page, open_nfl_app)
    _vm(page)
    got = page.evaluate(_CELL_JS, f"{ROW} td.crews-name")
    assert got["position"] == "sticky"
    assert got["bg"] != "rgba(0, 0, 0, 0)"
    widths = page.eval_on_selector_all(
        f"{VIEW} thead th", "els => els.map(e => Math.round(e.getBoundingClientRect().width))"
    )
    assert widths[0] == 44  # chevron
    assert widths[1] == 148  # Booth


def test_no_console_errors(page: Page, nfl_site_url: str) -> None:
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{nfl_site_url}/index.html?sport=nfl&view=crews")
    page.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.ready === true")
    _vm(page)
    page.get_by_role("button", name="Adjusted").click()
    page.locator(f"{VIEW} button[data-sort-key='games']").click()
    assert errors == []


def test_low_n_tag_and_flag_read_the_shipped_threshold(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    nfl_fixture_raw: dict[str, Any],
) -> None:
    # v2.1 (Phase 15 review F6): a changed constants.low_n_threshold moves the tags.
    raw = build_nfl_crews_raw(nfl_fixture_raw)
    raw["constants"]["low_n_threshold"] = 3
    page = nfl_guarded_page
    page.route("**/nfl-data.json*", lambda route: route.fulfill(json=raw))
    _open(page, open_nfl_app, "&perseason=0")
    vm = _vm(page)
    tags = page.locator(f"{ROW} td.is-low-n .crews-tag")
    assert tags.count() >= 1
    assert set(tags.all_inner_texts()) == {"n < 3"}
    assert tags.first.get_attribute("title") == "Fewer than 3 games have this figure"
    for r in vm["rows"]:
        for key in ("margin", "exc", "viewers"):
            cell = r[key]
            if cell["n"] and cell["mean"] is not None:
                assert cell["flagged"] == (cell["n"] < 3), (r["rowKey"], key, cell)
