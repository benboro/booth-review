"""Venues frame and the /venues cache loader, on synthetic data only."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from booth_review.build.sources import load_cfbd_venues
from booth_review.build.tables import BuildTables
from booth_review.build.venues import VENUES_SCHEMA, empty_venues_frame, venues_frame
from booth_review.config import DataPaths
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
    assert load_cfbd_venues(DataPaths(vault=tmp_path / "vault")) == []


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
    venues = load_cfbd_venues(paths)
    assert [v.id for v in venues] == [7]


def test_build_tables_venues_defaults_empty() -> None:
    assert BuildTables.__dataclass_fields__["venues"].default_factory is empty_venues_frame  # type: ignore[attr-defined]
