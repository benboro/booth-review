"""A rebuild from unchanged inputs is byte-identical (D-02): `generated_at` is
the newest input change from the manifest, never the wall clock. Synthetic data
only.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

from test_build_bowls_pipeline import _vault_with_sentinel_note

from booth_review.build.pipeline import input_stamp, nfl_input_stamp, run_build
from booth_review.config import DataPaths
from booth_review.nfl.layout import (
    NFL_SOURCES,
    NFLVERSE_SCHEDULES_PATH,
    nfl_506_path,
    nfl_506_url,
    nfl_rr_path,
    nflverse_pbp_assets_page_path,
    nflverse_pbp_path,
    wikipedia_path,
    wikipedia_url,
)
from booth_review.transport.types import Source

_KNOWN_BOWLS = "500007,Zebra Ridge Bowl,Ridge Bowl,true,ridge-bowl\n"


def _write_manifest(paths: DataPaths, entries: list[dict[str, object]]) -> None:
    paths.ledger.mkdir(parents=True, exist_ok=True)
    paths.manifest.write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8"
    )


def _entry(path: str | None, sha: str | None, fetched_at: str) -> dict[str, object]:
    return {"path": path, "sha256": sha, "fetched_at": fetched_at}


def test_no_manifest_gives_the_epoch(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    assert input_stamp(paths) == datetime(1970, 1, 1, tzinfo=UTC)


def test_identical_refresh_does_not_advance_the_stamp(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    _write_manifest(
        paths,
        [
            _entry("raw/p.json", "a", "2026-10-01T10:00:00Z"),
            _entry("raw/p.json", "a", "2026-10-04T10:00:00Z"),
        ],
    )
    assert input_stamp(paths) == datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


def test_changed_content_advances_the_stamp(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    _write_manifest(
        paths,
        [
            _entry("raw/p.json", "a", "2026-10-01T10:00:00Z"),
            _entry("raw/p.json", "a", "2026-10-04T10:00:00Z"),
            _entry("raw/p.json", "b", "2026-10-05T10:00:00Z"),
        ],
    )
    assert input_stamp(paths) == datetime(2026, 10, 5, 10, 0, tzinfo=UTC)


def test_null_path_entries_never_advance_the_stamp(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    _write_manifest(
        paths,
        [
            _entry("raw/p.json", "a", "2026-10-01T10:00:00Z"),
            _entry(None, None, "2026-10-06T10:00:00Z"),
            _entry(None, "z", "2026-10-07T10:00:00Z"),
        ],
    )
    assert input_stamp(paths) == datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


def test_two_builds_write_identical_site_data(git_vault: DataPaths, tmp_path: Path) -> None:
    reference = _vault_with_sentinel_note(git_vault, tmp_path, _KNOWN_BOWLS)
    _write_manifest(git_vault, [_entry("raw/cfbd/games/2025.json", "a", "2026-10-01T10:00:00Z")])
    target = git_vault.vault / "processed" / "site-data.json"
    run_build(git_vault, reference, commit=False, accept_baseline=True)
    first = target.read_bytes()
    run_build(git_vault, reference, commit=False, accept_baseline=True)
    assert target.read_bytes() == first
    assert json.loads(first)["generated_at"] == "2026-10-01T10:00:00+00:00"


def test_second_committed_build_commits_nothing(git_vault: DataPaths, tmp_path: Path) -> None:
    reference = _vault_with_sentinel_note(git_vault, tmp_path, _KNOWN_BOWLS)
    _write_manifest(git_vault, [_entry("raw/cfbd/games/2025.json", "a", "2026-10-01T10:00:00Z")])
    first = run_build(git_vault, reference, commit=True, accept_baseline=True)
    # The first rebuild compares against the baseline the first run recorded, so
    # audit/regression.csv gains its rows once; after that nothing changes.
    run_build(git_vault, reference, commit=True, accept_baseline=False)
    third = run_build(git_vault, reference, commit=True, accept_baseline=False)
    assert first.committed is True
    assert third.committed is False


def test_nfl_entries_do_not_move_the_cfb_stamp(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    _write_manifest(
        paths,
        [
            _entry("ratingsref/telecast/2025/x.json", "a", "2026-10-01T10:00:00Z"),
            _entry("nfl/nflverse/schedules/games.csv", "n", "2026-10-09T10:00:00Z"),
        ],
    )
    assert input_stamp(paths) == datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


def test_nfl_host_robots_entries_do_not_move_the_cfb_stamp(tmp_path: Path) -> None:
    # CR-03: robots.txt copies of NFL-only hosts are NFL inputs; Ratings
    # Reference's robots.txt is shared and stays a CFB input.
    paths = DataPaths(vault=tmp_path / "vault")
    nfl_hosts = (
        "raw.githubusercontent.com",
        "api.github.com",
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
        "en.wikipedia.org",
    )
    entries = [_entry("cfbd/games/2026.json", "a", "2026-10-01T10:00:00Z")]
    entries += [
        _entry(f"_robots/{host}/2026-10-0{day}.txt", "r", f"2026-10-0{day}T10:00:00Z")
        for day, host in enumerate(nfl_hosts, start=4)
    ]
    _write_manifest(paths, entries)
    assert input_stamp(paths) == datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    assert nfl_input_stamp(paths) == datetime(2026, 10, 8, 10, 0, tzinfo=UTC)

    _write_manifest(
        paths,
        [
            *entries,
            _entry("_robots/ratingsreference.com/2026-10-09.txt", "s", "2026-10-09T10:00:00Z"),
        ],
    )
    assert input_stamp(paths) == datetime(2026, 10, 9, 10, 0, tzinfo=UTC)
    assert nfl_input_stamp(paths) == datetime(2026, 10, 8, 10, 0, tzinfo=UTC)


def test_nfl_input_stamp_reads_only_nfl_entries(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    assert nfl_input_stamp(paths) == datetime(1970, 1, 1, tzinfo=UTC)
    _write_manifest(
        paths,
        [
            _entry("ratingsref/telecast/2025/x.json", "a", "2026-10-10T10:00:00Z"),
            _entry("nfl/nflverse/schedules/games.csv", "n", "2026-10-09T10:00:00Z"),
        ],
    )
    assert nfl_input_stamp(paths) == datetime(2026, 10, 9, 10, 0, tzinfo=UTC)


def test_nfl_layout_paths_and_sources() -> None:
    assert NFL_SOURCES == ("nfl_sports506", "nfl_ratingsref", "nfl_nflverse", "nfl_wikipedia")
    assert set(NFL_SOURCES) <= set(get_args(Source))
    assert nfl_506_path(2014, 3) == "nfl/sports506/2014/wk-03.html"
    assert nfl_506_url(2014, 3) == "https://506sports.com/nfl.php?yr=2014&wk=3"
    assert nflverse_pbp_path(2025) == "nfl/nflverse/pbp/play_by_play_2025.parquet"
    assert nflverse_pbp_assets_page_path(2) == "nfl/nflverse/pbp/_assets-p2.json"
    assert nfl_rr_path(2025, "nfl-a-b-2025-09-07") == (
        "nfl/ratingsref/telecast/2025/nfl-a-b-2025-09-07.json"
    )
    assert wikipedia_path(2025) == "nfl/wikipedia/2025.html"
    assert wikipedia_url(2025) == "https://en.wikipedia.org/wiki/2025_NFL_season"
    assert NFLVERSE_SCHEDULES_PATH == "nfl/nflverse/schedules/games.csv"
    assert DataPaths(vault=Path("v")).nfl_raw == Path("v") / "raw" / "nfl"
