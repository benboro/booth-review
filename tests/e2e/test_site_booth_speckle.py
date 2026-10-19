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

_THEMES = ["light", "dark"]
_CELL = 40
_COLS = 10
_ROWS = 5

_MARKERS_JS = """
async (metas) => {
  const gd = document.getElementById('chart');
  const out = {};
  for (const t of gd.data) {
    if (metas.includes(String(t.meta))) out[String(t.meta)] = JSON.parse(JSON.stringify(t.marker));
  }
  const p = await import('./modules/palette.js');
  const theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
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


@pytest.mark.parametrize("theme", _THEMES)
@pytest.mark.parametrize("state", ["filled", "hollow"])
def test_lead_star_has_no_pixels_outside_the_glyph(
    guarded_page: Page,
    serve_booths: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
    theme: str,
    state: str,
) -> None:
    guarded_page.emulate_media(color_scheme=theme)  # type: ignore[arg-type]
    serve_booths(guarded_page)
    open_app(guarded_page, "")
    guarded_page.wait_for_timeout(150)
    metas = (
        ["lead:disney"]
        if state == "filled"
        else ["unrated-lead-halo:disney", "unrated-lead:disney"]
    )
    info: dict[str, Any] = guarded_page.evaluate(_MARKERS_JS, metas)
    layers = [info["markers"][m] for m in metas]
    for marker in layers:
        assert marker["symbol"] == "star"
        assert marker["line"]["width"] == 0
    largest = max(float(m["size"]) for m in layers)
    guarded_page.evaluate(_DRAW_JS, [layers, info["bg"], _CELL, _COLS, _ROWS])
    url = _data_url(guarded_page, _CELL * _COLS, _CELL * _ROWS)
    result = guarded_page.evaluate(
        _ANALYZE_JS, [url, _CELL, _COLS, _ROWS, largest / 2 + 2, info["bg"]]
    )
    assert result["inside"] > 0, "the star was not drawn at all"
    assert result["stray"] == 0, f"{result['stray']} stray pixels outside the {state} star"
