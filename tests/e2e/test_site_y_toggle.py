"""The Y-axis control (04.15 D-09..D-12): markup, controls-row layout on every tab,
the Excitement swap, URL persistence, caption, band copy, tooltip, and the
summary/table/passing set staying identical in both Y modes (D-18, D-19).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

OpenApp = Callable[[Page, str], None]


def test_y_toggle_markup_and_default(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, "")
    buttons = guarded_page.locator("#y-toggle button")
    assert buttons.count() == 2
    assert [buttons.nth(i).inner_text() for i in range(2)] == ["Viewers", "Excitement"]
    assert [buttons.nth(i).get_attribute("data-y") for i in range(2)] == [
        "viewers",
        "excitement",
    ]
    assert [buttons.nth(i).get_attribute("aria-pressed") for i in range(2)] == [
        "true",
        "false",
    ]
    group = guarded_page.locator("#y-toggle")
    assert group.get_attribute("role") == "group"
    assert group.get_attribute("aria-label") == "Y-axis measure"
    captions = guarded_page.locator("#scatter-controls .axis-caption")
    assert [captions.nth(i).inner_text() for i in range(captions.count())] == [
        "X axis",
        "Y axis",
    ]


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide"], indirect=True)
@pytest.mark.parametrize("width", [360, 390, 641, 700, 800, 1280])
def test_controls_row_height_is_equal_on_every_tab(
    guarded_page: Page, open_app: OpenApp, width: int
) -> None:
    page = guarded_page
    page.set_viewport_size({"width": width, "height": 900})
    open_app(page, "?school=northfield,lakeview")
    height = "document.getElementById('chart-controls').getBoundingClientRect().height"
    scatter = page.evaluate(height)
    overflow = page.evaluate(
        """() => ['#axis-toggle', '#y-toggle'].every((s) => {
            const r = document.querySelector(s).getBoundingClientRect();
            return r.left >= 0 && r.right <= window.innerWidth;
        })"""
    )
    assert overflow
    page.locator("#tab-bars").click()
    page.wait_for_selector("#bars-title")
    assert abs(page.evaluate(height) - scatter) <= 1
    page.locator("#tab-butterfly").click()
    assert abs(page.evaluate(height) - scatter) <= 1
