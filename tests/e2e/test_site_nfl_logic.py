"""999.5-07: the DOM-free NFL core (data.js, palette.js, state.js, url-state.js).

In-page tests on the synthetic nfl-data fixture only; no vault rows.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

PRELUDE = """
const D = await import('./sports/nfl/data.js');
const S = await import('./sports/nfl/state.js');
const U = await import('./sports/nfl/url-state.js');
const P = await import('./sports/nfl/palette.js');
const CP = await import('./modules/palette.js');
const raw = await (await fetch('nfl-data.json')).json();
const m = D.prepareNfl(raw);
"""


@pytest.fixture
def run(nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None]) -> Callable[[str], Any]:
    open_flagon_cfb(nfl_guarded_page)

    def _run(body: str) -> Any:
        return nfl_guarded_page.evaluate("async () => {" + PRELUDE + body + "}")

    return _run


# ------------------------------------------------------------------ data.js


def test_prepare_counts_and_flexed_row(run: Callable[[str], Any], nfl_fixture_raw: dict) -> None:
    g = nfl_fixture_raw["games"]
    i = g["flexed"].index(True)
    got = run(f"return {{ n: m.n, row: D.gameRow(m, {i}) }}")
    assert got["n"] == len(g["season"])
    row = got["row"]
    assert row["flexed"] is True
    assert row["originalSlot"] == nfl_fixture_raw["lookups"]["slots"][g["original_slot"][i]]
    assert (
        row["originalNetwork"]
        == nfl_fixture_raw["lookups"]["networks"][g["original_network"][i]]["name"]
    )
    assert row["changeUrl"] == g["change_url"][i]


def test_game_row_nulls_crew_and_era(run: Callable[[str], Any], nfl_fixture_raw: dict) -> None:
    g = nfl_fixture_raw["games"]
    no_net = g["network"].index(None)
    no_view = g["viewers"].index(None)
    with_view = next(k for k, v in enumerate(g["viewers"]) if v is not None)
    got = run(
        f"return {{ a: D.gameRow(m, {no_net}), b: D.gameRow(m, {no_view}),\n"
        f"c: D.gameRow(m, {with_view}) }}"
    )
    assert got["a"]["network"] is None
    assert got["b"]["viewers"] is None and got["b"]["era"] is None and got["b"]["scope"] is None
    assert got["b"]["cause"] == g["cause"][no_view]
    assert got["c"]["era"] is not None and got["c"]["cause"] is None
    people = nfl_fixture_raw["lookups"]["people"]
    expect = [{"name": people[c["person"]]["name"], "role": c["role"]} for c in g["crew"][0]]
    assert run("return D.gameRow(m, 0).crew") == expect
    for k in range(len(g["season"])):
        for key, col in (("homePoints", "home_points"), ("excitement", "excitement")):
            if g[col][k] is None:
                assert run(f"return D.gameRow(m, {k}).{key}") is None


def test_person_games_and_category_precedence(
    run: Callable[[str], Any], nfl_fixture_raw: dict
) -> None:
    g = nfl_fixture_raw["games"]
    n = len(g["season"])
    expected_cat = []
    for i in range(n):
        if g["standalone"][i]:
            expected_cat.append(0)
        elif g["agotw"][i]:
            expected_cat.append(1)
        elif g["cbs_national"][i]:
            expected_cat.append(2)
        elif g["international"][i]:
            expected_cat.append(3)
        else:
            expected_cat.append(4)
    got = run("return { cat: Array.from(m.category), pg: [...m.personGames.entries()] }")
    assert got["cat"] == expected_cat
    pg = {k: v for k, v in got["pg"]}
    for person, games in pg.items():
        assert games == [i for i in range(n) if any(c["person"] == person for c in g["crew"][i])]


def test_category_agrees_with_special_rows(run: Callable[[str], Any]) -> None:
    bad = run(
        """
        const out = [];
        for (const r of m.special) {
          const c = [0, 0, 0, 0, 0];
          for (const i of m.franchiseGames.get(r.franchise) || []) {
            if (m.cols.season[i] === r.season) c[m.category[i]]++;
          }
          if (c[0] !== r.standalone_total || c[1] !== r.agotw || c[2] !== r.cbs_national
              || c[3] !== r.international_other
              || r.special !== r.standalone_total + r.agotw + r.cbs_national) out.push(r);
        }
        return out;
        """
    )
    assert bad == []


def test_model_blocks_typed(run: Callable[[str], Any], nfl_fixture_raw: dict) -> None:
    got = run(
        """return { special: m.special.length, sw: [...m.seasonWeeks.keys()],
          fox: m.foxBooths.length, fs: m.foxSeasons, ag: m.agotw.length,
          gl: m.foxBooths[0].gameList, rate: m.special.map(r => r.agotw_rate) }"""
    )
    assert got["special"] == len(nfl_fixture_raw["special"]["season"])
    assert got["sw"] == nfl_fixture_raw["season_weeks"]["season"]
    assert got["fox"] == len(nfl_fixture_raw["fox_booths"]["season"])
    assert got["fs"] == sorted(set(nfl_fixture_raw["fox_booths"]["season"]), reverse=True)
    assert got["ag"] == len(nfl_fixture_raw["agotw_viewership"]["season"])
    assert got["gl"] == nfl_fixture_raw["fox_booths"]["game_list"][0]
    assert got["rate"] == nfl_fixture_raw["special"]["agotw_rate"]


def test_colors_reach_three_to_one(run: Callable[[str], Any]) -> None:
    ratios = run(
        """
        const bg = { light: '#FFFFFF', dark: '#14161A' };
        const out = [];
        const all = [...Object.values(P.NFL_CATEGORY_COLORS), P.NFL_OTHER_COLOR,
          ...P.NFL_CREW_STYLES];
        for (const e of all) for (const t of ['light', 'dark']) {
          out.push(CP.contrastRatio(e[t], bg[t]));
        }
        return out;
        """
    )
    assert len(ratios) == 20
    assert min(ratios) >= 3.0


# ----------------------------------------------------------------- state.js


def test_default_state(run: Callable[[str], Any], nfl_fixture_raw: dict) -> None:
    s = run("return S.defaultNflState(m)")
    seasons = nfl_fixture_raw["games"]["season"]
    assert s["seasons"] == [min(seasons), max(seasons)]
    assert s["fseason"] == nfl_fixture_raw["freshness"]["fox_default_season"]
    assert s["view"] == "special" and s["teams"] == [] and s["selection"] is None


def test_game_passes_and_person_highlight(run: Callable[[str], Any], nfl_fixture_raw: dict) -> None:
    g = nfl_fixture_raw["games"]
    fr = nfl_fixture_raw["lookups"]["franchises"]
    team = fr[g["home"][0]]["id"]
    expect_team = [
        i
        for i in range(len(g["season"]))
        if g["home"][i] == g["home"][0] or g["away"][i] == g["home"][0]
    ]
    expect_any = [i for i in range(len(g["season"])) if g["agotw"][i] or g["cbs_national"][i]]
    expect_snf = [i for i in range(len(g["season"])) if g["standalone"][i] and g["slot"][i] == 5]
    got = run(
        f"""
        const d = S.defaultNflState(m);
        const idx = (st) => [...Array(m.n).keys()].filter(i => S.gamePasses(m, st, i));
        const pp = m.people[m.cols.crew[0][0].person].id;
        return {{
          all: idx(d).length,
          team: idx({{ ...d, teams: ['{team}'] }}),
          any: idx({{ ...d, cats: ['agotw', 'cbs'] }}),
          snf: idx({{ ...d, cats: ['snf'] }}),
          both: idx({{ ...d, teams: ['{team}'], cats: ['agotw', 'cbs'] }}),
          hl: [...Array(m.n).keys()].filter(i => S.personHighlight(m, {{ ...d, people: [pp] }}, i)),
          pg: m.personGames.get(m.personIndex.get(pp)),
        }};
        """
    )
    assert got["all"] == len(g["season"])
    assert got["team"] == expect_team
    assert got["any"] == expect_any
    assert got["snf"] == expect_snf
    assert got["both"] == [i for i in expect_team if i in expect_any]
    assert got["hl"] == got["pg"]


def test_team_bars_range_rates_and_fading(run: Callable[[str], Any], nfl_fixture_raw: dict) -> None:
    sp = nfl_fixture_raw["special"]
    sw = nfl_fixture_raw["season_weeks"]
    fr = nfl_fixture_raw["lookups"]["franchises"]
    rng = (2024, 2025)
    denom_fox = sum(
        sw["fox_doubleheader_weeks"][k] - sw["fox_ambiguous_weeks"][k]
        for k in range(len(sw["season"]))
        if rng[0] <= sw["season"][k] <= rng[1]
    )
    totals: dict[int, int] = {}
    agotw: dict[int, int] = {}
    for k in range(len(sp["season"])):
        if rng[0] <= sp["season"][k] <= rng[1]:
            f = sp["franchise"][k]
            totals[f] = totals.get(f, 0) + sp["special"][k] + sp["international_other"][k]
            agotw[f] = agotw.get(f, 0) + sp["agotw"][k]
    got = run(
        """
        const d = { ...S.defaultNflState(m), seasons: [2024, 2025] };
        const t = S.teamBars(m, { ...d, teams: [m.franchises[0].id], cats: ['agotw'] });
        return { bars: S.teamBars(m, d), faded: t.map(b => [b.franchise, b.teamFaded,
          b.segmentFaded.standalone, b.segmentFaded.agotw]) };
        """
    )
    bars = got["bars"]
    assert len(bars) == len(fr)
    order = [(-b["total"], b["name"]) for b in bars]
    assert order == sorted(order)
    for b in bars:
        assert b["total"] == totals.get(b["franchise"], 0)
        assert b["agotwRate"] == {"count": agotw.get(b["franchise"], 0), "denom": denom_fox}
    for f, team_faded, st_faded, ag_faded in got["faded"]:
        assert team_faded is (f != 0)
        assert st_faded is True and ag_faded is False


def test_rate_text_and_season_rows(run: Callable[[str], Any]) -> None:
    got = run(
        """return { a: S.rateText(4, 8), b: S.rateText(1, 3), c: S.rateText(0, 0),
          rows: S.teamSeasonRows(m, S.defaultNflState(m), 0).map(r => r.season) }"""
    )
    assert got["a"] == "4 of 8 weeks (50%)"
    assert got["b"] == "1 of 3 weeks (33%)"
    assert got["c"] == "n/a"
    assert got["rows"] == sorted(got["rows"], reverse=True) and len(got["rows"]) >= 1


def test_fox_rows_and_agotw_series(run: Callable[[str], Any], nfl_fixture_raw: dict) -> None:
    fb = nfl_fixture_raw["fox_booths"]
    n25 = sum(1 for s in fb["season"] if s == 2025)
    got = run(
        """
        const d = S.defaultNflState(m);
        const rows = S.foxRows(m, { ...d, fseason: 2025 });
        return { groups: rows.map(r => [r.season, r.group, r.rank]),
          none: S.foxRows(m, { ...d, fseason: 1999 }),
          ag: S.agotwSeries(m, d),
          narrow: S.agotwSeries(m, { ...d, seasons: [2025, 2025] }).points.length };
        """
    )
    assert len(got["groups"]) == n25 and {r[0] for r in got["groups"]} == {2025}
    rank = {"lead": 0, "other": 1, "others_pooled": 2}
    assert [rank[r[1]] for r in got["groups"]] == sorted(rank[r[1]] for r in got["groups"])
    assert got["none"] == []
    assert [p["season"] for p in got["ag"]["points"]] == [2024, 2025, 2026]
    assert [len(s["points"]) for s in got["ag"]["segments"]] == [1, 2]
    assert [s["order"] for s in got["ag"]["segments"]] == [0, 1]
    assert got["narrow"] == 1


def test_table_games_and_filter_count(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const d = S.defaultNflState(m);
        const sel = { kind: 'games', key: 'k', label: 'l', games: [3, 1, 20, 2] };
        const pp = m.people[m.cols.crew[0][0].person].id;
        const dates = (l) => l.map(i => m.cols.date[i]);
        const byPerson = S.tableGames(m, { ...d, people: [pp] });
        return { none: S.tableGames(m, d),
          selDates: dates(S.tableGames(m, { ...d, selection: sel })),
          selSet: S.tableGames(m, { ...d, selection: sel }).slice().sort((a, b) => a - b),
          filtered: S.tableGames(m, { ...d, selection: sel, seasons: [2025, 2025] })
            .every(i => m.cols.season[i] === 2025),
          byPerson, pg: m.personGames.get(m.personIndex.get(pp)),
          c0: S.activeFilterCount(m, d),
          c4: S.activeFilterCount(m, { ...d, seasons: [2025, 2025],
            teams: [m.franchises[0].id], cats: ['snf'], people: [pp] }) };
        """
    )
    assert got["none"] == []
    assert got["selDates"] == sorted(got["selDates"], reverse=True)
    assert got["selSet"] == [1, 2, 3, 20]
    assert got["filtered"] is True
    assert sorted(got["byPerson"]) == sorted(got["pg"])
    assert (got["c0"], got["c4"]) == (0, 4)


# ------------------------------------------------------------- url-state.js


def test_encode_default_and_order(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const d = S.defaultNflState(m);
        return { def: U.encodeNflState(d, m),
          full: U.encodeNflState({ ...d, view: 'fox', seasons: [2024, 2025],
            teams: [m.franchises[0].id], adjusted: true, metric: 'excitement' }, m),
          id: m.franchises[0].id };
        """
    )
    assert got["def"] == "?sport=nfl"
    assert got["full"] == (
        f"?sport=nfl&view=fox&seasons=2024-2025&team={got['id']}&adj=1&m=excitement"
    )


def test_round_trip(run: Callable[[str], Any]) -> None:
    ok = run(
        """
        const d = S.defaultNflState(m);
        const s = S.canonicalNflState({ ...d, view: 'scatter', seasons: [2025, 2024],
          teams: [m.franchises[1].id, m.franchises[0].id], people: [m.people[2].id],
          cats: ['flexed', 'tnf'], fseason: 2024, adjusted: true, metric: 'volatility',
          agotwY: 'resid', scatterX: 'margin', scatterY: 'excitement', dots: 'hide' }, m);
        const back = U.decodeNflState(U.encodeNflState(s, m), m);
        return JSON.stringify(back) === JSON.stringify(S.canonicalNflState(s, m));
        """
    )
    assert ok is True


def test_decode_never_throws(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const d = S.defaultNflState(m);
        const q = ['%', '?sport=nfl&seasons=abc', '?team=nope,%E0%A4%A', '?cat=bogus,tnf',
          '?fseason=1850', '?view=bogus', '?seasons=2030-2001', '?sport=cfb&team=%', '&&==', ''];
        const out = q.map(x => U.decodeNflState(x, m));
        return { out, d, ids: m.franchises.map(f => f.id) };
        """
    )
    out, d = got["out"], got["d"]
    assert out[0] == d and out[1]["seasons"] == d["seasons"]
    assert out[2]["teams"] == [] and out[3]["cats"] == ["tnf"]
    assert out[4]["fseason"] == d["fseason"] and out[5]["view"] == "special"
    assert out[6]["seasons"] == d["seasons"] and out[7] == d
