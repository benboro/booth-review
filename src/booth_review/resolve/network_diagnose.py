"""Read-only outlet inventory and network-combination diagnostic for JOIN-06.

Reads only cached raw/ files (506 week pages via load_506_listings, RR
telecast records via load_rr_records, CFBD media via parse_media) and
data/reference/networks.csv; sends no request. Writes only
interim/review_networks.csv (never committed by this module -- Plan 11's
build commits the vault's interim/ artifacts, same pattern as
resolve/diagnose.py). Printed output is network ids, outlet strings, and
counts only (T-03-25): no crew, no game matchup, no viewership figure.

CFBD's /games/media rows are scoped to FBS-involving games (JOIN-07's own
is_fbs_game rule, joined on CFBD's own game id -- media.id is always a CFBD
game id, not a name match, so this isn't the crosswalk-based JOIN-01/02
matching the plan's "no game matching needed here" note refers to).
Unscoped, the 2026 in-season file alone adds ~80 small-conference/DIII
streaming-channel outlet strings (e.g. school-branded ".com" domains) for
games with no FBS side at all -- entirely out of this project's scope
(AGENTS.md/JOIN-07) and never a telecast this project would plot.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from booth_review.config import DataPaths
from booth_review.reference import reference_dir
from booth_review.resolve.games import is_fbs_game
from booth_review.resolve.inputs import (
    load_506_listings,
    load_cfbd_games,
    load_rr_records,
    vault_seasons,
)
from booth_review.resolve.names import csv_safe
from booth_review.resolve.networks import (
    NetworkTable,
    load_networks,
    primary_network,
    split_outlets,
    strip_feed_marker,
)
from booth_review.sources.cfbd.parser import parse_media
from booth_review.transport.cache import atomic_write_bytes

REVIEW_COLUMNS = ("source", "outlet", "occurrences", "season_first", "season_last", "network_id")

_TOP_COMBINATIONS = 40


@dataclass
class _Usage:
    occurrences: int = 0
    season_first: int | None = None
    season_last: int | None = None

    def add(self, season: int) -> None:
        self.occurrences += 1
        self.season_first = season if self.season_first is None else min(self.season_first, season)
        self.season_last = season if self.season_last is None else max(self.season_last, season)


@dataclass(frozen=True)
class OutletUsageRow:
    source: str
    outlet: str
    occurrences: int
    season_first: int
    season_last: int
    network_id: str


@dataclass(frozen=True)
class CombinationRow:
    outlets: tuple[str, ...]
    primary_network_id: str | None
    count: int


@dataclass(frozen=True)
class NetworkDiagnostic:
    usage_rows: tuple[OutletUsageRow, ...]
    rr_parse_errors: int
    combinations: tuple[CombinationRow, ...]
    neutral_counts: dict[str, int]
    bowl_counts: dict[str, int]


def _collect_usage(paths: DataPaths) -> tuple[dict[tuple[str, str], _Usage], int]:
    """Every distinct (source, outlet) string observed in the cached vault,
    with occurrence counts and the first/last season it appeared in.
    """
    usage: dict[tuple[str, str], _Usage] = {}
    rr_parse_errors = 0

    for season in vault_seasons(paths):
        for listing in load_506_listings(paths, season):
            if not listing.network_raw:
                continue
            for part in split_outlets(listing.network_raw):
                base, _feed = strip_feed_marker(part)
                usage.setdefault(("sports506", base), _Usage()).add(season)

        records, errors = load_rr_records(paths, season)
        rr_parse_errors += errors
        for record in records:
            for entry in record.telecast.networks:
                for part in split_outlets(entry):
                    usage.setdefault(("ratingsref", part), _Usage()).add(season)

        media_path = paths.raw / "cfbd" / "media" / f"{season}.json"
        if media_path.is_file():
            fbs_game_ids = {g.id for g in load_cfbd_games(paths, season) if is_fbs_game(g)}
            for media in parse_media(media_path.read_bytes()):
                if not media.outlet or media.id not in fbs_game_ids:
                    continue
                usage.setdefault(("cfbd", media.outlet), _Usage()).add(season)

    return usage, rr_parse_errors


def _usage_rows(
    usage: dict[tuple[str, str], _Usage], table: NetworkTable
) -> tuple[OutletUsageRow, ...]:
    rows: list[OutletUsageRow] = []
    for (source, outlet), info in usage.items():
        assert info.season_first is not None
        assert info.season_last is not None
        row = table.lookup(outlet, info.season_last)
        if row is None:
            row = table.lookup(outlet, info.season_first)
        rows.append(
            OutletUsageRow(
                source=source,
                outlet=outlet,
                occurrences=info.occurrences,
                season_first=info.season_first,
                season_last=info.season_last,
                network_id=row.network_id if row is not None else "",
            )
        )
    rows.sort(key=lambda r: (r.source, r.outlet))
    return tuple(rows)


def _combinations_and_listing_counts(
    paths: DataPaths, table: NetworkTable
) -> tuple[Counter[tuple[tuple[str, ...], str | None]], dict[str, int], dict[str, int]]:
    combo_counts: Counter[tuple[tuple[str, ...], str | None]] = Counter()
    neutral_counts: dict[str, int] = {}
    bowl_counts: dict[str, int] = {}

    for season in vault_seasons(paths):
        for listing in load_506_listings(paths, season):
            if listing.feed_kind != "main" or not listing.network_raw:
                continue
            result = primary_network([listing.network_raw], season, table)
            key = (result.outlets, result.network_id)
            combo_counts[key] += 1
            primary_key = result.network_id or "(unmapped)"
            if listing.neutral:
                neutral_counts[primary_key] = neutral_counts.get(primary_key, 0) + 1
            if listing.game_label:
                bowl_counts[primary_key] = bowl_counts.get(primary_key, 0) + 1

        records, _errors = load_rr_records(paths, season)
        for record in records:
            if not record.telecast.networks:
                continue
            result = primary_network(list(record.telecast.networks), season, table)
            key = (result.outlets, result.network_id)
            combo_counts[key] += 1

    return combo_counts, neutral_counts, bowl_counts


def run_network_diagnostic(paths: DataPaths, ref_dir: Path) -> NetworkDiagnostic:
    table = load_networks(ref_dir)
    usage, rr_parse_errors = _collect_usage(paths)
    usage_rows = _usage_rows(usage, table)

    combo_counts, neutral_counts, bowl_counts = _combinations_and_listing_counts(paths, table)
    combinations = tuple(
        CombinationRow(outlets=outlets, primary_network_id=primary_id, count=count)
        for (outlets, primary_id), count in combo_counts.most_common(_TOP_COMBINATIONS)
    )

    return NetworkDiagnostic(
        usage_rows=usage_rows,
        rr_parse_errors=rr_parse_errors,
        combinations=combinations,
        neutral_counts=neutral_counts,
        bowl_counts=bowl_counts,
    )


def write_review(paths: DataPaths, diagnostic: NetworkDiagnostic) -> None:
    """Write interim/review_networks.csv. Rebuilt every run, not committed by
    this module (same pattern as resolve/diagnose.py's review files)."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(REVIEW_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in diagnostic.usage_rows:
        writer.writerow(
            {
                "source": row.source,
                "outlet": csv_safe(row.outlet),
                "occurrences": str(row.occurrences),
                "season_first": str(row.season_first),
                "season_last": str(row.season_last),
                "network_id": row.network_id,
            }
        )
    atomic_write_bytes(paths.interim / "review_networks.csv", buf.getvalue().encode("utf-8"))


def _distinct_by_source(rows: Iterable[OutletUsageRow]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts[row.source] += 1
    return counts


def _unmapped_by_source(
    rows: Iterable[OutletUsageRow],
) -> tuple[Counter[str], Counter[str]]:
    distinct: Counter[str] = Counter()
    occurrences: Counter[str] = Counter()
    for row in rows:
        if row.network_id:
            continue
        distinct[row.source] += 1
        occurrences[row.source] += row.occurrences
    return distinct, occurrences


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-write", action="store_true", help="Print counts only; skip writing review CSVs."
    )
    args = parser.parse_args(argv)

    paths = DataPaths.from_env()
    ref_dir = reference_dir()
    diagnostic = run_network_diagnostic(paths, ref_dir)
    if not args.no_write:
        write_review(paths, diagnostic)

    distinct_by_source = _distinct_by_source(diagnostic.usage_rows)
    mapped_ids = {row.network_id for row in diagnostic.usage_rows if row.network_id}
    unmapped_distinct, unmapped_occurrences = _unmapped_by_source(diagnostic.usage_rows)

    print(f"RR parse errors (skipped, not counted below): {diagnostic.rr_parse_errors}")
    print()

    print("distinct raw outlet strings by source:")
    for source, count in sorted(distinct_by_source.items()):
        print(f"  {source}: {count}")
    total_raw = sum(distinct_by_source.values())
    print(f"  total: {total_raw}")
    print()

    print(f"distinct mapped network ids (collapse count): {len(mapped_ids)}")
    print()

    print("unmapped outlet strings by source (distinct / total occurrences):")
    for source in sorted(set(unmapped_distinct) | set(unmapped_occurrences)):
        distinct_n = unmapped_distinct[source]
        occurrences_n = unmapped_occurrences[source]
        print(f"  {source}: {distinct_n} distinct, {occurrences_n} occurrences")
    if not unmapped_distinct and not unmapped_occurrences:
        print("  (none)")
    print()

    print(f"top outlet combinations by chosen primary (top {_TOP_COMBINATIONS} by count):")
    for combo in diagnostic.combinations:
        outlets = "+".join(combo.outlets) if combo.outlets else "(none)"
        primary = combo.primary_network_id or "(unmapped)"
        print(f"  {outlets} -> {primary}: {combo.count}")
    print()

    print("506 main-listing neutral-site rows by chosen primary:")
    for primary_id, count in sorted(diagnostic.neutral_counts.items()):
        print(f"  {primary_id}: {count}")
    print()

    print("506 main-listing labeled bowl/CFP rows by chosen primary:")
    for primary_id, count in sorted(diagnostic.bowl_counts.items()):
        print(f"  {primary_id}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
