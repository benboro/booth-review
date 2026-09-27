"""The scan/apply review tool for the people layer (JOIN-03).

`scan` reads every cached 506 crew name, registers every non-placeholder
name into the public people registry (data/reference/people.csv), recomputes
usual roles from main-feed two-person crews, and writes a vault review file
(data/vault/interim/review_people.csv) of suspicious name pairs with a
proposed decision each. `apply` reads that review file (a user-edited
decision if present, else the proposed one), updates people.csv and
people_reviewed.csv, and is idempotent. Printed output is counts only --
never a name (T-03-21).
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from booth_review.config import DataPaths
from booth_review.people.grouping import (
    Appearance,
    NameStats,
    SuspiciousPair,
    find_suspicious_pairs,
    propose_decision,
)
from booth_review.people.normalize import fold_person, is_placeholder
from booth_review.people.registry import (
    PeopleRegistry,
    ReviewedPair,
    apply_decisions,
    load_people,
    load_person_overrides,
    load_reviewed,
    register_names,
    with_usual_roles,
    write_people,
    write_reviewed,
)
from booth_review.people.roles import infer_usual_roles
from booth_review.reference import reference_dir
from booth_review.resolve.inputs import load_506_listings, vault_seasons
from booth_review.resolve.names import csv_safe, csv_unsafe
from booth_review.transport.cache import atomic_write_bytes

REVIEW_PEOPLE_COLUMNS = (
    "pair_id",
    "reason",
    "name_a",
    "name_b",
    "count_a",
    "count_b",
    "seasons_a",
    "seasons_b",
    "networks_a",
    "networks_b",
    "proposed",
    "decision",
    "note",
)

_DECISIONS = frozenset({"same", "different", "one"})


@dataclass(frozen=True)
class CollectResult:
    stats: dict[str, NameStats]
    raw_counts: dict[str, int]
    names_total: int
    placeholders_skipped: int


@dataclass(frozen=True)
class ScanSummary:
    names_total: int
    placeholders_skipped: int
    persons: int
    new_persons: int
    pairs_by_reason: dict[str, int]


@dataclass(frozen=True)
class ApplySummary:
    pairs_applied: int
    decisions_by_kind: dict[str, int]
    persons: int


def collect_name_stats(paths: DataPaths) -> CollectResult:
    """Every crew name across every cached 506 season/week (all feeds:
    main, alt-cast, Spanish, unknown). A placeholder ("TBA", ...) is
    excluded from `stats`/`raw_counts` but counted in `placeholders_skipped`.
    """
    raw_spellings: dict[str, set[str]] = {}
    raw_counts: dict[str, int] = {}
    counts: dict[str, int] = {}
    seasons_by_fold: dict[str, set[int]] = {}
    networks_by_fold: dict[str, Counter[str]] = {}
    appearances_by_fold: dict[str, list[Appearance]] = {}

    names_total = 0
    placeholders_skipped = 0

    for season in vault_seasons(paths):
        for listing in load_506_listings(paths, season):
            crew_folded = tuple(fold_person(n) for n in listing.crew_names if not is_placeholder(n))
            for name in listing.crew_names:
                names_total += 1
                if is_placeholder(name):
                    placeholders_skipped += 1
                    continue
                folded = fold_person(name)
                raw_spellings.setdefault(folded, set()).add(name)
                raw_counts[name] = raw_counts.get(name, 0) + 1
                counts[folded] = counts.get(folded, 0) + 1
                seasons_by_fold.setdefault(folded, set()).add(season)
                if listing.network_raw:
                    networks_by_fold.setdefault(folded, Counter())[listing.network_raw] += 1
                appearances_by_fold.setdefault(folded, []).append(
                    Appearance(
                        date_et=listing.date_et,
                        kickoff_et=listing.kickoff_et,
                        network_raw=listing.network_raw,
                        crew_folded=crew_folded,
                    )
                )

    stats = {
        folded: NameStats(
            raw_spellings=tuple(sorted(spellings)),
            folded=folded,
            count=counts[folded],
            seasons=frozenset(seasons_by_fold[folded]),
            networks=networks_by_fold.get(folded, Counter()),
            appearances=tuple(appearances_by_fold[folded]),
        )
        for folded, spellings in raw_spellings.items()
    }
    return CollectResult(
        stats=stats,
        raw_counts=raw_counts,
        names_total=names_total,
        placeholders_skipped=placeholders_skipped,
    )


def _main_feed_crews(paths: DataPaths, registry: PeopleRegistry) -> list[tuple[str, ...]]:
    """One person_id tuple per main-feed listing whose every crew name (once
    placeholders are dropped) resolves to a registered person -- the input
    infer_usual_roles needs. A listing with any unresolved name is skipped
    rather than guessed.
    """
    crews: list[tuple[str, ...]] = []
    for season in vault_seasons(paths):
        for listing in load_506_listings(paths, season):
            if listing.feed_kind != "main":
                continue
            names = [n for n in listing.crew_names if not is_placeholder(n)]
            if not names:
                continue
            person_ids = [registry.lookup(n) for n in names]
            if all(pid is not None for pid in person_ids):
                crews.append(tuple(pid for pid in person_ids if pid is not None))
    return crews


def _format_seasons(seasons: frozenset[int]) -> str:
    return "|".join(str(s) for s in sorted(seasons))


def _format_networks(networks: Counter[str]) -> str:
    return "|".join(sorted(networks))


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    atomic_write_bytes(path, buf.getvalue().encode("utf-8"))


def _write_review_people(paths: DataPaths, pairs: Sequence[SuspiciousPair]) -> None:
    rows: list[dict[str, str]] = []
    for pair_id, pair in enumerate(pairs, start=1):
        rows.append(
            {
                "pair_id": str(pair_id),
                "reason": pair.reason,
                "name_a": csv_safe(pair.name_a),
                "name_b": csv_safe(pair.name_b),
                "count_a": str(pair.stats_a.count),
                "count_b": str(pair.stats_b.count),
                "seasons_a": _format_seasons(pair.stats_a.seasons),
                "seasons_b": _format_seasons(pair.stats_b.seasons),
                "networks_a": csv_safe(_format_networks(pair.stats_a.networks)),
                "networks_b": csv_safe(_format_networks(pair.stats_b.networks)),
                "proposed": propose_decision(pair),
                "decision": "",
                "note": "",
            }
        )
    _write_csv(paths.interim / "review_people.csv", REVIEW_PEOPLE_COLUMNS, rows)


def _read_review_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def scan(paths: DataPaths, ref_dir: Path) -> ScanSummary:
    existing_registry = load_people(ref_dir)
    existing_ids = set(existing_registry.persons.keys())

    result = collect_name_stats(paths)
    registry = register_names(existing_registry, result.raw_counts)

    usual = infer_usual_roles(_main_feed_crews(paths, registry))
    registry = with_usual_roles(registry, usual)
    write_people(ref_dir, registry)

    reviewed_folded = {
        frozenset((fold_person(pair.name_a), fold_person(pair.name_b)))
        for pair in load_reviewed(ref_dir)
    }
    pairs = find_suspicious_pairs(result.stats, reviewed_folded, registry)
    _write_review_people(paths, pairs)

    new_persons = len(set(registry.persons) - existing_ids)
    pairs_by_reason: Counter[str] = Counter(pair.reason for pair in pairs)

    return ScanSummary(
        names_total=result.names_total,
        placeholders_skipped=result.placeholders_skipped,
        persons=len(registry.persons),
        new_persons=new_persons,
        pairs_by_reason=dict(pairs_by_reason),
    )


def apply(paths: DataPaths, ref_dir: Path) -> ApplySummary:
    review_path = paths.interim / "review_people.csv"
    raw_rows = _read_review_rows(review_path)

    registry = load_people(ref_dir)
    result = collect_name_stats(paths)

    by_key: dict[frozenset[str], ReviewedPair] = {
        frozenset((fold_person(pair.name_a), fold_person(pair.name_b))): pair
        for pair in load_reviewed(ref_dir)
    }

    decisions_by_kind: Counter[str] = Counter()
    for row in raw_rows:
        name_a = csv_unsafe(row["name_a"])
        name_b = csv_unsafe(row["name_b"])
        decision = row["decision"].strip() or row["proposed"].strip()
        if decision not in _DECISIONS:
            continue
        pair = ReviewedPair(name_a=name_a, name_b=name_b, reason=row["reason"], decision=decision)  # type: ignore[arg-type]
        by_key[frozenset((fold_person(name_a), fold_person(name_b)))] = pair
        decisions_by_kind[decision] += 1

    reviewed_pairs = list(by_key.values())
    override_ids = {o.person_id for o in load_person_overrides(ref_dir)}
    registry = apply_decisions(
        registry, reviewed_pairs, result.raw_counts, protected_ids=override_ids
    )

    # A merge/split changes which crews a person_id's appearances resolve
    # to, so usual roles (computed by scan() against the pre-decision
    # registry) must be recomputed here too -- otherwise a merged person
    # keeps whichever side's usual_role happened to survive the merge
    # (registry.apply_decisions keeps name_a's role field verbatim), even
    # when the losing side had far more two-person-crew evidence.
    usual = infer_usual_roles(_main_feed_crews(paths, registry))
    registry = with_usual_roles(registry, usual)

    write_people(ref_dir, registry)
    write_reviewed(ref_dir, reviewed_pairs)

    return ApplySummary(
        pairs_applied=len(raw_rows),
        decisions_by_kind=dict(decisions_by_kind),
        persons=len(registry.persons),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("scan", help="Register every 506 crew name and propose suspicious pairs.")
    subparsers.add_parser("apply", help="Apply the review file's decisions to the registry.")
    args = parser.parse_args(argv)

    paths = DataPaths.from_env()
    ref_dir = reference_dir()

    if args.command == "scan":
        summary = scan(paths, ref_dir)
        print(f"names: {summary.names_total} total, {summary.placeholders_skipped} placeholders")
        print(f"persons: {summary.persons} ({summary.new_persons} new)")
        print(f"suspicious pairs by reason: {dict(sorted(summary.pairs_by_reason.items()))}")
    else:
        apply_summary = apply(paths, ref_dir)
        print(f"pairs applied: {apply_summary.pairs_applied}")
        print(f"decisions by kind: {dict(sorted(apply_summary.decisions_by_kind.items()))}")
        print(f"persons: {apply_summary.persons}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
