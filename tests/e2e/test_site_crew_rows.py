"""Row model of the Crews table: Crew, PBP and Analyst rows, metrics, sort (plan 14-03).

Model-level tests: they run `buildCrewRows` / `sortCrewRows` in the page on the synthetic
crews dataset (tests/e2e/crews_fixture.py). Expected values come from the CASE_* constants.
"""

from __future__ import annotations

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
  const state = Object.assign(S.defaultState(data), partial);
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
