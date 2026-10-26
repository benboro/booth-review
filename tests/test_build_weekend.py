"""Tests for build/weekend.py: current week, week refs, schedule networks, stamps.

Synthetic games, media rows and manifest lines only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from booth_review.build.weekend import (
    build_schedule_inputs,
    current_label,
    restrict_espnpr_stamps,
    schedule_networks,
    week_labels,
    week_refs,
    weekend_stamps,
)
from booth_review.config import DataPaths
from booth_review.resolve.networks import NetworkRow, NetworkTable
from booth_review.sources.cfbd.parser import CfbdGame, CfbdMedia
from booth_review.transport.cache import Manifest, ManifestEntry

ET = ZoneInfo("America/New_York")
_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _game(game_id: int, week: int, start: datetime, **overrides: object) -> CfbdGame:
    defaults: dict[str, object] = {
        "id": game_id,
        "season": 2026,
        "week": week,
        "season_type": "regular",
        "start_date": start,
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
    defaults.update(overrides)
    return CfbdGame(**defaults)  # type: ignore[arg-type]


def _et(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=ET).astimezone(UTC)


def _season_games() -> list[CfbdGame]:
    """Weeks 8 (Sat Oct 24 plus a Sun 00:30 Hawaii kickoff) and 9 (Sat Oct 31)."""
    return [
        _game(1, 8, _et(10, 24, 12)),
        _game(2, 8, _et(10, 24, 19)),
        _game(3, 8, _et(10, 25, 0, 30)),
        _game(4, 9, _et(10, 31, 12)),
    ]


def test_current_label_hawaii_game_holds_week_open() -> None:
    games = _season_games()
    assert current_label(games, 2026, _et(10, 25, 4, 0)) == "8"


def test_current_label_rolls_over_after_last_kickoff_plus_four_hours() -> None:
    games = _season_games()
    assert current_label(games, 2026, _et(10, 25, 4, 31)) == "9"


def test_current_label_ignores_fcs_only_game_late_in_week() -> None:
    games = [
        *_season_games(),
        _game(
            9,
            8,
            _et(10, 25, 20),
            home_classification="fcs",
            away_classification="fcs",
        ),
    ]
    assert current_label(games, 2026, _et(10, 25, 5, 0)) == "9"


def test_current_label_stale_completed_flag_does_not_hold_the_week() -> None:
    games = _season_games()  # every game has completed False
    assert current_label(games, 2026, _et(10, 26, 12)) == "9"


def test_current_label_completed_true_does_not_close_the_week() -> None:
    games = [_game(1, 8, _et(10, 24, 12), completed=True), _game(3, 8, _et(10, 25, 0, 30))]
    assert current_label(games, 2026, _et(10, 25, 2)) == "8"


def test_current_label_week_zero_inside_its_span() -> None:
    games = [
        _game(1, 1, _et(8, 22, 20)),
        _game(2, 1, _et(8, 29, 12)),
        _game(3, 1, _et(8, 29, 19)),
    ]
    assert current_label(games, 2026, _et(8, 22, 22)) == "0"
    assert current_label(games, 2026, _et(8, 24, 12)) == "1"


def test_current_label_after_last_week_stays_on_it() -> None:
    assert current_label(_season_games(), 2026, _et(12, 15, 12)) == "9"


def test_current_label_before_first_week_is_first() -> None:
    assert current_label(_season_games(), 2026, _et(8, 1, 12)) == "8"


def test_current_label_none_without_numbered_weeks() -> None:
    assert current_label([], 2026, _et(10, 25, 4)) is None


def test_week_refs_numbered_and_sorted_with_monday_to_sunday() -> None:
    refs = week_refs(_season_games(), 2026)
    assert [r["label"] for r in refs] == ["8", "9"]
    assert refs[0] == {"label": "8", "number": 8, "start": "2026-10-19", "end": "2026-10-25"}


def test_week_labels_split_week_one() -> None:
    games = [_game(1, 1, _et(8, 22, 20)), _game(2, 1, _et(8, 29, 12)), _game(3, 2, _et(9, 5, 12))]
    assert week_labels(games, 2026) == {1: "0", 2: "1", 3: "2"}


# -- schedule_networks --------------------------------------------------------------


def _row(variant: str, nid: str, family: str = "x") -> NetworkRow:
    return NetworkRow(variant, nid, nid, family, "cable", "main", None, None, None)


_TABLE = NetworkTable(
    [
        _row("FOX", "fox", "fox"),
        _row("ESPN Radio", "espn-radio", "disney"),
        _row("Peacock", "peacock", "nbc"),
        _row("ESPN", "espn", "disney"),
    ]
)


def _media(game_id: int, media_type: str | None, outlet: str | None) -> CfbdMedia:
    return CfbdMedia(
        id=game_id,
        season=2026,
        week=8,
        season_type="regular",
        start_time=None,
        is_start_time_tbd=False,
        home_team="Home",
        away_team="Away",
        media_type=media_type,
        outlet=outlet,
    )


def test_schedule_networks_tv_wins_and_radio_is_ignored() -> None:
    rows = [_media(1, "tv", "FOX"), _media(1, "radio", "ESPN Radio")]
    result, unmapped = schedule_networks(rows, 2026, _TABLE)
    assert result[1] == ("fox", ["fox"])
    assert unmapped == 0


def test_schedule_networks_radio_only_game_has_no_entry() -> None:
    rows = [_media(2, "radio", "ESPN Radio"), _media(2, "mobile", "ESPN")]
    result, unmapped = schedule_networks(rows, 2026, _TABLE)
    assert 2 not in result
    assert unmapped == 0


def test_schedule_networks_web_fallback_when_no_tv() -> None:
    result, _ = schedule_networks([_media(3, "web", "Peacock")], 2026, _TABLE)
    assert result[3] == ("peacock", ["peacock"])


def test_schedule_networks_unmapped_outlet_is_null_and_counted() -> None:
    result, unmapped = schedule_networks([_media(4, "tv", "Mystery Net")], 2026, _TABLE)
    assert result[4] == (None, [])
    assert unmapped == 1


def test_schedule_unmapped_count_covers_fbs_regular_games_only(vault_paths: DataPaths) -> None:
    # 18-13 F10: the count describes scheduled games, so a non-FBS game's unmapped outlet is
    # never counted.
    games = [
        _game(1, 8, _et(10, 24, 12)),
        _game(2, 8, _et(10, 24, 13), home_classification="fcs", away_classification="fcs"),
    ]
    media = [_media(1, "tv", "Mystery Net"), _media(2, "tv", "Other Mystery Net")]
    inputs = build_schedule_inputs(vault_paths, 2026, games, media, _TABLE)
    assert inputs.networks[1] == (None, [])
    assert inputs.network_unmapped == 1


def test_schedule_networks_honour_a_primary_network_override() -> None:
    # 18-13 F20: the telecast build applies primary_network_overrides.csv by CFBD game id, so
    # the weekend grid does too; an override also names a network for a game with no media.
    rows = [_media(6, "tv", "ESPN"), _media(6, "tv", "FOX"), _media(7, "tv", "Mystery Net")]
    result, unmapped = schedule_networks(
        rows, 2026, _TABLE, primary_overrides={6: "fox", 7: "fox", 8: "peacock"}
    )
    assert result[6][0] == "fox"
    assert result[7][0] == "fox"
    assert result[8] == ("peacock", ["peacock"])
    assert unmapped == 0


def test_schedule_networks_outlets_list_every_mapped_tv_and_web_id() -> None:
    rows = [_media(5, "tv", "ESPN"), _media(5, "web", "Peacock")]
    result, _ = schedule_networks(rows, 2026, _TABLE)
    assert result[5] == ("espn", ["espn", "peacock"])


def test_schedule_networks_other_season_rows_are_skipped() -> None:
    row = _media(6, "tv", "FOX")
    other = CfbdMedia(**{**row.__dict__, "season": 2025})
    result, _ = schedule_networks([other], 2026, _TABLE)
    assert result == {}


# -- weekend_stamps -----------------------------------------------------------------


def _append(paths: DataPaths, path: str, fetched: str, sha: str, saved: str | None = None) -> None:
    Manifest(paths.manifest).append(
        ManifestEntry(
            url=f"https://example.invalid/{path}",
            source="x",
            season=2026,
            kind="page",
            fetched_at=fetched,
            status=200,
            etag=None,
            last_modified=None,
            sha256=sha,
            path=path,
            bytes=1,
            final_url=f"https://example.invalid/{path}",
            saved_at=saved,
        )
    )


def test_weekend_stamps_read_manifest_lines(vault_paths: DataPaths) -> None:
    _append(vault_paths, "cfbd/games/2026.json", "2026-10-20T10:00:00Z", "a")
    _append(vault_paths, "cfbd/media/2026.json", "2026-10-22T10:00:00Z", "b")
    _append(vault_paths, "cfbd/media/2026.json", "2026-10-23T10:00:00Z", "b")  # same bytes
    _append(vault_paths, "sports506/2026/wk-08.html", "2026-10-24T01:00:00Z", "c")
    _append(
        vault_paths,
        "sports506/2026/wk-08.html",
        "2026-10-24T05:00:00Z",
        "d",
        saved="2026-10-24T03:00:00Z",
    )
    _append(vault_paths, "espnpr/2026/commentators/wk-8.html", "2026-10-21T09:00:00Z", "e")
    stamps = weekend_stamps(vault_paths, 2026, ["8", "9"])
    assert stamps["8"] == {
        "schedule_updated_at": "2026-10-22T10:00:00Z",
        "crews_506_saved_at": "2026-10-24T03:00:00Z",
        "crews_espnpr_saved_at": "2026-10-21T09:00:00Z",
        "espnpr_week": "8",
    }
    assert stamps["9"]["crews_506_saved_at"] is None
    assert stamps["9"]["crews_espnpr_saved_at"] is None
    assert stamps["9"]["espnpr_week"] is None


def test_weekend_stamps_empty_manifest_is_all_none(vault_paths: DataPaths) -> None:
    stamps = weekend_stamps(vault_paths, 2026, ["8"])
    assert set(stamps["8"].values()) == {None}


def test_espnpr_stamp_only_for_weeks_where_a_backup_crew_landed(vault_paths: DataPaths) -> None:
    # 18-REVIEW IN-01: a saved commentators page alone must not put ESPN Press Room in the stamp;
    # the segment names the source only when one of its crews fills a shown game that week.
    _append(vault_paths, "espnpr/2026/commentators/wk-8.html", "2026-10-21T09:00:00Z", "e")
    _append(vault_paths, "espnpr/2026/commentators/wk-9.html", "2026-10-28T09:00:00Z", "f")
    stamps = weekend_stamps(vault_paths, 2026, ["8", "9"])
    kept = restrict_espnpr_stamps(stamps, {"9"})
    assert kept["8"]["crews_espnpr_saved_at"] is None
    assert kept["8"]["espnpr_week"] is None
    assert kept["9"]["crews_espnpr_saved_at"] == "2026-10-28T09:00:00Z"
    assert kept["9"]["espnpr_week"] == "9"
    # The other stamps and the input are untouched.
    assert kept["9"]["schedule_updated_at"] is None
    assert stamps["8"]["crews_espnpr_saved_at"] == "2026-10-21T09:00:00Z"
