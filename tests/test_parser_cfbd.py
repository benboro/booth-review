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
    CfbdVenue,
    VenueParse,
    parse_games,
    parse_lines,
    parse_media,
    parse_rankings,
    parse_teams,
    parse_venues,
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


def test_parse_games_is_cfp_and_playoff_round_from_playoff_object() -> None:
    content = (FIXTURES / "games.json").read_bytes()
    games = parse_games(content)
    by_id = {g.id: g for g in games}

    assert by_id[401520004].is_cfp is True
    assert by_id[401520004].playoff_round == "semifinal"
    for game_id in (401520001, 401520002, 401520003):
        assert by_id[game_id].is_cfp is False
        assert by_id[game_id].playoff_round is None


def test_parse_games_no_playoff_key_parses_to_not_cfp() -> None:
    data = json.loads((FIXTURES / "games.json").read_bytes())
    del data[0]["playoff"]
    games = parse_games(json.dumps(data).encode("utf-8"))
    assert games[0].is_cfp is False
    assert games[0].playoff_round is None


def test_parse_games_playoff_missing_round_is_cfp_with_null_round() -> None:
    data = json.loads((FIXTURES / "games.json").read_bytes())
    playoff_row = next(row for row in data if row["id"] == 401520004)
    del playoff_row["playoff"]["round"]
    games = parse_games(json.dumps(data).encode("utf-8"))
    playoff_game = next(g for g in games if g.id == 401520004)
    assert playoff_game.is_cfp is True
    assert playoff_game.playoff_round is None


def test_parse_games_playoff_non_string_round_is_cfp_with_null_round() -> None:
    data = json.loads((FIXTURES / "games.json").read_bytes())
    playoff_row = next(row for row in data if row["id"] == 401520004)
    playoff_row["playoff"]["round"] = 3
    games = parse_games(json.dumps(data).encode("utf-8"))
    playoff_game = next(g for g in games if g.id == 401520004)
    assert playoff_game.is_cfp is True
    assert playoff_game.playoff_round is None


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


# -- venue_id on games and parse_venues (phase 04.18) -----------------------------------


def _games_with_venue_id(value: object | None, *, present: bool = True) -> bytes:
    data = json.loads((FIXTURES / "games.json").read_bytes())
    data[0].pop("venueId", None)
    if present:
        data[0]["venueId"] = value
    return json.dumps(data).encode("utf-8")


def test_parse_games_venue_id_read_from_venue_id_key() -> None:
    games = parse_games(_games_with_venue_id(3001))
    assert games[0].venue_id == 3001


def test_parse_games_venue_id_absent_or_null_is_none() -> None:
    assert parse_games(_games_with_venue_id(None, present=False))[0].venue_id is None
    assert parse_games(_games_with_venue_id(None))[0].venue_id is None


@pytest.mark.parametrize("bad", ["3001", True])
def test_parse_games_venue_id_wrong_type_names_field_not_row(bad: object) -> None:
    with pytest.raises(ParseError, match="venueId") as excinfo:
        parse_games(_games_with_venue_id(bad))
    assert "Northfield State" not in str(excinfo.value)


def _venue_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": 1,
        "name": "Synthetic Field",
        "city": "Lincoln",
        "state": "NE",
        "countryCode": "US",
        "latitude": 40.82,
        "longitude": -96.71,
    }
    row.update(overrides)
    return row


def _venues(*rows: dict[str, object]) -> bytes:
    return json.dumps(list(rows)).encode("utf-8")


def test_parse_venues_top_level_coordinates() -> None:
    assert parse_venues(_venues(_venue_row())) == VenueParse(
        venues=[
            CfbdVenue(
                id=1,
                name="Synthetic Field",
                city="Lincoln",
                state="NE",
                country_code="US",
                latitude=40.82,
                longitude=-96.71,
            )
        ],
        malformed=0,
    )


def test_parse_venues_nested_location_shape() -> None:
    row = _venue_row()
    del row["latitude"], row["longitude"]
    row["location"] = {"x": -96.71, "y": 40.82}
    venue = parse_venues(_venues(row)).venues[0]
    assert venue.latitude == 40.82
    assert venue.longitude == -96.71


def test_parse_venues_no_coordinates_gives_none() -> None:
    row = _venue_row()
    del row["latitude"], row["longitude"]
    venue = parse_venues(_venues(row)).venues[0]
    assert venue.latitude is None
    assert venue.longitude is None


def test_parse_venues_empty_strings_become_none() -> None:
    venue = parse_venues(_venues(_venue_row(city="", state=""))).venues[0]
    assert venue.city is None
    assert venue.state is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"latitude": "40.8"},
        {"longitude": True},
        {"latitude": 91.0},
        {"longitude": -181.0},
        {"city": 5},
        {"id": "1"},
        {"name": 7},
    ],
)
def test_parse_venues_malformed_row_is_skipped_and_counted(
    overrides: dict[str, object],
) -> None:
    good = _venue_row(id=2, name="Good Field")
    result = parse_venues(_venues(_venue_row(**overrides), good))
    assert [v.id for v in result.venues] == [2]
    assert result.malformed == 1


@pytest.mark.parametrize("missing", ["id", "name"])
def test_parse_venues_row_missing_required_field_is_skipped_and_counted(missing: str) -> None:
    row = _venue_row()
    del row[missing]
    result = parse_venues(_venues(row))
    assert result.venues == []
    assert result.malformed == 1


def test_parse_venues_non_list_document_raises() -> None:
    with pytest.raises(ParseError):
        parse_venues(b'{"id": 1}')


def test_parse_venues_non_dict_row_is_counted() -> None:
    result = parse_venues(b"[1]")
    assert result == VenueParse(venues=[], malformed=1)


def test_parse_venues_duplicate_ids_keep_first_and_count_rest() -> None:
    result = parse_venues(
        _venues(
            _venue_row(),
            _venue_row(name="Other Field"),
            _venue_row(name="Third Field"),
        )
    )
    assert [v.name for v in result.venues] == ["Synthetic Field"]
    assert result.malformed == 2
