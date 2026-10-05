"""SITE-49 (04.12 D-01..D-04): scatter x-axis edge gutter."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


@pytest.fixture
def app_page(guarded_page: Page, open_app: Callable[[Page, str], None]) -> Page:
    """The app loaded once so `import('./modules/...')` resolves."""
    open_app(guarded_page, "")
    return guarded_page


def test_gutter_px_constant(app_page: Page) -> None:
    got = app_page.evaluate("async () => (await import('./modules/gutter.js')).GUTTER_PX")
    assert got == 10


def test_gutter_pads_closed_form(app_page: Page) -> None:
    got = app_page.evaluate(
        """async () => {
          const { gutterPads } = await import('./modules/gutter.js');
          return gutterPads(278, 1138);
        }"""
    )
    expected = 10 * 278 / (1138 - 20)
    assert got == [pytest.approx(expected), pytest.approx(expected)]


_GRID_JS = """
async () => {
  const { gutterPads, GUTTER_PX } = await import('./modules/gutter.js');
  let worst = Infinity;
  let bad = 0;
  let belowMin = 0;
  for (const plotPx of [150, 234, 266, 400, 700, 1000, 1138, 1400]) {
    for (const inner of [1, 87, 278, 2000]) {
      const mins = [
        [0, 0],
        [0.75 * 0.06 * inner, 0.03 * inner],
        [0.2 * inner, 0],
        [0, 0.2 * inner],
      ];
      for (const [minLo, minHi] of mins) {
        const [lo, hi] = gutterPads(inner, plotPx, { minLo, minHi });
        if (!Number.isFinite(lo) || !Number.isFinite(hi)) bad += 1;
        if (lo < minLo || hi < minHi) belowMin += 1;
        const t = inner + lo + hi;
        worst = Math.min(worst, (lo * plotPx) / t, (hi * plotPx) / t);
      }
    }
  }
  return { worst, bad, belowMin, px: GUTTER_PX };
}
"""


def test_gutter_pads_clear_px_across_widths(app_page: Page) -> None:
    got = app_page.evaluate(_GRID_JS)
    assert got["bad"] == 0
    assert got["belowMin"] == 0
    assert got["worst"] >= got["px"] - 1e-9


def test_gutter_pads_keeps_larger_mins(app_page: Page) -> None:
    got = app_page.evaluate(
        """async () => {
          const { gutterPads } = await import('./modules/gutter.js');
          return gutterPads(100, 1138, { minLo: 4.5, minHi: 3 });
        }"""
    )
    assert got == [4.5, 3]


def test_gutter_pads_degenerate_inputs(app_page: Page) -> None:
    got = app_page.evaluate(
        """async () => {
          const { gutterPads } = await import('./modules/gutter.js');
          const o = { minLo: 2, minHi: 1 };
          return [
            gutterPads(0, 1138, o),
            gutterPads(NaN, 1138, o),
            gutterPads(100, 20, o),
            gutterPads(100, undefined, o),
          ];
        }"""
    )
    assert got == [[2, 1]] * 4
