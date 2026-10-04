"""The desktop toolbar is a grid of equal cells, so no filter label re-wraps it.

SITE-20 (toggling a filter moves nothing) and 04.9 D-21: above 640px the toolbar's
row count depends only on the viewport width. Long labels truncate with an ellipsis
inside their cell, and every trigger carries its full label in `title` and
`aria-label`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

# One longest-label patch per current filter, and the reset values of the keys it sets.
WORST_CASE_PATCHES: list[tuple[str, dict[str, Any]]] = [
    ("seasons", {"seasons": [2021, 2025]}),
    ("networks", {"networks": ["net-a", "net-b"]}),
    ("slot-single", {"slots": ["afternoon"]}),
    ("slot-multi", {"slots": ["noon", "afternoon", "prime"]}),
    ("role", {"role": "analyst"}),
    ("conference", {"conferences": ["FBS Independents"]}),
    ("school-h2h", {"school": ["northfield", "lakeview"], "h2h": True}),
    ("school-one", {"school": ["cedar-hollow"], "h2h": False}),
    ("postseason", {"postseason": "exclude"}),
    ("people", {"people": ["dale-harlow", "dale-harlow-jr", "casey-lund"]}),
]
RESET: dict[str, Any] = {
    "seasons": None,
    "networks": None,
    "slots": None,
    "role": None,
    "conferences": [],
    "school": [],
    "h2h": False,
    "postseason": "all",
    "people": [],
}

_WAIT_TWO_FRAMES = "() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"


def _geometry(page: Page) -> dict[str, float]:
    page.evaluate(_WAIT_TWO_FRAMES)
    result: dict[str, float] = page.evaluate(
        """() => ({
          toolbarHeight: document.getElementById('toolbar').getBoundingClientRect().height,
          chartTop: document.getElementById('chart-area').getBoundingClientRect().top,
        })"""
    )
    return result


def _set(page: Page, patch: dict[str, Any]) -> None:
    page.evaluate("(patch) => window.__testHooks.setState(patch)", patch)


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide"], indirect=True)
@pytest.mark.parametrize("width", [800, 900, 1024])
def test_toolbar_height_and_chart_top_never_change(
    guarded_page: Page, open_app: Callable[[Page, str], None], width: int
) -> None:
    guarded_page.set_viewport_size({"width": width, "height": 900})
    open_app(guarded_page)
    baseline = _geometry(guarded_page)

    for name, patch in WORST_CASE_PATCHES:
        _set(guarded_page, patch)
        now = _geometry(guarded_page)
        assert now["toolbarHeight"] == baseline["toolbarHeight"], name
        if name != "people":  # selected people add their own chip row above the chart
            assert now["chartTop"] == baseline["chartTop"], name
        _set(guarded_page, RESET)

    combined: dict[str, Any] = {}
    for name, patch in WORST_CASE_PATCHES:
        if name not in ("school-one", "people"):
            combined.update(patch)
    _set(guarded_page, combined)
    assert _geometry(guarded_page) == baseline, "all together"
    _set(guarded_page, WORST_CASE_PATCHES[-1][1])
    assert _geometry(guarded_page)["toolbarHeight"] == baseline["toolbarHeight"]


def test_triggers_carry_full_label_in_title_and_aria_label(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    guarded_page.set_viewport_size({"width": 1024, "height": 900})
    open_app(guarded_page, "?seasons=2021-2025&school=northfield,lakeview&h2h=1")
    for selector, label in (
        ("#trigger-seasons", "Seasons 2021–2025"),  # noqa: RUF001
        ("#trigger-school", "School: Northfield vs Lakeview"),
        ("#trigger-role", "Role"),
    ):
        trigger = guarded_page.locator(selector)
        assert trigger.get_attribute("title") == label
        assert trigger.get_attribute("aria-label") == label


@pytest.mark.parametrize("width", [800, 900, 1024, 1280])
def test_rest_labels_do_not_truncate(
    guarded_page: Page, open_app: Callable[[Page, str], None], width: int
) -> None:
    guarded_page.set_viewport_size({"width": width, "height": 900})
    open_app(guarded_page)
    truncated = guarded_page.evaluate(
        """() => [...document.querySelectorAll('#toolbar > button')]
          .filter((b) => b.offsetParent !== null && b.scrollWidth > b.clientWidth)
          .map((b) => b.textContent)"""
    )
    assert truncated == []


def test_grid_has_room_for_ten_cells(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Nine filters plus Clear all fit one row at 1280px. Plan 04.9-08 adds the tenth
    cell (Game) and re-asserts the row count with it present."""
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    open_app(guarded_page)
    columns = guarded_page.evaluate(
        "() => getComputedStyle(document.getElementById('toolbar'))"
        ".gridTemplateColumns.split(' ').length"
    )
    assert columns >= 10
    tops = guarded_page.evaluate(
        """() => [...document.querySelectorAll('#toolbar > button')]
          .filter((b) => b.offsetParent !== null)
          .map((b) => Math.round(b.offsetTop))"""
    )
    assert len(set(tops)) == 1
