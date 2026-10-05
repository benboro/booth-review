"""Tests for job/gaps506.py: the 2026 506 gap finder (missing/stale weeks).

Uses synthetic CfbdGame instances and a vault_paths vault with synthetic
cached 506 pages and manifest lines -- never real vault content, per
AGENTS.md's "vault is private" rule.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from booth_review.config import DataPaths
from booth_review.job.gaps506 import (
    GAME_LENGTH,
    WEEK_ONE_SPLIT_GAP_DAYS,
    find_506_gaps,
    week_windows,
)
from booth_review.sources.cfbd.parser import CfbdGame
from booth_review.transport.cache import Manifest, ManifestEntry


def _game(**overrides: object) -> CfbdGame:
    defaults: dict[str, object] = {
        "id": 1,
        "season": 2026,
        "week": 1,
        "season_type": "regular",
        "start_date": datetime(2026, 8, 30, 16, 0, tzinfo=UTC),
        "start_time_tbd": False,
        "completed": True,
        "neutral_site": False,
        "conference_game": True,
        "venue": "Stadium",
        "home_id": 1,
        "home_team": "Home",
        "home_classification": "fbs",
        "home_conference": "Conf",
        "home_points": 20,
        "away_id": 2,
        "away_team": "Away",
        "away_classification": "fbs",
        "away_conference": "Conf",
        "away_points": 10,
        "excitement_index": 5.0,
        "notes": None,
    }
    defaults.update(overrides)
    return CfbdGame(**defaults)  # type: ignore[arg-type]


def _nav_page(labels: list[str], season: int = 2026) -> bytes:
    anchors = "".join(
        f'<a href="https://506sports.com/ncaaf.php?yr={season}&wk={label}">wk</a>'
        for label in labels
    )
    return f"<html><body><nav>{anchors}</nav></body></html>".encode()


def _append_manifest(
    vault_paths: DataPaths, week: int, fetched: datetime, saved: datetime | None = None
) -> None:
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    url = f"https://506sports.com/ncaaf.php?yr=2026&wk={week}"
    Manifest(vault_paths.manifest).append(
        ManifestEntry(
            url=url,
            source="sports506",
            season=2026,
            kind="page",
            fetched_at=fetched.strftime(fmt),
            status=200,
            etag=None,
            last_modified=None,
            sha256="x" * 8,
            path=f"sports506/2026/wk-{week:02d}.html",
            bytes=10,
            final_url=url,
            saved_at=saved.strftime(fmt) if saved else None,
        )
    )


# -- week_windows -------------------------------------------------------------------


def test_week_windows_regular_week_two_plus_maps_directly() -> None:
    game = _game(week=2, start_date=datetime(2026, 9, 5, 0, 0, tzinfo=UTC))
    windows = week_windows([game], 2026)
    assert windows["2"] == (game.start_date, game.start_date)


def test_week_windows_postseason_maps_to_b() -> None:
    start = datetime(2027, 1, 10, 0, 30, tzinfo=UTC)
    game = _game(week=20, season_type="postseason", start_date=start)
    windows = week_windows([game], 2026)
    assert "B" in windows
    assert windows["B"] == (game.start_date, game.start_date)


def test_week_windows_week_one_splits_at_largest_gap() -> None:
    early = _game(week=1, start_date=datetime(2026, 8, 27, 0, 0, tzinfo=UTC))
    late1 = _game(week=1, start_date=datetime(2026, 8, 31, 16, 0, tzinfo=UTC))
    late2 = _game(week=1, start_date=datetime(2026, 9, 1, 0, 0, tzinfo=UTC))
    windows = week_windows([early, late1, late2], 2026)
    assert windows["0"] == (early.start_date, early.start_date)
    assert windows["1"] == (late1.start_date, late2.start_date)


def test_week_windows_week_one_no_large_gap_all_label_one() -> None:
    g1 = _game(week=1, start_date=datetime(2026, 8, 29, 12, 0, tzinfo=UTC))
    g2 = _game(week=1, start_date=datetime(2026, 8, 30, 16, 0, tzinfo=UTC))
    windows = week_windows([g1, g2], 2026)
    assert "0" not in windows
    assert windows["1"] == (g1.start_date, g2.start_date)


def test_week_windows_drops_labels_outside_week_labels() -> None:
    game = _game(week=25, start_date=datetime(2026, 12, 1, 0, 0, tzinfo=UTC))
    assert week_windows([game], 2026) == {}


def test_week_windows_ignores_other_seasons() -> None:
    game = _game(week=2, season=2025, start_date=datetime(2025, 9, 5, 0, 0, tzinfo=UTC))
    assert week_windows([game], 2026) == {}


def test_week_one_split_gap_constant_is_four() -> None:
    assert WEEK_ONE_SPLIT_GAP_DAYS == 4


# -- find_506_gaps --------------------------------------------------------------------


def test_find_506_gaps_reports_missing_played_week(vault_paths: DataPaths) -> None:
    kickoff = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
    games = [_game(week=2, start_date=kickoff)]
    now = kickoff + GAME_LENGTH + timedelta(hours=1)

    result = find_506_gaps(vault_paths, 2026, games, now)

    assert result.missing == ["2"]
    assert result.stale == []
    assert result.judged == 1


def test_find_506_gaps_not_yet_played_never_reported(vault_paths: DataPaths) -> None:
    kickoff = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
    games = [_game(week=2, start_date=kickoff)]
    now = kickoff + timedelta(hours=1)

    result = find_506_gaps(vault_paths, 2026, games, now)

    assert result.missing == []
    assert result.stale == []
    assert result.judged == 0


def test_find_506_gaps_boundary_exactly_four_hours_not_yet_played(vault_paths: DataPaths) -> None:
    kickoff = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
    games = [_game(week=2, start_date=kickoff)]
    now = kickoff + GAME_LENGTH  # exactly 4h: "now > last_kickoff + 4h" is false here

    result = find_506_gaps(vault_paths, 2026, games, now)

    assert result.judged == 0


def test_find_506_gaps_reports_stale_cached_before_final_score(vault_paths: DataPaths) -> None:
    kickoff = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
    games = [_game(week=2, start_date=kickoff)]
    played_at = kickoff + GAME_LENGTH

    season_dir = vault_paths.raw / "sports506" / "2026"
    season_dir.mkdir(parents=True)
    (season_dir / "wk-02.html").write_bytes(_nav_page(["2"]))

    entry = ManifestEntry(
        url="https://506sports.com/ncaaf.php?yr=2026&wk=2",
        source="sports506",
        season=2026,
        kind="page",
        fetched_at=(kickoff - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        status=200,
        etag=None,
        last_modified=None,
        sha256="x" * 8,
        path="sports506/2026/wk-02.html",
        bytes=10,
        final_url="https://506sports.com/ncaaf.php?yr=2026&wk=2",
    )
    Manifest(vault_paths.manifest).append(entry)

    now = played_at + timedelta(hours=1)
    result = find_506_gaps(vault_paths, 2026, games, now)

    assert result.missing == []
    assert result.stale == ["2"]
    assert result.judged == 1


def test_find_506_gaps_cached_with_no_manifest_entry_is_not_stale(vault_paths: DataPaths) -> None:
    kickoff = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
    games = [_game(week=2, start_date=kickoff)]

    season_dir = vault_paths.raw / "sports506" / "2026"
    season_dir.mkdir(parents=True)
    (season_dir / "wk-02.html").write_bytes(_nav_page(["2"]))

    now = kickoff + GAME_LENGTH + timedelta(hours=1)
    result = find_506_gaps(vault_paths, 2026, games, now)

    assert result.missing == []
    assert result.stale == []
    assert result.judged == 1


def test_find_506_gaps_reports_fresh_cache_as_neither_missing_nor_stale(
    vault_paths: DataPaths,
) -> None:
    kickoff = datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
    games = [_game(week=2, start_date=kickoff)]
    played_at = kickoff + GAME_LENGTH

    season_dir = vault_paths.raw / "sports506" / "2026"
    season_dir.mkdir(parents=True)
    (season_dir / "wk-02.html").write_bytes(_nav_page(["2"]))

    entry = ManifestEntry(
        url="https://506sports.com/ncaaf.php?yr=2026&wk=2",
        source="sports506",
        season=2026,
        kind="page",
        fetched_at=(played_at + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        status=200,
        etag=None,
        last_modified=None,
        sha256="x" * 8,
        path="sports506/2026/wk-02.html",
        bytes=10,
        final_url="https://506sports.com/ncaaf.php?yr=2026&wk=2",
    )
    Manifest(vault_paths.manifest).append(entry)

    now = played_at + timedelta(hours=2)
    result = find_506_gaps(vault_paths, 2026, games, now)

    assert result.missing == []
    assert result.stale == []
    assert result.judged == 1


def test_find_506_gaps_drops_label_a_later_saved_nav_omits(vault_paths: DataPaths) -> None:
    early = _game(week=1, start_date=datetime(2026, 8, 27, 0, 0, tzinfo=UTC))  # -> "0" after split
    late = _game(week=1, start_date=datetime(2026, 8, 31, 16, 0, tzinfo=UTC))  # -> "1" after split
    games = [early, late]

    season_dir = vault_paths.raw / "sports506" / "2026"
    season_dir.mkdir(parents=True)
    # A different, already-cached week page; its own nav is the season's real
    # week list, which never included a "0" (506 never published one).
    (season_dir / "wk-05.html").write_bytes(_nav_page(["1", "5"]))
    now = late.start_date + GAME_LENGTH + timedelta(hours=1)
    _append_manifest(vault_paths, 5, now - timedelta(minutes=30))

    result = find_506_gaps(vault_paths, 2026, games, now)

    assert result.missing == ["1"]
    assert result.judged == 1  # "0" excluded by nav even though CFBD produced that window


def test_find_506_gaps_no_cached_pages_uses_all_window_labels(vault_paths: DataPaths) -> None:
    early = _game(week=1, start_date=datetime(2026, 8, 27, 0, 0, tzinfo=UTC))
    late = _game(week=1, start_date=datetime(2026, 8, 31, 16, 0, tzinfo=UTC))
    games = [early, late]

    now = late.start_date + GAME_LENGTH + timedelta(hours=1)
    result = find_506_gaps(vault_paths, 2026, games, now)

    assert sorted(result.missing) == ["0", "1"]
    assert result.judged == 2


def test_find_506_gaps_reports_played_week_absent_from_cached_nav(vault_paths: DataPaths) -> None:
    games = [
        _game(week=n, start_date=datetime(2026, 9, 5, 0, 0, tzinfo=UTC) + timedelta(weeks=n - 2))
        for n in (2, 3, 4)
    ]
    season_dir = vault_paths.raw / "sports506" / "2026"
    season_dir.mkdir(parents=True)
    # Saved before week 4 existed: its nav lists only 0-3.
    (season_dir / "wk-02.html").write_bytes(_nav_page(["0", "1", "2", "3"]))
    _append_manifest(vault_paths, 2, datetime(2026, 9, 10, 0, 0, tzinfo=UTC))

    now = games[-1].start_date + GAME_LENGTH + timedelta(hours=1)
    result = find_506_gaps(vault_paths, 2026, games, now)

    assert "4" in result.missing
    assert "3" in result.missing


def test_find_506_gaps_nav_saved_after_play_may_drop_a_label(vault_paths: DataPaths) -> None:
    early = _game(week=1, start_date=datetime(2026, 8, 27, 0, 0, tzinfo=UTC))
    late = _game(week=1, start_date=datetime(2026, 8, 31, 16, 0, tzinfo=UTC))
    season_dir = vault_paths.raw / "sports506" / "2026"
    season_dir.mkdir(parents=True)
    (season_dir / "wk-01.html").write_bytes(_nav_page(["1"]))
    now = late.start_date + GAME_LENGTH + timedelta(days=2)
    _append_manifest(vault_paths, 1, now - timedelta(days=1))

    result = find_506_gaps(vault_paths, 2026, [early, late], now)

    assert "0" not in result.missing
    assert result.missing == []


def test_find_506_gaps_stale_uses_save_time_not_import_time(vault_paths: DataPaths) -> None:
    kickoff = datetime(2026, 10, 3, 0, 0, tzinfo=UTC)
    games = [_game(week=5, start_date=kickoff)]
    played_at = kickoff + GAME_LENGTH
    season_dir = vault_paths.raw / "sports506" / "2026"
    season_dir.mkdir(parents=True)
    (season_dir / "wk-05.html").write_bytes(_nav_page(["5"]))
    _append_manifest(
        vault_paths,
        5,
        fetched=played_at + timedelta(hours=5),
        saved=played_at - timedelta(hours=2),
    )

    result = find_506_gaps(vault_paths, 2026, games, played_at + timedelta(hours=6))

    assert result.stale == ["5"]


def test_find_506_gaps_stale_falls_back_to_fetched_at_without_saved_at(
    vault_paths: DataPaths,
) -> None:
    kickoff = datetime(2026, 10, 3, 0, 0, tzinfo=UTC)
    games = [_game(week=5, start_date=kickoff)]
    played_at = kickoff + GAME_LENGTH
    season_dir = vault_paths.raw / "sports506" / "2026"
    season_dir.mkdir(parents=True)
    (season_dir / "wk-05.html").write_bytes(_nav_page(["5"]))
    _append_manifest(vault_paths, 5, fetched=played_at - timedelta(hours=1))

    result = find_506_gaps(vault_paths, 2026, games, played_at + timedelta(hours=6))

    assert result.stale == ["5"]
