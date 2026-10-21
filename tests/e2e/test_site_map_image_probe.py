"""Phase 11 Wave-0 probe: Plotly layout.images under the Map's reversed y-axis.

Pins where a raster placed with layout.images lands on the Map's axes (x 0..975,
y 610..0 reversed), that relayout of images keeps a drag-zoomed range, and prints the
cost of drawing, encoding and relaying out the land raster. Timing is printed, never
asserted. Synthetic fixture build only.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

# Shared in-page helpers, evaluated once per page via add_script-like string prefix.
_SETUP = """
async () => {
  const C = await import('./modules/map-chart.js');
  const G = await import('./vendor/us-states-albers.js');
  const fig = C.buildMapFigure({venueDots: [], venueFaded: [], legs: [], markers: []},
                               G.US_STATES, {theme: 'light', mobile: false});
  const div = document.createElement('div');
  div.id = 'probe-gd';
  div.style.cssText = 'position:fixed;top:0;left:0;width:1000px;height:640px;'
    + 'z-index:9999;background:#ffffff';
  document.body.appendChild(div);
  const layout = {...fig.layout, width: 1000, height: 640, autosize: false,
                  margin: {l: 0, r: 0, t: 0, b: 0}};
  await window.Plotly.newPlot(div, [{type: 'scatter', mode: 'markers', x: [], y: []}],
                              layout, {staticPlot: false});
  window.__probe = {urls: []};
  window.__probe.spec = (url, yanchor) => ({
    source: url, xref: 'x', yref: 'y', x: 0, y: 0, sizex: 975, sizey: 610,
    xanchor: 'left', yanchor, sizing: 'stretch', layer: 'below', opacity: 1,
  });
  window.__probe.frames = () => new Promise((r) =>
    requestAnimationFrame(() => requestAnimationFrame(r)));
  window.__probe.loaded = async (url) => {
    const img = new Image();
    img.src = url;
    await img.decode();
    await window.__probe.frames();
    return img.naturalWidth;
  };
  window.__probe.apply = async (blob, yanchor) => {
    const url = URL.createObjectURL(blob);
    window.__probe.urls.push(url);
    await window.Plotly.relayout(div, {images: [window.__probe.spec(url, yanchor)]});
    await window.__probe.loaded(url);
    return url;
  };
  return true;
}
"""


def _mount(page: Page, site_url: str) -> None:
    page.goto(f"{site_url}/index.html")
    page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    page.evaluate(_SETUP)


def _blocks_blob_js(scale: int = 1) -> str:
    return f"""
      const c = new OffscreenCanvas(975 * {scale}, 610 * {scale});
      const g = c.getContext('2d');
      g.setTransform({scale}, 0, 0, {scale}, 0, 0);
      g.fillStyle = '#ff0000'; g.fillRect(100, 60, 30, 30);
      g.fillStyle = '#0000ff'; g.fillRect(800, 500, 30, 30);
      const blob = await c.convertToBlob({{type: 'image/png'}});
    """


def _screen_pixel(page: Page, points: list[tuple[float, float]]) -> list[list[int]]:
    """Screenshot the probe div and read the RGB under each map point."""
    coords = page.evaluate(
        """(pts) => {
          const gd = document.getElementById('probe-gd');
          const fl = gd._fullLayout;
          return pts.map(([x, y]) => [
            fl.xaxis._offset + fl.xaxis.l2p(x),
            fl.yaxis._offset + fl.yaxis.l2p(y),
          ]);
        }""",
        [list(p) for p in points],
    )
    png = page.locator("#probe-gd").screenshot()
    b64 = base64.b64encode(png).decode()
    return page.evaluate(
        """async ([b64, coords]) => {
          const bin = Uint8Array.from(atob(b64), (ch) => ch.charCodeAt(0));
          const bmp = await createImageBitmap(new Blob([bin], {type: 'image/png'}));
          const cv = new OffscreenCanvas(bmp.width, bmp.height);
          const g = cv.getContext('2d');
          g.drawImage(bmp, 0, 0);
          return coords.map(([x, y]) => {
            const d = g.getImageData(Math.round(x), Math.round(y), 1, 1).data;
            return [d[0], d[1], d[2]];
          });
        }""",
        [b64, coords],
    )


def _is(px: list[int], color: str) -> bool:
    r, g, b = px
    if color == "red":
        return r > 200 and g < 60 and b < 60
    return b > 200 and r < 60 and g < 60


def _probe_anchor(page: Page, site_url: str, candidate: str) -> bool:
    _mount(page, site_url)
    page.evaluate(
        "async (cand) => {" + _blocks_blob_js() + "await window.__probe.apply(blob, cand);}",
        candidate,
    )
    red, blue = _screen_pixel(page, [(115, 75), (815, 515)])
    ok = _is(red, "red") and _is(blue, "blue")
    page.evaluate("() => { window.__probe.urls.forEach((u) => URL.revokeObjectURL(u)); }")
    return ok


def test_image_anchor_covers_map_space(guarded_page: Page, site_url: str) -> None:
    results = {c: _probe_anchor(guarded_page, site_url, c) for c in ("top", "bottom")}
    winners = [c for c, ok in results.items() if ok]
    print(f"ANCHOR_RESULTS={results}")
    assert len(winners) == 1, results
    print(f"IMAGE_YANCHOR={winners[0]}")


def test_relayout_images_keeps_zoom(guarded_page: Page, site_url: str) -> None:
    winner = next(c for c in ("top", "bottom") if _probe_anchor(guarded_page, site_url, c))
    _mount(guarded_page, site_url)
    got: dict[str, Any] = guarded_page.evaluate(
        "async (anchor) => {"
        + _blocks_blob_js()
        + """
        await window.__probe.apply(blob, anchor);
        const gd = document.getElementById('probe-gd');
        await window.Plotly.relayout(gd, {'xaxis.range': [200, 500],
                                          'yaxis.range': [400, 150]});
        const before = [gd.layout.xaxis.range.slice(), gd.layout.yaxis.range.slice()];
        await window.__probe.apply(blob, anchor);
        const after = [gd.layout.xaxis.range.slice(), gd.layout.yaxis.range.slice()];
        window.__probe.urls.forEach((u) => URL.revokeObjectURL(u));
        return {before, after};
        }""",
        winner,
    )
    for b_axis, a_axis in zip(got["before"], got["after"], strict=True):
        for b, a in zip(b_axis, a_axis, strict=True):
            assert abs(b - a) < 1e-6
    assert got["after"][0] == pytest.approx([200, 500])
    assert got["after"][1] == pytest.approx([400, 150])


_TIMING_JS = """
async ([anchor, scale, runs]) => {
  const G = await import('./vendor/us-states-albers.js');
  const gd = document.getElementById('probe-gd');
  const land = new Path2D();
  for (const s of G.US_STATES) {
    for (const ring of s.rings) {
      land.moveTo(ring[0], ring[1]);
      for (let i = 2; i < ring.length; i += 2) land.lineTo(ring[i], ring[i + 1]);
      land.closePath();
    }
  }
  const cell = 3;
  const gw = Math.ceil(975 / cell), gh = Math.ceil(610 / cell);
  const data = new ImageData(gw, gh);
  let seed = 12345;
  const rnd = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296;
  for (let i = 0; i < gw * gh; i++) {
    data.data[i * 4] = Math.floor(rnd() * 255);
    data.data[i * 4 + 1] = Math.floor(rnd() * 255);
    data.data[i * 4 + 2] = Math.floor(rnd() * 255);
    data.data[i * 4 + 3] = Math.floor(rnd() * 225);
  }
  const small = new OffscreenCanvas(gw, gh);
  small.getContext('2d').putImageData(data, 0, 0);

  const once = async (prev) => {
    const t0 = performance.now();
    const c = new OffscreenCanvas(975 * scale, 610 * scale);
    const g = c.getContext('2d');
    g.setTransform(scale, 0, 0, scale, 0, 0);
    g.fillStyle = '#F1F2F5';
    g.fill(land);
    g.save();
    g.clip(land);
    g.imageSmoothingEnabled = true;
    g.imageSmoothingQuality = 'high';
    g.drawImage(small, 0, 0, gw * cell, gh * cell);
    g.restore();
    const t1 = performance.now();
    const blob = await c.convertToBlob({type: 'image/png'});
    const t2 = performance.now();
    const url = URL.createObjectURL(blob);
    await window.Plotly.relayout(gd, {images: [window.__probe.spec(url, anchor)]});
    const t3 = performance.now();
    if (prev) URL.revokeObjectURL(prev);
    return {url, size: blob.size, draw: t1 - t0, encode: t2 - t1, relayout: t3 - t2};
  };
  let prev = null;
  for (let i = 0; i < 2; i++) prev = (await once(prev)).url;
  const rows = [];
  for (let i = 0; i < runs; i++) {
    const r = await once(prev);
    prev = r.url;
    rows.push(r);
  }
  if (prev) URL.revokeObjectURL(prev);
  const p95 = (k) => {
    const v = rows.map((r) => r[k]).sort((a, b) => a - b);
    return v[Math.min(v.length - 1, Math.ceil(v.length * 0.95) - 1)];
  };
  const tot = rows.map((r) => r.draw + r.encode + r.relayout).sort((a, b) => a - b);
  return {
    draw: p95('draw'), encode: p95('encode'), relayout: p95('relayout'),
    total: tot[Math.min(tot.length - 1, Math.ceil(tot.length * 0.95) - 1)],
    minSize: Math.min(...rows.map((r) => r.size)),
  };
}
"""


def test_raster_encode_timing(guarded_page: Page, site_url: str) -> None:
    winner = next(c for c in ("top", "bottom") if _probe_anchor(guarded_page, site_url, c))
    _mount(guarded_page, site_url)
    cdp = guarded_page.context.new_cdp_session(guarded_page)
    try:
        for rate in (1, 4):
            cdp.send("Emulation.setCPUThrottlingRate", {"rate": rate})
            for scale in (2, 1):
                r = guarded_page.evaluate(_TIMING_JS, [winner, scale, 20])
                assert r["minSize"] > 0
                print(
                    f"TIMING scale={scale} throttle={rate} "
                    f"draw_p95={r['draw']:.1f} encode_p95={r['encode']:.1f} "
                    f"relayout_p95={r['relayout']:.1f} total_p95={r['total']:.1f}"
                )
    finally:
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
