"""The desktop filter bar never moves when a filter is picked.

SITE-20 (toggling a filter moves nothing) and Phase 26 Round 3b: above 480px the bar is three
fixed-width groups of boxless entries, so its row count depends only on the viewport width
(the retired toolbar measuring script no longer measures it). A long pick truncates inside its
own entry, and every entry carries its full text in `title` and `aria-label`.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

import pytest
from layout_shift import layout_snapshot
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
    ("booth", {"booth": ["a", "b"]}),
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
    "booth": [],
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
    assert guarded_page.locator("#trigger-game .filter-value").inner_text().startswith("The Extra")
    assert _geometry(guarded_page) == baseline


def test_triggers_carry_full_label_in_title_and_aria_label(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    guarded_page.set_viewport_size({"width": 1024, "height": 900})
    open_app(guarded_page, "?seasons=2021-2025&school=northfield,lakeview&h2h=1")
    for selector, label in (
        ("#trigger-seasons", "Seasons: 2021–2025"),  # noqa: RUF001
        ("#trigger-school", "School: Northfield vs Lakeview"),
        ("#trigger-role", "Role"),
    ):
        trigger = guarded_page.locator(selector)
        assert trigger.get_attribute("title") == label
        assert trigger.get_attribute("aria-label") == label


_ENTRY_TOPS_JS = """() => [...document.querySelectorAll('#toolbar .fgroup-row .filter-trigger')]
  .filter((b) => b.offsetParent !== null).map((b) => Math.round(b.getBoundingClientRect().top))"""
_FILTER_CELLS = 10  # the bar holds ten CFB filter controls; Clear all lives in the selection row


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide", "narrow"], indirect=True)
@pytest.mark.parametrize("width", [800, 900, 1024, 1280])
def test_rows_and_snapshot_survive_every_worst_case_pick(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    width: int,
) -> None:
    """Ten visible entries; the row count is a function of width only (one from 1280px, two
    below), and no pick changes it, the bar's bottom, the tabs or any group's left edge."""
    guarded_page.set_viewport_size({"width": width, "height": 900})
    open_app(guarded_page)
    tops: list[int] = guarded_page.evaluate(_ENTRY_TOPS_JS)
    assert len(tops) == _FILTER_CELLS
    rows = len(set(tops))
    assert rows == (1 if width >= 1280 else 2)
    baseline = layout_snapshot(guarded_page)
    for name, patch in WORST_CASE_PATCHES:
        _set(guarded_page, patch)
        assert len(set(guarded_page.evaluate(_ENTRY_TOPS_JS))) == rows, name
        if name != "people":  # selected people add their own chip row above the chart
            assert layout_snapshot(guarded_page) == baseline, name
        _set(guarded_page, RESET)
    assert layout_snapshot(guarded_page) == baseline


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
    chart panel's top, and the panel stays 520px tall (the Map's fixed height).

    Phone width (v2.1 todo 2026-10-25-phone-map-blank-bands): the Map drops the chart
    tools row, whose concealed scatter controls and dead Reset zoom made a blank band
    above the map, and the map box follows the map's own aspect ratio with the key in
    flow under it. So on a phone the panel top moves up by exactly that row's height,
    the panel is shorter than 520px, and the filter row still never moves; switching
    back restores the Scatter geometry at every width."""
    guarded_page.set_viewport_size({"width": width, "height": 900})
    open_app(guarded_page)
    scatter = _panel_geometry(guarded_page)
    tools_height: float = guarded_page.evaluate(
        "() => document.getElementById('chart-tools').getBoundingClientRect().height"
    )
    before: int = guarded_page.evaluate("() => window.__testHooks.mapRenders")
    _set(guarded_page, {"view": "map"})
    guarded_page.wait_for_function("(n) => window.__testHooks.mapRenders > n", arg=before)
    on_map = _panel_geometry(guarded_page)
    assert on_map["toolbar"] == scatter["toolbar"]
    assert scatter["height"] == 520
    if width >= 1280:
        assert on_map["top"] == scatter["top"]
        assert on_map["height"] == 520
    else:
        # The panel moves up by the dropped row plus the module's row gap under it.
        shift = scatter["top"] - on_map["top"]
        assert tools_height > 0
        assert tools_height <= shift <= tools_height + 16, (shift, tools_height)
        assert 0 < on_map["height"] < 520
    _set(guarded_page, {"view": "scatter"})
    assert _panel_geometry(guarded_page) == scatter


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide", "narrow"], indirect=True)
def test_six_chart_tabs_fit_at_340px(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """04.18 D-09, Phase 18: six tabs share one row at 340px (it scrolls sideways), no clipping."""
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
    assert fit["n"] == 6
    assert len(fit["tops"]) == 1
    assert fit["clipped"] == 0
    # Phase 18: six tabs do not fit 340px side by side, so the row scrolls sideways inside its
    # own box; the page itself never overflows.
    assert fit["scrollWidth"] <= 340


_DOTS_RECT_JS = """() => {
  const el = document.getElementById('dots-toggle');
  const r = el.getBoundingClientRect();
  const lr = document.getElementById('legend-row').getBoundingClientRect();
  return {x: r.x, y: r.y - lr.y, w: r.width, h: r.height, vis: getComputedStyle(el).visibility,
          legendH: document.getElementById('legend-row').getBoundingClientRect().height};
}"""


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide"], indirect=True)
@pytest.mark.parametrize("width", [1280, 360])
def test_dots_toggle_conceals_without_layout_shift(
    guarded_page: Page, open_app: Callable[[Page, str], None], width: int
) -> None:
    """Phase 11 D-09: the Fade/Hide switch is concealed (not hidden) off the scatter, so
    the legend row and the switch's own box never move between tabs."""
    guarded_page.set_viewport_size({"width": width, "height": 900})
    open_app(guarded_page)
    off_map = guarded_page.evaluate(_DOTS_RECT_JS)
    assert off_map["vis"] == "visible"
    before: int = guarded_page.evaluate("() => window.__testHooks.mapRenders")
    _set(guarded_page, {"view": "map"})
    guarded_page.wait_for_function("(n) => window.__testHooks.mapRenders > n", arg=before)
    guarded_page.evaluate(_WAIT_TWO_FRAMES)
    on_map = guarded_page.evaluate(_DOTS_RECT_JS)
    assert on_map["vis"] == "hidden"
    for key in ("x", "y", "w", "h", "legendH"):
        assert on_map[key] == off_map[key], key


@pytest.mark.parametrize("view", ["scatter", "bars", "butterfly", "map", "crews"])
def test_no_network_colors_switch_on_any_tab(
    guarded_page: Page, open_app: Callable[[Page, str], None], view: str
) -> None:
    """Phase 17.1 D-07: colours are always on, so no tab carries a Network colors control."""
    open_app(guarded_page, f"?view={view}")
    assert guarded_page.locator("#colors-toggle").count() == 0
    assert "Network colors" not in guarded_page.evaluate("() => document.body.innerText")
