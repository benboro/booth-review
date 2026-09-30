"""Tests for build/games.py: the FBS-scoped, null-safe games table (JOIN-07,
FLAG-04), its rank-week alignment, and the postseason rank rule.

Most behaviors run against the synthetic `build_vault` fixture (invented
teams/games/lines/rankings, D-07: see tests/fixtures/build/cfbd/*_2025.json
and tests/fixtures/spike/cfbd_games_2025.json). A few behaviors that the
shared fixture doesn't exercise (an FCS-vs-FCS game, a TBD kickoff, and
rank_alignment's own counting logic) use hand-built `SeasonSources` instead,
so this file never edits the shared fixtures (later plans add their own
fixture files under their own names; they don't edit conftest.py either).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from booth_review.build.games import (
    GAMES_SCHEMA,
    POLL_PREFERENCE,
    RANK_WEEK_OFFSET,
    build_games_frame,
    rank_alignment,
)
from booth_review.build.sources import SeasonSources, load_all_sources
from booth_review.config import DataPaths
from booth_review.resolve.names import to_et_date
from booth_review.sources.cfbd.parser import (
    CfbdGame,
    CfbdPoll,
    CfbdPollWeek,
    CfbdRank,
)
from booth_review.sources.sports506.parser import Listing506


def _game(**overrides: object) -> CfbdGame:
    defaults: dict[str, object] = {
        "id": 1,
        "season": 2099,
        "week": 5,
        "season_type": "regular",
        "start_date": datetime(2099, 10, 4, 16, 0, tzinfo=UTC),
        "start_time_tbd": False,
        "completed": True,
        "neutral_site": False,
        "conference_game": True,
        "venue": "Test Field",
        "home_id": 1,
        "home_team": "Home Team",
        "home_classification": "fbs",
        "home_conference": "Test Conference",
        "home_points": 20,
        "away_id": 2,
        "away_team": "Away Team",
        "away_classification": "fbs",
        "away_conference": "Test Conference",
        "away_points": 17,
        "excitement_index": None,
        "notes": None,
        "is_cfp": False,
        "playoff_round": None,
    }
    defaults.update(overrides)
    return CfbdGame(**defaults)  # type: ignore[arg-type]


def _sources(**overrides: object) -> SeasonSources:
    defaults: dict[str, object] = {
        "season": 2099,
        "games": [],
        "listings": [],
        "rr_records": [],
        "rr_parse_errors": 0,
        "media": [],
        "lines": [],
        "rankings": [],
        "wp_pregame": [],
    }
    defaults.update(overrides)
    return SeasonSources(**defaults)  # type: ignore[arg-type]


def _listing(**overrides: object) -> Listing506:
    defaults: dict[str, object] = {
        "season": 2099,
        "week_label": "5",
        "source_row_index": 0,
        "date_et": to_et_date(datetime(2099, 10, 4, 16, 0, tzinfo=UTC)),
        "kickoff_et": None,
        "away_raw": "Away Team",
        "away_rank": None,
        "home_raw": "Home Team",
        "home_rank": None,
        "neutral": False,
        "network_raw": None,
        "crew_raw": None,
        "crew_names": (),
        "feed_kind": "unknown",
        "game_label": None,
    }
    defaults.update(overrides)
    return Listing506(**defaults)  # type: ignore[arg-type]


# -- FBS scope and season_type filter -----------------------------------------------------


def test_build_vault_frame_is_fbs_scoped_regular_or_postseason(build_vault: DataPaths) -> None:
    sources = load_all_sources(build_vault, seasons=[2025])
    frame = build_games_frame(sources)

    assert frame.height == 30
    assert set(frame["season_type"].unique().to_list()) <= {"regular", "postseason"}
    assert frame["home_classification"].eq("fbs").all()
    assert frame["away_classification"].eq("fbs").all()


def test_fcs_vs_fcs_game_is_excluded() -> None:
    fcs_game = _game(
        id=999,
        home_classification="fcs",
        away_classification="fcs",
    )
    fbs_game = _game(id=1000)
    sources = [_sources(games=[fcs_game, fbs_game])]

    frame = build_games_frame(sources)

    assert frame["game_id"].to_list() == [1000]


def test_spring_season_type_is_excluded() -> None:
    spring_game = _game(id=1001, season_type="spring_regular")
    sources = [_sources(games=[spring_game])]

    frame = build_games_frame(sources)

    assert frame.height == 0


# -- Null-safety: excitement -------------------------------------------------------------


def test_missing_excitement_stays_null(build_vault: DataPaths) -> None:
    sources = load_all_sources(build_vault, seasons=[2025])
    frame = build_games_frame(sources)

    row = frame.filter(frame["game_id"] == 500007).row(0, named=True)
    assert row["excitement"] is None


def test_zero_excitement_stays_zero_not_null() -> None:
    game = _game(excitement_index=0.0)
    sources = [_sources(games=[game])]

    frame = build_games_frame(sources)

    assert frame.row(0, named=True)["excitement"] == 0.0


def test_notes_are_carried_into_the_vault_frame() -> None:
    frame = build_games_frame(
        [
            _sources(
                games=[
                    _game(id=1, notes="SYNTHETIC HARBOR NOTE"),
                    _game(id=2, notes=None),
                ]
            )
        ]
    )

    assert frame.filter(frame["game_id"] == 1).row(0, named=True)["notes"] == (
        "SYNTHETIC HARBOR NOTE"
    )
    assert frame.filter(frame["game_id"] == 2).row(0, named=True)["notes"] is None


# -- Closing spread, spread_provider, pregame_x -------------------------------------------


def test_closing_spread_prefers_consensus_provider(build_vault: DataPaths) -> None:
    sources = load_all_sources(build_vault, seasons=[2025])
    frame = build_games_frame(sources)

    row = frame.filter(frame["game_id"] == 500001).row(0, named=True)
    assert row["closing_spread"] == pytest.approx(-3.5)
    assert row["spread_provider"] == "consensus"
    assert row["pregame_x"] == pytest.approx(-3.5)


def test_closing_spread_falls_back_when_no_consensus_quoted(build_vault: DataPaths) -> None:
    sources = load_all_sources(build_vault, seasons=[2025])
    frame = build_games_frame(sources)

    row = frame.filter(frame["game_id"] == 500002).row(0, named=True)
    assert row["closing_spread"] == pytest.approx(-6.5)
    assert row["spread_provider"] == "ExampleBook"
    assert row["pregame_x"] == pytest.approx(-6.5)


def test_game_with_no_line_has_null_spread_provider_and_pregame_x(
    build_vault: DataPaths,
) -> None:
    sources = load_all_sources(build_vault, seasons=[2025])
    frame = build_games_frame(sources)

    row = frame.filter(frame["game_id"] == 500008).row(0, named=True)
    assert row["closing_spread"] is None
    assert row["spread_provider"] is None
    assert row["pregame_x"] is None


# -- Rank preference and postseason rule ---------------------------------------------------


def test_poll_preference_constant_is_committee_then_ap() -> None:
    assert POLL_PREFERENCE == ("Playoff Committee Rankings", "AP Top 25")


def test_rank_uses_ap_when_no_committee_poll_exists_that_week(build_vault: DataPaths) -> None:
    sources = load_all_sources(build_vault, seasons=[2025])
    frame = build_games_frame(sources)

    row = frame.filter(frame["game_id"] == 500001).row(0, named=True)  # week 6
    assert row["home_rank"] == 3
    assert row["away_rank"] == 8
    assert row["rank_poll"] == "AP Top 25"


def test_rank_prefers_committee_poll_once_it_exists(build_vault: DataPaths) -> None:
    sources = load_all_sources(build_vault, seasons=[2025])
    frame = build_games_frame(sources)

    row = frame.filter(frame["game_id"] == 500005).row(0, named=True)  # week 10
    assert row["home_rank"] == 7
    assert row["away_rank"] == 11
    assert row["rank_poll"] == "Playoff Committee Rankings"

    row2 = frame.filter(frame["game_id"] == 500002).row(0, named=True)  # week 14
    assert row2["home_rank"] == 5
    assert row2["away_rank"] == 1
    assert row2["rank_poll"] == "Playoff Committee Rankings"


def test_unranked_team_gets_null_rank(build_vault: DataPaths) -> None:
    sources = load_all_sources(build_vault, seasons=[2025])
    frame = build_games_frame(sources)

    row = frame.filter(frame["game_id"] == 500003).row(0, named=True)  # week 1, unranked pair
    assert row["home_rank"] is None
    assert row["away_rank"] is None


def test_postseason_game_uses_latest_regular_week_not_the_final_poll(
    build_vault: DataPaths,
) -> None:
    sources = load_all_sources(build_vault, seasons=[2025])
    frame = build_games_frame(sources)

    row = frame.filter(frame["game_id"] == 500007).row(0, named=True)  # postseason
    # week 15's Playoff Committee Rankings (2/4), never the postseason
    # "final" AP poll's (1/7) for the same two teams.
    assert row["home_rank"] == 2
    assert row["away_rank"] == 4
    assert row["rank_poll"] == "Playoff Committee Rankings"


# -- game_type / playoff_round (D-17) ------------------------------------------------------


def test_regular_season_game_is_game_type_regular() -> None:
    game = _game(season_type="regular")
    sources = [_sources(games=[game])]

    frame = build_games_frame(sources)

    row = frame.row(0, named=True)
    assert row["game_type"] == "regular"
    assert row["playoff_round"] is None


def test_non_cfp_postseason_game_is_game_type_bowl() -> None:
    game = _game(season_type="postseason", is_cfp=False)
    sources = [_sources(games=[game])]

    frame = build_games_frame(sources)

    row = frame.row(0, named=True)
    assert row["game_type"] == "bowl"
    assert row["playoff_round"] is None


@pytest.mark.parametrize(
    "round_value", ["first_round", "quarterfinal", "semifinal", "championship"]
)
def test_cfp_game_is_game_type_playoff_with_round(round_value: str) -> None:
    game = _game(season_type="postseason", is_cfp=True, playoff_round=round_value)
    sources = [_sources(games=[game])]

    frame = build_games_frame(sources)

    row = frame.row(0, named=True)
    assert row["game_type"] == "playoff"
    assert row["playoff_round"] == round_value


def test_cfp_game_with_unknown_round_gives_null_playoff_round() -> None:
    game = _game(season_type="postseason", is_cfp=True, playoff_round="round_of_64")
    sources = [_sources(games=[game])]

    frame = build_games_frame(sources)

    row = frame.row(0, named=True)
    assert row["game_type"] == "playoff"
    assert row["playoff_round"] is None


# -- date_et / kickoff_et -----------------------------------------------------------------


def test_date_et_crosses_the_utc_day_boundary(build_vault: DataPaths) -> None:
    sources = load_all_sources(build_vault, seasons=[2025])
    frame = build_games_frame(sources)

    row = frame.filter(frame["game_id"] == 500007).row(0, named=True)
    # startDate 2026-01-20T00:30:00Z is 2026-01-19T19:30:00-05:00 in ET.
    assert str(row["date_et"]) == "2026-01-19"
    assert row["kickoff_et"] is not None
    assert row["kickoff_et"].startswith("2026-01-19T19:30:00")


def test_kickoff_et_is_null_when_start_time_tbd() -> None:
    game = _game(start_time_tbd=True)
    sources = [_sources(games=[game])]

    frame = build_games_frame(sources)

    row = frame.row(0, named=True)
    assert row["kickoff_et"] is None
    assert row["date_et"] is not None


# -- Schema, sort, determinism --------------------------------------------------------------


def test_frame_has_exactly_the_games_schema_columns_and_dtypes(build_vault: DataPaths) -> None:
    sources = load_all_sources(build_vault, seasons=[2025])
    frame = build_games_frame(sources)

    assert frame.columns == list(GAMES_SCHEMA.keys())
    for column, dtype in GAMES_SCHEMA.items():
        assert frame.schema[column] == dtype


def test_frame_is_sorted_by_game_id(build_vault: DataPaths) -> None:
    sources = load_all_sources(build_vault, seasons=[2025])
    frame = build_games_frame(sources)

    ids = frame["game_id"].to_list()
    assert ids == sorted(ids)


def test_two_builds_from_the_same_sources_are_equal(build_vault: DataPaths) -> None:
    sources = load_all_sources(build_vault, seasons=[2025])

    frame_a = build_games_frame(sources)
    frame_b = build_games_frame(sources)

    assert frame_a.equals(frame_b)


# -- rank_alignment ------------------------------------------------------------------------


def test_rank_alignment_counts_agreement_only_where_506_printed_a_rank() -> None:
    game_a = _game(id=1, week=5, home_team="Home Team", away_team="Away Team")
    listing_a = _listing(home_rank=None, away_rank=5)  # only the away side is printed
    rankings_a = CfbdPollWeek(
        season=2099,
        season_type="regular",
        week=5,  # offset 0 lookup
        polls=[
            CfbdPoll(
                poll="AP Top 25",
                ranks=[CfbdRank(rank=5, school="Away Team", conference=None)],
            )
        ],
    )

    game_b = _game(
        id=2,
        week=6,
        home_team="Home Team",
        away_team="Away Team",
        start_date=datetime(2099, 10, 11, 16, 0, tzinfo=UTC),
    )
    listing_b = _listing(
        date_et=to_et_date(datetime(2099, 10, 11, 16, 0, tzinfo=UTC)),
        home_rank=9,  # disagrees with CFBD's rank 2 below
        away_rank=None,
    )
    rankings_b = CfbdPollWeek(
        season=2099,
        season_type="regular",
        week=6,
        polls=[
            CfbdPoll(
                poll="AP Top 25",
                ranks=[CfbdRank(rank=2, school="Home Team", conference=None)],
            )
        ],
    )

    sources = [
        _sources(
            games=[game_a, game_b],
            listings=[listing_a, listing_b],
            rankings=[rankings_a, rankings_b],
        )
    ]
    frame = build_games_frame(sources)

    result = rank_alignment(sources, frame, offsets=(0, -1))

    # offset 0: game_a's away rank (5 == 5) agrees; game_b's home rank
    # (9 != 2) is compared but disagrees.
    assert result[0] == (1, 2)
    # offset -1 looks at week 4 for game_a (no rankings there, nothing
    # compared) and week 5 for game_b -- which happens to be game_a's own
    # week, ranking "Away Team" but not "Home Team", so game_b's printed
    # home_rank (9) is compared against an unranked lookup and disagrees.
    assert result[-1] == (0, 1)


def test_rank_week_offset_is_zero_per_the_real_vault_analysis() -> None:
    assert RANK_WEEK_OFFSET == 0
