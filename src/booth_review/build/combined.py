"""Combined-figure detection and confirmation (D-08, D-09): a figure that
combines viewership across simulcast feeds (a MegaCast, or a title game with
alt-casts) counts as one dot, credited to the main-feed booth and flagged
"combined across N feeds" for the hover and detail panel.

Ratings Reference's own `composite_of`/`carrier_network` fields are trusted
automatically when present (build.telecasts already sets `combined_feeds`
from a claim's `composite_of` -- research found neither field populated
anywhere in this project's 2014-2025 range, but a future record carrying
one is honored without a review round-trip). Everything else this module
finds is a *candidate* the user confirms by hand in the pointer-only
`data/reference/combined_figures.csv` (D-06): a rated main telecast whose
game has an alt-cast/Spanish 506 listing (`alt_listed`), or whose headline
figure is a statistical outlier against its own network-season (`outlier`).
`apply_combined` then folds every confirmed decision back into `telecasts`/
`telecast_flags`.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import polars as pl

from booth_review.build.io import write_review_csv
from booth_review.build.sources import load_all_sources
from booth_review.config import DataPaths
from booth_review.errors import ReferenceTableError
from booth_review.reference import read_reference_csv, reference_dir, write_reference_csv
from booth_review.resolve.overrides import pointer_for_listing
from booth_review.sources.sports506.parser import Listing506

COMBINED_COLUMNS = ("rr_telecast_id", "decision", "feeds", "reason")

REVIEW_COMBINED_COLUMNS = (
    "candidate_id",
    "rr_telecast_id",
    "season",
    "date_et",
    "network_id",
    "reasons",
    "alt_feed_count",
    "headline_value",
    "network_median",
    "proposed",
    "proposed_feeds",
    "decision",
)

Decision = Literal["combined", "single"]
Reason = Literal["megacast", "alt-cast-simulcast", "title-game", "other"]

_DECISIONS: frozenset[str] = frozenset({"combined", "single"})
_REASONS: frozenset[str] = frozenset({"megacast", "alt-cast-simulcast", "title-game", "other"})
_RR_ID_RE = re.compile(r"^cfb-[a-z0-9-]+$")

# A rated main telecast's headline figure this many times its network-season
# median (or more) is an "outlier" candidate for the user to judge (D-09).
OUTLIER_FACTOR = 3.0
# An outlier comparison only runs for a (season, network) with at least this
# many plotted telecasts -- too small a sample makes "3x the median" noise.
MIN_NETWORK_SEASON_TELECASTS = 10

# 506's own wording for a title game (checked against the main listing's
# game_label, case-insensitively): a structural signal, never a hardcoded
# team/network name.
_TITLE_GAME_MARKERS = ("championship",)


@dataclass(frozen=True)
class CombinedDecision:
    """One user-confirmed row of data/reference/combined_figures.csv."""

    rr_telecast_id: str
    decision: Decision
    feeds: int | None
    reason: Reason


@dataclass(frozen=True)
class CombinedCandidate:
    """One rated main telecast find_combined_candidates flags for review."""

    rr_telecast_id: str
    telecast_id: str
    season: int
    date_et: date
    network_id: str | None
    reasons: tuple[str, ...]
    alt_feed_count: int
    headline_value: float | None
    network_median: float | None
    proposed: Decision
    proposed_feeds: int | None


def load_combined_figures(reference_directory: Path) -> dict[str, CombinedDecision]:
    """Read combined_figures.csv (not required): rr_telecast_id ->
    CombinedDecision. Raises ReferenceTableError on a malformed
    rr_telecast_id, a decision outside combined|single, a reason outside
    megacast|alt-cast-simulcast|title-game|other, feeds < 2 on a combined
    row, a non-integer feeds value, or a duplicate rr_telecast_id.
    """
    path = reference_directory / "combined_figures.csv"
    raw_rows = read_reference_csv(path, COMBINED_COLUMNS, required=False)

    decisions: dict[str, CombinedDecision] = {}
    for line_no, raw in enumerate(raw_rows, start=2):
        rr_telecast_id = raw["rr_telecast_id"]
        if not _RR_ID_RE.match(rr_telecast_id):
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: malformed rr_telecast_id {rr_telecast_id!r}"
            )
        if rr_telecast_id in decisions:
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: duplicate rr_telecast_id {rr_telecast_id!r}"
            )

        decision = raw["decision"]
        if decision not in _DECISIONS:
            raise ReferenceTableError(f"{path.name}: line {line_no}: invalid decision {decision!r}")

        reason = raw["reason"]
        if reason not in _REASONS:
            raise ReferenceTableError(f"{path.name}: line {line_no}: invalid reason {reason!r}")

        feeds_raw = raw["feeds"]
        feeds: int | None = None
        if feeds_raw:
            try:
                feeds = int(feeds_raw)
            except ValueError:
                raise ReferenceTableError(
                    f"{path.name}: line {line_no}: invalid feeds {feeds_raw!r}"
                ) from None

        if decision == "combined" and (feeds is None or feeds < 2):
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: a combined decision needs feeds >= 2"
            )
        if decision == "single":
            feeds = None

        decisions[rr_telecast_id] = CombinedDecision(
            rr_telecast_id=rr_telecast_id,
            decision=decision,  # type: ignore[arg-type]
            feeds=feeds,
            reason=reason,  # type: ignore[arg-type]
        )
    return decisions


def _decision_row(decision: CombinedDecision) -> dict[str, str]:
    return {
        "rr_telecast_id": decision.rr_telecast_id,
        "decision": decision.decision,
        "feeds": str(decision.feeds) if decision.feeds is not None else "",
        "reason": decision.reason,
    }


def _alt_feed_counts(listing_links: pl.DataFrame) -> dict[int, int]:
    if listing_links.height == 0:
        return {}
    counts: dict[int, int] = {}
    other = listing_links.filter(pl.col("feed_kind") != "main")
    for row in other.select("game_id").iter_rows(named=True):
        counts[row["game_id"]] = counts.get(row["game_id"], 0) + 1
    return counts


def _network_season_medians(telecasts: pl.DataFrame) -> dict[tuple[int, str], float]:
    plotted = telecasts.filter(pl.col("plotted"))
    if plotted.height == 0:
        return {}
    grouped = plotted.group_by(["season", "network_id"]).agg(
        pl.col("headline_value").median().alias("median"),
        pl.col("headline_value").count().alias("n"),
    )
    medians: dict[tuple[int, str], float] = {}
    for row in grouped.iter_rows(named=True):
        if row["n"] >= MIN_NETWORK_SEASON_TELECASTS and row["network_id"] is not None:
            medians[(row["season"], row["network_id"])] = row["median"]
    return medians


def find_combined_candidates(
    telecasts: pl.DataFrame,
    viewership: pl.DataFrame,
    listing_links: pl.DataFrame,
) -> list[CombinedCandidate]:
    """Every rated main telecast, not already combined via RR's own
    composite_of (build.telecasts already sets combined_feeds for those),
    whose game has an alt-cast/Spanish 506 listing (`alt_listed`) or whose
    headline figure is a network-season outlier (`outlier`) -- D-09's two
    review sources. A telecast with no linked RR record (no rr_telecast_id
    to key a decision on) is never a candidate. `alt_listed` proposes
    "combined" across 1 + the game's alt/Spanish listing count; `outlier`
    alone proposes "single", left for the user to judge.
    """
    del viewership  # headline values already live on `telecasts`; kept for interface symmetry.

    if telecasts.height == 0:
        return []

    alt_feed_counts = _alt_feed_counts(listing_links)
    medians = _network_season_medians(telecasts)

    candidates: list[CombinedCandidate] = []
    rated_main = telecasts.filter(
        (pl.col("feed_type") == "main") & pl.col("rated") & pl.col("combined_feeds").is_null()
    )
    for row in rated_main.iter_rows(named=True):
        rr_ids = row["rr_telecast_ids"] or []
        if not rr_ids:
            continue

        reasons: list[str] = []
        alt_feed_count = alt_feed_counts.get(row["game_id"], 0)
        if alt_feed_count > 0:
            reasons.append("alt_listed")

        network_median = medians.get((row["season"], row["network_id"]))
        headline_value = row["headline_value"]
        if (
            network_median is not None
            and headline_value is not None
            and network_median > 0
            and headline_value > OUTLIER_FACTOR * network_median
        ):
            reasons.append("outlier")

        if not reasons:
            continue

        proposed: Decision = "combined" if "alt_listed" in reasons else "single"
        proposed_feeds = 1 + alt_feed_count if proposed == "combined" else None

        candidates.append(
            CombinedCandidate(
                rr_telecast_id=rr_ids[0],
                telecast_id=row["telecast_id"],
                season=row["season"],
                date_et=row["date_et"],
                network_id=row["network_id"],
                reasons=tuple(reasons),
                alt_feed_count=alt_feed_count,
                headline_value=headline_value,
                network_median=network_median,
                proposed=proposed,
                proposed_feeds=proposed_feeds,
            )
        )

    candidates.sort(key=lambda c: c.rr_telecast_id)
    return candidates


def apply_combined(
    telecasts: pl.DataFrame,
    telecast_flags: pl.DataFrame,
    candidates: Sequence[CombinedCandidate],
    decisions: Mapping[str, CombinedDecision],
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Fold every decided candidate into `telecasts.combined_feeds` (set for
    "combined", cleared for "single") and add a `telecast_flags` "combined"
    row for every telecast whose combined_feeds is set that doesn't already
    carry one (build.viewership.apply_headlines already flags an RR-field
    combined telecast; this only adds the ones this module's own decisions
    newly combine).
    """
    updates: dict[str, int | None] = {}
    for candidate in candidates:
        decision = decisions.get(candidate.rr_telecast_id)
        if decision is None:
            continue
        updates[candidate.telecast_id] = decision.feeds if decision.decision == "combined" else None

    if updates:
        updated_ids = list(updates.keys())
        updates_frame = pl.DataFrame(
            {"telecast_id": updated_ids, "_new_combined_feeds": list(updates.values())},
            schema={"telecast_id": pl.Utf8, "_new_combined_feeds": pl.Int32},
        )
        telecasts = (
            telecasts.join(updates_frame, on="telecast_id", how="left")
            .with_columns(
                pl.when(pl.col("telecast_id").is_in(updated_ids))
                .then(pl.col("_new_combined_feeds"))
                .otherwise(pl.col("combined_feeds"))
                .alias("combined_feeds")
            )
            .drop("_new_combined_feeds")
        )
        if telecasts.height:
            telecasts = telecasts.sort("telecast_id")

    already_flagged = set(
        telecast_flags.filter(pl.col("flag_id") == "combined")["telecast_id"].to_list()
    )
    new_flag_rows = [
        {"telecast_id": telecast_id, "flag_id": "combined", "kind": "combined"}
        for telecast_id, feeds in updates.items()
        if feeds is not None and telecast_id not in already_flagged
    ]
    if new_flag_rows:
        telecast_flags = pl.concat(
            [telecast_flags, pl.DataFrame(new_flag_rows, schema=dict(telecast_flags.schema))]
        )
        telecast_flags = telecast_flags.sort(["telecast_id", "flag_id"])

    return telecasts, telecast_flags


def _classify_reason(
    candidate: CombinedCandidate,
    telecast_pointers: Mapping[str, tuple[int, str | None]],
    listings_by_pointer: Mapping[tuple[int, str], Listing506],
) -> Reason:
    if candidate.alt_feed_count >= 2:
        reason: Reason = "megacast"
    else:
        reason = "alt-cast-simulcast"

    key = telecast_pointers.get(candidate.telecast_id)
    if key is not None:
        season, pointer = key
        listing = listings_by_pointer.get((season, pointer)) if pointer is not None else None
        if (
            listing is not None
            and listing.game_label is not None
            and any(marker in listing.game_label.lower() for marker in _TITLE_GAME_MARKERS)
        ):
            reason = "title-game"
    return reason


def main(argv: Sequence[str] | None = None) -> None:
    # Imported inside main, not at module level: build.tables imports this
    # module (to wire find_combined_candidates/apply_combined into
    # assemble_tables), so a module-level import here would cycle.
    from booth_review.build.tables import assemble_tables

    parser = argparse.ArgumentParser(
        description="Detect combined-figure candidates and pre-fill likely decisions."
    )
    parser.parse_args(argv)

    paths = DataPaths.from_env()
    ref_dir = reference_dir()
    tables = assemble_tables(paths, ref_dir)

    columns, rows = tables.review_rows["review_combined"]
    write_review_csv(paths.interim / "review_combined.csv", columns, rows)

    candidates = find_combined_candidates(tables.telecasts, tables.viewership, tables.listing_links)
    decisions = load_combined_figures(ref_dir)

    sources = load_all_sources(paths)
    listings_by_pointer: dict[tuple[int, str], Listing506] = {
        (season_sources.season, pointer_for_listing(listing)): listing
        for season_sources in sources
        for listing in season_sources.listings
    }
    telecast_pointers: dict[str, tuple[int, str | None]] = {
        row["telecast_id"]: (row["season"], row["s506_pointer"])
        for row in tables.telecasts.select("telecast_id", "season", "s506_pointer").iter_rows(
            named=True
        )
    }

    new_decisions = dict(decisions)
    reason_counts: Counter[str] = Counter()
    decision_counts: Counter[str] = Counter()
    for candidate in candidates:
        reason_counts["|".join(candidate.reasons)] += 1

        existing = new_decisions.get(candidate.rr_telecast_id)
        if existing is not None:
            decision_counts[existing.decision] += 1
            continue
        if "alt_listed" not in candidate.reasons:
            decision_counts["undecided"] += 1
            continue

        reason = _classify_reason(candidate, telecast_pointers, listings_by_pointer)
        new_decisions[candidate.rr_telecast_id] = CombinedDecision(
            rr_telecast_id=candidate.rr_telecast_id,
            decision="combined",
            feeds=candidate.proposed_feeds,
            reason=reason,
        )
        decision_counts["combined"] += 1

    if new_decisions != decisions:
        write_reference_csv(
            ref_dir / "combined_figures.csv",
            COMBINED_COLUMNS,
            [
                _decision_row(d)
                for d in sorted(new_decisions.values(), key=lambda d: d.rr_telecast_id)
            ],
        )

    print(f"combined candidates by reason: {dict(sorted(reason_counts.items()))}")
    print(f"decisions: {dict(sorted(decision_counts.items()))}")


if __name__ == "__main__":
    main()
