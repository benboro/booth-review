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
    expect = [
        {"name": people[c["person"]]["name"], "role": c["role"], "person": c["person"]}
        for c in g["crew"][0]
    ]
    assert run("return D.gameRow(m, 0).crew") == expect
    for k in range(len(g["season"])):
        for key, col in (("homePoints", "home_points"), ("excitement", "excitement")):
            if g[col][k] is None:
                assert run(f"return D.gameRow(m, {k}).{key}") is None


def test_person_games_and_category_precedence(
    run: Callable[[str], Any], nfl_fixture_raw: dict
) -> None:
    g = nfl_fixture_raw["games"]
    slots = nfl_fixture_raw["lookups"]["slots"]
    n = len(g["season"])
    solo = {"TNF": 0, "SNF": 1, "MNF": 2, "Thanksgiving": 3, "Christmas": 3, "Black Friday": 3}
    expected_cat = []
    for i in range(n):
        if g["standalone"][i]:
            expected_cat.append(solo.get(slots[g["slot"][i]], 4))
        elif g["agotw"][i]:
            expected_cat.append(5)
        elif g["cbs_national"][i]:
            expected_cat.append(6)
        elif g["international"][i]:
            expected_cat.append(7)
        else:
            expected_cat.append(8)
    got = run("return { cat: Array.from(m.category), pg: [...m.personGames.entries()] }")
    assert got["cat"] == expected_cat
    pg = {k: v for k, v in got["pg"]}
    for person, games in pg.items():
        assert games == [i for i in range(n) if any(c["person"] == person for c in g["crew"][i])]


def test_category_agrees_with_special_rows(run: Callable[[str], Any]) -> None:
    bad = run(
        """
        const keys = ['solo_thursday', 'solo_sunday', 'solo_monday', 'solo_holiday',
          'solo_other', 'agotw', 'cbs_national', 'international_other'];
        const out = [];
        for (const r of m.special) {
          const c = new Array(9).fill(0);
          for (const i of m.franchiseGames.get(r.franchise) || []) {
            if (m.cols.season[i] === r.season) c[m.category[i]]++;
          }
          if (keys.some((k, code) => c[code] !== r[k])) out.push(r);
        }
        return out;
        """
    )
    assert bad == []


def test_game_row_new_fields(run: Callable[[str], Any], nfl_fixture_raw: dict) -> None:
    g = nfl_fixture_raw["games"]
    lk = nfl_fixture_raw["lookups"]
    i = g["crew_source"].index("published_lineup")
    row = run(f"return D.gameRow(m, {i})")
    assert row["crewSource"] == "published_lineup"
    assert row["crewSourceUrl"] == g["crew_source_url"][i]
    net = g["network"][i]
    if net is None:
        assert row["networkFamily"] is None and row["networkGroup"] is None
    else:
        assert row["networkFamily"] == lk["networks"][net]["family"]
        grp = next((x["name"] for x in lk["network_groups"] if net in x["members"]), None)
        assert row["networkGroup"] == grp
    assert run("return D.gameRow(m, 0).crewSource") == g["crew_source"][0]


def test_prepare_requires_new_blocks(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const out = [];
        for (const k of ['booths', 'viewership']) {
          const bad = { ...raw }; delete bad[k];
          try { D.prepareNfl(bad); out.push('ok'); } catch (e) { out.push(e.message); }
        }
        return out;
        """
    )
    assert got == ["NFL data is incomplete"] * 2


def test_model_blocks_typed(run: Callable[[str], Any], nfl_fixture_raw: dict) -> None:
    lk = nfl_fixture_raw["lookups"]
    b = nfl_fixture_raw["booths"]
    v = nfl_fixture_raw["viewership"]
    got = run(
        """return { special: m.special.length, sw: [...m.seasonWeeks.keys()],
          groups: m.networkGroups.map(g => g.id),
          gon: [...m.groupOfNetwork.entries()],
          booths: m.booths.map(r => [r.season, r.network_group, r.rank]),
          gl: m.booths[0].gameList,
          cs: m.crewSeasons, csg: [...m.crewSeasonsByGroup.entries()],
          vw: m.viewership.map(r => [r.category, r.season]),
          vc: m.viewCategories.map(c => c.id),
          catalog: m.boothCatalog.map(e => [e.key, e.label, [...e.categories].sort()]),
          rate: m.special.map(r => r.agotw_rate) }"""
    )
    assert got["special"] == len(nfl_fixture_raw["special"]["season"])
    assert got["sw"] == nfl_fixture_raw["season_weeks"]["season"]
    assert got["groups"] == [x["id"] for x in lk["network_groups"]]
    gon = {}
    for gi, grp in enumerate(lk["network_groups"]):
        for net in grp["members"]:
            gon[net] = gi
    assert dict(map(tuple, got["gon"])) == gon
    rows = sorted(
        zip(b["season"], b["network_group"], b["rank"], b["game_list"], strict=True),
        key=lambda r: r[:3],
    )
    assert got["booths"] == [list(r[:3]) for r in rows]
    assert got["gl"] == rows[0][3]
    assert got["cs"] == sorted(set(b["season"]), reverse=True)
    for g, seasons in got["csg"]:
        assert seasons == sorted(
            {s for s, grp in zip(b["season"], b["network_group"], strict=True) if grp == g},
            reverse=True,
        )
    assert got["vw"] == sorted(map(list, zip(v["category"], v["season"], strict=True)))
    assert got["vc"] == [c["id"] for c in lk["view_categories"]]
    people = lk["people"]
    keys = {}
    for k in range(len(b["season"])):
        if b["games"][k] > 0:
            grp_id = lk["network_groups"][b["network_group"][k]]["id"]
            key = f"{grp_id}:{people[b['pbp_person'][k]]['id']}"
            keys[key] = None
    assert sorted(e[0] for e in got["catalog"]) == sorted(keys)
    for key, label, _cats in got["catalog"]:
        assert (
            " / " in label
            or label
            == people[next(i for i, p in enumerate(people) if p["id"] == key.split(":")[1])]["name"]
        )
    assert got["rate"] == nfl_fixture_raw["special"]["agotw_rate"]


def _luminance_js() -> str:
    return """
    const lin = (c) => {
      c /= 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    };
    const lum = (hex) => {
      const n = parseInt(hex.slice(1), 16);
      return 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
    };
    const ratio = (a, b) => {
      const la = lum(a), lb = lum(b);
      return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
    };
    """


def test_segment_colors_reach_3_to_1(
    nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None]
) -> None:
    open_flagon_cfb(nfl_guarded_page)
    got = nfl_guarded_page.evaluate(
        "async () => {"
        + PRELUDE
        + _luminance_js()
        + """
        const cs = getComputedStyle(document.documentElement);
        const bg = cs.getPropertyValue('--bg').trim().toUpperCase();
        const surface = cs.getPropertyValue('--surface').trim().toUpperCase();
        const out = [];
        const entries = [...Object.entries(P.NFL_CATEGORY_COLORS), ['other', P.NFL_OTHER_COLOR]];
        for (const [k, e] of entries) {
          const hex = e.light;
          out.push([k, ratio(hex, bg), ratio(hex, surface)]);
        }
        return { bg, surface, out };
        }"""
    )
    assert got["bg"].startswith("#") and got["surface"].startswith("#")
    assert len(got["out"]) == 9
    for key, on_bg, on_surface in got["out"]:
        assert on_bg >= 3.0, ("light", key, on_bg)
        assert on_surface >= 3.0, ("light", key, on_surface)


def test_view_category_colors_reach_3_to_1(
    nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None]
) -> None:
    """Every Viewership line color, including the per-line shades of shared hues."""
    open_flagon_cfb(nfl_guarded_page)
    got = nfl_guarded_page.evaluate(
        "async () => {"
        + PRELUDE
        + _luminance_js()
        + """
        const cs = getComputedStyle(document.documentElement);
        const bg = cs.getPropertyValue('--bg').trim().toUpperCase();
        const surface = cs.getPropertyValue('--surface').trim().toUpperCase();
        const out = [];
        for (const id of Object.keys(P.VIEW_CATEGORY_STYLE)) {
          const hex = P.viewCategoryStyle(id, 'light').color;
          out.push([id, ratio(hex, bg), ratio(hex, surface)]);
        }
        return { out };
        }"""
    )
    assert len(got["out"]) == 12
    for key, on_bg, on_surface in got["out"]:
        assert on_bg >= 3.0, ("light", key, on_bg)
        assert on_surface >= 3.0, ("light", key, on_surface)


def test_flag_labels_and_source_text(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const F = await import('./sports/nfl/game-format.js');
        const all = { standalone: true, agotw: true, cbsNational: true, international: true,
          flexed: true };
        return { labels: F.flagLabels(all), a: F.crewSourceText({ crewSource: 'published_lineup' }),
          b: F.crewSourceText({ crewSource: '506' }), c: F.crewSourceText({ crewSource: null }) };
        """
    )
    assert got["labels"] == [
        "Solo slot",
        "Fox AGOTW",
        "CBS late national",
        "International",
        "Flexed",
    ]
    assert got["a"] == "from published lineup" and got["b"] is None and got["c"] is None


def test_view_category_style_and_palette_keys(
    run: Callable[[str], Any], nfl_fixture_raw: dict
) -> None:
    ids = [c["id"] for c in nfl_fixture_raw["lookups"]["view_categories"]]
    got = run(
        f"""
        const ids = {ids!r};
        return {{ keys: Object.keys(P.NFL_CATEGORY_COLORS),
          styles: ids.map(id => P.viewCategoryStyle(id, 'light')),
          holiday: P.NFL_CATEGORY_COLORS.solo_holiday }};
        """
    )
    assert got["keys"] == [
        "solo_thursday", "solo_sunday", "solo_monday", "solo_holiday",
        "solo_other", "agotw", "cbs_national", "international_other",
    ]  # fmt: skip
    assert got["holiday"] == {"light": "#8A7A00", "dark": "#F0E442"}
    assert all(s["color"].startswith("#") and s["symbol"] for s in got["styles"])
    holiday = [
        s
        for id_, s in zip(ids, got["styles"], strict=True)
        if id_ in ("thanksgiving", "christmas", "black_friday")
    ]
    assert len({s["symbol"] for s in holiday}) == 3
    assert len({s["color"] for s in holiday}) == 3


# ----------------------------------------------------------------- state.js


def test_default_state(run: Callable[[str], Any], nfl_fixture_raw: dict) -> None:
    s = run("return S.defaultNflState(m)")
    seasons = nfl_fixture_raw["games"]["season"]
    assert s["seasons"] == [min(seasons), max(seasons)]
    assert s["cseason"] == nfl_fixture_raw["freshness"]["crews_default_season"]
    assert s["network"] == "fox" and s["booths"] == []
    assert (s["metric"], s["adjusted"], s["viewY"]) == ("margin", False, "mean")
    assert s["hiddenSegments"] == [] and s["hiddenCategories"] == []
    assert s["view"] == "special" and s["teams"] == [] and s["selection"] is None


def test_perseason_and_csort_state(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const d = S.defaultNflState(m);
        const c = (x) => S.canonicalNflState(x, m);
        return { d, off: c({ perseason: false }).perseason, odd: c({ perseason: 0 }).perseason,
          keep: c({ csort: { key: 'margin', dir: 'desc' } }).csort,
          bad: [{ key: 'crew', dir: 'asc' }, { key: 'games', dir: 'up' }, 'games', null, 7]
            .map((x) => c({ csort: x }).csort),
          keys: S.NFL_CSORT_KEYS, nat: S.NFL_NATURAL_DIR };
        """
    )
    assert got["d"]["perseason"] is True and got["d"]["csort"] is None
    assert got["off"] is False and got["odd"] is True
    assert got["keep"] == {"key": "margin", "dir": "desc"}
    assert got["bad"] == [None] * 5
    assert got["keys"] == [
        "booth",
        "season",
        "rank",
        "network",
        "games",
        "margin",
        "exc",
        "viewers",
    ]
    assert set(got["nat"]) == set(got["keys"])


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
            totals[f] = totals.get(f, 0) + sum(
                sp[c][k]
                for c in (
                    "solo_thursday", "solo_sunday", "solo_monday", "solo_holiday", "solo_other",
                    "agotw", "cbs_national", "international_other",
                )
            )  # fmt: skip
            agotw[f] = agotw.get(f, 0) + sp["agotw"][k]
    got = run(
        """
        const d = { ...S.defaultNflState(m), seasons: [2024, 2025] };
        const t = S.teamBars(m, { ...d, teams: [m.franchises[0].id], cats: ['agotw'] });
        return { bars: S.teamBars(m, d), faded: t.map(b => [b.franchise, b.teamFaded,
          b.segmentFaded.solo_thursday, b.segmentFaded.agotw]) };
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


def test_segment_counts_and_fading_map(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const d = S.defaultNflState(m);
        const bars = S.teamBars(m, d);
        const fade = (cats) => S.teamBars(m, { ...d, cats })[0].segmentFaded;
        const unfaded = (cats) => Object.entries(fade(cats)).filter(([, v]) => !v).map(([k]) => k);
        return { keys: Object.keys(bars[0].counts),
          sums: bars.every(b => b.total === Object.values(b.counts).reduce((x, y) => x + y, 0)),
          tnf: unfaded(['tnf']), holiday: unfaded(['christmas', 'blackfriday']),
          other: unfaded(['saturday']), intl: unfaded(['intl']), cbs: unfaded(['cbs']),
          flexed: unfaded(['flexed']), none: unfaded([]), ex: S.EXCLUSIVE_CATEGORIES.length };
        """
    )
    assert got["keys"] == [
        "solo_thursday", "solo_sunday", "solo_monday", "solo_holiday",
        "solo_other", "agotw", "cbs_national", "international_other",
    ]  # fmt: skip
    assert got["sums"] is True and got["ex"] == 9
    assert got["tnf"] == ["solo_thursday"]
    assert got["holiday"] == ["solo_holiday"]
    assert got["other"] == ["solo_other"]
    assert got["intl"] == ["solo_other", "international_other"]
    assert got["cbs"] == ["cbs_national"]
    assert len(got["flexed"]) == 8 and len(got["none"]) == 8


def test_crews_state_functions(run: Callable[[str], Any], nfl_fixture_raw: dict) -> None:
    b = nfl_fixture_raw["booths"]
    g = nfl_fixture_raw["games"]
    n25 = sorted(
        (b["rank"][k], b["pbp_person"][k])
        for k in range(len(b["season"]))
        if b["season"][k] == 2025 and b["network_group"][k] == 0
    )
    fox_games = [
        i for i in range(len(g["season"])) if g["season"][i] == 2025 and g["network"][i] == 0
    ]
    got = run(
        """
        const d = S.defaultNflState(m);
        const cov = S.crewsCoverage(m, d);
        return { rows: S.crewsRows(m, d).map(r => [r.rank, r.pbp_person]),
          none: S.crewsRows(m, { ...d, cseason: 1999 }),
          nets: S.crewsNetworks(m, d).map(x => x.id),
          narrow: S.crewsNetworks(m, { ...d, seasons: [2026, 2026] }).map(x => x.id),
          seasons: S.crewsSeasons(m, 0), cov };
        """
    )
    assert [tuple(r) for r in got["rows"]] == n25
    assert got["none"] == []
    assert got["nets"] == [
        x["id"]
        for gi, x in enumerate(nfl_fixture_raw["lookups"]["network_groups"])
        if any(
            g["network"][i] in x["members"]
            for i in range(len(g["season"]))
            if g["network"][i] is not None
        )
    ]
    assert set(got["narrow"]) <= set(got["nets"])
    assert got["seasons"] == [2025, 2024] or got["seasons"][0] >= got["seasons"][-1]
    assert got["cov"]["total"] == len(fox_games)
    assert got["cov"]["withCrew"] == sum(1 for i in fox_games if g["crew"][i])
    assert got["cov"]["fromLineup"] == sum(
        1 for i in fox_games if g["crew_source"][i] == "published_lineup"
    )


def test_viewership_series(run: Callable[[str], Any], nfl_fixture_raw: dict) -> None:
    v = nfl_fixture_raw["viewership"]
    got = run(
        """
        const d = S.defaultNflState(m);
        const all = S.viewershipSeries(m, d);
        return { all: all.map(s => [s.id, s.label, s.windowLevel, s.points.length]),
          p0: all[0].points[0],
          narrow: S.viewershipSeries(m, { ...d, seasons: [2025, 2025] })[0].points.length };
        """
    )
    lk = nfl_fixture_raw["lookups"]["view_categories"]
    assert [a[0] for a in got["all"]] == [c["id"] for c in lk]
    for ci, (_id, label, window, count) in enumerate(got["all"]):
        assert label == lk[ci]["label"] and window == lk[ci]["window_level"]
        assert count == sum(1 for c in v["category"] if c == ci)
    first = min(k for k in range(len(v["season"])) if v["category"][k] == 0)
    p0 = got["p0"]
    assert p0["season"] == v["season"][first] and p0["mean"] == v["mean_viewers"][first]
    assert p0["resid"] == v["viewership_resid"][first] and p0["lowN"] == v["low_n"][first]
    assert p0["gameList"] == v["game_list"][first] and p0["games"] == v["games"][first]
    assert got["narrow"] == 1


def test_booth_games_and_state_clean(run: Callable[[str], Any], nfl_fixture_raw: dict) -> None:
    got = run(
        """
        const d = S.defaultNflState(m);
        const key = m.boothCatalog[0].key;
        const e = m.boothIndex.get(key);
        const games = S.boothGames(m, [key]);
        const ok = games.every(i => m.groupOfNetwork.get(m.cols.network[i]) === e.group
          && m.cols.crew[i].some(c => c.person === e.person && c.role === 'pbp'));
        const table = S.tableGames(m, { ...d, booths: [key], people: [m.people[0].id] });
        const empty = S.tableGames(m, { ...d, booths: [key], seasons: [2030, 2030] });
        const dirty = S.canonicalNflState({ ...d, network: 'nope', cseason: 1999,
          booths: [key, 'zz:zz', 5], hiddenSegments: ['agotw', 'bogus'],
          hiddenCategories: ['snf', 'bogus'], metric: 'volatility' }, m);
        return { key, games, ok, table, empty, dirty,
          count: S.activeFilterCount(m, { ...d, booths: [key] }),
          has: S.pointHasBooth(m, games.slice(0, 1), [key]), no: S.pointHasBooth(m, games, []),
          garbage: S.canonicalNflState(null, m).view };
        """
    )
    assert got["games"] and got["ok"] is True
    assert set(got["table"]) == set(got["games"])
    assert got["empty"] == []
    dirty = got["dirty"]
    assert dirty["network"] == "fox"
    assert dirty["cseason"] == nfl_fixture_raw["freshness"]["crews_default_season"]
    assert dirty["booths"] == [got["key"]]
    assert dirty["hiddenSegments"] == ["agotw"] and dirty["hiddenCategories"] == ["snf"]
    assert dirty["metric"] == "margin"
    assert got["count"] == 1 and got["has"] is True and got["no"] is False
    assert got["garbage"] == "special"


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


def test_table_games_intersects_people_and_booths(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const d = S.defaultNflState(m);
        const key = m.boothCatalog[0].key;
        const bg = S.boothGames(m, [key]);
        const pg = (id) => m.personGames.get(m.personIndex.get(id)) || [];
        // a person who called one of the booth's games, and one who called none of them
        const inBooth = m.people.find((p) => pg(p.id).some((g) => bg.includes(g)));
        const outBooth = m.people.find((p) => pg(p.id).length && !pg(p.id).some((g) => bg.includes(g)));
        const both = S.tableGames(m, { ...d, people: [inBooth.id], booths: [key] });
        const expect = bg.filter((g) => pg(inBooth.id).includes(g));
        const none = outBooth ? S.tableGames(m, { ...d, people: [outBooth.id], booths: [key] }) : [];
        const season = m.cols.season[bg[0]];
        const narrowed = S.tableGames(m, { ...d, people: [inBooth.id], booths: [key], seasons: [season, season] });
        const dates = both.map((i) => m.cols.date[i]);
        return { both: both.slice().sort((a, b) => a - b), expect, none, hasOut: !!outBooth,
          narrowedOk: narrowed.every((i) => m.cols.season[i] === season && expect.includes(i)),
          sorted: dates.every((x, k) => k === 0 || dates[k - 1] >= x) };
        """
    )
    assert got["expect"] and got["both"] == got["expect"]
    assert got["sorted"] is True and got["narrowedOk"] is True
    if got["hasOut"]:
        assert got["none"] == []


def test_special_recount_matches_special_rows(run: Callable[[str], Any]) -> None:
    bad = run(
        """
        const d = S.defaultNflState(m);
        const passes = new Uint8Array(m.n).fill(1);
        const keys = ['solo_thursday', 'solo_sunday', 'solo_monday', 'solo_holiday',
          'solo_other', 'agotw', 'cbs_national', 'international_other'];
        const got = S.specialMatchedCounts(m, d, passes);
        const bad = [];
        m.franchises.forEach((f, fi) => {
          const rec = got.get(fi) || {};
          for (const k of keys) {
            const want = m.special.filter((r) => r.franchise === fi
              && r.season >= d.seasons[0] && r.season <= d.seasons[1]).reduce((n, r) => n + r[k], 0);
            if ((rec[k] || 0) !== want) bad.push([f.id, k, rec[k] || 0, want]);
          }
        });
        return bad;
        """
    )
    assert bad == []


# ------------------------------------------------------------- url-state.js


def test_encode_default_and_order(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const d = S.defaultNflState(m);
        const key = m.boothCatalog[0].key;
        return { def: U.encodeNflState(d, m),
          full: U.encodeNflState({ ...d, view: 'crews', seasons: [2024, 2025],
            teams: [m.franchises[0].id], network: 'cbs', cseason: 2024, booths: [key],
            adjusted: true, metric: 'viewers' }, m),
          vw: U.encodeNflState({ ...d, view: 'viewership', viewY: 'resid' }, m),
          id: m.franchises[0].id, key };
        """
    )
    assert got["def"] == "?sport=nfl"
    key = got["key"].replace(":", "%3A")
    assert got["full"] == (
        f"?sport=nfl&view=crews&seasons=2024-2025&team={got['id']}&net=cbs&cseason=2024"
        f"&booths={key}&adj=1&m=viewers"
    )
    assert got["vw"] == "?sport=nfl&view=viewership&ay=resid"


def test_round_trip(run: Callable[[str], Any]) -> None:
    ok = run(
        """
        const d = S.defaultNflState(m);
        const s = S.canonicalNflState({ ...d, view: 'scatter', seasons: [2025, 2024],
          teams: [m.franchises[1].id, m.franchises[0].id], people: [m.people[2].id],
          cats: ['flexed', 'tnf'], network: 'cbs', cseason: 2024, booths: [m.boothCatalog[0].key],
          adjusted: true, metric: 'excitement', viewY: 'resid', scatterX: 'margin',
          scatterY: 'excitement', dots: 'hide' }, m);
        const back = U.decodeNflState(U.encodeNflState(s, m), m);
        return JSON.stringify(back) === JSON.stringify(S.canonicalNflState(s, m));
        """
    )
    assert ok is True


def test_perseason_csort_round_trip(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const d = S.defaultNflState(m);
        const e = (x) => U.encodeNflState({ ...d, ...x }, m);
        const wide = [m.seasons[0], m.seasons[1]];
        const rt = (x) => U.decodeNflState(e(x), m);
        return { off: e({ perseason: false }),
          games: e({ csort: { key: 'games', dir: 'desc' } }),
          seasonDesc: e({ csort: { key: 'season', dir: 'desc' } }),
          marginAsc: e({ csort: { key: 'margin', dir: 'asc' } }),
          offGames: e({ perseason: false, csort: { key: 'games', dir: 'desc' } }),
          oneSeason: e({ seasons: [2025, 2025], csort: { key: 'games', dir: 'desc' } }),
          back: rt({ csort: { key: 'margin', dir: 'asc' } }).csort,
          backOff: rt({ perseason: false }).perseason,
          wide };
        """
    )
    assert got["off"] == "?sport=nfl&perseason=0"
    assert got["games"] == "?sport=nfl&csort=games"
    assert got["seasonDesc"] == "?sport=nfl"
    assert got["marginAsc"] == "?sport=nfl&csort=margin.asc"
    assert got["offGames"] == "?sport=nfl&perseason=0"
    assert got["oneSeason"] == "?sport=nfl&seasons=2025-2025&csort=games"
    assert got["back"] == {"key": "margin", "dir": "asc"}
    assert got["backOff"] is False


def test_csort_default_follows_the_stored_preference(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const [lo, hi] = m.seasons;
        const dec = (q) => U.decodeNflState(q, m).csort;
        return { seasonWide: dec('?csort=season.asc'),
          seasonOne: dec(`?seasons=${hi}-${hi}&csort=season.asc`),
          seasonOff: dec('?perseason=0&csort=season.asc'),
          gamesOff: dec('?perseason=0&csort=games'), gamesOn: dec('?csort=games'),
          bogus: [dec('?csort=crew'), dec('?csort=games.up'), dec('?csort=%'), dec('?csort=')],
          perBad: U.decodeNflState('?perseason=yes', m).perseason };
        """
    )
    assert got["seasonWide"] == {"key": "season", "dir": "asc"}
    assert got["seasonOne"] is None and got["seasonOff"] is None
    assert got["gamesOff"] is None
    assert got["gamesOn"] == {"key": "games", "dir": "desc"}
    assert got["bogus"] == [None] * 4
    assert got["perBad"] is True


def test_legacy_cseason_maps_to_seasons_in_any_order(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const [lo, hi] = m.seasons;
        const y = hi;
        const dec = (q) => U.decodeNflState(q, m).seasons;
        return { lo, hi, y,
          c: dec(`?sport=nfl&cseason=${y}`), f: dec(`?sport=nfl&fseason=${y}`),
          a: dec(`?sport=nfl&cseason=${y}&seasons=${lo}-${hi}`),
          b: dec(`?sport=nfl&seasons=${lo}-${hi}&cseason=${y}`),
          out: dec('?sport=nfl&cseason=1850') };
        """
    )
    one = [got["y"], got["y"]]
    full = [got["lo"], got["hi"]]
    assert got["c"] == one and got["f"] == one
    assert got["a"] == full and got["b"] == full
    assert got["out"] == full


def test_decode_aliases(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const q = ['?view=fox', '?view=agotw', '?view=crews&fseason=2024',
          '?cseason=2024&fseason=2025',
          '?fseason=2024&cseason=2025', '?m=volatility', '?m=viewers&ay=resid'];
        return q.map(x => U.decodeNflState(x, m));
        """
    )
    assert got[0]["view"] == "crews" and got[1]["view"] == "viewership"
    assert got[2]["cseason"] == 2024
    assert got[3]["cseason"] == 2024 and got[4]["cseason"] == 2024
    assert got[5]["metric"] == "margin"
    assert got[6]["metric"] == "viewers" and got[6]["viewY"] == "resid"


def test_decode_never_throws(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const d = S.defaultNflState(m);
        const q = ['%', '?sport=nfl&seasons=abc', '?team=nope,%E0%A4%A', '?cat=bogus,tnf',
          '?cseason=1850', '?view=bogus', '?seasons=2030-2001', '?sport=cfb&team=%', '&&==', '',
          '?net=%E0%A4%A', '?net=nope', '?booths=zz%3Azz,%', '?fseason=1850',
          '?csort=%E0%A4%A', '?csort=a.b.c', '?perseason=%', '?csort=games&csort=%'];
        const out = q.map(x => U.decodeNflState(x, m));
        return { out, d, ids: m.franchises.map(f => f.id) };
        """
    )
    out, d = got["out"], got["d"]
    assert out[0] == d and out[1]["seasons"] == d["seasons"]
    assert out[2]["teams"] == [] and out[3]["cats"] == ["tnf"]
    assert out[4]["cseason"] == d["cseason"] and out[5]["view"] == "special"
    assert out[6]["seasons"] == d["seasons"] and out[7] == d
    for k in (10, 11, 12, 13, 14, 15):
        assert out[k] == d
    assert out[16]["perseason"] is True and out[16]["csort"] is None
    assert out[17]["csort"] == {"key": "games", "dir": "desc"}
