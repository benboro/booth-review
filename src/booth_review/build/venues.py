"""The venue table the Map's `lookups.venues` derives from.

Display fields only (AGENTS.md Website): name, city, state, country and
coordinates. A venue without coordinates keeps null lat/lon; the site-data
build then ships `place: null` for its games rather than guessing (04.18 D-16).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from booth_review.errors import ReferenceTableError
from booth_review.reference import read_reference_csv_numbered
from booth_review.sources.cfbd.parser import CfbdVenue

VENUE_LOCATION_COLUMNS: tuple[str, ...] = ("venue_id", "lat", "lon", "source_url", "note")

VENUES_SCHEMA: dict[str, pl.DataType] = {
    "venue_id": pl.Int64(),
    "name": pl.String(),
    "city": pl.String(),
    "state": pl.String(),
    "country": pl.String(),
    "lat": pl.Float64(),
    "lon": pl.Float64(),
}


def empty_venues_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=VENUES_SCHEMA)


def venues_frame(venues: Sequence[CfbdVenue]) -> pl.DataFrame:
    """One row per venue, sorted by CFBD venue id."""
    rows = [
        {
            "venue_id": venue.id,
            "name": venue.name,
            "city": venue.city,
            "state": venue.state,
            "country": venue.country_code,
            "lat": venue.latitude,
            "lon": venue.longitude,
        }
        for venue in sorted(venues, key=lambda v: v.id)
    ]
    return pl.DataFrame(rows, schema=VENUES_SCHEMA)


@dataclass(frozen=True)
class VenueLocation:
    venue_id: int
    lat: float
    lon: float
    source_url: str


def load_venue_locations(reference_dir: Path) -> list[VenueLocation]:
    """Read venue_locations.csv (not required): hand-kept coordinates, keyed by
    CFBD venue id, for venues whose CFBD record lists none (04.18 D-16)."""
    path = reference_dir / "venue_locations.csv"
    rows: list[VenueLocation] = []
    seen: set[int] = set()
    for line_no, raw in read_reference_csv_numbered(path, VENUE_LOCATION_COLUMNS, required=False):

        def fail(what: str, line_no: int = line_no) -> ReferenceTableError:
            return ReferenceTableError(f"{path.name}: line {line_no}: {what}")

        try:
            venue_id = int(raw["venue_id"])
        except ValueError:
            raise fail("venue_id must be an integer") from None
        if venue_id in seen:
            raise fail("duplicate venue_id")
        seen.add(venue_id)
        try:
            lat, lon = float(raw["lat"]), float(raw["lon"])
        except ValueError:
            raise fail("lat and lon must be numbers") from None
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise fail("lat or lon is out of range")
        if not raw["source_url"].startswith("https://"):
            raise fail("source_url must be an https URL")
        rows.append(VenueLocation(venue_id, lat, lon, raw["source_url"]))
    return rows


def fill_venue_locations(
    venues: pl.DataFrame, locations: Sequence[VenueLocation]
) -> tuple[pl.DataFrame, int]:
    """Fill coordinates for venues that lack them. A venue that already has both
    coordinates is never changed, and a location for a venue not in the list is
    ignored. Returns the frame and the number of venues filled."""
    by_id = {loc.venue_id: loc for loc in locations}
    filled = 0
    rows = []
    for row in venues.iter_rows(named=True):
        loc = by_id.get(row["venue_id"])
        if loc is not None and (row["lat"] is None or row["lon"] is None):
            row = {**row, "lat": loc.lat, "lon": loc.lon}
            filled += 1
        rows.append(row)
    return pl.DataFrame(rows, schema=VENUES_SCHEMA), filled
