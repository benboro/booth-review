"""Venues frame and the /venues cache loader, on synthetic data only."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from booth_review.build.sources import load_cfbd_venues
from booth_review.build.tables import BuildTables
from booth_review.build.venues import (
    VENUE_LOCATION_COLUMNS,
    VENUES_SCHEMA,
    VenueLocation,
    empty_venues_frame,
    fill_venue_locations,
    load_venue_locations,
    venues_frame,
)
from booth_review.config import DataPaths
from booth_review.errors import ReferenceTableError
from booth_review.sources.cfbd.parser import CfbdVenue


def _venue(venue_id: int, **overrides: object) -> CfbdVenue:
    defaults: dict[str, object] = {
        "id": venue_id,
        "name": f"Test Venue {venue_id}",
        "city": "Testville",
        "state": "TS",
        "country_code": "US",
        "latitude": 40.0,
        "longitude": -100.0,
    }
    defaults.update(overrides)
    return CfbdVenue(**defaults)  # type: ignore[arg-type]


def test_empty_venues_frame_has_exact_schema() -> None:
    assert venues_frame([]).schema == pl.Schema(VENUES_SCHEMA)
    assert empty_venues_frame().height == 0


def test_venues_frame_sorts_and_keeps_nulls() -> None:
    frame = venues_frame(
        [
            _venue(30, state=None, country_code="IE"),
            _venue(10),
            _venue(20, latitude=None, longitude=None),
        ]
    )
    assert frame["venue_id"].to_list() == [10, 20, 30]
    assert frame["lat"].dtype == pl.Float64
    assert frame["lat"].to_list() == [40.0, None, 40.0]
    assert frame["state"].to_list() == ["TS", "TS", None]
    assert frame["country"].to_list() == ["US", "US", "IE"]


def test_load_cfbd_venues_absent_returns_empty(tmp_path: Path) -> None:
    result = load_cfbd_venues(DataPaths(vault=tmp_path / "vault"))
    assert result.venues == []
    assert result.malformed == 0


def test_load_cfbd_venues_parses_cached_file(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    target = paths.raw / "cfbd" / "venues" / "all.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(
        json.dumps(
            [
                {
                    "id": 7,
                    "name": "Test Venue",
                    "city": "Testville",
                    "latitude": 1.0,
                    "longitude": 2.0,
                }
            ]
        ).encode()
    )
    result = load_cfbd_venues(paths)
    assert [v.id for v in result.venues] == [7]
    assert result.malformed == 0


def test_load_cfbd_venues_skips_a_malformed_row_instead_of_aborting(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    target = paths.raw / "cfbd" / "venues" / "all.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(
        json.dumps(
            [
                {"id": 7, "name": "Test Venue", "latitude": 1.0, "longitude": 2.0},
                {"id": 8, "name": "Junk Venue", "latitude": 999.0, "longitude": 2.0},
            ]
        ).encode()
    )
    result = load_cfbd_venues(paths)
    assert [v.id for v in result.venues] == [7]
    assert result.malformed == 1


def test_build_tables_venues_defaults_empty() -> None:
    assert BuildTables.__dataclass_fields__["venues"].default_factory is empty_venues_frame  # type: ignore[attr-defined]


def _locations_csv(tmp_path: Path, *rows: str) -> Path:
    (tmp_path / "venue_locations.csv").write_text(
        "\n".join([",".join(VENUE_LOCATION_COLUMNS), *rows]) + "\n", encoding="utf-8"
    )
    return tmp_path


def test_fill_venue_locations_fills_a_venue_with_no_coordinates() -> None:
    venues = venues_frame([_venue(1, latitude=None, longitude=None), _venue(2)])
    frame, filled = fill_venue_locations(
        venues, [VenueLocation(1, 12.5, -34.5, "https://example.test/v1")]
    )
    assert filled == 1
    assert frame["lat"].to_list() == [12.5, 40.0]
    assert frame["lon"].to_list() == [-34.5, -100.0]


def test_fill_venue_locations_never_overrides_a_cfbd_coordinate() -> None:
    venues = venues_frame([_venue(2)])
    frame, filled = fill_venue_locations(
        venues, [VenueLocation(2, 1.0, 2.0, "https://example.test/v2")]
    )
    assert filled == 0
    assert frame["lat"].to_list() == [40.0]
    assert frame["lon"].to_list() == [-100.0]


def test_fill_venue_locations_ignores_a_venue_not_in_the_list() -> None:
    frame, filled = fill_venue_locations(
        venues_frame([_venue(2)]), [VenueLocation(99, 1.0, 2.0, "https://example.test/v99")]
    )
    assert filled == 0
    assert frame.height == 1


def test_load_venue_locations_reads_negative_coordinates(tmp_path: Path) -> None:
    directory = _locations_csv(tmp_path, "5,10.25,-20.5,https://example.test/v5,note")
    assert load_venue_locations(directory) == [
        VenueLocation(5, 10.25, -20.5, "https://example.test/v5")
    ]


def test_load_venue_locations_absent_file_is_empty(tmp_path: Path) -> None:
    assert load_venue_locations(tmp_path) == []


@pytest.mark.parametrize(
    "row",
    [
        "5,north,-20.5,https://example.test/v5,note",
        "5,95.0,-20.5,https://example.test/v5,note",
        "5,10.0,-20.5,http://example.test/v5,note",
        "x,10.0,-20.5,https://example.test/v5,note",
    ],
)
def test_load_venue_locations_rejects_malformed_rows(tmp_path: Path, row: str) -> None:
    with pytest.raises(ReferenceTableError):
        load_venue_locations(_locations_csv(tmp_path, row))


def test_load_venue_locations_rejects_duplicate_ids(tmp_path: Path) -> None:
    row = "5,10.0,-20.5,https://example.test/v5,note"
    with pytest.raises(ReferenceTableError, match="duplicate"):
        load_venue_locations(_locations_csv(tmp_path, row, row))
