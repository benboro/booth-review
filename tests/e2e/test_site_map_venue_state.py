"""Phase 11 plan 03: stable venue keys, venue/colors state, URL params. Synthetic data only."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

# ruff: noqa: E501  (inline JS fixtures)

pytestmark = pytest.mark.e2e

_PREP = """
async (mutation) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const U = await import('./modules/url-state.js');
  const raw = await (await fetch('site-data.json')).json();
  if (mutation) new Function('raw', mutation)(raw);
  const data = D.prepareData(raw);
  %s
}
"""


def _eval(page: Page, site_url: str, body: str, mutation: str | None = None) -> Any:
    page.goto(f"{site_url}/index.html")
    page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    return page.evaluate(_PREP % body, mutation)


# ---------------------------------------------------------------- keys


def test_geometry_exports_match_between_modules(guarded_page: Page, site_url: str) -> None:
    guarded_page.goto(f"{site_url}/index.html")
    guarded_page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    got = guarded_page.evaluate(
        """async () => {
          const G = await import('./modules/map-geo.js');
          const M = await import('./modules/map-model.js');
          const v = { lon: -96.7056, lat: 40.8206, state: 'NE', country: 'US', name: 'x', city: 'y' };
          return {
            proj: JSON.stringify(G.projectAlbersUsa(-96.7, 40.8, 'NE'))
              === JSON.stringify(M.projectAlbersUsa(-96.7, 40.8, 'NE')),
            place: JSON.stringify(G.placeVenue(v)) === JSON.stringify(M.placeVenue(v)),
            inset: G.HAWAII_INSET === M.HAWAII_INSET,
            size: [G.MAP_WIDTH, G.MAP_HEIGHT],
          };
        }"""
    )
    assert got == {"proj": True, "place": True, "inset": True, "size": [975, 610]}


def test_venue_keys_unique_and_slugged(guarded_page: Page, site_url: str) -> None:
    got = _eval(
        guarded_page,
        site_url,
        "return { keys: data.venueKeys, n: data.lookups.venues.length, groups: data.venueGroupKeys };",
    )
    assert len(got["keys"]) == got["n"] == 9
    assert len(set(got["keys"])) == 9
    assert got["keys"][0] == "northfield-stadium-lincoln"
    assert got["groups"][7] == "dublin"
    assert got["groups"][8] == "nassau"
    assert all(g is None for i, g in enumerate(got["groups"]) if i not in (7, 8))


def test_index_map_covers_keys_and_groups(guarded_page: Page, site_url: str) -> None:
    got = _eval(
        guarded_page,
        site_url,
        """return {
          dublin: data.venueIndexesByKey.get('dublin'),
          nassau: data.venueIndexesByKey.get('nassau'),
          one: data.venueIndexesByKey.get('northfield-stadium-lincoln'),
          size: data.venueIndexesByKey.size,
        };""",
    )
    assert got["dublin"] == [7]
    assert got["nassau"] == [8]
    assert got["one"] == [0]
    assert got["size"] == 11


def test_duplicate_name_city_gets_suffix(
    guarded_page: Page, site_url: str, serve_map_venues: Callable[[Page], None]
) -> None:
    serve_map_venues(guarded_page)
    got = _eval(guarded_page, site_url, "return data.venueKeys;")
    assert got[0] == "northfield-stadium-lincoln"
    assert got[9] == "northfield-stadium-lincoln-2"


def test_group_slug_colliding_with_a_venue_key_is_prefixed(
    guarded_page: Page, site_url: str
) -> None:
    mutation = "raw.lookups.venues[1].name = 'Dublin'; raw.lookups.venues[1].city = '';"
    got = _eval(
        guarded_page,
        site_url,
        "return { keys: data.venueKeys, groups: data.venueGroupKeys, d: data.venueIndexesByKey.get('abroad-dublin'), plain: data.venueIndexesByKey.get('dublin') };",
        mutation,
    )
    assert got["keys"][1] == "dublin"
    assert got["groups"][7] == "abroad-dublin"
    assert got["d"] == [7]
    assert got["plain"] == [1]
