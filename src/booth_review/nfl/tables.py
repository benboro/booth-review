"""NFL output tables: the per-game frame and the Task 2 special-games table (SPORT-03).

One row per (franchise_id, season). A game counts for both its home and its
away franchise, and once toward `special` however many categories it hits.
Rates divide by doubleheader weeks minus ambiguous weeks, because ambiguous
weeks are left out of the AGOTW and CBS-national counts (D-16); a zero
denominator gives null, never 0 or inf.

Tables are written only under the vault's processed/ (D-23), never to the
repo's public data/processed/.
"""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from booth_review.build.io import write_parquet_atomic, write_review_csv
from booth_review.config import DataPaths
from booth_review.nfl.games import NflGameTable
from booth_review.nfl.reference import NflFranchises

#: Frame slot label -> standalone_<slot> column suffix.
SLOT_COLUMNS: dict[str, str] = {
    "TNF": "tnf",
    "SNF": "snf",
    "MNF": "mnf",
    "Thanksgiving": "thanksgiving",
    "Christmas": "christmas",
    "Black Friday": "black_friday",
    "Saturday": "saturday",
    "Friday": "friday",
    "International": "international",
    "Sunday early": "sunday_early",
    "Sunday late": "sunday_late",
    "Other": "other",
}

#: Exclusive solo-slot groups (D-12): solo_<group> -> frame slot labels. Together they
#: cover every standalone slot, so the five columns sum to standalone_total.
SOLO_GROUPS: dict[str, tuple[str, ...]] = {
    "thursday": ("TNF",),
    "sunday": ("SNF",),
    "monday": ("MNF",),
    "holiday": ("Thanksgiving", "Christmas", "Black Friday"),
    "other": ("Saturday", "International", "Friday", "Sunday early", "Sunday late", "Other"),
}

NFL_SPECIAL_COLUMNS: tuple[str, ...] = (
    "franchise_id",
    "season",
    "display_name",
    "games",
    "standalone_total",
    *(f"standalone_{suffix}" for suffix in SLOT_COLUMNS.values()),
    *(f"solo_{suffix}" for suffix in SOLO_GROUPS),
    "agotw",
    "cbs_national",
    "international",
    "international_other",
    "flexed",
    "special",
    "fox_doubleheader_weeks",
    "cbs_doubleheader_weeks",
    "fox_ambiguous_weeks",
    "cbs_ambiguous_weeks",
    "agotw_rate",
    "cbs_national_rate",
    "through_week",
)

_COUNT_COLUMNS = tuple(c for c in NFL_SPECIAL_COLUMNS[3:] if not c.endswith("_rate"))

_SPECIAL_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "franchise_id": pl.String,
    "season": pl.Int64,
    "display_name": pl.String,
    **dict.fromkeys(_COUNT_COLUMNS, pl.Int64),
    "agotw_rate": pl.Float64,
    "cbs_national_rate": pl.Float64,
    "through_week": pl.Int64,
}


def _display_fallback(
    franchises: NflFranchises | None, franchise_id: str, season: int
) -> str | None:
    if franchises is None:
        return None
    for name in franchises.names.get(franchise_id, ()):
        lo = name.season_from if name.season_from is not None else season
        hi = name.season_to if name.season_to is not None else season
        if lo <= season <= hi:
            return name.display_name
    return None


def _season_week_counts(frame: pl.DataFrame) -> dict[int, dict[str, int]]:
    """Season-level doubleheader and ambiguous week counts (regular season only)."""
    out: dict[int, dict[str, int]] = {}
    reg = frame.filter(pl.col("game_type") == "REG")
    for season in reg["season"].unique().to_list():
        rows = reg.filter(pl.col("season") == season)
        entry: dict[str, int] = {}
        for network in ("fox", "cbs"):
            dh = rows.filter(pl.col(f"{network}_dh_sunday"))
            entry[f"{network}_doubleheader_weeks"] = dh["week"].n_unique()
            ambiguous = dh.filter(
                (pl.col("late_national_status") == "ambiguous") & (pl.col("network_id") == network)
            )
            entry[f"{network}_ambiguous_weeks"] = ambiguous["week"].n_unique()
        out[int(season)] = entry
    return out


def special_games_table(
    table: NflGameTable, franchises: NflFranchises | None = None
) -> pl.DataFrame:
    """Per-franchise-season counts and rates from the game frame."""
    frame = table.frame
    if frame.height == 0:
        return pl.DataFrame(schema=_SPECIAL_SCHEMA).select(NFL_SPECIAL_COLUMNS)

    side_cols = [
        "season",
        "game_type",
        "slot_name",
        "is_standalone",
        "is_agotw",
        "is_cbs_national",
        "is_international",
        "flexed",
        "is_special",
    ]
    sides = [
        frame.select(
            pl.col(f"{side}_franchise_id").alias("franchise_id"),
            pl.col(f"{side}_display_name").alias("display_name"),
            *side_cols,
        )
        for side in ("home", "away")
    ]
    long = pl.concat(sides).filter(pl.col("franchise_id").is_not_null())

    aggs: list[pl.Expr] = [
        pl.col("display_name").drop_nulls().first().alias("display_name"),
        pl.len().alias("games"),
        pl.col("is_standalone").sum().alias("standalone_total"),
    ]
    for label, suffix in SLOT_COLUMNS.items():
        aggs.append(
            (pl.col("is_standalone") & (pl.col("slot_name") == label))
            .sum()
            .alias(f"standalone_{suffix}")
        )
    for suffix, labels in SOLO_GROUPS.items():
        aggs.append(
            (pl.col("is_standalone") & pl.col("slot_name").is_in(labels))
            .sum()
            .alias(f"solo_{suffix}")
        )
    aggs += [
        pl.col("is_agotw").sum().alias("agotw"),
        pl.col("is_cbs_national").sum().alias("cbs_national"),
        pl.col("is_international").fill_null(False).sum().alias("international"),
        (
            pl.col("is_international").fill_null(False)
            & ~pl.col("is_standalone").fill_null(False)
            & ~pl.col("is_agotw").fill_null(False)
            & ~pl.col("is_cbs_national").fill_null(False)
        )
        .sum()
        .alias("international_other"),
        pl.col("flexed").sum().alias("flexed"),
        pl.col("is_special").sum().alias("special"),
    ]
    grouped = long.group_by(["franchise_id", "season"]).agg(aggs).sort(["franchise_id", "season"])

    week_counts = _season_week_counts(frame)
    rows: list[dict[str, object]] = []
    for raw in grouped.to_dicts():
        season = int(raw["season"])
        row: dict[str, object] = dict(raw)
        if row["display_name"] is None:
            row["display_name"] = _display_fallback(franchises, str(raw["franchise_id"]), season)
        counts = week_counts.get(
            season,
            {
                "fox_doubleheader_weeks": 0,
                "cbs_doubleheader_weeks": 0,
                "fox_ambiguous_weeks": 0,
                "cbs_ambiguous_weeks": 0,
            },
        )
        row.update(counts)
        fox_den = counts["fox_doubleheader_weeks"] - counts["fox_ambiguous_weeks"]
        cbs_den = counts["cbs_doubleheader_weeks"] - counts["cbs_ambiguous_weeks"]
        row["agotw_rate"] = int(raw["agotw"]) / fox_den if fox_den > 0 else None
        row["cbs_national_rate"] = int(raw["cbs_national"]) / cbs_den if cbs_den > 0 else None
        row["through_week"] = table.through_week.get(season)
        rows.append(row)
    return pl.DataFrame(rows, schema=_SPECIAL_SCHEMA, orient="row").select(NFL_SPECIAL_COLUMNS)


def _review_columns(rows: list[dict[str, object]]) -> list[str]:
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    return columns or ["reason"]


def write_review_files(
    paths: DataPaths, reviews: Mapping[str, list[dict[str, object]]]
) -> list[str]:
    """Write every review list to interim/review_nfl_<key>.csv; returns vault-relative paths."""
    written: list[str] = []
    for key in sorted(reviews):
        rows = reviews[key]
        rel = f"interim/review_nfl_{key}.csv"
        write_review_csv(paths.vault / rel, _review_columns(rows), rows)
        written.append(rel)
    return written


def write_nfl_tables(
    paths: DataPaths,
    game_table: NflGameTable,
    special: pl.DataFrame,
    extra: Mapping[str, pl.DataFrame] | None = None,
) -> list[str]:
    """Write the processed NFL tables and review CSVs into the vault; returns relative paths."""
    tables: dict[str, pl.DataFrame] = {
        "nfl_games": game_table.frame,
        "nfl_special_games_by_team_season": special,
    }
    for name, frame in (extra or {}).items():
        if not name.startswith("nfl_"):
            raise ValueError("extra NFL tables must be named nfl_*")
        tables[name] = frame
    written: list[str] = []
    for name, frame in sorted(tables.items()):
        rel = f"processed/{name}.parquet"
        write_parquet_atomic(frame, paths.vault / rel)
        written.append(rel)
    written += write_review_files(paths, game_table.reviews)
    return sorted(written)
