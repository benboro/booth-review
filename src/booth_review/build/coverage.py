"""The coverage audit (AUDIT-01): a deterministic season x network table of
field completeness, match rates, publisher mix, duplicate merges, combined
figures, and disagreement counts, over each build's plotted-eligible rated
main telecasts (feed_type "main", `rated` true) -- the same population D-10's
plotted rule draws its headline requirement from, minus the headline-present
filter itself (this table reports headline_present as one of its own
columns).

Excitement and pregame completeness are computed only against the FBS-scoped
`games` frame telecasts join to (research Pitfall 3): CFBD's own all-division
null rate is far higher and would misrepresent this project's actual
coverage. A missing value is counted as missing, never coerced to zero or
another default (D-11) -- every completeness count below comes from
`is not None` on the joined value, not a filled column.

Vault-only (D-07): `write_coverage` writes processed/coverage.csv and
processed/coverage_publishers.csv, reaching the public only through the
site's coverage page at launch. Both go through `build.io.write_review_csv`,
so every string cell is `csv_safe`d before it could ever be opened in a
spreadsheet (T-03-42).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from booth_review.build.io import write_review_csv
from booth_review.config import DataPaths

if TYPE_CHECKING:
    from booth_review.build.tables import BuildTables

COVERAGE_COLUMNS: tuple[str, ...] = (
    "season",
    "network_id",
    "rr_records",
    "rr_excluded",
    "rr_out_of_scope",
    "rr_unmatched",
    "rated_telecasts",
    "matched_crew",
    "records_with_crew",
    "crew_rate",
    "match_rate",
    "headline_present",
    "excitement_present",
    "pregame_present",
    "points_present",
    "ranks_present",
    "unranked_games",
    "kickoff_present",
    "publisher_present",
    "source_url_present",
    "duplicate_merges",
    "combined_figures",
    "headline_disagreements",
    "era_disagreements",
)

PUBLISHER_COLUMNS: tuple[str, ...] = ("season", "network_id", "publisher", "headline_count")

_ALL_NETWORK = "ALL"
_NO_PUBLISHER = "(none)"
_RATE_DECIMALS = 4

# Per-(season, network_id) counters accumulated over the eligible population;
# every one of these is a plain count, never a rate (rates are derived once,
# after accumulation, in _rate).
_BUCKET_KEYS: tuple[str, ...] = (
    "rated_telecasts",
    "matched_crew",
    "headline_present",
    "excitement_present",
    "pregame_present",
    "points_present",
    "ranks_present",
    "unranked_games",
    "kickoff_present",
    "publisher_present",
    "source_url_present",
    "duplicate_merges",
    "combined_figures",
    "headline_disagreements",
    "era_disagreements",
)


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, _RATE_DECIMALS)


def _empty_bucket() -> dict[str, int]:
    return dict.fromkeys(_BUCKET_KEYS, 0)


def _as_int(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) else default


@dataclass(frozen=True)
class CoverageReport:
    """The full season x network coverage table plus the publisher-mix rows.

    `rows` is sorted by season then network_id with "ALL" last, matching
    `COVERAGE_COLUMNS`; `publisher_rows` matches `PUBLISHER_COLUMNS`.
    """

    rows: list[dict[str, object]]
    publisher_rows: list[dict[str, object]]

    def totals(self) -> dict[str, object]:
        """A whole-build rollup summed across every season's "ALL" row.

        Every count column is summed directly; `crew_rate` and `match_rate`
        are re-derived from the summed numerator/denominator pairs rather
        than averaged, so the rolled-up rate stays internally consistent
        with the summed counts next to it.
        """
        all_rows = [row for row in self.rows if row["network_id"] == _ALL_NETWORK]
        summable = [
            column
            for column in COVERAGE_COLUMNS
            if column not in {"season", "network_id", "crew_rate", "match_rate"}
        ]
        result: dict[str, object] = {"network_id": _ALL_NETWORK, "seasons": len(all_rows)}
        for column in summable:
            values = [row[column] for row in all_rows if row[column] is not None]
            result[column] = sum(_as_int(v) for v in values) if values else None

        result["crew_rate"] = _rate(
            _as_int(result.get("matched_crew")), _as_int(result.get("rated_telecasts"))
        )

        rr_records = result.get("rr_records")
        rr_excluded = result.get("rr_excluded")
        rr_out_of_scope = result.get("rr_out_of_scope")
        if rr_records is None or rr_excluded is None or rr_out_of_scope is None:
            result["match_rate"] = None
        else:
            denominator = _as_int(rr_records) - _as_int(rr_excluded) - _as_int(rr_out_of_scope)
            result["match_rate"] = _rate(_as_int(result.get("records_with_crew")), denominator)
        return result


def build_coverage(tables: BuildTables) -> CoverageReport:
    """Build the season x network coverage table and publisher mix from
    `tables`. Never writes anything -- see `write_coverage`.
    """
    telecasts = tables.telecasts
    games = tables.games
    diagnostics = tables.diagnostics

    eligible = telecasts.filter(pl.col("rated") & (pl.col("feed_type") == "main"))
    games_slim = games.select(
        "game_id", "excitement", "pregame_x", "home_points", "away_points", "home_rank", "away_rank"
    )
    joined = eligible.join(games_slim, on="game_id", how="left")

    era_dis_columns, era_dis_rows = tables.review_rows.get("review_era_disagreements", ((), []))
    era_disagreements_by_telecast: dict[str, int] = {}
    if era_dis_columns:
        for review_row in era_dis_rows:
            telecast_id = str(review_row["telecast_id"])
            era_disagreements_by_telecast[telecast_id] = (
                era_disagreements_by_telecast.get(telecast_id, 0) + 1
            )

    buckets: dict[tuple[int, str | None], dict[str, int]] = {}
    publisher_counts: dict[tuple[int, str | None, str], int] = {}

    for row in joined.iter_rows(named=True):
        season = int(row["season"])
        network_id = row["network_id"]
        bucket = buckets.setdefault((season, network_id), _empty_bucket())

        bucket["rated_telecasts"] += 1
        if row["crew_matched"]:
            bucket["matched_crew"] += 1

        has_headline = row["headline_claim_id"] is not None
        if has_headline:
            bucket["headline_present"] += 1
        if row["excitement"] is not None:
            bucket["excitement_present"] += 1
        if row["pregame_x"] is not None:
            bucket["pregame_present"] += 1
        if row["home_points"] is not None and row["away_points"] is not None:
            bucket["points_present"] += 1
        home_rank_present = row["home_rank"] is not None
        away_rank_present = row["away_rank"] is not None
        if home_rank_present or away_rank_present:
            bucket["ranks_present"] += 1
        if not home_rank_present and not away_rank_present:
            bucket["unranked_games"] += 1
        if row["kickoff_et"] is not None:
            bucket["kickoff_present"] += 1
        if row["headline_publisher"] is not None:
            bucket["publisher_present"] += 1
        if row["headline_source_url"] is not None:
            bucket["source_url_present"] += 1
        bucket["duplicate_merges"] += int(row["duplicate_merges"] or 0)
        if row["combined_feeds"] is not None:
            bucket["combined_figures"] += 1
        if row["rr_current_check"] == "disagree":
            bucket["headline_disagreements"] += 1
        bucket["era_disagreements"] += era_disagreements_by_telecast.get(str(row["telecast_id"]), 0)

        if has_headline:
            publisher = row["headline_publisher"] if row["headline_publisher"] else _NO_PUBLISHER
            key = (season, network_id, publisher)
            publisher_counts[key] = publisher_counts.get(key, 0) + 1

    rows: list[dict[str, object]] = []
    for (season, network_id), bucket in buckets.items():
        rows.append(
            {
                "season": season,
                "network_id": network_id,
                "rr_records": None,
                "rr_excluded": None,
                "rr_out_of_scope": None,
                "rr_unmatched": None,
                "rated_telecasts": bucket["rated_telecasts"],
                "matched_crew": bucket["matched_crew"],
                "records_with_crew": None,
                "crew_rate": _rate(bucket["matched_crew"], bucket["rated_telecasts"]),
                "match_rate": None,
                "headline_present": bucket["headline_present"],
                "excitement_present": bucket["excitement_present"],
                "pregame_present": bucket["pregame_present"],
                "points_present": bucket["points_present"],
                "ranks_present": bucket["ranks_present"],
                "unranked_games": bucket["unranked_games"],
                "kickoff_present": bucket["kickoff_present"],
                "publisher_present": bucket["publisher_present"],
                "source_url_present": bucket["source_url_present"],
                "duplicate_merges": bucket["duplicate_merges"],
                "combined_figures": bucket["combined_figures"],
                "headline_disagreements": bucket["headline_disagreements"],
                "era_disagreements": bucket["era_disagreements"],
            }
        )

    seasons = sorted({season for season, _ in buckets} | set(diagnostics.per_season))
    for season in seasons:
        season_buckets = [bucket for (s, _network), bucket in buckets.items() if s == season]
        summed = {key: sum(bucket[key] for bucket in season_buckets) for key in _BUCKET_KEYS}
        diag = diagnostics.per_season.get(season, {})
        rows.append(
            {
                "season": season,
                "network_id": _ALL_NETWORK,
                "rr_records": diag.get("rr_records"),
                "rr_excluded": diag.get("rr_excluded"),
                "rr_out_of_scope": diag.get("rr_out_of_scope"),
                "rr_unmatched": diag.get("rr_unmatched"),
                "rated_telecasts": summed["rated_telecasts"],
                "matched_crew": summed["matched_crew"],
                "records_with_crew": diag.get("records_with_crew"),
                "crew_rate": _rate(summed["matched_crew"], summed["rated_telecasts"]),
                "match_rate": diagnostics.join08_by_season.get(season),
                "headline_present": summed["headline_present"],
                "excitement_present": summed["excitement_present"],
                "pregame_present": summed["pregame_present"],
                "points_present": summed["points_present"],
                "ranks_present": summed["ranks_present"],
                "unranked_games": summed["unranked_games"],
                "kickoff_present": summed["kickoff_present"],
                "publisher_present": summed["publisher_present"],
                "source_url_present": summed["source_url_present"],
                "duplicate_merges": summed["duplicate_merges"],
                "combined_figures": summed["combined_figures"],
                "headline_disagreements": summed["headline_disagreements"],
                "era_disagreements": summed["era_disagreements"],
            }
        )

    rows.sort(
        key=lambda r: (
            _as_int(r["season"]),
            1 if r["network_id"] == _ALL_NETWORK else 0,
            str(r["network_id"] or ""),
        )
    )

    publisher_rows: list[dict[str, object]] = [
        {
            "season": season,
            "network_id": network_id,
            "publisher": publisher,
            "headline_count": count,
        }
        for (season, network_id, publisher), count in publisher_counts.items()
    ]
    publisher_rows.sort(
        key=lambda r: (
            _as_int(r["season"]),
            str(r["network_id"] or ""),
            str(r["publisher"]),
        )
    )

    return CoverageReport(rows=rows, publisher_rows=publisher_rows)


def write_coverage(paths: DataPaths, report: CoverageReport) -> list[str]:
    """Write processed/coverage.csv and processed/coverage_publishers.csv
    (LF, csv_safe'd, atomic -- build.io.write_review_csv), returning their
    vault-relative paths.
    """
    write_review_csv(paths.processed / "coverage.csv", COVERAGE_COLUMNS, report.rows)
    write_review_csv(
        paths.processed / "coverage_publishers.csv", PUBLISHER_COLUMNS, report.publisher_rows
    )
    return ["processed/coverage.csv", "processed/coverage_publishers.csv"]
