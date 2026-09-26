"""Tests for the crosswalk-aware, record-centric matching added to
resolve/games.py (GameIndex, GameMatch, match_listing_to_game,
match_record_to_game) and resolve/overrides.py's loader validation
(JOIN-01/02/08, D-06).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from booth_review.errors import ReferenceTableError
from booth_review.resolve.games import GameIndex, match_listing_to_game, match_record_to_game
from booth_review.resolve.overrides import GameOverride, load_game_overrides
from booth_review.resolve.teams import TeamResolver
from booth_review.sources.cfbd.parser import CfbdGame
from booth_review.sources.ratingsref.parser import RRRecord, RRTelecast
from booth_review.sources.sports506.parser import Listing506
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
    start_et_iso: str,
    home_classification: str | None = "fbs",
    away_classification: str | None = "fbs",
) -> CfbdGame:
    start = datetime.fromisoformat(start_et_iso).astimezone(UTC)
    return CfbdGame(
        id=game_id,
        season=season,
        week=1,
        season_type="regular",
        start_date=start,
        start_time_tbd=False,
        completed=True,
        neutral_site=False,
        conference_game=True,
        venue="Example Field",
        home_id=home_id,
        home_team=home_team,
        home_classification=home_classification,
        home_conference="Example Conference",
        home_points=27,
        away_id=away_id,
        away_team=away_team,
        away_classification=away_classification,
        away_conference="Example Conference",
        away_points=20,
        excitement_index=5.0,
        notes=None,
    )


def _listing(
    *,
    season: int = 2025,
    week_label: str = "1",
    source_row_index: int = 0,
    date_et: date,
    away_raw: str,
    home_raw: str,
    network_raw: str | None = "ECN",
) -> Listing506:
    return Listing506(
        season=season,
        week_label=week_label,
        source_row_index=source_row_index,
        date_et=date_et,
        kickoff_et=None,
        away_raw=away_raw,
        away_rank=None,
        home_raw=home_raw,
        home_rank=None,
        neutral=False,
        network_raw=network_raw,
        crew_raw="Pat Example, Jordan Sample",
        crew_names=("Pat Example", "Jordan Sample"),
        feed_kind="main",
        game_label=None,
    )


def _record(
    telecast_id: str, *, event_date: str, teams: list[str], networks: list[str]
) -> RRRecord:
    return RRRecord(
        telecast=RRTelecast(
            id=telecast_id,
            event_date=event_date,  # type: ignore[arg-type]
            title=telecast_id,
            networks=networks,
            teams=teams,
            kind="game",
            tier=2,
        ),
        claims=[],
    )


_NORTHFIELD_LAKEVIEW_GAME = _game(
    1,
    season=2025,
    home_id=9201,
    home_team="Northfield",
    away_id=9202,
    away_team="Lakeview",
    start_et_iso="2025-09-13T12:00:00-04:00",
)
_REMATCH_GAME = _game(
    2,
    season=2025,
    home_id=9202,
    home_team="Lakeview",
    away_id=9201,
    away_team="Northfield",
    start_et_iso="2025-11-01T12:00:00-04:00",
)
_TOKEN_OVERLAP_GAME = _game(
    3,
    season=2025,
    home_id=9203,
    home_team="Cedarhollow",
    away_id=9204,
    away_team="Boulderpass",
    start_et_iso="2025-09-06T12:00:00-04:00",
)
_AMBIGUOUS_GAME_A = _game(
    5,
    season=2025,
    home_id=9207,
    home_team="Sample Prep",
    away_id=9208,
    away_team="Example Falcons",
    start_et_iso="2025-09-06T12:00:00-04:00",
)
_AMBIGUOUS_GAME_B = _game(
    6,
    season=2025,
    home_id=9209,
    home_team="Sample Vale",
    away_id=9210,
    away_team="Example Ridge",
    start_et_iso="2025-09-06T12:00:00-04:00",
)


def _index(*games: CfbdGame) -> GameIndex:
    return GameIndex(list(games))


def _resolver(*games: CfbdGame) -> TeamResolver:
    by_season: dict[int, list[CfbdGame]] = {}
    for game in games:
        by_season.setdefault(game.season, []).append(game)
    return TeamResolver(by_season, [])


# -- match_listing_to_game tiers ------------------------------------------------------------


def test_match_listing_to_game_exact() -> None:
    index = _index(_NORTHFIELD_LAKEVIEW_GAME)
    resolver = _resolver(_NORTHFIELD_LAKEVIEW_GAME)
    listing = _listing(date_et=date(2025, 9, 13), away_raw="Lakeview", home_raw="Northfield")
    result = match_listing_to_game(listing, index, resolver, {})
    assert result.confidence == "exact"
    assert result.game is _NORTHFIELD_LAKEVIEW_GAME
    assert result.source == "auto"
    assert result.excluded is False
    assert result.home_resolved.method == "direct"


def test_match_listing_to_game_date_shift() -> None:
    index = _index(_NORTHFIELD_LAKEVIEW_GAME)
    resolver = _resolver(_NORTHFIELD_LAKEVIEW_GAME)
    listing = _listing(date_et=date(2025, 9, 14), away_raw="Lakeview", home_raw="Northfield")
    result = match_listing_to_game(listing, index, resolver, {})
    assert result.confidence == "date-shift"
    assert result.game is _NORTHFIELD_LAKEVIEW_GAME


def test_match_listing_to_game_rematch_picks_the_right_date() -> None:
    index = _index(_NORTHFIELD_LAKEVIEW_GAME, _REMATCH_GAME)
    resolver = _resolver(_NORTHFIELD_LAKEVIEW_GAME, _REMATCH_GAME)
    listing = _listing(date_et=date(2025, 11, 1), away_raw="Northfield", home_raw="Lakeview")
    result = match_listing_to_game(listing, index, resolver, {})
    assert result.confidence == "exact"
    assert result.game is _REMATCH_GAME


def test_match_listing_to_game_none_when_resolved_pair_not_indexed() -> None:
    index = _index(_NORTHFIELD_LAKEVIEW_GAME)
    resolver = _resolver(_NORTHFIELD_LAKEVIEW_GAME)
    listing = _listing(date_et=date(2025, 9, 13), away_raw="Northfield", home_raw="Northfield")
    result = match_listing_to_game(listing, index, resolver, {})
    assert result.confidence == "none"
    assert result.game is None


def test_match_listing_to_game_partial_only_when_a_team_is_unresolved() -> None:
    index = _index(_TOKEN_OVERLAP_GAME)
    resolver = _resolver(_TOKEN_OVERLAP_GAME)
    listing = _listing(
        date_et=date(2025, 9, 6), away_raw="Boulderpass Tech", home_raw="Cedarhollow Prep"
    )
    result = match_listing_to_game(listing, index, resolver, {})
    assert result.home_resolved.method == "unresolved"
    assert result.confidence == "partial"
    assert result.game is _TOKEN_OVERLAP_GAME


def test_match_listing_to_game_ambiguous_when_several_games_qualify() -> None:
    index = _index(_AMBIGUOUS_GAME_A, _AMBIGUOUS_GAME_B)
    resolver = _resolver(_AMBIGUOUS_GAME_A, _AMBIGUOUS_GAME_B)
    listing = _listing(date_et=date(2025, 9, 6), away_raw="Example", home_raw="Sample")
    result = match_listing_to_game(listing, index, resolver, {})
    assert result.confidence == "ambiguous"
    assert result.game is None


def test_match_listing_to_game_none_when_nothing_is_nearby() -> None:
    index = _index(_NORTHFIELD_LAKEVIEW_GAME)
    resolver = _resolver(_NORTHFIELD_LAKEVIEW_GAME)
    listing = _listing(date_et=date(2025, 1, 1), away_raw="Zzyzx", home_raw="Qanat")
    result = match_listing_to_game(listing, index, resolver, {})
    assert result.confidence == "none"
    assert result.game is None


# -- match_record_to_game tiers --------------------------------------------------------------


def test_match_record_to_game_exact() -> None:
    index = _index(_NORTHFIELD_LAKEVIEW_GAME)
    resolver = _resolver(_NORTHFIELD_LAKEVIEW_GAME)
    record = _record(
        "cfb-northfield-lakeview-2025-09-13",
        event_date="2025-09-13",
        teams=["cfb-northfield", "cfb-lakeview"],
        networks=["ESPN"],
    )
    result = match_record_to_game(record, index, resolver, {})
    assert result.confidence == "exact"
    assert result.game is _NORTHFIELD_LAKEVIEW_GAME


def test_match_record_to_game_unresolved_when_teams_count_is_not_two() -> None:
    index = _index(_NORTHFIELD_LAKEVIEW_GAME)
    resolver = _resolver(_NORTHFIELD_LAKEVIEW_GAME)
    record = _record(
        "cfb-megacast-2025-09-13",
        event_date="2025-09-13",
        teams=["cfb-northfield", "cfb-lakeview", "cfb-extra"],
        networks=["ESPN"],
    )
    result = match_record_to_game(record, index, resolver, {})
    assert result.home_resolved.method == "unresolved"
    assert result.away_resolved.method == "unresolved"
    assert result.confidence == "none"


# -- overrides --------------------------------------------------------------------------------


def test_match_listing_to_game_override_match_wins_regardless_of_names() -> None:
    index = _index(_NORTHFIELD_LAKEVIEW_GAME, _REMATCH_GAME)
    resolver = _resolver(_NORTHFIELD_LAKEVIEW_GAME, _REMATCH_GAME)
    listing = _listing(
        week_label="2",
        source_row_index=9,
        date_et=date(2025, 1, 1),
        away_raw="Zzyzx",
        home_raw="Qanat",
    )
    overrides = {
        ("sports506", 2025, "2:9"): GameOverride(
            source="sports506",
            season=2025,
            pointer="2:9",
            action="match",
            cfbd_game_id=_REMATCH_GAME.id,
            reason="wrong-auto-match",
        )
    }
    result = match_listing_to_game(listing, index, resolver, overrides)
    assert result.game is _REMATCH_GAME
    assert result.source == "override"
    assert result.excluded is False


def test_match_listing_to_game_override_exclude() -> None:
    index = _index(_NORTHFIELD_LAKEVIEW_GAME)
    resolver = _resolver(_NORTHFIELD_LAKEVIEW_GAME)
    listing = _listing(
        week_label="3",
        source_row_index=2,
        date_et=date(2025, 9, 13),
        away_raw="Lakeview",
        home_raw="Northfield",
    )
    overrides = {
        ("sports506", 2025, "3:2"): GameOverride(
            source="sports506",
            season=2025,
            pointer="3:2",
            action="exclude",
            cfbd_game_id=None,
            reason="duplicate-listing",
        )
    }
    result = match_listing_to_game(listing, index, resolver, overrides)
    assert result.confidence == "none"
    assert result.excluded is True
    assert result.game is None


def test_match_listing_to_game_override_unknown_game_id_raises() -> None:
    index = _index(_NORTHFIELD_LAKEVIEW_GAME)
    resolver = _resolver(_NORTHFIELD_LAKEVIEW_GAME)
    listing = _listing(
        week_label="4",
        source_row_index=1,
        date_et=date(2025, 9, 13),
        away_raw="Lakeview",
        home_raw="Northfield",
    )
    overrides = {
        ("sports506", 2025, "4:1"): GameOverride(
            source="sports506",
            season=2025,
            pointer="4:1",
            action="match",
            cfbd_game_id=999999,
            reason="wrong-auto-match",
        )
    }
    with pytest.raises(ReferenceTableError):
        match_listing_to_game(listing, index, resolver, overrides)


def test_load_game_overrides_reads_the_fixture() -> None:
    overrides = load_game_overrides(FIXTURES)
    assert ("ratingsref", 2025, "cfb-boulderpass-cedarhollow-2025-08-30") in overrides
    assert ("sports506", 2025, "1:6") in overrides


def test_load_game_overrides_rejects_bad_reason(tmp_path: Path) -> None:
    atomic_write_bytes(
        tmp_path / "game_overrides.csv",
        b"source,season,pointer,action,cfbd_game_id,reason\n"
        b"sports506,2025,1:1,exclude,,not-a-real-reason\n",
    )
    with pytest.raises(ReferenceTableError):
        load_game_overrides(tmp_path)


def test_load_game_overrides_rejects_malformed_pointer(tmp_path: Path) -> None:
    atomic_write_bytes(
        tmp_path / "game_overrides.csv",
        b"source,season,pointer,action,cfbd_game_id,reason\n"
        b"sports506,2025,not-a-pointer,exclude,,other\n",
    )
    with pytest.raises(ReferenceTableError):
        load_game_overrides(tmp_path)


def test_load_game_overrides_rejects_match_without_game_id(tmp_path: Path) -> None:
    atomic_write_bytes(
        tmp_path / "game_overrides.csv",
        b"source,season,pointer,action,cfbd_game_id,reason\nsports506,2025,1:1,match,,other\n",
    )
    with pytest.raises(ReferenceTableError):
        load_game_overrides(tmp_path)


def test_load_game_overrides_rejects_duplicate_key(tmp_path: Path) -> None:
    atomic_write_bytes(
        tmp_path / "game_overrides.csv",
        b"source,season,pointer,action,cfbd_game_id,reason\n"
        b"sports506,2025,1:1,exclude,,other\n"
        b"sports506,2025,1:1,exclude,,other\n",
    )
    with pytest.raises(ReferenceTableError):
        load_game_overrides(tmp_path)
