"""13-UI-SPEC "Wait for fonts" on a page opened straight on NFL: its first Plotly draw waits
(at most 1500ms) for Roboto Condensed, and a face that arrives later re-lays the chart out."""

from __future__ import annotations

import time

import pytest
from playwright.sync_api import Page, Route

pytestmark = pytest.mark.e2e

FACE = "**/roboto-condensed-latin-400-normal.woff2"

# Records, for every Plotly draw, whether Roboto Condensed had loaded by then.
RECORD_DRAWS = """(() => {
  window.__draws = [];
  let plotly;
  Object.defineProperty(window, 'Plotly', {
    configurable: true,
    get() { return plotly; },
    set(value) {
      plotly = value;
      for (const name of ['newPlot', 'react']) {
        const draw = value[name];
        value[name] = function (...args) {
          window.__draws.push(document.fonts.check('12px "Roboto Condensed"'));
          return draw.apply(this, args);
        };
      }
    },
  });
})()"""


def _delay_face(page: Page, seconds: float) -> None:
    def handler(route: Route) -> None:
        time.sleep(seconds)
        route.continue_()

    page.route(FACE, handler)


def _open_nfl(page: Page, nfl_site_url: str) -> None:
    page.add_init_script(RECORD_DRAWS)
    page.goto(f"{nfl_site_url}/index.html?sport=nfl", wait_until="commit")
    page.wait_for_function(
        "window.__nflTestHooks && window.__nflTestHooks.ready === true", timeout=15000
    )


def test_first_nfl_draw_waits_for_the_condensed_face(page: Page, nfl_site_url: str) -> None:
    _delay_face(page, 0.7)
    _open_nfl(page, nfl_site_url)
    draws = page.evaluate("window.__draws")
    assert draws
    assert draws[0] is True


def test_late_condensed_face_redraws_the_nfl_chart(page: Page, nfl_site_url: str) -> None:
    _delay_face(page, 2.5)
    _open_nfl(page, nfl_site_url)
    assert page.evaluate("window.__draws")[0] is False
    page.wait_for_function("window.__draws.some((loaded) => loaded)", timeout=15000)
