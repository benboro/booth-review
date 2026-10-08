"""The venue table the Map's `lookups.venues` derives from.

Display fields only (AGENTS.md Website): name, city, state, country and
coordinates. A venue without coordinates keeps null lat/lon; the site-data
build then ships `place: null` for its games rather than guessing (04.18 D-16).
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

from booth_review.sources.cfbd.parser import CfbdVenue

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
