"""Shared synthetic builders for the NFL join tests."""

from __future__ import annotations

from booth_review.nfl.schedule import SCHEDULE_REQUIRED_COLUMNS, NflGame, parse_schedules
from booth_review.sources.sports506.nfl_parser import NflListing506


def schedule_csv(rows: list[dict[str, str]]) -> bytes:
    lines = [",".join(SCHEDULE_REQUIRED_COLUMNS)]
    for row in rows:
        lines.append(",".join(row.get(c, "") for c in SCHEDULE_REQUIRED_COLUMNS))
    return ("\n".join(lines) + "\n").encode()


def sched_row(
    game_id: str, week: int, day: str, away: str, home: str, **over: str
) -> dict[str, str]:
    base = {
        "game_id": game_id,
        "season": "2015",
        "game_type": "REG",
        "week": str(week),
        "gameday": day,
        "weekday": "Sunday",
        "gametime": "13:00",
        "away_team": away,
        "home_team": home,
        "location": "Home",
        "stadium_id": "S1",
        "stadium": "Invented Field",
    }
    base.update(over)
    return base


def games() -> tuple[NflGame, ...]:
    rows = [
        sched_row("g1", 3, "2015-09-27", "HCG", "OTT"),
        sched_row("g2", 3, "2015-09-28", "MOL", "ELK", weekday="Monday", gametime="20:15"),
        sched_row("g3", 4, "2015-10-04", "HCG", "OTT"),
        sched_row("g4", 5, "2015-10-12", "MOL", "OTT", weekday="Monday", gametime="20:15"),
    ]
    return tuple(parse_schedules(schedule_csv(rows)))


def listing(away: str, home: str, network: str = "FOX", *, week: int = 3, idx: int = 0, crew=()):
    return NflListing506(
        season=2015,
        week=week,
        network_raw=network,
        window="early",
        away_raw=away,
        home_raw=home,
        neutral_site=False,
        crew_names=tuple(crew),
        is_national_line=False,
        intl_city=None,
        national_time_et_raw=None,
        source_row_index=idx,
    )
