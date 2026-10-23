"""Row model of the Crews table: Crew, PBP and Analyst rows, metrics, sort (plan 14-03).

Model-level tests: they run `buildCrewRows` / `sortCrewRows` in the page on the synthetic
crews dataset (tests/e2e/crews_fixture.py). Expected values come from the CASE_* constants.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import pytest
from crews_fixture import (
    CASE_BREAK,
    CASE_ERA,
    CASE_FULL_N,
    CASE_LOW_N,
    CASE_MIXED_UNKNOWN,
    CASE_NO_CREW,
    CASE_NO_PBP,
    CASE_NON_BIG_FOUR,
    CASE_SIDELINE,
    CASE_TRIO,
    CASE_TWO_FAMILIES,
    build_crews_raw,
)
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_ROWS_JS = """
async ({partial, opts, sort}) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const G = await import('./modules/crew-groups.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  // '@team:N' and '@game:N' stand for the Nth team slug / game slug of the data.
  const slot = (v) => {
    if (typeof v !== 'string') return v;
    const m = /^@(team|game):(\\d+)$/.exec(v);
    if (!m) return v;
    return m[1] === 'team'
      ? data.teamSlugs[Number(m[2])]
      : Array.from(data.gameIndexBySlug.keys())[Number(m[2])];
  };
  const resolved = Object.fromEntries(
    Object.entries(partial).map(([k, v]) => [k, Array.isArray(v) ? v.map(slot) : slot(v)]),
  );
  const state = Object.assign(S.defaultState(data), resolved);
  const view = S.computeView(data, state);
  const out = G.buildCrewRows(data, view, opts);
  const rows = (sort === undefined ? out.rows : G.sortCrewRows(out.rows, sort)).map((r) => ({
    ...r,
    fillInGames: Array.from(r.fillInGames),
  }));
  const passes = [];
  for (let i = 0; i < data.n; i += 1) if (view.passesFilters[i]) passes.push(i);
  return {
    rows,
    leftOut: out.leftOut,
    totalRows: out.totalRows,
    passes,
    keys: G.crewIndex(data).keys,
    lowNMin: G.CREWS_LOW_N_MIN,
  };
}
"""


@pytest.fixture
def rows_page(
    guarded_page: Page,
    serve_crews: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> Callable[..., dict[str, Any]]:
    serve_crews(guarded_page)
    open_app(guarded_page, "?view=crews")

    def _rows(
        partial: dict[str, Any] | None = None,
        *,
        mode: str = "crew",
        per_season: bool = False,
        sort: Any = ...,
    ) -> dict[str, Any]:
        arg: dict[str, Any] = {
            "partial": partial or {},
            "opts": {"mode": mode, "perSeason": per_season},
        }
        if sort is not ...:
            arg["sort"] = sort
        return guarded_page.evaluate(_ROWS_JS, arg)  # type: ignore[no-any-return]

    return _rows


def _find(rows: list[dict[str, Any]], *slugs: str, **match: Any) -> list[dict[str, Any]]:
    out = [r for r in rows if all(s in [p["slug"] for p in r["people"]] for s in slugs)]
    return [r for r in out if all(r.get(k) == v for k, v in match.items())]


def _one(rows: list[dict[str, Any]], *slugs: str, **match: Any) -> dict[str, Any]:
    found = _find(rows, *slugs, **match)
    assert len(found) == 1, f"{slugs}: {len(found)} rows"
    return found[0]


# -- Crew mode -------------------------------------------------------------------------------


def test_row_count_equals_distinct_keys(rows_page: Callable[..., dict[str, Any]]) -> None:
    out = rows_page()
    distinct = {out["keys"][i] for i in out["passes"] if out["keys"][i] is not None}
    assert out["totalRows"] == len(distinct) == len(out["rows"])
    assert out["totalRows"] > 25
    assert out["lowNMin"] == 8
    # games called: the no-crew telecast is left out and counted
    assert out["leftOut"] == CASE_NO_CREW["games"]


def test_two_families_and_non_big_four(rows_page: Callable[..., dict[str, Any]]) -> None:
    rows = rows_page()["rows"]
    fam = _find(rows, CASE_TWO_FAMILIES["pbp"], CASE_TWO_FAMILIES["analyst"])
    assert sorted(r["family"] for r in fam) == sorted(CASE_TWO_FAMILIES["families"])
    assert all(r["gamesCount"] == CASE_TWO_FAMILIES["games"] // 2 for r in fam)
    reg = _find(rows, CASE_NON_BIG_FOUR["pbp"], CASE_NON_BIG_FOUR["analyst"])
    assert len(reg) == CASE_NON_BIG_FOUR["rows"]
    assert all(r["rankRun"] == "" and r["family"] is None for r in reg)
    assert all(r["gamesCount"] == CASE_NON_BIG_FOUR["games_per_row"] for r in reg)


def test_trio_names_pbp_first(rows_page: Callable[..., dict[str, Any]]) -> None:
    rows = rows_page()["rows"]
    row = _one(rows, CASE_TRIO["pbp"])
    slugs = [p["slug"] for p in row["people"]]
    assert slugs == [CASE_TRIO["pbp"], *CASE_TRIO["analysts"]]
    assert row["gamesCount"] == CASE_TRIO["games"]
    assert row["names"] == "Trio Pbp, Trio A1 and Trio A2"
    assert all(p["unknownTag"] is None for p in row["people"])


def test_no_pbp_all_unknown(rows_page: Callable[..., dict[str, Any]]) -> None:
    row = _one(rows_page()["rows"], *CASE_NO_PBP["people"])
    assert row["gamesCount"] == CASE_NO_PBP["games"]
    assert all(p["unknownTag"] == "all" for p in row["people"])
    assert row["rankRun"] == ""


def test_mixed_unknown_and_sideline(rows_page: Callable[..., dict[str, Any]]) -> None:
    rows = rows_page()["rows"]
    row = _one(rows, CASE_MIXED_UNKNOWN["x"], CASE_MIXED_UNKNOWN["y"])
    tags = {p["slug"]: p["unknownTag"] for p in row["people"]}
    assert tags[CASE_MIXED_UNKNOWN["y"]] == "all"
    assert tags[CASE_MIXED_UNKNOWN["x"]] == {"k": 1, "n": CASE_MIXED_UNKNOWN["games"]}
    # A2(a): the sideline person is not shown and does not change the row
    side = _one(rows, CASE_SIDELINE["pbp"])
    assert [p["slug"] for p in side["people"]] == [CASE_SIDELINE["pbp"], CASE_SIDELINE["analyst"]]
    assert side["gamesCount"] == CASE_SIDELINE["games"]
    assert not _find(rows, CASE_SIDELINE["sideline"])


def test_low_n_and_full_n(rows_page: Callable[..., dict[str, Any]]) -> None:
    rows = rows_page()["rows"]
    low = _one(rows, CASE_LOW_N["pbp"])
    assert low["viewers"]["n"] == CASE_LOW_N["rated"]
    assert low["viewers"]["flagged"] is True
    assert low["gamesCount"] == CASE_LOW_N["rated"] + CASE_LOW_N["unrated"]
    full = _one(rows, CASE_FULL_N["pbp"])
    assert full["viewers"]["n"] == CASE_FULL_N["rated"]
    assert full["viewers"]["flagged"] is False
    assert full["exc"]["n"] == CASE_FULL_N["excitement_values"]
    assert full["exc"]["flagged"] is False


def test_break_and_era_blanks(rows_page: Callable[..., dict[str, Any]]) -> None:
    pooled = rows_page()["rows"]
    brk = _one(pooled, CASE_BREAK["pbp"])
    assert brk["exc"]["blank"] == "break" and brk["exc"]["mean"] is None
    era = _one(pooled, CASE_ERA["pbp"])
    assert era["viewers"]["blank"] == "era" and era["viewers"]["mean"] is None
    per = rows_page(per_season=True)["rows"]
    brk_rows = _find(per, CASE_BREAK["pbp"])
    assert sorted(r["season"] for r in brk_rows) == CASE_BREAK["seasons"]
    assert all(r["exc"]["blank"] is None and r["exc"]["mean"] is not None for r in brk_rows)
    era_rows = _find(per, CASE_ERA["pbp"])
    assert len(era_rows) == 2
    assert all(r["viewers"]["blank"] is None for r in era_rows)


def test_seasons_narrowing_drops_empty_rows(rows_page: Callable[..., dict[str, Any]]) -> None:
    allrows = rows_page()["rows"]
    narrow = rows_page({"seasons": [2025, 2025]})
    assert 0 < narrow["totalRows"] < len(allrows)
    assert all(r["gamesCount"] > 0 for r in narrow["rows"])
    names = {r["crewKey"] for r in narrow["rows"]}
    assert _one(narrow["rows"], CASE_BREAK["pbp"])["gamesCount"] == 2
    assert _one(allrows, CASE_TRIO["pbp"])["crewKey"] not in names


def test_rank_runs_and_network(rows_page: Callable[..., dict[str, Any]]) -> None:
    pooled = rows_page()["rows"]
    fill = _one(pooled, "fill-pbp", "fill-ana")
    assert fill["rankRun"] == "Lead 2024" and fill["rankKey"] == 1
    assert 3 <= fill["gamesCount"] <= 4 and len(fill["fillInGames"]) <= 1
    per = rows_page(per_season=True)["rows"]
    assert _one(per, "fill-pbp", "fill-ana")["rankRun"] == "Lead"
    cite = _one(pooled, "cite-pbp")
    assert cite["rankRun"] == "No. 2 2024"
    two = _find(pooled, CASE_TWO_FAMILIES["pbp"])
    assert all(r["network"]["count"] == 1 for r in two)


# -- Person modes ----------------------------------------------------------------------------


def test_pbp_mode_partners(rows_page: Callable[..., dict[str, Any]]) -> None:
    out = rows_page(mode="pbp")
    row = _one(out["rows"], CASE_TRIO["pbp"])
    # one row per person across families
    assert len(_find(out["rows"], CASE_TWO_FAMILIES["pbp"])) == 1
    assert _one(out["rows"], CASE_TWO_FAMILIES["pbp"])["gamesCount"] == CASE_TWO_FAMILIES["games"]
    partners = {p["slug"]: p["games"] for p in row["partners"]}
    assert partners == {CASE_TRIO["analysts"][0]: 5, CASE_TRIO["analysts"][1]: 4}
    assert [p["games"] for p in row["partners"]] == sorted(partners.values(), reverse=True)
    assert row["partnersMore"] == 0 and len(row["partnersShown"]) == 2
    # leftOut: no resolved PBP (all-unknown telecast, mixed no-PBP pair, no crew)
    assert out["leftOut"] == CASE_NO_PBP["games"] + CASE_MIXED_UNKNOWN["games"] + 1


def test_pbp_partners_top_three_and_fill_in(rows_page: Callable[..., dict[str, Any]]) -> None:
    out = rows_page(mode="pbp")
    fill = _one(out["rows"], "fill-pbp")
    assert {p["slug"]: p["games"] for p in fill["partners"]} == {"fill-ana": 3, "fill-sub": 1}
    assert all(r["partnersMore"] == max(0, len(r["partners"]) - 3) for r in out["rows"])
    assert all(len(r["partnersShown"]) <= 3 for r in out["rows"])


def test_analyst_mode(rows_page: Callable[..., dict[str, Any]]) -> None:
    out = rows_page(mode="analyst")
    a1 = _one(out["rows"], CASE_TRIO["analysts"][0])
    assert a1["gamesCount"] == CASE_TRIO["games"]
    assert [p["slug"] for p in a1["partners"]] == [CASE_TRIO["pbp"]]
    # the trio game counts for both analysts
    assert _one(out["rows"], CASE_TRIO["analysts"][1])["gamesCount"] == CASE_TRIO["games"] - 1
    # the unknown-role sideline person never sits an analyst seat
    assert not _find(out["rows"], CASE_SIDELINE["sideline"])
    assert not _find(out["rows"], CASE_NO_PBP["people"][0])
    # mixed pair: X sat an analyst seat once, with no PBP: a row with no partner
    x = _one(out["rows"], CASE_MIXED_UNKNOWN["x"])
    assert x["gamesCount"] == 1 and x["partners"] == []
    # leftOut: passing games without a main-feed analyst
    assert out["leftOut"] == CASE_NO_PBP["games"] + 1 + 1


def test_person_rows_have_no_rank_run(rows_page: Callable[..., dict[str, Any]]) -> None:
    for mode in ("pbp", "analyst"):
        for per_season in (False, True):
            rows = rows_page(mode=mode, per_season=per_season)["rows"]
            assert rows and all(r["rankRun"] == "" and r["rankKey"] is None for r in rows)
    per = rows_page(mode="pbp", per_season=True)["rows"]
    assert len(_find(per, CASE_FULL_N["pbp"])) == 3


# -- Sort ------------------------------------------------------------------------------------


def _buckets(rows: list[dict[str, Any]], key: str) -> list[int]:
    return [2 if r[key]["mean"] is None else int(r[key]["flagged"]) for r in rows]


@pytest.mark.parametrize("key", ["exc", "viewers"])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_metric_sort_buckets(
    rows_page: Callable[..., dict[str, Any]], key: str, direction: str
) -> None:
    rows = rows_page(sort={"key": key, "dir": direction})["rows"]
    buckets = _buckets(rows, key)
    assert buckets == sorted(buckets)
    assert {1, 2} <= set(buckets)  # flagged and blank rows exist (full-n: see the next test)
    for b in (0, 1):
        means = [r[key]["mean"] for r, x in zip(rows, buckets, strict=True) if x == b]
        assert means == sorted(means, reverse=direction == "desc")


def test_default_sort_and_tail(rows_page: Callable[..., dict[str, Any]]) -> None:
    rows = rows_page(sort=None)["rows"]
    keyed = [(-r["gamesCount"], r["names"]) for r in rows]
    assert keyed == sorted(keyed)
    # CASE_PAST_CUT lands past the 25-row cut (D-13)
    pos = next(i for i, r in enumerate(rows) if "zz-cut-pbp" in [p["slug"] for p in r["people"]])
    assert pos >= 25


@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_rank_sort_blanks_last(rows_page: Callable[..., dict[str, Any]], direction: str) -> None:
    rows = rows_page(sort={"key": "rank", "dir": direction})["rows"]
    keys = [r["rankKey"] for r in rows]
    ranked = [k for k in keys if k is not None]
    assert keys == ranked + [None] * (len(keys) - len(ranked))
    assert ranked == sorted(ranked, reverse=direction == "desc")
    assert len(ranked) == 2 and len(keys) > 25
    if direction == "asc":
        assert rows[0]["rankRun"].startswith("Lead") and rows[1]["rankRun"].startswith("No. 2")


def test_text_sorts_and_input_untouched(rows_page: Callable[..., dict[str, Any]]) -> None:
    by_crew = rows_page(sort={"key": "crew", "dir": "asc"})["rows"]
    names = [r["names"] for r in by_crew]
    assert names == sorted(names)
    by_games = rows_page(sort={"key": "games", "dir": "asc"})["rows"]
    counts = [r["gamesCount"] for r in by_games]
    assert counts == sorted(counts)
    # no dir: the natural direction (games descending)
    natural = [r["gamesCount"] for r in rows_page(sort={"key": "games"})["rows"]]
    assert natural == sorted(natural, reverse=True)


_SYNTH_SORT_JS = """
async ({key, dir}) => {
  const G = await import('./modules/crew-groups.js');
  const m = (mean, n, flagged, blank = null) => ({ mean, n, flagged, blank });
  const mk = (names, v) => ({ names, gamesCount: 5, [key]: v, network: { name: '' } });
  const rows = [
    mk('blank-a', m(null, 0, false, 'none')),
    mk('flag-hi', m(9, 2, true)),
    mk('full-lo', m(2, 9, false)),
    mk('flag-lo', m(1, 1, true)),
    mk('full-hi', m(8, 12, false)),
    mk('blank-b', m(null, 9, false, 'break')),
  ];
  return G.sortCrewRows(rows, {key, dir}).map((r) => r.names);
}
"""


@pytest.mark.parametrize("key", ["exc", "viewers"])
def test_metric_sort_full_n_then_flagged_then_blank(
    rows_page: Callable[..., dict[str, Any]], guarded_page: Page, key: str
) -> None:
    rows_page()  # the app is open
    desc = guarded_page.evaluate(_SYNTH_SORT_JS, {"key": key, "dir": "desc"})
    asc = guarded_page.evaluate(_SYNTH_SORT_JS, {"key": key, "dir": "asc"})
    assert desc == ["full-hi", "full-lo", "flag-hi", "flag-lo", "blank-a", "blank-b"]
    assert asc == ["full-lo", "full-hi", "flag-lo", "flag-hi", "blank-a", "blank-b"]


# -- CFB-05: every master filter acts on the table as the matrix says ---------------------------

_PARTIALS: dict[str, dict[str, Any]] = {
    "seasons": {"seasons": [2024, 2024]},
    "seasons-wide": {"seasons": [2023, 2024]},
    "networks": {"networks": ["net-a"]},
    "slots": {"slots": ["afternoon"]},
    "slots-none": {"slots": ["night"]},
    "conference": {"conferences": ["@conf"]},
    "school": {"school": ["@team:0"]},
    "postseason-exclude": {"postseason": "exclude"},
    "postseason-only": {"postseason": "only"},
    "game": {"game": "@game:0"},
    "booth-a": {"booth": ["a"]},
    "booth-ab": {"booth": ["a", "b"]},
    "announcers": {"people": ["trio-pbp"]},
    "announcers-booth": {"people": ["fill-pbp"], "booth": ["a"]},
}


def _merged(raw: dict[str, Any], key: str) -> list[Any]:
    """A telecast column in the page's index order: rated games, then unrated."""
    unrated = raw["telecasts_unrated"]
    tail = unrated.get(key) or [None] * len(unrated["season"])
    return [*raw["telecasts"][key], *tail]


@pytest.mark.parametrize("name", sorted(_PARTIALS))
def test_filters_recount_rows(
    rows_page: Callable[..., dict[str, Any]], fixture_raw: dict[str, Any], name: str
) -> None:
    raw = build_crews_raw(fixture_raw)
    # every synthetic game copies the shared fixture's first rated game, so that conference matches
    conference = raw["lookups"]["conferences"][raw["telecasts"]["home_conference"][0]]["name"]
    partial = {
        k: [conference if x == "@conf" else x for x in v] if isinstance(v, list) else v
        for k, v in _PARTIALS[name].items()
    }
    out = rows_page(partial)
    season = _merged(raw, "season")
    exc = _merged(raw, "excitement")
    n_rated = len(raw["telecasts"]["season"])
    viewers = [*raw["telecasts"]["viewers"], *[None] * len(raw["telecasts_unrated"]["season"])]
    if "seasons" in partial:
        lo, hi = partial["seasons"]
        assert all(lo <= season[i] <= hi for i in out["passes"])

    expected: dict[str, list[int]] = {}
    for i in out["passes"]:
        if out["keys"][i] is not None:
            expected.setdefault(out["keys"][i], []).append(i)
    rows = {r["crewKey"]: r for r in out["rows"]}
    assert set(rows) == set(expected)
    assert out["totalRows"] == len(expected)
    for key, games in expected.items():
        row = rows[key]
        assert row["gamesCount"] > 0 and sorted(row["games"]) == games
        excs = [exc[i] for i in games if exc[i] is not None]
        vs = [viewers[i] for i in games if i < n_rated and viewers[i] is not None]
        assert row["exc"]["n"] == len(excs) and row["viewers"]["n"] == len(vs)
        for metric, vals in (("exc", excs), ("viewers", vs)):
            if row[metric]["blank"] is None:
                assert math.isclose(row[metric]["mean"], sum(vals) / len(vals))
            else:
                assert row[metric]["mean"] is None


def test_announcers_highlight_not_filter(rows_page: Callable[..., dict[str, Any]]) -> None:
    """U-06: picking an announcer highlights, so no row leaves the table."""
    cleared = rows_page()
    picked = rows_page({"people": ["trio-pbp"]})
    assert {r["crewKey"] for r in picked["rows"]} == {r["crewKey"] for r in cleared["rows"]}
    assert picked["leftOut"] == cleared["leftOut"]


def test_zero_game_rows_absent_under_seasons(rows_page: Callable[..., dict[str, Any]]) -> None:
    out = rows_page({"seasons": [2022, 2022]})
    assert out["rows"] and all(r["gamesCount"] > 0 for r in out["rows"])
    assert all(len(r["games"]) == r["gamesCount"] for r in out["rows"])
    empty = rows_page({"slots": ["night"]})
    assert empty["rows"] == [] and empty["totalRows"] == 0
