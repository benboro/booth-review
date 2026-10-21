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


def test_shuffling_duplicate_venues_keeps_each_ones_key(
    guarded_page: Page, site_url: str, serve_map_venues: Callable[[Page], None]
) -> None:
    """Same-name, same-city venues are keyed by their own data, not lookup order."""
    serve_map_venues(guarded_page)
    body = """
      const v = data.lookups.venues;
      const dupes = v.map((x, i) => i).filter((i) => data.venueKeys[i].startsWith('northfield-stadium-lincoln'));
      return {
        dupes: dupes.map((i) => ({ lat: v[i].lat, lon: v[i].lon, state: v[i].state, key: data.venueKeys[i] })),
        others: v.map((x, i) => [x.name, data.venueKeys[i]]).filter(([, k]) => !k.startsWith('northfield-stadium-lincoln')),
      };
    """
    base = _eval(guarded_page, site_url, body)
    assert len(base["dupes"]) == 2
    # Swap the lookup positions of the two duplicates (venue 0 and venue 9).
    mutation = """
      const v = raw.lookups.venues;
      const a = 0, b = 9;
      const t = v[a]; v[a] = v[b]; v[b] = t;
    """
    shuffled = _eval(guarded_page, site_url, body, mutation)
    by_place = {(d["lat"], d["lon"], d["state"]): d["key"] for d in base["dupes"]}
    assert {(d["lat"], d["lon"], d["state"]): d["key"] for d in shuffled["dupes"]} == by_place
    assert sorted(by_place.values()) == [
        "northfield-stadium-lincoln",
        "northfield-stadium-lincoln-2",
    ]
    assert sorted(shuffled["others"]) == sorted(base["others"])


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


def test_suffixed_key_never_lands_on_another_venues_own_key(
    guarded_page: Page, site_url: str
) -> None:
    mutation = (
        "const v = raw.lookups.venues;"
        " [['Foo', ''], ['Foo', ''], ['Foo 2', '']].forEach(([n, c], i) => { v[i].name = n; v[i].city = c; });"
        # Duplicates are ordered by their own data: pin venue 0 ahead of venue 1.
        " v[0].state = v[1].state = 'NE'; v[0].country = v[1].country = 'US';"
        " v[0].lat = 40; v[1].lat = 41; v[0].lon = v[1].lon = -96;"
    )
    got = _eval(
        guarded_page,
        site_url,
        "return { keys: data.venueKeys, byKey: [...data.venueIndexesByKey.keys()].length, n: data.lookups.venues.length };",
        mutation,
    )
    assert got["keys"][:3] == ["foo", "foo-3", "foo-2"]
    assert len(set(got["keys"])) == got["n"]


def test_abroad_group_key_never_collides_with_a_venue_or_another_group(
    guarded_page: Page, site_url: str
) -> None:
    mutation = (
        "const v = raw.lookups.venues;"
        " v[1].name = 'Dublin'; v[1].city = '';"
        " v[2].name = 'Abroad Dublin'; v[2].city = '';"
    )
    got = _eval(
        guarded_page,
        site_url,
        "return { keys: data.venueKeys, groups: data.venueGroupKeys, d: data.venueIndexesByKey.get('abroad-dublin-2'), a: data.venueIndexesByKey.get('abroad-dublin'), plain: data.venueIndexesByKey.get('dublin') };",
        mutation,
    )
    assert got["keys"][1] == "dublin"
    assert got["keys"][2] == "abroad-dublin"
    assert got["groups"][7] == "abroad-dublin-2"
    assert got["d"] == [7]
    assert got["a"] == [2]
    assert got["plain"] == [1]
    groups = {k for k in got["groups"] if k is not None}
    assert not groups & set(got["keys"])


# ---------------------------------------------------------------- state and view

_VENUE = "ironpeak-field-boulder"  # fixture venue 2: rated telecasts 1 (2019) and 8 (2026)


def test_default_state_has_venue_and_colors(guarded_page: Page, site_url: str) -> None:
    got = _eval(
        guarded_page,
        site_url,
        "const s = S.defaultState(data); return { venue: s.venue, colors: s.colors };",
    )
    assert got == {"venue": None, "colors": "on"}


def test_venue_alone_fills_table_with_its_filtered_games(guarded_page: Page, site_url: str) -> None:
    got = _eval(
        guarded_page,
        site_url,
        f"""
        const s = S.defaultState(data);
        const base = S.computeView(data, s);
        s.venue = '{_VENUE}';
        const v = S.computeView(data, s);
        const expect = [];
        for (let i = 0; i < data.n; i += 1) if (v.passesFilters[i] && data.t.place[i] === 2) expect.push(i);
        return {{ sel: v.venueSelected, has: v.hasSelection, matched: v.matched, expect,
                  baseSel: base.venueSelected, hi: v.highlighted, summary: v.summary,
                  baseSummary: base.summary, filterActive: v.filterActive }};
        """,
    )
    assert got["sel"] is True and got["baseSel"] is False
    assert got["has"] is False
    assert got["matched"] == got["expect"] == [1, 8, 13]  # 13: unrated game at venue 2
    assert got["hi"] == []
    assert got["summary"] == got["baseSummary"]


def test_venue_intersects_with_school_and_leaves_summary(guarded_page: Page, site_url: str) -> None:
    got = _eval(
        guarded_page,
        site_url,
        f"""
        const search = '?school=ironpeak';
        const s0 = U.decodeState(search, data);
        const a = S.computeView(data, s0);
        const s1 = {{ ...s0, venue: '{_VENUE}' }};
        const b = S.computeView(data, s1);
        const expect = a.matched.filter((i) => data.t.place[i] === 2);
        return {{ school: s0.school, a: a.matched, b: b.matched, expect,
                  hiSame: JSON.stringify(a.highlighted) === JSON.stringify(b.highlighted),
                  sumSame: JSON.stringify(a.summary) === JSON.stringify(b.summary),
                  hasSame: a.hasSelection === b.hasSelection }};
        """,
    )
    assert got["school"], "school slug must resolve"
    assert got["b"] == got["expect"]
    assert got["b"], "ironpeak plays at its own venue in the fixture"
    assert got["hiSame"] and got["sumSame"] and got["hasSame"]


def test_venue_with_filter_excluding_all_games_is_empty_but_selected(
    guarded_page: Page, site_url: str
) -> None:
    got = _eval(
        guarded_page,
        site_url,
        f"""
        const s = S.defaultState(data);
        s.venue = '{_VENUE}';
        s.seasons = [2022, 2024];
        const v = S.computeView(data, s);
        return {{ sel: v.venueSelected, matched: v.matched }};
        """,
    )
    assert got == {"sel": True, "matched": []}


def test_unknown_venue_is_ignored(guarded_page: Page, site_url: str) -> None:
    got = _eval(
        guarded_page,
        site_url,
        """
        const s = S.defaultState(data);
        s.venue = 'nope';
        const v = S.computeView(data, s);
        return { sel: v.venueSelected, matched: v.matched };
        """,
    )
    assert got == {"sel": False, "matched": []}


def test_group_key_filters_to_every_group_venue(guarded_page: Page, site_url: str) -> None:
    # Move rated telecast 0 to a second Dublin-labelled venue so the group has two members.
    mutation = (
        "raw.lookups.venues.push({city: 'Dublin', country: 'IE', lat: 53.4, lon: -6.3,"
        " name: 'Liffey Ground', state: null});"
        " raw.telecasts.place[0] = raw.lookups.venues.length - 1;"
        " raw.telecasts.place[1] = 7;"
    )
    got = _eval(
        guarded_page,
        site_url,
        """
        const s = S.defaultState(data);
        s.venue = 'dublin';
        const v = S.computeView(data, s);
        return { idx: data.venueIndexesByKey.get('dublin'), matched: v.matched };
        """,
        mutation,
    )
    assert got["idx"] == [7, 9]
    assert got["matched"] == [0, 1, 17]  # 17: unrated game at venue 7


# ---------------------------------------------------------------- URL


def test_venue_url_round_trip_and_drops(guarded_page: Page, site_url: str) -> None:
    got = _eval(
        guarded_page,
        site_url,
        f"""
        const out = {{}};
        const s = {{ ...S.defaultState(data), venue: '{_VENUE}' }};
        out.encoded = U.encodeState(s, data);
        out.round = U.decodeState(out.encoded, data).venue;
        out.plain = U.encodeState(S.defaultState(data), data);
        out.drops = ['?venue=nope', '?venue=%', '?venue=', '?venue=%E0%A4%A']
          .map((q) => U.decodeState(q, data).venue);
        out.group = U.decodeState('?venue=dublin', data).venue;
        return out;
        """,
    )
    assert f"venue={_VENUE}" in got["encoded"]
    assert got["round"] == _VENUE
    assert "venue" not in got["plain"]
    assert got["drops"] == [None, None, None, None]
    assert got["group"] == "dublin"


def test_colors_url_round_trip(guarded_page: Page, site_url: str) -> None:
    got = _eval(
        guarded_page,
        site_url,
        """
        const on = S.defaultState(data);
        const off = { ...on, colors: 'off' };
        return {
          off: U.encodeState(off, data),
          on: U.encodeState(on, data),
          offBack: U.decodeState('?colors=off', data).colors,
          maybe: U.decodeState('?colors=maybe', data).colors,
          none: U.decodeState('', data).colors,
        };
        """,
    )
    assert "colors=off" in got["off"]
    assert "colors" not in got["on"]
    assert got["offBack"] == "off"
    assert got["maybe"] == "on" and got["none"] == "on"
