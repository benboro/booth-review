"""Crew names to shared-people ids (D-13, D-16).

NFL-only people join people.csv as new persons with usual_role "unknown"; NFL
never reads usual_role (booth roles are positional), and a later CFB people
review that recomputes usual roles leaves these persons "unknown" (RESEARCH
Pitfall 5, resolved by design).

Existing persons are never modified automatically. A name that folds to an
existing person is returned as an ExistingPersonMatch for the people review CSV
(written by `nfl people` into the vault's interim/). A spelling is appended to
a person only for a row the user marked add-variant. A fold match that is really
a different person is settled through the existing people_reviewed.csv process,
never here. Errors and counts never carry names.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from booth_review.errors import ReferenceTableError
from booth_review.people.normalize import is_placeholder
from booth_review.people.registry import PeopleRegistry, load_people, register_names, write_people
from booth_review.reference import read_reference_csv
from booth_review.resolve.names import csv_unsafe

REVIEW_NFL_PEOPLE_COLUMNS = ("raw_name", "person_id", "count", "spelling_known", "decision")
_ADD_VARIANT = "add-variant"
_IGNORED_DECISIONS = frozenset({"", "keep"})


@dataclass(frozen=True)
class CrewResolution:
    pbp_person_id: str | None
    analyst_person_id: str | None
    sideline_person_ids: tuple[str, ...]
    unresolved_names: tuple[str, ...]


@dataclass(frozen=True)
class ExistingPersonMatch:
    raw_name: str
    person_id: str
    count: int
    spelling_known: bool


@dataclass(frozen=True)
class NflPeopleResult:
    counts: dict[str, int]
    existing_matches: tuple[ExistingPersonMatch, ...]


def resolve_crew(names: Sequence[str], registry: PeopleRegistry) -> CrewResolution:
    """Positional roles: 0 pbp, 1 analyst, the rest sideline. Placeholders are dropped first."""
    real = [name for name in names if not is_placeholder(name)]
    ids: list[str | None] = [registry.lookup(name) for name in real]
    unresolved = tuple(name for name, pid in zip(real, ids, strict=True) if pid is None)
    return CrewResolution(
        pbp_person_id=ids[0] if len(ids) > 0 else None,
        analyst_person_id=ids[1] if len(ids) > 1 else None,
        sideline_person_ids=tuple(pid for pid in ids[2:] if pid is not None),
        unresolved_names=unresolved,
    )


def register_nfl_people(
    reference_dir: Path,
    name_counts: Mapping[str, int],
    *,
    approved_variants: Mapping[str, str] | None = None,
    dry_run: bool = False,
) -> NflPeopleResult:
    registry = load_people(reference_dir)
    approvals = dict(approved_variants or {})

    existing: list[ExistingPersonMatch] = []
    unmatched: dict[str, int] = {}
    for name, count in name_counts.items():
        if is_placeholder(name):
            continue
        person_id = registry.lookup(name)
        if person_id is None:
            unmatched[name] = count
        else:
            known = name in registry.persons[person_id].variants
            existing.append(ExistingPersonMatch(name, person_id, count, known))

    # Only names with no existing person reach register_names, which would
    # otherwise append variants to existing persons on its own.
    updated = register_names(registry, unmatched) if unmatched else registry
    new_persons = len(updated.persons) - len(registry.persons)

    persons = dict(updated.persons)
    expected_extra: dict[str, list[str]] = {}
    invalid = 0
    for name, person_id in approvals.items():
        if registry.lookup(name) != person_id or person_id not in persons:
            invalid += 1
            continue
        person = persons[person_id]
        if name in person.variants:
            continue
        persons[person_id] = replace(person, variants=(*person.variants, name))
        expected_extra.setdefault(person_id, []).append(name)
    new_variants = sum(len(v) for v in expected_extra.values())
    final = PeopleRegistry(persons)

    for person_id, before in registry.persons.items():
        after = final.persons.get(person_id)
        wanted = replace(
            before, variants=before.variants + tuple(expected_extra.get(person_id, ()))
        )
        if after != wanted:
            raise ReferenceTableError(
                "people: an existing person changed unexpectedly during NFL registration"
            )

    if (new_persons or new_variants) and not dry_run:
        write_people(reference_dir, final)

    counts = {
        "new_persons": new_persons,
        "new_variants": new_variants,
        "existing_matches": len(existing),
        "invalid_decisions": invalid,
    }
    return NflPeopleResult(counts=counts, existing_matches=tuple(existing))


def read_people_decisions(path: Path) -> tuple[dict[str, str], int]:
    """Approved add-variant rows (raw_name -> person_id) plus a count of invalid decision values."""
    approvals: dict[str, str] = {}
    invalid = 0
    for row in read_reference_csv(path, REVIEW_NFL_PEOPLE_COLUMNS, required=False):
        decision = row["decision"].strip().casefold()
        if decision in _IGNORED_DECISIONS:
            continue
        if decision == _ADD_VARIANT:
            approvals[csv_unsafe(row["raw_name"])] = row["person_id"]
        else:
            invalid += 1
    return approvals, invalid
