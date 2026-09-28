"""Filter-rail browser tests (SITE-06, SITE-07, SITE-09, SITE-11, SITE-12,
SITE-18; D-05, D-06, D-08, D-09) -- proven against the fixture build served
by `guarded_page`/`mobile_page`/`open_app`, per
`tests/fixtures/contract/site-data.fixture.json`'s 12 dots and 10 people.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _view(page: Page) -> dict[str, Any]:
    result: dict[str, Any] = page.evaluate("() => window.__testHooks.getView()")
    return result


def _visible_count(page: Page) -> int:
    return int(_view(page)["visibleCount"])


def _highlighted(page: Page) -> list[int]:
    result: list[int] = _view(page)["highlighted"]
    return result


def _visible_customdata(page: Page) -> list[int]:
    """Every telecast index currently plotted in a family trace (not the highlight overlay)."""
    js = """
    () => document.getElementById('chart').data
      .filter((t) => typeof t.meta === 'string' && t.meta.startsWith('family:'))
      .flatMap((t) => t.customdata)
    """
    result: list[int] = page.evaluate(js)
    return result


def _options(page: Page, results_id: str) -> Any:
    return page.locator(f"#{results_id} li[role='option']:not([aria-disabled])")


def _add_person_by_query(page: Page, query: str, index: int = 0) -> None:
    """Types `query` into the person search, waits out the debounce, and clicks the option."""
    page.fill("#person-search", query)
    option = _options(page, "person-results").nth(index)
    expect(option).to_be_visible()
    option.click()


def _pick_team(page: Page, query: str) -> None:
    """Types `query` into the team search, waits out the debounce, and clicks the first option."""
    page.fill("#team-search", query)
    option = _options(page, "team-results").first
    expect(option).to_be_visible()
    option.click()


def test_season_counts_hidden_until_disclosure_opened(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """The per-season counts list is noisy by default, so it stays behind a
    collapsed `<details>` disclosure and is invisible until opened (SITE-06
    still requires the counts to exist, just not to always show)."""
    open_app(guarded_page, "")
    assert guarded_page.locator("#season-counts-details").get_attribute("open") is None
    expect(guarded_page.locator("#season-counts")).to_be_hidden()
    assert guarded_page.inner_text("#season-counts") == ""

    guarded_page.click("#season-counts-details summary")
    expect(guarded_page.locator("#season-counts")).to_be_visible()


def test_default_season_counts(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    """SITE-06: every season lists its rated-telecast count on first load,
    once the "Games per season" disclosure is opened."""
    open_app(guarded_page, "")
    guarded_page.click("#season-counts-details summary")
    text = guarded_page.inner_text("#season-counts")
    assert "2019: 2 rated telecasts" in text
    assert "2021: 2 rated telecasts" in text
    assert "2025: 4 rated telecasts" in text
    assert "2026: 4 rated telecasts" in text


def test_season_range_hides_dots_and_leaves_counts_unchanged(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-05: the season range hides dots but never changes the counts list."""
    open_app(guarded_page, "")
    guarded_page.select_option("#season-from", "2025")
    guarded_page.select_option("#season-to", "2026")
    guarded_page.wait_for_function("location.search.includes('seasons=2025-2026')")

    assert _visible_count(guarded_page) == 8
    guarded_page.click("#season-counts-details summary")
    text = guarded_page.inner_text("#season-counts")
    assert "2019: 2 rated telecasts" in text


def test_unchecking_fox_family_updates_total_and_counts(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-06: unchecking a family box hides its networks and its dots feed the per-season counts."""
    open_app(guarded_page, "")
    guarded_page.uncheck("input[data-family-checkbox='fox']")
    guarded_page.wait_for_function("location.search.includes('networks=')")

    assert _visible_count(guarded_page) == 9
    guarded_page.click("#season-counts-details summary")
    assert "2019: 1 rated telecast" in guarded_page.inner_text("#season-counts")


def test_isolating_a_single_network_via_family_checkboxes(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-06: unchecking every other family leaves a single network ("ESPN2 only"-style) selected."""
    open_app(guarded_page, "")
    guarded_page.uncheck("input[data-family-checkbox='disney']")
    guarded_page.uncheck("input[data-family-checkbox='conference']")
    guarded_page.uncheck("input[data-family-checkbox='other']")
    guarded_page.wait_for_function("location.search.includes('networks=net-b')")

    assert _visible_count(guarded_page) == 3


def test_unchecking_one_network_leaves_family_indeterminate(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    """D-06: with a second Disney network in play, unchecking just that one
    network hides only its own dot and leaves the family box indeterminate."""
    mutated = json.loads(json.dumps(fixture_raw))
    mutated["lookups"]["networks"].append(
        {"id": "net-e", "name": "Gamma Sports", "family": "disney"}
    )
    new_idx = len(mutated["lookups"]["networks"]) - 1
    mutated["telecasts"]["network"][4] = new_idx
    mutated["telecasts"]["outlets"][4] = [new_idx]
    body = json.dumps(mutated)

    guarded_page.route(
        "**/site-data.json*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=body),
    )
    open_app(guarded_page, "")

    before = _visible_customdata(guarded_page)
    assert 4 in before

    guarded_page.uncheck("input[data-network-id='net-e']")
    guarded_page.wait_for_function("location.search.includes('networks=')")

    after = _visible_customdata(guarded_page)
    assert 4 not in after
    assert 0 in after
    assert 8 in after
    assert len(after) == len(before) - 1

    family_checkbox = guarded_page.locator("input[data-family-checkbox='disney']")
    assert family_checkbox.evaluate("(el) => el.indeterminate") is True


def test_prime_time_slot_hides_unknown_kickoff(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-11: checking a slot hides non-matching dots, including the one with unknown kickoff."""
    open_app(guarded_page, "")
    guarded_page.check("input[name='slot'][value='prime']")
    guarded_page.wait_for_function("location.search.includes('slot=prime')")

    assert _visible_count(guarded_page) == 4


def test_role_filter_limits_taylor_vance_to_her_main_feed_role(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-07, D-08: a role filter matches only main-feed entries with that role."""
    open_app(guarded_page, "")
    _add_person_by_query(guarded_page, "Taylor Vance")

    guarded_page.check("input[name='role'][value='pbp']")
    guarded_page.wait_for_function("location.search.includes('role=pbp')")
    assert _highlighted(guarded_page) == []
    assert "No games match the current filters for Taylor Vance." in guarded_page.inner_text(
        "#summary-detail"
    )

    guarded_page.check("input[name='role'][value='analyst']")
    guarded_page.wait_for_function("location.search.includes('role=analyst')")
    assert _highlighted(guarded_page) == [5]
    assert guarded_page.is_checked("input[name='role'][value='pbp']") is False


def test_role_filter_never_matches_sideline_crew(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-08: a sideline/unknown-role person never matches a PBP or analyst role filter."""
    open_app(guarded_page, "")
    _add_person_by_query(guarded_page, "Robin Teague")

    guarded_page.check("input[name='role'][value='analyst']")
    guarded_page.wait_for_function("location.search.includes('role=analyst')")
    assert _highlighted(guarded_page) == []


def test_team_search_highlights_and_intersects_with_person(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-09, D-05: picking a team highlights its games; adding a person intersects."""
    open_app(guarded_page, "")
    _pick_team(guarded_page, "north")
    guarded_page.wait_for_function("location.search.includes('team=northfield')")
    assert sorted(_highlighted(guarded_page)) == [0, 4, 8]

    _add_person_by_query(guarded_page, "Casey Lund")
    assert _highlighted(guarded_page) == [4]


def test_reload_restores_full_filter_state(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-12: seasons, networks, slot, role, and team all survive a reload."""
    open_app(guarded_page, "")
    guarded_page.select_option("#season-from", "2021")
    guarded_page.select_option("#season-to", "2026")
    guarded_page.wait_for_function("location.search.includes('seasons=2021-2026')")

    guarded_page.uncheck("input[data-family-checkbox='other']")
    guarded_page.wait_for_function("location.search.includes('networks=')")

    guarded_page.check("input[name='slot'][value='prime']")
    guarded_page.wait_for_function("location.search.includes('slot=prime')")

    guarded_page.check("input[name='role'][value='analyst']")
    guarded_page.wait_for_function("location.search.includes('role=analyst')")

    _pick_team(guarded_page, "north")
    guarded_page.wait_for_function("location.search.includes('team=northfield')")

    url = guarded_page.evaluate("location.search")
    fragments = ("seasons=2021-2026", "networks=", "slot=prime", "role=analyst", "team=northfield")
    for fragment in fragments:
        assert fragment in url

    before_visible = _visible_count(guarded_page)
    before_highlighted = _highlighted(guarded_page)

    guarded_page.reload()
    guarded_page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")

    assert guarded_page.input_value("#season-from") == "2021"
    assert guarded_page.input_value("#season-to") == "2026"
    assert guarded_page.is_checked("input[data-family-checkbox='other']") is False
    assert guarded_page.is_checked("input[name='slot'][value='prime']") is True
    assert guarded_page.is_checked("input[name='role'][value='analyst']") is True
    assert "Northfield" in guarded_page.inner_text("#team-chip")

    assert _visible_count(guarded_page) == before_visible
    assert _highlighted(guarded_page) == before_highlighted


def test_clear_all_filters_restores_dots_and_keeps_team(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Clear all filters resets seasons/networks/slots/role but leaves the team highlight."""
    open_app(guarded_page, "")
    _pick_team(guarded_page, "north")
    guarded_page.wait_for_function("location.search.includes('team=northfield')")

    guarded_page.uncheck("input[data-family-checkbox='other']")
    guarded_page.wait_for_function("location.search.includes('networks=')")
    guarded_page.check("input[name='slot'][value='prime']")
    guarded_page.wait_for_function("location.search.includes('slot=prime')")

    guarded_page.click("#clear-filters")
    guarded_page.wait_for_function("location.search === '?team=northfield'")

    assert _visible_count(guarded_page) == 12
    assert sorted(_highlighted(guarded_page)) == [0, 4, 8]


def test_desktop_rail_toggle_collapses(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-09: the desktop rail collapses via its chevron toggle."""
    open_app(guarded_page, "")
    expect(guarded_page.locator("#rail-body")).to_be_visible()

    guarded_page.click("#rail-toggle")
    expect(guarded_page.locator("#rail-body")).to_be_hidden()
    assert guarded_page.get_attribute("#rail-toggle", "aria-expanded") == "false"


def test_desktop_rail_scrolls_independently_and_keeps_chart_in_view(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """The rail gets its own scrollbar and stays pinned near the top of the
    viewport, so scrolling it (even to its own bottom) never carries the
    chart out of view with it (previously the whole page scrolled together:
    no independent rail scrollbar, and scrolling to the bottom of the rail
    scrolled the chart off-screen with it)."""
    guarded_page.set_viewport_size({"width": 1280, "height": 600})
    open_app(guarded_page, "")

    overflow_y = guarded_page.eval_on_selector("#rail", "el => getComputedStyle(el).overflowY")
    assert overflow_y in ("auto", "scroll")

    viewport_height = guarded_page.evaluate("window.innerHeight")
    rail_height = guarded_page.eval_on_selector("#rail", "el => el.getBoundingClientRect().height")
    assert rail_height <= viewport_height + 1

    guarded_page.eval_on_selector("#rail", "el => { el.scrollTop = el.scrollHeight; }")
    scroll_top = guarded_page.eval_on_selector("#rail", "el => el.scrollTop")
    assert scroll_top > 0, "the rail did not scroll internally -- it has no overflow of its own"

    assert guarded_page.evaluate("window.scrollY") == 0

    chart_box = guarded_page.locator("#chart").bounding_box()
    assert chart_box is not None
    assert 0 <= chart_box["y"] < viewport_height


def test_network_family_group_has_no_leftover_ua_padding_on_desktop(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Root cause of "too much vertical spacing between network entries":
    `<fieldset>`'s and `<ul>`'s own UA-default padding/margin were never
    fully reset, adding ~44px of unstyled space around every family group on
    top of its actual content -- most families hold just 1-3 networks, so
    this read as oversized gaps between "network entries." Each single-
    network family group's total rendered height must stay compact."""
    open_app(guarded_page, "")

    family_groups = guarded_page.locator(".family-group")
    count = family_groups.count()
    assert count >= 1
    for i in range(count):
        box = family_groups.nth(i).bounding_box()
        assert box is not None
        assert box["height"] <= 60, (
            f"family group {i} is {box['height']}px tall, expected a compact block"
        )

    padding = guarded_page.eval_on_selector(".family-group", "el => getComputedStyle(el).padding")
    assert padding == "0px"
    list_margin = guarded_page.eval_on_selector(
        ".network-list", "el => getComputedStyle(el).margin"
    )
    assert list_margin == "0px"


def test_network_checklist_rows_are_compact_on_desktop(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    """Within one family, adjacent network checkbox rows are tightly spaced
    (the `<li>`'s own `xs` margin governs, not the generic filter-row `sm`
    label margin doubling up on top of it). The stock fixture has only one
    network per family, so a second `disney` network is added the same way
    `test_unchecking_one_network_leaves_family_indeterminate` does, to get
    two `<li>` rows inside one `.network-list`."""
    mutated = json.loads(json.dumps(fixture_raw))
    mutated["lookups"]["networks"].append(
        {"id": "net-e", "name": "Gamma Sports", "family": "disney"}
    )
    new_idx = len(mutated["lookups"]["networks"]) - 1
    mutated["telecasts"]["network"][4] = new_idx
    mutated["telecasts"]["outlets"][4] = [new_idx]
    body = json.dumps(mutated)

    guarded_page.route(
        "**/site-data.json*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=body),
    )
    open_app(guarded_page, "")

    rows = guarded_page.locator(
        "fieldset.family-group:has(input[data-family-checkbox='disney']) .network-list li"
    )
    expect(rows).to_have_count(2)

    tops = [rows.nth(i).bounding_box()["y"] for i in range(2)]
    gap = tops[1] - tops[0]
    assert gap <= 26, f"adjacent network rows sit {gap}px apart, expected a compact list"


def test_mobile_filters_drawer(mobile_page: Page, open_app: Callable[[Page, str], None]) -> None:
    """SITE-18: the phone Filters(N) button opens a bottom-sheet drawer with 44px tap targets."""
    open_app(mobile_page, "")
    filters_button = mobile_page.locator("#filters-button")
    expect(filters_button).to_be_visible()
    expect(mobile_page.locator("#rail")).to_be_hidden()

    filters_button.click()
    expect(mobile_page.locator("#rail")).to_be_visible()
    assert mobile_page.evaluate("() => document.activeElement.id") == "rail-close"

    mobile_page.keyboard.press("Escape")
    expect(mobile_page.locator("#rail")).to_be_hidden()
    assert mobile_page.evaluate("() => document.activeElement.id") == "filters-button"

    filters_button.click()
    mobile_page.check("input[name='slot'][value='prime']")
    mobile_page.wait_for_function("location.search.includes('slot=prime')")
    expect(filters_button).to_have_text("Filters (1)")

    tappable = mobile_page.locator("#rail button:visible, #rail label:visible")
    count = tappable.count()
    assert count > 0
    for i in range(count):
        box = tappable.nth(i).bounding_box()
        assert box is not None
        assert box["height"] >= 44
