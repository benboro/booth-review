"""Phase 26 round 3 phone fix, at 390px: "Filters (N changed)", a fixed one-line summary, a grouped
Filters panel with the people strip, and changed-filter chips that choose their wording by fit.
Synthetic fixtures only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from dark_checks import set_theme
from layout_shift import layout_snapshot
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

KEYS = ("tabs", "toolbar_bottom", "summary_h")
SHEET_OPEN = "document.getElementById('filters-sheet').matches(':popover-open')"
TWO_PEOPLE = "?people=dale-harlow,kris-venn"
FOUR_PEOPLE = "?people=dale-harlow,kris-venn,sam-delgado,pat-rowan"


def _open_sheet(page: Page) -> None:
    page.click("#filters-button")
    page.wait_for_function(SHEET_OPEN)
    page.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")


def _close_sheet(page: Page) -> None:
    page.click("#filters-show-results")
    page.wait_for_function(f"!({SHEET_OPEN})")


def _top(page: Page, selector: str) -> float:
    return float(
        page.evaluate("(s) => document.querySelector(s).getBoundingClientRect().top", selector)
    )


def _chip_form(page: Page, index: int = 0) -> tuple[str, str]:
    """The chip's wording form ('long' or 'short') and its visible text."""
    chip = page.locator("#filter-chips .chip-text").nth(index)
    return str(chip.get_attribute("data-form")), chip.inner_text()


# ---- button, summary, no shift ----


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_button_text_counts_changed_filters_and_chips_stay_off_the_page(
    mobile_page: Page, open_app: Callable[..., None], theme: str
) -> None:
    open_app(mobile_page, "")
    set_theme(mobile_page, theme)
    button = mobile_page.locator("#filters-button")
    expect(button).to_have_text("Filters")
    open_app(mobile_page, "?school=northfield&seasons=2019-2025")
    set_theme(mobile_page, theme)
    expect(button).to_have_text("Filters (2 changed)")
    expect(mobile_page.locator("#filter-chips")).to_be_hidden()
    expect(mobile_page.locator("#summary .sum-right")).to_be_hidden()


def test_summary_is_one_24px_line_and_picks_never_move_the_page(
    mobile_page: Page, open_app: Callable[..., None]
) -> None:
    open_app(mobile_page, "")
    base = layout_snapshot(mobile_page, include=KEYS)
    assert base["summary_h"] == 24
    for query in (
        "?school=northfield&seasons=2019-2025",
        FOUR_PEOPLE + "&mode=compare",
        "?people=dale-harlow-jr&conferences=SEC&role=pbp",
    ):
        open_app(mobile_page, query)
        assert layout_snapshot(mobile_page, include=KEYS) == base, query


def test_opening_and_closing_the_panel_moves_nothing(
    mobile_page: Page, open_app: Callable[..., None]
) -> None:
    open_app(mobile_page, TWO_PEOPLE)
    base = layout_snapshot(mobile_page, include=KEYS)
    _open_sheet(mobile_page)
    _close_sheet(mobile_page)
    assert layout_snapshot(mobile_page, include=KEYS) == base


# ---- grouped panel ----


def test_panel_groups_sections_like_the_bar(
    mobile_page: Page, open_app: Callable[..., None]
) -> None:
    open_app(mobile_page, "")
    _open_sheet(mobile_page)
    order: list[str] = mobile_page.evaluate(
        """() => [...document.querySelectorAll(
            '.sheet-body > .sheet-group-label, .sheet-body > section')]
          .map((el) => el.classList.contains('sheet-group-label') ? el.textContent : el.id)"""
    )
    assert order == [
        "Broadcast",
        "filter-announcers",
        "filter-networks",
        "filter-booth",
        "filter-role",
        "Matchup",
        "filter-conference",
        "filter-school",
        "filter-game",
        "Calendar",
        "filter-seasons",
        "filter-slots",
        "filter-postseason",
    ]
    rule = mobile_page.eval_on_selector(
        ".sheet-group-label",
        "el => { const s = getComputedStyle(el); return [s.borderBottomWidth, s.borderBottomColor,"
        " s.fontWeight, s.fontSize]; }",
    )
    ink = mobile_page.evaluate(
        "() => { const s = document.createElement('span'); s.style.color = 'var(--ink)';"
        " document.body.append(s); const c = getComputedStyle(s).color; s.remove(); return c; }"
    )
    assert rule == ["2px", ink, "600", "14px"]


def test_a_changed_section_shows_its_pick_in_the_accent_beside_its_heading(
    mobile_page: Page, open_app: Callable[..., None]
) -> None:
    open_app(mobile_page, "?school=northfield&role=pbp&people=dale-harlow")
    _open_sheet(mobile_page)
    pick = mobile_page.locator("#filter-school .section-pick")
    expect(pick).to_have_text("Northfield")
    heading = mobile_page.locator("#filter-school h3").bounding_box()
    box = pick.bounding_box()
    assert heading is not None and box is not None
    assert box["x"] >= heading["x"] + heading["width"]
    assert abs(box["y"] + box["height"] / 2 - (heading["y"] + heading["height"] / 2)) <= 8
    accent = mobile_page.evaluate(
        "() => { const s = document.createElement('span'); s.style.color = 'var(--accent)';"
        " document.body.append(s); const c = getComputedStyle(s).color; s.remove(); return c; }"
    )
    assert pick.evaluate("el => getComputedStyle(el).color") == accent
    assert pick.evaluate("el => getComputedStyle(el).fontWeight") == "600"
    # An untouched section shows none.
    expect(mobile_page.locator("#filter-conference .section-pick")).to_be_hidden()


# ---- people strip ----


def test_people_strip_is_112px_and_picking_a_person_moves_nothing(
    mobile_page: Page, open_app: Callable[..., None]
) -> None:
    open_app(mobile_page, "")
    _open_sheet(mobile_page)
    strip = mobile_page.locator("#people-strip")
    assert strip.bounding_box()["height"] == 112  # type: ignore[index]
    expect(mobile_page.locator("#chips .chip-none")).to_have_text("No one picked")
    for selector in ("#compare-toggle", "#together-toggle", "#clear-selection"):
        assert mobile_page.is_disabled(selector), selector
    list_top = _top(mobile_page, "#person-results")
    chips_top = _top(mobile_page, "#chips")

    mobile_page.fill("#person-search", "Dale Harlow")
    option = mobile_page.locator("#person-results li[role='option'][aria-selected='false']").first
    expect(option).to_be_visible()
    option.click()
    expect(mobile_page.locator("#chips .chip")).to_have_count(1)
    assert strip.bounding_box()["height"] == 112  # type: ignore[index]
    assert _top(mobile_page, "#person-results") == list_top
    assert _top(mobile_page, "#chips") == chips_top
    assert not mobile_page.is_disabled("#compare-toggle")
    assert not mobile_page.is_disabled("#clear-selection")

    # The strip's buttons are three equal 44px tall columns with the short labels.
    boxes = [
        mobile_page.locator(i).bounding_box()
        for i in ("#compare-toggle", "#together-toggle", "#clear-selection")
    ]
    assert all(b is not None and b["height"] == 44 for b in boxes)
    assert len({round(b["width"]) for b in boxes if b}) == 1


def test_strip_buttons_keep_their_full_accessible_names(
    mobile_page: Page, open_app: Callable[..., None]
) -> None:
    open_app(mobile_page, TWO_PEOPLE)
    _open_sheet(mobile_page)
    names = {
        "#compare-toggle": "Compare people",
        "#together-toggle": "Called together",
        "#clear-selection": "Clear selection",
    }
    for selector, name in names.items():
        assert (
            mobile_page.get_by_role("button", name=name).evaluate("el => '#' + el.id") == selector
        )
    shorts = mobile_page.locator("#people-strip .lbl-short").all_text_contents()
    assert shorts == ["Compare", "Together", "Clear people"]


def test_strip_returns_to_the_count_line_on_a_wide_viewport(
    mobile_page: Page, open_app: Callable[..., None]
) -> None:
    open_app(mobile_page, TWO_PEOPLE + "&mode=compare")
    assert mobile_page.locator("#people-strip").count() == 1
    mobile_page.set_viewport_size({"width": 1280, "height": 900})
    mobile_page.wait_for_function("!document.getElementById('people-strip')")
    assert mobile_page.locator("#summary .sum-right #chips").count() == 1
    last = mobile_page.evaluate("document.querySelector('#summary .sum-right').lastElementChild.id")
    assert last == "clear-filters"


# ---- changed-filter chip wording ----


def test_chip_shows_the_long_form_when_it_fits(
    mobile_page: Page, open_app: Callable[..., None]
) -> None:
    open_app(mobile_page, TWO_PEOPLE)
    _open_sheet(mobile_page)
    form, text = _chip_form(mobile_page)
    assert (form, text) == ("long", "Announcers: Dale Harlow, Kris Venn")
    chip = mobile_page.locator("#filter-chips .chip-text").first
    sizes: list[int] = chip.evaluate("el => [el.scrollWidth, el.clientWidth]")
    assert sizes[0] <= sizes[1]


def test_chip_falls_back_to_name_and_count_when_it_would_truncate(
    mobile_page: Page, open_app: Callable[..., None]
) -> None:
    open_app(mobile_page, FOUR_PEOPLE)
    _open_sheet(mobile_page)
    form, text = _chip_form(mobile_page)
    assert (form, text) == ("short", "Announcers (4)")
    assert "·" not in text
    # The full text stays the chip's accessible name and tooltip.
    chip = mobile_page.locator("#filter-chips .filter-chip").first
    assert chip.get_attribute("aria-label") == (
        "Announcers: Dale Harlow, Kris Venn, Sam Delgado, Pat Rowan"
    )


def test_chip_wording_follows_the_phone_width(
    mobile_page: Page, open_app: Callable[..., None]
) -> None:
    open_app(mobile_page, TWO_PEOPLE)
    _open_sheet(mobile_page)
    assert _chip_form(mobile_page) == ("long", "Announcers: Dale Harlow, Kris Venn")
    mobile_page.set_viewport_size({"width": 240, "height": 844})
    mobile_page.wait_for_function(
        "document.querySelector('#filter-chips .chip-text').dataset.form === 'short'"
    )
    assert _chip_form(mobile_page) == ("short", "Announcers (2)")
    mobile_page.set_viewport_size({"width": 390, "height": 844})
    mobile_page.wait_for_function(
        "document.querySelector('#filter-chips .chip-text').dataset.form === 'long'"
    )
    assert _chip_form(mobile_page)[0] == "long"


def test_every_chip_decides_on_its_own(mobile_page: Page, open_app: Callable[..., None]) -> None:
    open_app(mobile_page, FOUR_PEOPLE + "&seasons=2019-2025&role=pbp")
    _open_sheet(mobile_page)
    texts: list[Any] = mobile_page.locator("#filter-chips .chip-text").all_inner_texts()
    assert texts[0] == "Announcers (4)"
    assert texts[1] == "Seasons: 2019\u20132025"
    assert texts[2].startswith("Role: ")
    # The strip is one fixed line: it scrolls sideways and never grows.
    assert mobile_page.locator("#filter-chips").bounding_box()["height"] == 60  # type: ignore[index]


def test_clicking_a_chip_keeps_the_filters_sheet_open_and_reaches_its_section(
    mobile_page: Page, open_app: Callable[..., None]
) -> None:
    open_app(mobile_page, TWO_PEOPLE)
    _open_sheet(mobile_page)
    chip = mobile_page.locator("#filter-chips .filter-chip").first
    # The chip is not a popover control: it must not target the sheet it sits in.
    assert chip.get_attribute("popovertarget") is None
    chip.click()
    mobile_page.evaluate("() => new Promise((r) => requestAnimationFrame(r))")
    assert mobile_page.evaluate(SHEET_OPEN) is True
    focused = mobile_page.evaluate("() => document.activeElement.closest('[id^=filter-]')?.id")
    assert focused == "filter-announcers"

