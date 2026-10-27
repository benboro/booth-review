"""Shared helpers for the dark-mode e2e files (17-05): flip the theme, find white boxes.

`set_theme` flips `data-theme` the way a test can (the real toggle click is exercised
separately in each sport's file). `white_box_offenders` scans the chart surfaces for any
painted box lighter than the dark ground, which a missed repaint would leave behind.
"""

from __future__ import annotations

from typing import Any

from playwright.sync_api import Page

# Relative luminance of #434B48: anything brighter that paints a box is a white-box offender.
_THRESHOLD_HEX = "#434B48"


def rgb(hex_color: str) -> str:
    """'#RRGGBB' -> the 'rgb(r, g, b)' string a browser reports for a computed colour."""
    value = hex_color.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgb({r}, {g}, {b})"


def set_theme(page: Page, theme: str) -> None:
    """Flips data-theme; onThemeChange fires exactly as it does for the toggle."""
    page.evaluate("(t) => document.documentElement.setAttribute('data-theme', t)", theme)
    page.wait_for_function("(t) => document.documentElement.dataset.theme === t", arg=theme)
    settle(page)


def click_toggle(page: Page) -> None:
    """Clicks the real #theme-toggle and lets the repaint settle."""
    page.locator("#theme-toggle").click()
    settle(page)


def settle(page: Page) -> None:
    """Waits two animation frames plus any pending Plotly react."""
    page.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
    page.wait_for_timeout(400)


_OFFENDERS_JS = """
(thresholdHex) => {
  const lum = (r, g, b) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const t = thresholdHex.slice(1).match(/../g).map((h) => parseInt(h, 16));
  const limit = lum(t[0], t[1], t[2]);
  const parse = (s) => {
    const m = /rgba?\\(([^)]+)\\)/.exec(s || '');
    if (!m) return null;
    const p = m[1].split(',').map((x) => parseFloat(x));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const out = [];
  const check = (el, label, value) => {
    const c = parse(value);
    if (!c || c.a < 0.5) return;
    if (lum(c.r, c.g, c.b) > limit) out.push(label + ' ' + value);
  };
  const roots = document.querySelectorAll(
    '.js-plotly-plot, .hoverlayer, #chart-tooltip, #reset-zoom, .reset-zoom, ' +
    '.band-info, .band-note');
  for (const root of roots) {
    const nodes = [root, ...root.querySelectorAll('*')];
    for (const el of nodes) {
      // Pills, dots and swatches are intentional fills (an ink role pill, family colours).
      if (el.closest('.pill, .role-pill, .net-dot, .legend-dot, [class*="swatch"]')) continue;
      const box = el.getBoundingClientRect();
      if (box.width === 0 || box.height === 0) continue;
      const cs = getComputedStyle(el);
      if (el instanceof SVGElement) {
        const cls = (el.getAttribute('class') || '');
        // Plotly paints its backgrounds as rects: paper (.bg) and hover boxes.
        const isBox = el.tagName.toLowerCase() === 'rect'
          && (cls.split(' ').includes('bg') || el.closest('.hoverlayer') || el.closest('.legend'));
        if (isBox) check(el, 'svg-rect.' + cls, cs.fill);
      } else {
        check(el, el.tagName.toLowerCase() + '#' + el.id + '.' + el.className, cs.backgroundColor);
      }
    }
  }
  return out;
}
"""


def white_box_offenders(page: Page) -> list[str]:
    """Every painted chart-area box lighter than #434B48 (empty in a correct dark page)."""
    result: list[str] = page.evaluate(_OFFENDERS_JS, _THRESHOLD_HEX)
    return result


def chart_layout(page: Page, selector: str = "#chart") -> dict[str, Any]:
    """The colour- and range-bearing parts of the Plotly chart at `selector`."""
    result: dict[str, Any] = page.evaluate(
        """
        (sel) => {
          const gd = document.querySelector(sel);
          const l = gd.layout;
          const fl = gd._fullLayout;
          return {
            paper: l.paper_bgcolor, plot: l.plot_bgcolor,
            font: l.font && l.font.color,
            grid: l.xaxis && l.xaxis.gridcolor,
            gridY: l.yaxis && l.yaxis.gridcolor,
            tick: l.xaxis && l.xaxis.tickfont && l.xaxis.tickfont.color,
            hoverBg: l.hoverlabel && l.hoverlabel.bgcolor,
            hoverInk: l.hoverlabel && l.hoverlabel.font && l.hoverlabel.font.color,
            xrange: fl.xaxis.range.slice(), yrange: fl.yaxis.range.slice(),
            shapes: (l.shapes || []).map((s) => ({ type: s.type, fill: s.fillcolor,
                                                  line: s.line && s.line.color })),
          };
        }
        """,
        selector,
    )
    return result
