"""Head-to-head browser tests (SITE-42; 04.7 D-11..D-17): the School popover
control, its snap-back, the toolbar label, resets, the matched-games table,
facets, the stale Butterfly panel, and the phone sheet -- all against the
synthetic contract fixture (Northfield vs Lakeview: games 0 and 4).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

PAIR = "?school=northfield,lakeview"
H2H = PAIR + "&h2h=1"
STALE_TITLE = "Switch School to Either team to compare two schools"


def _open_school(page: Page) -> None:
    page.click("#trigger-school")
    page.wait_for_function("document.getElementById('pop-school').matches(':popover-open')")
    page.wait_for_function(
        "document.getElementById('trigger-school').getAttribute('aria-expanded') === 'true'"
    )


def _view(page: Page) -> dict[str, Any]:
    result: dict[str, Any] = page.evaluate("() => window.__testHooks.getView()")
    return result


def _box(page: Page, selector: str) -> dict[str, float]:
    result: dict[str, float] = page.locator(selector).first.bounding_box()  # type: ignore[assignment]
    return result


def _pressed(page: Page, match: str) -> str | None:
    return page.locator(f"#school-match [data-match='{match}']").get_attribute("aria-pressed")


def _active_customdata(page: Page) -> list[int]:
    js = """
    () => document.getElementById('chart').data
      .filter((t) => typeof t.meta === 'string' && t.meta.startsWith('family:'))
      .flatMap((t) => t.customdata)
    """
    result: list[int] = page.evaluate(js)
    return result


def _wait_search(page: Page, expr: str) -> None:
    page.wait_for_function(f"() => {expr}")


def test_head_to_head_control_appears_only_with_two_schools(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?school=northfield")
    _open_school(guarded_page)
    assert guarded_page.locator("#school-match").is_hidden()
    before = _box(guarded_page, "#pop-school")
    guarded_page.check("#school-list input[value='lakeview']")
    guarded_page.wait_for_function("() => !document.getElementById('school-match').hidden")
    assert guarded_page.locator("#school-match").is_visible()
    assert _pressed(guarded_page, "either") == "true"
    after = _box(guarded_page, "#pop-school")
    assert (before["x"], before["y"]) == (after["x"], after["y"])
    assert _box(guarded_page, "#school-match")["y"] < _box(guarded_page, "#school-search")["y"]


def test_head_to_head_keeps_only_games_between_the_two_schools(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, PAIR)
    _open_school(guarded_page)
    guarded_page.click("#school-match [data-match='both']")
    _wait_search(guarded_page, "location.search.includes('h2h=1')")
    # both-school games: rated 0 and 4 plus unrated 16 (Bayside Bowl between the same two schools)
    assert _view(guarded_page)["passesFilters"] == [0, 4, 16]
    assert _pressed(guarded_page, "both") == "true"
    # the active rated trace carries only rated games; unrated 16 is on the unrated-active traces
    assert sorted(_active_customdata(guarded_page)) == [0, 4]


def test_head_to_head_snaps_back_when_the_school_count_changes(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, H2H)
    _open_school(guarded_page)
    guarded_page.check("#school-list input[value='ironpeak']")
    _wait_search(guarded_page, "!location.search.includes('h2h')")
    assert guarded_page.locator("#school-match").is_hidden()
    guarded_page.uncheck("#school-list input[value='ironpeak']")
    guarded_page.wait_for_function("() => !document.getElementById('school-match').hidden")
    assert _pressed(guarded_page, "either") == "true"
    assert "h2h" not in guarded_page.evaluate("location.search")

    guarded_page.click("#school-match [data-match='both']")
    _wait_search(guarded_page, "location.search.includes('h2h=1')")
    guarded_page.locator("#school-chips .chip-remove[data-slug='lakeview']").click()
    _wait_search(guarded_page, "!location.search.includes('h2h')")


def test_toolbar_names_the_matchup(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, H2H)
    trigger = guarded_page.locator("#trigger-school")
    label = "School: Northfield vs Lakeview"
    assert trigger.inner_text().startswith(label)
    assert trigger.get_attribute("title") == label
    assert trigger.get_attribute("aria-label") == label

    open_app(guarded_page, PAIR)
    assert guarded_page.locator("#trigger-school").inner_text().startswith("School · 2")
    assert guarded_page.locator("#trigger-school").get_attribute("title") == "School · 2"


def test_long_matchup_label_truncates_without_overlap(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    mutated = copy.deepcopy(fixture_raw)
    mutated["lookups"]["teams"][0]["name"] = "Northwestern Wildcats Extra"
    mutated["lookups"]["teams"][1]["name"] = "Mississippi State Bulldogs Extra"
    body = json.dumps(mutated)
    guarded_page.route(
        "**/site-data.json*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=body),
    )
    # The slugs data.js derives from the renamed teams.
    url = "?school=northwestern-wildcats-extra,mississippi-state-bulldogs-extra&h2h=1"
    for width in (1280, 800):
        guarded_page.set_viewport_size({"width": width, "height": 900})
        open_app(guarded_page, url)
        trigger = guarded_page.locator("#trigger-school")
        # Equal grid cells (04.9 D-21): the long label does not widen its button.
        assert _box(guarded_page, "#trigger-school")["width"] == pytest.approx(
            _box(guarded_page, "#trigger-role")["width"], abs=1
        )
        assert trigger.evaluate("e => e.scrollWidth > e.clientWidth")
        assert trigger.evaluate("e => getComputedStyle(e).textOverflow") == "ellipsis"
        toolbar = _box(guarded_page, "#toolbar")
        table = _box(guarded_page, "#games-table:visible, #table-empty:visible")
        assert toolbar["y"] + toolbar["height"] <= table["y"] + 1
        assert guarded_page.evaluate(
            "() => document.documentElement.scrollWidth <= window.innerWidth"
        )


_GEOMETRY_JS = """
() => {
  const box = (id) => document.getElementById(id).getBoundingClientRect();
  const trigger = box('trigger-school');
  const pop = box('pop-school');
  return {
    toolbarHeight: box('toolbar').height,
    chartTop: box('chart-area').top,
    triggerLeft: trigger.left,
    triggerBottom: trigger.bottom,
    popLeft: pop.left,
    popTop: pop.top,
    popWidth: pop.width,
    innerWidth: window.innerWidth,
  };
}
"""


def _settled_geometry(page: Page) -> dict[str, float]:
    # Two animation frames, so the popover's rAF position clamp has run.
    page.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
    result: dict[str, float] = page.evaluate(_GEOMETRY_JS)
    return result


def _assert_popover_under_trigger(geometry: dict[str, float]) -> None:
    """The popover sits 4px under the School trigger, its left clamped on-screen
    (filters.js `positionPopover`)."""
    assert geometry["popTop"] == pytest.approx(geometry["triggerBottom"] + 4, abs=1)
    max_left = max(8, geometry["innerWidth"] - geometry["popWidth"] - 8)
    expected_left = max(8, min(geometry["triggerLeft"], max_left))
    assert geometry["popLeft"] == pytest.approx(expected_left, abs=1)


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide"], indirect=True)
@pytest.mark.parametrize("width", [900, 1024])
def test_toggling_head_to_head_keeps_the_toolbar_and_the_open_popover_in_place(
    guarded_page: Page, open_app: Callable[[Page, str], None], width: int
) -> None:
    """SITE-20: "School · 2" -> "School: Northfield vs Lakeview" must not re-wrap the
    toolbar or move the chart, and the open School popover stays under its button.
    The School button's grid cell, not a free-space cap, keeps the toolbar fixed:
    the longer label truncates inside the cell (04.9 D-21)."""
    guarded_page.set_viewport_size({"width": width, "height": 900})
    open_app(guarded_page, PAIR)
    _open_school(guarded_page)
    before = _settled_geometry(guarded_page)
    _assert_popover_under_trigger(before)

    guarded_page.click("#school-match [data-match='both']")
    _wait_search(guarded_page, "location.search.includes('h2h=1')")
    after = _settled_geometry(guarded_page)
    assert guarded_page.locator("#pop-school").evaluate("e => e.matches(':popover-open')")
    assert after["toolbarHeight"] == before["toolbarHeight"]
    assert after["chartTop"] == before["chartTop"]
    assert after["triggerLeft"] == before["triggerLeft"]
    _assert_popover_under_trigger(after)
    trigger = guarded_page.locator("#trigger-school")
    assert trigger.get_attribute("title") == "School: Northfield vs Lakeview"

    guarded_page.click("#school-match [data-match='either']")
    _wait_search(guarded_page, "!location.search.includes('h2h')")
    back = _settled_geometry(guarded_page)
    assert back["toolbarHeight"] == before["toolbarHeight"]
    assert back["chartTop"] == before["chartTop"]
    _assert_popover_under_trigger(back)


def test_school_reset_and_clear_all_turn_head_to_head_off(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, H2H + "&dots=hide")
    _open_school(guarded_page)
    guarded_page.click("[data-reset='school']")
    _wait_search(guarded_page, "location.search === '?dots=hide'")

    open_app(guarded_page, H2H + "&dots=hide&slot=prime")
    guarded_page.click("#clear-filters")
    _wait_search(guarded_page, "location.search === '?dots=hide'")


def test_matched_games_table_lists_the_head_to_head_games(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, H2H)
    # head-to-head rows: rated 0 and 4 + unrated 16 = 3
    assert guarded_page.locator("#games-table tbody tr").count() == 3
    open_app(guarded_page, PAIR)
    # either school: rated 0, 4, 8, 9 + unrated 13 (Northfield), 16, 18 (Lakeview) = 7
    assert guarded_page.locator("#games-table tbody tr").count() == 7


def test_head_to_head_facets(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    open_app(guarded_page, PAIR)
    either_schools = _view(guarded_page)["facets"]["schools"]
    open_app(guarded_page, H2H)
    assert _view(guarded_page)["facets"]["schools"] == either_schools
    _open_seasons = guarded_page.click
    _open_seasons("#trigger-seasons")
    guarded_page.wait_for_function(
        "document.getElementById('pop-seasons').matches(':popover-open')"
    )
    guarded_page.click("#season-counts-details summary")
    text = guarded_page.locator("#season-counts").inner_text()
    # games 0 (2019), 4 (2025) and unrated 16 (2021) are the head-to-head games; 2026 has none
    assert "2019: 1 game" in text
    assert "2025: 1 game" in text
    assert "2021: 1 game" in text
    assert "2026: 0 games" in text


def test_switching_to_head_to_head_on_the_butterfly_shows_the_hint(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, PAIR + "&view=butterfly")
    _open_school(guarded_page)
    guarded_page.click("#school-match [data-match='both']")
    _wait_search(guarded_page, "location.search.includes('h2h=1')")
    tab = guarded_page.locator("#tab-butterfly")
    assert tab.get_attribute("aria-selected") == "true"
    assert tab.get_attribute("aria-disabled") == "true"
    assert guarded_page.locator("#bars-note").is_visible()
    assert guarded_page.locator("#bars-note .season-empty-title").inner_text() == STALE_TITLE

    guarded_page.evaluate(
        "() => window.__testHooks.setState({ people: ['dale-harlow', 'casey-lund'] })"
    )
    guarded_page.wait_for_function("() => document.getElementById('bars-note').hidden")
    assert "in Northfield vs Lakeview games" in guarded_page.locator("#bars-title").inner_text()


def test_phone_sheet_shows_the_control_with_touch_targets(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(mobile_page, PAIR)
    mobile_page.click("#filters-button")
    control = mobile_page.locator("#filters-sheet .sheet-body #school-match")
    control.scroll_into_view_if_needed()
    assert control.is_visible()
    for btn in control.locator("button").all():
        assert btn.bounding_box()["height"] >= 44  # type: ignore[index]
    mobile_page.click("#school-match [data-match='both']")
    _wait_search(mobile_page, "location.search.includes('h2h=1')")
    assert mobile_page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
