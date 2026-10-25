"""Phase 10 plan 10-08: lead stars never speckle (notes-2 #1), filled and hollow, both themes.

A scattergl star comes from the SDF glyph atlas; a `marker.line` on it breaks into stray pixels
outside the glyph. The figure's own star marker configs (read from `gd.data`, never hand-copied)
are drawn as isolated stars on a grid and every pixel outside the glyph's box must still be the
background colour.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_CELL = 40
_COLS = 10
_ROWS = 5

_MARKERS_JS = """
async (metas) => {
  const gd = document.getElementById('chart');
  const out = {};
  for (const t of gd.data) {
    if (!metas.includes(String(t.meta))) continue;
    const m = JSON.parse(JSON.stringify(t.marker));
    // A per-point marker (the highlight traces) is reduced to the lead game's own point.
    const at = Math.max(0, Array.from(t.customdata || []).indexOf(14));
    const keys = [[m, 'symbol'], [m, 'size'], [m, 'color'], [m.line, 'width'], [m.line, 'color']];
    for (const [obj, key] of keys) {
      if (obj && Array.isArray(obj[key])) obj[key] = obj[key][at];
    }
    out[String(t.meta)] = m;
  }
  const p = await import('./modules/palette.js');
  const theme = (document.documentElement.dataset.theme === 'dark') ? 'dark' : 'light';
  return { markers: out, bg: p.SURFACE[theme] };
}
"""

_DRAW_JS = """
async ([layers, bg, cell, cols, rows]) => {
  const old = document.getElementById('speckle-probe');
  if (old) old.remove();
  const w = cell * cols;
  const h = cell * rows;
  const div = document.createElement('div');
  div.id = 'speckle-probe';
  div.style.cssText = `position:fixed;left:0;top:0;z-index:99999;width:${w}px;height:${h}px;`;
  document.body.appendChild(div);
  const xs = [];
  const ys = [];
  for (let r = 0; r < rows; r += 1) {
    for (let c = 0; c < cols; c += 1) {
      xs.push(c * cell + cell / 2);
      ys.push(r * cell + cell / 2);
    }
  }
  const data = layers.map((marker) => ({
    type: 'scattergl', mode: 'markers', x: xs, y: ys, marker,
    hoverinfo: 'skip', showlegend: false,
  }));
  await window.Plotly.newPlot(div, data, {
    width: w, height: h, margin: { l: 0, r: 0, t: 0, b: 0 },
    paper_bgcolor: bg, plot_bgcolor: bg,
    xaxis: { range: [0, w], visible: false, fixedrange: true },
    yaxis: { range: [h, 0], visible: false, fixedrange: true },
  }, { staticPlot: true });
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
}
"""

_ANALYZE_JS = """
([url, cell, cols, rows, half, bg]) => new Promise((resolve) => {
  const img = new Image();
  img.onload = () => {
    const c = document.createElement('canvas');
    c.width = img.width; c.height = img.height;
    const ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(0, 0, img.width, img.height).data;
    const hex = (v) => parseInt(v, 16);
    const ref = [hex(bg.slice(1, 3)), hex(bg.slice(3, 5)), hex(bg.slice(5, 7))];
    let stray = 0;
    let inside = 0;
    for (let y = 0; y < cell * rows; y += 1) {
      for (let x = 0; x < cell * cols; x += 1) {
        const o = (y * img.width + x) * 4;
        const diff = Math.hypot(d[o] - ref[0], d[o + 1] - ref[1], d[o + 2] - ref[2]);
        if (diff <= 30) continue;
        const dx = Math.abs((x % cell) - cell / 2);
        const dy = Math.abs((y % cell) - cell / 2);
        if (Math.max(dx, dy) > half) stray += 1;
        else inside += 1;
      }
    }
    resolve({ stray, inside });
  };
  img.src = url;
})
"""


def _data_url(page: Page, width: int, height: int) -> str:
    png = page.screenshot(clip={"x": 0, "y": 0, "width": width, "height": height})
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


# state -> (query, marker metas drawn bottom to top). "hollow-outlined" is the no-rating star with
# the dot outline a filter adds (review F2); "hollow-highlighted" is it under a one-announcer
# highlight, its ACCENT open outline beneath the family open star (review F1).
_STATES = {
    "filled": ("", ["lead-halo:disney", "lead:disney"]),
    "hollow": ("", ["unrated-lead:disney"]),
    "hollow-outlined": (
        "?networks=net-a&dots=fade",
        ["unrated-lead-rim:disney", "unrated-lead:disney"],
    ),
    "hollow-highlighted": (
        "?people=casey-lund",
        ["highlight-halo-unrated-open", "highlight-unrated"],
    ),
}


@pytest.mark.parametrize("state", list(_STATES))
def test_lead_star_has_no_pixels_outside_the_glyph(
    guarded_page: Page,
    serve_booths: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
    state: str,
) -> None:
    query, metas = _STATES[state]
    serve_booths(guarded_page)
    open_app(guarded_page, query)
    guarded_page.wait_for_timeout(150)
    # The filled state is the cased star as drawn: surface casing star beneath the lead star.
    # The hollow (no-rating) star is a 14px open star with a line since Phase 17 (user sign-off).
    info: dict[str, Any] = guarded_page.evaluate(_MARKERS_JS, metas)
    layers = [info["markers"][m] for m in metas]
    for marker in layers:
        if state == "filled":
            assert marker["symbol"] == "star"
            assert marker["line"]["width"] == 0
        else:
            assert marker["symbol"] == "star-open"
            assert float(marker["size"]) >= 14
    largest = max(float(m["size"]) + float(m["line"]["width"]) for m in layers)
    # A star's top tip reaches about 0.65 of its size from the centre (11px at 17px), past the
    # size / 2 of a square marker, so the glyph box is 0.65 * size plus a 1px antialias margin.
    half = largest * 0.65 + 1
    guarded_page.evaluate(_DRAW_JS, [layers, info["bg"], _CELL, _COLS, _ROWS])
    url = _data_url(guarded_page, _CELL * _COLS, _CELL * _ROWS)
    result = guarded_page.evaluate(_ANALYZE_JS, [url, _CELL, _COLS, _ROWS, half, info["bg"]])
    assert result["inside"] > 0, "the star was not drawn at all"
    assert result["stray"] == 0, f"{result['stray']} stray pixels outside the {state} star"
