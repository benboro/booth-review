"""U8: Reset zoom is a compact button with a gap from the chart's control groups.

The NFL Scatter put Reset zoom in the one-cell `.chart-controls` grid, so it stretched to the
axis groups' width and sat flush under them. Every sport's Reset zoom must keep its content
width, the secondary-button height, and at least a 4px gap from each control group, at 1440
and 390. Synthetic fixtures only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_GEOMETRY_JS = """
() => {
  const buttons = [...document.querySelectorAll('button.reset-zoom')]
    .filter((b) => b.offsetParent !== null);
  return buttons.map((b) => {
    const r = b.getBoundingClientRect();
    const s = getComputedStyle(b);
    const pad = parseFloat(s.paddingLeft) + parseFloat(s.paddingRight);
    const border = parseFloat(s.borderLeftWidth) + parseFloat(s.borderRightWidth);
    const scope = b.closest('.module-head') || document;
    const groups = [...scope.querySelectorAll('.axis-group, .segmented')]
      .filter((g) => g.offsetParent !== null && !g.contains(b))
      .map((g) => {
        const q = g.getBoundingClientRect();
        const vgap = Math.max(q.top - r.bottom, r.top - q.bottom);
        const hgap = Math.max(q.left - r.right, r.left - q.right);
        return Math.max(vgap, hgap);
      });
    return {
      width: r.width, height: r.height, content: b.scrollWidth - pad,
      pad, border, groups, minGap: groups.length ? Math.min(...groups) : null,
    };
  });
}
"""


def _assert_compact(page: Page) -> None:
    found: list[dict[str, Any]] = page.evaluate(_GEOMETRY_JS)
    assert len(found) == 1
    geo = found[0]
    assert geo["width"] < 200
    assert geo["width"] <= geo["content"] + geo["pad"] + geo["border"] + 2
    assert 28 <= geo["height"] <= 30  # the secondary-button height (.reset-zoom min-height)
    assert geo["groups"], "no control group found beside Reset zoom"
    assert geo["minGap"] >= 4


@pytest.fixture(params=[1440, 390], ids=["1440", "390"])
def width(request: pytest.FixtureRequest) -> int:
    return int(request.param)


def _page(request: pytest.FixtureRequest, width: int, desktop: str, mobile: str) -> Page:
    if width == 390:
        page: Page = request.getfixturevalue(mobile)
        return page
    page = request.getfixturevalue(desktop)
    page.set_viewport_size({"width": 1440, "height": 900})
    return page


def test_cfb_reset_zoom_is_compact(
    request: pytest.FixtureRequest, width: int, open_app: Callable[..., None]
) -> None:
    page = _page(request, width, "guarded_page", "mobile_page")
    open_app(page, "?view=scatter")
    _assert_compact(page)


def test_nfl_reset_zoom_is_compact(
    request: pytest.FixtureRequest, width: int, open_nfl_app: Callable[..., None]
) -> None:
    page = _page(request, width, "nfl_guarded_page", "nfl_mobile_page")
    open_nfl_app(page, "?sport=nfl&view=scatter")
    page.wait_for_selector("#nfl-view-scatter .legend-chips button")
    _assert_compact(page)


def test_mlb_reset_zoom_is_compact(
    request: pytest.FixtureRequest, width: int, open_mlb_app: Callable[..., None]
) -> None:
    page = _page(request, width, "mlb_guarded_page", "mlb_mobile_page")
    open_mlb_app(page, "?sport=mlb&view=scatter")
    page.wait_for_selector("#mlb-view-scatter .legend-chips button")
    _assert_compact(page)
