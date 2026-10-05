"""Game picker browser tests (SITE-44, SITE-45, SITE-18; 04.9 D-01..D-06, D-14, D-17, D-19).

The ninth toolbar button and its popover: the sectioned, counted radio list, facet
hiding, search, the keyboard model, the desktop-only rivalry tooltip, resets, the phone
sheet, and the empty-table copy -- all against the synthetic contract fixture (games:
CFP Semifinal, Harbor Bowl formerly Bayside Bowl, Summit Bowl, Lakeshore Rivalry between
Northfield and Lakeview, The Bridge Game between Stonebridge and Maplecrest).
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

DEFAULT_ROWS = [
    "CFP Semifinal (1)",
    "Harbor Bowl (1)",
    "Summit Bowl (1)",
    "The Bridge Game (1)",
    "Lakeshore Rivalry (2)",
]

_ROWS_JS = """
() => [...document.querySelectorAll('#game-options [data-game]')]
  .filter((b) => b.offsetParent !== null)
  .map((b) => b.querySelector('.game-label').textContent + ' ' +
    b.querySelector('.option-count').textContent)
"""
_HEADERS_JS = """
() => [...document.querySelectorAll('#game-options .game-section-head')]
  .filter((h) => h.offsetParent !== null)
  .map((h) => h.querySelector('.game-section-name').textContent)
"""


def _open_game(page: Page) -> None:
    page.click("#trigger-game")
    page.wait_for_function("document.getElementById('pop-game').matches(':popover-open')")
    page.wait_for_function(
        "document.getElementById('trigger-game').getAttribute('aria-expanded') === 'true'"
    )


def _rows(page: Page) -> list[str]:
    result: list[str] = page.evaluate(_ROWS_JS)
    return result


def _headers(page: Page) -> list[str]:
    result: list[str] = page.evaluate(_HEADERS_JS)
    return result


def _row(page: Page, slug: str) -> Any:
    return page.locator(f"#game-options [data-game='{slug}']")


def _passing(page: Page) -> int:
    result: int = page.evaluate("() => window.__testHooks.getView().passingCount")
    return result


def _active_customdata(page: Page) -> list[int]:
    js = """
    () => document.getElementById('chart').data
      .filter((t) => typeof t.meta === 'string' && t.meta.startsWith('family:'))
      .flatMap((t) => t.customdata)
    """
    result: list[int] = page.evaluate(js)
    return result


def _wait_url(page: Page, expr: str) -> None:
    page.wait_for_function(f"() => {expr}")


def test_default_popover_lists_sections_counts_and_hides_empty_rows(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    trigger = guarded_page.locator("#trigger-game")
    assert trigger.inner_text() == "Game"
    assert trigger.get_attribute("title") == "Game"
    _open_game(guarded_page)
    assert _headers(guarded_page) == ["PLAYOFF", "BOWLS", "RIVALRIES"]
    assert _rows(guarded_page) == DEFAULT_ROWS
    hidden = guarded_page.evaluate(
        """() => ['cfp-national-championship', 'cfp-quarterfinal', 'cfp-first-round']
          .map((s) => document.querySelector(`[data-game="${s}"]`).offsetParent === null)"""
    )
    assert hidden == [True, True, True]
    assert "All games" not in guarded_page.inner_text("#game-options")


def test_pick_replaces_the_earlier_pick_and_narrows_the_chart(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _open_game(guarded_page)
    _row(guarded_page, "harbor-bowl").click()
    _wait_url(guarded_page, "location.search.includes('game=harbor-bowl')")
    trigger = guarded_page.locator("#trigger-game")
    assert trigger.inner_text().startswith("Game: Harbor Bowl")
    assert trigger.get_attribute("title") == "Game: Harbor Bowl"
    assert _passing(guarded_page) == 1
    assert guarded_page.locator("#games-table tbody tr").count() == 1
    assert guarded_page.evaluate(
        "() => document.getElementById('pop-game').matches(':popover-open')"
    )

    _row(guarded_page, "summit-bowl").click()
    _wait_url(guarded_page, "location.search.includes('game=summit-bowl')")
    assert _row(guarded_page, "harbor-bowl").get_attribute("aria-checked") == "false"
    assert _row(guarded_page, "summit-bowl").get_attribute("aria-checked") == "true"


def test_picked_game_emptied_by_another_filter_stays_checked_and_greyed(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?game=summit-bowl&postseason=exclude")
    _open_game(guarded_page)
    row = _row(guarded_page, "summit-bowl")
    assert row.evaluate("(el) => el.offsetParent !== null")
    assert row.get_attribute("aria-checked") == "true"
    assert "is-zero" in (row.get_attribute("class") or "")
    assert "(0)" in row.inner_text()
    assert "postseason=exclude" in guarded_page.url
    assert guarded_page.locator("#trigger-postseason").inner_text() == "Bowls/Playoffs: Exclude"


def test_search_filters_rows_headers_and_empty_line(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _open_game(guarded_page)
    search = guarded_page.locator("#game-search")
    cases = {
        "bayside": (["BOWLS"], ["Harbor Bowl (1)"]),
        "maplecrest": (["RIVALRIES"], ["The Bridge Game (1)"]),
        "north": (["RIVALRIES"], ["Lakeshore Rivalry (2)"]),
        "semi": (["PLAYOFF"], ["CFP Semifinal (1)"]),
        # Spaces and separators are ignored when matching (WR-01).
        "north-field": (["RIVALRIES"], ["Lakeshore Rivalry (2)"]),
        "bridge  game": (["RIVALRIES"], ["The Bridge Game (1)"]),
    }
    for query, (headers, rows) in cases.items():
        search.fill(query)
        assert _headers(guarded_page) == headers, query
        assert _rows(guarded_page) == rows, query

    search.fill("zzz")
    assert _headers(guarded_page) == []
    assert _rows(guarded_page) == []
    assert guarded_page.inner_text("#game-empty") == 'No games match "zzz".'

    search.fill("a" * 50)
    assert guarded_page.inner_text("#game-empty") == f'No games match "{"a" * 40}...".'

    search.fill("")
    assert _rows(guarded_page) == DEFAULT_ROWS
    assert guarded_page.locator("#game-empty").is_hidden()


def test_empty_line_tells_search_misses_from_filtered_out_games(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    # WR-04: Harbor Bowl matches "harbor" but Exclude bowls & playoffs leaves it at 0.
    open_app(guarded_page, "?postseason=exclude")
    _open_game(guarded_page)
    search = guarded_page.locator("#game-search")
    search.fill("harbor")
    assert _rows(guarded_page) == []
    assert guarded_page.inner_text("#game-empty") == 'No games match "harbor" with these filters.'
    search.fill("zzz")
    assert guarded_page.inner_text("#game-empty") == 'No games match "zzz".'
    search.fill("lakeshore")
    assert _rows(guarded_page) == ["Lakeshore Rivalry (2)"]
    assert guarded_page.locator("#game-empty").is_hidden()


def test_empty_line_when_filters_leave_no_game_and_no_query(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    # 2021 has no named-game telecast in the fixture, so every row is at zero.
    open_app(guarded_page, "?seasons=2021-2021")
    _open_game(guarded_page)
    assert _rows(guarded_page) == []
    assert _headers(guarded_page) == []
    assert guarded_page.inner_text("#game-empty") == "No games match these filters."
    guarded_page.locator("#game-search").fill("bridge")
    assert guarded_page.inner_text("#game-empty") == 'No games match "bridge" with these filters.'


def test_keyboard_moves_selection_without_wrapping(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _open_game(guarded_page)
    guarded_page.focus("#game-search")
    guarded_page.keyboard.press("ArrowDown")
    assert guarded_page.evaluate("() => document.activeElement.dataset.game") == "cfp-semifinal"
    assert "game=" not in guarded_page.url

    guarded_page.keyboard.press("ArrowDown")
    _wait_url(guarded_page, "location.search.includes('game=harbor-bowl')")
    assert guarded_page.evaluate("() => document.activeElement.dataset.game") == "harbor-bowl"

    guarded_page.keyboard.press("End")
    _wait_url(guarded_page, "location.search.includes('game=lakeshore')")
    guarded_page.keyboard.press("ArrowDown")  # no wrap past the last row
    assert guarded_page.evaluate("() => document.activeElement.dataset.game") == "lakeshore"

    guarded_page.keyboard.press("Home")
    _wait_url(guarded_page, "location.search.includes('game=cfp-semifinal')")
    guarded_page.keyboard.press("ArrowUp")
    assert guarded_page.evaluate("() => document.activeElement.id") == "game-search"
    assert "game=cfp-semifinal" in guarded_page.url
    stops = guarded_page.locator("#game-options [data-game][tabindex='0']")
    assert stops.count() == 1


def test_rivalry_tooltip_is_desktop_only(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _open_game(guarded_page)
    rivalry = _row(guarded_page, "lakeshore")
    assert rivalry.get_attribute("title") == "Northfield vs Lakeview"
    assert "Northfield" not in (rivalry.get_attribute("aria-label") or "")
    assert _row(guarded_page, "harbor-bowl").get_attribute("title") is None


_LONG_RIVALRY = "Lakeshore Rivalry for the Very Long Invented Trophy Name"
_LONG_BOWL = "Harbor Bowl Presented by a Very Long Invented Name"


def _serve_long_names(page: Page, fixture_raw: dict[str, Any]) -> None:
    raw = copy.deepcopy(fixture_raw)
    raw["lookups"]["rivalries"][1]["name"] = _LONG_RIVALRY
    franchise = raw["lookups"]["bowl_franchises"][0]
    assert franchise["slug"] == "harbor-bowl"
    franchise["name"] = _LONG_BOWL
    franchise["former"] = [*franchise["former"], "Harbor Bowl"]
    page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))


def test_truncated_rows_show_the_full_name_on_hover(
    guarded_page: Page, open_app: Callable[[Page, str], None], fixture_raw: dict[str, Any]
) -> None:
    # WR-03: a desktop row cut off by the ellipsis carries its full name in title;
    # a rivalry keeps its teams after the name. Short rows are unchanged.
    _serve_long_names(guarded_page, fixture_raw)
    open_app(guarded_page, "")
    _open_game(guarded_page)
    truncated = guarded_page.evaluate(
        """(slugs) => slugs.map((s) => {
          const l = document.querySelector(`[data-game="${s}"] .game-label`);
          return l.scrollWidth > l.clientWidth;
        })""",
        ["lakeshore", "harbor-bowl", "bridge-game", "summit-bowl"],
    )
    assert truncated == [True, True, False, False]
    assert _row(guarded_page, "lakeshore").get_attribute("title") == (
        f"{_LONG_RIVALRY}: Northfield vs Lakeview"
    )
    assert _row(guarded_page, "harbor-bowl").get_attribute("title") == _LONG_BOWL
    assert _row(guarded_page, "bridge-game").get_attribute("title") == ("Stonebridge vs Maplecrest")
    assert _row(guarded_page, "summit-bowl").get_attribute("title") is None


def test_phone_truncated_rows_carry_no_title(
    mobile_page: Page, open_app: Callable[[Page, str], None], fixture_raw: dict[str, Any]
) -> None:
    _serve_long_names(mobile_page, fixture_raw)
    open_app(mobile_page, "")
    mobile_page.click("#filters-button")
    rivalry = _row(mobile_page, "lakeshore")
    rivalry.scroll_into_view_if_needed()
    assert rivalry.get_attribute("title") is None
    assert _row(mobile_page, "harbor-bowl").get_attribute("title") is None
    assert "Northfield" not in rivalry.inner_text()


def test_phone_rows_carry_no_team_text(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(mobile_page, "")
    mobile_page.click("#filters-button")
    rivalry = _row(mobile_page, "lakeshore")
    rivalry.scroll_into_view_if_needed()
    assert rivalry.get_attribute("title") is None
    assert "Northfield" not in rivalry.inner_text()


def test_game_reset_clears_only_game_and_clear_all_clears_both(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?game=lakeshore&school=northfield")
    assert sorted(_active_customdata(guarded_page)) == [0, 4]
    _open_game(guarded_page)
    guarded_page.click("#pop-game .group-reset")
    _wait_url(guarded_page, "!location.search.includes('game=')")
    assert "school=northfield" in guarded_page.url

    open_app(guarded_page, "?game=lakeshore&school=northfield")
    guarded_page.click("#clear-filters")
    _wait_url(
        guarded_page, "!location.search.includes('game=') && !location.search.includes('school=')"
    )


def test_phone_sheet_section_badge_and_touch_targets(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(mobile_page, "?game=lakeshore")
    assert mobile_page.locator("#filters-button").inner_text() == "Filters (1)"
    mobile_page.click("#filters-button")
    sibling = mobile_page.evaluate(
        "() => document.getElementById('filter-game').previousElementSibling.id"
    )
    assert sibling == "filter-postseason"
    mobile_page.locator("#game-search").scroll_into_view_if_needed()
    assert mobile_page.locator("#game-search").bounding_box()["height"] >= 44  # type: ignore[index]
    heights = mobile_page.evaluate(
        """() => [...document.querySelectorAll('#game-options [data-game]')]
          .filter((b) => b.offsetParent !== null).map((b) => b.getBoundingClientRect().height)"""
    )
    assert heights
    assert all(h >= 44 for h in heights)
    assert mobile_page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")


def test_empty_table_copy_names_games(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    text = guarded_page.inner_text("#table-empty")
    assert "Select an announcer, a school, or a game to list matching games." in text
    assert "Pick an announcer, a school, or a game from the filters above." in text
    assert "or a school from the School filter" not in text


def test_game_search_has_one_accessible_name(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    search = guarded_page.locator("#game-search")
    assert search.get_attribute("aria-label") is None
    assert guarded_page.get_by_label("Search games").evaluate("(el) => el.id") == "game-search"


def _head(page: Page, section: str) -> Any:
    return page.locator(f"#game-head-{section}")


def _expanded(page: Page) -> list[str | None]:
    return [
        _head(page, s).get_attribute("aria-expanded") for s in ("playoff", "bowls", "rivalries")
    ]


def _storage_and_search(page: Page) -> tuple[int, int, str]:
    result: tuple[int, int, str] = tuple(  # type: ignore[assignment]
        page.evaluate("() => [localStorage.length, sessionStorage.length, location.search]")
    )
    return result


def test_section_headers_are_toggle_buttons_with_icons(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _open_game(guarded_page)
    assert _headers(guarded_page) == ["PLAYOFF", "BOWLS", "RIVALRIES"]
    info = guarded_page.evaluate(
        """() => [...document.querySelectorAll('#game-options .game-section-head')].map((h) => ({
          tag: h.tagName,
          id: h.id,
          expanded: h.getAttribute('aria-expanded'),
          controls: h.getAttribute('aria-controls'),
          held: document.getElementById(h.getAttribute('aria-controls'))
            ?.querySelectorAll('[role=radio]').length,
          kids: [...h.children].slice(0, 2).map((c) => c.getAttribute('class')),
          kind: h.querySelector('.game-type-icon').dataset.kind,
          role: h.getAttribute('role'),
          checked: h.getAttribute('aria-checked'),
          before: getComputedStyle(h, '::before').content,
        }))"""
    )
    assert [i["tag"] for i in info] == ["BUTTON"] * 3
    assert [i["id"] for i in info] == [
        "game-head-playoff",
        "game-head-bowls",
        "game-head-rivalries",
    ]
    assert all(i["expanded"] == "true" for i in info)
    assert [i["controls"] for i in info] == [
        "game-rows-playoff",
        "game-rows-bowls",
        "game-rows-rivalries",
    ]
    assert all(i["held"] for i in info)
    assert all(i["kids"] == ["game-caret", "game-type-icon"] for i in info)
    assert [i["kind"] for i in info] == ["playoff", "bowl", "rivalry"]
    assert all(i["role"] is None and i["checked"] is None for i in info)
    assert all(i["before"] == "none" for i in info)
    assert (
        guarded_page.get_by_role("button", name="BOWLS", exact=True).evaluate("(el) => el.id")
        == "game-head-bowls"
    )


def test_collapse_hides_rows_but_keeps_pick_and_filters(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?game=summit-bowl")
    _open_game(guarded_page)
    url = guarded_page.url
    passing = _passing(guarded_page)
    head = _head(guarded_page, "bowls")
    head.click()
    assert head.get_attribute("aria-expanded") == "false"
    assert guarded_page.locator("#game-rows-bowls").is_hidden()
    assert _row(guarded_page, "summit-bowl").is_hidden()
    assert head.is_visible()
    assert head.locator(".game-caret").evaluate("(el) => getComputedStyle(el).transform") != "none"
    assert guarded_page.url == url
    assert _passing(guarded_page) == passing
    assert _row(guarded_page, "summit-bowl").get_attribute("aria-checked") == "true"
    assert guarded_page.evaluate("() => document.activeElement.id") == "game-head-bowls"
    head.click()
    assert head.get_attribute("aria-expanded") == "true"
    assert _row(guarded_page, "summit-bowl").is_visible()
    assert guarded_page.locator("#game-empty").is_hidden()


def test_header_keyboard_toggle_keeps_focus(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _open_game(guarded_page)
    _head(guarded_page, "bowls").focus()
    guarded_page.keyboard.press("Enter")
    assert _head(guarded_page, "bowls").get_attribute("aria-expanded") == "false"
    guarded_page.keyboard.press("Space")
    assert _head(guarded_page, "bowls").get_attribute("aria-expanded") == "true"
    assert guarded_page.evaluate("() => document.activeElement.id") == "game-head-bowls"


def test_arrow_keys_skip_collapsed_rows(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _open_game(guarded_page)
    _head(guarded_page, "bowls").click()
    guarded_page.focus("#game-search")
    guarded_page.keyboard.press("ArrowDown")
    assert guarded_page.evaluate("() => document.activeElement.dataset.game") == "cfp-semifinal"
    guarded_page.keyboard.press("ArrowDown")
    _wait_url(guarded_page, "location.search.includes('game=bridge-game')")
    assert guarded_page.evaluate("() => document.activeElement.dataset.game") == "bridge-game"
    assert guarded_page.locator("#game-options [data-game][tabindex='0']").count() == 1


def test_all_collapsed_has_no_radio_tab_stop(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    errors: list[str] = []
    guarded_page.on("pageerror", lambda e: errors.append(str(e)))
    open_app(guarded_page, "")
    _open_game(guarded_page)
    for section in ("playoff", "bowls", "rivalries"):
        _head(guarded_page, section).click()
    assert _expanded(guarded_page) == ["false"] * 3
    assert guarded_page.locator("#game-options [data-game][tabindex='0']").count() == 0
    assert guarded_page.locator("#game-empty").is_hidden()
    assert all(_head(guarded_page, s).is_visible() for s in ("playoff", "bowls", "rivalries"))
    assert errors == []


def test_collapse_shifts_nothing_outside_the_popover(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    open_app(guarded_page, "")
    _open_game(guarded_page)
    js = """() => {
      const r = document.getElementById('pop-game').getBoundingClientRect();
      return [document.getElementById('toolbar').getBoundingClientRect().height,
        document.getElementById('chart-area').getBoundingClientRect().top, r.top, r.left];
    }"""
    before = guarded_page.evaluate(js)
    for section in ("playoff", "bowls", "rivalries"):
        _head(guarded_page, section).click()
        assert guarded_page.evaluate(js) == before
    for section in ("playoff", "bowls", "rivalries"):
        _head(guarded_page, section).click()
        assert guarded_page.evaluate(js) == before


def test_phone_headers_are_touch_targets_and_collapse(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(mobile_page, "")
    mobile_page.click("#filters-button")
    heads = mobile_page.locator("#game-options .game-section-head")
    for i in range(heads.count()):
        heads.nth(i).scroll_into_view_if_needed()
        assert heads.nth(i).bounding_box()["height"] >= 44  # type: ignore[index]
    _head(mobile_page, "rivalries").tap()
    assert _head(mobile_page, "rivalries").get_attribute("aria-expanded") == "false"
    assert mobile_page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")


def test_collapse_is_not_remembered(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _open_game(guarded_page)
    before = _storage_and_search(guarded_page)
    _head(guarded_page, "bowls").click()
    assert _storage_and_search(guarded_page) == before
    open_app(guarded_page, "")
    _open_game(guarded_page)
    assert _expanded(guarded_page) == ["true"] * 3


def test_search_expands_matching_sections_and_restores_on_clear(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _open_game(guarded_page)
    _head(guarded_page, "bowls").click()
    search = guarded_page.locator("#game-search")
    search.fill("harbor")
    assert _head(guarded_page, "bowls").get_attribute("aria-expanded") == "true"
    assert _row(guarded_page, "harbor-bowl").is_visible()
    assert _headers(guarded_page) == ["BOWLS"]
    search.fill("")
    assert _expanded(guarded_page) == ["true", "false", "true"]
    assert _rows(guarded_page) == DEFAULT_ROWS[:1] + DEFAULT_ROWS[3:]


def test_header_click_during_search_becomes_the_baseline(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _open_game(guarded_page)
    search = guarded_page.locator("#game-search")
    search.fill("bridge")
    _head(guarded_page, "rivalries").click()
    assert _head(guarded_page, "rivalries").get_attribute("aria-expanded") == "false"
    assert _row(guarded_page, "bridge-game").is_hidden()
    search.fill("")
    assert _expanded(guarded_page) == ["true", "true", "false"]


def test_collapsed_section_with_the_pick_shows_hint(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _open_game(guarded_page)
    _row(guarded_page, "summit-bowl").click()
    _wait_url(guarded_page, "location.search.includes('game=summit-bowl')")
    hint = guarded_page.locator("#game-head-bowls .game-picked-hint")
    head = _head(guarded_page, "bowls")
    assert hint.is_hidden()
    expanded_height = head.bounding_box()["height"]  # type: ignore[index]
    head.click()
    assert hint.is_visible()
    assert hint.inner_text() == "1 picked"
    assert head.locator(".game-section-name").inner_text() == "BOWLS"
    assert hint.get_attribute("aria-hidden") == "true"
    assert guarded_page.get_by_role("button", name="BOWLS", exact=True).count() == 1
    assert head.bounding_box()["height"] == expanded_height  # type: ignore[index]
    head.click()
    assert hint.is_hidden()
    _head(guarded_page, "playoff").click()
    assert guarded_page.locator("#game-head-playoff .game-picked-hint").is_hidden()


# Opens a popover by clicking its trigger and snapshots the Game sections in the same
# task, before the queued `toggle` event and before any frame paints (WR-01). A reset
# that waits for `toggle` would still show the stale collapsed state here.
_REOPEN_SNAPSHOT_JS = """
([triggerId, popId]) => {
  document.getElementById(triggerId).click();
  const sections = ['playoff', 'bowls', 'rivalries'];
  return {
    open: document.getElementById(popId).matches(':popover-open'),
    expanded: sections.map((s) =>
      document.getElementById(`game-head-${s}`).getAttribute('aria-expanded')),
    rowsHidden: sections.map((s) => document.getElementById(`game-rows-${s}`).hidden),
    hints: [...document.querySelectorAll('#game-options .game-picked-hint')]
      .filter((h) => !h.hidden).length,
  };
}
"""

_ALL_OPEN_SNAPSHOT = {
    "open": True,
    "expanded": ["true"] * 3,
    "rowsHidden": [False] * 3,
    "hints": 0,
}


def test_reopen_starts_all_sections_open(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?game=summit-bowl")
    _open_game(guarded_page)
    _head(guarded_page, "bowls").click()
    assert guarded_page.locator("#game-head-bowls .game-picked-hint").is_visible()
    guarded_page.keyboard.press("Escape")
    guarded_page.wait_for_function("!document.getElementById('pop-game').matches(':popover-open')")
    snapshot = guarded_page.evaluate(_REOPEN_SNAPSHOT_JS, ["trigger-game", "pop-game"])
    assert snapshot == _ALL_OPEN_SNAPSHOT


def test_phone_sheet_reopen_starts_all_sections_open(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(mobile_page, "?game=summit-bowl")
    mobile_page.click("#filters-button")
    mobile_page.wait_for_function(
        "document.getElementById('filters-sheet').matches(':popover-open')"
    )
    _head(mobile_page, "bowls").scroll_into_view_if_needed()
    _head(mobile_page, "bowls").tap()
    assert _head(mobile_page, "bowls").get_attribute("aria-expanded") == "false"
    mobile_page.click("#filters-show-results")
    mobile_page.wait_for_function(
        "!document.getElementById('filters-sheet').matches(':popover-open')"
    )
    snapshot = mobile_page.evaluate(_REOPEN_SNAPSHOT_JS, ["filters-button", "filters-sheet"])
    assert snapshot == _ALL_OPEN_SNAPSHOT


def test_reset_and_clear_all_clear_the_game_search(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?game=lakeshore")
    _open_game(guarded_page)
    guarded_page.locator("#game-search").fill("bridge")
    guarded_page.click("#pop-game .group-reset")
    _wait_url(guarded_page, "!location.search.includes('game=')")
    assert guarded_page.input_value("#game-search") == ""
    assert _rows(guarded_page) == DEFAULT_ROWS

    open_app(guarded_page, "?game=lakeshore")
    _open_game(guarded_page)
    guarded_page.locator("#game-search").fill("bridge")
    guarded_page.keyboard.press("Escape")
    guarded_page.click("#clear-filters")
    _wait_url(guarded_page, "!location.search.includes('game=')")
    _open_game(guarded_page)
    assert guarded_page.input_value("#game-search") == ""
    assert _rows(guarded_page) == DEFAULT_ROWS


def test_game_reset_clears_a_search_with_no_pick(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _open_game(guarded_page)
    reset = guarded_page.locator("#pop-game .group-reset")
    assert reset.get_attribute("aria-disabled") == "true"
    guarded_page.locator("#game-search").fill("harbor")
    assert reset.get_attribute("aria-disabled") == "false"
    reset.click()
    assert guarded_page.input_value("#game-search") == ""
    assert _rows(guarded_page) == DEFAULT_ROWS
    assert reset.get_attribute("aria-disabled") == "true"
    assert "game=" not in guarded_page.url

    # Emptying the box by hand dims Reset again, with no pick to keep it live.
    guarded_page.locator("#game-search").fill("harbor")
    guarded_page.locator("#game-search").fill("")
    assert reset.get_attribute("aria-disabled") == "true"


def test_other_group_reset_keeps_the_game_search(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?school=northfield")
    _open_game(guarded_page)
    guarded_page.locator("#game-search").fill("bridge")
    guarded_page.evaluate(
        "() => document.querySelector('#pop-school .group-reset, [data-reset=\"school\"]').click()"
    )
    _wait_url(guarded_page, "!location.search.includes('school=')")
    assert guarded_page.input_value("#game-search") == "bridge"
