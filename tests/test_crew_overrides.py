"""Crew override loader, apply post-pass, and gap rows (synthetic data only)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from booth_review.build.crew_overrides import (
    CREW_OVERRIDE_COLUMNS,
    CrewOverride,
    load_crew_overrides,
)
from booth_review.errors import ReferenceTableError

_SENTINEL = "ZZ-sentinel-cell"


def _row(**changes: object) -> dict[str, str]:
    base = {
        "cfbd_game_id": "1001",
        "network_id": "net-a",
        "crew_position": "0",
        "person_id": "p-a",
        "role": "pbp",
        "reason": "no-506-listing",
        "source_kind": "press-release",
        "source_name": "Example Press Room",
        "source_url": "https://example.com/pr/1",
    }
    base.update({key: str(value) for key, value in changes.items()})
    return base


def _write(
    tmp_path: Path, rows: list[dict[str, str]], header: tuple[str, ...] = CREW_OVERRIDE_COLUMNS
) -> Path:
    path = tmp_path / "crew_overrides.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(header), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return tmp_path


def _two_rows() -> list[dict[str, str]]:
    return [_row(), _row(crew_position=1, person_id="p-b", role="analyst")]


def test_columns_are_the_documented_header() -> None:
    assert ",".join(CREW_OVERRIDE_COLUMNS) == (
        "cfbd_game_id,network_id,crew_position,person_id,role,reason,"
        "source_kind,source_name,source_url"
    )


def test_valid_telecast_loads_as_one_override(tmp_path: Path) -> None:
    rows = list(reversed(_two_rows()))  # file order must not matter
    loaded = load_crew_overrides(_write(tmp_path, rows))
    assert loaded == {
        (1001, "net-a"): CrewOverride(
            cfbd_game_id=1001,
            network_id="net-a",
            people=(("p-a", "pbp"), ("p-b", "analyst")),
            reason="no-506-listing",
            source_kind="press-release",
            source_name="Example Press Room",
            source_url="https://example.com/pr/1",
        )
    }


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_crew_overrides(tmp_path) == {}


def test_extra_column_rejected(tmp_path: Path) -> None:
    reference = _write(tmp_path, [], header=(*CREW_OVERRIDE_COLUMNS, "extra"))
    with pytest.raises(ReferenceTableError):
        load_crew_overrides(reference)


def test_reordered_column_rejected(tmp_path: Path) -> None:
    header = (CREW_OVERRIDE_COLUMNS[1], CREW_OVERRIDE_COLUMNS[0], *CREW_OVERRIDE_COLUMNS[2:])
    with pytest.raises(ReferenceTableError):
        load_crew_overrides(_write(tmp_path, [], header=header))


_BAD_CELLS = [
    ("cfbd_game_id", _SENTINEL),
    ("crew_position", _SENTINEL),
    ("crew_position", "-1"),
    ("network_id", f"Bad_{_SENTINEL}"),
    ("person_id", ""),
    ("role", _SENTINEL),
    ("role", "unknown"),
    ("reason", _SENTINEL),
    ("source_kind", _SENTINEL),
    ("source_url", ""),
    ("source_url", f"ftp://{_SENTINEL}"),
    ("source_url", f"https://example.com/{_SENTINEL} x"),
    ("source_name", ""),
    ("source_name", _SENTINEL * 5),
    ("source_name", f"<b>{_SENTINEL}</b>"),
]


@pytest.mark.parametrize(("column", "value"), _BAD_CELLS)
def test_bad_cell_is_rejected_with_file_and_line_only(
    tmp_path: Path, column: str, value: str
) -> None:
    rows = _two_rows()
    rows[1][column] = value
    with pytest.raises(ReferenceTableError) as exc:
        load_crew_overrides(_write(tmp_path, rows))
    message = str(exc.value)
    assert "crew_overrides.csv: line" in message
    assert _SENTINEL not in message


def _sentinel_rows(**second: object) -> list[dict[str, str]]:
    first = _row(source_name=_SENTINEL[:20])
    return [first, _row(crew_position=1, person_id="p-b", role="analyst", **second)]


def test_duplicate_position_rejected(tmp_path: Path) -> None:
    rows = [_row(person_id=_SENTINEL), _row(person_id="p-b")]
    with pytest.raises(ReferenceTableError) as exc:
        load_crew_overrides(_write(tmp_path, rows))
    assert "crew_overrides.csv: line 3" in str(exc.value)
    assert _SENTINEL not in str(exc.value)


def test_same_person_twice_rejected(tmp_path: Path) -> None:
    rows = [_row(person_id=_SENTINEL), _row(crew_position=1, person_id=_SENTINEL, role="analyst")]
    with pytest.raises(ReferenceTableError) as exc:
        load_crew_overrides(_write(tmp_path, rows))
    assert "crew_overrides.csv: line" in str(exc.value)
    assert _SENTINEL not in str(exc.value)


def test_non_contiguous_positions_rejected(tmp_path: Path) -> None:
    rows = [_row(person_id=_SENTINEL), _row(crew_position=2, person_id="p-b", role="analyst")]
    with pytest.raises(ReferenceTableError) as exc:
        load_crew_overrides(_write(tmp_path, rows))
    assert "crew_overrides.csv: line 2" in str(exc.value)
    assert _SENTINEL not in str(exc.value)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("reason", "correction"),
        ("source_kind", "school"),
        ("source_name", f"Other {_SENTINEL}"),
        ("source_url", f"https://example.com/{_SENTINEL}"),
    ],
)
def test_rows_of_one_telecast_must_agree_on_source(tmp_path: Path, column: str, value: str) -> None:
    rows = _two_rows()
    rows[1][column] = value
    with pytest.raises(ReferenceTableError) as exc:
        load_crew_overrides(_write(tmp_path, rows))
    assert "crew_overrides.csv: line" in str(exc.value)
    assert _SENTINEL not in str(exc.value)
