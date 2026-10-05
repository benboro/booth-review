"""A rebuild from unchanged inputs is byte-identical (D-02): `generated_at` is
the newest input change from the manifest, never the wall clock. Synthetic data
only.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from test_build_bowls_pipeline import _vault_with_sentinel_note

from booth_review.build.pipeline import input_stamp, run_build
from booth_review.config import DataPaths

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
