"""Phase 17.1 D-21: the overseas entries (Dublin, London, Nassau, Sydney) never overlap.

Measures the rendered ring and label boxes on the real page (at the phone and desktop
widths, in both themes) and asserts that no two entries' boxes intersect. The fixture
carries Dublin and Nassau venues; the test adds London and Sydney venues to the served
data so the two near neighbours (Dublin and London) are both on the map.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

OpenApp = Callable[[Page, str], None]

_BOXES = """() => {
  const gd = document.getElementById('map-chart');
  const traces = Array.from(gd.querySelectorAll('.scatterlayer .trace'));
  const layer = traces.find((t) => t.querySelector('.textpoint')) ;
  const rect = (r) => ({x0: r.left, y0: r.top, x1: r.right, y1: r.bottom});
  const rings = Array.from(layer.querySelectorAll('.points path.point'))
    .map((p) => rect(p.getBoundingClientRect()));
  const labels = Array.from(layer.querySelectorAll('.textpoint text'))
    .map((t) => ({text: t.textContent, ...rect(t.getBoundingClientRect())}));
  return {rings, labels};
}"""


def _serve_extra_venues(page: Page, fixture_raw: dict[str, Any]) -> None:
    raw = copy.deepcopy(fixture_raw)
    venues = raw["lookups"]["venues"]
    base = {"state": None, "lat": None, "lon": None}
    venues.append(
        {
            **base,
            "name": "Bridge Park",
            "city": "London",
            "country": "GB",
            "lat": 51.5,
            "lon": -0.12,
        }
    )
    venues.append(
        {
            **base,
            "name": "Harbour Oval",
            "city": "Sydney",
            "country": "AU",
            "lat": -33.87,
            "lon": 151.2,
        }
    )
    place = raw["telecasts"]["place"]
    # Games 0..3 land on Dublin, Nassau, London, Sydney (indexes 7..10).
    for game, venue in enumerate(range(7, 7 + 4)):
        place[game] = venue
    page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))


def _hit(a: dict[str, float], b: dict[str, float]) -> bool:
    return a["x0"] < b["x1"] and b["x0"] < a["x1"] and a["y0"] < b["y1"] and b["y0"] < a["y1"]


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width,height", [(390, 844), (1440, 900)])
def test_overseas_entries_do_not_overlap(
    guarded_page: Page,
    open_app: OpenApp,
    fixture_raw: dict[str, Any],
    width: int,
    height: int,
    theme: str,
) -> None:
    guarded_page.set_viewport_size({"width": width, "height": height})
    guarded_page.add_init_script(f"localStorage.setItem('bl-theme', '{theme}')")
    _serve_extra_venues(guarded_page, fixture_raw)
    open_app(guarded_page, "?view=map")
    guarded_page.wait_for_function("() => window.__testHooks.mapRenders >= 1")
    guarded_page.wait_for_timeout(500)
    boxes = guarded_page.evaluate(_BOXES)
    rings, labels = boxes["rings"], boxes["labels"]
    names = sorted(label["text"] for label in labels)
    assert names == ["Dublin", "London", "Nassau", "Sydney"], names
    assert len(rings) == len(labels) == 4
    for i in range(4):
        for j in range(i + 1, 4):
            assert not _hit(rings[i], rings[j]), ("ring", i, j, rings)
            assert not _hit(labels[i], labels[j]), ("label", labels[i], labels[j])
        for j in range(4):
            if i != j:
                assert not _hit(rings[i], labels[j]), ("ring/label", i, j, rings[i], labels[j])


def _assert_apart(boxes: dict[str, Any]) -> None:
    rings, labels = boxes["rings"], boxes["labels"]
    assert len(rings) == len(labels) == 4
    for i in range(4):
        for j in range(i + 1, 4):
            assert not _hit(rings[i], rings[j]), ("ring", i, j, rings)
            assert not _hit(labels[i], labels[j]), ("label", labels[i], labels[j])
        for j in range(4):
            if i != j:
                assert not _hit(rings[i], labels[j]), ("ring/label", i, j, rings[i], labels[j])


@pytest.mark.parametrize("narrow", [390, 500])
def test_overseas_entries_stay_apart_after_a_resize(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any], narrow: int
) -> None:
    """WR-03: the spacing is in rendered pixels, so narrowing the window re-spaces the entries.
    500px stays above the phone breakpoint, so only the resize handler can redraw the map."""
    guarded_page.set_viewport_size({"width": 1440, "height": 900})
    _serve_extra_venues(guarded_page, fixture_raw)
    open_app(guarded_page, "?view=map")
    guarded_page.wait_for_function("() => window.__testHooks.mapRenders >= 1")
    guarded_page.wait_for_timeout(300)
    _assert_apart(guarded_page.evaluate(_BOXES))
    before = guarded_page.evaluate("() => window.__testHooks.mapRenders")
    guarded_page.set_viewport_size({"width": narrow, "height": 900})
    guarded_page.wait_for_function("(n) => window.__testHooks.mapRenders > n", arg=before)
    guarded_page.wait_for_timeout(500)
    _assert_apart(guarded_page.evaluate(_BOXES))
