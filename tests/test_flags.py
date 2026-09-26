"""Tests for the flags layer (FLAG-01..04) against the synthetic tables
under tests/fixtures/reference/. Loading the real data/reference/*.csv
tables (Task 2) is covered separately by test_real_reference_tables_load.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from booth_review.errors import ReferenceTableError
from booth_review.flags.era import ERA_COLUMNS, era_check, era_for, load_eras
from booth_review.flags.events import event_flags_for, load_event_flags
from booth_review.flags.excitement import excitement_value
from booth_review.flags.measurement_type import measurement_type
from booth_review.reference import write_reference_csv

FIXTURES = Path(__file__).parent / "fixtures" / "reference"


def test_load_eras_from_fixture() -> None:
    eras = load_eras(FIXTURES)
    assert [e.era_id for e in eras] == [
        "rr-fixture-era-1",
        "rr-fixture-era-2",
        "rr-fixture-era-3",
        "rr-fixture-era-4",
        "rr-fixture-era-5",
    ]
    assert eras[0].start is None
    assert eras[-1].end is None


def test_era_for_ooh_boundary_inclusive_on_start() -> None:
    eras = load_eras(FIXTURES)
    assert era_for(date(2020, 8, 30), eras).era_id == "rr-fixture-era-1"
    assert era_for(date(2020, 8, 31), eras).era_id == "rr-fixture-era-2"


def test_era_for_coviewing_boundary_inclusive_on_start() -> None:
    eras = load_eras(FIXTURES)
    assert era_for(date(2026, 8, 30), eras).era_id == "rr-fixture-era-4"
    assert era_for(date(2026, 8, 31), eras).era_id == "rr-fixture-era-5"


def test_era_check_agree_disagree_not_comparable() -> None:
    eras = load_eras(FIXTURES)
    era = next(e for e in eras if e.era_id == "rr-fixture-era-2")
    rr_id = next(iter(era.rr_era_ids))
    assert era_check(era, rr_id) == "agree"
    assert era_check(era, "some-other-rr-era-id") == "disagree"
    assert era_check(era, None) == "not_comparable"


def _era_row(era_id: str, start: str, end: str) -> dict[str, str]:
    return {
        "era_id": era_id,
        "label": era_id,
        "start_date": start,
        "end_date": end,
        "rr_era_ids": "",
        "source_url": "https://example.com/" + era_id,
        "note": "",
    }


def test_load_eras_rejects_gap(tmp_path: Path) -> None:
    write_reference_csv(
        tmp_path / "measurement_eras.csv",
        ERA_COLUMNS,
        [
            _era_row("era-a", "", "2020-01-01"),
            _era_row("era-b", "2020-01-05", ""),
        ],
    )
    with pytest.raises(ReferenceTableError):
        load_eras(tmp_path)


def test_load_eras_rejects_overlap(tmp_path: Path) -> None:
    write_reference_csv(
        tmp_path / "measurement_eras.csv",
        ERA_COLUMNS,
        [
            _era_row("era-a", "", "2020-01-05"),
            _era_row("era-b", "2020-01-01", ""),
        ],
    )
    with pytest.raises(ReferenceTableError):
        load_eras(tmp_path)


def test_load_eras_rejects_first_era_with_start_date(tmp_path: Path) -> None:
    write_reference_csv(
        tmp_path / "measurement_eras.csv",
        ERA_COLUMNS,
        [_era_row("era-a", "2020-01-01", "")],
    )
    with pytest.raises(ReferenceTableError):
        load_eras(tmp_path)


def test_load_eras_rejects_last_era_with_end_date(tmp_path: Path) -> None:
    write_reference_csv(
        tmp_path / "measurement_eras.csv",
        ERA_COLUMNS,
        [
            _era_row("era-a", "", "2020-01-05"),
            _era_row("era-b", "2020-01-06", "2020-06-01"),
        ],
    )
    with pytest.raises(ReferenceTableError):
        load_eras(tmp_path)


def test_measurement_type_mapping() -> None:
    assert measurement_type("blend") == "nielsen_adobe"
    assert measurement_type("nielsen") == "nielsen"
    assert measurement_type(None) == "unknown"
    assert measurement_type("other") == "unknown"


def test_event_flags_for_matches_window_and_network() -> None:
    flags = load_event_flags(FIXTURES)
    matched = event_flags_for(date(2025, 11, 1), 2025, "net-a", flags)
    assert "fixture-event-1" in matched
    assert "fixture-model-break" in matched


def test_event_flags_for_outside_window_or_network() -> None:
    flags = load_event_flags(FIXTURES)
    assert "fixture-event-1" not in event_flags_for(date(2025, 12, 1), 2025, "net-a", flags)
    assert "fixture-event-1" not in event_flags_for(date(2025, 11, 1), 2025, "net-z", flags)


def test_event_flags_for_model_break_applies_regardless_of_network() -> None:
    flags = load_event_flags(FIXTURES)
    assert event_flags_for(date(2020, 1, 1), 2026, None, flags) == ["fixture-model-break"]
    assert event_flags_for(date(2020, 1, 1), 2024, None, flags) == []


def test_excitement_value_null_passthrough() -> None:
    assert excitement_value(None) is None
    assert excitement_value(0.0) == 0.0
    assert excitement_value(87.5) == 87.5
