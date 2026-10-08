"""04.18 (SITE-72..75): map-chart.js, the Map's Plotly figure builder and events.

In-page tests on synthetic models and the real vendored geometry (no vault rows).
"""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_FAMILIES = ["disney", "fox", "cbs", "nbc", "cw", "wbd", "conference", "other"]


def _load(page: Page, site_url: str) -> None:
    page.goto(f"{site_url}/index.html")
    page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")


def _run(page: Page, site_url: str, body: str) -> Any:
    _load(page, site_url)
    return page.evaluate(
        """async () => {
          const C = await import('./modules/map-chart.js');
          const P = await import('./modules/palette.js');
          const G = await import('./vendor/us-states-albers.js');
          const empty = {dots: [], faded: [], legs: [], markers: []};
          const rich = {
            dots: [
              {venue: 3, family: 'fox', x: 400, y: 300, symbol: 'circle', tier: 'base'},
              {venue: 4, family: 'fox', x: 410, y: 310, symbol: 'circle', tier: 'other'},
              {venue: 5, family: 'fox', x: 420, y: 320, symbol: 'diamond', tier: 'subject'},
              {venue: 6, family: 'cbs', x: 430, y: 330, symbol: 'star', tier: 'subject'},
            ],
            faded: [{venue: 7, family: 'nbc', x: 500, y: 300}],
            legs: [
              {subject: 0, season: 2020, from: 1, to: 2, family: 'nbc',
               points: [1, 2, 3, 4, 5, 6, 7].map((i) => ({x: i * 10, y: i * 5}))},
              {subject: 0, season: 2021, from: 2, to: 3, family: 'cbs',
               points: [1, 2, 3, 4, 5, 6, 7, 8, 9].map((i) => ({x: i * 11, y: i * 4}))},
              {subject: 0, season: 2021, from: 3, to: 4, family: 'nbc',
               points: [1, 2, 3].map((i) => ({x: i * 13, y: i * 3}))},
            ],
            markers: [
              {x: 955, y: 30, label: '<b>x</b>', side: 'left', family: 'fox', faded: false},
              {x: 120, y: 575, label: 'Sydney', side: 'right', family: 'cbs', faded: true},
            ],
          };
          const build = (m, theme = 'light', mobile = false) =>
            C.buildMapFigure(m, G.US_STATES, {theme, mobile});
          const byName = (fig, n) => fig.traces.find((t) => t.name === n);
          """
        + body
        + "}"
    )


def test_trace_names_constant_across_models_themes_and_envs(
    guarded_page: Page, site_url: str
) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const out = [];
        for (const m of [empty, {...empty, dots: rich.dots}, rich]) {
          for (const theme of ['light', 'dark']) {
            for (const mobile of [false, true]) {
              out.push(build(m, theme, mobile).traces.map((t) => t.name));
            }
          }
        }
        return {runs: out, names: [...C.MAP_TRACE_NAMES]};
        """,
    )
    expected = (
        ["outline"]
        + [f"legs:{f}" for f in _FAMILIES]
        + [f"inert:{f}" for f in _FAMILIES]
        + [f"dots:{f}" for f in _FAMILIES]
        + ["markers"]
    )
    assert got["names"] == expected
    assert len(expected) == 26
    for run in got["runs"]:
        assert run == expected


def test_outline_trace(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const t = byName(build(empty), 'outline');
        const rings = G.US_STATES.reduce((n, s) => n + s.rings.length, 0);
        return {
          nulls: t.x.filter((v) => v === null).length, rings, fill: t.fill,
          fillcolor: t.fillcolor, land: P.MAP_LAND.light, color: t.line.color,
          outline: P.MAP_OUTLINE.light, width: t.line.width, hover: t.hoverinfo,
          ynulls: t.y.filter((v) => v === null).length, mode: t.mode,
        };
        """,
    )
    assert got["nulls"] == got["rings"] - 1
    assert got["ynulls"] == got["nulls"]
    assert got["fill"] == "toself"
    assert got["fillcolor"] == got["land"]
    assert got["color"] == got["outline"]
    assert got["width"] == 0.6
    assert got["hover"] == "skip"
    assert got["mode"] == "lines"


def test_legs_traces(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const fig = build(rich);
        const nbc = byName(fig, 'legs:nbc');
        const cbs = byName(fig, 'legs:cbs');
        return {
          nbcX: nbc.x.length, nbcNulls: nbc.x.filter((v) => v === null).length,
          cbsX: cbs.x.length, color: nbc.line.color, want: P.FAMILY_COLORS.light.nbc,
          width: nbc.line.width, opacity: nbc.opacity, hover: nbc.hoverinfo,
          foxX: byName(fig, 'legs:fox').x.length,
        };
        """,
    )
    # nbc: 7 points + null + 3 points
    assert got["nbcX"] == 7 + 1 + 3
    assert got["nbcNulls"] == 1
    assert got["cbsX"] == 9
    assert got["color"] == got["want"]
    assert got["width"] == 1.25
    assert got["opacity"] == 0.55
    assert got["hover"] == "skip"
    assert got["foxX"] == 0


def test_dots_inert_and_markers(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const fig = build(rich);
        const fox = byName(fig, 'dots:fox');
        const inert = byName(fig, 'inert:nbc');
        const mk = byName(fig, 'markers');
        const mobileMk = byName(build(rich, 'light', true), 'markers');
        return {
          fox: {
            custom: fox.customdata, symbol: fox.marker.symbol, size: fox.marker.size,
            opacity: fox.marker.opacity, lw: fox.marker.line.width,
            lc: fox.marker.line.color, outline: P.DOT_OUTLINE,
            hoverinfo: fox.hoverinfo, ht: fox.hovertemplate,
          },
          cbs: {size: byName(fig, 'dots:cbs').marker.size},
          inert: {
            size: inert.marker.size, opacity: inert.marker.opacity, hoverinfo: inert.hoverinfo,
            ht: inert.hovertemplate, custom: inert.customdata ?? null, n: inert.x.length,
          },
          mk: {
            symbol: mk.marker.symbol, size: mk.marker.size, lw: mk.marker.line.width,
            colors: mk.marker.line.color, opacity: mk.marker.opacity, pos: mk.textposition,
            font: mk.textfont.size, fontColor: mk.textfont.color, muted: P.MUTED.light,
            text: mk.text, fox: P.FAMILY_COLORS.light.fox, cbs: P.FAMILY_COLORS.light.cbs,
          },
          mobileFont: mobileMk.textfont.size,
        };
        """,
    )
    fox = got["fox"]
    assert fox["custom"] == [3, 4, 5]
    assert fox["symbol"] == ["circle", "circle", "diamond"]
    assert fox["size"] == [7, 7, 10]
    assert fox["opacity"] == [0.6, 0.45, 0.85]
    assert fox["lw"] == [0, 0, 1]
    assert fox["lc"][2] == fox["outline"]
    assert fox["hoverinfo"] == "none"
    assert fox["ht"] is None
    assert got["cbs"]["size"] == [12]
    inert = got["inert"]
    assert inert["size"] == 7
    assert inert["opacity"] == 0.15
    assert inert["hoverinfo"] == "skip"
    assert inert["ht"] is None
    assert inert["custom"] is None
    assert inert["n"] == 1
    mk = got["mk"]
    assert mk["symbol"] == "circle-open"
    assert mk["size"] == 9
    assert mk["lw"] == 1.5
    assert mk["colors"] == [mk["fox"], mk["cbs"]]
    assert mk["opacity"] == [0.6, 0.15]
    assert mk["pos"] == ["middle left", "middle right"]
    assert mk["font"] == 12
    assert mk["fontColor"] == mk["muted"]
    assert got["mobileFont"] == 10
    assert mk["text"][0] == "&lt;b&gt;x&lt;/b&gt;"
    assert "<b>" not in "".join(mk["text"])


def test_layout_and_config(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const d = build(rich, 'dark', false);
        const m = build(rich, 'light', true);
        const pick = (f) => ({
          xv: f.layout.xaxis.visible, yv: f.layout.yaxis.visible,
          xr: f.layout.xaxis.range, yr: f.layout.yaxis.range,
          sa: f.layout.yaxis.scaleanchor, sr: f.layout.yaxis.scaleratio,
          con: f.layout.xaxis.constrain, drag: f.layout.dragmode,
          xfix: f.layout.xaxis.fixedrange, yfix: f.layout.yaxis.fixedrange,
          hd: f.layout.hoverdistance, ui: f.layout.uirevision,
          paper: f.layout.paper_bgcolor, plot: f.layout.plot_bgcolor,
          legend: f.layout.showlegend, cfg: f.config,
        });
        return {d: pick(d), m: pick(m), bg: P.PAGE_BG.dark, mbg: P.PAGE_BG.light};
        """,
    )
    d, m = got["d"], got["m"]
    for f in (d, m):
        assert f["xv"] is False
        assert f["yv"] is False
        assert f["xr"] == [0, 975]
        assert f["yr"] == [610, 0]
        assert f["sa"] == "x"
        assert f["sr"] == 1
        assert f["con"] == "domain"
        assert f["ui"] == "map"
        assert f["legend"] is False
        assert f["cfg"]["scrollZoom"] is False
        assert f["cfg"]["modeBarButtonsToRemove"] == ["lasso2d", "select2d"]
        assert f["cfg"]["responsive"] is True
        assert f["cfg"]["displaylogo"] is False
    assert d["drag"] == "zoom"
    assert d["xfix"] is False
    assert d["yfix"] is False
    assert d["cfg"]["displayModeBar"] is True
    assert d["paper"] == got["bg"]
    assert d["plot"] == got["bg"]
    assert m["drag"] is False
    assert m["xfix"] is True
    assert m["yfix"] is True
    assert m["hd"] == 22
    assert m["cfg"]["displayModeBar"] is False
    assert m["paper"] == got["mbg"]


def test_land_and_outline_contrast(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const r = {};
        for (const t of ['light', 'dark']) {
          r[t] = [P.contrastRatio(P.MAP_OUTLINE[t], P.MAP_LAND[t]),
                  P.contrastRatio(P.MAP_LAND[t], P.PAGE_BG[t])];
        }
        return r;
        """,
    )
    for theme in ("light", "dark"):
        outline_vs_land, land_vs_page = got[theme]
        assert outline_vs_land >= 1.4
        assert land_vs_page <= 1.2


# ---------------------------------------------------------------- Task 2: geometry, render, events

_RICH_MODEL = """{
  dots: [
    {venue: 3, family: 'nbc', x: 400, y: 300, symbol: 'circle', tier: 'base'},
    {venue: 4, family: 'fox', x: 700, y: 450, symbol: 'circle', tier: 'base'},
  ],
  faded: [{venue: 7, family: 'nbc', x: 200, y: 150}],
  legs: [{subject: 0, season: 2020, from: 1, to: 2, family: 'fox',
          points: [{x: 400, y: 300}, {x: 550, y: 350}, {x: 700, y: 450}]}],
  markers: [{x: 800, y: 80, label: 'Dublin', side: 'left', family: 'cbs', faded: false}],
}"""

_MOUNT = """
async ([model, width, height, mobile]) => {
  const C = await import('./modules/map-chart.js');
  const G = await import('./vendor/us-states-albers.js');
  document.getElementById('map-test')?.remove();
  const div = document.createElement('div');
  div.id = 'map-test';
  div.style.cssText = `position:fixed;top:0;left:0;width:${width}px;height:${height}px;`
    + 'z-index:9999';
  document.body.appendChild(div);
  window.__mapTest = {calls: [], C, G};
  await C.renderMap(div, C.buildMapFigure(MODEL, G.US_STATES, {theme: 'light', mobile}));
  C.bindMapEvents(div, {
    onVenueClick: (v, f) => window.__mapTest.calls.push(['click', v, f]),
    onVenueHover: (v, f) => window.__mapTest.calls.push(['hover', v, f]),
  });
  return true;
}
""".replace("MODEL", _RICH_MODEL)

_PX = """
([x, y]) => {
  const gd = document.getElementById('map-test');
  const r = gd.getBoundingClientRect();
  const fl = gd._fullLayout;
  return [r.left + fl.xaxis._offset + fl.xaxis.l2p(x), r.top + fl.yaxis._offset + fl.yaxis.l2p(y)];
}
"""

_PLOT_BOX = """
() => {
  const gd = document.getElementById('map-test');
  const fl = gd._fullLayout;
  return {
    l: fl.xaxis._offset, t: fl.yaxis._offset, w: fl.xaxis._length, h: fl.yaxis._length,
    pw: gd.getBoundingClientRect().width, ph: gd.getBoundingClientRect().height,
    n: gd.data.length,
  };
}
"""


def _mount(page: Page, site_url: str, width: int, height: int, mobile: bool = False) -> None:
    _load(page, site_url)
    page.evaluate(_MOUNT, [None, width, height, mobile])


def _px(page: Page, x: float, y: float) -> tuple[float, float]:
    px, py = page.evaluate(_PX, [x, y])
    return px, py


def test_projection_lands_in_vendored_state_rings(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const M = await import('./modules/map-model.js');
        const inside = (ring, x, y) => {
          let c = false;
          const n = ring.length / 2;
          for (let i = 0, j = n - 1; i < n; j = i, i += 1) {
            const xi = ring[2 * i], yi = ring[2 * i + 1], xj = ring[2 * j], yj = ring[2 * j + 1];
            if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c;
          }
          return c;
        };
        const stateOf = (pt) => {
          if (!pt) return null;
          for (const s of G.US_STATES) {
            let n = 0;
            for (const r of s.rings) if (inside(r, pt.x, pt.y)) n += 1;
            if (n % 2 === 1) return s.id;
          }
          return null;
        };
        return {
          sb: stateOf(M.projectAlbersUsa(-86.234, 41.698, 'IN')),
          la: stateOf(M.projectAlbersUsa(-118.2, 34.0, 'CA')),
          hi: stateOf(M.projectAlbersUsa(-157.86, 21.3, 'HI')),
          lnk: stateOf(M.projectAlbersUsa(-96.7056, 40.8206, 'NE')),
          atl: stateOf(M.projectAlbersUsa(-84.4008, 33.7554, 'GA')),
          bou: stateOf(M.projectAlbersUsa(-105.2669, 40.0095, 'CO')),
          nas: stateOf(M.projectAlbersUsa(-77.3, 25.05, null)),
          count: G.US_STATES.length,
        };
        """,
    )
    assert got["sb"] == "18"
    assert got["la"] == "06"
    assert got["hi"] == "15"
    assert got["lnk"] == "31"
    assert got["atl"] == "13"
    assert got["bou"] == "08"
    assert got["nas"] is None
    assert got["count"] == 50


def test_render_centers_at_desktop_and_phone_widths(guarded_page: Page, site_url: str) -> None:
    page = guarded_page
    _mount(page, site_url, 1280, 520)
    box = page.evaluate(_PLOT_BOX)
    assert box["n"] == 26
    left = box["l"]
    right = box["pw"] - box["l"] - box["w"]
    assert abs(left - right) <= 2
    assert abs(box["w"] / box["h"] - 975 / 610) / (975 / 610) <= 0.01
    _mount(page, site_url, 360, 520, mobile=True)
    box = page.evaluate(_PLOT_BOX)
    above = box["t"]
    below = box["ph"] - box["t"] - box["h"]
    assert abs(above - below) <= 2
    assert abs(box["w"] / box["h"] - 975 / 610) / (975 / 610) <= 0.01


def test_events_only_from_active_dots(guarded_page: Page, site_url: str) -> None:
    page = guarded_page
    _mount(page, site_url, 1280, 520)
    ax, ay = _px(page, 400, 300)
    page.mouse.move(ax - 60, ay - 60)
    page.mouse.move(ax, ay, steps=4)
    page.wait_for_timeout(200)
    calls = page.evaluate("window.__mapTest.calls")
    labels = page.locator("#map-test .hoverlayer .hovertext").count()
    assert ["hover", 3, "nbc"] in calls
    assert labels == 0
    page.mouse.click(ax, ay)
    page.wait_for_timeout(200)
    assert ["click", 3, "nbc"] in page.evaluate("window.__mapTest.calls")
    before = len(page.evaluate("window.__mapTest.calls"))
    ix, iy = _px(page, 200, 150)
    page.mouse.move(ix, iy, steps=4)
    mx, my = _px(page, 800, 80)
    page.mouse.move(mx, my, steps=4)
    page.mouse.click(mx, my)
    page.wait_for_timeout(200)
    assert len(page.evaluate("window.__mapTest.calls")) == before


def test_react_keeps_traces_and_double_click_resets(guarded_page: Page, site_url: str) -> None:
    page = guarded_page
    _mount(page, site_url, 1280, 520)
    got = page.evaluate(
        """async () => {
          const {C, G} = window.__mapTest;
          const gd = document.getElementById('map-test');
          const fig = C.buildMapFigure({dots: [], faded: [], legs: [], markers: []},
            G.US_STATES, {theme: 'dark', mobile: false});
          await C.renderMap(gd, fig);
          return gd.data.length;
        }"""
    )
    assert got == 26
    ax, ay = _px(page, 487, 305)
    page.evaluate(
        "() => window.Plotly.relayout(document.getElementById('map-test'),"
        " {'xaxis.range': [100, 300]})"
    )
    page.mouse.dblclick(ax, ay)
    page.wait_for_timeout(300)
    rng = page.evaluate("document.getElementById('map-test')._fullLayout.xaxis.range")
    assert abs(rng[0]) <= 0.5
    assert abs(rng[1] - 975) <= 0.5
