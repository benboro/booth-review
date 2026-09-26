"""Tests for resolve/teams.py: clean_team_text, TeamResolver's crosswalk
precedence, season ranges, direct matching, and loader validation (JOIN-01).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from booth_review.errors import ReferenceTableError
from booth_review.resolve.teams import (
    TeamCrosswalkRow,
    TeamResolver,
    clean_team_text,
    load_team_crosswalk,
)
from booth_review.sources.cfbd.parser import CfbdGame
from booth_review.transport.cache import atomic_write_bytes

FIXTURES = Path(__file__).parent / "fixtures" / "reference"


def _game(
    game_id: int,
    *,
    season: int,
    home_id: int,
    home_team: str,
    away_id: int,
    away_team: str,
) -> CfbdGame:
    from datetime import UTC, datetime

    return CfbdGame(
        id=game_id,
        season=season,
        week=1,
        season_type="regular",
        start_date=datetime(season, 9, 13, tzinfo=UTC),
        start_time_tbd=False,
        completed=True,
        neutral_site=False,
        conference_game=True,
        venue="Example Field",
        home_id=home_id,
        home_team=home_team,
        home_classification="fbs",
        home_conference="Example Conference",
        home_points=27,
        away_id=away_id,
        away_team=away_team,
        away_classification="fbs",
        away_conference="Example Conference",
        away_points=20,
        excitement_index=5.0,
        notes=None,
    )


# -- clean_team_text ----------------------------------------------------------------------


def test_clean_team_text_strips_trailing_location_note() -> None:
    assert clean_team_text("Lakeview (in Harbor City)", "sports506") == "Lakeview"
    assert clean_team_text("Lakeview (at Harbor City)", "sports506") == "Lakeview"


def test_clean_team_text_no_note_is_unchanged() -> None:
    assert clean_team_text("Lakeview", "sports506") == "Lakeview"


def test_clean_team_text_strips_rr_prefix() -> None:
    assert clean_team_text("cfb-northfield", "ratingsref") == "northfield"


def test_clean_team_text_cfbd_and_any_are_unchanged() -> None:
    assert clean_team_text("Northfield", "cfbd") == "Northfield"
    assert clean_team_text("Northfield", "any") == "Northfield"


# -- load_team_crosswalk --------------------------------------------------------------------


def test_load_team_crosswalk_reads_the_fixture() -> None:
    rows = load_team_crosswalk(FIXTURES)
    assert {row.variant for row in rows} == {"N. Field", "Cedar Hollow"}


def test_load_team_crosswalk_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_team_crosswalk(tmp_path) == []


def test_load_team_crosswalk_rejects_invalid_source(tmp_path: Path) -> None:
    atomic_write_bytes(
        tmp_path / "team_crosswalk.csv",
        b"source,variant,canonical,cfbd_team_id,season_from,season_to,note\n"
        b"bogus,Foo,Bar,1,,,note\n",
    )
    with pytest.raises(ReferenceTableError):
        load_team_crosswalk(tmp_path)


def test_load_team_crosswalk_rejects_note_over_80_chars(tmp_path: Path) -> None:
    long_note = "x" * 81
    atomic_write_bytes(
        tmp_path / "team_crosswalk.csv",
        f"source,variant,canonical,cfbd_team_id,season_from,season_to,note\n"
        f"any,Foo,Bar,1,,,{long_note}\n".encode(),
    )
    with pytest.raises(ReferenceTableError):
        load_team_crosswalk(tmp_path)


def test_load_team_crosswalk_rejects_non_integer_id(tmp_path: Path) -> None:
    atomic_write_bytes(
        tmp_path / "team_crosswalk.csv",
        b"source,variant,canonical,cfbd_team_id,season_from,season_to,note\n"
        b"any,Foo,Bar,not-a-number,,,note\n",
    )
    with pytest.raises(ReferenceTableError):
        load_team_crosswalk(tmp_path)


# -- TeamResolver ---------------------------------------------------------------------------


def test_resolver_crosswalk_row_resolves_variant() -> None:
    games = {
        2025: [
            _game(
                1,
                season=2025,
                home_id=9201,
                home_team="Northfield",
                away_id=9202,
                away_team="Lakeview",
            )
        ]
    }
    rows = [
        TeamCrosswalkRow(
            source="sports506",
            variant="N. Field",
            canonical="Northfield",
            cfbd_team_id=9201,
            season_from=None,
            season_to=None,
            note="506 abbreviation for Northfield",
        )
    ]
    resolver = TeamResolver(games, rows)
    result = resolver.resolve("sports506", "N. Field", 2025)
    assert result.method == "crosswalk"
    assert result.team_id == 9201
    assert result.canonical == "Northfield"


def test_resolver_crosswalk_row_applies_only_inside_season_range() -> None:
    games = {
        2025: [
            _game(
                1,
                season=2025,
                home_id=9203,
                home_team="Cedarhollow",
                away_id=9202,
                away_team="Lakeview",
            )
        ],
        2019: [
            _game(
                2,
                season=2019,
                home_id=9210,
                home_team="Silverlake",
                away_id=9202,
                away_team="Lakeview",
            )
        ],
    }
    rows = [
        TeamCrosswalkRow(
            source="any",
            variant="Cedar Hollow",
            canonical="Cedarhollow",
            cfbd_team_id=9203,
            season_from=2020,
            season_to=2025,
            note="pre-2026 two-word spelling",
        )
    ]
    resolver = TeamResolver(games, rows)

    in_range = resolver.resolve("any", "Cedar Hollow", 2025)
    assert in_range.method == "crosswalk"
    assert in_range.team_id == 9203

    out_of_range = resolver.resolve("any", "Cedar Hollow", 2019)
    assert out_of_range.method == "unresolved"


def test_resolver_source_specific_row_wins_over_any() -> None:
    games = {
        2025: [
            _game(
                1,
                season=2025,
                home_id=9207,
                home_team="Foxhollow",
                away_id=9208,
                away_team="Ironpeak",
            ),
        ]
    }
    rows = [
        TeamCrosswalkRow(
            source="any",
            variant="Ambiguous Name",
            canonical="Foxhollow",
            cfbd_team_id=9207,
            season_from=None,
            season_to=None,
            note="any-source fallback",
        ),
        TeamCrosswalkRow(
            source="sports506",
            variant="Ambiguous Name",
            canonical="Ironpeak",
            cfbd_team_id=9208,
            season_from=None,
            season_to=None,
            note="source-specific wins",
        ),
    ]
    resolver = TeamResolver(games, rows)

    via_sports506 = resolver.resolve("sports506", "Ambiguous Name", 2025)
    assert via_sports506.team_id == 9208

    via_ratingsref = resolver.resolve("ratingsref", "Ambiguous Name", 2025)
    assert via_ratingsref.team_id == 9207


def test_resolver_direct_match_without_crosswalk() -> None:
    games = {
        2025: [
            _game(
                1,
                season=2025,
                home_id=9201,
                home_team="Northfield",
                away_id=9202,
                away_team="Lakeview",
            )
        ]
    }
    resolver = TeamResolver(games, [])
    result = resolver.resolve("cfbd", "Northfield", 2025)
    assert result.method == "direct"
    assert result.team_id == 9201


def test_resolver_unresolved_with_no_match() -> None:
    games = {
        2025: [
            _game(
                1,
                season=2025,
                home_id=9201,
                home_team="Northfield",
                away_id=9202,
                away_team="Lakeview",
            )
        ]
    }
    resolver = TeamResolver(games, [])
    result = resolver.resolve("cfbd", "Nonexistent Team", 2025)
    assert result.method == "unresolved"
    assert result.team_id is None


def test_resolver_unresolved_when_two_teams_share_a_normalized_name() -> None:
    games = {
        2025: [
            _game(
                1,
                season=2025,
                home_id=1,
                home_team="Example State",
                away_id=2,
                away_team="Lakeview",
            ),
            _game(
                2,
                season=2025,
                home_id=3,
                home_team="Example  State",
                away_id=4,
                away_team="Northfield",
            ),
        ]
    }
    resolver = TeamResolver(games, [])
    result = resolver.resolve("cfbd", "Example State", 2025)
    assert result.method == "unresolved"


def test_resolver_raises_when_crosswalk_id_never_appears_in_range() -> None:
    games = {
        2025: [
            _game(
                1,
                season=2025,
                home_id=9201,
                home_team="Northfield",
                away_id=9202,
                away_team="Lakeview",
            )
        ]
    }
    bad_row = TeamCrosswalkRow(
        source="any",
        variant="Ghost Team",
        canonical="Ghost",
        cfbd_team_id=999999,
        season_from=None,
        season_to=None,
        note="never appears in any season's games",
    )
    with pytest.raises(ReferenceTableError):
        TeamResolver(games, [bad_row])


def test_resolver_caches_repeat_lookups() -> None:
    games = {
        2025: [
            _game(
                1,
                season=2025,
                home_id=9201,
                home_team="Northfield",
                away_id=9202,
                away_team="Lakeview",
            )
        ]
    }
    resolver = TeamResolver(games, [])
    first = resolver.resolve("cfbd", "Northfield", 2025)
    second = resolver.resolve("cfbd", "Northfield", 2025)
    assert first == second
