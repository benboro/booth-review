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


_AXES_JS = """
() => {
  const gd = document.getElementById('chart');
  const fl = gd._fullLayout;
  const pts = [];
  gd.data.forEach((t) => {
    (t.customdata ?? []).forEach((cd, k) => {
      if (cd === %d) pts.push({ meta: String(t.meta), x: t.x[k], y: t.y[k], yaxis: t.yaxis ?? 'y',
        size: Array.isArray(t.marker.size) ? t.marker.size[k] : t.marker.size,
        symbol: Array.isArray(t.marker.symbol) ? t.marker.symbol[k] : t.marker.symbol });
    });
  });
  const ann = gd.layout.annotations?.[0]?.x;
  return {
    xRange: gd.layout.xaxis.range.slice(), xLen: fl.xaxis._length,
    xTickvals: gd.layout.xaxis.tickvals, xTicktext: gd.layout.xaxis.ticktext,
    yRange: gd.layout.yaxis.range.slice(), yLen: fl.yaxis._length,
    yTickvals: gd.layout.yaxis.tickvals, yTicktext: gd.layout.yaxis.ticktext,
    pts, sentinel: ann,
    t6: window.__testHooks.data.t.excitement[%d],
  };
}
""" % (_PINNED, _PINNED)

_SIZES = [(1280, 900), (360, 800)]


@pytest.mark.parametrize("size", _SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_pinned_game_on_x_excitement(
    request: pytest.FixtureRequest,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
    size: tuple[int, int],
) -> None:
    page = _open_mutated(request, open_app, fixture_raw, size, "?axis=excitement")
    r = page.evaluate(_AXES_JS)
    assert r["xTicktext"][-1] == "12+"
    assert r["xTickvals"][-1] == 12
    assert r["t6"] == _PINNED_VALUE
    main = [p for p in r["pts"] if p["yaxis"] != "y2"]
    assert main
    assert all(p["x"] == 12 for p in main)
    lo, hi = r["xRange"]
    assert hi > 12
    clearance = (hi - 12) * r["xLen"] / (hi - lo)
    assert clearance >= 10 - 1e-6, clearance
    # the N/A strip stays left of the data minimum
    assert r["sentinel"] < 3.0
    assert lo < r["sentinel"]


@pytest.mark.parametrize("size", _SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_pinned_game_on_y_excitement(
    request: pytest.FixtureRequest,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
    size: tuple[int, int],
) -> None:
    page = _open_mutated(request, open_app, fixture_raw, size, "?y=excitement")
    r = page.evaluate(_AXES_JS)
    assert r["yTicktext"] == ["4", "6", "8", "10", "12+"]
    assert r["yTickvals"] == [4, 6, 8, 10, 12]
    main = [p for p in r["pts"] if p["yaxis"] != "y2"]
    assert main
    assert all(p["y"] == 12 for p in main)
    lo, hi = r["yRange"]
    assert hi > 12
    clearance = (hi - 12) * r["yLen"] / (hi - lo)
    assert clearance >= 10 - 1e-6, clearance


@pytest.mark.parametrize("size", _SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_pinned_compare_highlight_sits_at_cap(
    request: pytest.FixtureRequest,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
    size: tuple[int, int],
) -> None:
    query = "?y=excitement&people=kris-venn,sam-delgado&mode=compare"
    page = _open_mutated(request, open_app, fixture_raw, size, query)
    r = page.evaluate(_AXES_JS)
    hl = [p for p in r["pts"] if p["meta"].startswith("highlight")]
    assert hl, r["pts"]
    assert all(p["y"] == 12 for p in hl)
    assert all(p["size"] > 0 for p in hl)
    lo, hi = r["yRange"]
    assert (hi - 12) * r["yLen"] / (hi - lo) >= 10 - 1e-6


def test_axes_agree_on_the_capped_range(
    guarded_page: Page, open_app: Callable[[Page, str], None], fixture_raw: dict[str, Any]
) -> None:
    raw = _mutated(fixture_raw)
    guarded_page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    open_app(guarded_page, "")
    got = guarded_page.evaluate(
        """async () => {
          const C = await import('./modules/chart.js');
          const d = window.__testHooks.data;
          const x = C.naBand(d, 'excitement', 1000);
          const y = C.measureYAxis(d, 'excitement', 600);
          return { xr: d.xRange.excitement, xt: x.tickvals, xx: x.ticktext,
                   yt: y.tickvals, yx: y.ticktext };
        }"""
    )
    assert got["xr"] == [3.0, 12]
    assert got["xt"] == got["yt"] == [4, 6, 8, 10, 12]
    assert got["xx"] == got["yx"] == ["4", "6", "8", "10", "12+"]


def test_true_value_survives_in_tooltip_hover_and_panel(
    guarded_page: Page, open_app: Callable[[Page, str], None], fixture_raw: dict[str, Any]
) -> None:
    raw = _mutated(fixture_raw)
    guarded_page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    open_app(guarded_page, "?axis=excitement")
    got = guarded_page.evaluate(
        """async (i) => {
          const C = await import('./modules/chart.js');
          const T = await import('./modules/tooltip.js');
          const d = window.__testHooks.data;
          return {
            x: C.hoverText(d, i, { axis: 'excitement', y: 'viewers', theme: 'light' }),
            y: C.hoverText(d, i, { axis: 'spread', y: 'excitement', theme: 'light' }),
            lineX: T.tooltipModel(d, i, { axis: 'excitement', y: 'viewers' }).axisLine,
            lineY: T.tooltipModel(d, i, { axis: 'spread', y: 'excitement' }).axisLine,
          };
        }""",
        _PINNED,
    )
    assert "Excitement: 23.2" in got["x"]
    assert "Excitement: 23.2" in got["y"]
    assert got["lineX"] == "Excitement: 23.2"
    assert got["lineY"].endswith("Excitement: 23.2")
    guarded_page.evaluate(f"window.__testHooks.openPanel({_PINNED})")
    guarded_page.wait_for_timeout(150)
    assert "Excitement: 23.2" in guarded_page.inner_text("#panel-body")


def test_unmutated_fixture_has_plain_ticks_and_wrapper_matches(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    got = guarded_page.evaluate(
        """async () => {
          const C = await import('./modules/chart.js');
          const d = window.__testHooks.data;
          return { a: C.measureYAxis(d, 'excitement', 600), b: C.excitementYAxis(d, 600) };
        }"""
    )
    assert got["a"] == got["b"]
    assert got["a"]["tickvals"] == [4, 6, 8]
    assert not any("+" in s for s in got["a"]["ticktext"])
