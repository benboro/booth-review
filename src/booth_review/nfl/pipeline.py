"""The NFL build behind `booth-review nfl build` (D-20 steps 2 and 3).

Everything runs inside one `VaultRepo.lock()`: load inputs, assemble the game
frame, build the Task 2 table and the Task 1 crew table (`nfl_task1_crews`, with
its lead-booth, AGOTW-miss, single-header and model review CSVs), check 2014-2015
acceptance, write processed/ tables and interim/ review CSVs, then make one
path-scoped, count-only commit.
Tables go to the vault only (D-23); nothing is published. A build with an
invalid week override is blocked: review files are written, tables are not.

With `site_data=True` an unblocked build also writes processed/nfl-data.json, the
NFL site file (999.5), in the same lock and the same commit, so it always matches
the tables. A builder error never blocks the table commit: the previous file stays
and the outcome counts `site_data_failed`. A blocked build leaves the file alone.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from booth_review.build.nfl_site_data import (
    build_nfl_site_data,
    load_nfl_site_inputs,
    write_nfl_site_data,
)
from booth_review.config import DataPaths
from booth_review.errors import SiteBuildError
from booth_review.nfl.acceptance import AcceptanceResult
from booth_review.nfl.acceptance import check_acceptance as run_acceptance
from booth_review.nfl.games import NflGameTable, NflReference, assemble_nfl_games
from booth_review.nfl.inputs import load_nfl_inputs
from booth_review.nfl.reference import load_nfl_franchises
from booth_review.nfl.tables import special_games_table, write_nfl_tables, write_review_files
from booth_review.nfl.task1 import TASK1_TABLE, build_task1
from booth_review.vault import VaultRepo, batch_message

ExtraTables = Callable[[NflGameTable, NflReference], Mapping[str, pl.DataFrame]]

#: Task 1 counts added to the commit message, with short labels: the vault's
#: count-only message whitelist caps a message at 120 characters.
_MESSAGE_COUNTS: tuple[tuple[str, str], ...] = (
    ("ambiguous_fox_weeks", "ambig"),
    ("seasons_close", "close"),
    ("seasons_tied", "tied"),
    ("agotw_miss_weeks", "misses"),
    ("skipped_single_header_weeks", "single"),
)
_MAX_MESSAGE_LEN = 120


@dataclass(frozen=True)
class NflBuildOutcome:
    blocked: bool
    written: tuple[str, ...]
    counts: Mapping[str, int]
    acceptance: AcceptanceResult | None
    committed: bool


def run_nfl_build(
    paths: DataPaths,
    reference_directory: Path,
    *,
    seasons: Sequence[int],
    include_playoffs: bool,
    commit: bool,
    check_acceptance: bool,
    now: datetime | None = None,
    extra_tables: ExtraTables | None = None,
    site_data: bool = False,
) -> NflBuildOutcome:
    vault = VaultRepo(paths.vault)
    vault.check()
    # `now` only decides which games count as played; the tables carry no wall-clock field.
    played_cut = now if now is not None else datetime.now(UTC)

    with vault.lock():
        inputs = load_nfl_inputs(paths, seasons)
        ref = NflReference.load(reference_directory)
        table = assemble_nfl_games(inputs, ref, include_playoffs=include_playoffs, now=played_cut)
        counts: dict[str, int] = dict(table.counts)
        counts["listing_parse_failures"] = inputs.listing_parse_failures
        counts["rr_parse_failures"] = inputs.rr_parse_failures

        acceptance: AcceptanceResult | None = None
        if check_acceptance:
            acceptance = run_acceptance(table.frame)
            table.reviews["acceptance"].extend(acceptance.rows)
            counts["acceptance_unmatched"] = acceptance.unmatched
            counts["acceptance_multi_network"] = acceptance.multi_network

        blocked = counts.get("override_errors", 0) > 0
        written: list[str]
        if blocked:
            written = write_review_files(paths, table.reviews)
        else:
            special = special_games_table(table, load_nfl_franchises(reference_directory))
            extra: Mapping[str, pl.DataFrame]
            task1_reviews: Mapping[str, list[dict[str, object]]] = {}
            if extra_tables is not None:
                # Test hook: replaces the Task 1 table.
                extra = extra_tables(table, ref)
            else:
                task1, task1_reviews, task1_counts = build_task1(table, ref)
                extra = {TASK1_TABLE: task1}
                counts.update(task1_counts)
            written = write_nfl_tables(paths, table, special, extra)
            written += write_review_files(paths, task1_reviews)
            if site_data and extra_tables is None:
                try:
                    site = build_nfl_site_data(load_nfl_site_inputs(paths, reference_directory))
                    written.append(write_nfl_site_data(paths, site))
                    counts["site_games"] = len(site.games.season)
                except (SiteBuildError, pl.exceptions.PolarsError, ValueError):
                    counts["site_data_failed"] = 1

        committed = False
        if commit:
            label = f"{min(seasons)}-{max(seasons)}" if seasons else "none"
            base = {
                "games": counts["games"],
                "standalone": counts["standalone"],
                "blocked": int(blocked),
            }
            task1_part = {short: int(counts[k]) for k, short in _MESSAGE_COUNTS if k in counts}
            message = batch_message("build", "nfl", label, {**base, **task1_part})
            if len(message) > _MAX_MESSAGE_LEN:
                message = batch_message("build", "nfl", label, base)
            committed = vault.commit_batch(message, paths=sorted(set(written)))

    return NflBuildOutcome(
        blocked=blocked,
        written=tuple(sorted(set(written))),
        counts=counts,
        acceptance=acceptance,
        committed=committed,
    )
