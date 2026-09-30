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
from datetime import UTC, datetime
from pathlib import Path

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


def _build_counts(tables: BuildTables, result: RegressionResult) -> dict[str, int]:
    totals = tables.diagnostics.totals
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
        "crew_overrides_redundant": totals.get("crew_overrides_redundant", 0),
        "crew_overrides_differs": totals.get("crew_overrides_differs", 0),
        "crew_gaps_unpatched": totals.get("crew_gaps_unpatched", 0),
        "review_rows_total": review_rows_total,
        "compared_seasons": result.compared_seasons,
    }


def run_build(
    paths: DataPaths,
    reference_directory: Path,
    *,
    commit: bool,
    accept_baseline: bool,
    now: datetime | None = None,
) -> BuildOutcome:
    """Rebuild every processed table from raw, write the coverage/regression
    audits, gate `processed/site-data.json` on the regression guard, and
    (when `commit`) commit every written path in one count-only message.
    """
    vault = VaultRepo(paths.vault)
    vault.check()
    generated_at = now if now is not None else datetime.now(UTC)

    with vault.lock():
        tables = assemble_tables(paths, reference_directory)
        coverage = build_coverage(tables)

        metrics: Sequence[SeasonMetrics] = build_metrics(tables, paths)
        baseline = load_baseline(paths)
        completeness = load_completeness_counts(paths)
        result = check_regression(metrics, baseline, completeness)

        write_data = (not result.blocked) or accept_baseline
        # Assemble and validate site data first (WR-01): if it raises, the
        # run aborts before any processed table, audit file, or new
        # baseline is written.
        try:
            site = (
                build_site_data(tables, coverage, reference_directory, generated_at)
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
    )
