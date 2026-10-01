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


# --- Task 3: chart panel branching ----------------------------------------


def _visible(page: Page, selector: str) -> bool:
    return page.locator(selector).is_visible()


def test_stale_bars_tab_stays_selected_and_shows_the_note(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?view=bars")
    assert _attr(guarded_page, "#tab-bars", "aria-selected") == "true"
    assert _attr(guarded_page, "#tab-bars", "aria-disabled") == "true"
    assert not _visible(guarded_page, "#chart")
    assert _visible(guarded_page, "#bars-panel")
    assert _visible(guarded_page, "#bars-note")
    assert guarded_page.locator("#bars-note .season-empty-title").inner_text() == BARS_HINT
    assert guarded_page.locator("#bars-note .season-empty-hint").inner_text() == (
        "Pick a school, narrow Networks, or select an announcer to see counts."
    )
    for selector in ("#bars-title", "#bars-footer", "#bars-captions", "#bars-data"):
        assert not _visible(guarded_page, selector), selector
    assert "view=bars" in guarded_page.evaluate("() => location.search")
    assert _box(guarded_page, "#bars-chart-box")["height"] >= 520


def test_restoring_the_filter_brings_the_bars_panel_back(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?view=bars")
    guarded_page.evaluate("() => window.__testHooks.setState({ school: ['northfield'] })")
    assert not _visible(guarded_page, "#bars-note")
    assert guarded_page.locator("#bars-title").evaluate("e => !e.hidden")
    assert guarded_page.locator("#bars-footer").evaluate("e => !e.hidden")
    assert guarded_page.locator("#bars-captions").evaluate("e => !e.hidden")
    assert guarded_page.locator("#bars-data").evaluate("e => !e.hidden")
    guarded_page.evaluate("() => window.__testHooks.setState({ school: [] })")
    assert _visible(guarded_page, "#bars-note")
    assert _attr(guarded_page, "#tab-bars", "aria-selected") == "true"


def test_stale_butterfly_copy(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    open_app(guarded_page, "?view=butterfly&school=northfield")
    assert guarded_page.locator("#bars-note .season-empty-title").inner_text() == BUTTERFLY_HINT
    assert guarded_page.locator("#bars-note .season-empty-hint").inner_text() == (
        "Select two schools or two announcers to compare them."
    )


def test_tab_switching_never_shifts_the_chart_chrome(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?school=northfield,lakeview")
    before = {s: _box(guarded_page, s) for s in ("#legend-chips", "#chart-controls", "#tab-hint")}
    for view in ("bars", "butterfly", "scatter"):
        guarded_page.locator(f"#tab-{view}").click()
        assert _state(guarded_page)["view"] == view
        for selector, box in before.items():
            now = _box(guarded_page, selector)
            assert now["y"] == box["y"], (view, selector)
            assert now["height"] == box["height"], (view, selector)
    guarded_page.locator("#tab-bars").click()
    assert _box(guarded_page, "#bars-chart-box")["height"] >= 520


def test_scatter_works_after_first_loading_on_a_bar_tab(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, ONE_SCHOOL + "&view=bars")
    guarded_page.locator("#tab-scatter").click()
    assert _visible(guarded_page, "#chart")
    guarded_page.wait_for_function("() => document.querySelector('#chart .main-svg')")
    widths = guarded_page.evaluate(
        "() => ({svg: document.querySelector('#chart .main-svg').getBoundingClientRect().width,"
        " box: document.getElementById('chart').clientWidth})"
    )
    assert abs(widths["svg"] - widths["box"]) <= 1

    guarded_page.locator("#chart").scroll_into_view_if_needed()
    point = guarded_page.evaluate(
        """() => {
          const gd = document.getElementById('chart');
          const layout = gd._fullLayout;
          const rect = gd.getBoundingClientRect();
          for (const t of gd.data) {
            if (!t.customdata) continue;
            return {
              x: rect.left + layout._size.l + layout.xaxis.d2p(t.x[0]),
              y: rect.top + layout._size.t + layout.yaxis.d2p(t.y[0]),
            };
          }
          return null;
        }"""
    )
    assert point is not None
    guarded_page.mouse.move(5, 5)
    guarded_page.mouse.move(point["x"], point["y"])
    guarded_page.wait_for_selector("#chart-tooltip:not([hidden])", timeout=5000)


def test_scatter_only_captions_hide_on_bar_tabs(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, ONE_SCHOOL + "&axis=excitement")
    assert _visible(guarded_page, "#excitement-caption")
    assert _visible(guarded_page, "#era-note")
    guarded_page.locator("#tab-bars").click()
    for selector in ("#excitement-caption", "#era-note", "#shape-legend"):
        assert not _visible(guarded_page, selector), selector
    assert "axis=excitement" in guarded_page.evaluate("() => location.search")
    guarded_page.locator("#tab-scatter").click()
    assert _visible(guarded_page, "#excitement-caption")
    assert _visible(guarded_page, "#era-note")


def test_resizing_on_the_bars_tab_raises_no_errors(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    errors: list[str] = []
    guarded_page.on("pageerror", lambda exc: errors.append(str(exc)))
    guarded_page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    open_app(guarded_page, ONE_SCHOOL + "&view=bars")
    for width in (800, 1280):
        guarded_page.set_viewport_size({"width": width, "height": 800})
        guarded_page.wait_for_timeout(200)
    assert errors == []
