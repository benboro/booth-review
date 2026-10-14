"""Offline tests for the MLB profile of the 506 hand-save importer.

Pages are synthetic (tests/fixtures/mlb/sports506), relabelled in tmp copies.
Every importer is built on a mock transport with zero responses.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from booth_review.sources.sports506.importer import (
    CFB_PROFILE,
    MLB_PROFILE,
    Sports506Importer,
    identify_page,
    inspect_folder,
)
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient

FIX = Path(__file__).parent / "fixtures" / "mlb" / "sports506"


def _page(
    name: str, season: int, *, label: str | None = None, was_label: str | None = None
) -> bytes:
    text = (FIX / name).read_text(encoding="utf-8").replace("2099", str(season))
    if label is not None and was_label is not None:
        text = text.replace(f"wk={was_label}", f"wk={label}").replace(
            f"Week {was_label},", f"Week {label},"
        )
    return text.encode("utf-8")


def _importer(vault_paths, mock_transport_factory):
    handle = mock_transport_factory({})
    client = PoliteClient(transport=handle.transport, clock=lambda: 0.0, sleep=lambda _s: None)
    return Sports506Importer(
        RawCache(vault_paths, client), vault_paths, profile=MLB_PROFILE
    ), handle


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


def test_weekly_page_imports_with_manifest_shape(
    vault_paths, mock_transport_factory, tmp_path
) -> None:
    importer, handle = _importer(vault_paths, mock_transport_factory)
    mtime = 1_700_000_000.0
    _save(tmp_path / "in", "a.html", _page("week_cgame_synthetic.html", 2026), mtime)

    result = importer.run(2026, incoming_dir=tmp_path / "in")

    assert result.imported == ["3"]
    assert handle.requests == []
    assert (vault_paths.raw / "mlb/sports506/2026/wk-03.html").is_file()
    (line,) = _manifest(vault_paths)
    assert line["source"] == "mlb_sports506"
    assert line["url"] == "https://506sports.com/mlb.php?yr=2026&wk=3"
    assert line["origin"] == "manual"
    assert line["saved_at"] == datetime.fromtimestamp(mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_round_pages_import_as_round_labels(vault_paths, mock_transport_factory, tmp_path) -> None:
    importer, _ = _importer(vault_paths, mock_transport_factory)
    folder = tmp_path / "in"
    _save(folder, "a.html", _page("round_cgame_noheader_synthetic.html", 2025))
    _save(folder, "b.html", _page("round_cgame_header_synthetic.html", 2025))

    result = importer.run(2025, incoming_dir=folder)

    assert sorted(result.imported) == ["WC", "WS"]
    assert (vault_paths.raw / "mlb/sports506/2025/wk-WC.html").is_file()
    assert (vault_paths.raw / "mlb/sports506/2025/wk-WS.html").is_file()
    assert result.expected == ["WC", "DS", "CS", "WS"]
    assert result.missing == ["DS", "CS"]


def test_2025_fox_map_page_is_out_of_scope(vault_paths, mock_transport_factory, tmp_path) -> None:
    importer, _ = _importer(vault_paths, mock_transport_factory)
    _save(tmp_path / "in", "m.html", _page("fox_map_synthetic.html", 2025))

    result = importer.run(2025, incoming_dir=tmp_path / "in")

    assert result.out_of_scope == 1
    assert result.unrecognized == 0
    assert result.imported == []
    assert result.counts()["out_of_scope"] == 1


def test_pre_2025_page_rejected_and_nothing_expected(
    vault_paths, mock_transport_factory, tmp_path
) -> None:
    importer, _ = _importer(vault_paths, mock_transport_factory)
    _save(tmp_path / "in", "o.html", _page("round_cgame_header_synthetic.html", 2018))

    result = importer.run(2018, incoming_dir=tmp_path / "in")

    assert result.imported == []
    assert [s.reason for s in result.skipped_invalid] == ["no MLB round pages before 2025"]
    assert result.expected == []
    assert result.missing == []
    assert not (vault_paths.raw / "mlb").exists()


def test_2026_expected_labels_come_from_nav(vault_paths, mock_transport_factory, tmp_path) -> None:
    importer, _ = _importer(vault_paths, mock_transport_factory)
    page = _page("week_cgame_synthetic.html", 2026)
    nav = (
        b'<a href="mlb.php?yr=2026&amp;wk=3">3</a><a href="mlb.php?yr=2026&amp;wk=4">4</a>'
        b'<a href="mlb.php?yr=2026&amp;wk=WS">WS</a>'
    )
    page = re.sub(
        rb'<div id="seasonnav">.*?</div>', b'<div id="seasonnav">' + nav + b"</div>", page
    )
    _save(tmp_path / "in", "a.html", page)

    result = importer.run(2026, incoming_dir=tmp_path / "in")

    assert result.expected_source == "nav"
    assert result.expected == ["3", "4", "WS"]
    assert result.missing == ["4", "WS"]


def test_weekly_page_failing_smoke_is_rejected(
    vault_paths, mock_transport_factory, tmp_path
) -> None:
    importer, _ = _importer(vault_paths, mock_transport_factory)
    page = _page("week_cgame_synthetic.html", 2026)
    # Keep one game block so the layout is cgame but the listing count is too low.
    first = page.index(b'<div id="cgame">')
    second = page.index(b'<div id="cgame">', first + 1)
    thin = page[:second] + b"</article></body></html>"
    _save(tmp_path / "in", "a.html", thin)

    result = importer.run(2026, incoming_dir=tmp_path / "in")

    assert result.imported == []
    (skipped,) = result.skipped_invalid
    assert "listings, need" in skipped.reason


def test_force_replaces_changed_page(vault_paths, mock_transport_factory, tmp_path) -> None:
    importer, _ = _importer(vault_paths, mock_transport_factory)
    folder = tmp_path / "in"
    original = _page("week_cgame_synthetic.html", 2026)
    _save(folder, "a.html", original)
    assert importer.run(2026, incoming_dir=folder).imported == ["3"]

    changed = original.replace(b"</body>", b"<!-- synthetic re-save --></body>")
    _save(folder, "a.html", changed)
    kept = importer.run(2026, incoming_dir=folder)
    assert kept.changed_without_force == ["3"]
    assert kept.imported == []
    assert (vault_paths.raw / "mlb/sports506/2026/wk-03.html").read_bytes() == original

    forced = importer.run(2026, incoming_dir=folder, force=True)
    assert forced.replaced == ["3"]
    assert (vault_paths.raw / "mlb/sports506/2026/wk-03.html").read_bytes() == changed


def test_unsupported_round_label_is_reported_not_written(
    vault_paths, mock_transport_factory, tmp_path
) -> None:
    importer, _ = _importer(vault_paths, mock_transport_factory)
    page = _page("round_cgame_header_synthetic.html", 2025, label="TB", was_label="WS")
    _save(tmp_path / "in", "tb.html", page)

    result = importer.run(2025, incoming_dir=tmp_path / "in")

    assert result.unsupported_pages == ["TB"]
    assert result.counts()["unsupported"] == 1
    assert result.has_problems
    assert result.imported == []
    assert not (vault_paths.raw / "mlb").exists()


def test_canonical_and_title_must_agree(tmp_path) -> None:
    page = _page("round_cgame_header_synthetic.html", 2025).replace(
        b"Week WS, 2025", b"Week CS, 2025"
    )
    assert identify_page(tmp_path / "x.html", page, MLB_PROFILE) is None


def test_inspect_reports_counts_and_writes_nothing(
    vault_paths, mock_transport_factory, tmp_path
) -> None:
    folder = tmp_path / "in"
    _save(folder, "a.html", _page("week_cgame_synthetic.html", 2026))
    _save(folder, "b.html", _page("round_cgame_header_synthetic.html", 2025))
    _save(folder, "c.html", _page("round_cgame_noheader_synthetic.html", 2025))
    _save(folder, "d.html", _page("fox_map_synthetic.html", 2025))
    _save(folder, "e.html", b"<html><body>nothing here</body></html>")

    rows, summary = inspect_folder(MLB_PROFILE, folder)

    assert [r.file_index for r in rows] == [0, 1, 2, 3, 4]
    by_verdict = [r.verdict for r in rows]
    assert by_verdict == [
        "importable",
        "importable",
        "importable",
        "out_of_scope",
        "unrecognized",
    ]
    assert rows[0].layout == "cgame"
    assert rows[0].listings > 0
    assert rows[3].layout == "map"
    assert rows[3].listings == 0
    assert summary["importable"] == 3
    assert summary["season_2025"] == 3
    assert summary["season_2026"] == 1
    assert not vault_paths.manifest.exists() or _manifest(vault_paths) == []
    assert not (vault_paths.raw / "mlb").exists()
    for row in rows:
        assert not hasattr(row, "path")


def test_inspect_other_profiles_not_implemented(tmp_path) -> None:
    with pytest.raises(NotImplementedError):
        inspect_folder(CFB_PROFILE, tmp_path)
