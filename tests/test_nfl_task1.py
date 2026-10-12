"""Task 1 crew table on synthetic game frames (invented games, people and figures)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest
from nfl_game_helpers import make_ref

from booth_review.nfl.adjust import LOW_N, VIEWERSHIP_PREDICTORS
from booth_review.nfl.games import NFL_GAME_SCHEMA, NflGameTable, NflReference
from booth_review.nfl.reference import NflLeadBoothOverride
from booth_review.nfl.task1 import (
    NFL_TASK1_COLUMNS,
    VIEW_CATEGORY_ORDER,
    build_task1,
    view_category_expr,
)

FULL = "+".join(VIEWERSHIP_PREDICTORS)
FIRST_SUNDAY = date(2015, 9, 13)

_USED = (
    "season",
    "week",
    "game_type",
    "game_id",
    "game_date",
    "network_id",
    "slot_name",
    "is_cbs_national",
    "is_agotw",
    "late_national_status",
    "pbp_person_id",
    "analyst_person_id",
    "pregame_spread",
    "final_margin",
    "excitement_score",
    "wp_volatility",
    "viewership",
    "era_id",
    "crew_source",
)
SCHEMA = {k: NFL_GAME_SCHEMA[k] for k in _USED}


def game(
    gid: str,
    *,
    season: int = 2015,
    week: int = 1,
    network: str = "fox",
    slot: str = "Sunday late",
    cbs_national: bool = False,
    crew_source: str | None = "506",
    agotw: bool = False,
    status: str | None = None,
    pbp: str | None = None,
    analyst: str | None = None,
    spread: float | None = 3.0,
    margin: float | None = 7.0,
    excitement: float | None = 3.0,
    volatility: float | None = 0.03,
    viewers: float | None = None,
    era: str = "era-a",
    game_type: str = "REG",
    day_offset: int = 0,
) -> dict[str, object]:
    return {
        "season": season,
        "week": week,
        "game_type": game_type,
        "game_id": gid,
        "game_date": FIRST_SUNDAY.replace(year=season)
        + timedelta(days=7 * (week - 1) + day_offset),
        "network_id": network,
        "slot_name": slot,
        "is_cbs_national": cbs_national,
        "is_agotw": agotw,
        "late_national_status": status or ("single" if agotw else "not_agotw"),
        "pbp_person_id": pbp,
        "analyst_person_id": analyst,
        "pregame_spread": spread,
        "final_margin": margin,
        "excitement_score": excitement,
        "wp_volatility": volatility,
        "viewership": viewers,
        "era_id": era,
        "crew_source": crew_source,
    }


def background(season: int = 2015) -> list[dict[str, object]]:
    """240 CBS games, 60 per spread band, margin = 4 + |spread| exactly."""
    rows = []
    for band, spread in enumerate((1.5, 4.5, 8.0, 12.0)):
        for i in range(60):
            rows.append(
                game(
                    f"bg-{season}-{band}-{i}",
                    season=season,
                    week=1 + i % 17,
                    network="cbs",
                    spread=spread if i % 2 else -spread,
                    margin=4 + spread,
                    excitement=2.0 + spread / 4,
                    volatility=0.02,
                )
            )
    return rows


def table(rows: list[dict[str, object]]) -> NflGameTable:
    frame = pl.DataFrame(rows, schema=SCHEMA, orient="row")
    return NflGameTable(frame=frame, reviews={}, counts={}, through_week={})


@pytest.fixture
def ref(tmp_path: Path) -> NflReference:
    return make_ref(tmp_path)


def booth_rows(out: pl.DataFrame) -> pl.DataFrame:
    return out.filter(pl.col("view") == "booth")


def lead_case() -> list[dict[str, object]]:
    rows = background()
    for week in range(1, 11):
        # Lead booth: big mismatches that finished closer than the league expects.
        rows.append(
            game(
                f"lead-{week}",
                week=week,
                agotw=True,
                pbp="pb-lead",
                analyst="an-lead",
                spread=12.0,
                margin=3.0,
            )
        )
        rows.append(
            game(f"two-{week}", week=week, pbp="pb-two", analyst="an-two", spread=1.5, margin=5.5)
        )
    for week in range(1, 4):
        rows.append(
            game(f"three-{week}", week=week, pbp="pb-three", analyst="an-three", spread=4.5)
        )
    rows.append(game("two-fill", week=11, pbp="pb-two", analyst="an-fill", spread=1.5, margin=5.5))
    return rows


def test_columns_and_constants_on_every_row(ref: NflReference) -> None:
    out, _, _ = build_task1(table(lead_case()), ref)
    assert tuple(out.columns) == NFL_TASK1_COLUMNS
    for name in (
        "coverage_normalized",
        "viewership_scope",
        "excitement_method",
        "era_id",
        "predictors_used",
    ):
        assert name in NFL_TASK1_COLUMNS
    assert out["coverage_normalized"].to_list() == [False] * out.height
    assert set(out["excitement_method"].to_list()) == {"GEI-style"}


def test_lead_gets_bigger_mismatches_but_closer_than_expected(ref: NflReference) -> None:
    out, _, _ = build_task1(table(lead_case()), ref)
    booths = booth_rows(out)
    lead = booths.filter(pl.col("booth_group") == "lead").row(0, named=True)
    two = booths.filter(pl.col("booth_pbp_person_id") == "pb-two").row(0, named=True)
    assert lead["booth_rank"] == 1 and lead["booth_pbp_person_id"] == "pb-lead"
    assert lead["regular_analyst_person_id"] == "an-lead"
    assert lead["games"] == 10 and lead["raw_n_spread"] == 10
    assert lead["raw_mean_abs_spread"] > two["raw_mean_abs_spread"]
    assert lead["adj_margin_resid"] < 0
    assert lead["adj_n_margin"] == 10 and lead["adj_margin_se"] == pytest.approx(0.0)
    assert lead["low_n"] is False
    assert two["booth_group"] == "other" and two["booth_rank"] == 2
    assert two["fill_in_games"] == 1 and two["games"] == 11
    assert two["adj_margin_resid"] == pytest.approx(0.0)
    assert lead["predictors_used"] is None and lead["era_id"] is None
    assert lead["viewership_scope"] is None


def test_low_n_booth_and_no_pooled_others_row(ref: NflReference) -> None:
    out, _, _ = build_task1(table(lead_case()), ref)
    booths = booth_rows(out)
    three = booths.filter(pl.col("booth_pbp_person_id") == "pb-three").row(0, named=True)
    assert three["booth_rank"] == 3 and three["games"] == 3 < LOW_N
    assert three["low_n"] is True
    assert three["network_group"] == "fox" and three["rank_source"] == "inferred"
    assert set(booths["booth_group"].to_list()) == {"lead", "other"}
    assert booths["booth_pbp_person_id"].null_count() == 0


def test_booth_rows_carry_flagship_games_and_raw_viewers(ref: NflReference) -> None:
    rows = lead_case()
    for r in rows:
        if r["game_id"] in ("lead-1", "lead-2"):
            r["viewership"] = 100.0 if r["game_id"] == "lead-1" else 200.0
    out, _, _ = build_task1(table(rows), ref)
    lead = booth_rows(out).filter(pl.col("booth_group") == "lead").row(0, named=True)
    assert lead["flagship_games"] == 10
    assert lead["raw_n_viewers"] == 2 and lead["raw_mean_viewers"] == pytest.approx(150.0)
    two = booth_rows(out).filter(pl.col("booth_pbp_person_id") == "pb-two").row(0, named=True)
    assert two["flagship_games"] == 0
    assert two["raw_n_viewers"] == 0 and two["raw_mean_viewers"] is None


def test_zero_game_published_booth_has_null_measures(ref: NflReference) -> None:
    from booth_review.nfl.reference import NflBoothRank

    cited = (NflBoothRank("fox", 2015, 1, "pb-lead", "an-lead", "https://example.com/r"),)
    cited += (NflBoothRank("fox", 2015, 2, "pb-ghost", "an-ghost", "https://example.com/r"),)
    out, _, counts = build_task1(
        table(lead_case()), replace(ref, booth_ranks={("fox", 2015): cited})
    )
    ghost = booth_rows(out).filter(pl.col("booth_pbp_person_id") == "pb-ghost").row(0, named=True)
    assert ghost["games"] == 0 and ghost["booth_rank"] == 2
    assert ghost["rank_source"] == "published"
    assert ghost["raw_mean_abs_spread"] is None and ghost["adj_margin_resid"] is None
    assert ghost["low_n"] is True
    assert counts["seasons_published"] == 1


def test_null_measures_are_counted_not_zeroed(ref: NflReference) -> None:
    rows = lead_case()
    rows.append(game("lead-null", week=12, pbp="pb-lead", analyst="an-lead", spread=None))
    out, _, _ = build_task1(table(rows), ref)
    lead = booth_rows(out).filter(pl.col("booth_group") == "lead").row(0, named=True)
    assert lead["games"] == 11
    assert lead["raw_n_spread"] == 10 and lead["raw_n_margin"] == 11
    assert lead["adj_n_margin"] == 10


def test_playoff_games_stay_out_of_booths(ref: NflReference) -> None:
    rows = lead_case()
    rows.append(game("po", week=19, game_type="WC", pbp="pb-lead", analyst="an-lead"))
    out, reviews, _ = build_task1(table(rows), ref)
    lead = booth_rows(out).filter(pl.col("booth_group") == "lead").row(0, named=True)
    assert lead["games"] == 10
    assert "single_header_weeks" not in reviews


def test_non_doubleheader_fox_games_now_count(ref: NflReference) -> None:
    rows = lead_case()
    rows.append(game("single", week=12, pbp="pb-lead", analyst="an-lead"))
    out, _, _ = build_task1(table(rows), ref)
    lead = booth_rows(out).filter(pl.col("booth_group") == "lead").row(0, named=True)
    assert lead["games"] == 11


def test_other_group_booths_are_built(ref: NflReference) -> None:
    rows = lead_case()
    rows += [game(f"c-{i}", week=i + 1, network="cbs", pbp="pb-cbs") for i in range(3)]
    out, _, _ = build_task1(table(rows), ref)
    cbs = booth_rows(out).filter(pl.col("network_group") == "cbs")
    assert cbs["booth_pbp_person_id"].to_list() == ["pb-cbs"]


# -- view_category ------------------------------------------------------------------------------


def test_view_category_expr_mapping() -> None:
    cases = [
        (dict(agotw=True, status="single"), "agotw"),
        (dict(agotw=True, status="ambiguous", slot="Sunday late"), None),
        (dict(cbs_national=True), "cbs_national"),
        (dict(slot="SNF"), "snf"),
        (dict(slot="MNF"), "mnf"),
        (dict(slot="TNF"), "tnf"),
        (dict(slot="Thanksgiving"), "thanksgiving"),
        (dict(slot="Christmas"), "christmas"),
        (dict(slot="Black Friday"), "black_friday"),
        (dict(slot="International"), "international"),
        (dict(slot="Saturday"), "saturday"),
        (dict(slot="Friday"), "friday"),
        (dict(slot="Other"), "other"),
        (dict(slot="Sunday early"), None),
        (dict(slot="Sunday late"), None),
    ]
    frame = pl.DataFrame([game(f"g{i}", **kw) for i, (kw, _) in enumerate(cases)], schema=SCHEMA)  # type: ignore[arg-type]
    got = frame.select(view_category_expr())["view_category"].to_list()
    assert got == [want for _, want in cases]
    assert set(VIEW_CATEGORY_ORDER) >= {w for _, w in cases if w}


# -- category viewership by era ---------------------------------------------------------------


def agotw_games(
    era: str, season: int, count: int, *, booth: str, base: float, full: bool, start: int = 0
) -> list[dict[str, object]]:
    rows = []
    for i in range(start, start + count):
        spread = float((i * 7) % 15) - 7.0
        margin = float((i * 11) % 23) - 9.0
        excitement = 1.0 + ((i * 5) % 13) / 2.0
        volatility = 0.01 * ((i * 3) % 17) + 0.02 * (i % 4)
        if full:
            viewers = base + 50 * abs(spread) - 20 * abs(margin) + 30 * excitement + 10 * volatility
        else:
            viewers = base + 50 * abs(spread)
        rows.append(
            game(
                f"ag-{era}-{season}-{i}",
                season=season,
                week=1 + i % 18,
                agotw=True,
                pbp=booth,
                analyst=f"an-{booth}",
                spread=spread,
                margin=margin,
                excitement=excitement,
                volatility=volatility,
                viewers=viewers,
                era=era,
            )
        )
    return rows


def viewership_case() -> list[dict[str, object]]:
    rows = background()
    rows += agotw_games("era-a", 2015, 20, booth="pb-a", base=1000, full=True)
    rows += agotw_games("era-a", 2016, 20, booth="pb-b", base=1000, full=True, start=20)
    rows += agotw_games("era-b", 2017, 12, booth="pb-b", base=9000, full=False)
    rows += agotw_games("era-c", 2018, 8, booth="pb-c", base=1000, full=True)
    # A Sunday-late game with a figure has no category and never enters the view.
    rows.append(game("other-fig", season=2015, pbp="pb-x", analyst="an-x", viewers=500.0))
    return rows


def viewership_rows(out: pl.DataFrame) -> pl.DataFrame:
    return out.filter(pl.col("view") == "category_viewership")


def test_viewership_rows_per_category_season_era(ref: NflReference) -> None:
    out, _, counts = build_task1(table(viewership_case()), ref)
    view = viewership_rows(out)
    keys = [(r["season"], r["view_category"], r["era_id"]) for r in view.iter_rows(named=True)]
    assert keys == [
        (2015, "agotw", "era-a"),
        (2016, "agotw", "era-a"),
        (2017, "agotw", "era-b"),
        (2018, "agotw", "era-c"),
    ]
    assert int(view["n_viewership"].sum()) == 60
    assert set(view["viewership_scope"].to_list()) == {"window"}
    assert view["coverage_normalized"].to_list() == [False] * 4
    assert view["booth_pbp_person_id"].null_count() == 4
    assert counts["category_viewership_games"] == 60
    assert counts["category_viewership_no_era"] == 0


def test_full_model_fallback_and_thin_era(ref: NflReference) -> None:
    out, reviews, counts = build_task1(table(viewership_case()), ref)
    view = {
        r["era_id"]: r for r in viewership_rows(out).iter_rows(named=True) if r["season"] > 2015
    }
    assert viewership_rows(out).filter(pl.col("era_id") == "era-a")["predictors_used"][0] == FULL
    assert view["era-a"]["viewership_resid"] == pytest.approx(0.0, abs=1e-6)
    assert view["era-b"]["predictors_used"] == "abs_spread"
    # Fit within era-b only: era-b's line is exact, so pooling with era-a would show.
    assert view["era-b"]["viewership_resid"] == pytest.approx(0.0, abs=1e-6)
    assert view["era-b"]["mean_viewers"] > 9000
    thin = view["era-c"]
    assert thin["predictors_used"] is None
    assert thin["viewership_resid"] is None and thin["viewership_se"] is None
    assert thin["n_viewership"] == 8 and thin["low_n"] is True
    model = [r for r in reviews["task1_model"] if r["kind"] == "viewership"]
    by_era = {r["era_id"]: r for r in model}
    assert by_era["era-a"]["predictors_used"] == FULL and by_era["era-a"]["n"] == 40
    assert by_era["era-a"]["view_category"] == "agotw"
    assert by_era["era-a"]["coef_abs_spread"] == pytest.approx(50, abs=1e-6)
    assert by_era["era-b"]["coef_abs_final_margin"] is None
    assert by_era["era-c"]["reason"] == "thin-era" and by_era["era-c"]["n"] == 8
    assert counts["thin_eras"] == 1


def test_models_are_fitted_within_each_category(ref: NflReference) -> None:
    rows = background()
    rows += agotw_games("era-a", 2015, 20, booth="pb-a", base=1000, full=True)
    snf = agotw_games("era-a", 2015, 20, booth="pb-s", base=50000, full=True)
    for r in snf:
        r["is_agotw"] = False
        r["late_national_status"] = "not_agotw"
        r["slot_name"] = "SNF"
        r["game_id"] = str(r["game_id"]).replace("ag-", "snf-")
    out, reviews, _ = build_task1(table(rows + snf), ref)
    view = viewership_rows(out)
    assert sorted(view["view_category"].to_list()) == ["agotw", "snf"]
    assert view["viewership_resid"].abs().max() < 1e-6  # type: ignore[operator]
    assert set(view["viewership_scope"].to_list()) == {"window", "game"}
    fits = [r for r in reviews["task1_model"] if r["kind"] == "viewership"]
    assert {r["view_category"] for r in fits} == {"agotw", "snf"}


def test_games_without_an_era_are_counted_and_dropped(ref: NflReference) -> None:
    rows = viewership_case()
    rows.append(game("noera", agotw=True, viewers=700.0, era=None))  # type: ignore[arg-type]
    out, _, counts = build_task1(table(rows), ref)
    assert counts["category_viewership_no_era"] == 1
    assert int(viewership_rows(out)["n_viewership"].sum()) == 60


def test_model_review_lists_bands_and_ols_per_outcome(ref: NflReference) -> None:
    _, reviews, _ = build_task1(table(lead_case()), ref)
    model = reviews["task1_model"]
    bands = [r for r in model if r["kind"] == "band"]
    ols = [r for r in model if r["kind"] == "ols"]
    assert {r["outcome"] for r in bands} == {
        "abs_final_margin",
        "excitement_score",
        "wp_volatility",
    }
    assert len(bands) == 12 and len(ols) == 3
    assert all(set(r) == set(model[0]) for r in model)


def test_lead_reviews_and_counts(ref: NflReference) -> None:
    rows = lead_case()
    # Week 12: pb-two calls AGOTW while the lead calls another Fox game.
    rows.append(game("miss-a", week=12, agotw=True, pbp="pb-two", analyst="an-two"))
    rows.append(game("miss-b", week=12, pbp="pb-lead", analyst="an-lead"))
    _, reviews, counts = build_task1(table(rows), ref)
    assert len(reviews["agotw_misses"]) == 1
    assert {
        "seasons_close",
        "seasons_tied",
        "agotw_miss_weeks",
        "published_lineup_games",
        "booth_rank_disagreements",
        "ambiguous_fox_weeks",
    } <= set(counts)
    assert counts["agotw_miss_weeks"] == 1
    assert all(isinstance(v, int) for v in counts.values())
    assert set(reviews) == {
        "lead_booth",
        "agotw_misses",
        "lead_absent_weeks",
        "booth_rank_disagreements",
        "task1_model",
    }


def test_lead_override_is_honored(ref: NflReference) -> None:
    ov = NflLeadBoothOverride(2015, "fox", "pb-two", "reported", "https://example.com/x")
    out, _, counts = build_task1(
        table(lead_case()), replace(ref, lead_booth_overrides={("fox", 2015): ov})
    )
    lead = booth_rows(out).filter(pl.col("booth_group") == "lead").row(0, named=True)
    assert lead["booth_pbp_person_id"] == "pb-two"
    assert counts["seasons_overridden"] == 1


def test_empty_frame_gives_empty_table(ref: NflReference) -> None:
    out, reviews, counts = build_task1(table([]), ref)
    assert out.height == 0 and tuple(out.columns) == NFL_TASK1_COLUMNS
    assert counts["task1_booth_rows"] == 0
    assert reviews["task1_model"] is not None


def test_build_is_deterministic(ref: NflReference) -> None:
    rows = viewership_case() + lead_case()[240:]
    first, _, _ = build_task1(table(rows), ref)
    second, _, _ = build_task1(table(list(reversed(rows))), ref)
    assert first.equals(second)
