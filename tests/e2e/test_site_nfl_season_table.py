# ruff: noqa: E501  (embedded JS lines and tooltip copy)
"""17.1-02: the NFL team "season by season" table (grouped heads, group rules, header tooltips).

Synthetic nfl-data fixture only; no vault rows.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from dark_checks import set_theme
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

GD = "#nfl-view-special .nfl-chart > div"
TABLE = "#nfl-view-special .nfl-breakdown table"
HEADS = [
    "Season",
    "Solo slots",
    "Sunday windows",
    "Special games",
    "Flexed",
    "Thursday night",
    "Sunday night",
    "Monday night",
    "Holiday",
    "Other solo slot",
    "Fox AGOTW",
    "CBS late national",
    "International",
]
TIPS = {
    "Special games": "Solo slots plus Sunday-window games: Thu + Sun + Mon + Holiday + Other solo + AGOTW + CBS + Intl.",
    "Other solo slot": "A game alone in its window that is not a Thursday, Sunday or Monday night game or a holiday, such as a Saturday, Friday or lone Sunday-afternoon game, or a solo international game.",
    "Fox AGOTW": "Fox's America's Game of the Week, its top Sunday-afternoon game.",
    "CBS late national": "CBS's late Sunday-afternoon national game.",
}
RULED = ["Thursday night", "Fox AGOTW", "Special games", "Flexed"]


def _select_team(page: Page) -> None:
    page.wait_for_function("window.__nflTestHooks.getViewModel('special').drawn === true")
    page.evaluate(
        """(sel) => {
          document.querySelector(sel).emit('plotly_click',
            { points: [{ customdata: 0 }], event: { clientX: 300, clientY: 200 } });
        }""",
        GD,
    )
    page.wait_for_selector(TABLE)


@pytest.fixture
def app(nfl_guarded_page: Page, open_nfl_app: Callable[..., None]) -> Page:
    nfl_guarded_page.set_viewport_size({"width": 1440, "height": 900})
    open_nfl_app(nfl_guarded_page)
    _select_team(nfl_guarded_page)
    return nfl_guarded_page


@pytest.fixture
def mobile(nfl_mobile_page: Page, open_nfl_app: Callable[..., None]) -> Page:
    open_nfl_app(nfl_mobile_page)
    _select_team(nfl_mobile_page)
    return nfl_mobile_page


def _tip_text(page: Page) -> str | None:
    hidden = page.evaluate("document.getElementById('chart-tooltip')?.hidden ?? true")
    if hidden:
        return None
    return page.evaluate("document.getElementById('chart-tooltip').textContent")  # type: ignore[no-any-return]


def test_structure_and_totals(app: Page) -> None:
    rows = app.locator(f"{TABLE} thead tr")
    assert rows.count() == 2
    assert rows.nth(0).locator("th").all_inner_texts() == [
        "Season",
        "Solo slots",
        "Sunday windows",
        "Special games",
        "Flexed",
    ]
    assert rows.nth(1).locator("th").all_inner_texts() == HEADS[5:]
    spans = app.eval_on_selector_all(
        f"{TABLE} thead tr:first-child th", "els => els.map(e => [e.colSpan, e.rowSpan])"
    )
    assert spans == [[1, 2], [5, 1], [3, 1], [1, 2], [1, 2]]
    for tr in app.locator(f"{TABLE} tbody tr").all():
        cells = [int(c) for c in tr.locator("td").all_inner_texts()]
        assert len(cells) == 10
        assert sum(cells[:8]) == cells[8]
        assert tr.locator("td").nth(5).inner_text().isdigit()
        assert tr.locator("td").nth(6).inner_text().isdigit()
    table_text = app.inner_text(TABLE)
    for bad in ("n/a", "weeks", "%", " of "):
        assert bad not in table_text
    text = app.inner_text("#nfl-view-special .nfl-breakdown")
    assert (
        "Special games is the sum of the eight columns before it. "
        "Flexed games are counted separately."
    ) in text
    assert app.locator("#nfl-view-special .nfl-breakdown a").count() == 0


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_vertical_rules_and_weights(app: Page, theme: str) -> None:
    set_theme(app, theme)
    muted = app.evaluate(
        "getComputedStyle(document.documentElement).getPropertyValue('--muted').trim()"
    )
    got = app.evaluate(
        """(sel) => {
          const probe = document.createElement('i');
          probe.style.color = getComputedStyle(document.documentElement).getPropertyValue('--muted');
          document.body.appendChild(probe);
          const muted = getComputedStyle(probe).color;
          probe.remove();
          const out = [];
          for (const c of document.querySelectorAll(sel + ' th, ' + sel + ' td')) {
            const s = getComputedStyle(c);
            out.push({
              text: c.textContent, cls: c.className, left: s.borderLeftWidth, right: s.borderRightWidth,
              color: s.borderLeftColor, muted, weight: s.fontWeight, bg: s.backgroundColor,
              align: s.textAlign, nums: s.fontVariantNumeric, bottom: s.borderBottomWidth,
            });
          }
          return out;
        }""",
        TABLE,
    )
    assert muted
    for c in got:
        assert c["right"] == "0px", c
        if "nfl-vrule" in c["cls"]:
            assert c["left"] == "1px" and c["color"] == c["muted"], c
        else:
            assert c["left"] == "0px", c
        if "nfl-spanner" in c["cls"]:
            assert c["bottom"] == "0px" and c["align"] == "center", c
        if "nfl-total" in c["cls"]:
            assert c["weight"] == "600" and c["bg"] == "rgba(0, 0, 0, 0)", c
        if " num" in f" {c['cls']}":
            assert c["align"] == "right" and "tabular-nums" in c["nums"], c
    ruled_heads = {c["text"] for c in got if "nfl-vrule" in c["cls"] and c["text"] in HEADS}
    assert ruled_heads == {*RULED, "Solo slots", "Sunday windows"}
    # Each spanner's trimmed rule is narrower than its cell.
    widths = app.eval_on_selector_all(
        f"{TABLE} th.nfl-spanner",
        """els => els.map(e => [e.querySelector('.nfl-spanner-label').getBoundingClientRect().width,
          e.getBoundingClientRect().width,
          getComputedStyle(e.querySelector('.nfl-spanner-label')).borderBottomWidth])""",
    )
    for inner, outer, border in widths:
        assert inner < outer and border == "1px"


def test_only_four_heads_are_tooltip_buttons(app: Page) -> None:
    buttons = app.locator(f"{TABLE} button.nfl-tip")
    assert buttons.all_inner_texts() == list(TIPS)
    assert app.locator(f"{TABLE} button").count() == 4
    for label, text in TIPS.items():
        b = app.locator(f"{TABLE} button.nfl-tip", has_text=label)
        assert b.get_attribute("type") == "button"
        assert b.get_attribute("aria-description") == text
        assert b.get_attribute("title") is None
        style = b.evaluate(
            "e => { const s = getComputedStyle(e); return [s.textDecorationLine, s.textDecorationStyle]; }"
        )
        assert style == ["underline", "dotted"]


def test_tooltip_hover_focus_blur_escape(app: Page) -> None:
    for label, text in TIPS.items():
        b = app.locator(f"{TABLE} button.nfl-tip", has_text=label)
        b.hover()
        app.wait_for_function("!document.getElementById('chart-tooltip').hidden")
        assert _tip_text(app) == text
        app.mouse.move(5, 5)
        app.wait_for_function("document.getElementById('chart-tooltip').hidden")
        b.focus()
        app.wait_for_function("!document.getElementById('chart-tooltip').hidden")
        assert _tip_text(app) == text
        app.keyboard.press("Escape")
        app.wait_for_function("document.getElementById('chart-tooltip').hidden")
        b.focus()
        b.blur()
        app.wait_for_function("document.getElementById('chart-tooltip').hidden")


_HIDDEN = "document.getElementById('chart-tooltip').hidden"
_SHOWN = "!document.getElementById('chart-tooltip').hidden"


def test_escape_closes_a_hovered_tip_without_focus(app: Page) -> None:
    """WR-04 (WCAG 1.4.13): a mouse-hovered tip closes on Escape with focus elsewhere."""
    b = app.locator(f"{TABLE} button.nfl-tip", has_text="Fox AGOTW")
    b.hover()
    app.wait_for_function(_SHOWN)
    assert app.evaluate("document.activeElement === document.body")
    app.keyboard.press("Escape")
    app.wait_for_function(_HIDDEN)


def test_hovered_tip_stays_open_while_the_pointer_is_on_it(app: Page) -> None:
    """WR-04 (WCAG 1.4.13): moving the pointer from the header onto its tip keeps it open."""
    b = app.locator(f"{TABLE} button.nfl-tip", has_text="Special games")
    b.hover()
    app.wait_for_function(_SHOWN)
    box = app.evaluate(
        "(() => { const r = document.getElementById('chart-tooltip').getBoundingClientRect();"
        " return [r.left + r.width / 2, r.top + r.height / 2]; })()"
    )
    app.mouse.move(box[0], box[1], steps=4)
    app.wait_for_timeout(500)
    assert _tip_text(app) == TIPS["Special games"]
    app.mouse.move(5, 5)
    app.wait_for_function(_HIDDEN)


def test_focused_tip_outlives_the_pointer_leaving(app: Page) -> None:
    """WR-04: a keyboard-focused header keeps its tip when the pointer passes over and away."""
    b = app.locator(f"{TABLE} button.nfl-tip", has_text="CBS late national")
    b.focus()
    app.wait_for_function(_SHOWN)
    b.hover()
    app.mouse.move(5, 5)
    app.wait_for_timeout(500)
    assert _tip_text(app) == TIPS["CBS late national"]
    b.blur()
    app.wait_for_function(_HIDDEN)


def test_touch_tip_tracks_aria_expanded_and_outside_hides(mobile: Page) -> None:
    """WR-04: the touch toggle reports aria-expanded, and a tip hidden by other code (a
    resize, say) counts as closed, so one tap on the same header reopens it."""
    b = mobile.locator(f"{TABLE} button.nfl-tip", has_text="Special games")
    b.evaluate("e => e.scrollIntoView({ block: 'center' })")
    assert b.get_attribute("aria-expanded") == "false"
    b.tap()
    mobile.wait_for_function(_SHOWN)
    assert b.get_attribute("aria-expanded") == "true"
    mobile.evaluate("document.getElementById('chart-tooltip').hidden = true")
    mobile.wait_for_function(
        "(sel) => document.querySelector(sel).getAttribute('aria-expanded') === 'false'",
        arg=f"{TABLE} button.nfl-tip",
    )
    b.tap()
    mobile.wait_for_function(_SHOWN)
    assert _tip_text(mobile) == TIPS["Special games"]
    assert b.get_attribute("aria-expanded") == "true"
    b.tap()
    mobile.wait_for_function(_HIDDEN)
    assert b.get_attribute("aria-expanded") == "false"


def test_tooltip_stays_in_viewport_at_right_edge(app: Page) -> None:
    app.locator(f"{TABLE} button.nfl-tip", has_text="Special games").hover()
    app.wait_for_function("!document.getElementById('chart-tooltip').hidden")
    box = app.evaluate(
        "(() => { const r = document.getElementById('chart-tooltip').getBoundingClientRect();"
        " return [r.left, r.right, innerWidth]; })()"
    )
    assert box[0] >= 0 and box[1] <= box[2]


def test_phone_tap_toggle_outside_and_replace(mobile: Page) -> None:
    assert mobile.evaluate("innerWidth") == 390  # the page did not widen to fit the table
    assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth")
    one = mobile.locator(f"{TABLE} button.nfl-tip", has_text="Special games")
    two = mobile.locator(f"{TABLE} button.nfl-tip", has_text="Fox AGOTW")
    one.evaluate("e => e.scrollIntoView({ block: 'center' })")
    one.tap()
    mobile.wait_for_function("!document.getElementById('chart-tooltip').hidden")
    assert _tip_text(mobile) == TIPS["Special games"]
    one.tap()
    mobile.wait_for_function("document.getElementById('chart-tooltip').hidden")
    one.tap()
    mobile.wait_for_function("!document.getElementById('chart-tooltip').hidden")
    two.tap()
    mobile.wait_for_function(
        "t => document.getElementById('chart-tooltip').textContent === t", arg=TIPS["Fox AGOTW"]
    )
    mobile.locator("#nfl-view-special .nfl-breakdown h3").evaluate(
        "e => e.scrollIntoView({ block: 'center' })"
    )
    mobile.locator("#nfl-view-special .nfl-breakdown h3").tap()
    mobile.wait_for_function("document.getElementById('chart-tooltip').hidden")


def test_touch_tip_keeps_head_height(mobile: Page) -> None:
    size = mobile.eval_on_selector(
        f"{TABLE} button.nfl-tip", "e => [e.offsetHeight, e.offsetWidth]"
    )
    assert size[0] < 44


def test_rerender_while_open_hides_tooltip(mobile: Page) -> None:
    b = mobile.locator(f"{TABLE} button.nfl-tip", has_text="Special games")
    b.evaluate("e => e.scrollIntoView({ block: 'center' })")
    b.tap()
    mobile.wait_for_function("!document.getElementById('chart-tooltip').hidden")
    mobile.evaluate("window.__nflTestHooks.setState({ seasons: [2025, 2026] })")
    mobile.wait_for_function("document.getElementById('chart-tooltip').hidden")
    mobile.mouse.click(5, 5)
    assert mobile.evaluate("document.getElementById('chart-tooltip').hidden")


def test_international_label_in_table_head(app: Page) -> None:
    assert "International" in app.locator(f"{TABLE} thead th").all_inner_texts()
    assert "International, shared" not in app.inner_text("#nfl-view-special")


def test_phone_second_head_row_is_not_pinned(mobile: Page) -> None:
    """Only the rowspanned Season cell is pinned; the second head row's first cell is a data header."""
    positions = mobile.evaluate(
        """(sel) => {
          const rows = document.querySelectorAll(sel + ' thead tr');
          return [...rows].map((r) => getComputedStyle(r.firstElementChild).position);
        }""",
        TABLE,
    )
    assert positions == ["sticky", "static"]


def test_colgroups_match_the_spanners(app: Page) -> None:
    """IN-07: the scope="colgroup" spanners sit over real <colgroup>s (1 / 5 / 3 / 1 / 1)."""
    spans = app.eval_on_selector_all(f"{TABLE} > colgroup", "els => els.map(e => e.span)")
    assert spans == [1, 5, 3, 1, 1]
    spanners = app.eval_on_selector_all(
        f"{TABLE} th.nfl-spanner", "els => els.map(e => [e.scope, e.colSpan])"
    )
    assert spanners == [["colgroup", 5], ["colgroup", 3]]


# ---- v2.1 todos: phone table reach and scroll cue; header tips above the header ----


def test_phone_table_sits_under_its_heading_and_cues_its_scroll(mobile: Page) -> None:
    # todo 2026-10-25-nfl-phone-season-table-reach: the stacked breakdown lines no longer sit
    # between the heading and the table, and the scroller carries the site's edge-fade cue.
    page = mobile
    got = page.evaluate(
        """() => { const b = document.querySelector('#nfl-view-special .nfl-breakdown');
          const h = b.querySelector('h3').getBoundingClientRect();
          const scroll = b.querySelector('.table-scroll');
          const s = scroll.getBoundingClientRect();
          const lines = b.querySelector('.nfl-breakdown-lines');
          return { gap: s.top - h.bottom,
                   linesAfterTable: !!lines && !!(scroll.compareDocumentPosition(lines) & 4),
                   overflow: scroll.scrollWidth > scroll.clientWidth + 1,
                   cue: scroll.classList.contains('has-more-right') }; }"""
    )
    assert got["gap"] <= 24, got
    assert got["linesAfterTable"] is True, got
    assert got["overflow"] is True and got["cue"] is True, got


def _tip_button(page: Page, label: str) -> Any:
    return page.locator(f"{TABLE} th button.nfl-tip", has_text=label).first


def test_header_tips_open_above_the_header_with_the_formula_on_one_line(app: Page) -> None:
    # todo 2026-10-25-nfl-special-games-tooltip-covers-data: a header tip opened below its
    # header covered the data cells under it, and the Special games formula wrapped mid-sum.
    for label in TIPS:
        button = _tip_button(app, label)
        button.hover()
        app.wait_for_function("!document.getElementById('chart-tooltip').hidden")
        tip = app.locator("#chart-tooltip").bounding_box()
        head = button.bounding_box()
        assert tip is not None and head is not None
        assert tip["y"] + tip["height"] <= head["y"], (label, tip, head)
        assert _tip_text(app) == TIPS[label]
        app.mouse.move(5, 5)
        app.wait_for_function("document.getElementById('chart-tooltip').hidden")
    _tip_button(app, "Special games").hover()
    app.wait_for_function("!document.getElementById('chart-tooltip').hidden")
    formula = app.evaluate(
        """() => { const f = document.querySelector('#chart-tooltip .tooltip-formula');
          if (!f) return null;
          const cs = getComputedStyle(f);
          return { text: f.textContent, lines: f.getBoundingClientRect().height / parseFloat(cs.lineHeight),
                   nowrap: cs.whiteSpace }; }"""
    )
    assert formula is not None
    assert formula["text"] == "Thu + Sun + Mon + Holiday + Other solo + AGOTW + CBS + Intl."
    assert formula["nowrap"] == "nowrap" and formula["lines"] < 1.5, formula


def test_phone_special_games_tip_keeps_the_formula_on_one_line_in_the_viewport(
    mobile: Page,
) -> None:
    page = mobile
    _tip_button(page, "Special games").click()
    page.wait_for_function("!document.getElementById('chart-tooltip').hidden")
    got = page.evaluate(
        """() => { const t = document.getElementById('chart-tooltip').getBoundingClientRect();
          const f = document.querySelector('#chart-tooltip .tooltip-formula');
          const cs = getComputedStyle(f);
          return { left: t.left, right: t.right, vw: window.innerWidth,
                   lines: f.getBoundingClientRect().height / parseFloat(cs.lineHeight),
                   fits: f.scrollWidth <= f.clientWidth + 1 }; }"""
    )
    assert got["left"] >= 0 and got["right"] <= got["vw"], got
    assert got["lines"] < 1.5 and got["fits"] is True, got
