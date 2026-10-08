"""The Fade | Hide switch at the end of the legend row (04.7 D-04, D-07, D-10),
proven in the browser against the synthetic fixture."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

RULE = "Filters fade the games they exclude unless Hide is on."
HIDE = '#dots-toggle [data-dots="hide"]'
FADE = '#dots-toggle [data-dots="fade"]'


def _box(page: Page, selector: str) -> dict[str, float]:
    box = page.locator(selector).bounding_box()
    assert box is not None, selector
    return box


def _traces(page: Page) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = page.evaluate(
        "() => document.getElementById('chart').data.map(t => ({meta: t.meta, x: t.x}))"
    )
    return result


def _inert_total(page: Page) -> int:
    return sum(len(t["x"]) for t in _traces(page) if str(t["meta"]).startswith("inert:"))


def _family_total(page: Page) -> int:
    return sum(len(t["x"]) for t in _traces(page) if not str(t["meta"]).startswith("inert:"))


def _pressed(page: Page, selector: str) -> str | None:
    return page.locator(selector).get_attribute("aria-pressed")


def _visibility(page: Page, selector: str) -> str:
    result: str = page.evaluate(
        "(s) => getComputedStyle(document.querySelector(s)).visibility", selector
    )
    return result


def test_switch_sits_after_the_chips_outside_the_chip_list(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    assert guarded_page.locator("#legend-row > #legend-chips").count() == 1
    assert guarded_page.locator("#legend-row > #dots-toggle").count() == 1
    assert guarded_page.locator("#legend-chips [data-dots]").count() == 0
    assert guarded_page.locator("#legend-chips button").count() == 4
    assert _pressed(guarded_page, FADE) == "true"
    assert _pressed(guarded_page, HIDE) == "false"
    last_chip = _box(guarded_page, "#legend-chips li:last-child button")
    switch = _box(guarded_page, "#dots-toggle")
    assert switch["x"] >= last_chip["x"] + last_chip["width"]


def test_switch_hides_and_restores_filtered_out_dots(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?slot=late")
    assert _inert_total(guarded_page) == 11
    guarded_page.click(HIDE)
    guarded_page.wait_for_function("location.search.includes('dots=hide')")
    assert _inert_total(guarded_page) == 0
    assert _family_total(guarded_page) == 1
    assert guarded_page.evaluate("window.__testHooks.getState().dots") == "hide"
    assert _pressed(guarded_page, HIDE) == "true"
    guarded_page.click(FADE)
    guarded_page.wait_for_function("!location.search.includes('dots=')")
    assert _inert_total(guarded_page) == 11
    assert _pressed(guarded_page, FADE) == "true"


def test_dots_param_loads_and_unknown_values_fall_back(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?dots=hide")
    assert _pressed(guarded_page, HIDE) == "true"
    assert _pressed(guarded_page, FADE) == "false"
    open_app(guarded_page, "?dots=bogus")
    assert _pressed(guarded_page, FADE) == "true"
    assert _pressed(guarded_page, HIDE) == "false"
    guarded_page.wait_for_function("location.search === ''")


def test_switch_is_concealed_off_scatter_and_never_shifts_the_row(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?school=northfield,lakeview")
    row = _box(guarded_page, "#legend-row")
    controls = _box(guarded_page, "#chart-controls")
    for view in ("bars", "butterfly", "scatter"):
        guarded_page.click(f"#tab-{view}")
        guarded_page.wait_for_function(f"window.__testHooks.getState().view === '{view}'")
        now_row = _box(guarded_page, "#legend-row")
        now_controls = _box(guarded_page, "#chart-controls")
        assert now_row["y"] == row["y"] and now_row["height"] == row["height"]
        assert now_controls["y"] == controls["y"]
        expected = "visible" if view == "scatter" else "hidden"
        assert _visibility(guarded_page, "#dots-toggle") == expected


def test_toggling_fade_hide_moves_nothing(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?seasons=2025-2025")
    selectors = ["#legend-row", "#chart-controls", "#chart", "#summary"]
    before = [_box(guarded_page, s) for s in selectors]
    guarded_page.click(HIDE)
    guarded_page.wait_for_function("location.search.includes('dots=hide')")
    guarded_page.click(FADE)
    guarded_page.wait_for_function("!location.search.includes('dots=')")
    assert [_box(guarded_page, s) for s in selectors] == before


def test_clear_all_and_resets_keep_the_switch(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?dots=hide&school=northfield&slot=prime")
    guarded_page.click("#clear-filters")
    guarded_page.wait_for_function("location.search === '?dots=hide'")
    assert _pressed(guarded_page, HIDE) == "true"
    open_app(guarded_page, "?dots=hide&school=northfield")
    guarded_page.click("#trigger-school")
    guarded_page.wait_for_function("document.getElementById('pop-school').matches(':popover-open')")
    guarded_page.click('[data-reset="school"]')
    guarded_page.wait_for_function("location.search === '?dots=hide'")


def test_switch_copy_states_the_fade_rule(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    chips = guarded_page.locator("#legend-chips")
    assert chips.get_attribute("aria-label") == "Network families: select to show or hide"
    group = guarded_page.locator('#dots-toggle [role="group"]')
    assert group.get_attribute("aria-label") == "Filtered-out dots"
    assert group.get_attribute("title") == RULE
    assert group.get_attribute("aria-description") == RULE
    expect(guarded_page.locator("#dots-toggle .dots-caption")).to_have_text("Filtered-out dots")
    expect(guarded_page.locator("#filter-networks .helper")).to_have_count(0)


@pytest.mark.parametrize("width", [390, 360])
def test_phone_switch_wraps_below_the_chips_with_touch_targets(
    mobile_page: Page, open_app: Callable[[Page, str], None], width: int
) -> None:
    mobile_page.set_viewport_size({"width": width, "height": 780})
    open_app(mobile_page, "")
    chart = _box(mobile_page, "#chart")
    row = _box(mobile_page, "#legend-row")
    assert row["y"] >= chart["y"] + chart["height"]
    last_chip = _box(mobile_page, "#legend-chips li:last-child button")
    switch = _box(mobile_page, "#dots-toggle")
    assert switch["y"] >= last_chip["y"] + last_chip["height"]
    for button in mobile_page.locator("#dots-toggle button").all():
        box = button.bounding_box()
        assert box is not None and box["height"] >= 44
    assert mobile_page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def test_empty_range_note_sits_in_a_surface_box_over_faded_dots(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?people=jax-venn&seasons=2021-2025")
    # jax-venn works only rated games 1 (2019) and 9 (2026); dale-harlow now has unrated game 17 in
    # 2025, so he no longer empties this range. The 6 rated dots drawn "inert:" are games 2-7.
    note = guarded_page.locator("#season-empty-note")
    expect(note).to_be_visible()
    styles = guarded_page.evaluate(
        "() => { const probe = document.createElement('div');"
        " probe.style.backgroundColor = 'var(--surface)'; document.body.appendChild(probe);"
        " const surface = getComputedStyle(probe).backgroundColor; probe.remove();"
        " const s = getComputedStyle(document.getElementById('season-empty-note'));"
        " return {surface, bg: s.backgroundColor, border: s.borderTopWidth,"
        " events: s.pointerEvents}; }"
    )
    assert styles["bg"] == styles["surface"]
    assert styles["border"] == "1px"
    assert styles["events"] == "none"
    box = _box(guarded_page, "#season-empty-note")
    chart = _box(guarded_page, "#chart")
    assert box["x"] >= chart["x"] and box["y"] >= chart["y"]
    assert box["x"] + box["width"] <= chart["x"] + chart["width"]
    assert box["y"] + box["height"] <= chart["y"] + chart["height"]
    assert box["width"] < chart["width"] and box["height"] < chart["height"]
    assert _inert_total(guarded_page) == 6
