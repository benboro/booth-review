"""SITE-52 (04.13-17, notes-2 #1): the "No public rating" band's markers never speckle.

Plotly's scattergl draws an open symbol (`circle-open`, `star-open`, ...) from an SDF glyph
atlas, which breaks into pixelated squares at small sizes (notes2-band-speckle.png). Two guards:

- structural: no `scattergl` trace in any chart state carries an open symbol, so the glyph path
  that speckles is never taken;
- pixel: the band's real marker configs (read from `gd.data`, never hand-copied) are drawn at
  real-data density through `scattergl` and again through SVG `scatter` (analytic reference);
  the two renderings must agree to within a few pixels.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_WAIT_TWO_FRAMES = "() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"

_STATES = [
    "",
    "?school=northfield",
    "?school=northfield&dots=hide",
    "?people=pat-rowan",
    "?people=pat-rowan,sam-delgado&mode=compare",
    "?people=kris-venn,sam-delgado,dale-harlow,casey-lund&mode=compare",
    "?axis=excitement",
    "?axis=date",
    "?axis=date&seasons=2025-2026",
]

_THEMES = ["light", "dark"]

# One open-symbol scan over every scattergl trace: string symbols, array symbols, and numeric
# codes (Plotly's open variants are code % 200 > 100).
OPEN_SYMBOLS_JS = """
() => {
  const bad = [];
  const isOpen = (s) => {
    if (typeof s === 'number') return s % 200 > 100;
    return typeof s === 'string' && /-open(-dot)?$/.test(s);
  };
  for (const t of document.getElementById('chart').data) {
    if (t.type !== 'scattergl') continue;
    const sym = t.marker && t.marker.symbol;
    const list = Array.isArray(sym) || ArrayBuffer.isView(sym) ? Array.from(sym) : [sym];
    if (list.some(isOpen)) bad.push('open');
  }
  return bad.length;
}
"""

# Band marker configs by trace meta, straight from the live figure.
_BAND_MARKERS_JS = """
(metas) => {
  const gd = document.getElementById('chart');
  const out = {};
  for (const t of gd.data) {
    if (metas.includes(String(t.meta))) out[String(t.meta)] = JSON.parse(JSON.stringify(t.marker));
  }
  const fl = gd._fullLayout;
  return {
    markers: out,
    xRange: fl.xaxis.range.slice(),
    yRange: fl.yaxis2.range.slice(),
    bandHeight: Math.round(fl.yaxis2._length),
  };
}
"""

_THEME_JS = """
async () => {
  const p = await import('./modules/palette.js');
  const theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  return p.SURFACE[theme];
}
"""

# Draws a band-only figure in a fixed overlay div: `type` is 'scattergl' or 'scatter'. `spec.traces`
# is a list of {x, y, marker}; or `spec.synthetic` asks for deterministic points (dense: 7,000
# evenly spread x with the Weyl-hash y data.js uses for band jitter; grid: isolated markers on a
# 16px grid).
_DRAW_JS = """
async ([type, spec]) => {
  const old = document.getElementById('speckle-probe');
  if (old) old.remove();
  const div = document.createElement('div');
  div.id = 'speckle-probe';
  div.style.cssText = 'position:fixed;left:0;top:0;z-index:99999;'
    + `width:${spec.width}px;height:${spec.height}px;`;
  document.body.appendChild(div);
  const [x0, x1] = spec.xRange;
  const [y0, y1] = spec.yRange;
  let traces = spec.traces;
  if (spec.synthetic) {
    const xs = [];
    const ys = [];
    if (spec.synthetic === 'dense') {
      const n = 7000;
      for (let i = 0; i < n; i += 1) {
        xs.push(x0 + ((i + 0.5) / n) * (x1 - x0));
        ys.push((Math.imul(i + 1, 2654435761) >>> 0) / 4294967296);
      }
    } else {
      for (let py = 8; py < spec.height; py += 16) {
        for (let px = 8; px < spec.width; px += 16) {
          xs.push(x0 + (px / spec.width) * (x1 - x0));
          ys.push(y0 + (py / spec.height) * (y1 - y0));
        }
      }
    }
    traces = [{ x: xs, y: ys, marker: spec.marker }];
  }
  const data = traces.map((t) => ({
    type, mode: 'markers', x: t.x, y: t.y, marker: t.marker, hoverinfo: 'skip', showlegend: false,
  }));
  await window.Plotly.newPlot(div, data, {
    width: spec.width, height: spec.height, margin: { l: 0, r: 0, t: 0, b: 0 },
    paper_bgcolor: spec.bg, plot_bgcolor: spec.bg,
    xaxis: { range: [x0, x1], visible: false, fixedrange: true },
    yaxis: { range: [y0, y1], visible: false, fixedrange: true },
  }, { staticPlot: true });
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
}
"""

_DIFF_JS = """
([urlA, urlB]) => new Promise((resolve) => {
  const load = (u) => new Promise((ok) => {
    const i = new Image();
    i.onload = () => ok(i);
    i.src = u;
  });
  Promise.all([load(urlA), load(urlB)]).then(([a, b]) => {
    const px = (img) => {
      const c = document.createElement('canvas');
      c.width = img.width; c.height = img.height;
      const ctx = c.getContext('2d');
      ctx.drawImage(img, 0, 0);
      return ctx.getImageData(0, 0, img.width, img.height).data;
    };
    const da = px(a);
    const db = px(b);
    let differing = 0;
    for (let i = 0; i < da.length; i += 4) {
      const d = Math.hypot(da[i] - db[i], da[i + 1] - db[i + 1], da[i + 2] - db[i + 2]);
      if (d > 60) differing += 1;
    }
    resolve(differing);
  });
})
"""


def _shot(page: Page, width: int, height: int) -> str:
    png = page.screenshot(clip={"x": 0, "y": 0, "width": width, "height": height})
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def gl_vs_svg_diff(page: Page, spec: dict[str, Any]) -> int:
    """Pixels (RGB distance over 60) that differ between the GL and the SVG rendering of `spec`."""
    shots = []
    for kind in ("scattergl", "scatter"):
        page.evaluate(_DRAW_JS, [kind, spec])
        shots.append(_shot(page, spec["width"], spec["height"]))
    page.evaluate("() => document.getElementById('speckle-probe')?.remove()")
    return int(page.evaluate(_DIFF_JS, shots))


def _open(
    page: Page,
    open_app: Callable[[Page, str], None],
    query: str,
    theme: str,
    width: int,
) -> None:
    page.emulate_media(color_scheme=theme)  # type: ignore[arg-type]
    page.set_viewport_size({"width": width, "height": 900})
    open_app(page, query)
    page.evaluate(_WAIT_TWO_FRAMES)
    page.wait_for_timeout(150)


@pytest.mark.parametrize("theme", _THEMES)
@pytest.mark.parametrize("query", _STATES)
def test_no_scattergl_trace_uses_an_open_symbol(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    query: str,
    theme: str,
) -> None:
    """notes-2 #1: an open scattergl symbol speckles at small sizes; the figure never uses one."""
    _open(guarded_page, open_app, query, theme, 1280)
    open_traces: int = guarded_page.evaluate(OPEN_SYMBOLS_JS)
    assert open_traces == 0, f"{open_traces} scattergl trace(s) carry an open symbol at {query!r}"


# Calibrated (04.13-17): the speckled open-symbol band differs from its SVG reference by
# thousands of pixels; filled circles with a line stay within a handful.
_MAX_DIFF_DENSE = 400
_MAX_DIFF_GRID = 40

_BAND_CASES = [
    ("", "unrated-active:disney"),
    ("?school=northfield", "unrated-active:disney"),
    ("?school=northfield", "unrated-inert:disney"),
]


@pytest.mark.parametrize("width", [1280, 360])
@pytest.mark.parametrize("theme", _THEMES)
@pytest.mark.parametrize(("query", "meta"), _BAND_CASES)
@pytest.mark.parametrize("synthetic", ["dense", "grid"])
def test_band_markers_match_the_svg_reference_at_real_density(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    query: str,
    meta: str,
    theme: str,
    width: int,
    synthetic: str,
) -> None:
    """The band's own marker config, drawn through GL, matches the analytic SVG rendering."""
    _open(guarded_page, open_app, query, theme, width)
    info = guarded_page.evaluate(_BAND_MARKERS_JS, [meta])
    marker = info["markers"][meta]
    bg: str = guarded_page.evaluate(_THEME_JS)
    spec = {
        "synthetic": synthetic,
        "marker": marker,
        "xRange": info["xRange"],
        "yRange": info["yRange"],
        "bg": bg,
        "width": 600,
        "height": max(int(info["bandHeight"]), 48),
    }
    differing = gl_vs_svg_diff(guarded_page, spec)
    limit = _MAX_DIFF_DENSE if synthetic == "dense" else _MAX_DIFF_GRID
    assert differing <= limit, f"{differing} pixels differ from the SVG reference (limit {limit})"
