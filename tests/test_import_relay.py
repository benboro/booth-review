"""Offline tests for the MLB relay crew importer (09-07), synthetic data only."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from booth_review.errors import FrozenSeasonError
from booth_review.mlb.layout import MLB_RELAY_PATH
from booth_review.sources.relay.importer import (
    RELAY_COLUMNS,
    RelayImporter,
    RelayValidationError,
    validate_relay_csv,
)
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient

FIX = Path(__file__).parent / "fixtures" / "mlb" / "relay"


def _valid() -> str:
    return (FIX / "crew_relays_valid.csv").read_text(encoding="utf-8")


def _err(content: str | bytes) -> str:
    data = content.encode("utf-8") if isinstance(content, str) else content
    with pytest.raises(RelayValidationError) as info:
        validate_relay_csv(data)
    return str(info.value)


def _with_cell(column: str, value: str, row: int = 1) -> str:
    lines = _valid().splitlines()
    cells = lines[row].split(",")
    cells[RELAY_COLUMNS.index(column)] = value
    lines[row] = ",".join(cells)
    return "\n".join(lines) + "\n"


def test_validate_accepts_valid_fixture():
    rows = validate_relay_csv((FIX / "crew_relays_valid.csv").read_bytes())
    assert len(rows) == 4
    assert rows[3].game_number == 2


def test_validate_header_mismatch_names_position_only():
    swapped = _valid().replace("away_club,home_club", "home_club,away_club", 1)
    msg = _err(swapped)
    assert "position 3" in msg
    assert "club" not in msg


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("post_url", "http://tamirmoore.blogspot.com/x.html"),
        ("post_url", "https://evil.example.com/x.html"),
        ("press_url", "http://press.example.com/x"),
        ("game_date", "10/03/2026"),
        ("season", "2025"),
        ("game_number", "3"),
        ("pbp", ""),
        ("analyst_1", "=SECRETCELL"),
        ("analyst_1", "@SECRETCELL"),
        ("analyst_1", "+SECRETCELL"),
        ("analyst_1", "-SECRETCELL"),
    ],
)
def test_validate_rejects_bad_cell_without_echoing_it(column, value):
    msg = _err(_with_cell(column, value))
    assert f"line 2: column {column}" in msg
    assert "SECRETCELL" not in msg
    assert "evil" not in msg


def test_validate_bad_url_fixture_rejected():
    assert "post_url" in _err((FIX / "crew_relays_bad_url.csv").read_bytes())


def test_validate_duplicate_names_both_lines():
    assert "lines 2 and 3" in _err((FIX / "crew_relays_duplicate.csv").read_bytes())


def test_validate_size_caps():
    assert "size" in _err(b"x" * 1_000_001)
    header = ",".join(RELAY_COLUMNS)
    body = _valid().splitlines()[1]
    rows = [body.replace("Alpha Foxes", f"Club {i}") for i in range(2001)]
    assert "row cap" in _err(header + "\n" + "\n".join(rows) + "\n")


def _importer(paths, mock_transport_factory) -> RelayImporter:
    handle = mock_transport_factory({})
    client = PoliteClient(transport=handle.transport, clock=lambda: 0.0, sleep=lambda _s: None)
    return RelayImporter(RawCache(paths, client), paths)


def _stage(tmp_path: Path, text: str | None = None) -> Path:
    src = tmp_path / "in"
    src.mkdir(exist_ok=True)
    if text is None:
        shutil.copy(FIX / "crew_relays_valid.csv", src / "relays.csv")
    else:
        (src / "relays.csv").write_text(text, encoding="utf-8", newline="")
    return src


def test_import_writes_bytes_and_manifest(git_vault, mock_transport_factory, tmp_path):
    src = _stage(tmp_path)
    result = _importer(git_vault, mock_transport_factory).run(2026, src=src)
    assert result.counts() == {
        "rows": 4,
        "written": 1,
        "skipped_existing": 0,
        "changed_without_force": 0,
    }
    assert (git_vault.raw / MLB_RELAY_PATH).read_bytes() == (src / "relays.csv").read_bytes()
    entries = [json.loads(x) for x in git_vault.manifest.read_text().splitlines()]
    assert [e["source"] for e in entries] == ["mlb_relay"]
    assert entries[0]["path"] == MLB_RELAY_PATH


def test_rerun_skips_and_changed_needs_force(git_vault, mock_transport_factory, tmp_path):
    src = _stage(tmp_path)
    importer = _importer(git_vault, mock_transport_factory)
    importer.run(2026, src=src)
    assert importer.run(2026, src=src).skipped_existing == 1

    changed = _valid().replace("Sam Rook", "Sam Rooke")
    _stage(tmp_path, changed)
    result = importer.run(2026, src=src)
    assert result.changed_without_force == 1
    assert result.has_problems
    assert b"Rooke" not in (git_vault.raw / MLB_RELAY_PATH).read_bytes()

    forced = importer.run(2026, src=src, force=True)
    assert forced.written == 1
    assert b"Rooke" in (git_vault.raw / MLB_RELAY_PATH).read_bytes()


@pytest.mark.parametrize("count", [0, 2])
def test_zero_or_several_files_is_a_count_error(git_vault, mock_transport_factory, tmp_path, count):
    src = tmp_path / "in"
    src.mkdir()
    for i in range(count):
        shutil.copy(FIX / "crew_relays_valid.csv", src / f"r{i}.csv")
    result = _importer(git_vault, mock_transport_factory).run(2026, src=src)
    assert result.has_problems
    assert result.written == 0


def test_frozen_season_refuses(git_vault, mock_transport_factory, tmp_path):
    git_vault.frozen.write_text(json.dumps({"mlb_relay": [2026]}), encoding="utf-8")
    with pytest.raises(FrozenSeasonError):
        _importer(git_vault, mock_transport_factory).run(2026, src=_stage(tmp_path))
