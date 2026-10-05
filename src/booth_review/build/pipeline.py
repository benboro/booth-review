"""The full build pipeline behind `booth-review build` (D-12): assemble every
processed table from raw (Plans 07-09), write the coverage audit (AUDIT-01),
gate the site-data write on the regression guard (AUDIT-03), and commit the
vault count-only, all inside one `VaultRepo.lock()` (T-03-46).

Only `run_build`'s own `--accept-baseline` path (Plan 11's CLI flag) ever
changes `audit/build_baseline.csv` -- a plain blocked build never does, and
skips every `processed/` write (the Parquet tables, coverage CSVs, and
`site-data.json`), leaving whatever the last accepted build wrote in place
(T-03-47). A blocked build still writes the `audit/` metrics and regression
report and the `interim/` review files, which are what a user needs to see
why it was blocked.

Site data is assembled and validated before anything is written, and before
`--accept-baseline` records a new baseline, so a run that fails validation
never leaves a new baseline (or half-updated processed tables) behind.
An incomplete bowls crosswalk (a plotted postseason game with no bowls.csv
row) still writes the interim review files, so `interim/review_bowls.csv` is
there to fill, then aborts before any processed, audit, or baseline write.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import polars as pl

from booth_review.build.coverage import build_coverage, write_coverage
from booth_review.build.regression import (
    RegressionResult,
    SeasonMetrics,
    build_metrics,
    check_regression,
    load_baseline,
    load_completeness_counts,
    write_metrics,
    write_regression_report,
)
from booth_review.build.regression import (
    accept_baseline as accept_baseline_metrics,
)
from booth_review.build.site_data import build_site_data, write_site_data
from booth_review.build.tables import BuildTables, assemble_tables, write_tables
from booth_review.config import DataPaths
from booth_review.errors import BowlCrosswalkError
from booth_review.transport.cache import Manifest
from booth_review.vault import VaultRepo, batch_message


@dataclass(frozen=True)
class BuildOutcome:
    """The result of one `run_build` call.

    `blocked` is the raw AUDIT-03 regression verdict (a metric dropped
    against the accepted baseline or the Phase 2 completeness counts);
    `accepted` is whether this run's `--accept-baseline` wrote a new
    baseline. The CLI's exit code is `4` only when `blocked and not
    accepted` -- an accepted, previously-blocked build still exits `0`.
    """

    blocked: bool
    accepted: bool
    reasons: tuple[str, ...]
    counts: dict[str, int]
    written: tuple[str, ...]
    committed: bool
    # crew_overrides.csv lines whose crew differs from 506's without
    # `correction`: flagged for the user, never a reason to block.
    crew_override_differs_lines: tuple[int, ...] = ()


# A preliminary headline figure older than this many days is listed in
# interim/review_preliminary_headlines.csv (PITFALLS: preliminary figures settle).
PRELIMINARY_STALE_DAYS = 10
_PRELIMINARY_COLUMNS = ("telecast_id", "date_et", "claim_id")

_MANIFEST_TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def input_stamp(paths: DataPaths) -> datetime:
    """The newest change to a collected input, from the request manifest.

    An entry counts as a change when it wrote a cached file (non-null path and
    sha256) whose sha256 differs from the previous entry for the same path; the
    first entry for a path is a change. Identical inputs give an identical
    stamp, so a rebuild with nothing new is byte-identical (D-02 idempotence),
    and a refresh that returns the same bytes does not move it.
    """
    last_sha: dict[str, str] = {}
    newest = _EPOCH
    for entry in Manifest(paths.manifest).entries():
        path = entry.get("path")
        sha = entry.get("sha256")
        fetched_at = entry.get("fetched_at")
        if path is None or sha is None or fetched_at is None:
            continue
        previous = last_sha.get(path)
        last_sha[path] = sha
        if previous == sha:
            continue
        stamp = datetime.strptime(fetched_at, _MANIFEST_TIME_FMT).replace(tzinfo=UTC)
        newest = max(newest, stamp)
    return newest


def _stale_preliminary_headlines(
    tables: BuildTables, generated_at: datetime
) -> list[dict[str, object]]:
    """Plotted telecasts whose headline figure is still preliminary more than
    PRELIMINARY_STALE_DAYS before `generated_at`. Ids and dates only."""
    cutoff = generated_at.date() - timedelta(days=PRELIMINARY_STALE_DAYS)
    plotted = tables.telecasts.filter(pl.col("plotted") & (pl.col("date_et") < cutoff)).select(
        "telecast_id", "date_et"
    )
    stale = (
        tables.viewership.filter(pl.col("is_headline") & (pl.col("status") == "preliminary"))
        .select("telecast_id", "claim_id")
        .join(plotted, on="telecast_id", how="inner")
        .sort(["telecast_id", "claim_id"])
    )
    return [
        {
            "telecast_id": row["telecast_id"],
            "date_et": row["date_et"].isoformat(),
            "claim_id": row["claim_id"],
        }
        for row in stale.iter_rows(named=True)
    ]


def _build_counts(tables: BuildTables, result: RegressionResult) -> dict[str, int]:
    totals = tables.diagnostics.totals
    games = tables.games
    newest_season = games["season"].max() if games.height else None
    current_season = int(str(newest_season)) if newest_season is not None else 0
    games_now = games.filter(pl.col("season") == current_season)
    telecasts_now = tables.telecasts.filter(pl.col("season") == current_season)

    def review_count(key: str) -> int:
        entry = tables.review_rows.get(key)
        return len(entry[1]) if entry is not None else 0

    join08_rate = tables.diagnostics.join08_rate
    review_rows_total = sum(len(rows) for _columns, rows in tables.review_rows.values())
    return {
        "plotted_telecasts": int(tables.telecasts.filter(pl.col("plotted")).height),
        "rated_telecasts": totals.get("rated_telecasts", 0),
        "records_with_crew": totals.get("records_with_crew", 0),
        "rr_records": totals.get("rr_records", 0),
        # x10000 (not x100) so a 4-decimal rate (matching regression.py's own
        # _RATE_DECIMALS) stays an exact integer rather than losing precision.
        "join08_rate_x10000": (round(join08_rate * 10000) if join08_rate is not None else 0),
        "duplicate_merges": totals.get("duplicate_merges", 0),
        "combined_figures": totals.get("combined_combined", 0),
        "bowl_names_unknown": totals.get("bowl_names_unknown", 0),
        "crew_overrides_applied": totals.get("crew_overrides_applied", 0),
        "crew_overrides_patched": totals.get("crew_overrides_patched", 0),
        "crew_overrides_redundant": totals.get("crew_overrides_redundant", 0),
        "crew_overrides_differs": totals.get("crew_overrides_differs", 0),
        "crew_overrides_corrections": totals.get("crew_overrides_corrections", 0),
        "crew_gaps_unpatched": totals.get("crew_gaps_unpatched", 0),
        "review_rows_total": review_rows_total,
        "current_season": current_season,
        "games_current_season": int(games_now.height),
        "games_final_current_season": int(
            games_now.filter(
                pl.col("home_points").is_not_null() & pl.col("away_points").is_not_null()
            ).height
        ),
        "telecasts_current_season": int(telecasts_now.height),
        "rated_current_season": int(telecasts_now.filter(pl.col("rated")).height),
        "plotted_current_season": int(telecasts_now.filter(pl.col("plotted")).height),
        "bowls_missing": int(totals.get("bowls_missing", 0)),
        "bowls_no_franchise": 0,
        "review_people_new": review_count("review_people_new"),
        "review_unresolved_teams": review_count("review_unresolved_teams"),
        "compared_seasons": result.compared_seasons,
    }


def run_build(
    paths: DataPaths,
    reference_directory: Path,
    *,
    commit: bool,
    accept_baseline: bool,
    now: datetime | None = None,
    bowl_crosswalk: Literal["strict", "lenient"] = "strict",
) -> BuildOutcome:
    """Rebuild every processed table from raw, write the coverage/regression
    audits, gate `processed/site-data.json` on the regression guard, and
    (when `commit`) commit every written path in one count-only message.
    """
    vault = VaultRepo(paths.vault)
    vault.check()
    generated_at = now if now is not None else input_stamp(paths)

    with vault.lock():
        tables = assemble_tables(paths, reference_directory)
        stale_preliminary = _stale_preliminary_headlines(tables, generated_at)
        tables.review_rows["review_preliminary_headlines"] = (
            _PRELIMINARY_COLUMNS,
            stale_preliminary,
        )
        coverage = build_coverage(tables)

        metrics: Sequence[SeasonMetrics] = build_metrics(tables, paths)
        baseline = load_baseline(paths)
        completeness = load_completeness_counts(paths)
        result = check_regression(metrics, baseline, completeness)

        write_data = (not result.blocked) or accept_baseline
        # Assemble and validate site data first (WR-01): if it raises, the
        # run aborts before any processed table, audit file, or new
        # baseline is written.
        site_counts: dict[str, int] = {}
        try:
            site = (
                build_site_data(
                    tables,
                    coverage,
                    reference_directory,
                    generated_at,
                    counts=site_counts,
                    bowl_crosswalk=bowl_crosswalk,
                )
                if write_data
                else None
            )
        except BowlCrosswalkError:
            write_tables(paths, tables, processed=False)
            raise

        written: list[str] = []
        # A blocked build writes only the interim review files, never the
        # processed tables (WR-02).
        written.extend(write_tables(paths, tables, processed=write_data))
        if write_data:
            written.extend(write_coverage(paths, coverage))

        written.extend(write_metrics(paths, metrics))
        written.extend(write_regression_report(paths, metrics, baseline, completeness, result))

        accepted = False
        if accept_baseline:
            written.extend(accept_baseline_metrics(paths, metrics))
            accepted = True

        if site is not None:
            written.extend(write_site_data(paths, site))

        counts = _build_counts(tables, result)
        counts.update(site_counts)
        counts["preliminary_headlines_over_10_days"] = len(stale_preliminary)

        committed = False
        if commit:
            seasons = sorted(tables.diagnostics.per_season)
            season_label = f"{seasons[0]}-{seasons[-1]}" if seasons else "none"
            message = batch_message(
                "build",
                "all",
                season_label,
                {
                    "telecasts": counts["plotted_telecasts"],
                    "matched": counts["records_with_crew"],
                    "blocked": 0 if write_data else 1,
                },
            )
            committed = vault.commit_batch(message, paths=sorted(set(written)))

    return BuildOutcome(
        blocked=result.blocked,
        accepted=accepted,
        reasons=result.reasons,
        counts=counts,
        written=tuple(sorted(set(written))),
        committed=committed,
        crew_override_differs_lines=tables.crew_override_differs_lines,
    )
