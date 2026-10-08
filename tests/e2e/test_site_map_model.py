"""04.18 (SITE-72/73/74): map-model.js, the DOM-free core of the Map tab.

In-page tests on synthetic data and view objects only (fictional names, no vault rows).
"""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


def _load(page: Page, site_url: str) -> None:
    page.goto(f"{site_url}/index.html")
    page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")


def _run(page: Page, site_url: str, body: str) -> Any:
    _load(page, site_url)
    return page.evaluate(
        "async () => { const M = await import('./modules/map-model.js');" + body + "}"
    )


# ---------------------------------------------------------------- geometry (Task 2)


def test_projection_matches_d3_reference_points(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const pts = {
          sb: M.projectAlbersUsa(-86.234, 41.698, 'IN'),
          la: M.projectAlbersUsa(-118.2, 34.0, 'CA'),
          hi: M.projectAlbersUsa(-157.86, 21.3, 'HI'),
          nas: M.projectAlbersUsa(-77.3, 25.05, null),
          ak: M.projectAlbersUsa(-149.9, 61.2, 'AK'),
          dub: M.projectAlbersUsa(-6.2, 53.3, null),
        };
        return pts;
        """,
    )
    expect = {
        "sb": (661.94, 227.98),
        "la": (87.33, 364.47),
        "hi": (266.92, 549.35),
        "nas": (884.55, 577.43),
        "ak": (112.29, 544.42),
    }
    for key, (x, y) in expect.items():
        pt = got[key]
        assert abs(pt["x"] - x) <= 0.01, key
        assert abs(pt["y"] - y) <= 0.01, key
    assert got["dub"] is None


def test_place_venue_us_hawaii_and_abroad(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const v = (o) => ({name: 'Field', city: 'Town', state: null, country: null,
                           lat: 0, lon: 0, ...o});
        return {
          in: M.placeVenue(v({state: 'IN', country: 'US', lat: 41.698, lon: -86.234})),
          hi: M.placeVenue(v({state: 'HI', country: 'US', lat: 21.3, lon: -157.86})),
          ie: M.placeVenue(v({country: 'IE', city: 'Dublin', lat: 53.3, lon: -6.2})),
          gb: M.placeVenue(v({country: 'GB', city: 'London', lat: 51.5, lon: -0.1})),
          au: M.placeVenue(v({country: 'AU', city: 'Sydney', lat: -33.9, lon: 151.2})),
          bs: M.placeVenue(v({country: 'BS', city: 'Nassau', lat: 25.05, lon: -77.3})),
          jp: M.placeVenue(v({country: 'JP', city: 'Tokyo', lat: 35.68, lon: 139.69})),
          inset: M.HAWAII_INSET,
        };
        """,
    )
    assert got["in"]["edge"] is False
    assert got["in"]["abroad"] is False
    hi, inset = got["hi"], got["inset"]
    assert inset["x0"] <= hi["x"] <= inset["x1"]
    assert inset["y0"] <= hi["y"] <= inset["y1"]
    ie = got["ie"]
    assert (ie["x"], ie["y"], ie["edge"], ie["label"], ie["side"]) == (
        955,
        30,
        True,
        "Dublin",
        "left",
    )
    gb = got["gb"]
    assert (gb["x"], gb["y"], gb["label"]) == (955, 52, "London")
    au = got["au"]
    assert (au["x"], au["y"], au["label"], au["side"]) == (120, 575, "Sydney", "right")
    bs = got["bs"]
    assert abs(bs["x"] - 884.55) <= 0.01
    assert abs(bs["y"] - 577.43) <= 0.01
    assert (bs["edge"], bs["abroad"], bs["label"]) == (False, True, "Nassau")
    jp = got["jp"]
    assert (jp["x"], jp["y"], jp["label"]) == (40, 588, "Tokyo")


def test_arc_points_geometry(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const a = {x: 100, y: 300}, b = {x: 500, y: 300};
        const fwd = M.arcPoints(a, b), back = M.arcPoints(b, a);
        const mid = (p) => p[Math.floor(p.length / 2)];
        return {
          first: fwd[0], last: fwd[fwd.length - 1],
          midF: mid(fwd), midB: mid(back),
          zero: M.arcPoints(a, a).length,
          short: M.arcPoints({x: 0, y: 0}, {x: 100, y: 0}).length,
          long: M.arcPoints({x: 0, y: 0}, {x: 1000, y: 0}).length,
          bow: M.MAP_ARC_BOW,
        };
        """,
    )
    assert got["first"] == {"x": 100, "y": 300}
    assert got["last"] == {"x": 500, "y": 300}
    assert got["midF"]["y"] < 300
    assert got["midB"]["y"] > 300
    assert got["zero"] == 0
    assert got["short"] == 7
    assert got["long"] == 25
    assert got["bow"] == 0.15
    # Quadratic midpoint sits half of the control offset (0.15 * 400) off the chord.
    assert abs((300 - got["midF"]["y"]) - 0.15 * 400 / 2) < 1.0


def test_copy_constants(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        return {
          one: M.noLocationNote(1), three: M.noLocationNote(3),
          aria: M.mapAriaLabel(9), hint: M.MAP_HINT,
          frozen: [M.EDGE_ANCHORS, M.FALLBACK_ANCHORS, M.HAWAII_INSET,
                   M.MAP_SHAPES_CAPTION, M.MAP_EMPTY, M.MAP_ERROR].map(Object.isFrozen),
        };
        """,
    )
    assert got["one"] == "1 game has no venue location"
    assert got["three"] == "3 games have no venue location"
    assert got["aria"] == "Map of 9 game venues"
    assert got["hint"] == "Pick an announcer or a school to trace a path"
    assert all(got["frozen"])
