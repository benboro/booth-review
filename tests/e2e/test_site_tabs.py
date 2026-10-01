"""Chart tabs, hint row, Bar style / Group-by controls, and the chart panel
(SITE-33; D-10, D-12, D-13, D-14, D-17), proven in the browser against the
12-telecast synthetic fixture.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

BARS_HINT = "Pick a school, network, or announcer"
BUTTERFLY_HINT = "Pick exactly two schools or two announcers"
ONE_SCHOOL = "?school=northfield"
TWO_SUBJECTS = "?school=northfield&networks=net-a"


def _attr(page: Page, selector: str, name: str) -> str | None:
    return page.locator(selector).get_attribute(name)


def _state(page: Page) -> dict[str, Any]:
    return page.evaluate("() => window.__testHooks.getState()")


def _hint(page: Page) -> str:
    return page.locator("#tab-hint").inner_text()


def _box(page: Page, selector: str) -> dict[str, float]:
    box = page.locator(selector).bounding_box()
    assert box is not None, selector
    return box


def _is_concealed(page: Page, selector: str) -> bool:
    return page.evaluate(
        "(s) => getComputedStyle(document.querySelector(s)).visibility === 'hidden'", selector
    )


def test_default_page_has_three_tabs_with_scatter_selected(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    labels = guarded_page.locator("#chart-tabs [role=tab]").all_inner_texts()
    assert labels == ["Scatter", "Bars", "Butterfly"]
    assert _attr(guarded_page, "#tab-scatter", "aria-selected") == "true"
    assert _attr(guarded_page, "#tab-scatter", "tabindex") == "0"
    assert _attr(guarded_page, "#tab-scatter", "aria-disabled") is None
    for tab, hint in (("#tab-bars", BARS_HINT), ("#tab-butterfly", BUTTERFLY_HINT)):
        assert _attr(guarded_page, tab, "aria-disabled") == "true"
        assert _attr(guarded_page, tab, "title") == hint
        assert _attr(guarded_page, tab, "aria-selected") == "false"
    assert _hint(guarded_page) == ""


def test_one_school_enables_bars_only(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, ONE_SCHOOL)
    assert _attr(guarded_page, "#tab-bars", "aria-disabled") is None
    assert _attr(guarded_page, "#tab-butterfly", "aria-disabled") == "true"


def test_clicking_a_disabled_tab_shows_its_hint_without_switching(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, ONE_SCHOOL)
    guarded_page.locator("#tab-butterfly").click(force=True)
    assert _state(guarded_page)["view"] == "scatter"
    assert "view=" not in guarded_page.evaluate("() => location.search")
    assert guarded_page.evaluate("() => document.activeElement.id") == "tab-butterfly"
    assert _hint(guarded_page) == BUTTERFLY_HINT
    guarded_page.keyboard.press("Escape")
    assert _hint(guarded_page) == ""


def test_hover_and_blur_deliver_and_clear_the_hint(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    guarded_page.locator("#tab-bars").hover()
    assert _hint(guarded_page) == BARS_HINT
    guarded_page.mouse.move(600, 600)
    assert _hint(guarded_page) == ""

    guarded_page.locator("#tab-scatter").focus()
    guarded_page.keyboard.press("ArrowRight")
    assert _hint(guarded_page) == BARS_HINT
    guarded_page.locator("#tab-scatter").focus()
    assert _hint(guarded_page) == ""


def test_any_state_change_clears_the_hint(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    guarded_page.locator("#tab-bars").click(force=True)
    assert _hint(guarded_page) == BARS_HINT
    guarded_page.evaluate("() => window.__testHooks.setState({ axis: 'excitement' })")
    assert _hint(guarded_page) == ""


def test_clicking_an_enabled_tab_selects_it_and_updates_the_url(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, ONE_SCHOOL)
    guarded_page.locator("#tab-bars").click()
    assert _state(guarded_page)["view"] == "bars"
    assert "view=bars" in guarded_page.evaluate("() => location.search")
    assert _attr(guarded_page, "#tab-bars", "aria-selected") == "true"
    assert _attr(guarded_page, "#tab-bars", "tabindex") == "0"
    assert _attr(guarded_page, "#tab-scatter", "tabindex") == "-1"
    assert guarded_page.evaluate("() => document.activeElement.id") == "tab-bars"


def test_keyboard_navigation_is_roving_with_manual_activation(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, ONE_SCHOOL)
    active = "() => document.activeElement.id"
    guarded_page.locator("#tab-scatter").focus()
    guarded_page.keyboard.press("ArrowRight")
    assert guarded_page.evaluate(active) == "tab-bars"
    assert _state(guarded_page)["view"] == "scatter"
    guarded_page.keyboard.press("End")
    assert guarded_page.evaluate(active) == "tab-butterfly"
    guarded_page.keyboard.press("Home")
    assert guarded_page.evaluate(active) == "tab-scatter"
    guarded_page.keyboard.press("ArrowLeft")
    assert guarded_page.evaluate(active) == "tab-butterfly"
    guarded_page.keyboard.press("ArrowLeft")
    assert guarded_page.evaluate(active) == "tab-bars"
    guarded_page.keyboard.press("Enter")
    assert _state(guarded_page)["view"] == "bars"
    assert guarded_page.evaluate(active) == "tab-bars"
    guarded_page.keyboard.press("Home")
    guarded_page.keyboard.press("Space")
    assert _state(guarded_page)["view"] == "scatter"


def test_bar_controls_replace_the_axis_toggle_without_shifting_layout(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, ONE_SCHOOL)
    assert _is_concealed(guarded_page, "#bar-controls")
    assert not _is_concealed(guarded_page, "#axis-toggle")
    axis_before = _box(guarded_page, "#axis-toggle")

    guarded_page.locator("#tab-bars").click()
    assert not _is_concealed(guarded_page, "#bar-controls")
    assert _is_concealed(guarded_page, "#axis-toggle")
    assert _box(guarded_page, "#axis-toggle")["height"] == axis_before["height"]
    assert _is_concealed(guarded_page, "#group-by")

    guarded_page.locator('#bar-style-toggle button[data-bars="stacked"]').click()
    assert "bars=stacked" in guarded_page.evaluate("() => location.search")
    assert _attr(guarded_page, '#bar-style-toggle button[data-bars="stacked"]', "aria-pressed") == (
        "true"
    )
    assert _attr(guarded_page, '#bar-style-toggle button[data-bars="simple"]', "aria-pressed") == (
        "false"
    )


def test_group_by_shows_with_two_subjects_and_drives_the_url(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, TWO_SUBJECTS + "&view=bars")
    assert not _is_concealed(guarded_page, "#group-by")
    announcers = '#group-by-toggle button[data-group="announcers"]'
    assert _attr(guarded_page, announcers, "aria-pressed") == "true"
    guarded_page.locator('#group-by-toggle button[data-group="teams"]').click()
    assert "group=teams" in guarded_page.evaluate("() => location.search")
    guarded_page.locator(announcers).click()
    assert "group=" not in guarded_page.evaluate("() => location.search")


def test_scatter_tab_shows_axis_toggle_and_conceals_bar_controls(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    assert not _is_concealed(guarded_page, "#axis-toggle")
    assert _is_concealed(guarded_page, "#bar-controls")
