"""In-browser proof of the weekend map's pure modules (Phase 24, plan 03): the window shape
rules and symbol table (`weekend-map.js`), the palette constants, the CFB weekend game's venue
fields (`weekend-data.js`), the day model (dots, nudge rows, edge markers, not-on-map list, splat
input) and the figure builder (`weekend-map-chart.js`).

Both modules are pure and DOM-free; these tests import them with `page.evaluate` and feed them
synthetic WeekendGame literals built here, so they need no fixture data beyond a served page.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_IMPORT = (
    "const M = await import('./modules/weekend-map.js');"
    "const P = await import('./modules/palette.js');"
)


@pytest.fixture
def map_page(guarded_page: Page, open_app: Callable[[Page, str], None]) -> Page:
    open_app(guarded_page, "")
    return guarded_page


def _run(page: Page, body: str, arg: Any = None) -> Any:
    return page.evaluate(f"async (arg) => {{ {_IMPORT} {body} }}", arg)


# -- window rules --------------------------------------------------------------------------


def test_cfb_window_boundaries(map_page: Page) -> None:
    out = _run(
        map_page,
        "return arg.map((m) => M.cfbWindow(m));",
        [0, 720, 869, 870, 1139, 1140, 1319, 1320, 1439, None],
    )
    assert out == [
        "noon",
        "noon",
        "noon",
        "afternoon",
        "afternoon",
        "prime",
        "prime",
        "late",
        "late",
        "tba",
    ]


def test_nfl_window_from_slot_name(map_page: Page) -> None:
    slots = [
        "Sunday early",
        "Sunday late",
        "TNF",
        "SNF",
        "MNF",
        "International",
        "Saturday",
        "Christmas",
        "Black Friday",
        "Thanksgiving",
        "Other",
        None,
    ]
    out = _run(map_page, "return arg.map((s) => M.nflWindow(s));", slots)
    assert out == ["early", "late"] + ["night"] * 9 + ["tba"]


def test_window_symbol_table_is_frozen_and_complete(map_page: Page) -> None:
    out = _run(
        map_page,
        """return {
          cfb: M.WINDOW_SYMBOL.cfb, nfl: M.WINDOW_SYMBOL.nfl, tba: M.WINDOW_SYMBOL.tba,
          frozen: Object.isFrozen(M.WINDOW_SYMBOL) && Object.isFrozen(M.WINDOW_SYMBOL.cfb)
            && Object.isFrozen(M.WINDOW_SYMBOL.nfl),
          labels: M.WINDOW_LABELS, caption: M.WINDOW_CAPTION,
          symbols: [
            M.symbolOf({ sport: 'cfb', kickoffMin: 720 }),
            M.symbolOf({ sport: 'cfb', kickoffMin: 1200 }),
            M.symbolOf({ sport: 'cfb', kickoffMin: null }),
            M.symbolOf({ sport: 'nfl', kickoffMin: 780, slotName: 'Sunday late' }),
            M.symbolOf({ sport: 'nfl', kickoffMin: 1200, slotName: 'SNF' }),
            M.symbolOf({ sport: 'nfl', kickoffMin: null, slotName: null }),
          ],
        };""",
    )
    assert out["cfb"] == {
        "noon": "circle",
        "afternoon": "square",
        "prime": "diamond",
        "late": "triangle-up",
    }
    assert out["nfl"] == {"early": "circle", "late": "square", "night": "diamond"}
    assert out["tba"] == "circle-open"
    assert out["frozen"] is True
    assert out["symbols"] == [
        "circle",
        "diamond",
        "circle-open",
        "square",
        "diamond",
        "circle-open",
    ]
    assert out["labels"]["cfb"] == {
        "noon": "Noon",
        "afternoon": "Afternoon",
        "prime": "Prime",
        "late": "Late",
        "tba": "Time TBA",
    }
    assert out["labels"]["nfl"]["night"] == "Night and standalone"
    assert out["caption"]["cfb"].startswith("Noon is before 2:30 pm.")
    assert out["caption"]["nfl"].startswith("Early is the 1:00 pm window.")


# -- palette -------------------------------------------------------------------------------


def test_every_map_family_clears_three_to_one_on_the_land(map_page: Page) -> None:
    out = _run(
        map_page,
        """const rows = [];
        for (const theme of ['light', 'dark']) for (const f of P.FAMILY_ORDER) {
          rows.push([theme, f, P.contrastRatio(P.MAP_FAMILY_COLORS[theme][f], P.MAP_LAND[theme])]);
        }
        return rows;""",
    )
    assert len(out) == 16
    for theme, family, ratio in out:
        assert ratio >= 3.0, (theme, family, ratio)


def test_weekend_map_palette_constants(map_page: Page) -> None:
    out = _run(
        map_page,
        """return {
          dot: P.WEEKEND_MAP_DOT, splat: P.MAP_SPLAT_WEEKEND,
          keyline: P.MAP_LINE_WIDTH.dotKeyline, hit: P.MAP_VENUE_DOT.hitDiameter,
        };""",
    )
    assert out["dot"]["desktop"] == {
        "circle": 12,
        "square": 10,
        "diamond": 14,
        "triangle-up": 13,
        "circle-open": 12,
    }
    assert out["dot"]["phone"] == {
        "circle": 10,
        "square": 8,
        "diamond": 12,
        "triangle-up": 11,
        "circle-open": 10,
    }
    assert out["dot"]["hitDiameter"] == out["hit"] == 12
    assert out["dot"]["keyline"] == out["keyline"] == 1.5
    assert out["splat"]["viewersWeight"] == 0
    assert 0.3 <= out["splat"]["maxAlpha"] <= 0.5


# -- CFB weekend game venue fields ---------------------------------------------------------


def test_cfb_weekend_game_carries_place_and_venue(map_page: Page) -> None:
    out = map_page.evaluate(
        """async () => {
          const D = await import('./modules/data.js');
          const W = await import('./modules/weekend-data.js');
          const raw = await (await fetch('site-data.json')).json();
          const data = D.prepareData(raw);
          const n = data.scheduledRaw.season.length;
          data.scheduledRaw.place = Array.from({ length: n }, (_, j) => (j === 0 ? 0 : null));
          const games = W.cfbWeekendGames(data, data.weekend.label).filter(
            (g) => g.block === 'scheduled');
          return {
            rows: games.map((g) => [g.index, g.placeIdx, g.venue == null ? null : g.venue.name]),
            venue0: data.lookups.venues[0]?.name ?? null,
          };
        }"""
    )
    by_index = {row[0]: row for row in out["rows"]}
    assert out["venue0"] is not None
    if 0 in by_index:
        assert by_index[0][1] == 0
        assert by_index[0][2] == out["venue0"]
    for index, place_idx, venue_name in out["rows"]:
        if index != 0:
            assert place_idx is None
            assert venue_name is None


# -- day model -----------------------------------------------------------------------------

ATHENS = {"name": "Sanford Stadium", "city": "Athens", "state": "GA", "country": "US",
          "lat": 33.9498, "lon": -83.3733}  # fmt: skip
TUSCALOOSA = {"name": "Bryant-Denny Stadium", "city": "Tuscaloosa", "state": "AL",
              "country": "US", "lat": 33.2084, "lon": -87.5504}  # fmt: skip
HONOLULU = {"name": "Clarence T.C. Ching Complex", "city": "Honolulu", "state": "HI",
            "country": "US", "lat": 21.2926, "lon": -157.8167}  # fmt: skip
LONDON = {"name": "Wembley Stadium", "city": "London", "state": None, "country": "GB",
          "lat": 51.556, "lon": -0.2796}  # fmt: skip
DUBLIN = {"name": "Aviva Stadium", "city": "Dublin", "state": None, "country": "IE",
          "lat": 53.3352, "lon": -6.2285}  # fmt: skip
MADRID = {"name": "Santiago Bernabeu", "city": "Madrid", "state": None, "country": "ES",
          "lat": 40.4531, "lon": -3.6883}  # fmt: skip
NAMELESS = {"name": None, "city": None, "state": None, "country": "BR",
            "lat": -23.5, "lon": -46.6}  # fmt: skip
NO_POINT = {"name": "Mystery Field", "city": "Nowhere", "state": "ZZ", "country": "US",
            "lat": None, "lon": None}  # fmt: skip

_PLOT_975 = {"w": 975, "h": 610}  # one rendered px per map unit
_PLOT_390 = {"w": 390, "h": 244}  # 0.4 px per unit


def _place_idx(venue: dict[str, Any]) -> int:
    """A stable stand-in place index per venue, as the data file's lookup gives one."""
    return sum(ord(c) for c in f"{venue['name']}|{venue['lat']}|{venue['lon']}")


def _game(key: str, venue: dict[str, Any] | None, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "key": key,
        "sport": "cfb",
        "block": "scheduled",
        "index": 0,
        "date": "2026-10-31",
        "kickoffMin": 720,
        "networkId": "fox",
        "networkName": "FOX",
        "family": "fox",
        "away": "Away",
        "home": f"Home {key}",
        "awayRank": None,
        "homeRank": None,
        "neutral": False,
        "pbp": None,
        "analyst": None,
        "lead": False,
        "crewKnown": False,
        "past": False,
        "placeIdx": None if venue is None else _place_idx(venue),
        "venue": venue,
    }
    base.update(kw)
    return base


def _model(page: Page, games: list[dict[str, Any]], **env: Any) -> Any:
    arg = {"games": games, "env": env}
    return _run(
        page,
        """const picked = new Set(arg.env.failKeys ?? []);
        const matched = new Set(arg.env.matchKeys ?? []);
        const badNet = new Set(arg.env.badNetworks ?? []);
        const passes = (g) => (picked.has(g.key) ? false : matched.has(g.key) ? true : null);
        const networksPicked = (id) => (badNet.has(id) ? false : null);
        const m = M.buildWeekendMapModel({
          games: arg.games, day: '2026-10-31', passes, networksPicked, theme: 'light',
          mobile: arg.env.mobile ?? false, plot: arg.env.plot ?? { w: 975, h: 610 },
        });
        const slim = (d) => ({
          key: d.key, x: d.x, y: d.y, vx: d.venueX, vy: d.venueY, symbol: d.symbol,
          size: d.size, family: d.family, faded: d.faded, ringed: d.ringed,
          label: d.label ?? null, text: d.text ?? null, side: d.side ?? null,
        });
        return {
          dots: m.dots.map(slim), markers: m.markers.map(slim),
          notOnMap: m.notOnMap.map((g) => g.key), counts: m.counts,
          splat: m.splatModel,
        };""",
        arg,
    )


def test_every_game_lands_in_exactly_one_place(map_page: Page) -> None:
    games = [
        _game("a", ATHENS),
        _game("b", HONOLULU),
        _game("c", LONDON),
        _game("d", None),
        _game("e", NAMELESS),
        _game("f", NO_POINT),
        _game("g", MADRID, kickoffMin=None),
    ]
    out = _model(map_page, games)
    placed = [d["key"] for d in out["dots"]] + [m["key"] for m in out["markers"]]
    everything = placed + out["notOnMap"]
    assert sorted(everything) == sorted(g["key"] for g in games)
    assert {d["key"] for d in out["dots"]} == {"a", "b"}
    assert {m["key"] for m in out["markers"]} == {"c", "g"}
    assert sorted(out["notOnMap"]) == ["d", "e", "f"]  # never at a home city
    assert out["counts"]["total"] == 7
    hawaii = next(d for d in out["dots"] if d["key"] == "b")
    assert 216 <= hawaii["x"] <= 332 and 528 <= hawaii["y"] <= 603  # the inset
    labels = {m["key"]: m["label"] for m in out["markers"]}
    assert labels == {"c": "London", "g": "Madrid"}
    assert next(m for m in out["markers"] if m["key"] == "g")["symbol"] == "circle-open"


def test_not_on_map_order_known_time_then_network_then_home(map_page: Page) -> None:
    games = [
        _game("tba", None, kickoffMin=None, home="Aardvark"),
        _game("late", None, kickoffMin=1200, home="Zed", networkId="fox"),
        _game("early-b", None, kickoffMin=720, home="Bravo", networkId="fox"),
        _game("early-a", None, kickoffMin=720, home="Alpha", networkId="fox"),
        _game("early-abc", None, kickoffMin=720, home="Charlie", networkId="abc"),
    ]
    out = _model(map_page, games)
    assert out["notOnMap"] == ["early-a", "early-b", "early-abc", "late", "tba"]


def test_shared_venue_row_is_centred_ordered_and_pitched(map_page: Page) -> None:
    games = [
        _game("late", ATHENS, kickoffMin=900),  # square 10
        _game("tba", ATHENS, kickoffMin=None),  # circle-open 12
        _game("noon", ATHENS, kickoffMin=720),  # circle 12
    ]
    out = _model(map_page, games, plot=_PLOT_975)
    rows = {d["key"]: d for d in out["dots"]}
    vx, vy = rows["noon"]["vx"], rows["noon"]["vy"]
    pitch = 14  # largest member 12 + 2 px, at one px per unit
    assert rows["noon"]["x"] == pytest.approx(vx - pitch)
    assert rows["late"]["x"] == pytest.approx(vx)
    assert rows["tba"]["x"] == pytest.approx(vx + pitch)  # no time last
    assert all(d["y"] == pytest.approx(vy) for d in rows.values())


def test_a_row_wraps_after_four_sixteen_px_down(map_page: Page) -> None:
    games = [_game(f"g{i}", ATHENS, kickoffMin=720 + 10 * i) for i in range(5)]
    out = _model(map_page, games, plot=_PLOT_975)
    rows = {d["key"]: d for d in out["dots"]}
    vx, vy = rows["g0"]["vx"], rows["g0"]["vy"]
    first = [rows[f"g{i}"] for i in range(4)]
    assert [d["x"] for d in first] == pytest.approx([vx - 21, vx - 7, vx + 7, vx + 21])
    assert all(d["y"] == pytest.approx(vy) for d in first)
    assert rows["g4"]["y"] == pytest.approx(vy + 16)
    assert rows["g4"]["x"] == pytest.approx(vx)  # a lone second row is centred


def test_nudge_threshold_is_six_rendered_px(map_page: Page) -> None:
    out = _run(
        map_page,
        """const at = (dx, ppu) => M.nudgeRows(
          [{ key: 'a', x: 100, y: 100, size: 12, kickoffMin: 700 },
           { key: 'b', x: 100 + dx, y: 100, size: 12, kickoffMin: 800 }], ppu)
          .map((p) => [p.x, p.y]);
        return { four: at(4, 1), eight: at(8, 1), scaled: at(4 / 0.4, 0.4), alone: at(8, 1) };""",
    )
    assert out["four"][0][0] != 100 and out["four"][1][0] != 104  # grouped, so moved
    assert out["eight"] == [[100, 100], [108, 100]]  # apart, so left alone
    assert out["scaled"][0][0] != 100  # 4 px at 0.4 px per unit is still 4 px


def test_two_venues_four_px_apart_share_a_row_at_390(map_page: Page) -> None:
    # One degree of longitude east of Athens, in map units, from the projection itself.
    unit = map_page.evaluate(
        """async (v) => {
          const G = await import('./modules/map-geo.js');
          return G.placeVenue({ ...v, lon: v.lon + 1 }).x - G.placeVenue(v).x;
        }""",
        ATHENS,
    )
    per_px = 1 / (0.4 * unit)  # degrees of longitude per rendered px at 390
    near = {**ATHENS, "name": "Near Field", "lon": ATHENS["lon"] + 4 * per_px}
    far = {**ATHENS, "name": "Far Field", "lon": ATHENS["lon"] + 8 * per_px}
    four = {d["key"]: d for d in _model(map_page, [_game("a", ATHENS), _game("b", near)],
                                        plot=_PLOT_390)["dots"]}  # fmt: skip
    assert four["a"]["vx"] == pytest.approx(four["b"]["vx"])  # grouped: one row centre
    assert four["a"]["x"] != four["a"]["vx"]
    eight = {d["key"]: d for d in _model(map_page, [_game("a", ATHENS), _game("c", far)],
                                         plot=_PLOT_390)["dots"]}  # fmt: skip
    assert eight["a"]["x"] == eight["a"]["vx"] and eight["c"]["x"] == eight["c"]["vx"]


def test_fade_ring_and_layer_order(map_page: Page) -> None:
    games = [
        _game("m1", ATHENS, kickoffMin=900),
        _game("f1", TUSCALOOSA, kickoffMin=720),
        _game("n1", HONOLULU, kickoffMin=1000),
        _game("net", ATHENS, kickoffMin=720, networkId="cbs"),
        _game("m0", TUSCALOOSA, kickoffMin=600),
    ]
    out = _model(
        map_page,
        games,
        failKeys=["f1"],
        matchKeys=["m1", "m0"],
        badNetworks=["cbs"],
    )
    by_key = {d["key"]: d for d in out["dots"]}
    assert by_key["f1"]["faded"] and not by_key["f1"]["ringed"]
    assert by_key["net"]["faded"]  # a Networks pick fades without a person pick
    assert by_key["m1"]["ringed"] and not by_key["m1"]["faded"]
    assert not by_key["n1"]["faded"] and not by_key["n1"]["ringed"]
    order = [d["key"] for d in out["dots"]]
    layers = [(0 if by_key[k]["faded"] else 2 if by_key[k]["ringed"] else 1) for k in order]
    assert layers == sorted(layers)  # faded, normal, matched
    assert order[-2:] == ["m0", "m1"]  # within a layer, earlier kickoff first
    plain = _model(map_page, games)
    assert not any(d["faded"] or d["ringed"] for d in plain["dots"])


def test_splat_counts_only_unfaded_games(map_page: Page) -> None:
    games = [
        _game("a1", ATHENS),
        _game("a2", ATHENS, networkId="cbs", family="cbs"),
        _game("a3", ATHENS),
        _game("h", HONOLULU),
        _game("l", LONDON),
    ]
    out = _model(map_page, games, failKeys=["a3"])
    venues = {round(v["x"]): v for v in out["splat"]["venues"]}
    assert len(venues) == 2  # Athens and Honolulu; London is an edge marker
    athens = max(out["splat"]["venues"], key=lambda v: v["games"])
    assert athens["games"] == 2 and athens["score"] == 2  # a3 is faded, weight 1 each
    assert sum(athens["counts"]) == 2
    hawaii = min(out["splat"]["venues"], key=lambda v: v["games"])
    assert hawaii["region"] == 2 and athens["region"] == 1
    assert out["splat"]["medianScore"] >= 1
    none = _model(map_page, games, failKeys=["a1", "a2", "a3", "h", "l"])
    assert none["splat"]["venues"] == []


def test_edge_marker_boxes_never_intersect_at_390(map_page: Page) -> None:
    games = [
        _game("l1", LONDON, kickoffMin=720),
        _game("l2", LONDON, kickoffMin=900),
        _game("d1", DUBLIN, kickoffMin=720),
        _game("m1", MADRID, kickoffMin=1000),
        _game("m2", MADRID, kickoffMin=1100),
        _game("m3", MADRID, kickoffMin=None),
    ]
    out = _model(map_page, games, plot=_PLOT_390, mobile=True)
    ppu = 0.4
    boxes: list[tuple[str, str, float, float, float, float]] = []
    for m in out["markers"]:
        cx, cy, half = m["x"] * ppu, m["y"] * ppu, m["size"] / 2
        boxes.append((m["key"], "mark", cx - half, cy - half, cx + half, cy + half))
        if m["text"]:
            width = 6.5 * len(m["text"])
            if m["side"] == "left":
                x0, x1 = cx - half - 4 - width, cx - half - 4
            else:
                x0, x1 = cx + half + 4, cx + half + 4 + width
            boxes.append((m["key"], "label", x0, cy - 6, x1, cy + 6))
    assert sum(1 for b in boxes if b[1] == "label") == 3  # one label per site
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            apart = a[4] <= b[2] or b[4] <= a[2] or a[5] <= b[3] or b[5] <= a[3]
            assert apart, (a, b)
