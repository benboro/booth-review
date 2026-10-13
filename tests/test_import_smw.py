"""Offline tests for `booth-review import smw` (04.19 D-04), on synthetic data only."""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from smw_helpers import CHARTS, TINY_PNG, build_season, reconcile

from booth_review.cli import main
from booth_review.errors import FrozenSeasonError
from booth_review.sources.smw.importer import SmwImporter
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient

SAVED = 1_700_000_000
SAVED_ISO = datetime.fromtimestamp(SAVED, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _importer(paths, mock_transport_factory) -> SmwImporter:
    handle = mock_transport_factory({})
    client = PoliteClient(transport=handle.transport, clock=lambda: 0.0, sleep=lambda _s: None)
    return SmwImporter(RawCache(paths, client), paths)


def _stamp(folder: Path) -> None:
    for path in [p for p in folder.rglob("*") if p.is_file()]:
        os.utime(path, (SAVED, SAVED))


def _manifest(paths) -> list[dict]:
    if not paths.manifest.is_file():
        return []
    return [json.loads(x) for x in paths.manifest.read_text(encoding="utf-8").splitlines()]


def _written(paths) -> list[Path]:
    root = paths.raw / "smw"
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


def test_imports_every_file_with_manual_provenance(git_vault, mock_transport_factory, tmp_path):
    paths = git_vault
    folder = build_season(tmp_path / "in")
    _stamp(folder)
    result = _importer(paths, mock_transport_factory).run(2022, incoming_dir=folder)

    assert not result.has_problems
    # page + 3 charts + chart_order + 3 pass-a + 3 pass-b + diff + rows
    assert len(result.imported) == 1 + 3 + 1 + 3 + 3 + 2
    dest = paths.raw / "smw" / "2022"
    assert (dest / "season-page.html").is_file()
    assert (dest / "charts" / "week5cfb.png").read_bytes() == TINY_PNG
    assert (dest / "chart_order.csv").is_file()
    assert (dest / "transcription" / "pass-a" / "week5cfb.csv").is_file()
    assert (dest / "transcription" / "rows.csv").is_file()

    entries = _manifest(paths)
    assert len(entries) == len(result.imported)
    for entry in entries:
        assert entry["origin"] == "manual"
        assert entry["saved_at"] == SAVED_ISO
        assert entry["source"] == "smw"
        assert entry["season"] == 2022
        assert entry["url"] == entry["final_url"]
        assert entry["url"].startswith(
            "https://www.sportsmediawatch.com/college-football-tv-ratings/"
        )
        assert entry["path"].startswith("smw/2022/")
        assert len(entry["sha256"]) == 64


def test_rerun_skips_identical_and_changed_needs_force(git_vault, mock_transport_factory, tmp_path):
    paths = git_vault
    folder = build_season(tmp_path / "in")
    importer = _importer(paths, mock_transport_factory)
    first = importer.run(2022, incoming_dir=folder)
    again = importer.run(2022, incoming_dir=folder)
    assert again.imported == []
    assert len(again.skipped_existing) == len(first.imported)
    assert not again.has_problems

    build_season(folder, viewers="6.01M")  # consistent re-transcription
    refused = importer.run(2022, incoming_dir=folder)
    assert refused.has_problems
    assert refused.changed_without_force
    assert refused.imported == []
    rows_path = paths.raw / "smw" / "2022" / "transcription" / "rows.csv"
    assert "6.01M" not in rows_path.read_text()

    forced = importer.run(2022, incoming_dir=folder, force=True)
    assert not forced.has_problems
    assert "6.01M" in rows_path.read_text()


def test_chart_without_rows_is_refused(git_vault, mock_transport_factory, tmp_path):
    folder = build_season(tmp_path / "in")
    rows = folder / "transcription" / "rows.csv"
    kept = [x for x in rows.read_text().splitlines(keepends=True) if "week5cfb.png," not in x]
    rows.write_text("".join(kept))
    result = _importer(git_vault, mock_transport_factory).run(2022, incoming_dir=folder)
    assert result.has_problems
    assert result.missing_charts == ["week5cfb.png"]
    assert _written(git_vault) == []


def test_hand_edited_rows_csv_is_refused(git_vault, mock_transport_factory, tmp_path):
    folder = build_season(tmp_path / "in")
    rows = folder / "transcription" / "rows.csv"
    rows.write_text(rows.read_text().replace("5.83M", "9.99M", 1))
    result = _importer(git_vault, mock_transport_factory).run(2022, incoming_dir=folder)
    assert result.problems == ["rows.csv does not match the merge"]
    assert _written(git_vault) == []


def test_stale_diff_csv_is_refused(git_vault, mock_transport_factory, tmp_path):
    folder = build_season(tmp_path / "in")
    (folder / "transcription" / "pass-b" / "week5cfb.csv").write_text(
        (folder / "transcription" / "pass-b" / "week5cfb.csv").read_text().replace("5.83M", "5.38M")
    )
    result = _importer(git_vault, mock_transport_factory).run(2022, incoming_dir=folder)
    assert result.problems == ["diff.csv does not match the passes"]
    assert _written(git_vault) == []


def test_wrong_season_or_missing_page_is_refused(git_vault, mock_transport_factory, tmp_path):
    folder = build_season(tmp_path / "in")
    importer = _importer(git_vault, mock_transport_factory)
    wrong = importer.run(2021, incoming_dir=folder)
    assert wrong.problems == ["season-page.html does not name this season"]
    (folder / "season-page.html").unlink()
    missing = importer.run(2022, incoming_dir=folder)
    assert missing.problems == ["season-page.html is missing"]
    assert _written(git_vault) == []


def test_non_png_is_skipped_invalid(git_vault, mock_transport_factory, tmp_path):
    folder = build_season(tmp_path / "in")
    (folder / "week5cfb.png").write_bytes(b"<html>not an image</html>")
    result = _importer(git_vault, mock_transport_factory).run(2022, incoming_dir=folder)
    assert result.skipped_invalid == ["week5cfb.png"]
    assert result.has_problems
    assert _written(git_vault) == []


def test_unresolved_disagreement_is_refused(git_vault, mock_transport_factory, tmp_path):
    folder = build_season(tmp_path / "in", b_viewers="5.38M")
    assert not (folder / "transcription" / "rows.csv").exists()
    result = _importer(git_vault, mock_transport_factory).run(2022, incoming_dir=folder)
    assert result.has_problems
    assert _written(git_vault) == []


def test_known_disagreements_validated_and_copied(git_vault, mock_transport_factory, tmp_path):
    folder = build_season(tmp_path / "in")
    known = folder / "transcription" / "known_disagreements.csv"
    known.write_text("chart_file,row,explanation\nweek5cfb.png,1,printed figure differs\n")
    importer = _importer(git_vault, mock_transport_factory)
    ok = importer.run(2022, incoming_dir=folder)
    assert not ok.has_problems
    assert "transcription/known_disagreements.csv" in ok.imported

    known.write_text("chart_file,row,explanation\nweek5cfb.png,7,no such row\n")
    bad = importer.run(2022, incoming_dir=folder)
    assert bad.has_problems and bad.imported == []
    known.write_text("chart_file,row,explanation\nweek5cfb.png,1,\n")
    assert importer.run(2022, incoming_dir=folder).has_problems
    known.write_text("chart_file,row,explanation\nweek5cfb.png,1," + "x" * 201 + "\n")
    assert importer.run(2022, incoming_dir=folder).has_problems


def test_frozen_season_refuses(git_vault, mock_transport_factory, tmp_path):
    git_vault.frozen.write_text(json.dumps({"smw": [2022]}), encoding="utf-8")
    folder = build_season(tmp_path / "in")
    with pytest.raises(FrozenSeasonError):
        _importer(git_vault, mock_transport_factory).run(2022, incoming_dir=folder)


def test_cli_import_commits_count_only_and_sends_nothing(
    git_vault, mock_transport_factory, patched_client, tmp_path
):
    paths = git_vault
    handle = mock_transport_factory({})
    patched_client(handle)
    folder = build_season(tmp_path / "in")

    assert main(["import", "smw", "--season", "2022", "--from", str(folder)]) == 0
    assert handle.requests == []

    remote = paths.vault.parent / "remote.git"
    git = ["git", "--git-dir", str(remote)]
    subject = subprocess.run(
        [*git, "log", "-1", "--format=%s"], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert re.match(r"^import: smw 2022 \(imported \d+, skipped \d+\)$", subject)
    touched = subprocess.run(
        [*git, "show", "--name-only", "--format=", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert touched
    assert all(t.startswith("raw/smw/2022/") or t == "ledger/requests.jsonl" for t in touched)
    assert set(CHARTS) <= {Path(t).name for t in touched}


def test_cli_import_refusal_exits_4_and_writes_nothing(
    git_vault, mock_transport_factory, patched_client, tmp_path, capsys
):
    patched_client(mock_transport_factory({}))
    folder = build_season(tmp_path / "in")
    reconcile(folder)
    rows = folder / "transcription" / "rows.csv"
    rows.write_text(rows.read_text().replace("5.83M", "1.00M", 1))
    assert main(["import", "smw", "--season", "2022", "--from", str(folder), "--no-commit"]) == 4
    out = capsys.readouterr().out
    assert "problems 1" in out
    assert "1.00M" not in out
    assert _written(git_vault) == []
