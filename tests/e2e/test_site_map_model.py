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


# ------------------------------------------------------- model on synthetic data (Task 3)

_SYNTH = """
const venues = [
  {name: 'Alpha Field', city: 'South Bend', state: 'IN', country: 'US', lat: 41.698, lon: -86.234},
  {name: 'Beta Bowl', city: 'Los Angeles', state: 'CA', country: 'US', lat: 34.0, lon: -118.2},
  {name: 'Gamma Park', city: 'Honolulu', state: 'HI', country: 'US', lat: 21.3, lon: -157.86},
  {name: 'Dublin Arena', city: 'Dublin', state: null, country: 'IE', lat: 53.3, lon: -6.2},
  {name: 'Nassau Stadium', city: 'Nassau', state: null, country: 'BS', lat: 25.05, lon: -77.3},
  {name: 'Delta Dome', city: 'Columbus', state: 'OH', country: 'US', lat: 39.99, lon: -83.0},
];
const teams = ['Aces', 'Bears', 'Cats', 'Dogs', 'Eagles', 'Foxes'].map((name) => ({name}));
const networks = [
  {name: 'NetOne', family: 'disney'}, {name: 'NetTwo', family: 'nbc'},
  {name: 'NetThree', family: 'cbs'},
];
const people = [{name: 'Pat'}, {name: 'Quinn'}, {name: 'Rae'}];
// [season, date, kickoff, home, away, network, neutral, place]; merged order is NOT date order.
const G = [
  [2024, '2024-09-14', '19:30', 0, 1, 0, false, 0],
  [2024, '2024-09-07', '12:00', 2, 3, 1, false, 1],
  [2024, '2024-10-12', null, 0, 4, 0, false, 0],
  [2024, '2024-10-12', '15:00', 5, 1, 1, false, 5],
  [2024, '2024-11-02', '12:00', 3, 2, 2, true, 2],
  [2024, '2024-11-09', '12:00', 4, 5, 0, true, 3],
  [2025, '2025-09-06', '12:00', 0, 2, 0, false, 0],
  [2025, '2025-09-20', '12:00', 1, 3, 1, false, 1],
  [2025, '2025-10-04', '12:00', 0, 5, 0, false, null],
  [2025, '2025-10-11', '12:00', 4, 3, 2, true, 4],
  [2025, '2025-10-18', '12:00', 0, 1, 1, false, 0],
  [2025, '2025-11-01', '12:00', 5, 2, 2, false, 5],
];
const col = (k) => G.map((g) => g[k]);
const data = {
  n: G.length,
  t: {season: col(0), date: col(1), kickoff: col(2), home_team: col(3), away_team: col(4),
      network: col(5), neutral: col(6), place: col(7)},
  familyOf: G.map((g) => ['disney', 'nbc', 'cbs'][g[5]]),
  lookups: {venues, teams, networks, people},
  teamSlugs: ['a', 'b', 'c', 'd', 'e', 'f'],
  personIndexById: new Map([['pat', 0], ['quinn', 1], ['rae', 2]]),
};
const ones = () => new Uint8Array(G.length).fill(1);
const mkView = (o = {}) => {
  const passesFilters = o.passes ?? ones();
  return {
    passesFilters, visible: o.visible ?? ones(),
    visibleCount: (o.visible ?? ones()).reduce((a, b) => a + b, 0),
    highlighted: o.highlighted ?? [], peopleOnGame: o.peopleOnGame ?? new Map(),
  };
};
const mkState = (o = {}) => ({people: [], school: [], ...o});
// Pat called games 0,1,2,6,7,10 (and 8, which has no venue); Quinn called 0 and 6 as well.
const pat = [1, 0, 2, 6, 7, 8, 10];
const patOn = new Map(pat.map((i) => [i, [0]]));
const hlView = (hl) => mkView({highlighted: hl, peopleOnGame: new Map(hl.map((i) => [i, [0]]))});
"""


def _model(page: Page, site_url: str, body: str) -> Any:
    return _run(page, site_url, _SYNTH + body)


def test_no_subject_gives_dots_only(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const m = M.buildMapModel(data, mkView(), mkState());
        const uniq = (key) => [...new Set(m.dots.map((d) => d[key]))];
        return {has: m.hasSubject, legs: m.legs.length, tiers: uniq('tier'),
                syms: uniq('symbol'), subjects: m.subjects.length};
        """,
    )
    assert got == {"has": False, "legs": 0, "tiers": ["base"], "syms": ["circle"], "subjects": 0}


def test_one_person_legs_in_date_order(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const view = mkView({highlighted: pat, peopleOnGame: patOn});
        const st = mkState({people: ['pat'], school: ['a']});
        const m = M.buildMapModel(data, view, st);
        return {subjects: m.subjects.map((s) => [s.kind, s.label, s.symbol]),
                legs: m.legs.map((l) => [l.from, l.to, l.season, l.family]),
                firstTo: m.legs.map((l) => l.to)};
        """,
    )
    assert got["subjects"] == [["person", "Pat", "circle"]]
    # 2024 date order: 1 (09-07), 0 (09-14), 2 (10-12); 2025: 6, 7, (8 unlocated), 10.
    # Games 0 and 2 share a venue, so 0 -> 2 is a zero-length leg and is omitted.
    assert got["legs"] == [
        [1, 0, 2024, "disney"],
        [6, 7, 2025, "nbc"],
        [7, 10, 2025, "nbc"],
    ]


def test_school_subjects_and_labels(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const m = M.buildMapModel(data, mkView(), mkState({school: ['a', 'b']}));
        const subjects = m.subjects.map((s) => [s.kind, s.label, s.symbol]);
        return {subjects, legs: m.legs.length > 0};
        """,
    )
    assert got["subjects"] == [["school", "Aces", "circle"], ["school", "Bears", "square"]]
    assert got["legs"] is True


def test_season_break_and_destination_family(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const m = M.buildMapModel(data, mkView({highlighted: pat, peopleOnGame: patOn}),
                                  mkState({people: ['pat']}));
        const fam = m.legs.every((l) => l.family === data.familyOf[l.to]);
        const cross = m.legs.some((l) => data.t.season[l.from] !== data.t.season[l.to]);
        const firstGames = [1, 6];
        return {fam, cross, firstIsTo: m.legs.some((l) => firstGames.includes(l.to))};
        """,
    )
    assert got == {"fam": True, "cross": False, "firstIsTo": False}


def test_failing_game_is_skipped_and_fades(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const passes = ones(); passes[7] = 0;          // game 7: nbc at Beta Bowl (venue 1)
        const st = mkState({people: ['pat']});
        const hl = pat.filter((i) => i !== 7);
        const on = new Map(hl.map((i) => [i, [0]]));
        const fade = M.buildMapModel(data, mkView({passes, highlighted: hl, peopleOnGame: on}), st);
        const vis = ones(); vis[7] = 0;
        const hide = M.buildMapModel(data, mkView({passes, visible: vis, highlighted: hl,
                                                   peopleOnGame: on}), st);
        // Game 1 (nbc, venue 1) still passes, so (1, nbc) is not faded; fail game 1 too.
        const p2 = ones(); p2[7] = 0; p2[1] = 0;
        const hl2 = pat.filter((i) => i !== 7 && i !== 1);
        const on2 = new Map(hl2.map((i) => [i, [0]]));
        const fade2 = M.buildMapModel(
          data, mkView({passes: p2, highlighted: hl2, peopleOnGame: on2}), st);
        const v2 = ones(); v2[7] = 0; v2[1] = 0;
        const hide2 = M.buildMapModel(data, mkView({passes: p2, visible: v2, highlighted: hl2,
                                                    peopleOnGame: on2}), st);
        const legs = (m) => m.legs.map((l) => [l.from, l.to]);
        return {
          joins: legs(fade), sameLegs: JSON.stringify(legs(fade)) === JSON.stringify(legs(hide)),
          fadedNone: fade.faded.length, hideNone: hide.faded.length,
          fadedKeys: fade2.faded.map((f) => [f.venue, f.family]), hide2: hide2.faded.length,
        };
        """,
    )
    # Game 7 is skipped: the 2025 path joins 6 -> 10 (same venue, so no leg is drawn).
    assert got["joins"] == [[1, 0]]
    assert got["sameLegs"] is True
    assert got["fadedNone"] == 0
    assert got["hideNone"] == 0
    assert got["fadedKeys"] == [[1, "nbc"]]
    assert got["hide2"] == 0


def test_no_location_games_never_draw_and_are_counted(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const m = M.buildMapModel(data, mkView({highlighted: pat, peopleOnGame: patOn}),
                                  mkState({people: ['pat']}));
        const vis = ones(); vis[8] = 0;
        const m0 = M.buildMapModel(data, mkView({visible: vis}), mkState());
        return {n: m.noLocationCount, n0: m0.noLocationCount,
                inLeg: m.legs.some((l) => l.from === 8 || l.to === 8),
                inDot: [...m.venueGames.values()].flat().includes(8)};
        """,
    )
    assert got == {"n": 1, "n0": 0, "inLeg": False, "inDot": False}


def test_dots_one_per_venue_and_family(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const m = M.buildMapModel(data, mkView(), mkState());
        const at0 = m.dots.filter((d) => d.venue === 0);
        const at1 = m.dots.filter((d) => d.venue === 1);
        return {fams0: at0.map((d) => d.family), fams1: at1.map((d) => d.family),
                sameXY: new Set(at0.map((d) => d.x + ',' + d.y)).size,
                drawn: m.drawnCount,
                order: m.dots.map((d) => d.family)};
        """,
    )
    # Venue 0 hosts disney (games 0, 2, 6) and nbc (10): two dots at one x, y.
    assert got["fams0"] == ["disney", "nbc"]
    assert got["sameXY"] == 1
    assert got["fams1"] == ["nbc"]
    assert got["drawn"] == 6
    assert got["order"] == sorted(got["order"], key=["disney", "cbs", "nbc"].index)


def test_compare_symbols_shared_star_and_cap(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const on = new Map([[0, [0, 1]], [1, [0]], [6, [1]]]);
        const view = mkView({highlighted: [0, 1, 6], peopleOnGame: on});
        const m = M.buildMapModel(data, view, mkState({people: ['pat', 'quinn']}));
        const symsAt = m.dots.filter((d) => d.venue === 0 && d.family === 'disney'
          && d.tier === 'subject').map((d) => d.symbol);
        const five = M.mapSubjects(data, mkView(), mkState({school: ['a', 'b', 'c', 'd', 'e']}));
        const m5 = M.buildMapModel(data, mkView(), mkState({school: ['a', 'b', 'c', 'd', 'e']}));
        // Game 3 is Foxes vs Bears: with b then f picked, the earlier pick (b) names it.
        const two = M.buildMapModel(data, mkView(), mkState({school: ['b', 'f']}));
        const star = two.dots.filter((d) => d.symbol === 'star').length;
        const g3 = two.dots.find(
          (d) => d.venue === 5 && d.family === 'nbc' && d.tier === 'subject');
        return {subj: m.subjects.map((s) => s.symbol), shared: m.hasShared,
                dots: m.dots.filter((d) => d.tier === 'subject').map((d) => [d.venue, d.symbol]),
                five: five.map((s) => s.symbol), capped: m5.shapesCapped, capped2: two.shapesCapped,
                star, g3sym: g3.symbol, symsAt: symsAt};
        """,
    )
    assert got["subj"] == ["circle", "square"]
    assert got["shared"] is True
    assert got["symsAt"] == ["square", "star"]
    assert got["five"] == ["circle", "square", "diamond", "triangle-up", "circle"]
    assert got["capped"] is True
    assert got["capped2"] is False
    assert got["star"] == 0
    assert got["g3sym"] == "circle"


def test_out_and_back_lens_and_zero_length_leg(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        // Games 6 (venue 0), 7 (venue 1), 10 (venue 0): out and back between two venues.
        const hl = [6, 7, 10];
        const m = M.buildMapModel(data, hlView(hl), mkState({people: ['pat']}));
        const [out, back] = m.legs;
        // Side of the out leg's direction of travel on which each leg's midpoint falls.
        const a = out.points[0], b = out.points[out.points.length - 1];
        const side = (leg) => {
          const mid = leg.points[Math.floor(leg.points.length / 2)];
          return Math.sign((b.x - a.x) * (mid.y - a.y) - (b.y - a.y) * (mid.x - a.x));
        };
        // Games 0 and 2 share venue 0: no leg between them.
        const hl2 = [0, 2];
        const m2 = M.buildMapModel(data, hlView(hl2), mkState({people: ['pat']}));
        const opposite = side(out) === -side(back) && side(out) !== 0;
        return {n: m.legs.length, opposite, zero: m2.legs.length};
        """,
    )
    assert got == {"n": 2, "opposite": True, "zero": 0}


def test_edge_and_nassau_markers(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const m = M.buildMapModel(data, mkView(), mkState());
        const passes = ones(); passes[5] = 0;       // the only Dublin game
        const m2 = M.buildMapModel(data, mkView({passes}), mkState());
        const vis = ones(); vis[5] = 0;
        const m3 = M.buildMapModel(data, mkView({passes, visible: vis}), mkState());
        return {a: m.markers, b: m2.markers, c: m3.markers.map((x) => x.label)};
        """,
    )
    by = {mk["label"]: mk for mk in got["a"]}
    assert (by["Dublin"]["x"], by["Dublin"]["y"], by["Dublin"]["family"]) == (955, 30, "disney")
    assert abs(by["Nassau"]["x"] - 884.55) <= 0.01
    assert by["Nassau"]["family"] == "cbs"
    assert by["Dublin"]["faded"] is False
    faded = {mk["label"]: mk["faded"] for mk in got["b"]}
    assert faded["Dublin"] is True
    assert "Dublin" not in got["c"]


def test_tooltip_lines(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const hl = [1, 0, 2, 6, 7, 10];
        const on = new Map(hl.map((i) => [i, [0]]));
        const m = M.buildMapModel(data, mkView({highlighted: hl, peopleOnGame: on}),
                                  mkState({people: ['pat']}));
        const two = M.buildMapModel(data, mkView({highlighted: hl, peopleOnGame: on}),
                                    mkState({people: ['pat', 'quinn']}));
        const hi = M.buildMapModel(data, hlView([4]), mkState({people: ['pat']}));
        return {
          one: M.venueTooltipLines(data, m, 0),
          two: M.venueTooltipLines(data, two, 0).map((l) => l.text),
          ie: M.venueTooltipLines(data, m, 3)[0].text,
          neutral: M.venueTooltipLines(data, hi, 2).map((l) => l.text),
          plain: M.venueTooltipLines(data, M.buildMapModel(data, mkView(), mkState()), 1)
            .map((l) => l.text),
        };
        """,
    )
    one = got["one"]
    assert one[0] == {"text": "Alpha Field · South Bend, IN", "kind": "title"}
    assert one[1]["text"] == "ABC/ESPN 3 · NBC/Peacock 1"
    assert one[2]["text"] == "── Pat here ──"
    assert [line["text"] for line in one[3:6]] == [
        "2024-09-14  Bears @ Aces  NetOne",
        "2024-10-12  Eagles @ Aces  NetOne",
        "2025-09-06  Cats @ Aces  NetOne",
    ]
    assert one[6] == {"text": "+1 more", "kind": "hint"}
    assert got["two"][2] == "── ● Pat here ──"
    assert got["ie"] == "Dublin Arena · Dublin, Ireland"
    assert "2024-11-02  Cats vs Dogs  NetThree" not in got["plain"]
    assert got["neutral"][-1] == "2024-11-02  Cats vs Dogs  NetThree"
    assert got["plain"][1] == "NBC/Peacock 2"


def test_counts_and_empty(guarded_page: Page, site_url: str) -> None:
    got = _model(
        guarded_page,
        site_url,
        """
        const none = new Uint8Array(G.length);
        const m = M.buildMapModel(data, mkView({passes: none, visible: none}), mkState());
        const full = M.buildMapModel(data, mkView(), mkState());
        return {emptyAll: m.emptyAll, drawn: m.drawnCount, dots: m.dots.length,
                full: full.emptyAll, fullDrawn: full.drawnCount};
        """,
    )
    assert got == {"emptyAll": True, "drawn": 0, "dots": 0, "full": False, "fullDrawn": 6}
