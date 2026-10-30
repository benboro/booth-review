"""In-browser proof of the This weekend layout model (Phase 18, plan 05): row
classification, day tabs, time axis, sub-row packing, cell states, cell colours and the
weekend pick state. The model (`site/modules/weekend.js`) is pure and DOM-free; these tests
import it with `page.evaluate` and feed it synthetic game literals built here, so they need
no fixture data beyond a served page.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_IMPORT = "const W = await import('./modules/weekend.js');"


def _game(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "key": "g",
        "sport": "cfb",
        "block": "scheduled",
        "index": 0,
        "date": "2026-10-31",
        "kickoffMin": 720,
        "networkId": "fox",
        "networkName": "FOX",
        "family": "fox",
        "away": "Away",
        "home": "Home",
        "awayRank": None,
        "homeRank": None,
        "neutral": False,
        "pbp": None,
        "analyst": None,
        "boothRank": None,
        "lead": False,
        "crewKnown": False,
        "past": False,
    }
    base.update(kw)
    return base


@pytest.fixture
def weekend_page(guarded_page: Page, open_app: Callable[[Page, str], None]) -> Page:
    open_app(guarded_page, "")
    return guarded_page


def _run(page: Page, body: str, arg: Any = None) -> Any:
    return page.evaluate(f"async (arg) => {{ {_IMPORT} {body} }}", arg)


# -- classification ----------------------------------------------------------------------


def test_classify_cfb(weekend_page: Page) -> None:
    games = [
        _game(networkId="fox"),
        _game(networkId="peacock"),
        _game(networkId="espn-plus"),
        _game(networkId="sec-network"),
        _game(networkId="some-regional-net"),
        _game(networkId=None),
        _game(kickoffMin=None),
        _game(networkId="espn3"),
        _game(networkId="apple"),
    ]
    out = _run(weekend_page, "return arg.map((g) => W.classifyGame(g));", games)
    assert out == [
        {"section": "grid", "row": "fox"},
        {"section": "grid", "row": "streaming"},
        {"section": "compact"},
        {"section": "grid", "row": "sec-network"},
        {"section": "compact"},
        {"section": "tba"},
        {"section": "tba"},
        {"section": "compact"},
        {"section": "grid", "row": "streaming"},
    ]


def test_classify_nfl(weekend_page: Page) -> None:
    games = [
        _game(sport="nfl", networkId="cbs"),
        _game(sport="nfl", networkId="prime"),
        _game(sport="nfl", networkId=None),
    ]
    out = _run(weekend_page, "return arg.map((g) => W.classifyGame(g));", games)
    assert out == [
        {"section": "grid", "row": "cbs"},
        {"section": "grid", "row": "prime"},
        {"section": "tba"},
    ]


def test_grid_rows_constant(weekend_page: Page) -> None:
    out = _run(weekend_page, "return [W.WEEKEND_GRID_ROWS, W.BLOCK_MINUTES];")
    assert out[0] == [
        "abc", "cbs", "fox", "nbc", "espn", "espn2", "espnews", "espnu", "sec-network",
        "acc-network", "big-ten-network", "fs1", "cbs-sports-network", "tnt",
        "usa-network", "cw",
    ]  # fmt: skip
    assert out[1] == {"cfb": 210, "nfl": 195}


# -- day model ---------------------------------------------------------------------------


def test_rows_lead_with_premium_then_precedence_and_streaming_last(weekend_page: Page) -> None:
    games = [
        _game(key="a", networkId="peacock", kickoffMin=900),
        _game(key="b", networkId="espn", kickoffMin=720),
        _game(key="c", networkId="abc", kickoffMin=720),
        _game(key="d", networkId="fs1", kickoffMin=780),
        _game(key="e", networkId="fox", kickoffMin=720),
        _game(key="f", networkId="espn2", kickoffMin=720, date="2026-10-30"),
        _game(key="g", networkId="cbs", kickoffMin=930),
        _game(key="h", networkId="nbc", kickoffMin=1170),
        _game(key="i", networkId="big-ten-network", kickoffMin=720),
        _game(key="j", networkId="espn2", kickoffMin=930),
    ]
    out = _run(
        weekend_page,
        "return W.buildDayModel(arg, {sport: 'cfb', day: '2026-10-31', width: 1440})"
        ".rows.map((r) => r.id);",
        games,
    )
    assert out == [
        "fox", "abc", "espn", "nbc", "cbs", "fs1", "big-ten-network", "espn2", "streaming",
    ]  # fmt: skip


def test_build_day_model_geometry_and_buckets(weekend_page: Page) -> None:
    games = [
        _game(key="a", networkId="fox", kickoffMin=720),
        _game(key="b", networkId="fox", kickoffMin=1350),
        _game(key="c", networkId="espn-plus", kickoffMin=900),
        _game(key="d", networkId=None, kickoffMin=None),
        _game(key="e", networkId="abc", kickoffMin=None),
        _game(key="f", networkId="cbs", kickoffMin=None, date=None),
    ]
    m = _run(
        weekend_page,
        "return W.buildDayModel(arg, {sport: 'cfb', day: '2026-10-31', width: 1440});",
        games,
    )
    assert m["axis"]["start"] == 720
    assert m["axis"]["end"] == 1560
    assert m["axis"]["ticks"][0] == {"min": 720, "label": "12 pm"}
    assert m["axis"]["ticks"][-1]["label"] == "2 am"
    assert m["pxh"] == 96  # (1440 - 96) // 14 hours
    fox = m["rows"][0]
    assert fox["height"] == 44
    first, second = fox["cells"]
    assert first["left"] == 0
    assert first["width"] == round(210 * m["pxh"] / 60) - 2
    assert second["left"] == round((1350 - 720) * m["pxh"] / 60)
    assert [g["key"] for g in m["compact"]] == ["c"]
    # Time-unknown and network-unknown games, plus the undated one, all land in the strip.
    assert sorted(g["key"] for g in m["tba"]) == ["d", "e", "f"]


def test_pack_sub_rows_booth_rank_order(weekend_page: Page) -> None:
    games = [
        _game(key="r2", boothRank=2, kickoffMin=720, home="B"),
        _game(key="r1", boothRank=1, kickoffMin=720, home="C"),
        _game(key="rn", boothRank=None, kickoffMin=720, home="A"),
    ]
    out = _run(
        weekend_page,
        "const r = W.packSubRows(arg, 210);"
        "return {n: r.subRows, p: r.placed.map((x) => [x.game.key, x.subRow])};",
        games,
    )
    assert out["n"] == 3
    assert sorted(out["p"]) == [["r1", 0], ["r2", 1], ["rn", 2]]


def test_pack_seven_nfl_games_then_reuse(weekend_page: Page) -> None:
    games = [
        _game(
            sport="nfl",
            key=f"e{i}",
            kickoffMin=780,
            boothRank=i + 1,
            home=f"H{i}",
            networkId="cbs",
        )
        for i in range(7)
    ] + [
        _game(
            sport="nfl",
            key=f"l{i}",
            kickoffMin=985,
            boothRank=(1 if i == 3 else i + 2),
            home=f"L{i}",
            networkId="cbs",
        )
        for i in range(4)
    ]
    out = _run(
        weekend_page,
        "const r = W.packSubRows(arg, 195);"
        "return {n: r.subRows, p: Object.fromEntries("
        "r.placed.map((x) => [x.game.key, x.subRow]))};",
        games,
    )
    assert out["n"] == 7
    assert out["p"]["e0"] == 0
    assert out["p"]["l3"] == 0  # the rank-1 late game takes the top sub-row
    assert sorted(out["p"][f"l{i}"] for i in range(4)) == [0, 1, 2, 3]


def test_pack_ties_fall_to_home_team(weekend_page: Page) -> None:
    games = [_game(key="z", home="Zed"), _game(key="a", home="Ace")]
    out = _run(
        weekend_page,
        "return W.packSubRows(arg, 210).placed.map((x) => [x.game.key, x.subRow]);",
        games,
    )
    assert out == [["a", 0], ["z", 1]]


# -- axis --------------------------------------------------------------------------------


def test_axis_range(weekend_page: Page) -> None:
    out = _run(
        weekend_page,
        "return [W.axisRange([720, 1350], 210), W.axisRange([750], 210), W.axisRange([], 210)];",
    )
    assert out[0] == {"start": 720, "end": 1560}
    assert out[1] == {"start": 720, "end": 960}  # 12:30 + 3:30 = 16:00
    assert out[2] is None


def test_px_per_hour_clamp(weekend_page: Page) -> None:
    out = _run(
        weekend_page,
        "return [W.pxPerHour(1440, 18), W.pxPerHour(1440, 10), W.pxPerHour(1440, 13), "
        "W.pxPerHour(1440, 15)];",
    )
    assert out == [80, 120, 103, 89]


# -- day tabs ----------------------------------------------------------------------------


def test_day_tabs_and_default_day(weekend_page: Page) -> None:
    games = [
        _game(date="2026-10-29"),
        _game(date="2026-10-31"),
        _game(date="2026-10-31", kickoffMin=900),
        _game(date=None, kickoffMin=None),
    ]
    out = _run(
        weekend_page,
        "const d = W.dayTabs(arg);return {d, def: W.defaultDay(d, 'cfb'), lab: d.map(W.dayLabel)};",
        games,
    )
    assert out["d"] == ["2026-10-29", "2026-10-31"]
    assert out["def"] == "2026-10-31"
    assert out["lab"] == ["Thu. Oct. 29", "Sat. Oct. 31"]


def test_default_day_nfl_and_fallback(weekend_page: Page) -> None:
    out = _run(
        weekend_page,
        "return ["
        "W.defaultDay(['2026-10-25', '2026-10-26'], 'nfl'),"
        "W.defaultDay(['2026-10-29', '2026-10-30'], 'cfb'),"
        "W.defaultDay([], 'cfb')];",
    )
    assert out == ["2026-10-25", "2026-10-29", None]


def test_tabs_include_dated_strip_games(weekend_page: Page) -> None:
    games = [_game(date="2026-10-30", networkId=None, kickoffMin=None)]
    out = _run(weekend_page, "return W.dayTabs(arg);", games)
    assert out == ["2026-10-30"]


# -- cell state and text -----------------------------------------------------------------


def test_cell_state(weekend_page: Page) -> None:
    games = [
        _game(crewKnown=True, pbp="Joe Buck", analyst="Troy Aikman"),
        _game(),
        _game(past=True),
    ]
    out = _run(
        weekend_page,
        "const now = W.etWallMinutes('2026-10-31', 600);"
        "const later = W.etWallMinutes('2026-10-31', 800);"
        "return [W.cellState(arg[0], later), W.cellState(arg[1], now),"
        " W.cellState(arg[1], later), W.cellState(arg[2], now)];",
        games,
    )
    assert out == ["known", "tba", "not-listed", "not-listed"]


def test_et_parts_uses_eastern_time(weekend_page: Page) -> None:
    # 16:00 UTC in late October is noon EDT; 03:30 UTC on Dec. 6 is 10:30 pm EST on Dec. 5.
    out = _run(
        weekend_page,
        "return [W.etParts(new Date('2026-10-31T16:00:00Z')),"
        " W.etParts(new Date('2026-12-06T03:30:00Z'))];",
    )
    assert out[0] == {"date": "2026-10-31", "minutes": 720}
    assert out[1] == {"date": "2026-12-05", "minutes": 22 * 60 + 30}


def test_booth_line(weekend_page: Page) -> None:
    games = [
        _game(crewKnown=True, pbp="Chris Fowler", analyst="Kirk Herbstreit", lead=True),
        _game(crewKnown=True, pbp="Chris Fowler"),
        _game(crewKnown=True, pbp="Chris Fowler", analyst="Kirk Herbstreit"),
        _game(),
    ]
    out = _run(
        weekend_page,
        "return [W.boothLine(arg[0], 'known'), W.boothLine(arg[1], 'known'),"
        " W.boothLine(arg[2], 'known'), W.boothLine(arg[3], 'tba'),"
        " W.boothLine(arg[3], 'not-listed')];",
        games,
    )
    assert out[0] == {"star": True, "text": "Chris Fowler · Kirk Herbstreit", "weight": 600}
    assert out[1]["text"] == "Chris Fowler · Analyst TBA"
    assert out[2]["star"] is False
    assert out[3] == {"star": False, "text": "Crew TBA", "weight": 400}
    assert out[4] == {"star": False, "text": "Crew not listed", "weight": 400}


def test_booth_line_keeps_a_suffixed_name_whole(weekend_page: Page) -> None:
    g = _game(crewKnown=True, pbp="Mike Golic Jr.", analyst="Robert Griffin III")
    out = _run(weekend_page, "return W.boothLine(arg, 'known').text;", g)
    assert out == "Mike Golic Jr. · Robert Griffin III"


def test_matchup_text(weekend_page: Page) -> None:
    games = [
        _game(away="Florida", home="Georgia", awayRank=20, homeRank=5),
        _game(away="Florida", home="Georgia", neutral=True),
        _game(sport="nfl", away="Chiefs", home="Bills"),
    ]
    out = _run(weekend_page, "return arg.map(W.matchupText);", games)
    assert out == ["#20 Florida @ #5 Georgia", "Florida vs Georgia", "Chiefs @ Bills"]


# -- colours -----------------------------------------------------------------------------


def test_cell_colors_are_accessible(weekend_page: Page) -> None:
    out = _run(
        weekend_page,
        """
        const P = await import('./modules/palette.js');
        const fails = [];
        let n = 0;
        for (const theme of ['light', 'dark']) {
          for (const fam of Object.keys(P.FAMILY_COLORS[theme])) {
            n += 1;
            const known = W.cellColors(fam, theme, 'known');
            const tint = W.cellColors(fam, theme, 'tba');
            const lost = W.cellColors(fam, theme, 'not-listed');
            const known_ok = known.fg === '#FFFFFF'
              && P.contrastRatio(known.bg, known.fg) >= 7 && known.edge === null;
            const tint_ok = P.contrastRatio(tint.bg, tint.fg) >= 4.5;
            const edge_ok = P.contrastRatio(tint.edge, P.PAGE_BG[theme]) >= 3;
            const same = tint.bg === lost.bg && tint.bg === P.mixHex(
              P.FAMILY_COLORS[theme][fam], P.PAGE_BG[theme], 0.18);
            if (!(known_ok && tint_ok && edge_ok && same)) fails.push([theme, fam]);
          }
        }
        const unknown = W.cellColors('martian', 'light', 'known').bg
          === W.cellColors('other', 'light', 'known').bg;
        return {n, fails, unknown, faded: W.WEEKEND_FADED_OPACITY,
                families: Object.keys(P.FAMILY_COLORS.light).length};
        """,
    )
    assert out["n"] == out["families"] * 2
    assert out["fails"] == []
    assert out["unknown"] is True
    assert out["faded"] == 0.3


# -- picks and strip ---------------------------------------------------------------------


def test_weekend_pick_state_resets_unused_controls(weekend_page: Page) -> None:
    state = {
        "people": [3],
        "compare": True,
        "together": True,
        "role": "pbp",
        "seasons": [2024],
        "slots": ["a"],
        "postseason": "only",
        "game": 4,
        "booth": ["a"],
        "school": [1],
        "conferences": [2],
        "networks": [5],
    }
    defaults = {
        **state,
        "people": [],
        "compare": False,
        "together": False,
        "role": None,
        "seasons": None,
        "slots": None,
        "postseason": "all",
        "game": None,
        "booth": [],
        "school": [],
        "conferences": [],
        "networks": None,
    }
    out = _run(
        weekend_page,
        "return [W.weekendPickState(arg.state, arg.defaults, 'cfb'),"
        " W.weekendPickState({cats: ['x'], seasons: [1, 2], booths: ['a'], teams: ['t']},"
        " {cats: [], seasons: [3, 4], booths: [], teams: []}, 'nfl')];",
        {"state": state, "defaults": defaults},
    )
    cfb = out[0]
    for key in ("seasons", "slots", "postseason", "game"):
        assert cfb[key] == defaults[key]
    for key in ("people", "compare", "together", "role", "booth", "school", "conferences"):
        assert cfb[key] == state[key]
    assert cfb["networks"] == [5]
    assert out[1] == {"cats": [], "seasons": [3, 4], "booths": ["a"], "teams": ["t"]}


def test_strip_collapsed_default(weekend_page: Page) -> None:
    out = _run(
        weekend_page,
        "return [0, 6, 7, 12].map(W.stripCollapsedByDefault);",
    )
    assert out == [False, False, True, True]


def test_ap_kickoff_year_option(weekend_page: Page) -> None:
    out = _run(
        weekend_page,
        "return ["
        " W.apKickoff('2020-11-21', '2020-11-21T12:00:00-05:00', 'kickoff time not recorded',"
        " { year: true }),"
        " W.apKickoff('2020-11-21', null, 'kickoff time not recorded', { year: true }),"
        " W.apKickoff('2026-10-31', '2026-10-31T12:00:00-04:00')];",
    )
    assert out == [
        "Sat. Nov. 21, 2020, 12:00 pm ET",
        "Sat. Nov. 21, 2020, kickoff time not recorded",
        "Sat. Oct. 31, 12:00 pm ET",
    ]
