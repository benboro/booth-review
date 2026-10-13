"""Tests for job/gaps_espnpr.py: the weekly ESPN Press Room hand-save reminder (04.19 D-14).

Uses synthetic CfbdGame instances and a vault_paths vault with synthetic
saved-page stand-ins -- never real vault content or a real ESPN page, per
AGENTS.md's "vault is private" rule. The module never fetches: these tests
run with no client at all.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from booth_review.config import DataPaths
from booth_review.job.gaps_espnpr import espnpr_page_week, find_espnpr_gap, week_spans
from booth_review.sources.cfbd.parser import CfbdGame

ET = ZoneInfo("America/New_York")
_MODULE = Path(__file__).parent.parent / "src" / "booth_review" / "job" / "gaps_espnpr.py"


def _game(week: int, start_et: datetime, **overrides: object) -> CfbdGame:
    fields: dict[str, object] = {
        "id": 1,
        "season": 2026,
        "week": week,
        "season_type": "regular",
        "start_date": start_et.astimezone(UTC),
        "start_time_tbd": False,
        "completed": False,
        "neutral_site": False,
        "conference_game": True,
        "venue": "Stadium",
        "home_id": 1,
        "home_team": "Home",
        "home_classification": "fbs",
        "home_conference": "Conf",
        "home_points": None,
        "away_id": 2,
        "away_team": "Away",
        "away_classification": "fbs",
        "away_conference": "Conf",
        "away_points": None,
        "excitement_index": None,
        "notes": None,
    }
    fields.update(overrides)
    return CfbdGame(**fields)  # type: ignore[arg-type]


def _et(month: int, day: int, hour: int = 12, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=ET)


# A synthetic 2026 slate. CFBD week 1 holds ESPN Week 0 (Sat Aug 29) and Week 1
# (Thu Sep 3 through the Labor Day Monday game, Sep 7); CFBD week N >= 2 is ESPN
# Week N. Weeks 3-6 are left out to make a week with no games; week 7 has a stray
# Sunday game the week before its Saturday slate; week 8 is the last numbered
# week, and one bowl game follows.
GAMES = [
    _game(1, _et(8, 29, 15)),
    _game(1, _et(9, 3, 20)),
    _game(1, _et(9, 5, 12)),
    _game(1, _et(9, 7, 20)),
    _game(2, _et(9, 12, 12)),
    _game(7, _et(10, 11, 15)),
    _game(7, _et(10, 15, 19)),
    _game(7, _et(10, 17, 12)),
    _game(7, _et(10, 17, 22)),
    _game(8, _et(10, 24, 15)),
    _game(1, _et(12, 19, 15), season_type="postseason"),
]


# -- espnpr_page_week ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "label"),
    [
        (_et(10, 14, 10), "7"),  # Wednesday of week 7
        (_et(10, 18, 9), "7"),  # the Sunday after week 7's games, page not yet replaced
        (_et(10, 19, 9), "8"),  # Monday: the page moves on to week 8
        (_et(10, 12, 0), "7"),  # 00:00 ET Monday opens week 7's span
        (_et(10, 25, 23), "8"),  # Sunday night after the final numbered week
        (_et(8, 24, 0), "0"),  # Monday of ESPN Week 0
        (_et(8, 30, 12), "0"),
        (_et(9, 1, 12), "1"),
        (_et(9, 7, 12), "2"),  # Labor Day: week 1's last game, but the page is week 2's
        (_et(9, 10, 12), "2"),
        (_et(10, 11, 18), None),  # week 7's stray Sunday game stays out of week 6's span
        (_et(10, 7, 12), None),
    ],
)
def test_page_week_is_the_week_whose_monday_to_sunday_span_holds_the_run(
    now: datetime, label: str | None
) -> None:
    assert espnpr_page_week(GAMES, 2026, now) == label


@pytest.mark.parametrize(
    "now",
    [
        _et(8, 23, 23),  # before Week 0's Monday
        _et(9, 23, 12),  # a week with no games
        _et(10, 26, 0),  # after the final numbered week's Sunday
        _et(12, 18, 12),  # bowl season has no numbered page
        _et(1, 5, 12, year=2027),
    ],
)
def test_page_week_is_none_outside_the_numbered_weeks(now: datetime) -> None:
    assert espnpr_page_week(GAMES, 2026, now) is None


def test_page_week_ignores_other_seasons_and_needs_games() -> None:
    assert espnpr_page_week(GAMES, 2025, _et(10, 14, 10)) is None
    assert espnpr_page_week([], 2026, _et(10, 14, 10)) is None


def test_page_week_takes_utc_and_et_alike() -> None:
    now = _et(10, 19, 0)
    assert espnpr_page_week(GAMES, 2026, now.astimezone(UTC)) == "8"
    # 03:59 UTC Monday is still Sunday night in ET.
    assert espnpr_page_week(GAMES, 2026, datetime(2026, 10, 19, 3, 59, tzinfo=UTC)) == "7"


# -- find_espnpr_gap -------------------------------------------------------------------


def _save(paths: DataPaths, season: int, name: str) -> None:
    folder = paths.raw / "espnpr" / str(season) / "commentators"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(b"<html>synthetic</html>")


def test_gap_names_the_current_week_when_its_page_is_absent(vault_paths: DataPaths) -> None:
    assert find_espnpr_gap(vault_paths, 2026, GAMES, _et(10, 14, 10)) == "7"


def test_gap_is_none_once_the_current_week_is_saved(vault_paths: DataPaths) -> None:
    _save(vault_paths, 2026, "wk-7.html")
    assert find_espnpr_gap(vault_paths, 2026, GAMES, _et(10, 14, 10)) is None
    # The next Monday the page carries week 8, which is not saved.
    assert find_espnpr_gap(vault_paths, 2026, GAMES, _et(10, 19, 9)) == "8"


def test_gap_only_counts_this_seasons_unpadded_page(vault_paths: DataPaths) -> None:
    _save(vault_paths, 2025, "wk-7.html")
    _save(vault_paths, 2026, "wk-07.html")
    _save(vault_paths, 2026, "wk-6.html")
    assert find_espnpr_gap(vault_paths, 2026, GAMES, _et(10, 14, 10)) == "7"


def test_gap_is_none_outside_the_season(vault_paths: DataPaths) -> None:
    assert find_espnpr_gap(vault_paths, 2026, GAMES, _et(8, 20, 12)) is None
    assert find_espnpr_gap(vault_paths, 2026, GAMES, _et(11, 2, 12)) is None
    assert find_espnpr_gap(vault_paths, 2026, [], _et(10, 14, 10)) is None


def test_gap_reads_without_writing(vault_paths: DataPaths) -> None:
    before = sorted(p.relative_to(vault_paths.vault) for p in vault_paths.vault.rglob("*"))
    find_espnpr_gap(vault_paths, 2026, GAMES, _et(10, 14, 10))
    after = sorted(p.relative_to(vault_paths.vault) for p in vault_paths.vault.rglob("*"))
    assert after == before


def test_module_has_no_fetch_path() -> None:
    source = _MODULE.read_text(encoding="utf-8")
    for banned in ("httpx", "PoliteClient", "requests", "RawCache", "urllib", "socket"):
        assert banned not in source


def test_week_spans_anchor_on_the_saturday_slate() -> None:
    spans = week_spans(GAMES, 2026)
    assert spans == {
        "0": _et(8, 24, 0),
        "1": _et(8, 31, 0),
        "2": _et(9, 7, 0),
        "7": _et(10, 12, 0),
        "8": _et(10, 19, 0),
    }


def test_week_spans_with_no_saturday_game_take_the_busiest_week() -> None:
    games = [
        _game(9, _et(10, 27, 19)),
        _game(9, _et(10, 29, 19)),
        _game(9, _et(11, 2, 19)),  # a lone Monday game the week after
    ]
    assert week_spans(games, 2026) == {"9": _et(10, 26, 0)}
