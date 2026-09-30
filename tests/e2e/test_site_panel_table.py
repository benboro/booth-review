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

    assert guarded_page.evaluate("document.getElementById('detail-panel').open") is True
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
    assert "Acme Harbor Bowl" in body7
    assert "Neutral site" not in body7
    assert "Prime time" not in body7
    assert "Sat, Dec 6, 2025" in body7

    guarded_page.evaluate("window.__testHooks.openPanel(5)")
    body5 = guarded_page.inner_text("#panel-body")
    assert "CFP semifinal" in body5
    assert "Summit Bowl Game presented by Northwind" in body5


def test_panel_game_type_line_has_matching_icon_before_label(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """A2a: a bowl or playoff game's game-type line shows its icon first,
    then the label; a regular-season game has no game-type line and keeps
    the long slot label on the panel's date line (A1 is tooltip-only)."""
    open_app(guarded_page, "")

    guarded_page.evaluate("window.__testHooks.openPanel(7)")
    lines = guarded_page.locator("#panel-body .panel-game-type")
    assert lines.count() == 1
    bowl = lines.first
    assert bowl.get_attribute("class") == "panel-game-type panel-bowl"
    assert bowl.locator("svg.game-type-icon").get_attribute("data-kind") == "bowl"
    assert bowl.locator("svg.game-type-icon").get_attribute("aria-hidden") == "true"
    assert bowl.evaluate(
        "el => [...el.children].map(c => c.tagName.toLowerCase() + '.' + c.getAttribute('class'))"
    ) == [
        "svg.game-type-icon",
        "span.bowl-sponsor",
        "strong.bowl-core",
    ]
    assert bowl.locator(".bowl-sponsor").text_content() == "Acme "
    assert bowl.locator(".bowl-core").text_content() == "Harbor Bowl"

    guarded_page.evaluate("window.__testHooks.openPanel(5)")
    lines = guarded_page.locator("#panel-body .panel-game-type")
    assert lines.count() == 2
    first, second = lines.nth(0), lines.nth(1)
    # F3: a semifinal is played at a bowl: bowl line first, then the trophy line.
    assert first.get_attribute("class") == "panel-game-type panel-bowl"
    assert first.locator("svg.game-type-icon").get_attribute("data-kind") == "bowl"
    assert first.locator(".bowl-core").text_content() == "Summit Bowl"
    assert first.locator(".bowl-sponsor").text_content() == " Game presented by Northwind"
    assert second.locator("svg.game-type-icon").get_attribute("data-kind") == "playoff"
    assert second.evaluate("el => el.textContent") == "CFP semifinal"
    assert "·" not in first.text_content()
    assert "·" not in second.text_content()

    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    assert guarded_page.locator("#panel-body .panel-game-type").count() == 0
    assert "Noon (before 2 PM ET)" in guarded_page.inner_text("#panel-body")


@pytest.mark.parametrize(
    ("round_", "neutral", "lines"),
    [
        ("first_round", False, [(["playoff"], "CFP first round")]),
        ("first_round", True, [(["playoff"], "CFP first round")]),
        ("quarterfinal", False, [(["bowl"], "Bowl"), (["playoff"], "CFP quarterfinal")]),
        ("semifinal", False, [(["bowl"], "Bowl"), (["playoff"], "CFP semifinal")]),
        ("championship", True, [(["playoff"], "CFP championship")]),
        ("unrecorded_round", False, [(["playoff"], "College Football Playoff")]),
    ],
)
def test_panel_cfp_game_without_a_named_bowl_shows_generic_lines(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    serve_bowl: Callable[..., None],
    round_: str | None,
    neutral: bool,
    lines: list[tuple[list[str], str]],
) -> None:
    """D-21: with the bowl name unknown (bowl null), a CFP quarterfinal or
    semifinal shows "[bowl] Bowl" then the trophy line; other rounds show the
    trophy line alone. "Neutral site" follows when the game is neutral (no
    named bowl line replaced it). Icons are aria-hidden."""
    serve_bowl(guarded_page, index=5, bowl=None, round_=round_, neutral=neutral)
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.openPanel(5)")
    rows = guarded_page.locator("#panel-body .panel-game-type")
    assert rows.count() == len(lines)
    for n, (kinds, text) in enumerate(lines):
        line = rows.nth(n)
        icons = line.locator("svg.game-type-icon")
        assert icons.evaluate_all("els => els.map(e => e.dataset.kind)") == kinds
        assert icons.evaluate_all("els => els.map(e => e.getAttribute('aria-hidden'))") == [
            "true"
        ] * len(kinds)
        assert line.evaluate("el => el.textContent") == text
        assert line.evaluate("el => el.lastChild.nodeType") == 3
        assert line.locator(".bowl-core").count() == 0
    body = guarded_page.inner_text("#panel-body")
    assert ("Neutral site" in body) is neutral


def test_panel_unknown_bowl_name_keeps_neutral_site(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    serve_bowl: Callable[..., None],
) -> None:
    """D-18/D-21: a bowl with no known name shows a plain "[bowl] Bowl" line
    and keeps "Neutral site" when the game is neutral; a regular-season
    neutral game has no game-type line but shows "Neutral site"."""
    serve_bowl(guarded_page, index=7, bowl=None)
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.openPanel(7)")
    lines = guarded_page.locator("#panel-body .panel-game-type")
    assert lines.count() == 1
    assert lines.first.evaluate("el => el.textContent") == "Bowl"
    assert lines.first.locator(".bowl-core").count() == 0
    assert "Neutral site" in guarded_page.inner_text("#panel-body")

    guarded_page.evaluate("window.__testHooks.openPanel(3)")
    assert guarded_page.locator("#panel-body .panel-game-type").count() == 0
    assert "Neutral site" in guarded_page.inner_text("#panel-body")


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_panel_bowl_core_and_sponsor_colors(
    guarded_page: Page, open_app: Callable[[Page, str], None], scheme: str
) -> None:
    """D-20: the core name is bold in --text, the sponsor text is --muted."""
    guarded_page.emulate_media(color_scheme=scheme)  # type: ignore[arg-type]
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.openPanel(7)")
    css = """() => {
        const probe = (v) => { const e = document.createElement('span');
            e.style.color = `var(${v})`; document.body.appendChild(e);
            const c = getComputedStyle(e).color; e.remove(); return c; };
        const core = getComputedStyle(document.querySelector('#panel-body .bowl-core'));
        const sp = getComputedStyle(document.querySelector('#panel-body .bowl-sponsor'));
        return {core: core.color, weight: core.fontWeight, sp: sp.color,
                text: probe('--text'), muted: probe('--muted')};
    }"""
    got = guarded_page.evaluate(css)
    assert got["core"] == got["text"]
    assert got["weight"] == "600"
    assert got["sp"] == got["muted"]


def test_panel_bowl_name_is_rendered_as_literal_text(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    serve_bowl: Callable[..., None],
) -> None:
    """T-04.2-28: a malicious bowl name renders as literal text and never runs."""
    evil = '<img src=x onerror="window.__xss=1">Harbor Bowl'
    serve_bowl(
        guarded_page,
        index=7,
        bowl=0,
        bowls=[
            {"name": evil, "core": "Harbor Bowl"},
            {"name": "Summit Bowl", "core": "Summit Bowl"},
        ],
    )
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.openPanel(7)")
    assert "<img" in guarded_page.locator("#panel-body .panel-bowl").inner_text()
    assert guarded_page.locator("#panel-body .panel-bowl img").count() == 0
    assert guarded_page.evaluate("window.__xss") is None


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
    assert guarded_page.evaluate("document.getElementById('detail-panel').open") is True

    guarded_page.click("#panel-close")
    guarded_page.wait_for_function("document.getElementById('detail-panel').open === false")
    guarded_page.wait_for_function("document.activeElement.id === 'trigger-seasons'")

    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    guarded_page.keyboard.press("Escape")
    guarded_page.wait_for_function("document.getElementById('detail-panel').open === false")
    guarded_page.wait_for_function("document.activeElement.id === 'trigger-seasons'")


def test_focus_returns_to_chart_after_a_dot_open_and_to_the_row_after_a_row_open(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-02: a dot click leaves focus on <body>, so focus returns to #chart;
    a row open returns focus to that row (matched by its index)."""
    open_app(guarded_page, "")
    _click_dot(guarded_page, 4)
    guarded_page.keyboard.press("Escape")
    guarded_page.wait_for_function("document.getElementById('detail-panel').open === false")
    guarded_page.wait_for_function("document.activeElement.id === 'chart'")

    guarded_page.evaluate("window.__testHooks.setState({people: ['dale-harlow']})")

    row = guarded_page.locator("#games-table tbody tr").first
    row.focus()
    row.press("Enter")
    expect(guarded_page.locator("#detail-panel")).to_be_visible()
    guarded_page.click("#panel-close")
    guarded_page.wait_for_function("document.getElementById('detail-panel').open === false")
    guarded_page.wait_for_function("document.activeElement.tagName === 'TR'")


def test_closing_and_immediately_reopening_the_modal_keeps_it_open(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Closing then reopening in the same task leaves the dialog open (no
    stale hide path can re-close it)."""
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    guarded_page.evaluate(
        "() => { document.getElementById('panel-close').click(); window.__testHooks.openPanel(1); }"
    )
    guarded_page.wait_for_timeout(300)

    assert guarded_page.evaluate("document.getElementById('detail-panel').open") is True
    expect(guarded_page.locator("#panel-close")).to_be_visible()


def test_a_late_close_event_from_an_earlier_session_does_not_steal_focus(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """`close` is delivered as a task, so under load the previous session's
    event can land after the next session has also closed. Both events then
    see a closed dialog; the second must not treat the consumed opener as
    missing and move focus to #chart (flaky CI failure of the Escape step in
    test_panel_swap_close_and_escape_restore_focus)."""
    open_app(guarded_page, "")
    guarded_page.focus("#trigger-seasons")
    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    # Close, reopen, and close again in one task: two close events queue and
    # both arrive with the dialog closed.
    guarded_page.evaluate(
        "() => { window.__testHooks.closePanel(); window.__testHooks.openPanel(1);"
        " document.getElementById('detail-panel').close(); }"
    )
    guarded_page.wait_for_timeout(300)

    assert guarded_page.evaluate("document.getElementById('detail-panel').open") is False
    assert guarded_page.evaluate("document.activeElement.id") == "trigger-seasons"


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
    guarded_page.wait_for_function("document.getElementById('detail-panel').open === false")

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


_SNAPSHOT_JS = """
() => {
  const box = (id) => {
    const r = document.getElementById(id).getBoundingClientRect();
    return [r.x, r.y, r.width, r.height];
  };
  return {
    chart: document.querySelector('#chart .main-svg').getBoundingClientRect().width,
    chartArea: box('chart-area'),
    matched: box('matched-games'),
    scrollY: window.scrollY,
  };
}
"""


def _snapshot(page: Page) -> dict[str, Any]:
    snap: dict[str, Any] = page.evaluate(_SNAPSHOT_JS)
    return snap


def _dialog_open(page: Page) -> bool:
    opened: bool = page.evaluate("document.getElementById('detail-panel').open")
    return opened


def _close_by_backdrop(page: Page) -> None:
    page.mouse.click(4, 4)


@pytest.mark.parametrize(("width", "height"), [(1400, 900), (800, 900)])
def test_modal_opens_centered_and_leaves_the_layout_unchanged(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    width: int,
    height: int,
) -> None:
    """D-01, D-04, D-06: opening from a dot or a table row leaves the chart,
    #chart-area, the table box, and scrollY exactly as they were; the dialog
    is centered, min(560, viewport - 32) wide, and at most 85vh tall."""
    guarded_page.set_viewport_size({"width": width, "height": height})
    open_app(guarded_page, "")

    before = _snapshot(guarded_page)
    _click_dot(guarded_page, 4)
    assert _snapshot(guarded_page) == before
    assert _dialog_open(guarded_page)
    guarded_page.wait_for_function(
        "document.getElementById('detail-panel').getAnimations().length === 0"
    )

    box = guarded_page.locator("#detail-panel").bounding_box()
    assert box is not None
    # Centered in the viewport minus the reserved scrollbar gutter (at most
    # 15px on a classic-scrollbar browser, so the center may sit 7.5px left).
    assert abs(box["x"] + box["width"] / 2 - width / 2) <= 8
    assert abs(box["width"] - min(560, width - 32)) <= 1
    assert box["height"] <= 0.85 * height + 1

    guarded_page.keyboard.press("Escape")
    assert not _dialog_open(guarded_page)

    guarded_page.evaluate("window.__testHooks.setState({people: ['dale-harlow']})")
    expect(guarded_page.locator("#games-table")).to_be_visible()
    guarded_page.locator("#games-table tbody tr").first.scroll_into_view_if_needed()
    before_row = _snapshot(guarded_page)
    guarded_page.locator("#games-table tbody tr").first.locator("td").nth(1).click()
    assert _snapshot(guarded_page) == before_row
    assert _dialog_open(guarded_page)


@pytest.mark.parametrize(("width", "height"), [(1400, 900), (800, 900)])
def test_layout_unchanged_across_every_open_and_close_path(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    width: int,
    height: int,
) -> None:
    """D-01, D-02: the x button, Escape, a backdrop click, a row-opened modal,
    and a swap all leave the layout and scroll position untouched."""
    guarded_page.set_viewport_size({"width": width, "height": height})
    open_app(guarded_page, "?people=dale-harlow")
    expect(guarded_page.locator("#games-table")).to_be_visible()
    row = guarded_page.locator("#games-table tbody tr").first
    row.scroll_into_view_if_needed()
    before = _snapshot(guarded_page)

    def _check(expect_open: bool) -> None:
        assert _snapshot(guarded_page) == before
        assert _dialog_open(guarded_page) is expect_open

    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    _check(True)
    guarded_page.click("#panel-close")
    _check(False)

    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    guarded_page.keyboard.press("Escape")
    _check(False)

    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    _close_by_backdrop(guarded_page)
    _check(False)

    row.locator("td").nth(1).click()
    _check(True)
    guarded_page.click("#panel-close")
    _check(False)

    guarded_page.evaluate("window.__testHooks.openPanel(7)")
    guarded_page.evaluate("window.__testHooks.openPanel(5)")
    _check(True)
    guarded_page.click("#panel-close")
    _check(False)


def test_drag_select_ending_on_backdrop_does_not_close(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Pitfall 4: a press inside the dialog that is released on the backdrop
    (a text drag-select) must not close it."""
    guarded_page.set_viewport_size({"width": 1400, "height": 900})
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.openPanel(7)")
    body_box = guarded_page.locator("#panel-body").bounding_box()
    assert body_box is not None

    guarded_page.mouse.move(body_box["x"] + 20, body_box["y"] + 10)
    guarded_page.mouse.down()
    guarded_page.mouse.move(4, 4, steps=5)
    guarded_page.mouse.up()

    assert _dialog_open(guarded_page)


def test_table_row_open_scrolls_nothing(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-06: opening from a table row does not scroll the page."""
    guarded_page.set_viewport_size({"width": 1280, "height": 800})
    open_app(guarded_page, "?people=dale-harlow")
    first_row = guarded_page.locator("#games-table tbody tr").first
    first_row.scroll_into_view_if_needed()
    before = guarded_page.evaluate("window.scrollY")

    first_row.locator("td").nth(1).click()

    assert _dialog_open(guarded_page)
    assert guarded_page.evaluate("window.scrollY") == before


def test_long_panel_content_scrolls_inside_the_modal(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-03, D-04: long content scrolls inside the dialog, the dialog stays
    within 85vh, and wheeling over the backdrop never scrolls the page."""
    guarded_page.set_viewport_size({"width": 1280, "height": 400})
    open_app(guarded_page, "?people=dale-harlow")
    guarded_page.evaluate("window.__testHooks.openPanel(7)")

    assert (
        guarded_page.evaluate("getComputedStyle(document.querySelector('.panel-inner')).overflowY")
        == "auto"
    )
    panel_box = guarded_page.locator("#detail-panel").bounding_box()
    assert panel_box is not None
    assert panel_box["height"] <= 0.85 * 400 + 1
    assert guarded_page.evaluate(
        "() => { const el = document.querySelector('.panel-inner'); "
        "return el.scrollHeight > el.clientHeight + 1; }"
    )
    guarded_page.evaluate("document.querySelector('.panel-inner').scrollTop = 40")
    assert guarded_page.evaluate("document.querySelector('.panel-inner').scrollTop") > 0

    before = guarded_page.evaluate("window.scrollY")
    guarded_page.mouse.move(4, 4)
    guarded_page.mouse.wheel(0, 400)
    guarded_page.wait_for_timeout(150)
    assert guarded_page.evaluate("window.scrollY") == before


def test_modal_makes_the_page_inert_and_closes_popovers(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-03: opening the modal closes an open filter popover and hides the
    tooltip, and nothing behind the backdrop receives a click."""
    guarded_page.set_viewport_size({"width": 1400, "height": 900})
    open_app(guarded_page, "")
    guarded_page.click("#trigger-seasons")
    guarded_page.wait_for_function(
        "document.getElementById('pop-seasons').matches(':popover-open')"
    )

    guarded_page.evaluate("window.__testHooks.openPanel(7)")
    assert (
        guarded_page.evaluate("document.getElementById('pop-seasons').matches(':popover-open')")
        is False
    )
    assert guarded_page.evaluate("document.querySelector('.chart-tooltip')?.hidden ?? true") is True

    box = guarded_page.locator("#trigger-networks").bounding_box()
    assert box is not None
    guarded_page.mouse.click(box["x"] + 4, box["y"] + 4)
    assert (
        guarded_page.evaluate("document.getElementById('pop-networks').matches(':popover-open')")
        is False
    )
    assert _dialog_open(guarded_page) is False  # the click landed on the backdrop, closing it


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
    mobile_page.wait_for_function("document.getElementById('detail-panel').open")


def test_mobile_tap_opens_bottom_sheet_with_44px_close(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-18: tapping a dot on a phone opens the panel as a full-width
    bottom sheet pinned to the viewport's bottom, with a 44px close button."""
    open_app(mobile_page, "")
    _tap_dot(mobile_page, 4)
    mobile_page.wait_for_function("document.getElementById('detail-panel').open")
    mobile_page.wait_for_function(
        "document.getElementById('detail-panel').getAnimations().length === 0"
    )
    box = mobile_page.locator("#detail-panel").bounding_box()
    assert box is not None
    viewport_width = mobile_page.evaluate("window.innerWidth")
    viewport_height = mobile_page.evaluate("window.innerHeight")
    assert abs(box["width"] - viewport_width) <= 1
    assert abs((box["y"] + box["height"]) - viewport_height) <= 1
    assert abs(box["height"] - 0.55 * viewport_height) <= 2

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
