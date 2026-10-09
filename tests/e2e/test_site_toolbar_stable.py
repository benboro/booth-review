"""The desktop toolbar is a grid of equal cells, so no filter label re-wraps it.

SITE-20 (toggling a filter moves nothing) and 04.9 D-21: above 640px the toolbar's
row count depends only on the viewport width and the visitor's font. toolbar-fit.js
sizes the cells from the widest resting label in that font, so resting labels never
truncate; long active summaries truncate with an ellipsis inside their cell, and
every trigger carries its full label in `title` and `aria-label`.
"""

from __future__ import annotations

import copy
import json
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
    ("game-round", {"game": "cfp-national-championship"}),
    ("game-rivalry", {"game": "bridge-game"}),
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
    "game": None,
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


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide"], indirect=True)
@pytest.mark.parametrize("width", [800, 900, 1024])
def test_date_axis_never_moves_toolbar_or_chart(
    guarded_page: Page, open_app: Callable[[Page, str], None], width: int
) -> None:
    guarded_page.set_viewport_size({"width": width, "height": 900})
    open_app(guarded_page)
    baseline = _geometry(guarded_page)
    _set(guarded_page, {"axis": "date"})
    assert _geometry(guarded_page) == baseline
    _set(guarded_page, {"axis": "date", "seasons": [2021, 2025]})
    assert _geometry(guarded_page) == baseline
    _set(guarded_page, {"axis": "spread", "seasons": None})
    assert _geometry(guarded_page) == baseline


def test_date_axis_never_moves_toolbar_or_chart_on_phone(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    guarded_page.set_viewport_size({"width": 360, "height": 800})
    open_app(guarded_page)
    baseline = _geometry(guarded_page)
    _set(guarded_page, {"axis": "date"})
    assert _geometry(guarded_page) == baseline
    tops: list[int] = guarded_page.evaluate(
        "() => [...document.querySelectorAll('#axis-toggle button')]"
        ".map((b) => Math.round(b.getBoundingClientRect().top))"
    )
    assert len(tops) == 3
    assert len(set(tops)) == 1
    _set(guarded_page, {"axis": "spread"})
    assert _geometry(guarded_page) == baseline


@pytest.mark.parametrize("width", [800, 900, 1024])
def test_long_rivalry_name_never_changes_toolbar_height(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
    width: int,
) -> None:
    mutated = copy.deepcopy(fixture_raw)
    long_name = "The Extraordinarily Long Rivalry Game"  # 37 characters
    mutated["lookups"]["rivalries"][0]["name"] = long_name + "!!!"
    mutated["lookups"]["rivalries"][0]["slug"] = "long-rivalry"
    body = json.dumps(mutated)
    guarded_page.route(
        "**/site-data.json*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=body),
    )
    guarded_page.set_viewport_size({"width": width, "height": 900})
    open_app(guarded_page)
    baseline = _geometry(guarded_page)
    _set(guarded_page, {"game": "long-rivalry"})
    assert guarded_page.locator("#trigger-game").inner_text().startswith("Game: The Extra")
    assert _geometry(guarded_page) == baseline


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


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide"], indirect=True)
@pytest.mark.parametrize("width", [800, 900, 1024, 1280])
def test_rest_labels_do_not_truncate(
    guarded_page: Page, open_app: Callable[[Page, str], None], width: int
) -> None:
    guarded_page.set_viewport_size({"width": width, "height": 900})
    open_app(guarded_page)
    assert _truncated(guarded_page) == []


def _truncated(page: Page) -> list[str]:
    """Visible toolbar buttons whose label does not fit. `scrollWidth` rounds to
    whole pixels and missed a 0.24px clip that showed "Bowls/Playoff…", so each
    button is also compared, to the sub-pixel, with its own `max-content` width
    (measured and restored in one task, so nothing repaints)."""
    result: list[str] = page.evaluate(
        """() => [...document.querySelectorAll('#toolbar > button')]
          .filter((b) => b.offsetParent !== null)
          .filter((b) => {
            if (b.scrollWidth > b.clientWidth) return true;
            const width = b.getBoundingClientRect().width;
            b.style.width = 'max-content';
            const needed = b.getBoundingClientRect().width;
            b.style.width = '';
            return needed > width + 0.01;
          })
          .map((b) => b.textContent)"""
    )
    return result


_VISIBLE_TOPS_JS = """() => [...document.querySelectorAll('#toolbar > button')]
  .filter((b) => b.offsetParent !== null).map((b) => Math.round(b.offsetTop))"""

_CELL_MIN_JS = (
    "() => document.getElementById('toolbar').style.getPropertyValue('--toolbar-cell-min')"
)


@pytest.mark.parametrize("font_setting", ["narrow"], indirect=True)
def test_grid_has_room_for_ten_cells(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """With a font narrow enough for the 116px floor, all ten cells (nine filters
    plus Clear all) fit one row at 1280px, and picking a long game keeps it there."""
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    open_app(guarded_page)
    assert int(guarded_page.evaluate(_CELL_MIN_JS).removesuffix("px")) <= 116
    columns = guarded_page.evaluate(
        "() => getComputedStyle(document.getElementById('toolbar'))"
        ".gridTemplateColumns.split(' ').length"
    )
    assert columns >= 10
    tops: list[int] = guarded_page.evaluate(_VISIBLE_TOPS_JS)
    assert len(tops) == 10
    assert len(set(tops)) == 1
    _set(guarded_page, {"game": "cfp-national-championship"})
    assert len(set(guarded_page.evaluate(_VISIBLE_TOPS_JS))) == 1
    assert _truncated(guarded_page) == ["Game: CFP National Championship"]


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide", "narrow"], indirect=True)
@pytest.mark.parametrize("width", [800, 900, 1024, 1280])
def test_toolbar_rows_with_game_button(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    width: int,
    font_setting: str,
) -> None:
    """Ten visible cells, two rows at 800, 900, and 1024px on every font. At 1280px
    the row count follows the font: one row for a narrow font, two for DejaVu Sans
    (whose resting "Clear all filters" needs a wider cell than ten fit), and either
    for the machine's own default. Whatever it is, toggling filters never changes it,
    and no resting label truncates."""
    guarded_page.set_viewport_size({"width": width, "height": 900})
    open_app(guarded_page)
    tops: list[int] = guarded_page.evaluate(_VISIBLE_TOPS_JS)
    assert len(tops) == 10
    rows = len(set(tops))
    if width < 1280:
        assert rows == 2
    elif font_setting == "narrow":
        assert rows == 1
    elif font_setting in ("dejavu", "wide"):
        assert rows == 2
    else:
        assert rows in (1, 2)
    assert _truncated(guarded_page) == []

    cell_min = guarded_page.evaluate(_CELL_MIN_JS)
    for _name, patch in WORST_CASE_PATCHES:
        _set(guarded_page, patch)
        assert len(set(guarded_page.evaluate(_VISIBLE_TOPS_JS))) == rows
        _set(guarded_page, RESET)
    assert guarded_page.evaluate(_CELL_MIN_JS) == cell_min
    assert len(set(guarded_page.evaluate(_VISIBLE_TOPS_JS))) == rows


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide"], indirect=True)
def test_cell_width_comes_from_resting_labels_only(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """The cell width is measured from the resting labels, never a live summary: a
    page opened with long active labels gets the same cells as a plain one, and the
    resting labels fit once those filters are cleared."""
    guarded_page.set_viewport_size({"width": 1024, "height": 900})
    open_app(guarded_page)
    plain = guarded_page.evaluate(_CELL_MIN_JS)
    assert plain.endswith("px")

    open_app(guarded_page, "?game=cfp-national-championship&postseason=exclude")
    assert guarded_page.locator("#trigger-game").inner_text().startswith("Game: CFP")
    assert guarded_page.evaluate(_CELL_MIN_JS) == plain
    _set(guarded_page, RESET)
    assert _truncated(guarded_page) == []


_PANEL_JS = """() => {
  const r = document.getElementById('chart-panel').getBoundingClientRect();
  return {
    toolbar: document.getElementById('toolbar').getBoundingClientRect().height,
    top: r.top,
    height: r.height,
  };
}"""


def _panel_geometry(page: Page) -> dict[str, float]:
    page.evaluate(_WAIT_TWO_FRAMES)
    result: dict[str, float] = page.evaluate(_PANEL_JS)
    return result


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide"], indirect=True)
@pytest.mark.parametrize("width", [1280, 360])
def test_scatter_and_map_share_toolbar_and_chart_panel_geometry(
    guarded_page: Page, open_app: Callable[[Page, str], None], width: int
) -> None:
    """04.18 D-09: switching Scatter <-> Map moves neither the controls row nor the
    chart panel's top, and the panel stays 520px tall (the Map's fixed height)."""
    guarded_page.set_viewport_size({"width": width, "height": 900})
    open_app(guarded_page)
    scatter = _panel_geometry(guarded_page)
    before: int = guarded_page.evaluate("() => window.__testHooks.mapRenders")
    _set(guarded_page, {"view": "map"})
    guarded_page.wait_for_function("(n) => window.__testHooks.mapRenders > n", arg=before)
    on_map = _panel_geometry(guarded_page)
    assert on_map["toolbar"] == scatter["toolbar"]
    assert on_map["top"] == scatter["top"]
    assert on_map["height"] == scatter["height"] == 520
    _set(guarded_page, {"view": "scatter"})
    assert _panel_geometry(guarded_page) == scatter


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide", "narrow"], indirect=True)
def test_four_chart_tabs_fit_at_340px(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """04.18 D-09: Scatter, Bars, Butterfly and Map fit one row in 340px, no page overflow."""
    guarded_page.set_viewport_size({"width": 340, "height": 800})
    open_app(guarded_page, "?view=map")
    fit: dict[str, Any] = guarded_page.evaluate(
        """() => {
          const tabs = [...document.querySelectorAll('#chart-tabs .chart-tab')];
          const slot = document.getElementById('chart-tabs').getBoundingClientRect();
          return {
            n: tabs.length,
            tops: [...new Set(tabs.map((t) => Math.round(t.getBoundingClientRect().top)))],
            clipped: tabs.filter((t) => t.scrollWidth > t.clientWidth).length,
            right: Math.max(...tabs.map((t) => t.getBoundingClientRect().right)),
            slotRight: slot.right,
            scrollWidth: document.documentElement.scrollWidth,
          };
        }"""
    )
    assert fit["n"] == 4
    assert len(fit["tops"]) == 1
    assert fit["clipped"] == 0
    assert fit["right"] <= fit["slotRight"] + 0.5
    assert fit["scrollWidth"] <= 340
