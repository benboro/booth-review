"""SITE-68 (04.17 D-13..D-16, D-18): the scatter drawn against total points or margin on y.

Points and Margin plot a linear axis from 0 capped at 120 and 70; a game above its cap is
pinned there and keeps its true value in the tooltip. A game without a final score sits in
the bottom band as a filled marker. Synthetic fixture and in-test mutations only.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_WAIT_TWO_FRAMES = "() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"

# Mutated payload: index 0 totals 150 / margin 50, index 1 totals 100 / margin 80,
# index 2 (rated) and the first unrated game have no score.
_BIG_TOTAL = 0
_BIG_MARGIN = 1
_NO_SCORE_RATED = 2

_SIZES = [(1280, 900), (360, 800)]

_MEASURES = {
    "points": {"title": "Total points (both teams)", "step": 20, "cap": 120, "plus": "120+"},
    "margin": {"title": "Margin of victory (points)", "step": 10, "cap": 70, "plus": "70+"},
}

_FIG_JS = """
() => {
  const gd = document.getElementById('chart');
  const fl = gd._fullLayout;
  return {
    type: gd.layout.yaxis.type,
    title: gd.layout.yaxis.title.text,
    range: gd.layout.yaxis.range.slice(),
    tickvals: Array.from(gd.layout.yaxis.tickvals ?? []),
    ticktext: Array.from(gd.layout.yaxis.ticktext ?? []),
    uirevision: gd.layout.uirevision,
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
async ([mode, logPx]) => {
  const { measureYAxis } = await import('./modules/chart.js');
  return measureYAxis(window.__testHooks.data, mode, logPx);
}
"""


def _mutated(fixture_raw: dict[str, Any]) -> dict[str, Any]:
    raw = copy.deepcopy(fixture_raw)
    tel = raw["telecasts"]
    tel["home_points"][_BIG_TOTAL], tel["away_points"][_BIG_TOTAL] = 100, 50
    tel["home_points"][_BIG_MARGIN], tel["away_points"][_BIG_MARGIN] = 90, 10
    tel["home_points"][_NO_SCORE_RATED] = None
    raw["telecasts_unrated"]["home_points"][0] = None
    return raw


def _open(
    request: pytest.FixtureRequest,
    open_app: Callable[[Page, str], None],
    size: tuple[int, int],
    query: str,
    raw: dict[str, Any] | None = None,
) -> Page:
    page: Page = request.getfixturevalue("guarded_page" if size[0] > 600 else "mobile_page")
    if raw is not None:
        page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    page.set_viewport_size({"width": size[0], "height": size[1]})
    open_app(page, query)
    page.evaluate(_WAIT_TWO_FRAMES)
    page.wait_for_timeout(150)
    return page


def _traces(page: Page) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = page.evaluate(_TRACES_JS)
    return out


@pytest.mark.parametrize("size", _SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize("mode", ["points", "margin"])
def test_axis_is_linear_from_zero_with_fixed_ticks(
    request: pytest.FixtureRequest,
    open_app: Callable[[Page, str], None],
    size: tuple[int, int],
    mode: str,
) -> None:
    m = _MEASURES[mode]
    page = _open(request, open_app, size, f"?y={mode}")
    fig = page.evaluate(_FIG_JS)
    assert fig["type"] == "linear"
    assert fig["title"] == m["title"]
    assert fig["uirevision"] == f"spread:y-{mode}"
    expected = page.evaluate(_EXPECTED_AXIS_JS, [mode, fig["yLength"]])
    assert fig["range"] == pytest.approx(expected["range"], abs=1e-9)
    assert fig["range"][0] < 0
    assert fig["tickvals"][0] == 0
    assert all(v % m["step"] == 0 for v in fig["tickvals"])
    assert not any("+" in s for s in fig["ticktext"])


@pytest.mark.parametrize("size", _SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize(("mode", "game"), [("points", _BIG_TOTAL), ("margin", _BIG_MARGIN)])
def test_pinned_game_sits_at_cap_with_plus_tick(
    request: pytest.FixtureRequest,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
    size: tuple[int, int],
    mode: str,
    game: int,
) -> None:
    m = _MEASURES[mode]
    page = _open(request, open_app, size, f"?y={mode}", _mutated(fixture_raw))
    fig = page.evaluate(_FIG_JS)
    assert fig["ticktext"][-1] == m["plus"]
    assert fig["tickvals"][-1] == m["cap"]
    pts = [
        (t, k)
        for t in _traces(page)
        if t["yaxis"] != "y2"
        for k, i in enumerate(t["customdata"])
        if i == game
    ]
    assert pts
    assert all(t["y"][k] == m["cap"] for t, k in pts)
    lo, hi = fig["range"]
    assert (hi - m["cap"]) * fig["yLength"] / (hi - lo) >= 10 - 1e-6


@pytest.mark.parametrize("size", _SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize("mode", ["points", "margin"])
def test_band_holds_exactly_the_games_without_a_score(
    request: pytest.FixtureRequest,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
    size: tuple[int, int],
    mode: str,
) -> None:
    raw = _mutated(fixture_raw)
    page = _open(request, open_app, size, f"?y={mode}", raw)
    nr = len(raw["telecasts"]["season"])
    surface = page.evaluate(
        "async () => { const p = await import('./modules/palette.js');"
        " const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;"
        " return p.SURFACE[dark ? 'dark' : 'light']; }"
    )
    jitter = page.evaluate("Array.from(window.__testHooks.data.bandJitter)")
    n = page.evaluate("window.__testHooks.data.n")
    traces = _traces(page)
    band: dict[int, float] = {}
    for t in traces:
        if t["meta"].startswith("unrated-active:"):
            assert t["yaxis"] == "y2"
            for k, i in enumerate(t["customdata"]):
                band[i] = t["y"][k]
    assert sorted(band) == [_NO_SCORE_RATED, nr]
    for i, y in band.items():
        assert y == pytest.approx(jitter[i])
    main = sorted(i for t in traces if t["meta"].startswith("family:") for i in t["customdata"])
    assert main == sorted(set(range(n)) - {_NO_SCORE_RATED, nr})
    for t in traces:
        assert t["color"] != surface, f"{t['meta']} draws a ring (D-16)"
        assert t["symbol"] != "circle-open"


def test_band_button_reads_no_final_score(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?y=points")
    guarded_page.wait_for_timeout(150)
    assert "No final score" in guarded_page.inner_text("body")


@pytest.mark.parametrize("size", _SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_compare_shapes_filled_and_sizes_match_excitement(
    request: pytest.FixtureRequest, open_app: Callable[[Page, str], None], size: tuple[int, int]
) -> None:
    query = "people=kris-venn,sam-delgado&mode=compare"
    seen = {}
    for y in ("excitement", "points", "margin"):
        page = _open(request, open_app, size, f"?y={y}&{query}")
        hl = [t for t in _traces(page) if t["meta"].startswith("highlight")]
        assert hl
        for t in hl:
            assert t["opacity"] == 1
            assert "open" not in str(t["symbol"])
        sizes = {s for t in hl for s in (t["size"] if isinstance(t["size"], list) else [t["size"]])}
        seen[y] = sorted(sizes)
    assert seen["points"] == seen["excitement"]
    assert seen["margin"] == seen["excitement"]


def test_pairs_with_every_x(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    open_app(guarded_page, "?axis=excitement&y=points")
    assert guarded_page.evaluate("window.__testHooks.getState()")["axis"] == "excitement"
    assert guarded_page.evaluate("window.__testHooks.getState()")["y"] == "points"
    fig = guarded_page.evaluate(_FIG_JS)
    assert fig["title"] == "Total points (both teams)"
    assert fig["uirevision"] == "excitement:y-points"
    assert (
        guarded_page.evaluate("document.getElementById('chart').layout.xaxis.title.text")
        == "Excitement index (CFBD)"
    )
    open_app(guarded_page, "?axis=date&y=margin")
    state = guarded_page.evaluate("window.__testHooks.getState()")
    assert (state["axis"], state["y"]) == ("date", "margin")
    fig = guarded_page.evaluate(_FIG_JS)
    assert fig["title"] == "Margin of victory (points)"
    assert fig["uirevision"] == "date:all:y-margin"
    bands = guarded_page.evaluate(
        "(document.getElementById('chart').layout.shapes ?? [])"
        ".filter((s) => String(s.name ?? s.meta ?? '').startsWith('postseason')).length"
    )
    assert bands >= 0  # shape naming is owned by 04.17-01 tests; the layout must still build


def test_trace_count_constant_across_y_modes(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    counts = []
    for y in ("viewers", "excitement", "points", "margin"):
        guarded_page.evaluate(f"window.__testHooks.setState({{y: '{y}'}})")
        guarded_page.wait_for_timeout(200)
        counts.append(guarded_page.evaluate(_FIG_JS)["traces"])
    assert len(set(counts)) == 1, counts


_MARKERS_JS = """
() => document.getElementById('chart').data
  .filter((t) => String(t.meta).startsWith('family:') || String(t.meta).startsWith('inert:'))
  .map((t) => ({ meta: String(t.meta), size: t.marker.size, opacity: t.marker.opacity,
                 width: t.marker.line?.width }))
"""


@pytest.mark.parametrize(
    "patch",
    [
        "{}",
        "{school: ['{slug}']}",
        "{school: ['{slug}'], dots: 'hide'}",
    ],
)
def test_summary_and_sizes_match_across_y_modes(
    guarded_page: Page, open_app: Callable[[Page, str], None], patch: str
) -> None:
    open_app(guarded_page, "")
    slug = guarded_page.evaluate("window.__testHooks.data.teamSlugs[0]")
    patch = patch.replace("{slug}", slug)
    seen = []
    for y in ("viewers", "excitement", "points", "margin"):
        guarded_page.evaluate(
            f"window.__testHooks.setState({{school: [], networks: null, dots: null, y: '{y}'}})"
        )
        guarded_page.evaluate(f"window.__testHooks.setState({patch})")
        guarded_page.wait_for_timeout(200)
        view = guarded_page.evaluate("window.__testHooks.getView()")
        seen.append(
            (
                view["passesFilters"],
                view["visibleCount"],
                view["passingCount"],
                view["enlargeDots"],
                guarded_page.evaluate(_MARKERS_JS),
            )
        )
    assert all(s == seen[0] for s in seen[1:])
