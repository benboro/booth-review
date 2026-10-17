"""MLB output tables and review files, written only to the vault (999.4 D-23).

Tables go to `processed/mlb_*.parquet`, review lists to `interim/review_mlb_*.csv`.
Nothing here writes the public repo's data/processed/. Review rows hold ids, labels and
counts only, never source text. Every writer returns vault-relative paths so the build
can commit exactly what it wrote.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

import polars as pl

from booth_review.build.io import write_parquet_atomic, write_review_csv
from booth_review.config import DataPaths
from booth_review.mlb.apple import APPLE_BOOTHS_TABLE, APPLE_SUMMARY_TABLE
from booth_review.mlb.inputs import Review
from booth_review.mlb.postseason import POSTSEASON_SEASONS_TABLE, POSTSEASON_TABLE

__all__ = [
    "MLB_TABLES",
    "REVIEW_KEYS",
    "REVIEW_ROW_COLUMNS",
    "review_rows",
    "write_mlb_reviews",
    "write_mlb_tables",
]

GAMES_TABLE: Final = "mlb_games"
TELECASTS_TABLE: Final = "mlb_telecasts"
LINEUPS_TABLE: Final = "mlb_lineups"
WE_TABLE: Final = "mlb_we_table"

#: The eight processed tables a build writes.
MLB_TABLES: Final[tuple[str, ...]] = (
    GAMES_TABLE,
    TELECASTS_TABLE,
    LINEUPS_TABLE,
    WE_TABLE,
    APPLE_BOOTHS_TABLE,
    APPLE_SUMMARY_TABLE,
    POSTSEASON_TABLE,
    POSTSEASON_SEASONS_TABLE,
)

#: Review file keys a build writes (interim/review_mlb_<key>.csv).
REVIEW_KEYS: Final[tuple[str, ...]] = (
    "crew_disagreements",
    "lineups",
    "nongame",
    "people",
    "postseason_map",
    "rr",
    "unresolved",
)

REVIEW_ROW_COLUMNS: Final = ("source", "kind", "count", "pointer")


def review_rows(reviews: Sequence[Review]) -> list[dict[str, object]]:
    """Review rows sorted for stable output; same-slot rows merge their counts."""
    merged: dict[tuple[str, str, str], int] = {}
    for item in reviews:
        key = (item.source, item.kind, item.pointer)
        merged[key] = merged.get(key, 0) + item.count
    return [
        {"source": s, "kind": k, "count": n, "pointer": p}
        for (s, k, p), n in sorted(merged.items())
    ]


def write_mlb_tables(paths: DataPaths, frames: Mapping[str, pl.DataFrame]) -> list[str]:
    """Write the processed MLB tables; every name must be a known mlb_* table."""
    written: list[str] = []
    for name in sorted(frames):
        if name not in MLB_TABLES:
            raise ValueError(f"unknown MLB table: {name}")
        rel = f"processed/{name}.parquet"
        write_parquet_atomic(frames[name], paths.vault / rel)
        written.append(rel)
    return written


def write_mlb_reviews(
    paths: DataPaths,
    reviews: Mapping[str, tuple[Sequence[str], Sequence[Mapping[str, object]]]],
) -> list[str]:
    """Write each (columns, rows) review to interim/review_mlb_<key>.csv; relative paths."""
    written: list[str] = []
    for key in sorted(reviews):
        columns, rows = reviews[key]
        rel = f"interim/review_mlb_{key}.csv"
        write_review_csv(paths.vault / rel, columns, rows)
        written.append(rel)
    return written
