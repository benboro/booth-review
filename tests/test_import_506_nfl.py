"""Offline tests for the NFL profile of the 506 hand-save importer.

Pages are synthetic (tests/fixtures/nfl/sports506). Every importer is built on a
mock transport with zero responses, so any request would raise immediately.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from booth_review.errors import FrozenSeasonError
from booth_review.sources.sports506.importer import (
    CFB_PROFILE,
    NFL_PROFILE,
    Sports506Importer,
    identify_page,
)
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient

NFL_FIXTURES = Path(__file__).parent / "fixtures" / "nfl" / "sports506"
CFB_FIXTURES = Path(__file__).parent / "fixtures" / "sports506"
_PAGE_2014 = (NFL_FIXTURES / "nfl_2014_wk03_synthetic.html").read_bytes()
_PAGE_2025 = (NFL_FIXTURES / "nfl_2025_wk10_synthetic.html").read_bytes()
_CFB_PAGE = (CFB_FIXTURES / "week_synthetic.html").read_bytes()


def _importer(vault_paths, mock_transport_factory, profile=NFL_PROFILE) -> tuple:
    handle = mock_transport_factory({})
    client = PoliteClient(transport=handle.transport, clock=lambda: 0.0, sleep=lambda _s: None)
    return Sports506Importer(RawCache(vault_paths, client), vault_paths, profile=profile), handle


def _save(folder: Path, name: str, content: bytes, mtime: float | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _manifest(paths) -> list[dict]:
    if not paths.manifest.is_file():
        return []
    return [json.loads(x) for x in paths.manifest.read_text(encoding="utf-8").splitlines()]


def test_imports_nfl_pages_with_manual_origin_and_mtime(
    vault_paths, mock_transport_factory, tmp_path
) -> None:
    importer, handle = _importer(vault_paths, mock_transport_factory)
    folder = tmp_path / "nfl"
    mtime_a, mtime_b = 1_700_000_000.0, 1_750_000_000.0
    _save(folder, "a.html", _PAGE_2014, mtime_a)
    _save(folder, "b.html", _PAGE_2025, mtime_b)

    r14 = importer.run(2014, incoming_dir=folder)
    r25 = importer.run(2025, incoming_dir=folder)

    assert r14.imported == ["3"]
    assert r25.imported == ["10"]
    assert handle.requests == []
    assert (vault_paths.raw / "nfl/sports506/2014/wk-03.html").read_bytes() == _PAGE_2014
    assert (vault_paths.raw / "nfl/sports506/2025/wk-10.html").read_bytes() == _PAGE_2025
    lines = {line["season"]: line for line in _manifest(vault_paths)}
    assert lines[2014]["source"] == "nfl_sports506"
    assert lines[2014]["url"] == "https://506sports.com/nfl.php?yr=2014&wk=3"
    assert lines[2014]["origin"] == "manual"
    assert lines[2014]["saved_at"] == datetime.fromtimestamp(mtime_a, UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    assert lines[2025]["path"] == "nfl/sports506/2025/wk-10.html"


def test_expected_labels_follow_season_length(
    vault_paths, mock_transport_factory, tmp_path
) -> None:
    importer, _ = _importer(vault_paths, mock_transport_factory)
    folder = tmp_path / "nfl"
    _save(folder, "a.html", _PAGE_2014)
    old = importer.run(2014, incoming_dir=folder)
    new = importer.run(2025, incoming_dir=folder)
    assert old.expected == [str(n) for n in range(1, 18)]
    assert new.expected == [str(n) for n in range(1, 19)]
    assert "0" not in old.expected
    assert "B" not in new.expected


def test_week_18_rejected_before_2021(vault_paths, mock_transport_factory, tmp_path) -> None:
    importer, _ = _importer(vault_paths, mock_transport_factory)
    page = _PAGE_2014.replace(b"yr=2014&wk=3", b"yr=2014&wk=18").replace(
        b"Week 3, 2014", b"Week 18, 2014"
    )
    folder = tmp_path / "nfl"
    _save(folder, "a.html", page)
    result = importer.run(2014, incoming_dir=folder)
    assert result.imported == []
    assert result.unrecognized == 1
    assert not (vault_paths.raw / "nfl/sports506/2014/wk-18.html").exists()


def test_leagues_reject_each_others_pages(vault_paths, mock_transport_factory, tmp_path) -> None:
    folder = tmp_path / "mixed"
    cfb_path = _save(folder, "cfb.html", _CFB_PAGE)
    nfl_path = _save(folder, "nfl.html", _PAGE_2025)
    assert identify_page(cfb_path, _CFB_PAGE, NFL_PROFILE) is None
    assert identify_page(nfl_path, _PAGE_2025, CFB_PROFILE) is None
    assert identify_page(nfl_path, _PAGE_2025, NFL_PROFILE) == (2025, "10")

    nfl_importer, _ = _importer(vault_paths, mock_transport_factory)
    result = nfl_importer.run(2025, incoming_dir=folder)
    assert result.imported == ["10"]
    assert result.unrecognized == 1

    cfb_importer, _ = _importer(vault_paths, mock_transport_factory, CFB_PROFILE)
    cfb_result = cfb_importer.run(2025, incoming_dir=folder)
    assert cfb_result.unrecognized == 1
    assert "10" not in cfb_result.imported


def test_nfl_frozen_blocks_but_cfb_frozen_does_not(
    vault_paths, mock_transport_factory, tmp_path
) -> None:
    importer, _ = _importer(vault_paths, mock_transport_factory)
    folder = tmp_path / "nfl"
    _save(folder, "a.html", _PAGE_2025)

    vault_paths.frozen.write_text(json.dumps({"sports506": [2025]}), encoding="utf-8")
    assert importer.run(2025, incoming_dir=folder).imported == ["10"]

    vault_paths.frozen.write_text(json.dumps({"nfl_sports506": [2025]}), encoding="utf-8")
    with pytest.raises(FrozenSeasonError, match="nfl_sports506 2025"):
        importer.run(2025, incoming_dir=tmp_path / "does-not-exist")


def test_failed_smoke_check_rejects_with_reason(
    vault_paths, mock_transport_factory, tmp_path
) -> None:
    importer, handle = _importer(vault_paths, mock_transport_factory)
    thin = _PAGE_2025.split(b"</header>")[0] + b"</header></article></body></html>"
    folder = tmp_path / "nfl"
    _save(folder, "a.html", thin)
    result = importer.run(2025, incoming_dir=folder)
    assert result.imported == []
    assert [item.label for item in result.skipped_invalid] == ["10"]
    assert result.skipped_invalid[0].reason
    assert handle.requests == []
    assert not (vault_paths.raw / "nfl/sports506/2025/wk-10.html").exists()


def test_nfl_default_folder_and_never_reads_root(
    vault_paths, mock_transport_factory, tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _save(tmp_path / "data/incoming/506", "root.html", _PAGE_2025)
    importer, _ = _importer(vault_paths, mock_transport_factory)
    result = importer.run(2025)
    assert result.imported == []
    assert result.root_pages == 0
    _save(tmp_path / "data/incoming/506/nfl", "n.html", _PAGE_2025)
    assert importer.run(2025).imported == ["10"]


def test_imports_2026_card_layout_page(vault_paths, mock_transport_factory, tmp_path) -> None:
    page = (NFL_FIXTURES / "nfl_2026_wk04_synthetic.html").read_bytes()
    importer, handle = _importer(vault_paths, mock_transport_factory)
    folder = tmp_path / "nfl"
    _save(folder, "506 Sports - NFL Maps_ Week 4, 2026.html", page, 1_790_000_000.0)

    assert identify_page(folder / "x.html", page, NFL_PROFILE) == (2026, "4")
    result = importer.run(2026, incoming_dir=folder)

    assert result.imported == ["4"]
    assert handle.requests == []
    assert (vault_paths.raw / "nfl/sports506/2026/wk-04.html").read_bytes() == page
