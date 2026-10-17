"""Apple booths table (SPORT-06) on synthetic 2026 data."""

from __future__ import annotations

import dataclasses
import math
from datetime import date, timedelta
from pathlib import Path

import polars as pl
from mlb_games_support import build_reference

from booth_review.mlb.apple import APPLE_BOOTHS_TABLE, APPLE_SUMMARY_TABLE, build_apple_booths
from booth_review.mlb.crews import booth_key
from booth_review.mlb.listings import game_key, telecast_frame
from booth_review.mlb.reference import MlbBoothRank, MlbBoothRanks
from booth_review.mlb.rr_match import RRGameMatch

DAY0 = date(2026, 5, 1)
PLAN = [("p1", "506")] * 3 + [("p1", "relay")] * 3 + [("p2", "506")] * 4 + [("p3", "relay")] * 2


def _tele(i: int, pbp: str | None, source: str | None, *, network="apple", production="own"):
    day = DAY0 + timedelta(days=i)
    return {
        "game_key": game_key(day, "alpha", "bravo", 0),
        "season": 2026,
        "game_date": day,
        "away_club": "alpha",
        "home_club": "bravo",
        "game_number": 0,
        "network_id": network,
        "family": network,
        "starred": False,
        "is_exclusive": None,
        "production": production,
        "window": None,
        "local_outlet": None,
        "crew_names": [],
        "local_simulcast": production == "simulcast",
        "source": "506",
        "source_label": "1",
        "round": None,
        "series_game": None,
        "neutral": False,
        "venue_note": None,
        "date_shift": False,
    }


def crews_frame() -> pl.DataFrame:
    rows, extra = [], []
    for i, (pbp, source) in enumerate(PLAN):
        rows.append(_tele(i, pbp, source))
        extra.append((pbp, source))
    rows.append(_tele(20, None, None, production="simulcast"))
    extra.append((None, None))
    rows.append(_tele(21, "p9", "506", network="fox_net"))
    extra.append(("p9", "506"))
    frame = telecast_frame(rows)
    return frame.with_columns(
        pl.Series("pbp_person_id", [p for p, _ in extra], dtype=pl.String),
        pl.Series(
            "analyst_person_ids", [["a"] if p else [] for p, _ in extra], dtype=pl.List(pl.String)
        ),
        pl.Series("crew_source", [s for _, s in extra], dtype=pl.String),
        pl.Series("crew_named", [p is not None for p, _ in extra], dtype=pl.Boolean),
        pl.Series("crew_in_scope", [p is not None for p, _ in extra], dtype=pl.Boolean),
        pl.Series(
            "booth_key",
            [booth_key(n, 2026, p) for (p, _), n in zip(extra, frame["network_id"], strict=True)],
            dtype=pl.String,
        ),
    )


def make_ref(tmp_path: Path, ranks: list[tuple[int, str | None]]):
    ref = build_reference(tmp_path / "ref")
    rows = tuple(
        MlbBoothRank("apple", 2026, rank, f"n{rank}", "an", pid, None, "https://example.org/r")
        for rank, pid in ranks
    )
    return dataclasses.replace(ref, booth_ranks=MlbBoothRanks(rows, ()))


KEYS = [game_key(DAY0 + timedelta(days=i), "alpha", "bravo", 0) for i in range(12)]


def inputs(filled: bool):
    empty = pl.DataFrame(schema={"game_key": pl.String, "pregame_stakes": pl.Float64})
    stakes = (
        pl.DataFrame({"game_key": KEYS, "pregame_stakes": [1.0 + i * 0.1 for i in range(12)]})
        if filled
        else empty
    )
    exc = (
        pl.DataFrame({"game_key": KEYS, "wp_excitement": [2.0 + i * 0.2 for i in range(12)]})
        if filled
        else pl.DataFrame(schema={"game_key": pl.String, "wp_excitement": pl.Float64})
    )
    strength = pl.DataFrame({"game_key": KEYS, "strength_prior": [0.5] * 12})
    baseline = (
        pl.DataFrame(
            {
                "game_date": [date(2024, 5, 1)] * 10,
                "pregame_stakes": [0.5] * 10,
                "wp_excitement": [2.5] * 10,
            }
        )
        if filled
        else None
    )
    return stakes, exc, strength, baseline


def run(tmp_path, filled, ranks=((1, "p1"), (2, "p2"), (3, "p3")), rr=()):
    stakes, exc, strength, baseline = inputs(filled)
    return build_apple_booths(
        pl.DataFrame(),
        crews_frame(),
        stakes,
        exc,
        strength,
        list(rr),
        make_ref(tmp_path, list(ranks)),
        baseline=baseline,
    )


def test_table_names() -> None:
    assert APPLE_BOOTHS_TABLE == "mlb_apple_booths"
    assert APPLE_SUMMARY_TABLE == "mlb_apple_summary"


def test_pending_run_has_counts_labels_and_null_measures(tmp_path: Path) -> None:
    booths, summary, reviews, counts = run(tmp_path, filled=False)
    assert booths["rank_label"].to_list() == ["Lead", "#2", "#3"]
    assert booths["games"].to_list() == [6, 4, 2]
    assert booths["crew_listed"].to_list() == [6, 4, 2]
    assert booths["relay_crews"].to_list() == [3, 0, 2]
    assert booths["low_n"].to_list() == [True, True, True]
    assert set(booths["quality_status"]) == {"pending"}
    for col in ("stakes_raw", "stakes_adj", "excitement_raw", "excitement_adj"):
        assert booths[col].null_count() == 3
    assert booths["strength_prior"].to_list() == [0.5, 0.5, 0.5]
    row = summary.row(0, named=True)
    assert row["quality_status"] == "pending"
    assert row["apple_games"] == 12  # simulcast and other-network rows are excluded
    assert row["rr_rated"] == 0
    assert row["stakes_adj_diff"] is None and row["excitement_adj_diff_se"] is None
    assert reviews == []
    assert counts["booths"] == 3


def test_same_call_fills_when_inputs_arrive(tmp_path: Path) -> None:
    booths, summary, _, _ = run(tmp_path, filled=True)
    assert set(booths["quality_status"]) == {"ready"}
    lead = booths.row(0, named=True)
    # lead booth calls days 0..5: stakes 1.0..1.5, mean 1.25; baseline mean 0.5
    assert math.isclose(lead["stakes_raw"], 1.25)
    assert math.isclose(lead["stakes_adj"], 0.75)
    assert math.isclose(lead["excitement_adj"], 2.0 + 0.5 - 2.5)
    row = summary.row(0, named=True)
    assert row["quality_status"] == "ready"
    assert row["stakes_raw_lead_n"] == 6 and row["stakes_raw_others_n"] == 6
    expected_diff = 1.25 - sum(1.0 + i * 0.1 for i in range(6, 12)) / 6
    assert math.isclose(row["stakes_raw_diff"], expected_diff)
    assert row["stakes_raw_diff_se"] is not None and row["stakes_raw_diff_se"] > 0
    assert math.isclose(row["stakes_adj_diff"], expected_diff)


def test_unresolved_lead_is_null_with_review(tmp_path: Path) -> None:
    booths, summary, reviews, _ = run(tmp_path, filled=True, ranks=((1, None), (2, "p2")))
    assert "Lead" not in booths["rank_label"].to_list()
    assert summary["lead_booth_key"][0] is None
    assert summary["stakes_raw_diff"][0] is None
    assert [r.kind for r in reviews] == ["lead_unresolved"]


def test_lead_pbp_matching_no_booth_is_unresolved(tmp_path: Path) -> None:
    _, summary, reviews, _ = run(tmp_path, filled=False, ranks=((1, "nobody"),))
    assert summary["lead_booth_key"][0] is None
    assert reviews[0].kind == "lead_unresolved"


def test_rr_rated_counts_clean_figures_only(tmp_path: Path) -> None:
    def match(key, cause, viewers):
        return RRGameMatch(
            key,
            cause,
            None,
            (),
            None,
            (),
            (),
            viewers,
            "per-game",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )

    rr = [
        match(KEYS[0], None, 1.0e6),
        match(KEYS[1], "conflict", None),
        match("other", None, 2.0e6),
    ]
    _, summary, _, counts = run(tmp_path, filled=False, rr=rr)
    assert summary["rr_rated"][0] == 1
    assert counts["rr_rated"] == 1


def test_booth_analyst_label_is_most_frequent_and_crew_listed_counts_named(
    tmp_path: Path,
) -> None:
    frame = crews_frame()
    analysts = frame["analyst_person_ids"].to_list()
    # p2's four games (indexes 6-9): first game a one-off, the rest the regular analyst
    analysts[6] = ["one_off"]
    for i in (7, 8, 9):
        analysts[i] = ["regular"]
    frame = frame.with_columns(pl.Series("analyst_person_ids", analysts, dtype=pl.List(pl.String)))
    sources = frame["crew_source"].to_list()
    sources[6] = "wikipedia"  # a named crew from a non-506/relay source still counts as listed
    frame = frame.with_columns(pl.Series("crew_source", sources, dtype=pl.String))
    ref = make_ref(tmp_path, [(1, "p1"), (2, "p2"), (3, "p3")])
    stakes, exc, strength, baseline = inputs(False)
    booths, _, _, _ = build_apple_booths(
        pl.DataFrame(), frame, stakes, exc, strength, [], ref, baseline=baseline
    )
    row = booths.filter(pl.col("pbp_person_id") == "p2").row(0, named=True)
    assert row["analyst_person_ids"] == ["regular"]
    assert row["crew_listed"] == row["games"] == 4
