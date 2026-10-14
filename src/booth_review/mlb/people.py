"""MLB announcer names to shared-people ids.

Same discipline as the NFL module: a plain build never writes people.csv. A dry
run writes `interim/review_mlb_people.csv` listing every unresolved announcer
name (from crews and from `mlb_booth_ranks.csv` rows that
`load_mlb_booth_ranks` returned as unresolved), and `apply` registers only the
rows the user marked `add`. New persons join with usual_role "unknown"; existing
persons are never modified. Errors and counts never carry names.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from booth_review.build.io import write_review_csv
from booth_review.config import DataPaths
from booth_review.mlb.reference import UnresolvedRankName
from booth_review.nfl.people import resolve_crew
from booth_review.people.normalize import is_placeholder
from booth_review.people.registry import PeopleRegistry, load_people, register_names, write_people
from booth_review.reference import read_reference_csv
from booth_review.resolve.names import csv_unsafe

__all__ = [
    "REVIEW_MLB_PEOPLE_COLUMNS",
    "MlbPeopleResult",
    "read_people_decisions",
    "register_mlb_people",
    "resolve_crew",
]

REVIEW_MLB_PEOPLE_COLUMNS = ("raw_name", "count", "decision")
_ADD = "add"
_IGNORED_DECISIONS = frozenset({"", "keep"})


@dataclass(frozen=True)
class MlbPeopleResult:
    counts: dict[str, int]
    unresolved: tuple[str, ...]


def review_path(paths: DataPaths) -> Path:
    return paths.interim / "review_mlb_people.csv"


def read_people_decisions(path: Path) -> tuple[tuple[str, ...], int]:
    """Names the user marked `add`, plus a count of invalid decision values."""
    adds: list[str] = []
    invalid = 0
    for row in read_reference_csv(path, REVIEW_MLB_PEOPLE_COLUMNS, required=False):
        decision = row["decision"].strip().casefold()
        if decision in _IGNORED_DECISIONS:
            continue
        if decision == _ADD:
            adds.append(csv_unsafe(row["raw_name"]))
        else:
            invalid += 1
    return tuple(adds), invalid


def register_mlb_people(
    paths: DataPaths,
    reference_dir: Path,
    crew_names: Iterable[str],
    rank_unresolved: Sequence[UnresolvedRankName] = (),
    *,
    apply: bool = False,
) -> MlbPeopleResult:
    registry: PeopleRegistry = load_people(reference_dir)
    name_counts: Counter[str] = Counter()
    for name in crew_names:
        if not is_placeholder(name):
            name_counts[name] += 1
    for entry in rank_unresolved:
        if not is_placeholder(entry.raw_name):
            name_counts[entry.raw_name] += 1
    unresolved = {n: c for n, c in name_counts.items() if registry.lookup(n) is None}
    ordered = tuple(sorted(unresolved))
    path = review_path(paths)

    if not apply:
        previous = {
            csv_unsafe(r["raw_name"]): r["decision"]
            for r in read_reference_csv(path, REVIEW_MLB_PEOPLE_COLUMNS, required=False)
        }
        rows = [
            {"raw_name": n, "count": unresolved[n], "decision": previous.get(n, "")}
            for n in ordered
        ]
        write_review_csv(path, REVIEW_MLB_PEOPLE_COLUMNS, rows)
        return MlbPeopleResult({"unresolved": len(ordered), "new_persons": 0}, ordered)

    adds, invalid = read_people_decisions(path)
    # Only marked names that are still unresolved reach register_names, which
    # would otherwise append variants to existing persons on its own.
    chosen = {n: max(unresolved.get(n, 1), 1) for n in adds if registry.lookup(n) is None}
    new_persons = 0
    if chosen:
        updated = register_names(registry, chosen)
        new_persons = len(updated.persons) - len(registry.persons)
        if new_persons:
            write_people(reference_dir, updated)
    return MlbPeopleResult(
        {"unresolved": len(ordered), "new_persons": new_persons, "invalid_decisions": invalid},
        ordered,
    )
