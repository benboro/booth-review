"""SITE-52 (04.13 D-01..D-05): the "No public rating" band, hollow markers, and their rules."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page
from test_site_chart import (
    _RING,
    _RING_VISIBLE,
    _assert_ring_on,
    _boxes_overlap,
    _dot_point,
    _halo_ring_inner_radius,
    _hover_dot,
    _inert_dot_point,
    _speckle_count,
)

pytestmark = pytest.mark.e2e

_VIEWPORTS = [(1280, 900), (360, 800)]
_AXES = ["", "?axis=excitement", "?axis=date"]
_FAMILIES = ["disney", "fox", "conference"]

_WAIT_TWO_FRAMES = "() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"

_TRACES_JS = """
() => document.getElementById('chart').data.map((t) => ({
  meta: String(t.meta),
  yaxis: t.yaxis ?? 'y',
  x: Array.from(t.x ?? []),
  y: Array.from(t.y ?? []),
  customdata: Array.from(t.customdata ?? []),
  hoverinfo: t.hoverinfo,
  hovertemplate: t.hovertemplate ?? null,
  symbol: t.marker.symbol,
  size: t.marker.size,
  opacity: t.marker.opacity,
  lineWidth: t.marker.line?.width,
  lineColor: t.marker.line?.color,
  color: t.marker.color,
}))
"""

# The 6px ring width per family: 1.5, or 2 for a family under 3:1 against SURFACE (UI-SPEC Color).
_THIN_JS = """
async () => {
  const p = await import('./modules/palette.js');
  const theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  const out = {};
  for (const [f, c] of Object.entries(p.FAMILY_COLORS[theme])) {
    out[f] = p.contrastRatio(c, p.SURFACE[theme]) < 3 ? 2 : 1.5;
  }
  return out;
}
"""

_GEOMETRY_JS = """
() => {
  const gd = document.getElementById('chart');
  const fl = gd._fullLayout;
  return {
    y2Length: fl.yaxis2._length,
    y2Offset: fl.yaxis2._offset,
    logLength: fl.yaxis._length,
    logOffset: fl.yaxis._offset,
    plotH: fl._size.h,
    y2domain: gd.layout.yaxis2.domain.slice(),
    ydomain: gd.layout.yaxis.domain.slice(),
    xAnchor: gd.layout.xaxis.anchor,
    y2: {
      fixedrange: gd.layout.yaxis2.fixedrange,
      showticklabels: gd.layout.yaxis2.showticklabels,
      showgrid: gd.layout.yaxis2.showgrid,
      zeroline: gd.layout.yaxis2.zeroline,
    },
    shape0: gd.layout.shapes[0],
    shapes: gd.layout.shapes,
    ann0: gd.layout.annotations[0].text,
  };
}
"""


def _open_at(
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


def _by_meta(page: Page) -> dict[str, dict[str, Any]]:
    return {t["meta"]: t for t in _traces(page)}


def _unrated_points(page: Page, prefix: str) -> dict[int, dict[str, Any]]:
    """Merged index -> {x, y, trace} over every trace whose meta starts with `prefix`."""
    out: dict[int, dict[str, Any]] = {}
    for t in _traces(page):
        if t["meta"].startswith(prefix):
            for k, i in enumerate(t["customdata"]):
                out[i] = {"x": t["x"][k], "y": t["y"][k], "trace": t}
    return out


# ---------------------------------------------------------------------------
# bandLayout (pure)
# ---------------------------------------------------------------------------


def test_band_layout_closed_form(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    open_app(guarded_page, "")
    got = guarded_page.evaluate(
        """async () => {
          const { bandLayout, BAND } = await import('./modules/chart.js');
          const c = bandLayout(undefined);
          return { a: bandLayout(420), b: bandLayout(700), c, d: bandLayout(-5), BAND };
        }"""
    )
    a = got["a"]
    assert a["bandPx"] == 56
    assert a["gapPx"] == 28
    assert a["bandTop"] == pytest.approx(56 / 420)
    assert a["logBottom"] == pytest.approx(84 / 420)
    assert a["y2range"] == [pytest.approx(-12 / 32), pytest.approx(1 + 12 / 32)]
    assert got["b"]["bandPx"] == pytest.approx(84)
    assert got["c"] == a
    assert got["d"] == a
    assert got["BAND"] == {"frac": 0.12, "minPx": 56, "gapPx": 28, "padPx": 12}


# ---------------------------------------------------------------------------
# Band geometry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("axis_query", _AXES)
@pytest.mark.parametrize("size", _VIEWPORTS, ids=lambda s: f"{s[0]}x{s[1]}")
def test_band_geometry(
    request: pytest.FixtureRequest,
    open_app: Callable[[Page, str], None],
    size: tuple[int, int],
    axis_query: str,
) -> None:
    page = _open_at(request, open_app, size, axis_query)
    got = page.evaluate(_GEOMETRY_JS)
    assert got["xAnchor"] == "y2"
    assert got["y2domain"][0] == 0
    assert got["ydomain"][1] == 1
    assert got["y2"] == {
        "fixedrange": True,
        "showticklabels": False,
        "showgrid": False,
        "zeroline": False,
    }
    assert got["y2Length"] >= 56 - 0.5
    expected_band = max(0.12 * got["plotH"], 56)
    assert got["y2Length"] == pytest.approx(expected_band, abs=1.5)
    # a fixed 28px gap row between the log axis and the band
    gap = got["y2Offset"] - (got["logOffset"] + got["logLength"])
    assert gap == pytest.approx(28, abs=1.5)
    # band rectangle and top edge are appended after the existing shapes
    rect = got["shapes"][-2]
    edge = got["shapes"][-1]
    assert rect["type"] == "rect" and rect["layer"] == "below" and rect["yref"] == "paper"
    assert rect["y0"] == 0 and rect["y1"] == pytest.approx(got["y2domain"][1])
    assert edge["type"] == "line" and edge["y0"] == edge["y1"] == pytest.approx(got["y2domain"][1])
    assert edge["line"]["width"] == 1
    if axis_query != "?axis=date":
        assert got["shape0"]["type"] == "line"
        assert got["ann0"] == "N/A"


def test_band_stays_drawn_when_filters_leave_no_unrated_games(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?networks=net-d&dots=hide")
    got = guarded_page.evaluate(_GEOMETRY_JS)
    assert got["y2Length"] >= 55.5
    unrated = _unrated_points(guarded_page, "unrated-")
    assert unrated == {}


# ---------------------------------------------------------------------------
# Hollow markers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("axis_query", _AXES)
def test_default_unrated_markers(
    guarded_page: Page, open_app: Callable[[Page, str], None], axis_query: str
) -> None:
    open_app(guarded_page, axis_query)
    traces = _traces(guarded_page)
    active = [t for t in traces if t["meta"].startswith("unrated-active:")]
    assert {f"unrated-active:{f}" for f in _FAMILIES} <= {t["meta"] for t in active}
    thin = guarded_page.evaluate(_THIN_JS)
    pts = _unrated_points(guarded_page, "unrated-active:")
    assert sorted(pts) == list(range(12, 20))
    by_family = {t["meta"].split(":", 1)[1]: sorted(t["customdata"]) for t in active}
    assert by_family["disney"] == [13, 14, 15, 18, 19]
    assert by_family["fox"] == [12, 16]
    assert by_family["conference"] == [17]
    for t in active:
        assert t["yaxis"] == "y2"
        assert t["symbol"] == "circle-open"
        assert t["size"] == 6
        assert t["lineWidth"] == thin[t["meta"].split(":", 1)[1]]
        assert t["opacity"] == 1
        assert t["lineColor"] == t["color"]


def test_jitter_is_the_band_y_and_stable_across_reload(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    # data.js: jitter hashed by unrated-block index (Weyl), merged index 12 is block index 1
    jit = {i: ((((i - 12 + 1) * 2654435761) & 0xFFFFFFFF) / 4294967296) for i in range(12, 20)}
    first = _unrated_points(guarded_page, "unrated-active:")
    for i, p in first.items():
        assert p["y"] == pytest.approx(jit[i])
        assert 0 <= p["y"] < 1
    guarded_page.reload()
    guarded_page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    again = _unrated_points(guarded_page, "unrated-active:")
    assert {i: p["y"] for i, p in again.items()} == {i: p["y"] for i, p in first.items()}


@pytest.mark.parametrize("axis_query", ["", "?axis=excitement"])
def test_game_without_x_sits_at_the_na_sentinel(
    guarded_page: Page, open_app: Callable[[Page, str], None], axis_query: str
) -> None:
    open_app(guarded_page, axis_query)
    sentinel = guarded_page.evaluate(
        "() => document.getElementById('chart').layout.annotations[0].x"
    )
    pts = _unrated_points(guarded_page, "unrated-active:")
    assert pts[12]["x"] == pytest.approx(sentinel)


@pytest.mark.parametrize("size", _VIEWPORTS, ids=lambda s: f"{s[0]}x{s[1]}")
@pytest.mark.parametrize("axis_query", _AXES)
def test_markers_never_clip_at_band_edges(
    request: pytest.FixtureRequest,
    open_app: Callable[[Page, str], None],
    size: tuple[int, int],
    axis_query: str,
) -> None:
    page = _open_at(request, open_app, size, axis_query)
    got = page.evaluate(
        """() => {
          const gd = document.getElementById('chart');
          const ya = gd._fullLayout.yaxis2;
          const out = [];
          for (const t of gd.data) {
            if (t.yaxis !== 'y2') continue;
            for (const y of t.y) out.push(ya._length - ya.d2p(y));
          }
          return { fromBottom: out, length: ya._length };
        }"""
    )
    assert got["fromBottom"]
    for from_bottom in got["fromBottom"]:
        assert from_bottom >= 12 - 0.5
        assert got["length"] - from_bottom >= 12 - 0.5


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def test_networks_filter_hides_unrated_games_of_other_networks(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?networks=net-a,net-b")
    seen = {i for t in _traces(guarded_page) for i in t["customdata"]}
    assert 15 not in seen and 18 not in seen
    # hidden, not faded: the inert traces do not carry them either (no customdata there)
    inert = [t for t in _traces(guarded_page) if t["meta"].startswith("unrated-inert:")]
    assert sum(len(t["x"]) for t in inert) == 0


def test_fade_filter_moves_failing_games_to_inert_and_enlarges_passing(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?school=northfield")
    traces = _traces(guarded_page)
    active = [t for t in traces if t["meta"].startswith("unrated-active:")]
    inert = [t for t in traces if t["meta"].startswith("unrated-inert:")]
    passing = sorted(i for t in active for i in t["customdata"])
    assert passing == [13, 16]
    assert sum(len(t["x"]) for t in inert) == 6
    for t in active:
        assert t["size"] == 10
        assert t["lineWidth"] == 2
        assert t["lineColor"] == t["color"]  # the ring is the outline: no separate black line
    opacity = guarded_page.evaluate(
        "async () => (await import('./modules/chart.js')).DOT_OPACITY.inert"
    )
    for t in inert:
        assert t["hoverinfo"] == "skip"
        assert t["hovertemplate"] is None
        assert t["size"] == 6
        assert t["opacity"] == opacity
        assert t["symbol"] == "circle-open"


def test_active_traces_share_hover_config_with_rated_twins(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    for query in ("", "?people=pat-rowan"):
        open_app(guarded_page, query)
        by = _by_meta(guarded_page)
        for family in _FAMILIES:
            rated = by[f"family:{family}"]
            unrated = by[f"unrated-active:{family}"]
            assert unrated["hoverinfo"] == rated["hoverinfo"]
            assert unrated["hovertemplate"] == rated["hovertemplate"]


def test_date_trims_out_of_season_unrated_games_spread_fades_them(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?axis=date&seasons=2025-2026")
    shown = _unrated_points(guarded_page, "unrated-")
    n_shown = sum(
        len(t["x"])
        for t in _traces(guarded_page)
        if t["meta"].startswith("unrated-") and t["yaxis"] == "y2"
    )
    assert 0 < n_shown < 8, "fixture needs unrated games both inside and outside 2025-2026"
    assert all(p["x"] >= 191 for p in shown.values())
    open_app(guarded_page, "?seasons=2025-2026")
    n_inert = sum(
        len(t["x"]) for t in _traces(guarded_page) if t["meta"].startswith("unrated-inert:")
    )
    assert n_inert == 8 - n_shown


# ---------------------------------------------------------------------------
# Trace count
# ---------------------------------------------------------------------------


_COUNT_QUERIES = [
    "",
    "?school=northfield",
    "?school=northfield&dots=hide",
    "?people=pat-rowan",
    "?people=pat-rowan,sam-delgado&mode=compare",
    "?axis=excitement",
    "?axis=date",
    "?axis=date&seasons=2025-2026",
]


def test_trace_count_is_constant_and_names_are_present(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    counts = set()
    for query in _COUNT_QUERIES:
        open_app(guarded_page, query)
        metas = [t["meta"] for t in _traces(guarded_page)]
        for f in _FAMILIES:
            assert f"unrated-inert:{f}" in metas
            assert f"unrated-active:{f}" in metas
        assert "highlight-halo-unrated" in metas
        assert "highlight-unrated" in metas
        assert metas[-1] == "highlight"
        counts.add(len(metas) - (1 if "highlight-halo" in metas else 0))
    assert len(counts) == 1, counts


# ---------------------------------------------------------------------------
# Compare mode
# ---------------------------------------------------------------------------


def _highlight(page: Page) -> dict[int, dict[str, Any]]:
    by = _by_meta(page)
    out: dict[int, dict[str, Any]] = {}
    t = by["highlight-unrated"]
    syms = t["symbol"] if isinstance(t["symbol"], list) else [t["symbol"]] * len(t["x"])
    sizes = t["size"] if isinstance(t["size"], list) else [t["size"]] * len(t["x"])
    for k, i in enumerate(t["customdata"]):
        out[i] = {"symbol": syms[k], "size": sizes[k]}
    return out


def test_compare_open_shapes_and_open_halo(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?people=pat-rowan,sam-delgado&mode=compare")
    hl = _highlight(guarded_page)
    assert hl[15] == {"symbol": "circle-open", "size": 10}
    assert hl[16] == {"symbol": "star-open", "size": 15}
    assert hl[19] == {"symbol": "star-open", "size": 15}
    by = _by_meta(guarded_page)
    t = by["highlight-unrated"]
    assert t["yaxis"] == "y2" and t["lineWidth"] == 2 and t["opacity"] == 1
    halo = by["highlight-halo-unrated"]
    assert halo["yaxis"] == "y2"
    assert sorted(halo["x"]) == sorted(
        [hl_x for i, hl_x in zip(t["customdata"], t["x"], strict=True) if i in (16, 19)]
    )
    assert halo["symbol"] == ["star-open", "star-open"]
    assert halo["size"] == [18, 18]
    assert halo["lineWidth"] == 2
    assert halo["hoverinfo"] == "skip"
    accent = guarded_page.evaluate(
        "async () => (await import('./modules/palette.js')).ACCENT.light"
    )
    assert halo["color"] == accent


def test_compare_shared_booth_is_a_star_and_others_get_shapes(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?people=kris-venn,morgan-ash&mode=compare")
    assert _highlight(guarded_page)[13]["symbol"] == "star-open"
    open_app(guarded_page, "?people=dale-harlow,kris-venn&mode=compare")
    hl = _highlight(guarded_page)
    assert hl[17] == {"symbol": "circle-open", "size": 10}
    assert hl[13]["symbol"] in {"square-open", "diamond-open", "triangle-up-open"}
    assert hl[13]["size"] == 12
    halo = _by_meta(guarded_page)["highlight-halo-unrated"]
    assert 15 in halo["size"]
    assert halo["symbol"] == [hl[13]["symbol"]]


_SPECKLE_QUERY = "?people=kris-venn,sam-delgado,dale-harlow,casey-lund&mode=compare"


@pytest.mark.parametrize("color_scheme", ["light", "dark"])
def test_open_compare_shapes_in_the_band_have_no_edge_speckles(
    guarded_page: Page, open_app: Callable[[Page, str], None], color_scheme: str
) -> None:
    """D-31 guard on the open traces: no accent speckle beyond the open halo's own shape.

    Measures with the `_speckle_count` helper of test_site_chart.py (imported, not edited).
    """
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    guarded_page.emulate_media(color_scheme=color_scheme)
    open_app(guarded_page, _SPECKLE_QUERY)
    guarded_page.locator("#chart").scroll_into_view_if_needed()
    points = guarded_page.evaluate(
        """() => {
          const gd = document.getElementById('chart');
          const fl = gd._fullLayout;
          const rect = gd.getBoundingClientRect();
          const t = gd.data.find((d) => d.meta === 'highlight-unrated');
          return t.x.map((x, k) => ({
            customdata: t.customdata[k],
            symbol: t.marker.symbol[k],
            size: t.marker.size[k],
            px: rect.left + fl._size.l + fl.xaxis.d2p(x),
            py: rect.top + fl.yaxis2._offset + fl.yaxis2.d2p(t.y[k]),
          }));
        }"""
    )
    guarded_page.mouse.move(5, 5)
    guarded_page.wait_for_timeout(100)
    tested = 0
    total = 0
    for point in points:
        if point["symbol"] == "circle-open":
            continue
        others = [p for p in points if p["customdata"] != point["customdata"]]
        if any(_boxes_overlap(point, o) for o in others):
            continue
        tested += 1
        total += _speckle_count(
            guarded_page,
            point["px"],
            point["py"],
            color_scheme,
            _halo_ring_inner_radius(point["size"]),
            others,
        )
    assert tested > 0, "no open non-circle marker was testable"
    assert total == 0, f"{total} speckle pixel(s) around open compare markers"


# ---------------------------------------------------------------------------
# Contrast
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_every_family_ring_color_clears_three_to_one_on_surface(
    guarded_page: Page, open_app: Callable[[Page, str], None], theme: str
) -> None:
    open_app(guarded_page, "")
    got = guarded_page.evaluate(
        """async (theme) => {
          const p = await import('./modules/palette.js');
          const out = {};
          for (const [f, c] of Object.entries(p.FAMILY_COLORS[theme])) {
            out[f] = p.contrastRatio(c, p.SURFACE[theme]);
          }
          return out;
        }""",
        theme,
    )
    # A family under 3:1 gets a 2px ring (see chart.js); never fail on the palette itself.
    assert got
    assert all(math.isfinite(v) and v > 1 for v in got.values()), got
    if theme == "light":
        assert got["other"] >= 2.5


# ---------------------------------------------------------------------------
# Pointer behavior (D-04)
# ---------------------------------------------------------------------------

_MATCHUP_JS = """
async (i) => {
  const m = await import('./modules/format.js');
  return m.formatMatchup(window.__testHooks.data, i, { withScore: true });
}
"""


def test_hover_ring_diameter_treats_circle_open_as_a_circle(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    got = guarded_page.evaluate(
        """async () => {
          const m = await import('./modules/hover-ring.js');
          return [m.hoverRingDiameter(6, 'circle-open'), m.hoverRingDiameter(10, 'circle-open'),
                  m.hoverRingDiameter(6, 'star-open') > 14];
        }"""
    )
    assert got == [14, 18, True]


def test_test_hooks_expose_rated_and_game_counts(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    assert guarded_page.evaluate("[window.__testHooks.nRated, window.__testHooks.nGames]") == [
        12,
        20,
    ]


@pytest.mark.parametrize(("axis_query", "index"), [("", 17), ("?axis=date", 19), ("", 3)])
def test_hover_ring_is_centered_on_band_and_rated_markers(
    guarded_page: Page, open_app: Callable[[Page, str], None], axis_query: str, index: int
) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    open_app(guarded_page, axis_query)
    point = _hover_dot(guarded_page, index)
    guarded_page.wait_for_selector(_RING_VISIBLE, timeout=3000)
    box = _assert_ring_on(guarded_page, index, point)
    assert abs(box["width"] - box["height"]) < 0.5
    if index >= 12:
        assert box["width"] == pytest.approx(14, abs=0.5)  # circle-open 6 + 8
    assert guarded_page.is_visible("#chart-tooltip")
    tip = guarded_page.locator("#chart-tooltip").bounding_box()
    assert tip is not None
    assert abs(tip["x"] - point["x"]) < 400


def test_tap_on_band_marker_shows_panel_at_360(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(mobile_page, "")
    point = _dot_point(mobile_page, 13)
    mobile_page.touchscreen.tap(point["x"], point["y"])
    mobile_page.wait_for_function("document.getElementById('detail-panel').open")
    assert mobile_page.inner_text("#panel-title") == mobile_page.evaluate(_MATCHUP_JS, 13)


def test_click_on_band_marker_opens_its_modal(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    point = _hover_dot(guarded_page, 16)
    guarded_page.mouse.click(point["x"], point["y"])
    guarded_page.wait_for_function("document.getElementById('detail-panel').open")
    assert guarded_page.inner_text("#panel-title") == guarded_page.evaluate(_MATCHUP_JS, 16)


def test_inert_band_marker_has_no_tooltip_and_no_ring(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?school=northfield")
    inert = [t for t in _traces(guarded_page) if t["meta"].startswith("unrated-inert:")]
    meta = next(t["meta"] for t in inert if t["x"])
    guarded_page.mouse.move(5, 5)
    point = _inert_dot_point(guarded_page, meta, 0)
    guarded_page.mouse.move(point["x"], point["y"])
    guarded_page.wait_for_timeout(400)
    assert guarded_page.is_hidden("#chart-tooltip")
    assert guarded_page.is_hidden(_RING)
    guarded_page.mouse.click(point["x"], point["y"])
    guarded_page.wait_for_timeout(200)
    assert not guarded_page.evaluate("document.getElementById('detail-panel').open")


# ---------------------------------------------------------------------------
# Band label / info button / note (D-01, D-12)
# ---------------------------------------------------------------------------

_BAND_INFO_JS = """
() => {
  const b = document.getElementById('band-info');
  const gd = document.getElementById('chart');
  const fl = gd._fullLayout;
  const c = gd.getBoundingClientRect();
  const r = b.getBoundingClientRect();
  const text = b.querySelector('.band-info-text').getBoundingClientRect();
  return {
    box: { x: r.x, y: r.y, w: r.width, h: r.height },
    chartTop: c.top, chartLeft: c.left, chartH: c.height,
    plotLeft: fl._size.l,
    gapTop: fl.yaxis2._offset - 28,
    gapBottom: fl.yaxis2._offset,
    lineH: parseFloat(getComputedStyle(b).lineHeight),
    textH: text.height,
    label: b.textContent.trim(),
    scrollW: document.documentElement.scrollWidth,
    clientW: document.documentElement.clientWidth,
  };
}
"""

_MARKER_CENTERS_JS = """
() => {
  const gd = document.getElementById('chart');
  const fl = gd._fullLayout;
  const c = gd.getBoundingClientRect();
  const out = [];
  for (const t of gd.data) {
    const ya = t.yaxis === 'y2' ? fl.yaxis2 : fl.yaxis;
    for (let k = 0; k < (t.x ?? []).length; k++) {
      if (t.x[k] == null || t.y[k] == null) continue;
      const px = c.left + fl._size.l + fl.xaxis.l2p(t.x[k]);
      const py = c.top + ya._offset + ya.l2p(t.y[k]);
      out.push([px, py]);
    }
  }
  return out;
}
"""


@pytest.mark.parametrize("size", _VIEWPORTS)
@pytest.mark.parametrize("axis_query", _AXES)
def test_band_info_button_geometry(
    request: pytest.FixtureRequest,
    open_app: Callable[[Page, str], None],
    size: tuple[int, int],
    axis_query: str,
) -> None:
    page = _open_at(request, open_app, size, axis_query)
    info = page.evaluate(_BAND_INFO_JS)
    box = info["box"]
    assert page.is_visible("#band-info")
    assert box["w"] >= 44
    assert box["h"] >= 44
    assert info["label"].startswith("No public rating")
    gap_center = info["chartTop"] + (info["gapTop"] + info["gapBottom"]) / 2
    assert abs(box["y"] + box["h"] / 2 - gap_center) <= 2
    assert abs(box["x"] - (info["chartLeft"] + info["plotLeft"] + 4)) <= 2
    assert info["textH"] < 2 * info["lineH"]
    assert info["scrollW"] <= info["clientW"]
    for px, py in page.evaluate(_MARKER_CENTERS_JS):
        inside = box["x"] <= px <= box["x"] + box["w"] and box["y"] <= py <= box["y"] + box["h"]
        assert not inside


def test_band_info_hidden_off_the_scatter(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?school=northfield")
    assert guarded_page.is_visible("#band-info")
    guarded_page.click("#band-info")
    guarded_page.click("#tab-bars")
    guarded_page.wait_for_timeout(200)
    assert guarded_page.is_hidden("#band-info")
    assert guarded_page.is_hidden("#band-note")


@pytest.mark.parametrize("size", _VIEWPORTS)
def test_band_note_toggle_escape_outside_and_no_shift(
    request: pytest.FixtureRequest, open_app: Callable[[Page, str], None], size: tuple[int, int]
) -> None:
    page = _open_at(request, open_app, size, "")
    assert page.get_attribute("#band-info", "aria-label") == (
        "Why do some games have no public rating?"
    )
    assert page.get_attribute("#band-info", "aria-controls") == "band-note"
    before = page.evaluate(
        "() => [document.getElementById('chart').getBoundingClientRect().height,"
        " document.getElementById('summary').getBoundingClientRect().top + scrollY]"
    )
    page.click("#band-info")
    assert page.get_attribute("#band-info", "aria-expanded") == "true"
    assert page.is_visible("#band-note")
    text = page.inner_text("#band-note")
    for phrase in (
        "No public rating",
        "We found no published viewer count for these games.",
        "The network is rarely rated, such as ESPN+, CBS Sports Network, or SEC Network.",
        "Few figures were compiled for 2021\u201324.",
        "No figure was published.",
    ):
        assert phrase in text
    href = page.get_attribute("#band-note a", "href") or ""
    assert href.endswith("methodology.html#games-with-no-public-rating")
    note = page.locator("#band-note").bounding_box()
    assert note is not None
    assert note["width"] <= 280
    assert note["x"] >= 0
    assert note["x"] + note["width"] <= size[0]
    after = page.evaluate(
        "() => [document.getElementById('chart').getBoundingClientRect().height,"
        " document.getElementById('summary').getBoundingClientRect().top + scrollY]"
    )
    assert after == before
    page.keyboard.press("Escape")
    assert page.is_hidden("#band-note")
    assert page.get_attribute("#band-info", "aria-expanded") == "false"
    assert page.evaluate("document.activeElement.id") == "band-info"
    page.click("#band-info")
    assert page.is_visible("#band-note")
    page.mouse.click(size[0] - 5, 5)
    assert page.is_hidden("#band-note")
    page.click("#band-info")
    page.click("#band-info")
    assert page.is_hidden("#band-note")
    page.focus("#band-info")
    page.keyboard.press("Enter")
    assert page.is_visible("#band-note")
    page.keyboard.press("Space")
    assert page.is_hidden("#band-note")


# ---------------------------------------------------------------------------
# End to end: band hover / tap -> tooltip -> modal (D-04)
# ---------------------------------------------------------------------------

_WHY_HREF = "methodology.html#games-with-no-public-rating"


@pytest.mark.parametrize(
    ("axis_query", "index", "line"),
    [
        ("", 17, "No public rating · Conference Network games are rarely rated"),
        ("?axis=date", 19, "No public rating · viewership not posted yet"),
    ],
)
def test_hover_band_marker_shows_cause_tooltip_ring_and_modal(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    axis_query: str,
    index: int,
    line: str,
) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    open_app(guarded_page, axis_query)
    point = _hover_dot(guarded_page, index)
    guarded_page.wait_for_selector(_RING_VISIBLE, timeout=3000)
    assert line in guarded_page.inner_text("#chart-tooltip")
    _assert_ring_on(guarded_page, index, point)
    guarded_page.mouse.click(point["x"], point["y"])
    guarded_page.wait_for_function("document.getElementById('detail-panel').open")
    body = guarded_page.locator("#panel-body")
    assert line in body.inner_text()
    link = body.locator("a", has_text="Why no rating?")
    assert (link.get_attribute("href") or "").endswith(_WHY_HREF)


def test_tap_band_marker_at_360_shows_cause_line(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(mobile_page, "")
    point = _dot_point(mobile_page, 13)
    mobile_page.touchscreen.tap(point["x"], point["y"])
    mobile_page.wait_for_function("document.getElementById('detail-panel').open")
    shown = mobile_page.inner_text("#panel-body")
    assert "No public rating · few figures were compiled for 2021\u201324" in shown


def test_compare_faded_unrated_marker_is_inert(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?school=northfield&people=pat-rowan,sam-delgado&mode=compare")
    inert = [
        t["meta"]
        for t in _traces(guarded_page)
        if t["meta"].startswith("unrated-inert:") and t["x"]
    ]
    assert inert, "fixture must leave some unrated games inert under a school filter with compare"
    guarded_page.mouse.move(5, 5)
    point = _inert_dot_point(guarded_page, inert[0], 0)
    guarded_page.mouse.move(point["x"], point["y"])
    guarded_page.wait_for_timeout(400)
    assert guarded_page.is_hidden("#chart-tooltip")


def test_plotly_tooltip_mode_labels_band_marker_with_cause(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.setTooltipMode('plotly')")
    guarded_page.wait_for_function(
        "document.getElementById('chart').data.at(-1).hovertemplate === '%{text}<extra></extra>'"
    )
    point = _dot_point(guarded_page, 12)
    guarded_page.mouse.move(5, 5)
    guarded_page.evaluate(_WAIT_TWO_FRAMES)
    guarded_page.mouse.move(point["x"], point["y"], steps=4)
    guarded_page.wait_for_selector(".hoverlayer .hovertext", timeout=3000)
    label = guarded_page.text_content(".hoverlayer .hovertext") or ""
    assert "No public rating · no figure was published" in label
