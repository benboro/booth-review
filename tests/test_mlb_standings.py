"""Standings, pregame stakes and the strength prior on an invented eight-club league."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from mlb_games_support import build_reference

from booth_review.mlb import standings
from booth_review.mlb.constants import STAKES_MIN_GAMES
from booth_review.mlb.standings import (
    daily_standings,
    game_strength_prior,
    pregame_stakes,
    strength_prior,
    team_divisions,
    team_leverage,
)

TEAMS = {
    "E1": ("AL", "East"),
    "E2": ("AL", "East"),
    "E3": ("AL", "East"),
    "W1": ("AL", "West"),
    "W2": ("AL", "West"),
    "W3": ("AL", "West"),
    "N1": ("NL", "Central"),
    "N2": ("NL", "Central"),
}

# (day, away, home, away runs, home runs, game number)
SCHEDULE: list[tuple[str, str, str, int | None, int | None, int]] = [
    ("01", "E1", "E2", 5, 3, 0),
    ("01", "E3", "W3", 4, 0, 0),
    ("01", "W1", "W2", 3, 1, 0),
    ("02", "E1", "E3", 2, 1, 0),
    ("02", "W1", "W3", 6, 2, 0),
    ("02", "W2", "E2", 0, 7, 0),
    ("03", "E2", "E3", 3, 2, 0),
    ("03", "E1", "W1", 3, 1, 0),
]
DAY3 = "03"


def gameinfo(
    season: int = 2021,
    schedule: list[tuple[str, str, str, int | None, int | None, int]] | None = None,
    *,
    forfeit: dict[int, str] | None = None,
    round_: str = "regular",
) -> pl.DataFrame:
    rows = []
    for index, (day, away, home, vr, hr, number) in enumerate(schedule or SCHEDULE):
        date = f"{season}04{day}"
        rows.append(
            {
                "gid": f"{home}{date}{number}",
                "visteam": away,
                "hometeam": home,
                "date": date,
                "number": number,
                "season": season,
                "round": round_,
                "vruns": vr,
                "hruns": hr,
                "forfeit": (forfeit or {}).get(index),
            }
        )
    return pl.DataFrame(
        rows,
        schema={
            "gid": pl.String,
            "visteam": pl.String,
            "hometeam": pl.String,
            "date": pl.String,
            "number": pl.Int8,
            "season": pl.Int32,
            "round": pl.String,
            "vruns": pl.Int32,
            "hruns": pl.Int32,
            "forfeit": pl.String,
        },
    )


def row_of(frame: pl.DataFrame, date: str, team: str) -> dict[str, object]:
    found = frame.filter((pl.col("date") == date) & (pl.col("team") == team))
    assert found.height == 1
    return found.row(0, named=True)


def test_record_is_through_the_previous_day() -> None:
    frame, reviews = daily_standings(gameinfo(), TEAMS, 2021)
    assert reviews == []
    first = row_of(frame, "20210401", "E1")
    assert (first["w"], first["l"], first["played"]) == (0, 0, 0)
    assert first["games_left"] == 162
    assert (row_of(frame, "20210402", "E1")["w"], row_of(frame, "20210402", "E1")["l"]) == (1, 0)
    third = row_of(frame, "20210403", "E1")
    assert (third["w"], third["l"]) == (2, 0)
    assert row_of(frame, "20210403", "W2")["l"] == 2


def test_doubleheader_and_suspended_games_count_on_their_recorded_date() -> None:
    schedule = [
        ("01", "E1", "E2", 5, 3, 1),
        ("01", "E1", "E2", 1, 2, 2),
        ("02", "E1", "E3", 2, 1, 0),
    ]
    frame, _ = daily_standings(gameinfo(schedule=schedule), TEAMS, 2021)
    assert row_of(frame, "20210401", "E1")["played"] == 0  # same-day games are not yet in
    after = row_of(frame, "20210402", "E1")
    assert (after["w"], after["l"]) == (1, 1)


def test_tie_and_forfeit_are_excluded_and_reviewed() -> None:
    schedule = [
        ("01", "E1", "E2", 4, 4, 0),
        ("01", "E3", "W3", 4, 0, 0),
        ("02", "W1", "W2", 3, 1, 0),
        ("03", "E1", "E2", 1, 0, 0),
    ]
    info = gameinfo(schedule=schedule, forfeit={1: "V"})
    frame, reviews = daily_standings(info, TEAMS, 2021)
    assert {(r.reason) for r in reviews} == {"tie", "forfeit"}
    assert all(r.gid for r in reviews)
    assert row_of(frame, "20210403", "E1")["played"] == 0
    assert row_of(frame, "20210403", "E3")["played"] == 0
    assert row_of(frame, "20210403", "W1")["w"] == 1


def test_games_behind_division_and_leader_lead() -> None:
    frame, _ = daily_standings(gameinfo(), TEAMS, 2021)
    assert row_of(frame, "20210403", "E1")["gb_div"] == pytest.approx(-1.0, abs=1e-12)
    assert row_of(frame, "20210403", "E2")["gb_div"] == pytest.approx(1.0, abs=1e-12)
    assert row_of(frame, "20210403", "E3")["gb_div"] == pytest.approx(1.0, abs=1e-12)
    assert row_of(frame, "20210403", "W1")["gb_div"] == pytest.approx(-2.0, abs=1e-12)
    assert row_of(frame, "20210403", "W3")["gb_div"] == pytest.approx(2.0, abs=1e-12)
    assert row_of(frame, "20210403", "N1")["gb_div"] == pytest.approx(0.0, abs=1e-12)


def test_wild_card_two_spots_through_2021() -> None:
    frame, _ = daily_standings(gameinfo(2021), TEAMS, 2021)
    # non-winners E2, E3 (1-1) hold the spots; W2, W3 (0-2) trail the last spot by one
    assert row_of(frame, "20210403", "E2")["gb_wc"] == pytest.approx(-1.0, abs=1e-12)
    assert row_of(frame, "20210403", "E3")["gb_wc"] == pytest.approx(-1.0, abs=1e-12)
    assert row_of(frame, "20210403", "W2")["gb_wc"] == pytest.approx(1.0, abs=1e-12)
    assert row_of(frame, "20210403", "W3")["gb_wc"] == pytest.approx(1.0, abs=1e-12)
    assert row_of(frame, "20210403", "E1")["gb_wc"] is None  # a division leader


def test_wild_card_three_spots_from_2022() -> None:
    frame, _ = daily_standings(gameinfo(2022), TEAMS, 2022)
    # W2 now holds the third spot and leads W3 (same record) by nothing
    assert row_of(frame, "20220403", "W2")["gb_wc"] == pytest.approx(0.0, abs=1e-12)
    assert row_of(frame, "20220403", "W3")["gb_wc"] == pytest.approx(0.0, abs=1e-12)
    assert row_of(frame, "20220403", "E2")["gb_wc"] == pytest.approx(-1.0, abs=1e-12)


def test_ties_break_by_wins_then_club_id_and_are_flagged() -> None:
    frame, _ = daily_standings(gameinfo(), TEAMS, 2021)
    e2, e3 = row_of(frame, "20210403", "E2"), row_of(frame, "20210403", "E3")
    assert e2["tie_flag"] is True and e3["tie_flag"] is True
    assert row_of(frame, "20210403", "E1")["tie_flag"] is False
    # E2 sorts ahead of E3 by club id, so E2 holds the first wild-card slot
    assert e2["gb_wc"] == e3["gb_wc"]


def test_results_frame_fills_missing_runs() -> None:
    blank = gameinfo(schedule=[(d, a, h, None, None, n) for d, a, h, _v, _r, n in SCHEDULE])
    empty, _ = daily_standings(blank, TEAMS, 2021)
    assert empty.is_empty()
    results = gameinfo().select("gid", "vruns", "hruns")
    frame, _ = daily_standings(blank, TEAMS, 2021, results=results)
    assert row_of(frame, "20210403", "E1")["w"] == 2


def test_team_leverage_matches_hand_numbers() -> None:
    assert team_leverage(0.0, None, 1) == pytest.approx(0.5641895835477563, abs=1e-12)
    assert team_leverage(1.0, -1.0, 100) == pytest.approx(0.05420673935524316, abs=1e-12)
    assert team_leverage(-1.0, None, 160) == pytest.approx(0.04350184836931465, abs=1e-12)
    assert team_leverage(1.5, 4.0, 36) == pytest.approx(0.07323188157795373, abs=1e-12)


def test_team_leverage_uses_the_race_closest_to_its_cutoff() -> None:
    # 0.5 out of the division but 8 clear in the wild-card field: the division race is live.
    assert team_leverage(0.5, -8.0, 100) == team_leverage(0.5, None, 100)
    assert team_leverage(0.5, -8.0, 100) > team_leverage(8.0, None, 100)
    assert team_leverage(-8.0, 0.5, 100) == team_leverage(0.5, None, 100)


def test_team_leverage_is_null_without_games_or_gap() -> None:
    assert team_leverage(1.0, 1.0, 0) is None
    assert team_leverage(None, None, 50) is None
    assert team_leverage(None, -1.0, 100) == team_leverage(-1.0, None, 100)


def _stakes_games(info: pl.DataFrame) -> pl.DataFrame:
    return info.filter(pl.col("date").str.ends_with(DAY3))


def test_pregame_stakes_is_mean_of_both_clubs_with_raw_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(standings, "STAKES_MIN_GAMES", 2)
    info = gameinfo()
    table, _ = daily_standings(info, TEAMS, 2021)
    out = pregame_stakes(_stakes_games(info), table, 2021)
    row = out.filter(pl.col("hometeam") == "W1").row(0, named=True)  # E1 at W1
    assert (row["away_w"], row["away_l"], row["away_gb_div"]) == (2, 0, -1.0)
    assert (row["home_w"], row["home_l"], row["home_gb_div"]) == (2, 0, -2.0)
    lo = team_leverage(-1.0, None, 160)
    hi = team_leverage(-2.0, None, 160)
    assert lo is not None and hi is not None
    assert row["pregame_stakes"] == pytest.approx((lo + hi) / 2, abs=1e-12)
    assert row["away_leverage"] == pytest.approx(lo, abs=1e-12)


def test_pregame_stakes_null_before_min_games() -> None:
    assert STAKES_MIN_GAMES > 2
    info = gameinfo()
    table, _ = daily_standings(info, TEAMS, 2021)
    out = pregame_stakes(_stakes_games(info), table, 2021)
    assert out.height == 2
    assert out["pregame_stakes"].null_count() == 2
    assert out["away_w"].null_count() == 0  # raw columns still shown


def test_pregame_stakes_null_in_2020_and_without_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(standings, "STAKES_MIN_GAMES", 0)
    info = gameinfo(2020)
    table, _ = daily_standings(info, TEAMS, 2020)
    assert pregame_stakes(_stakes_games(info), table, 2020)["pregame_stakes"].null_count() == 2
    blank = gameinfo(2026, [(d, a, h, None, None, n) for d, a, h, _v, _r, n in SCHEDULE])
    table, _ = daily_standings(blank, TEAMS, 2026)
    out = pregame_stakes(_stakes_games(blank), table, 2026)
    assert out["pregame_stakes"].null_count() == out.height == 2


def test_strength_prior_is_the_2025_win_percentage_and_2026_games_average_it() -> None:
    prior = strength_prior(gameinfo(2025), 2025)
    pct = dict(prior.select("team", "win_pct").iter_rows())
    assert pct["E1"] == pytest.approx(1.0)
    assert pct["E2"] == pytest.approx(2 / 3)
    assert pct["W3"] == pytest.approx(0.0)
    assert "N1" not in pct  # no 2025 games
    games = pl.DataFrame({"gid": ["a", "b"], "visteam": ["E1", "E1"], "hometeam": ["E2", "N1"]})
    out = game_strength_prior(games, prior)
    assert out["strength_prior"][0] == pytest.approx((1.0 + 2 / 3) / 2)
    assert out["strength_prior"][1] is None


def test_team_divisions_reads_the_reference(tmp_path: Path) -> None:
    ref = build_reference(tmp_path / "ref")
    mapping = team_divisions(ref, 2021)
    assert mapping["XAA"] == ("AL", "East")
    assert mapping["XDD"] == ("NL", "West")


def test_standings_are_deterministic() -> None:
    first, _ = daily_standings(gameinfo(), TEAMS, 2021)
    second, _ = daily_standings(gameinfo(), TEAMS, 2021)
    assert first.equals(second)
