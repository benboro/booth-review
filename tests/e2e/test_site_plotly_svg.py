"""04.18 spike: the vendored Plotly 4.1.1 SVG `scatter` behaviors the Map builds on.

Kept as a regression test. Synthetic traces only; each test mounts a throwaway div on
the loaded app page and drives it with the real mouse.
"""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

# Every trace below is an SVG `type: 'scatter'` (never the WebGL variant).

_LAYOUT = """{
  xaxis: {range: [0, 975], visible: false, constrain: 'domain'},
  yaxis: {range: [610, 0], visible: false, scaleanchor: 'x', scaleratio: 1, constrain: 'domain'},
  margin: {l: 0, r: 0, t: 0, b: 0}, hovermode: 'closest', dragmode: 'zoom',
  showlegend: false, uirevision: 'map'
}"""
_CONFIG = "{responsive: true, scrollZoom: false, displaylogo: false}"

_MOUNT = """
async ({traces, width, height}) => {
  document.getElementById('svg-spike')?.remove();
  const div = document.createElement('div');
  div.id = 'svg-spike';
  div.style.cssText = `position:fixed;top:0;left:0;width:${width}px;height:${height}px;`
    + 'background:#fff;z-index:9999';
  document.body.appendChild(div);
  window.__svgSpike = [];
  await window.Plotly.newPlot(div, traces, LAYOUT, CONFIG);
  div.on('plotly_hover', (e) => {
    const p = e.points[0];
    window.__svgSpike.push(['hover', p.curveNumber, p.customdata]);
  });
  div.on('plotly_click', (e) => {
    const p = e.points[0];
    window.__svgSpike.push(['click', p.curveNumber, p.customdata]);
  });
  return true;
}
""".replace("LAYOUT", _LAYOUT).replace("CONFIG", _CONFIG)

_POINT_PX = """
([x, y]) => {
  const gd = document.getElementById('svg-spike');
  const r = gd.getBoundingClientRect();
  const fl = gd._fullLayout;
  return [r.left + fl.xaxis._offset + fl.xaxis.l2p(x), r.top + fl.yaxis._offset + fl.yaxis.l2p(y)];
}
"""


def _load(page: Page, site_url: str) -> None:
    page.goto(f"{site_url}/index.html")
    page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")


def _mount(page: Page, traces: list[dict[str, Any]], width: int = 900, height: int = 520) -> None:
    page.evaluate(_MOUNT, {"traces": traces, "width": width, "height": height})


def _px(page: Page, x: float, y: float) -> tuple[float, float]:
    px, py = page.evaluate(_POINT_PX, [x, y])
    return px, py


def test_svg_scatter_hover_none_fires_events(guarded_page: Page, site_url: str) -> None:
    page = guarded_page
    _load(page, site_url)
    _mount(
        page,
        [
            {
                "type": "scatter",
                "mode": "markers",
                "x": [100],
                "y": [100],
                "hoverinfo": "skip",
                "hovertemplate": None,
                "marker": {"size": 10},
            },
            {
                "type": "scatter",
                "mode": "markers",
                "x": [300],
                "y": [200],
                "customdata": [7],
                "hoverinfo": "none",
                "hovertemplate": None,
                "marker": {"size": 10},
            },
        ],
    )
    ax, ay = _px(page, 300, 200)
    page.mouse.move(ax - 40, ay - 40)
    page.mouse.move(ax, ay, steps=4)
    page.wait_for_timeout(200)
    events = page.evaluate("window.__svgSpike")
    labels = page.locator("#svg-spike .hoverlayer .hovertext").count()
    assert ["hover", 1, 7] in events
    assert labels == 0
    page.mouse.click(ax, ay)
    page.wait_for_timeout(200)
    events = page.evaluate("window.__svgSpike")
    assert ["click", 1, 7] in events
    before = len(events)
    ix, iy = _px(page, 100, 100)
    page.mouse.move(ix, iy, steps=4)
    page.wait_for_timeout(200)
    after = len(page.evaluate("window.__svgSpike"))
    assert after == before


def test_svg_fill_toself_fills_each_ring(guarded_page: Page, site_url: str) -> None:
    page = guarded_page
    _load(page, site_url)
    _mount(
        page,
        [
            {
                "type": "scatter",
                "mode": "lines",
                "fill": "toself",
                "connectgaps": False,
                "x": [10, 50, 50, 10, 10, None, 100, 140, 140, 100, 100],
                "y": [10, 10, 50, 50, 10, None, 10, 10, 50, 50, 10],
                "hoverinfo": "skip",
            }
        ],
    )
    info = page.evaluate(
        """() => {
          const ds = [...document.querySelectorAll('#svg-spike .scatterlayer .trace .js-fill')]
            .map((p) => p.getAttribute('d') || '');
          const rings = ds.reduce((n, d) => n + (d.match(/M/g) || []).length, 0);
          return {paths: ds.length, rings};
        }"""
    )
    paths = info["paths"]
    rings = info["rings"]
    assert paths >= 1
    assert rings >= 2 or paths >= 2


@pytest.mark.parametrize("width", [360, 1280])
def test_scaleanchor_centers_fixed_aspect(guarded_page: Page, site_url: str, width: int) -> None:
    page = guarded_page
    _load(page, site_url)
    _mount(
        page,
        [{"type": "scatter", "mode": "markers", "x": [1], "y": [1], "hoverinfo": "skip"}],
        width=width,
        height=520,
    )
    m = page.evaluate(
        """() => {
          const fl = document.getElementById('svg-spike')._fullLayout;
          return {xl: fl.xaxis._length, yl: fl.yaxis._length, xo: fl.xaxis._offset,
                  yo: fl.yaxis._offset, w: fl.width, h: fl.height};
        }"""
    )
    ratio = m["xl"] / m["yl"]
    assert abs(ratio - 975 / 610) / (975 / 610) < 0.01
    left, right = m["xo"], m["w"] - m["xo"] - m["xl"]
    top, bottom = m["yo"], m["h"] - m["yo"] - m["yl"]
    if width == 360:
        assert abs(top - bottom) <= 2
        assert top > 20
    else:
        assert abs(left - right) <= 2
        assert left > 20


def test_double_click_resets_zoom(guarded_page: Page, site_url: str) -> None:
    page = guarded_page
    _load(page, site_url)
    _mount(page, [{"type": "scatter", "mode": "markers", "x": [1], "y": [1], "hoverinfo": "skip"}])
    page.evaluate(
        "() => window.Plotly.relayout(document.getElementById('svg-spike'),"
        " {'xaxis.range': [100, 300], 'yaxis.range': [300, 100]})"
    )
    zoomed = page.evaluate("document.getElementById('svg-spike')._fullLayout.xaxis.range")
    assert abs(zoomed[0] - 100) < 0.5
    cx, cy = _px(page, 200, 200)
    page.mouse.dblclick(cx, cy)
    page.wait_for_timeout(400)
    rng = page.evaluate("document.getElementById('svg-spike')._fullLayout.xaxis.range")
    lo, hi = rng[0], rng[1]
    assert abs(lo - 0) < 0.5
    assert abs(hi - 975) < 0.5
