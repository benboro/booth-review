"""Phase 11: map-venues.js and palette map constants, synthetic data only."""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page

# ruff: noqa: E501  (inline JS fixtures)

pytestmark = pytest.mark.e2e


def _run(page: Page, site_url: str, body: str, module: str = "palette.js") -> Any:
    page.goto(f"{site_url}/index.html")
    page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    return page.evaluate(
        f"async () => {{ const M = await import('./modules/{module}');" + body + "}"
    )


# ---------------------------------------------------------------- palette / oklab


def test_oklab_round_trip_and_mix_endpoints(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const ch = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
        const close = (a, b) => ch(a).every((v, i) => Math.abs(v - ch(b)[i]) <= 1);
        const sets = [M.FAMILY_COLORS.light, M.FAMILY_COLORS.dark,
                      M.MAP_FAMILY_COLORS.light, M.MAP_FAMILY_COLORS.dark];
        let roundTrip = true;
        for (const set of sets) for (const h of Object.values(set)) {
          if (!close(M.oklabToHex(M.hexToOklab(h)), h)) roundTrip = false;
        }
        const a = '#0072B2', b = '#D55E00';
        return {
          whiteL: M.hexToOklab('#FFFFFF')[0],
          roundTrip,
          m0: close(M.mixOklab(a, b, 0), a),
          m1: close(M.mixOklab(a, b, 1), b),
          differs: M.mixOklab(a, b, 0.5).toUpperCase() !== M.mixHex(a, b, 0.5).toUpperCase(),
        };
        """,
    )
    assert abs(got["whiteL"] - 1) < 1e-3
    assert got["roundTrip"] and got["m0"] and got["m1"] and got["differs"]


def test_palette_map_constants(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        // Phase 24: the light map deepens families under 3:1 on the land, so a map colour
        // is the page colour or a darker mix of it (same hue, never lighter).
        const same = (t) => Object.keys(M.FAMILY_COLORS[t])
          .filter((k) => k !== 'conference')
          .every((k) => M.MAP_FAMILY_COLORS[t][k] === M.FAMILY_COLORS[t][k]
            || M.contrastRatio(M.MAP_FAMILY_COLORS[t][k], '#000000')
              < M.contrastRatio(M.FAMILY_COLORS[t][k], '#000000'));
        return {
          lc: M.MAP_FAMILY_COLORS.light.conference,
          dc: M.MAP_FAMILY_COLORS.dark.conference,
          same: same('light') && same('dark'),
          contrastL: M.contrastRatio(M.MAP_FAMILY_COLORS.light.conference, M.MAP_LAND.light),
          contrastD: M.contrastRatio(M.MAP_FAMILY_COLORS.dark.conference, M.MAP_LAND.dark),
          frozen: Object.isFrozen(M.MAP_SPLAT) && Object.isFrozen(M.MAP_VENUE_DOT),
          splat: M.MAP_SPLAT, dot: M.MAP_VENUE_DOT, neutral: M.MAP_DOT_NEUTRAL,
        };
        """,
    )
    assert got["lc"] == "#6A5BA0"
    assert got["dc"] == "#9A8CD0"
    assert got["same"] and got["frozen"]
    # The green-gray land (#E8EDEA, Phase 26) puts the unchanged conference purple at 4.90:1;
    # keep the WCAG AA 4.5:1 floor rather than the old 5:1 margin.
    assert got["contrastL"] >= 4.5
    # The dark land (#242A28) puts the kept dark violet at 4.90:1; same 4.5:1 floor as light.
    assert got["contrastD"] >= 4.5
    assert got["splat"]["viewersWeight"] == 0.35
    assert got["splat"]["unratedFallback"] == 150000
    assert got["dot"]["maxDiameter"] == 20
    assert got["dot"]["phoneMaxDiameter"] == 10
    assert got["dot"]["hitDiameter"] == 12
    assert not {"radiusMax", "radiusBase", "phoneMax"} & set(got["dot"])
    # Phase 17 lifted the dark neutral to #8B8377 (3.97:1 on the new land, 17-UI-SPEC).
    assert got["neutral"] == {"light": "#B3AA9C", "dark": "#8B8377"}


# ---------------------------------------------------------------- venue model

_BUILD = """
const P = await import('./modules/palette.js');
// games: [venueIdx, family, viewers|null]
const build = (games, venues, extra = {}) => {
  const data = {
    t: { place: games.map((g) => g[0]), viewers: games.map((g) => g[2]) },
    familyOf: games.map((g) => g[1]),
    lookups: { venues: venues.map((v) => ({ name: v.name, state: v.state ?? 'IA' })) },
    venueKeys: venues.map((v) => v.name),
    venueGroupKeys: venues.map((v) => v.group ?? null),
  };
  const placements = venues.map((v, i) => ({ x: 10 * i, y: 5 * i, abroad: !!v.abroad, label: v.name }));
  const passing = extra.passing ?? games.map((_, i) => i);
  return M.buildVenueModel(data, passing, placements);
};
const rep = (n, fam, v) => Array.from({ length: n }, () => [0, fam, v]);
"""


def _model(page: Page, site_url: str, body: str) -> Any:
    return _run(page, site_url, _BUILD + body, module="map-venues.js")


def test_leader_by_games_not_viewers(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const m = build([...rep(9, 'fox', 1e6), ...rep(5, 'cbs', 9e6)], [{ name: 'Riverbend Stadium' }]);
        const v = m.venues[0];
        return { leader: v.leader, ru: v.runnerUpGames, margin: v.margin };
        """,
    )
    assert got["leader"] == "fox"
    assert got["ru"] == 5
    assert abs(got["margin"] - 4 / 14) < 1e-9


def test_tie_goes_to_viewers_then_family_order(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const a = build([...rep(4, 'fox', 1e6), ...rep(4, 'cbs', 2e6)], [{ name: 'Lakeside Field' }]).venues[0];
        const b = build([...rep(4, 'cbs', 1e6), ...rep(4, 'fox', 1e6)], [{ name: 'Lakeside Field' }]).venues[0];
        return { a: [a.leader, a.margin], b: [b.leader, b.margin] };
        """,
    )
    assert got["a"] == ["cbs", 0]
    assert got["b"] == ["fox", 0]


def test_tie_prefers_real_viewers_over_the_unrated_floor(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        // One unrated FOX game against one CBS game at 120K: the floor (p10 of the rated
        // games) is above 120K here, so floor-weighted viewers would pick FOX while the
        // card shows FOX with no figure.
        const games = [[0, 'fox', null], [0, 'cbs', 120000], ...Array.from({ length: 11 }, (_, k) => [1, 'nbc', 300000 + k * 1000])];
        const m = build(games, [{ name: 'Lakeside Field' }, { name: 'Other Park' }]);
        const v = m.byKey.get('Lakeside Field');
        // Neither side rated: weighted (floor) then FAMILY_ORDER still decide.
        const none = build([[0, 'cbs', null], [0, 'fox', null]], [{ name: 'Lakeside Field' }]).venues[0];
        return { leader: v.leader, floor: m.floorViewers, none: none.leader };
        """,
    )
    assert got["floor"] > 120000
    assert got["leader"] == "cbs"
    assert got["none"] == "fox"


def test_score_orders_venues(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const g = (v, n, fam, tot) => Array.from({ length: n }, () => [v, fam, tot / n]);
        const vs = (names) => names.map((name) => ({ name }));
        const m1 = build([...g(0, 12, 'fox', 40e6), ...g(1, 15, 'fox', 3e6)], vs(['Harbor A', 'Harbor B']));
        const m2 = build([...g(0, 2, 'fox', 20e6), ...g(1, 9, 'fox', 6e6), ...g(2, 0, 'fox', 0)],
                         vs(['Hill P', 'Hill S', 'Empty']));
        return {
          first1: m1.venues[0].key,
          first2: m2.venues[0].key,
          keys2: m2.venues.map((v) => v.key),
          zero: M.venueScore(0, 5e6),
        };
        """,
    )
    assert got["first1"] == "Harbor B"  # more games draws first, whatever the audience
    assert got["first2"] == "Hill S"
    assert "Empty" not in got["keys2"]
    assert got["zero"] == 0


def test_floor_and_unrated_games(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const rated = Array.from({ length: 11 }, (_, i) => [0, 'fox', (i + 1) * 1e5]);
        const m = build([...rated, [0, 'cbs', null]], [{ name: 'Mill Park' }]);
        const none = build([[0, 'fox', null], [0, 'fox', null]], [{ name: 'Mill Park' }]);
        const v = m.venues[0], cbs = P.FAMILY_ORDER.indexOf('cbs');
        return {
          floor: m.floorViewers, med: m.medianRatedViewers,
          cbsViewers: v.viewers[cbs], cbsWeighted: v.weighted[cbs], cbsRated: v.ratedCounts[cbs],
          noneFloor: none.floorViewers, noneMed: none.medianRatedViewers,
          noneViewers: none.venues[0].viewers.reduce((a, b) => a + b, 0),
        };
        """,
    )
    # 11 rated games passing plus one unrated: floor is p10 of the rated list.
    assert got["floor"] == 200000
    assert got["med"] == 600000
    assert got["cbsViewers"] == 0
    assert got["cbsWeighted"] == 200000
    assert got["cbsRated"] == 0
    assert got["noneFloor"] == 150000
    assert got["noneMed"] == 150000
    assert got["noneViewers"] == 0


def test_dot_size_formula(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const at = (n, r) => M.venueDotSize(n, r);
        const area = (n, k) => (at(n, 73)[k] / at(73, 73)[k]) ** 2;
        return {
          top: at(73, 73), one: at(1, 73), over: at(200, 73), zero: at(0, 73),
          badRef: [at(1, 0), at(1, -5), at(1, NaN)],
          areas: [1, 10, 20, 50].map((n) => [area(n, 'desktop') - n / 73, area(n, 'phone') - n / 73]),
          ratio: at(50, 73).desktop / at(10, 73).desktop,
        };
        """,
    )
    assert got["top"] == {"desktop": 20, "phone": 10}
    assert abs(got["one"]["desktop"] - 20 / 73**0.5) < 1e-9
    assert abs(got["one"]["phone"] - 10 / 73**0.5) < 1e-9
    # No clamp (D-24): a count above the reference keeps area proportional to games.
    assert abs(got["over"]["desktop"] - 20 * (200 / 73) ** 0.5) < 1e-9
    assert abs(got["over"]["phone"] - 10 * (200 / 73) ** 0.5) < 1e-9
    assert got["zero"] == {"desktop": 0, "phone": 0}
    for size in got["badRef"]:
        assert size == {
            "desktop": 20 if size["desktop"] else 0,
            "phone": 10 if size["phone"] else 0,
        }
    for a, b in got["areas"]:
        assert abs(a) < 1e-9 and abs(b) < 1e-9
    assert abs(got["ratio"] - 5**0.5) < 1e-9


def test_size_rescales_with_filters(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const vs = [{ name: 'Big Bowl' }, { name: 'Small Bowl' }];
        const games = [...Array.from({ length: 16 }, () => [0, 'fox', 4e6]),
                       ...Array.from({ length: 4 }, () => [1, 'fox', 4e6])];
        const m = build(games, vs);
        const only = build(games, vs, { passing: games.map((_, i) => i).filter((i) => games[i][0] === 1) });
        const few = build(games, vs, { passing: [0, 1, 2, 16] });
        const none = build(games, vs, { passing: [] });
        return {
          top: m.venues[0].size, small: m.venues[1].size,
          onlySmall: only.venues[0].size, ref: [m.refGames, only.refGames, few.refGames, none.refGames],
          fewSizes: few.venues.map((v) => [v.key, v.games, v.size.desktop]),
          expected: M.venueDotSize(4, 16),
          hasRef: 'referenceGames' in M,
        };
        """,
    )
    assert got["top"] == {"desktop": 20, "phone": 10}
    assert got["small"] == got["expected"]
    # Narrowing to the small venue makes it the busiest, so it grows to max.
    assert got["onlySmall"] == {"desktop": 20, "phone": 10}
    assert got["ref"] == [16, 4, 3, 0]
    assert got["fewSizes"][0][2] == 20
    for _key, games, desktop in got["fewSizes"]:
        assert abs(desktop - 20 * (games / 3) ** 0.5) < 1e-9
    assert got["hasRef"] is False


def test_venues_draw_largest_games_first(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const g = (v, n, tot) => Array.from({ length: n }, () => [v, 'fox', tot / n]);
        const m = build([...g(0, 3, 90e6), ...g(1, 7, 1e6), ...g(2, 7, 1e6)],
                        [{ name: 'Few Big Fans' }, { name: 'Many A' }, { name: 'Many B' }]);
        return m.venues.map((v) => v.key);
        """,
    )
    assert got == ["Many A", "Many B", "Few Big Fans"]


def test_dot_color_fade(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const ch = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
        const close = (a, b) => ch(a).every((v, i) => Math.abs(v - ch(b)[i]) <= 1);
        const one = build(rep(5, 'wbd', 1e6), [{ name: 'Solo Dome' }]).venues[0];
        const split = build([...rep(3, 'fox', 1e6), ...rep(3, 'nbc', 1e6)], [{ name: 'Split Dome' }]).venues[0];
        return {
          oneL: close(one.dotColor.light, P.MAP_FAMILY_COLORS.light.wbd),
          oneD: close(one.dotColor.dark, P.MAP_FAMILY_COLORS.dark.wbd),
          splitL: close(split.dotColor.light, P.MAP_DOT_NEUTRAL.light),
          splitD: close(split.dotColor.dark, P.MAP_DOT_NEUTRAL.dark),
        };
        """,
    )
    assert all(got.values())


def test_abroad_groups_hawaii_and_missing_placement(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const venues = [
          { name: 'Island Oval', state: 'HI' },
          { name: 'Abroad One', abroad: true, group: 'abroad-x' },
          { name: 'Abroad Two', abroad: true, group: 'abroad-x' },
        ];
        const games = [[0, 'fox', 1e6], [1, 'cbs', 2e6], [2, 'cbs', 3e6], [2, 'fox', null], [7, 'fox', 1e6]];
        const m = build(games, venues);
        const grp = m.byKey.get('abroad-x');
        return {
          venueKeys: m.venues.map((v) => v.key), region: m.venues[0].region,
          grp: grp && { games: grp.games, leader: grp.leader, idx: grp.indexes, viewers: grp.viewers.reduce((a, b) => a + b, 0) },
          groups: m.groups.length, hasVenue: m.byKey.has('Island Oval'),
        };
        """,
    )
    assert got["venueKeys"] == ["Island Oval"]
    assert got["region"] == 2
    assert got["grp"] == {"games": 3, "leader": "cbs", "idx": [1, 2], "viewers": 5000000}
    assert got["groups"] == 1
    assert got["hasVenue"]


def test_venues_sorted_and_module_is_dom_free(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const games = [[0, 'fox', 1e6], [1, 'fox', 1e6], [1, 'fox', 1e6], [1, 'fox', 1e6]];
        const m = build(games, [{ name: 'Quiet Park' }, { name: 'Busy Park' }]);
        const src = await (await fetch('./modules/map-venues.js')).text();
        return {
          order: m.venues.map((v) => v.key),
          scores: m.venues.map((v) => v.score),
          dom: /\\b(document|window|Plotly)\\b/.test(src),
          json: JSON.stringify(m.venues[0]).length > 0,
        };
        """,
    )
    assert got["order"] == ["Busy Park", "Quiet Park"]
    assert got["scores"][0] >= got["scores"][1]
    assert not got["dom"]
    assert got["json"]
