"""Tests for the CFBD v2 JSON parsers over synthetic fixtures.

All fixtures under tests/fixtures/cfbd/ are synthetic: invented teams,
venues, and numbers, never copied from a real CFBD response.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from booth_review.errors import ParseError
from booth_review.sources.cfbd.parser import (
    parse_games,
    parse_lines,
    parse_media,
    parse_rankings,
    parse_teams,
    parse_wp_pregame,
)

FIXTURES = Path(__file__).parent / "fixtures" / "cfbd"


def test_parse_games_returns_typed_rows() -> None:
    content = (FIXTURES / "games.json").read_bytes()
    games = parse_games(content)
    assert len(games) == 4
    first = games[0]
    assert first.id == 401520001
    assert first.home_team == "Northfield State"
    assert first.away_team == "Lakeshore Tech"
    assert first.home_classification == "fbs"
    assert first.away_classification == "fbs"


def test_parse_games_start_date_is_aware_utc() -> None:
    content = (FIXTURES / "games.json").read_bytes()
    games = parse_games(content)
    first = games[0]
    assert first.start_date.tzinfo is not None
    assert first.start_date == datetime(2025, 8, 30, 16, 0, 0, tzinfo=UTC)


def test_parse_games_start_date_without_offset_raises() -> None:
    data = json.loads((FIXTURES / "games.json").read_bytes())
    data[0]["startDate"] = "2025-08-30T16:00:00"
    with pytest.raises(ParseError, match="startDate"):
        parse_games(json.dumps(data).encode("utf-8"))


def test_parse_games_null_excitement_index_stays_none() -> None:
    content = (FIXTURES / "games.json").read_bytes()
    games = parse_games(content)
    postseason_game = next(g for g in games if g.season_type == "postseason")
    assert postseason_game.excitement_index is None


def test_parse_games_fbs_vs_fcs_classifications_kept_verbatim() -> None:
    content = (FIXTURES / "games.json").read_bytes()
    games = parse_games(content)
    fbs_fcs_game = next(g for g in games if g.away_classification == "fcs")
    assert fbs_fcs_game.home_classification == "fbs"
    assert fbs_fcs_game.away_classification == "fcs"


def test_parse_games_neutral_site_flag_kept() -> None:
    content = (FIXTURES / "games.json").read_bytes()
    games = parse_games(content)
    assert any(g.neutral_site is True for g in games)


def test_parse_games_notes_kept_verbatim_for_postseason() -> None:
    content = (FIXTURES / "games.json").read_bytes()
    games = parse_games(content)
    postseason_game = next(g for g in games if g.season_type == "postseason")
    assert postseason_game.notes == "Example Championship Bowl"


def test_parse_games_missing_required_key_raises_named_field() -> None:
    data = json.loads((FIXTURES / "games.json").read_bytes())
    del data[0]["homeTeam"]
    with pytest.raises(ParseError, match="homeTeam"):
        parse_games(json.dumps(data).encode("utf-8"))


def test_parse_media_returns_outlet_and_media_type() -> None:
    content = (FIXTURES / "media.json").read_bytes()
    media = parse_media(content)
    assert len(media) == 2
    tv_row = next(m for m in media if m.media_type == "tv")
    assert tv_row.outlet == "Example Cable Network"


def test_parse_lines_one_row_per_provider() -> None:
    content = (FIXTURES / "lines.json").read_bytes()
    lines = parse_lines(content)
    assert len(lines) == 2
    providers = {line.provider for line in lines}
    assert providers == {"ExampleBook", "SecondBook"}
    example_book = next(line for line in lines if line.provider == "ExampleBook")
    assert example_book.spread == -6.5
    assert example_book.spread_open == -7.0
    second_book = next(line for line in lines if line.provider == "SecondBook")
    assert second_book.spread is None


def test_parse_wp_pregame_probability_in_unit_range() -> None:
    content = (FIXTURES / "wp_pregame.json").read_bytes()
    rows = parse_wp_pregame(content)
    assert len(rows) == 2
    assert all(0.0 <= row.home_win_probability <= 1.0 for row in rows)


def test_parse_rankings_poll_names_kept_verbatim() -> None:
    content = (FIXTURES / "rankings.json").read_bytes()
    poll_weeks = parse_rankings(content)
    assert len(poll_weeks) == 1
    poll_names = {poll.poll for poll in poll_weeks[0].polls}
    assert poll_names == {"Example Top 25", "Example Committee Rankings"}
    top_25 = next(p for p in poll_weeks[0].polls if p.poll == "Example Top 25")
    assert top_25.ranks[0].school == "Northfield State"
    assert top_25.ranks[0].rank == 1


def test_parse_teams_returns_typed_rows() -> None:
    content = (FIXTURES / "teams_fbs.json").read_bytes()
    teams = parse_teams(content)
    assert len(teams) == 4
    assert {t.school for t in teams} == {
        "Northfield State",
        "Lakeshore Tech",
        "Riverside Poly",
        "Granite College",
    }
