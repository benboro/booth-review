"""SITE-67 / SITE-68 (04.17 D-09..D-15): the fixed caps module and the derived arrays.

Synthetic fixture and in-test mutations only. The fixture's largest excitement is 9.9,
below the cap, so the pinned cases mutate a deep copy of the payload (23.2 is synthetic).
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_WAIT_TWO_FRAMES = "() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"

# Merged index of the mutated game: rated, crewed by kris-venn and sam-delgado.
_PINNED = 6
_PINNED_VALUE = 23.2


def _mutated(fixture_raw: dict[str, Any]) -> dict[str, Any]:
    """Fixture copy with one excitement above the cap and extreme scores."""
    raw = copy.deepcopy(fixture_raw)
    tel = raw["telecasts"]
    tel["excitement"][_PINNED] = _PINNED_VALUE
    tel["home_points"][0], tel["away_points"][0] = 100, 50
    tel["home_points"][1], tel["away_points"][1] = 90, 10
    unrated = raw["telecasts_unrated"]
    unrated["home_points"][0] = None
    return raw


def _load(page: Page, site_url: str) -> None:
    page.goto(f"{site_url}/index.html")
    page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")


def _open_mutated(
    request: pytest.FixtureRequest,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
    size: tuple[int, int],
    query: str,
) -> Page:
    page: Page = request.getfixturevalue("guarded_page" if size[0] > 600 else "mobile_page")
    raw = _mutated(fixture_raw)
    page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    page.set_viewport_size({"width": size[0], "height": size[1]})
    open_app(page, query)
    page.evaluate(_WAIT_TWO_FRAMES)
    page.wait_for_timeout(150)
    return page


_CAPS_JS = """
async () => {
  const C = await import('./modules/caps.js');
  return {
    cap: C.EXCITEMENT_CAP,
    measures: JSON.parse(JSON.stringify(C.Y_MEASURES)),
    frozen: [C.Y_MEASURES, ...Object.values(C.Y_MEASURES)].map(Object.isFrozen),
    exCapIsConst: C.Y_MEASURES.excitement.cap === C.EXCITEMENT_CAP,
    pin: [C.pin(23.2, 12), C.pin(11.9, 12), C.pin(null, 12), C.pin(12, 12), C.pin(undefined, 12)],
    ex: C.cappedTicks(0.0037, 12, 2, 12, true),
    pts: C.cappedTicks(0, 120, 20, 120, true),
    mar: C.cappedTicks(0, 70, 10, 70, true),
    exNo: C.cappedTicks(3.0, 9.9, 2, 12, false),
    ptsNo: C.cappedTicks(0, 120, 20, 120, false),
  };
}
"""


def test_caps_module_constants_and_helpers(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    r = guarded_page.evaluate(_CAPS_JS)
    assert r["cap"] == 12
    assert all(r["frozen"])
    assert r["exCapIsConst"]
    assert r["measures"] == {
        "excitement": {"cap": 12, "step": 2, "title": "Excitement index (CFBD)"},
        "points": {"cap": 120, "step": 20, "title": "Total points (both teams)"},
        "margin": {"cap": 70, "step": 10, "title": "Margin of victory (points)"},
    }
    assert r["pin"] == [12, 11.9, None, 12, None]
    assert r["ex"] == {"tickvals": [2, 4, 6, 8, 10, 12], "ticktext": ["2", "4", "6", "8", "10", "12+"]}
    assert r["pts"]["tickvals"] == [0, 20, 40, 60, 80, 100, 120]
    assert r["pts"]["ticktext"][-1] == "120+"
    assert r["mar"]["tickvals"] == [0, 10, 20, 30, 40, 50, 60, 70]
    assert r["mar"]["ticktext"][-1] == "70+"
    assert r["exNo"] == {"tickvals": [4, 6, 8], "ticktext": ["4", "6", "8"]}
    assert r["ptsNo"]["ticktext"][-1] == "120"
    assert not any("+" in s for s in r["ptsNo"]["ticktext"] + r["exNo"]["ticktext"])


_DERIVED_JS = """
() => {
  const d = window.__testHooks.data;
  const t = d.t;
  return {
    n: d.n,
    total: Array.from(d.total), margin: Array.from(d.margin),
    home: Array.from(t.home_points), away: Array.from(t.away_points),
    tKeys: Object.keys(t),
    xe: d.xRange.excitement, pinned: d.pinned, maxOf: d.maxOf,
    exc: Array.from(t.excitement),
  };
}
"""


def test_derived_total_and_margin_on_fixture(guarded_page: Page, site_url: str) -> None:
    _load(guarded_page, site_url)
    r = guarded_page.evaluate(_DERIVED_JS)
    assert len(r["total"]) == len(r["margin"]) == r["n"]
    for i in range(r["n"]):
        h, a = r["home"][i], r["away"][i]
        if h is None or a is None:
            assert r["total"][i] is None
            assert r["margin"][i] is None
        else:
            assert r["total"][i] == h + a
            assert r["margin"][i] == abs(h - a)
    assert "total" not in r["tKeys"]
    assert "margin" not in r["tKeys"]
    assert r["xe"] == [3.0, 9.9]
    assert r["pinned"] == {"excitement": False, "points": False, "margin": False}
    assert r["maxOf"]["points"] == max(v for v in r["total"] if v is not None)
    assert r["maxOf"]["margin"] == max(v for v in r["margin"] if v is not None)


def test_derived_and_pinned_on_mutated_payload(
    guarded_page: Page, open_app: Callable[[Page, str], None], fixture_raw: dict[str, Any]
) -> None:
    raw = _mutated(fixture_raw)
    guarded_page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    open_app(guarded_page, "")
    r = guarded_page.evaluate(_DERIVED_JS)
    assert r["xe"][1] == 12
    assert r["xe"][0] == 3.0
    assert r["pinned"] == {"excitement": True, "points": True, "margin": True}
    assert r["maxOf"]["excitement"] == _PINNED_VALUE
    assert r["exc"][_PINNED] == _PINNED_VALUE
    assert r["total"][0] == 150
    assert r["margin"][0] == 50
    assert r["total"][1] == 100
    assert r["margin"][1] == 80
    assert r["maxOf"]["points"] == 150
    assert r["maxOf"]["margin"] == 80
    nr = len(raw["telecasts"]["season"])
    assert r["total"][nr] is None
    assert r["margin"][nr] is None
