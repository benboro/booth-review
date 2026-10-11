"""Synthetic nflverse schedules CSV parse."""

from __future__ import annotations

from datetime import date

import pytest

from booth_review.errors import ParseError
from booth_review.nfl.schedule import (
    SCHEDULE_REQUIRED_COLUMNS,
    parse_schedules,
    parse_schedules_counted,
)


def _csv(rows: list[dict[str, str]], drop: str | None = None) -> bytes:
    cols = [c for c in SCHEDULE_REQUIRED_COLUMNS if c != drop]
    lines = [",".join(cols)]
    for row in rows:
        lines.append(",".join(row.get(c, "") for c in cols))
    return ("\n".join(lines) + "\n").encode()


def _row(**over: str) -> dict[str, str]:
    base = {
        "game_id": "2024_01_AAA_BBB",
        "season": "2024",
        "game_type": "REG",
        "week": "1",
        "gameday": "2024-09-08",
        "weekday": "Sunday",
        "gametime": "13:00",
        "away_team": "AAA",
        "away_score": "17",
        "home_team": "BBB",
        "home_score": "20",
        "location": "Home",
        "result": "3",
        "overtime": "0",
        "spread_line": "-2.5",
        "stadium_id": "S1",
        "stadium": "Test Field",
    }
    base.update(over)
    return base


def test_parse_types_and_tz() -> None:
    (g,) = parse_schedules(_csv([_row()]))
    assert g.gameday == date(2024, 9, 8)
    assert g.kickoff_et.hour == 13
    assert g.kickoff_et.utcoffset() is not None
    assert g.kickoff_et.tzinfo is not None
    assert g.home_score == 20
    assert g.overtime is False
    assert g.spread_line == -2.5


def test_empty_values_become_none() -> None:
    (g,) = parse_schedules(
        _csv([_row(away_score="", home_score="", result="", spread_line="", overtime="")])
    )
    assert g.away_score is None
    assert g.home_score is None
    assert g.result is None
    assert g.spread_line is None
    assert g.overtime is None


def test_missing_column_names_column_only() -> None:
    with pytest.raises(ParseError, match="spread_line"):
        parse_schedules(_csv([_row()], drop="spread_line"))


def test_season_filter() -> None:
    rows = [_row(), _row(game_id="x", season="2023", gameday="2023-09-10")]
    games = parse_schedules(_csv(rows), seasons=[2023])
    assert [g.season for g in games] == [2023]


def test_bad_time_names_season_and_row_not_value() -> None:
    with pytest.raises(ParseError) as err:
        parse_schedules(_csv([_row(gametime="zz:99")]))
    assert "season 2024 row 2" in str(err.value)
    assert "zz:99" not in str(err.value)


@pytest.mark.parametrize(
    "over",
    [
        {"gametime": ""},
        {"gametime": "NA"},
        {"gametime": "TBD"},
        {"gameday": ""},
        {"gameday": "NA"},
        {"week": ""},
        {"week": "NA"},
    ],
)
def test_unscheduled_row_is_skipped_and_counted_not_fatal(over: dict[str, str]) -> None:
    # WR-04: a TBD late-season or flex row never stops the whole parse.
    rows = [_row(), _row(game_id="2024_18_CCC_DDD", **over), _row(game_id="2024_02_EEE_FFF")]
    games, skipped = parse_schedules_counted(_csv(rows))
    assert [g.game_id for g in games] == ["2024_01_AAA_BBB", "2024_02_EEE_FFF"]
    assert skipped == 1
    assert [g.game_id for g in parse_schedules(_csv(rows))] == [g.game_id for g in games]


def test_unscheduled_row_outside_the_seasons_is_not_counted() -> None:
    rows = [_row(), _row(game_id="x", season="2023", gameday="2023-09-10", gametime="")]
    assert parse_schedules_counted(_csv(rows), seasons=[2024])[1] == 0


def test_structural_problems_still_raise() -> None:
    with pytest.raises(ParseError, match="row 2: season is not a number"):
        parse_schedules(_csv([_row(season="")]))
    with pytest.raises(ParseError, match="week is not a number"):
        parse_schedules(_csv([_row(week="x")]))
