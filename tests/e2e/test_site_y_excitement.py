"""SITE-58 (04.15 D-13..D-16, D-19): the scatter drawn against CFBD excitement on y.

Synthetic fixture only. In the contract fixture, merged indices 2 (rated), 12 and 19
(unrated) have no excitement value, and 12 and 19 also have no spread.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_WAIT_TWO_FRAMES = "() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"

_NULL_EXCITEMENT = [2, 12, 19]

_FIG_JS = """
() => {
  const gd = document.getElementById('chart');
  const fl = gd._fullLayout;
  return {
    type: gd.layout.yaxis.type,
    title: gd.layout.yaxis.title.text,
    range: gd.layout.yaxis.range.slice(),
    uirevision: gd.layout.uirevision,
    y2domain: fl.yaxis2.domain.slice(),
    y2offset: fl.yaxis2._offset,
    y2length: fl.yaxis2._length,
    yLength: fl.yaxis._length,
    traces: gd.data.length,
  };
}
"""

_TRACES_JS = """
() => document.getElementById('chart').data.map((t) => ({
  meta: String(t.meta),
  yaxis: t.yaxis ?? 'y',
  x: Array.from(t.x ?? []),
  y: Array.from(t.y ?? []),
  customdata: Array.from(t.customdata ?? []),
  symbol: t.marker.symbol,
  size: t.marker.size,
  opacity: t.marker.opacity,
  color: t.marker.color,
  lineWidth: t.marker.line?.width,
}))
"""

_EXPECTED_AXIS_JS = """
async (logPx) => {
  const { excitementYAxis } = await import('./modules/chart.js');
  const data = window.__testHooks.data;
  return { expected: excitementYAxis(data, logPx), xr: data.xRange.excitement };
}
"""


def _open(
    request: pytest.FixtureRequest,
    open_app: Callable[[Page, str], None],
    size: tuple[int, int],
    query: str,
) -> Page:
    page: Page = request.getfixturevalue("guarded_page" if size[0] > 600 else "mobile_page")
    page.set_viewport_size({"width": size[0], "height": size[1]})
    open_app(page, query)
    page.evaluate(_WAIT_TWO_FRAMES)
    page.wait_for_timeout(150)
    return page


def _traces(page: Page) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = page.evaluate(_TRACES_JS)
    return out


@pytest.mark.parametrize("size", [(1280, 900), (360, 800)], ids=lambda s: f"{s[0]}x{s[1]}")
def test_excitement_y_axis_is_linear_whole_range_with_gutter(
    request: pytest.FixtureRequest, open_app: Callable[[Page, str], None], size: tuple[int, int]
) -> None:
    page = _open(request, open_app, size, "?y=excitement")
    fig = page.evaluate(_FIG_JS)
    assert fig["type"] == "linear"
    assert fig["title"] == "Excitement index (CFBD)"
    got = page.evaluate(_EXPECTED_AXIS_JS, fig["yLength"])
    lo, hi = got["xr"]
    assert fig["range"] == pytest.approx(got["expected"]["range"], abs=1e-9)
    assert fig["range"][0] < lo
    assert fig["range"][1] > hi
    base = fig["range"]
    slug = page.evaluate("window.__testHooks.data.teamSlugs[0]")
    page.evaluate(f"window.__testHooks.setState({{school: ['{slug}']}})")
    page.wait_for_timeout(150)
    assert page.evaluate(_FIG_JS)["range"] == pytest.approx(base, abs=1e-9)


@pytest.mark.parametrize("size", [(1280, 900), (360, 800)], ids=lambda s: f"{s[0]}x{s[1]}")
def test_excitement_y_clears_largest_dot(
    request: pytest.FixtureRequest, open_app: Callable[[Page, str], None], size: tuple[int, int]
) -> None:
    page = _open(request, open_app, size, "?y=excitement&people=kris-venn,sam-delgado&mode=compare")
    got = page.evaluate(
        """() => {
          const gd = document.getElementById('chart');
          const [lo, hi] = gd._fullLayout.yaxis.range;
          const h = gd._fullLayout.yaxis._length;
          const ys = [];
          for (const t of gd.data) {
            if (t.yaxis === 'y2') continue;
            for (const y of t.y) if (typeof y === 'number') ys.push(y);
          }
          const sizes = [];
          for (const t of gd.data) {
            const s = t.marker?.size;
            for (const v of Array.isArray(s) ? s : [s]) if (typeof v === 'number') sizes.push(v);
          }
          return {
            top: ((hi - Math.max(...ys)) * h) / (hi - lo),
            bottom: ((Math.min(...ys) - lo) * h) / (hi - lo),
            max: Math.max(...sizes),
          };
        }"""
    )
    assert got["max"] == 18
    assert got["top"] >= 10 - 1e-6, got
    assert got["bottom"] >= 10 - 1e-6, got


def test_band_holds_exactly_the_null_excitement_games(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?y=excitement")
    surface = guarded_page.evaluate(
        "async () => { const p = await import('./modules/palette.js');"
        " const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;"
        " return p.SURFACE[dark ? 'dark' : 'light']; }"
    )
    traces = _traces(guarded_page)
    in_band = sorted(
        i for t in traces if t["meta"].startswith("unrated-active:") for i in t["customdata"]
    )
    assert in_band == _NULL_EXCITEMENT
    for t in traces:
        if t["yaxis"] == "y2":
            continue
        assert all(isinstance(y, (int, float)) for y in t["y"]), t["meta"]
    for t in traces:
        assert t["color"] != surface, f"{t['meta']} draws a ring (D-14)"
        assert t["symbol"] != "circle-open"
    # every game with a value is in a main trace, rated or not
    main = sorted(i for t in traces if t["meta"].startswith("family:") for i in t["customdata"])
    assert main == sorted(set(range(20)) - set(_NULL_EXCITEMENT))
    # the band is all filled: inert band points share their family's inert marker
    for t in traces:
        if t["meta"].startswith("unrated-"):
            assert t["lineWidth"] in (0, 1), (t["meta"], t["lineWidth"])


def test_compare_shapes_are_filled_and_default_y_restores_rings(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    query = "people=pat-rowan,sam-delgado&mode=compare"
    open_app(guarded_page, f"?y=excitement&{query}")
    for t in _traces(guarded_page):
        if t["meta"].startswith("highlight"):
            assert t["opacity"] == 1
            assert "open" not in str(t["symbol"])
    open_app(guarded_page, f"?{query}")
    surface = guarded_page.evaluate(
        "async () => { const p = await import('./modules/palette.js');"
        " const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;"
        " return p.SURFACE[dark ? 'dark' : 'light']; }"
    )
    assert any(t["color"] == surface for t in _traces(guarded_page)), "04.13 rings return"


@pytest.mark.parametrize("size", [(1280, 900), (360, 800)], ids=lambda s: f"{s[0]}x{s[1]}")
def test_band_geometry_is_the_same_in_both_y_modes(
    request: pytest.FixtureRequest, open_app: Callable[[Page, str], None], size: tuple[int, int]
) -> None:
    page = _open(request, open_app, size, "")
    base = page.evaluate(_FIG_JS)
    page.evaluate("window.__testHooks.setState({y: 'excitement'})")
    page.wait_for_timeout(200)
    exc = page.evaluate(_FIG_JS)
    assert exc["type"] == "linear"
    assert exc["y2domain"] == pytest.approx(base["y2domain"])
    assert exc["y2offset"] == pytest.approx(base["y2offset"])
    assert exc["y2length"] == pytest.approx(base["y2length"])
    assert exc["yLength"] == pytest.approx(base["yLength"])


def test_corner_game_missing_both_values(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?y=excitement")
    sentinel = guarded_page.evaluate(
        "() => document.getElementById('chart').layout.annotations[0].x"
    )
    pts = {}
    for t in _traces(guarded_page):
        if t["meta"].startswith("unrated-active:"):
            for k, i in enumerate(t["customdata"]):
                pts[i] = (t["x"][k], t["y"][k], t["yaxis"])
    for i in (12, 19):
        assert pts[i][0] == pytest.approx(sentinel)
        assert pts[i][2] == "y2"
        assert 0 <= pts[i][1] < 1


def test_y_switch_resets_uirevision_only_for_excitement(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    assert guarded_page.evaluate(_FIG_JS)["uirevision"] == "spread"
    open_app(guarded_page, "?y=excitement")
    assert guarded_page.evaluate(_FIG_JS)["uirevision"] == "spread:y-excitement"
    open_app(guarded_page, "?axis=date&y=excitement")
    assert guarded_page.evaluate(_FIG_JS)["uirevision"] == "date:all:y-excitement"


_MARKERS_JS = """
() => document.getElementById('chart').data
  .filter((t) => String(t.meta).startsWith('family:') || String(t.meta).startsWith('inert:'))
  .map((t) => ({ meta: String(t.meta), size: t.marker.size, opacity: t.marker.opacity,
                 width: t.marker.line?.width }))
"""


@pytest.mark.parametrize(
    "patch",
    [
        "{school: ['{slug}']}",
        "{school: ['{slug}'], dots: 'hide'}",
        "{networks: ['net-a']}",
    ],
)
def test_tiers_sizes_and_networks_hiding_match_across_y_modes(
    guarded_page: Page, open_app: Callable[[Page, str], None], patch: str
) -> None:
    open_app(guarded_page, "")
    slug = guarded_page.evaluate("window.__testHooks.data.teamSlugs[0]")
    patch = patch.replace("{slug}", slug)
    seen = []
    for y in ("viewers", "excitement"):
        reset = f"{{school: [], networks: null, dots: null, y: '{y}'}}"
        guarded_page.evaluate(f"window.__testHooks.setState({reset})")
        guarded_page.evaluate(f"window.__testHooks.setState({patch})")
        guarded_page.wait_for_timeout(200)
        view = guarded_page.evaluate("window.__testHooks.getView()")
        seen.append(
            (
                view["passesFilters"],
                view["visibleCount"],
                view["passingCount"],
                guarded_page.evaluate(_MARKERS_JS),
            )
        )
    assert seen[0] == seen[1]


def test_band_jitter_covers_every_game(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    got = guarded_page.evaluate(
        "() => { const d = window.__testHooks.data;"
        " return { n: d.n, nRated: d.nRated, b: Array.from(d.bandJitter),"
        " j: Array.from(d.jitter) }; }"
    )
    assert len(got["b"]) == got["n"]
    assert all(0 <= v < 1 for v in got["b"])
    for i in range(got["nRated"], got["n"]):
        assert got["b"][i] == got["j"][i]
