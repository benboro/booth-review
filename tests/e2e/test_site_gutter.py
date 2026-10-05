"""SITE-49 (04.12 D-01..D-04): scatter x-axis edge gutter."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page
from test_site_date_axis import (
    _STATE_JS,
    _XRANGE_JS,
    _double_click_plot,
    _home,
    _settle,
)

pytestmark = pytest.mark.e2e


@pytest.fixture
def app_page(guarded_page: Page, open_app: Callable[[Page, str], None]) -> Page:
    """The app loaded once so `import('./modules/...')` resolves."""
    open_app(guarded_page, "")
    return guarded_page


def test_gutter_px_constant(app_page: Page) -> None:
    got = app_page.evaluate("async () => (await import('./modules/gutter.js')).GUTTER_PX")
    assert got == 10


def test_gutter_pads_closed_form(app_page: Page) -> None:
    got = app_page.evaluate(
        """async () => {
          const { gutterPads } = await import('./modules/gutter.js');
          return gutterPads(278, 1138);
        }"""
    )
    expected = 10 * 278 / (1138 - 20)
    assert got == [pytest.approx(expected), pytest.approx(expected)]


_GRID_JS = """
async () => {
  const { gutterPads, GUTTER_PX } = await import('./modules/gutter.js');
  let worst = Infinity;
  let bad = 0;
  let belowMin = 0;
  for (const plotPx of [150, 234, 266, 400, 700, 1000, 1138, 1400]) {
    for (const inner of [1, 87, 278, 2000]) {
      const mins = [
        [0, 0],
        [0.75 * 0.06 * inner, 0.03 * inner],
        [0.2 * inner, 0],
        [0, 0.2 * inner],
      ];
      for (const [minLo, minHi] of mins) {
        const [lo, hi] = gutterPads(inner, plotPx, { minLo, minHi });
        if (!Number.isFinite(lo) || !Number.isFinite(hi)) bad += 1;
        if (lo < minLo || hi < minHi) belowMin += 1;
        const t = inner + lo + hi;
        worst = Math.min(worst, (lo * plotPx) / t, (hi * plotPx) / t);
      }
    }
  }
  return { worst, bad, belowMin, px: GUTTER_PX };
}
"""


def test_gutter_pads_clear_px_across_widths(app_page: Page) -> None:
    got = app_page.evaluate(_GRID_JS)
    assert got["bad"] == 0
    assert got["belowMin"] == 0
    assert got["worst"] >= got["px"] - 1e-9


def test_gutter_pads_keeps_larger_mins(app_page: Page) -> None:
    got = app_page.evaluate(
        """async () => {
          const { gutterPads } = await import('./modules/gutter.js');
          return gutterPads(100, 1138, { minLo: 4.5, minHi: 3 });
        }"""
    )
    assert got == [4.5, 3]


def test_gutter_pads_degenerate_inputs(app_page: Page) -> None:
    got = app_page.evaluate(
        """async () => {
          const { gutterPads } = await import('./modules/gutter.js');
          const o = { minLo: 2, minHi: 1 };
          return [
            gutterPads(0, 1138, o),
            gutterPads(NaN, 1138, o),
            gutterPads(100, 20, o),
            gutterPads(100, undefined, o),
          ];
        }"""
    )
    assert got == [[2, 1]] * 4


# ---------------------------------------------------------------------------
# Rendered chart: edge gaps, pan limits, filter invariance, y, marker extent
# ---------------------------------------------------------------------------

_WAIT_TWO_FRAMES = "() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"

_EDGE_JS = """
() => {
  const gd = document.getElementById('chart');
  const [lo, hi] = gd._fullLayout.xaxis.range;
  const w = gd._fullLayout._size.w;
  const xs = [];
  for (const t of gd.data) for (const x of t.x) if (typeof x === 'number') xs.push(x);
  const na = (gd.layout.annotations ?? []).find((a) => a.text === 'N/A');
  const px = (x) => ((x - lo) * w) / (hi - lo);
  return {
    n: xs.length,
    left: px(Math.min(...xs)),
    right: ((hi - Math.max(...xs)) * w) / (hi - lo),
    naLeft: na ? px(na.x) : null,
  };
}
"""

_VIEWPORTS = [(1280, 900), (390, 844), (360, 800)]
_AXES = ["?axis=date", "", "?axis=excitement", "?axis=date&seasons=2025-2025"]


def _open_at(
    request: pytest.FixtureRequest,
    open_app: Callable[[Page, str], None],
    size: tuple[int, int],
    query: str,
) -> Page:
    """Open the app at `size`; phones use the touch context, desktop the plain page."""
    page: Page = request.getfixturevalue("guarded_page" if size[0] > 600 else "mobile_page")
    page.set_viewport_size({"width": size[0], "height": size[1]})
    open_app(page, query)
    page.evaluate(_WAIT_TWO_FRAMES)
    page.wait_for_timeout(150)
    return page


def _join(axis_query: str, extra: str) -> str:
    if not extra:
        return axis_query
    return f"{axis_query}&{extra}" if axis_query else f"?{extra}"


@pytest.mark.parametrize("people", ["", "people=dale-harlow"])
@pytest.mark.parametrize("size", _VIEWPORTS, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize("axis_query", _AXES)
def test_edge_dots_clear_gutter(
    request: pytest.FixtureRequest,
    open_app: Callable[[Page, str], None],
    axis_query: str,
    size: tuple[int, int],
    people: str,
) -> None:
    page = _open_at(request, open_app, size, _join(axis_query, people))
    got = page.evaluate(_EDGE_JS)
    assert got["n"] > 0
    assert got["left"] >= 9.5, got
    assert got["right"] >= 9.5, got
    if got["naLeft"] is not None:
        assert got["naLeft"] >= 9.5, got


@pytest.mark.parametrize("size", [(1280, 900), (360, 800)], ids=lambda s: f"{s[0]}x{s[1]}")
def test_date_pan_limits_are_the_padded_range(
    request: pytest.FixtureRequest, open_app: Callable[[Page, str], None], size: tuple[int, int]
) -> None:
    page = _open_at(request, open_app, size, "?axis=date")
    got = page.evaluate(
        """() => {
          const l = document.getElementById('chart').layout.xaxis;
          return { range: l.range.slice(), lo: l.minallowed, hi: l.maxallowed };
        }"""
    )
    assert got["lo"] == pytest.approx(got["range"][0], abs=1e-9)
    assert got["hi"] == pytest.approx(got["range"][1], abs=1e-9)
    assert got["range"][0] < 0
    assert got["range"][1] > 278


_RANGE_JS = "() => document.getElementById('chart')._fullLayout.xaxis.range.slice()"


@pytest.mark.parametrize("query", ["", "?axis=excitement"])
def test_spread_and_excitement_range_ignores_filters(
    mobile_page: Page, open_app: Callable[[Page, str], None], query: str
) -> None:
    open_app(mobile_page, query)
    original = mobile_page.evaluate(_RANGE_JS)
    for patch in (
        "{seasons: [2025, 2025]}",
        "{dots: 'hide'}",
        "{networks: ['net-a']}",
        "{networks: null, school: ['northfield', 'lakeview'], h2h: true}",
    ):
        mobile_page.evaluate(f"window.__testHooks.setState({patch})")
        mobile_page.wait_for_timeout(150)
        assert mobile_page.evaluate(_RANGE_JS) == pytest.approx(original, abs=1e-9), patch


_Y_JS = """
() => {
  const gd = document.getElementById('chart');
  const [lo, hi] = gd._fullLayout.yaxis.range;
  const h = gd._fullLayout._size.h;
  const ys = [];
  for (const t of gd.data) {
    for (const y of t.y) if (typeof y === 'number' && y > 0) ys.push(Math.log10(y));
  }
  return {
    top: ((hi - Math.max(...ys)) * h) / (hi - lo),
    bottom: ((Math.min(...ys) - lo) * h) / (hi - lo),
  };
}
"""


@pytest.mark.parametrize("size", [(1280, 900), (360, 800)], ids=lambda s: f"{s[0]}x{s[1]}")
def test_y_axis_clears_largest_dot(
    request: pytest.FixtureRequest, open_app: Callable[[Page, str], None], size: tuple[int, int]
) -> None:
    """04.12 D-04 record: the unchanged y range already leaves >= 10px top and bottom."""
    page = _open_at(request, open_app, size, "")
    got = page.evaluate(_Y_JS)
    assert got["top"] >= 10, got
    assert got["bottom"] >= 10, got


# Two announcers who share a telecast in the synthetic fixture, so the compare
# view draws the shared-game star (15px) with its halo (18px).
_STAR_QUERY = "?people=kris-venn,sam-delgado&mode=compare"


def test_gutter_clears_largest_marker(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, _STAR_QUERY)
    guarded_page.wait_for_timeout(300)
    got = guarded_page.evaluate(
        """async () => {
          const { GUTTER_PX } = await import('./modules/gutter.js');
          const gd = document.getElementById('chart');
          let max = 0;
          for (const t of gd.data) {
            const s = t.marker?.size;
            for (const v of Array.isArray(s) ? s : [s]) {
              if (typeof v === 'number') max = Math.max(max, v);
            }
          }
          const symbols = Object.values(window.__testHooks.getView().symbols ?? {});
          return { max, gutter: GUTTER_PX, star: symbols.includes('star') };
        }"""
    )
    assert got["star"], "the compare selection must draw a star or this guard is vacuous"
    assert got["max"] == 18
    assert got["max"] / 2 + 1 <= got["gutter"]


# ---------------------------------------------------------------------------
# Resize / rotation (04.12 D-01, D-03)
# ---------------------------------------------------------------------------


def _drag_zoom(page: Page) -> list[float]:
    page.locator("#chart").scroll_into_view_if_needed()
    box = page.evaluate(
        "() => { const gd = document.getElementById('chart'); const r = gd.getBoundingClientRect();"
        " const s = gd._fullLayout._size;"
        " const x = r.left + s.l; const y = r.top + s.t + s.h * 0.5;"
        " return { x0: x + s.w * 0.3, x1: x + s.w * 0.6, y }; }"
    )
    page.mouse.move(box["x0"], box["y"])
    page.mouse.down()
    page.mouse.move(box["x1"], box["y"], steps=8)
    page.mouse.up()
    _settle(page)
    zoomed: list[float] = page.evaluate(_XRANGE_JS)
    assert zoomed[1] - zoomed[0] < 278 * 0.5
    return zoomed


def _date_desktop(guarded_page: Page, open_app: Callable[[Page, str], None]) -> Page:
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    open_app(guarded_page, "?axis=date")
    _settle(guarded_page)
    return guarded_page


def test_resize_recomputes_date_home(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    page = _date_desktop(guarded_page, open_app)
    before = page.evaluate(_XRANGE_JS)
    page.set_viewport_size({"width": 900, "height": 900})
    _settle(page)
    home = _home(page, [0, 278])
    now = page.evaluate(_XRANGE_JS)
    assert now == pytest.approx(home, abs=1e-6)
    assert now != pytest.approx(before, abs=1e-6)
    lay = page.evaluate(
        "() => { const l = document.getElementById('chart').layout.xaxis;"
        " return [l.minallowed, l.maxallowed]; }"
    )
    assert lay == pytest.approx(home, abs=1e-6)
    got = page.evaluate(_EDGE_JS)
    assert got["left"] >= 9.5, got
    assert got["right"] >= 9.5, got
    assert _double_click_plot(page) == pytest.approx(home, abs=1e-6)
    assert _double_click_plot(page) == pytest.approx(home, abs=1e-6)


def test_resize_keeps_a_desktop_zoom(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    page = _date_desktop(guarded_page, open_app)
    zoomed = _drag_zoom(page)
    page.set_viewport_size({"width": 1000, "height": 900})
    _settle(page)
    assert page.evaluate(_XRANGE_JS) == pytest.approx(zoomed, abs=1e-6)
    # 04.11 D-13: a non-season filter after the resize still keeps the zoom.
    page.evaluate(_STATE_JS, {"school": ["northfield"]})
    _settle(page)
    assert page.evaluate(_XRANGE_JS) == pytest.approx(zoomed, abs=1e-6)
    page.evaluate(_STATE_JS, {"school": []})
    _settle(page)
    assert page.evaluate(_XRANGE_JS) == pytest.approx(zoomed, abs=1e-6)
    assert _double_click_plot(page) == pytest.approx(_home(page, [0, 278]), abs=1e-6)
    # Back at home, a later filter leaves the range at home.
    page.evaluate(_STATE_JS, {"school": ["northfield"]})
    _settle(page)
    assert page.evaluate(_XRANGE_JS) == pytest.approx(_home(page, [0, 278]), abs=1e-6)


def test_zoom_made_after_a_resize_survives_a_filter(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """A second zoom after a resize kept the first must also survive a filter (D-13)."""
    page = _date_desktop(guarded_page, open_app)
    _drag_zoom(page)
    page.set_viewport_size({"width": 1000, "height": 900})
    _settle(page)
    rezoomed = _drag_zoom(page)
    page.evaluate(_STATE_JS, {"school": ["northfield"]})
    _settle(page)
    assert page.evaluate(_XRANGE_JS) == pytest.approx(rezoomed, abs=1e-6)
    assert _double_click_plot(page) == pytest.approx(_home(page, [0, 278]), abs=1e-6)


def test_resize_on_bars_tab_keeps_the_scatter_zoom(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Resizing while Bars shows, then returning and filtering, keeps the zoom (D-13)."""
    page = _date_desktop(guarded_page, open_app)
    zoomed = _drag_zoom(page)
    page.evaluate(_STATE_JS, {"view": "bars"})
    _settle(page)
    page.set_viewport_size({"width": 1000, "height": 900})
    _settle(page)
    page.evaluate(_STATE_JS, {"view": "scatter"})
    _settle(page)
    assert page.evaluate(_XRANGE_JS) == pytest.approx(zoomed, abs=1e-6)
    page.evaluate(_STATE_JS, {"school": ["northfield"]})
    _settle(page)
    assert page.evaluate(_XRANGE_JS) == pytest.approx(zoomed, abs=1e-6)


_KEPT_JS = """
() => {
  const gd = document.getElementById('chart');
  const l = gd.layout.xaxis;
  return {
    live: gd._fullLayout.xaxis.range.slice(),
    input: l.range.slice(),
    lo: l.minallowed,
    hi: l.maxallowed,
  };
}
"""


@pytest.mark.parametrize("edge", ["left", "right"])
def test_widening_resize_clamps_a_kept_zoom_inside_the_pan_limits(
    guarded_page: Page, open_app: Callable[[Page, str], None], edge: str
) -> None:
    """WR-03: a zoom pinned to an edge stays inside the narrower limits, at its width."""
    guarded_page.set_viewport_size({"width": 700, "height": 900})
    open_app(guarded_page, "?axis=date")
    _settle(guarded_page)
    home = guarded_page.evaluate("() => document.getElementById('chart').boothHomeX.slice()")
    zoom = [home[0], home[0] + 50] if edge == "left" else [home[1] - 50, home[1]]
    guarded_page.evaluate("(r) => Plotly.relayout('chart', {'xaxis.range': r})", zoom)
    _settle(guarded_page)
    guarded_page.set_viewport_size({"width": 1400, "height": 900})
    _settle(guarded_page)
    got = guarded_page.evaluate(_KEPT_JS)
    assert got["lo"] > home[0] and got["hi"] < home[1], "widening must narrow the limits"
    assert got["input"] == pytest.approx(got["live"], abs=1e-9)
    assert got["live"][0] >= got["lo"] - 1e-9
    assert got["live"][1] <= got["hi"] + 1e-9
    assert got["live"][1] - got["live"][0] == pytest.approx(50, abs=1e-6)
    pinned = got["live"][0] if edge == "left" else got["live"][1]
    assert pinned == pytest.approx(got["lo"] if edge == "left" else got["hi"], abs=1e-9)


@pytest.mark.parametrize("query", ["?axis=date", ""])
def test_phone_rotation_recomputes_gutter(
    mobile_page: Page, open_app: Callable[[Page, str], None], query: str
) -> None:
    open_app(mobile_page, query)
    mobile_page.set_viewport_size({"width": 844, "height": 390})
    _settle(mobile_page)
    got = mobile_page.evaluate(_EDGE_JS)
    assert got["left"] >= 9.5, got
    assert got["right"] >= 9.5, got
    if got["naLeft"] is not None:
        assert got["naLeft"] >= 9.5, got


def test_season_change_after_resize_still_resets_zoom(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    page = _date_desktop(guarded_page, open_app)
    page.set_viewport_size({"width": 1000, "height": 900})
    _settle(page)
    _drag_zoom(page)
    page.evaluate(_STATE_JS, {"seasons": [2025, 2026]})
    _settle(page)
    assert page.evaluate(_XRANGE_JS) == pytest.approx(_home(page, [153, 278]), abs=1e-6)


def test_height_only_resize_keeps_range_object(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    page = _date_desktop(guarded_page, open_app)
    home_x = page.evaluate("() => document.getElementById('chart').boothHomeX.slice()")
    rng = page.evaluate(_XRANGE_JS)
    renders = page.evaluate("() => window.__testHooks.scatterResizeRenders")
    page.set_viewport_size({"width": 1280, "height": 700})
    _settle(page)
    assert page.evaluate(_XRANGE_JS) == pytest.approx(rng, abs=1e-9)
    assert page.evaluate("() => document.getElementById('chart').boothHomeX") == home_x
    assert page.evaluate("() => window.__testHooks.scatterResizeRenders") == renders
