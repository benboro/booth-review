"""Detail-panel and matched-games-table browser tests (SITE-04, SITE-05,
SITE-13, SITE-17, SITE-18, SITE-19; D-02, D-04, D-07, D-08, D-10, D-11,
D-16) -- proven against the fixture build served by
`guarded_page`/`mobile_page`/`open_app`/`fixture_raw`, per
`tests/fixtures/contract/site-data.fixture.json`'s 12 dots and 10 people.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e

# Computes the click/tap point for a telecast's dot from Plotly's own layout
# (RESEARCH T3): the family trace whose `customdata` holds the telecast
# index gives the plotted x/y, converted to page pixels via the axes' own
# `d2p` and the chart div's own size/offset -- never a hardcoded pixel guess.
_DOT_PIXEL_JS = """
(customdata) => {
  const gd = document.getElementById('chart');
  const layout = gd._fullLayout;
  const rect = gd.getBoundingClientRect();
  for (const trace of gd.data) {
    if (typeof trace.meta !== 'string' || !trace.meta.startsWith('family:')) continue;
    const idx = trace.customdata.indexOf(customdata);
    if (idx === -1) continue;
    return {
      x: rect.left + layout._size.l + layout.xaxis.d2p(trace.x[idx]),
      y: rect.top + layout._size.t + layout.yaxis.d2p(trace.y[idx]),
    };
  }
  return null;
}
"""


def _dot_point(page: Page, customdata: int) -> dict[str, float]:
    point: dict[str, float] | None = page.evaluate(_DOT_PIXEL_JS, customdata)
    assert point is not None, f"no dot with customdata {customdata}"
    return point


def _click_dot(page: Page, customdata: int) -> None:
    """Clicks telecast `customdata`'s dot, retrying once (a real WebGL click
    can be flaky in headless Chromium; the hook-driven tests below carry the
    detailed assertions, so this one retry is enough)."""
    point = _dot_point(page, customdata)
    for attempt in range(2):
        page.mouse.click(point["x"], point["y"])
        try:
            expect(page.locator("#detail-panel")).to_be_visible(timeout=2000)
            return
        except AssertionError:
            if attempt == 1:
                raise


def _tap_dot(page: Page, customdata: int) -> None:
    point = _dot_point(page, customdata)
    page.touchscreen.tap(point["x"], point["y"])


def _add_person_by_query(page: Page, query: str, index: int = 0) -> None:
    """Types `query` into the person search, waits out the debounce, and clicks the option."""
    page.fill("#person-search", query)
    option = page.locator("#person-results li[role='option']:not([aria-disabled])").nth(index)
    expect(option).to_be_visible()
    option.click()


def _pick_team(page: Page, query: str) -> None:
    """Types `query` into the team search, waits out the debounce, and clicks the first option."""
    page.fill("#team-search", query)
    option = page.locator("#team-results li[role='option']:not([aria-disabled])").first
    expect(option).to_be_visible()
    option.click()


def _aria_sort(page: Page, key: str) -> str:
    result: str = page.eval_on_selector(
        f'button[data-sort="{key}"]', 'el => el.closest("th").getAttribute("aria-sort")'
    )
    return result


def _row_texts(page: Page) -> list[str]:
    return page.locator("#games-table tbody tr").all_inner_texts()


def test_click_dot_opens_panel_with_both_rr_record_links(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    """SITE-05: clicking dot 4's real pixel position opens the panel with its
    two numbered Ratings Reference record links."""
    open_app(guarded_page, "")
    _click_dot(guarded_page, 4)

    assert guarded_page.evaluate("document.body.classList.contains('panel-open')") is True
    rr_urls = fixture_raw["telecasts"]["rr_urls"][4]
    assert len(rr_urls) == 2
    for i, url in enumerate(rr_urls, start=1):
        link = guarded_page.locator(
            f"#panel-body a:has-text('View record {i} on Ratings Reference')"
        )
        expect(link).to_have_attribute("href", url)


def test_open_panel_hook_shows_source_and_506_link_variants(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-05, D-16: a missing source_url shows plain "not recorded" text
    (never a dead link) while a present s506_url still links; a missing
    s506_url omits that row entirely."""
    open_app(guarded_page, "")

    guarded_page.evaluate("window.__testHooks.openPanel(2)")
    assert (
        guarded_page.locator("#panel-body a:has-text('Original source not recorded')").count() == 0
    )
    assert "Original source not recorded" in guarded_page.inner_text("#panel-body")
    listing_link = guarded_page.locator("#panel-body a:has-text('View 506 Sports listing')")
    expect(listing_link).to_have_count(1)

    guarded_page.evaluate("window.__testHooks.openPanel(3)")
    assert guarded_page.locator("#panel-body a:has-text('View 506 Sports listing')").count() == 0


def test_open_panel_hook_shows_nielsen_adobe_badge(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-02: dot 5's Nielsen+Adobe figure shows the verbatim badge."""
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.openPanel(5)")
    expect(guarded_page.locator("#panel-body .badge")).to_have_text("Nielsen + Adobe (streaming)")


def test_open_panel_hook_shows_alt_cast_and_combined_feeds(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-08: dot 7's alt-cast Taylor Vance and its combined-feed count both show."""
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.openPanel(7)")
    body = guarded_page.inner_text("#panel-body")
    assert "Taylor Vance" in body
    assert "alt-cast" in body
    assert "Combined across 3 feeds" in body


def test_open_panel_hook_shows_spanish_feed_label(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-08: dot 10's Spanish-feed crew entry is labelled, never matched as main."""
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.openPanel(10)")
    assert "Spanish feed" in guarded_page.inner_text("#panel-body")


def test_open_panel_hook_shows_flag_label(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-04: dot 11's model-break flag label shows in the panel."""
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.openPanel(11)")
    assert "CFBD win-probability model break (2025+)" in guarded_page.inner_text("#panel-body")


def test_open_panel_shows_selected_on_this_game(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-07: with Dale Harlow selected, his own dot names him as selected."""
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.setState({people: ['dale-harlow']})")
    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    assert "Selected on this game: Dale Harlow" in guarded_page.inner_text("#panel-body")


def test_panel_swap_close_and_escape_restore_focus(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-10: opening a second dot swaps the panel's contents without closing
    it; the close button and Escape both close it and return focus to
    whatever was focused before the panel opened."""
    open_app(guarded_page, "")

    guarded_page.focus("#person-search")
    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    guarded_page.evaluate("window.__testHooks.openPanel(8)")
    assert "Northfield 24 at Ironpeak 17" in guarded_page.inner_text("#panel-title")
    assert guarded_page.evaluate("document.body.classList.contains('panel-open')") is True

    guarded_page.click("#panel-close")
    guarded_page.wait_for_function("document.getElementById('detail-panel').hidden === true")
    assert guarded_page.evaluate("document.activeElement.id") == "person-search"

    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    guarded_page.keyboard.press("Escape")
    guarded_page.wait_for_function("document.getElementById('detail-panel').hidden === true")
    assert guarded_page.evaluate("document.activeElement.id") == "person-search"


def test_table_empty_state_by_default(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-11: with nothing selected, the table stays hidden and the prompt shows."""
    open_app(guarded_page, "")
    expect(guarded_page.locator("#table-empty")).to_be_visible()
    assert "Nothing selected" in guarded_page.inner_text("#table-empty")
    expect(guarded_page.locator("#games-table")).to_be_hidden()
    assert guarded_page.locator("#games-table tbody tr").count() == 0


def test_table_sorts_by_date_then_viewers(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-13: Dale Harlow's two games list date-ascending by default;
    sorting by viewers, then again, toggles direction with matching aria-sort."""
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.setState({people: ['dale-harlow']})")
    expect(guarded_page.locator("#games-table")).to_be_visible()

    rows = _row_texts(guarded_page)
    assert len(rows) == 2
    assert "2019" in rows[0]
    assert "2026" in rows[1]

    guarded_page.click('button[data-sort="viewers"]')
    rows = _row_texts(guarded_page)
    assert "970,000" in rows[0]
    assert "850,000" in rows[1]
    assert _aria_sort(guarded_page, "viewers") == "descending"
    assert _aria_sort(guarded_page, "date") == "none"

    guarded_page.click('button[data-sort="viewers"]')
    rows = _row_texts(guarded_page)
    assert "850,000" in rows[0]
    assert "970,000" in rows[1]
    assert _aria_sort(guarded_page, "viewers") == "ascending"


def test_table_alt_cast_row_and_team_only_rows(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-08/D-05: an alt-cast selected person is labelled in her row; a
    team-only highlight lists exactly that team's games."""
    open_app(guarded_page, "")
    _add_person_by_query(guarded_page, "Taylor Vance")
    assert "(alt-cast)" in guarded_page.inner_text("#games-table")

    guarded_page.click("#clear-selection")
    _pick_team(guarded_page, "north")
    expect(guarded_page.locator("#games-table")).to_be_visible()
    assert guarded_page.locator("#games-table tbody tr").count() == 3


def test_table_source_cell_links_and_details_button_opens_panel(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-16: the Source cell links the publisher and a Ratings Reference
    record; its Details button opens the same telecast in the panel."""
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.setState({people: ['dale-harlow']})")

    first_row = guarded_page.locator("#games-table tbody tr").first
    source_link = first_row.locator("a:has-text('Wire Service Example')")
    expect(source_link).to_have_attribute("href", "https://example.com/source/1")
    expect(first_row.locator("a:has-text('Ratings Reference')")).to_have_count(1)

    first_row.locator("button:has-text('Details')").click()
    expect(guarded_page.locator("#detail-panel")).to_be_visible()
    assert "Lakeview" in guarded_page.inner_text("#panel-title")


def test_mobile_tap_opens_bottom_sheet_with_44px_close(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-18: tapping a dot on a phone opens the panel as a full-width
    bottom sheet pinned to the viewport's bottom, with a 44px close button."""
    open_app(mobile_page, "")
    _tap_dot(mobile_page, 4)
    mobile_page.wait_for_function("document.body.classList.contains('panel-open')")

    box = mobile_page.locator("#detail-panel").bounding_box()
    assert box is not None
    viewport_width = mobile_page.evaluate("window.innerWidth")
    viewport_height = mobile_page.evaluate("window.innerHeight")
    assert abs(box["width"] - viewport_width) <= 2
    assert abs((box["y"] + box["height"]) - viewport_height) <= 2

    close_box = mobile_page.locator("#panel-close").bounding_box()
    assert close_box is not None
    assert close_box["width"] >= 44
    assert close_box["height"] >= 44


def test_injection_resistant_team_name_and_javascript_url(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    """SITE-19/T-04-34/T-04-35: a malicious team name renders as literal text
    (never executes), and a `javascript:` source_url never becomes a link
    href, in both the panel and the table."""
    mutated = json.loads(json.dumps(fixture_raw))
    mutated["lookups"]["teams"][0]["name"] = '<img src=x onerror="window.__xss=1">'
    mutated["telecasts"]["source_url"][0] = "javascript:window.__xss=2"
    body = json.dumps(mutated)

    def _serve_mutated(route: Route) -> None:
        route.fulfill(status=200, content_type="application/json", body=body)

    guarded_page.route("**/site-data.json*", _serve_mutated)
    open_app(guarded_page, "")

    guarded_page.evaluate("window.__testHooks.setState({people: ['dale-harlow']})")
    guarded_page.evaluate("window.__testHooks.openPanel(0)")

    assert guarded_page.evaluate("window.__xss") is None
    assert "<img" in guarded_page.inner_text("#panel-title")
    assert "<img" in guarded_page.inner_text("#games-table")

    hrefs = guarded_page.eval_on_selector_all(
        "#panel-body a, #games-table a", "els => els.map((e) => e.getAttribute('href'))"
    )
    assert len(hrefs) > 0
    assert all(not (href or "").startswith("javascript:") for href in hrefs)
