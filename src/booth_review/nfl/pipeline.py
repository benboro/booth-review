"""The NFL build behind `booth-review nfl build` (D-20 step 2 deliverable).

Everything runs inside one `VaultRepo.lock()`: load inputs, assemble the game
frame, build the Task 2 table, check 2014-2015 acceptance, write processed/
tables and interim/ review CSVs, then make one path-scoped, count-only commit.
Tables go to the vault only (D-23); nothing is published. A build with an
invalid week override is blocked: review files are written, tables are not.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from booth_review.config import DataPaths
from booth_review.nfl.acceptance import AcceptanceResult
from booth_review.nfl.acceptance import check_acceptance as run_acceptance
from booth_review.nfl.games import NflGameTable, NflReference, assemble_nfl_games
from booth_review.nfl.inputs import load_nfl_inputs
from booth_review.nfl.reference import load_nfl_franchises
from booth_review.nfl.tables import special_games_table, write_nfl_tables, write_review_files
from booth_review.vault import VaultRepo, batch_message

ExtraTables = Callable[[NflGameTable, NflReference], Mapping[str, pl.DataFrame]]


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
            extra = extra_tables(table, ref) if extra_tables is not None else None
            written = write_nfl_tables(paths, table, special, extra)

        committed = False
        if commit:
            label = f"{min(seasons)}-{max(seasons)}" if seasons else "none"
            message = batch_message(
                "build",
                "nfl",
                label,
                {
                    "games": counts["games"],
                    "standalone": counts["standalone"],
                    "blocked": int(blocked),
                },
            )
            committed = vault.commit_batch(message, paths=sorted(set(written)))

    return NflBuildOutcome(
        blocked=blocked,
        written=tuple(sorted(set(written))),
        counts=counts,
        acceptance=acceptance,
        committed=committed,
    )
