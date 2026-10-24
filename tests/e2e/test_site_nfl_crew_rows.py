"""Phase 15-06: the NFL Crews row model (site/sports/nfl/crew-rows.js).

In-page tests on the synthetic NFL Crews overlay (tests/e2e/nfl_crews_fixture.py); expected
values are computed in Python from the overlay dict and the Python pooling oracle
(`booth_review.nfl.adjust.mean_se`). No vault rows.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import nfl_crews_fixture as fx
import pytest
from nfl_crews_fixture import (
    CASE_CROSS_ERA,
    CASE_FILL_IN,
    CASE_LOW_POOL,
    CASE_MIXED_SEAT,
    CASE_MOVED,
    CASE_NULL_ANALYST,
    CASE_NULL_RESID,
    CASE_TWO_ANALYSTS,
    CASE_WINDOW,
    POOL_ORACLE,
    POOL_ORACLE_EXCITEMENT,
    POOL_TOLERANCE,
    build_nfl_crews_raw,
)
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

PRELUDE = """
const D = await import('./sports/nfl/data.js');
const S = await import('./sports/nfl/state.js');
const R = await import('./sports/nfl/crew-rows.js');
const MODE = await import('./sports/nfl/mode.js');
const raw = await (await fetch('nfl-data.json')).json();
const m = D.prepareNfl(raw);
const base = { ...S.defaultNflState(m), seasons: [m.seasons[0], m.seasons[1]] };
const slim = (rows) => rows.map((r) => ({
  rowKey: r.rowKey, boothKey: r.boothKey, groupId: r.groupId, season: r.season,
  pbp: r.pbp && r.pbp.id, analyst: r.analyst && r.analyst.id, names: r.names,
  gamesCount: r.gamesCount, games: r.games, gamesList: r.gamesList,
  fillIn: [...r.fillIn], windowGames: [...r.windowGames],
  margin: r.margin, exc: r.exc, viewers: r.viewers, adjusted: r.adjusted,
  rankRun: r.rankRun, rankKey: r.rankKey, published: r.published,
}));
"""


@pytest.fixture
def run(
    nfl_guarded_page: Page,
    open_flagon_cfb: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> Callable[[str], Any]:
    serve_nfl_crews(nfl_guarded_page)
    open_flagon_cfb(nfl_guarded_page)

    def _run(body: str) -> Any:
        return nfl_guarded_page.evaluate("async () => {" + PRELUDE + body + "}")

    return _run


@pytest.fixture
def overlay(nfl_fixture_raw: dict[str, Any]) -> dict[str, Any]:
    return build_nfl_crews_raw(nfl_fixture_raw)


def _rows(run: Callable[[str], Any], state: str = "{}", sort: str | None = None) -> dict[str, Any]:
    out = run(
        f"""
        const st = {{ ...base, ...{state} }};
        const b = R.buildNflCrewRows(m, st);
        return {{ perSeason: b.perSeason, mode: b.mode, reason: b.reason,
                  totalRows: b.totalRows, rows: slim(b.rows) }};
        """
    )
    assert isinstance(out, dict)
    return out


def _find(rows: list[dict[str, Any]], pbp: str, **kw: Any) -> list[dict[str, Any]]:
    return [r for r in rows if r["pbp"] == pbp and all(r.get(k) == v for k, v in kw.items())]


def _pool_parts(overlay: dict[str, Any], key: str) -> list[dict[str, Any]]:
    gid, pbp_slug, an_slug = key.split(":")
    people = {p["id"]: i for i, p in enumerate(overlay["lookups"]["people"])}
    gi = next(i for i, g in enumerate(overlay["lookups"]["network_groups"]) if g["id"] == gid)
    b = overlay["booths"]
    return [
        {
            "n": b["adj_n_margin"][i],
            "m": b["adj_margin_resid"][i],
            "se": b["adj_margin_se"][i],
            "nx": b["adj_n_excitement"][i],
            "mx": b["adj_excitement_resid"][i],
            "sex": b["adj_excitement_se"][i],
        }
        for i in range(len(b["season"]))
        if b["network_group"][i] == gi
        and b["pbp_person"][i] == people[pbp_slug]
        and b["analyst_person"][i] == people[an_slug]
    ]


def test_pool_residual_matches_mean_se(run: Callable[[str], Any], overlay: dict[str, Any]) -> None:
    assert POOL_ORACLE
    for key, (n, mean, se) in POOL_ORACLE.items():
        parts = _pool_parts(overlay, key)
        got = run(f"return R.poolResidual({json.dumps(parts)});")
        assert got["n"] == n
        assert mean is not None
        assert abs(got["mean"] - mean) <= POOL_TOLERANCE, (
            f"pool mean off by more than {POOL_TOLERANCE}"
        )
        assert se is not None
        assert abs(got["se"] - se) <= POOL_TOLERANCE, f"pool se off by more than {POOL_TOLERANCE}"
    for key, (n, mean, se) in POOL_ORACLE_EXCITEMENT.items():
        parts = [{"n": p["nx"], "m": p["mx"], "se": p["sex"]} for p in _pool_parts(overlay, key)]
        got = run(f"return R.poolResidual({json.dumps(parts)});")
        assert got["n"] == n
        assert mean is not None and se is not None
        assert abs(got["mean"] - mean) <= POOL_TOLERANCE
        assert abs(got["se"] - se) <= POOL_TOLERANCE


def test_pool_residual_null_and_n1_rules(run: Callable[[str], Any]) -> None:
    got = run(
        """
        return {
          allNull: R.poolResidual([{ n: 3, m: null, se: null }, { n: 2, m: null, se: null }]),
          empty: R.poolResidual([]),
          dropped: R.poolResidual([{ n: 4, m: 1, se: 0.5 }, { n: 9, m: null, se: null }]),
          one: R.poolResidual([{ n: 1, m: 2.5, se: null }]),
          oneInPool: R.poolResidual([{ n: 1, m: 2, se: null }, { n: 3, m: 4, se: 1 }]),
          alone: R.poolResidual([{ n: 4, m: 1, se: 0.5 }]),
        };
        """
    )
    assert got["allNull"] == {"n": 0, "mean": None, "se": None}
    assert got["empty"] == {"n": 0, "mean": None, "se": None}
    assert got["dropped"]["n"] == 4  # the null season leaves with its n
    assert got["one"] == {"n": 1, "mean": 2.5, "se": None}  # N = 1 gives no SE
    # n = 1 adds 0 to the first SS term: SS = 2*3*1 + 1*(2-3.5)^2 + 3*(4-3.5)^2 = 9
    pooled = got["oneInPool"]
    assert pooled["n"] == 4
    assert pooled["mean"] == pytest.approx(3.5)
    assert pooled["se"] == pytest.approx((9 / 3 / 4) ** 0.5)
    assert got["alone"]["se"] == pytest.approx(0.5)  # a single part pools to itself


def test_pool_raw_weights_by_n(run: Callable[[str], Any]) -> None:
    got = run(
        """
        return {
          w: R.poolRaw([{ n: 1, mean: 10 }, { n: 3, mean: 2 }]),
          nul: R.poolRaw([{ n: 2, mean: 4 }, { n: 0, mean: null }]),
          none: R.poolRaw([{ n: 0, mean: null }]),
        };
        """
    )
    assert got["w"] == {"n": 4, "mean": 4.0}
    assert got["nul"] == {"n": 2, "mean": 4.0}
    assert got["none"] == {"n": 0, "mean": None}


def _pairs(overlay: dict[str, Any]) -> set[tuple[int, int, int | None]]:
    b = overlay["booths"]
    return {
        (b["network_group"][i], b["pbp_person"][i], b["analyst_person"][i])
        for i in range(len(b["season"]))
    }


def test_row_counts_pooled_and_per_season(
    run: Callable[[str], Any], overlay: dict[str, Any]
) -> None:
    pooled = _rows(run, "{ perseason: false }")
    season = _rows(run, "{ perseason: true }")
    b = overlay["booths"]
    zero_game = sum(1 for g in b["games"] if g == 0)  # lineup-only rows stay (planner choice)
    assert pooled["perSeason"] is False
    assert (
        pooled["totalRows"] == len(pooled["rows"]) == fx.EXPECT_POOLED_ROWS == len(_pairs(overlay))
    )
    assert season["perSeason"] is True
    assert len(season["rows"]) == len(b["season"]) == fx.EXPECT_SEASON_ROWS + zero_game
    assert len(pooled["rows"]) > 25
    assert len({r["rowKey"] for r in season["rows"]}) == len(season["rows"])


def test_moved_pair_and_two_analysts(run: Callable[[str], Any]) -> None:
    pooled = _rows(run, "{ perseason: false }")["rows"]
    moved = _find(pooled, CASE_MOVED["pbp"])  # type: ignore[arg-type]
    assert len(moved) == CASE_MOVED["pooled_rows"]
    assert len({r["groupId"] for r in moved}) == 2
    two = _find(pooled, CASE_TWO_ANALYSTS["pbp"])  # type: ignore[arg-type]
    assert len(two) == CASE_TWO_ANALYSTS["pooled_rows"]
    assert {r["boothKey"] for r in two} == {CASE_TWO_ANALYSTS["catalog_key"]}
    assert {r["analyst"] for r in two} == set(CASE_TWO_ANALYSTS["analysts"])  # type: ignore[arg-type]
    season = _rows(run, "{ perseason: true }")["rows"]
    assert len(_find(season, CASE_TWO_ANALYSTS["pbp"])) == CASE_TWO_ANALYSTS["season_rows"]  # type: ignore[arg-type]


def test_pooled_adjusted_matches_oracle(run: Callable[[str], Any], overlay: dict[str, Any]) -> None:
    pooled = _rows(run, "{ perseason: false, adjusted: true }")
    assert pooled["mode"] == "adjusted"
    for key, (n, mean, se) in POOL_ORACLE.items():
        gid, pbp, an = key.split(":")
        (row,) = [
            r
            for r in pooled["rows"]
            if r["groupId"] == gid and r["pbp"] == pbp and r["analyst"] == an
        ]
        cell = row["adjusted"]["margin"]
        assert cell["n"] == n
        assert mean is not None and se is not None
        assert abs(cell["resid"] - mean) <= POOL_TOLERANCE
        assert abs(cell["se"] - se) <= POOL_TOLERANCE
    for key, (n, mean, _se) in POOL_ORACLE_EXCITEMENT.items():
        gid, pbp, an = key.split(":")
        (row,) = [
            r
            for r in pooled["rows"]
            if r["groupId"] == gid and r["pbp"] == pbp and r["analyst"] == an
        ]
        assert row["adjusted"]["exc"]["n"] == n
        assert mean is not None
        assert abs(row["adjusted"]["exc"]["resid"] - mean) <= POOL_TOLERANCE
    # The null-residual season leaves the pool with its n; Raw keeps it.
    (nullr,) = _find(pooled["rows"], CASE_NULL_RESID["pbp"])  # type: ignore[arg-type]
    assert nullr["adjusted"]["margin"] == {"resid": None, "se": None, "n": 0, "flagged": False}
    assert nullr["margin"]["n"] == CASE_NULL_RESID["n"]
    # n = 1: a mean, no standard error.
    (one,) = _find(pooled["rows"], "synth-pbp-one")
    assert one["adjusted"]["margin"]["n"] == 1
    assert one["adjusted"]["margin"]["resid"] is not None
    assert one["adjusted"]["margin"]["se"] is None


def test_low_n_pools_clear(run: Callable[[str], Any]) -> None:
    season = _find(_rows(run, "{ perseason: true }")["rows"], CASE_LOW_POOL["pbp"])  # type: ignore[arg-type]
    assert sorted(r["margin"]["n"] for r in season) == sorted(CASE_LOW_POOL["ns"].values())  # type: ignore[attr-defined]
    assert all(r["margin"]["flagged"] and r["adjusted"]["margin"]["flagged"] for r in season)
    (pooled,) = _find(_rows(run, "{ perseason: false }")["rows"], CASE_LOW_POOL["pbp"])  # type: ignore[arg-type]
    assert pooled["margin"]["n"] == CASE_LOW_POOL["pooled_n"]
    assert pooled["margin"]["flagged"] is False
    assert pooled["adjusted"]["margin"]["flagged"] is False


def test_cross_era_blanks_pooled_viewers(run: Callable[[str], Any]) -> None:
    (pooled,) = _find(_rows(run, "{ perseason: false }")["rows"], CASE_CROSS_ERA["pbp"])  # type: ignore[arg-type]
    assert pooled["viewers"]["blank"] == "era"
    assert pooled["viewers"]["mean"] is None
    season = _find(_rows(run, "{ perseason: true }")["rows"], CASE_CROSS_ERA["pbp"])  # type: ignore[arg-type]
    assert len(season) == 2
    assert all(r["viewers"]["blank"] is None and r["viewers"]["mean"] is not None for r in season)


def test_raw_recompute_matches_shipped_raw(
    run: Callable[[str], Any], overlay: dict[str, Any]
) -> None:
    got = run(
        """
        const out = [];
        for (const r of m.booths) {
          const c = R.rawFromGames(m, r.gameList || []);
          out.push({ n: [r.raw_n_margin, c.margin.n], mean: [r.raw_mean_abs_margin, c.margin.mean],
                     exc: [r.raw_mean_excitement, c.exc.mean],
                     v: [r.raw_mean_viewers, c.viewers.mean],
                     games: r.games });
        }
        return out;
        """
    )
    checked = 0
    for g in got:
        if g["games"] == 0:
            continue
        checked += 1
        assert g["n"][0] == g["n"][1]
        for k in ("mean", "exc", "v"):
            shipped, computed = g[k]
            if shipped is None:
                assert computed is None
                continue
            assert computed is not None
            assert abs(shipped - computed) <= 0.001 * max(1.0, abs(shipped))
    assert checked > 25


def test_team_pick_forces_raw_with_reason(
    run: Callable[[str], Any], overlay: dict[str, Any]
) -> None:
    fid = overlay["lookups"]["franchises"][0]["id"]
    out = run(
        f"""
        const st = {{ ...base, perseason: false, adjusted: true, teams: ['{fid}'] }};
        const b = R.buildNflCrewRows(m, st);
        const idx = m.franchiseIndex.get('{fid}');
        return {{ mode: b.mode, reason: b.reason, want: MODE.REASONS.crewsTeam,
                  n: b.rows.length,
                  allHaveTeam: b.rows.every((r) => r.games.length > 0 && r.games.every(
                    (g) => m.cols.home[g] === idx || m.cols.away[g] === idx)),
                  noAdj: b.rows.every((r) => r.adjusted.margin.resid === null) }};
        """
    )
    assert out["mode"] == "raw"
    assert out["reason"] == out["want"]
    assert out["allHaveTeam"] and out["noAdj"]
    full = _rows(run, "{ perseason: false }")
    assert 0 < out["n"] < len(full["rows"])  # 0-game rows dropped under the subset


def test_pbp_voice_pick_is_a_row_filter(run: Callable[[str], Any]) -> None:
    out = _rows(run, "{ perseason: false, adjusted: true, people: ['synth-many-pbp-00'] }")
    assert out["mode"] == "adjusted"
    assert out["reason"] is None
    assert [r["pbp"] for r in out["rows"]] == ["synth-many-pbp-00"]
    full = _rows(run, "{ perseason: false }")["rows"]
    (whole,) = _find(full, "synth-many-pbp-00")
    assert out["rows"][0]["gamesCount"] == whole["gamesCount"]  # kept whole, not recounted
    assert out["rows"][0]["adjusted"]["margin"]["resid"] is not None


def test_mixed_seat_pick_is_a_subset(run: Callable[[str], Any]) -> None:
    seat = CASE_MIXED_SEAT["person"]
    out = run(
        f"""
        const st = {{ ...base, perseason: false, adjusted: true, people: ['{seat}'] }};
        const b = R.buildNflCrewRows(m, st);
        return {{ mode: b.mode, reason: b.reason, want: MODE.REASONS.crewsSubset,
                  rows: slim(b.rows) }};
        """
    )
    assert out["mode"] == "raw"
    assert out["reason"] == out["want"]
    assert {r["pbp"] for r in out["rows"]} == {seat, CASE_MIXED_SEAT["analyst_row"]["pbp"]}  # type: ignore[index]
    assert all(r["gamesCount"] > 0 for r in out["rows"])


def test_booths_pick_keeps_whole_rows(run: Callable[[str], Any]) -> None:
    key = CASE_TWO_ANALYSTS["catalog_key"]
    out = _rows(run, f"{{ perseason: false, adjusted: true, booths: ['{key}'] }}")
    assert out["mode"] == "adjusted"
    assert len(out["rows"]) == 2
    assert {r["boothKey"] for r in out["rows"]} == {key}
    full = {r["rowKey"]: r for r in _rows(run, "{ perseason: false }")["rows"]}
    for r in out["rows"]:
        assert r["gamesCount"] == full[r["rowKey"]]["gamesCount"]
        assert r["adjusted"]["margin"]["resid"] is not None


def test_game_lists_tags_and_null_analyst(run: Callable[[str], Any]) -> None:
    rows = _rows(run, "{ perseason: true }")["rows"]
    (fill,) = _find(rows, CASE_FILL_IN["pbp"])  # type: ignore[arg-type]
    assert len(fill["fillIn"]) == CASE_FILL_IN["fill_in_games"]
    assert set(fill["fillIn"]) <= set(fill["games"])
    (win,) = _find(rows, CASE_WINDOW["pbp"])  # type: ignore[arg-type]
    assert len(win["windowGames"]) == CASE_WINDOW["window_games"]
    (solo,) = _find(rows, CASE_NULL_ANALYST["pbp"])  # type: ignore[arg-type]
    assert solo["analyst"] is None
    assert solo["names"] == "Synth Pbp Solo"
    assert solo["fillIn"] == []
    for r in rows:
        assert sorted(r["gamesList"]) == sorted(r["games"])
    got = run(
        """
        const rows = R.buildNflCrewRows(m, base).rows;
        return rows.every((r) => r.gamesList.every((g, k, a) =>
          k === 0 || m.cols.date[a[k - 1]] >= m.cols.date[g]));
        """
    )
    assert got is True


def test_rank_runs_and_games_ranked_lead(
    run: Callable[[str], Any], overlay: dict[str, Any]
) -> None:
    b = overlay["booths"]
    people = overlay["lookups"]["people"]
    games_ranked = {
        (b["network_group"][i], b["pbp_person"][i])
        for i in range(len(b["season"]))
        if b["rank"][i] == 1 and b["rank_source"][i] == "games" and b["games"][i] > 0
    }
    assert games_ranked
    season = _rows(run, "{ perseason: true }")["rows"]
    groups = [g["id"] for g in overlay["lookups"]["network_groups"]]
    saw_lead = saw_games = False
    for i in range(len(b["season"])):
        if b["rank"][i] != 1 or b["games"][i] == 0:
            continue
        pbp = people[b["pbp_person"][i]]["id"]
        (row,) = [
            r
            for r in season
            if r["pbp"] == pbp
            and r["season"] == b["season"][i]
            and r["groupId"] == groups[b["network_group"][i]]
            and r["analyst"] == people[b["analyst_person"][i]]["id"]
        ]
        if b["rank_source"][i] == "games":
            assert row["rankRun"] == "No. 1"
            saw_games = True
        else:
            assert row["rankRun"] == "Lead"
            saw_lead = True
    assert saw_lead and saw_games
    assert all("," not in r["rankRun"] for r in season)
    pooled = _rows(run, "{ perseason: false }")["rows"]
    two = _find(pooled, CASE_TWO_ANALYSTS["pbp"])  # type: ignore[arg-type]
    assert all(r["rankRun"].startswith("No. 2 ") for r in two)


def test_sort_buckets_both_directions(run: Callable[[str], Any]) -> None:
    out = run(
        """
        const rows = R.buildNflCrewRows(m, { ...base, perseason: false }).rows;
        const bucket = (r) => (r.viewers.mean == null ? 2 : r.viewers.flagged ? 1 : 0);
        const pick = (dir) => R.sortNflCrewRows(rows, { key: 'viewers', dir }, false).map(bucket);
        const monotone = (a) => a.every((v, i) => i === 0 || a[i - 1] <= v);
        const g = R.sortNflCrewRows(rows, null, false).map((r) => r.gamesCount);
        const sRows = R.buildNflCrewRows(m, { ...base, perseason: true }).rows;
        const s = R.sortNflCrewRows(sRows, null, true).map((r) => [r.season, r.gamesCount]);
        const poolSeason = R.sortNflCrewRows(rows, { key: 'season', dir: 'asc' }, false)
          .map((r) => r.gamesCount);
        return { asc: monotone(pick('asc')), desc: monotone(pick('desc')),
                 buckets: [...new Set(pick('asc'))], g, s, poolSeason };
        """
    )
    assert out["asc"] and out["desc"]
    assert out["buckets"] == [0, 1, 2]
    assert out["g"] == sorted(out["g"], reverse=True)
    seasons = [s for s, _ in out["s"]]
    assert seasons == sorted(seasons, reverse=True)
    for season in set(seasons):
        gs = [g for s, g in out["s"] if s == season]
        assert gs == sorted(gs, reverse=True)
    assert out["poolSeason"] == sorted(out["poolSeason"], reverse=True)
