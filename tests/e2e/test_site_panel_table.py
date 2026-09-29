"""Detail-panel and matched-games-table browser tests (SITE-04, SITE-05,
SITE-13, SITE-17, SITE-18, SITE-19, SITE-20, SITE-22, SITE-24, SITE-26;
D-01, D-02, D-04, D-06, D-07, D-08, D-09, D-10, D-12, D-16, D-17, D-19) --
proven against the fixture build served by
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
    """Opens the Announcers popover (D-21), types `query` into the person
    search, waits for `#person-results` to reflect it (D-28's synchronous
    filter, no debounce), and clicks the unchecked option."""
    if not page.locator("#pop-announcers").evaluate("(el) => el.matches(':popover-open')"):
        page.click("#trigger-announcers")
        page.wait_for_function("document.getElementById('pop-announcers').matches(':popover-open')")
        page.wait_for_function(
            "document.getElementById('trigger-announcers').getAttribute('aria-expanded') === 'true'"
        )
    page.fill("#person-search", query)
    trimmed = query.strip()
    page.wait_for_function(
        "(q) => document.getElementById('person-results').dataset.query === q", arg=trimmed
    )
    option = page.locator("#person-results li[role='option'][aria-selected='false']").nth(index)
    expect(option).to_be_visible()
    option.click()


def _aria_sort(page: Page, key: str) -> str:
    result: str = page.eval_on_selector(
        f'button[data-sort="{key}"]', 'el => el.closest("th").getAttribute("aria-sort")'
    )
    return result


def _row_texts(page: Page) -> list[str]:
    return page.locator("#games-table tbody tr").all_inner_texts()


def _boxes_intersect(a: dict[str, float], b: dict[str, float]) -> bool:
    return (
        a["x"] < b["x"] + b["width"]
        and a["x"] + a["width"] > b["x"]
        and a["y"] < b["y"] + b["height"]
        and a["y"] + a["height"] > b["y"]
    )


def _chart_svg_width(page: Page) -> float:
    width: float = page.evaluate(
        "() => document.querySelector('#chart .main-svg').getBoundingClientRect().width"
    )
    return width


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


def test_panel_crew_list_is_position_first(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Product notes 2026-09-27: crew entries read "[Position]: [Name]"
    everywhere crew is listed; the panel previously listed "Name — Role"
    (name first)."""
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    items = guarded_page.locator("#panel-body .panel-crew li").all_inner_texts()
    assert "Play-by-play: Dale Harlow" in items
    assert "Analyst: Dale Harlow Jr." in items


def test_panel_shows_conferences_game_type_and_gated_slot_label(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-09, D-17, D-19: the panel's conference row reads away-vs-home; the
    game-type label shows for non-regular games (omitted for a regular-season
    game); the time-slot label shows only for a regular-season Saturday
    game -- dot 0 is one, dot 7 is a Saturday *bowl* (game_type wins over
    the weekday, D-19), and dot 5 is a CFP semifinal."""
    open_app(guarded_page, "")

    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    body0 = guarded_page.inner_text("#panel-body")
    assert "Conference: SEC vs Pac-12" in body0
    assert "Noon (before 2 PM ET)" in body0

    guarded_page.evaluate("window.__testHooks.openPanel(7)")
    body7 = guarded_page.inner_text("#panel-body")
    assert "Bowl" in body7
    assert "Prime time" not in body7
    assert "Sat, Dec 6, 2025" in body7

    guarded_page.evaluate("window.__testHooks.openPanel(5)")
    body5 = guarded_page.inner_text("#panel-body")
    assert "CFP semifinal" in body5


def test_panel_and_table_network_pills_have_wcag_aa_colors(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-26: a network pill's fill/text colors come from its family, the
    same lookup table wherever a pill renders -- the panel's network field
    and the table's network cell."""
    open_app(guarded_page, "?school=northfield")

    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    panel_pill = guarded_page.locator("#panel-body .panel-networks .pill").first
    expect(panel_pill).to_have_css("background-color", "rgb(0, 114, 178)")
    expect(panel_pill).to_have_css("color", "rgb(255, 255, 255)")

    expect(guarded_page.locator("#games-table")).to_be_visible()
    table_pill = guarded_page.locator("#games-table tbody tr").first.locator(".pill").first
    expect(table_pill).to_have_css("background-color", "rgb(0, 114, 178)")
    expect(table_pill).to_have_css("color", "rgb(255, 255, 255)")

    guarded_page.evaluate("window.__testHooks.openPanel(1)")
    fox_pill = guarded_page.locator("#panel-body .panel-networks .pill").first
    expect(fox_pill).to_have_css("background-color", "rgb(0, 158, 115)")
    expect(fox_pill).to_have_css("color", "rgb(0, 0, 0)")


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

    # D-21: #person-search now lives inside the closed Announcers popover, so
    # it can't take focus; #trigger-seasons stands in as "whatever was
    # focused before the panel opened."
    guarded_page.focus("#trigger-seasons")
    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    guarded_page.evaluate("window.__testHooks.openPanel(8)")
    assert "Northfield 24 at Ironpeak 17" in guarded_page.inner_text("#panel-title")
    assert guarded_page.evaluate("document.body.classList.contains('panel-open')") is True

    guarded_page.click("#panel-close")
    guarded_page.wait_for_function("document.getElementById('detail-panel').hidden === true")
    assert guarded_page.evaluate("document.activeElement.id") == "trigger-seasons"

    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    guarded_page.keyboard.press("Escape")
    guarded_page.wait_for_function("document.getElementById('detail-panel').hidden === true")
    assert guarded_page.evaluate("document.activeElement.id") == "trigger-seasons"


def test_reopening_the_panel_during_the_close_transition_keeps_it_shown(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """WR-03: closing the panel schedules a 150 ms post-transition hide; an
    immediate reopen (e.g. clicking another row) must cancel it, or the
    stale timer hides the reopened panel while `panel-open` stays set."""
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    guarded_page.evaluate(
        "() => { document.getElementById('panel-close').click(); window.__testHooks.openPanel(1); }"
    )
    guarded_page.wait_for_timeout(400)

    assert guarded_page.evaluate("document.getElementById('detail-panel').hidden") is False
    assert guarded_page.evaluate("document.body.classList.contains('panel-open')") is True
    expect(guarded_page.locator("#panel-close")).to_be_visible()


def test_table_empty_state_by_default(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-12: with nothing selected, the table stays hidden and the prompt shows."""
    open_app(guarded_page, "")
    expect(guarded_page.locator("#table-empty")).to_be_visible()
    assert "Nothing selected" in guarded_page.inner_text("#table-empty")
    expect(guarded_page.locator("#games-table")).to_be_hidden()
    assert guarded_page.locator("#games-table tbody tr").count() == 0


def test_table_fills_for_school_alone_but_not_for_other_filters_alone(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-12: School alone fills the table with every game that involves it
    (the no-bulk rule's one exception besides a person); Networks or
    Conference alone -- with no person or school selected -- never fill it,
    so a broad filter can never turn the table into a listing of a whole
    league."""
    open_app(guarded_page, "?school=northfield")
    expect(guarded_page.locator("#games-table")).to_be_visible()
    assert guarded_page.locator("#games-table tbody tr").count() == 3

    open_app(guarded_page, "?networks=net-a")
    expect(guarded_page.locator("#table-empty")).to_be_visible()
    expect(guarded_page.locator("#games-table")).to_be_hidden()

    open_app(guarded_page, "?conferences=SEC")
    expect(guarded_page.locator("#table-empty")).to_be_visible()
    expect(guarded_page.locator("#games-table")).to_be_hidden()


def test_sort_header_label_is_not_duplicated(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Regression (screenshot 2026-09-27): `<th>Date <button>Date ...`
    duplicated the sortable column's own label ("Date Date ▲"); the label
    now lives only inside the button."""
    open_app(guarded_page, "")

    date_header_text = guarded_page.inner_text('th:has(button[data-sort="date"])')
    assert date_header_text.count("Date") == 1
    viewers_header_text = guarded_page.inner_text('th:has(button[data-sort="viewers"])')
    assert viewers_header_text.count("Viewers") == 1


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


def test_table_alt_cast_row_and_school_only_rows(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-08/D-12: an alt-cast selected person is labelled in her row; a
    school-only selection lists exactly that school's games."""
    open_app(guarded_page, "")
    _add_person_by_query(guarded_page, "Taylor Vance")
    assert "(alt-cast)" in guarded_page.inner_text("#games-table")

    guarded_page.click("#clear-selection")
    guarded_page.evaluate("window.__testHooks.setState({school: ['northfield']})")
    expect(guarded_page.locator("#games-table")).to_be_visible()
    assert guarded_page.locator("#games-table tbody tr").count() == 3


def test_sideline_role_crew_shows_in_table_and_hover(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """CR-04: role-"unknown" (sideline/other) main-feed crew is listed in the
    table's crew cell and the tooltip. Robin Teague is dot 3's only crew, so
    neither may read "Crew not recorded" there; on dots 8 and 11 Robin is
    listed next to the PBP/analyst crew."""
    open_app(guarded_page, "?people=robin-teague")
    expect(guarded_page.locator("#games-table")).to_be_visible()

    rows = _row_texts(guarded_page)
    assert len(rows) == 3
    for row in rows:
        assert "Sideline/other: Robin Teague" in row
        assert "Crew not recorded" not in row

    # D-22: the default TOOLTIP_MODE ('html') carries no `text` array on any
    # trace -- the custom tooltip renders straight from `tooltipModel`
    # instead. Switch to the `'plotly'` fallback path to read the
    # hovertemplate `text` array this check was written against (see
    # test_site_chart.py's `_use_plotly_tooltip` for the same pattern).
    guarded_page.evaluate("window.__testHooks.setTooltipMode('plotly')")
    guarded_page.wait_for_function(
        "document.getElementById('chart').data.at(-1).hovertemplate === '%{text}<extra></extra>'"
    )
    hover_texts: list[str] = guarded_page.evaluate(
        "() => document.getElementById('chart').data.at(-1).text"
    )
    assert len(hover_texts) == 3
    for text in hover_texts:
        assert "Sideline/other: Robin Teague" in text
        assert "Crew not recorded" not in text


def test_table_row_click_and_enter_open_the_panel_no_details_column(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-06: the whole row is the click/Enter target that opens the detail
    panel; there is no separate Details button/column any more."""
    open_app(guarded_page, "?people=dale-harlow")
    expect(guarded_page.locator("#games-table")).to_be_visible()

    assert guarded_page.locator(".details-button").count() == 0
    assert guarded_page.locator("th:has-text('Details')").count() == 0

    first_row = guarded_page.locator("#games-table tbody tr").first
    first_row.locator("td").nth(1).click()
    expect(guarded_page.locator("#detail-panel")).to_be_visible()
    assert "Lakeview" in guarded_page.inner_text("#panel-title")

    guarded_page.click("#panel-close")
    guarded_page.wait_for_function("document.getElementById('detail-panel').hidden === true")

    second_row = guarded_page.locator("#games-table tbody tr").nth(1)
    second_row.focus()
    second_row.press("Enter")
    expect(guarded_page.locator("#detail-panel")).to_be_visible()


def test_table_row_link_click_follows_the_link_and_does_not_open_the_panel(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-06: a click on a link inside a clickable row (the Source cell)
    follows the link instead of opening the panel -- the row's click handler
    ignores events whose target is inside an `a`."""
    open_app(guarded_page, "?people=dale-harlow")
    first_row = guarded_page.locator("#games-table tbody tr").first
    source_link = first_row.locator("a").first

    # The link opens a new tab (target=_blank, rel=noopener). This test only
    # proves the row's own click handler didn't also open the panel -- it
    # doesn't need the new tab to finish loading, so it's closed immediately.
    with guarded_page.context.expect_page() as new_page_info:
        source_link.click()
    new_page_info.value.close()

    expect(guarded_page.locator("#detail-panel")).to_be_hidden()


@pytest.mark.parametrize(("width", "height", "min_shrink"), [(1280, 800, 250), (800, 900, 200)])
def test_panel_opens_beside_the_chart_only(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    width: int,
    height: int,
    min_shrink: int,
) -> None:
    """D-23, SITE-20: opening the panel narrows only the chart through a real
    grid column (Plotly resizes) -- the matched-games table stays exactly
    where and how wide it was. The panel never overlaps the chart, the
    legend chips, or the table, sits above the table (not beside it), and
    matches the chart area's own height (replaces plan 04.1-05's
    both-rows-span behavior)."""
    guarded_page.set_viewport_size({"width": width, "height": height})
    open_app(guarded_page, "?people=dale-harlow")
    expect(guarded_page.locator("#games-table")).to_be_visible()

    before_chart_width = _chart_svg_width(guarded_page)
    table_box_before = guarded_page.locator("#games-table").bounding_box()
    chart_area_box_before = guarded_page.locator("#chart-area").bounding_box()
    legend_box_before = guarded_page.locator("#legend-chips").bounding_box()
    assert table_box_before is not None
    assert chart_area_box_before is not None
    assert legend_box_before is not None

    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    guarded_page.wait_for_function(
        "(args) => { "
        "const w = document.querySelector('#chart .main-svg').getBoundingClientRect().width; "
        "return (args.before - w) >= args.minShrink; }",
        arg={"before": before_chart_width, "minShrink": min_shrink},
        timeout=3000,
    )

    table_box = guarded_page.locator("#games-table").bounding_box()
    chart_area_box = guarded_page.locator("#chart-area").bounding_box()
    panel_box = guarded_page.locator("#detail-panel").bounding_box()
    chart_box = guarded_page.locator("#chart").bounding_box()
    legend_box = guarded_page.locator("#legend-chips").bounding_box()
    matched_games_box = guarded_page.locator("#matched-games").bounding_box()
    assert table_box is not None
    assert chart_area_box is not None
    assert panel_box is not None
    assert chart_box is not None
    assert legend_box is not None
    assert matched_games_box is not None

    # The table stays exactly where and how wide it was -- the panel narrows
    # only the chart (D-23).
    table_right = table_box["x"] + table_box["width"]
    table_right_before = table_box_before["x"] + table_box_before["width"]
    assert abs(table_box["x"] - table_box_before["x"]) <= 1
    assert abs(table_right - table_right_before) <= 1
    assert abs(table_box["width"] - table_box_before["width"]) <= 1

    assert not _boxes_intersect(panel_box, chart_box)
    assert not _boxes_intersect(panel_box, legend_box)
    assert not _boxes_intersect(panel_box, table_box)
    assert panel_box["y"] + panel_box["height"] <= matched_games_box["y"] + 1
    assert abs(panel_box["height"] - chart_area_box["height"]) <= 2

    # #chart-area's own height tracks the chart plot's fixed height, plus
    # whatever the D-04 chip legend row needs (`flex-wrap: wrap`, pre-
    # existing, unrelated to this plan's panel geometry) -- at the tablet
    # width the narrower chart area can wrap the legend chips onto an
    # extra line. Any #chart-area height change beyond that legend-driven
    # growth would mean the panel geometry itself is pushing the chart row
    # taller, which D-23 forbids.
    legend_growth = max(0.0, legend_box["height"] - legend_box_before["height"])
    assert abs(chart_area_box["height"] - chart_area_box_before["height"]) <= legend_growth + 2


@pytest.mark.parametrize(("width", "height"), [(1280, 800), (800, 900)])
def test_closing_the_panel_restores_the_chart_width_every_time(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    width: int,
    height: int,
) -> None:
    """D-24: every close path -- the close button, Escape, a close mid-
    transition, a table-row-opened panel, and a panel swap -- restores the
    chart to exactly its pre-open width. `panelResizes` alone isn't proof (a
    resize can fire and still leave the chart at the wrong width if a later
    close never resizes at all); this polls the chart's own geometry."""
    guarded_page.set_viewport_size({"width": width, "height": height})
    open_app(guarded_page, "?people=dale-harlow")
    expect(guarded_page.locator("#games-table")).to_be_visible()

    w0 = _chart_svg_width(guarded_page)
    min_shrink = 250 if width >= 1280 else 200

    def _wait_for_shrink() -> None:
        guarded_page.wait_for_function(
            "(args) => { "
            "const w = document.querySelector('#chart .main-svg').getBoundingClientRect().width; "
            "return (args.before - w) >= args.minShrink; }",
            arg={"before": w0, "minShrink": min_shrink},
            timeout=3000,
        )

    def _wait_for_close() -> None:
        guarded_page.wait_for_function(
            "(target) => { "
            "const w = document.querySelector('#chart .main-svg').getBoundingClientRect().width; "
            "return Math.abs(w - target) <= 1; }",
            arg=w0,
            timeout=3000,
        )
        guarded_page.wait_for_function("document.getElementById('detail-panel').hidden === true")

    # (a) openPanel(0) + #panel-close click
    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    _wait_for_shrink()
    guarded_page.click("#panel-close")
    _wait_for_close()

    # (b) openPanel(0) + Escape
    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    _wait_for_shrink()
    guarded_page.keyboard.press("Escape")
    _wait_for_close()

    # (c) openPanel(0) then close 50ms later, mid-transition (no shrink wait --
    # the whole point is closing before the open transition finishes).
    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    guarded_page.wait_for_timeout(50)
    guarded_page.click("#panel-close")
    _wait_for_close()

    # (d) a table row click opens the panel, then #panel-close closes it.
    first_row = guarded_page.locator("#games-table tbody tr").first
    first_row.click()
    _wait_for_shrink()
    guarded_page.click("#panel-close")
    _wait_for_close()

    # (e) openPanel(0) -> openPanel(8) swap -> close
    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    _wait_for_shrink()
    guarded_page.evaluate("window.__testHooks.openPanel(8)")
    guarded_page.click("#panel-close")
    _wait_for_close()


def test_closing_the_panel_restores_the_chart_width_under_reduced_motion(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-24: under reduced motion the panel hides immediately with no
    transition event ever firing; the rAF-driven resize path
    (`resizeChartForPanelIfNoTransition`) plus the ResizeObserver debounce
    still restore the chart's width after a close."""
    guarded_page.emulate_media(reduced_motion="reduce")
    guarded_page.set_viewport_size({"width": 1280, "height": 800})
    open_app(guarded_page, "?people=dale-harlow")
    expect(guarded_page.locator("#games-table")).to_be_visible()

    w0 = _chart_svg_width(guarded_page)
    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    guarded_page.wait_for_function(
        "(target) => { "
        "const w = document.querySelector('#chart .main-svg').getBoundingClientRect().width; "
        "return (target - w) >= 200; }",
        arg=w0,
        timeout=3000,
    )
    guarded_page.click("#panel-close")
    guarded_page.wait_for_function(
        "(target) => { "
        "const w = document.querySelector('#chart .main-svg').getBoundingClientRect().width; "
        "return Math.abs(w - target) <= 1; }",
        arg=w0,
        timeout=3000,
    )
    guarded_page.wait_for_function("document.getElementById('detail-panel').hidden === true")


def test_table_row_click_scrolls_chart_and_panel_into_view(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-23: a table row can be far below the fold; clicking it opens the
    panel beside the chart and scrolls both into view."""
    guarded_page.set_viewport_size({"width": 1280, "height": 800})
    open_app(guarded_page, "?people=dale-harlow")

    first_row = guarded_page.locator("#games-table tbody tr").first
    matchup = first_row.locator("td").nth(1).inner_text()

    guarded_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    first_row.click()

    guarded_page.wait_for_function(
        "() => { "
        "const top = document.getElementById('chart-area').getBoundingClientRect().top; "
        "return top >= -1 && top < window.innerHeight; }",
        timeout=3000,
    )

    panel_box = guarded_page.locator("#detail-panel").bounding_box()
    assert panel_box is not None
    viewport_width = guarded_page.evaluate("window.innerWidth")
    viewport_height = guarded_page.evaluate("window.innerHeight")
    viewport_box = {"x": 0, "y": 0, "width": viewport_width, "height": viewport_height}
    assert _boxes_intersect(panel_box, viewport_box)
    assert guarded_page.inner_text("#panel-title") == matchup


def test_long_panel_content_scrolls_inside_the_panel(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-23: longer panel content scrolls inside the panel and never makes
    the chart row taller -- dot 7 (a flag, a combined-feeds note, and a
    3-person crew: the fixture's richest panel body) is the stress case."""
    guarded_page.set_viewport_size({"width": 1280, "height": 800})
    open_app(guarded_page, "?people=dale-harlow")

    chart_area_box_before = guarded_page.locator("#chart-area").bounding_box()
    assert chart_area_box_before is not None

    guarded_page.evaluate("window.__testHooks.openPanel(7)")
    guarded_page.wait_for_function("document.body.classList.contains('panel-open')")

    overflow_y = guarded_page.evaluate(
        "getComputedStyle(document.querySelector('.panel-inner')).overflowY"
    )
    assert overflow_y == "auto"

    panel_box = guarded_page.locator("#detail-panel").bounding_box()
    inner_box = guarded_page.locator(".panel-inner").bounding_box()
    chart_area_box = guarded_page.locator("#chart-area").bounding_box()
    assert panel_box is not None
    assert inner_box is not None
    assert chart_area_box is not None
    assert abs(inner_box["height"] - panel_box["height"]) <= 1
    assert abs(chart_area_box["height"] - chart_area_box_before["height"]) <= 2

    overflows = guarded_page.evaluate(
        "() => { const el = document.querySelector('.panel-inner'); "
        "return el.scrollHeight > el.clientHeight + 1; }"
    )
    if overflows:
        before_scroll_y = guarded_page.evaluate("window.scrollY")
        guarded_page.evaluate("document.querySelector('.panel-inner').scrollTop = 40")
        after_scroll_top = guarded_page.evaluate("document.querySelector('.panel-inner').scrollTop")
        after_scroll_y = guarded_page.evaluate("window.scrollY")
        assert after_scroll_top > 0
        assert after_scroll_y == before_scroll_y


def test_phone_table_never_scrolls_the_page(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Phone table overflow (deferred-items.md, folded into this plan's Task
    2 step 5): a filled matched-games table on a phone scrolls inside its
    own container, never the page (SITE-20, sign-off step 10's "no
    horizontal scroll"). Tapping a row still opens the bottom sheet (D-06)."""
    open_app(mobile_page, "?people=dale-harlow")
    expect(mobile_page.locator("#games-table")).to_be_visible()

    scroll_width = mobile_page.evaluate("document.documentElement.scrollWidth")
    inner_width = mobile_page.evaluate("window.innerWidth")
    assert scroll_width <= inner_width

    first_row = mobile_page.locator("#games-table tbody tr").first
    first_row.tap()
    mobile_page.wait_for_function("document.body.classList.contains('panel-open')")


def test_mobile_tap_opens_bottom_sheet_with_44px_close(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-18: tapping a dot on a phone opens the panel as a full-width
    bottom sheet pinned to the viewport's bottom, with a 44px close button."""
    open_app(mobile_page, "")
    _tap_dot(mobile_page, 4)
    mobile_page.wait_for_function("document.body.classList.contains('panel-open')")
    # The bottom sheet's own slide-in is a 150ms `transform` transition
    # (Task 2); wait for it to finish before measuring, or a bounding box
    # read moments after the class is added can catch it mid-slide.
    mobile_page.wait_for_function(
        "getComputedStyle(document.getElementById('detail-panel')).transform === 'none'"
    )

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


def test_mobile_table_row_meets_the_44px_tap_target(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-18: a matched-games row is at least 44px tall on phones -- the
    same tap-target minimum as every other interactive control, now that
    the whole row (not a separate button) is the click target (D-06)."""
    open_app(mobile_page, "?school=northfield")
    expect(mobile_page.locator("#games-table")).to_be_visible()
    row_box = mobile_page.locator("#games-table tbody tr").first.bounding_box()
    assert row_box is not None
    assert row_box["height"] >= 44


def test_injection_resistant_team_name_conference_name_and_javascript_url(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    """SITE-19/T-04-34/T-04-35: a malicious team or conference name renders
    as literal text (never executes), and a `javascript:` source_url never
    becomes a link href, in both the panel and the table."""
    mutated = json.loads(json.dumps(fixture_raw))
    mutated["lookups"]["teams"][0]["name"] = '<img src=x onerror="window.__xss=1">'
    mutated["lookups"]["conferences"][5]["name"] = '<img src=x onerror="window.__xssConf=1">'
    mutated["telecasts"]["source_url"][0] = "javascript:window.__xss=2"
    body = json.dumps(mutated)

    def _serve_mutated(route: Route) -> None:
        route.fulfill(status=200, content_type="application/json", body=body)

    guarded_page.route("**/site-data.json*", _serve_mutated)
    open_app(guarded_page, "")

    guarded_page.evaluate("window.__testHooks.setState({people: ['dale-harlow']})")
    guarded_page.evaluate("window.__testHooks.openPanel(0)")

    assert guarded_page.evaluate("window.__xss") is None
    assert guarded_page.evaluate("window.__xssConf") is None
    assert "<img" in guarded_page.inner_text("#panel-title")
    assert "<img" in guarded_page.inner_text("#games-table")
    assert "<img" in guarded_page.locator("#panel-body .panel-conferences").inner_text()

    hrefs = guarded_page.eval_on_selector_all(
        "#panel-body a, #games-table a", "els => els.map((e) => e.getAttribute('href'))"
    )
    assert len(hrefs) > 0
    assert all(not (href or "").startswith("javascript:") for href in hrefs)
