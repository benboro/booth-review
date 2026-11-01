"""People helpers shared by the backup-crew passes (ESPN Press Room, Awful Announcing).

Both passes fold a source's names onto people.csv plus the persons the 506 pass
already added, and register unknown names as provisional persons (Phase 3
D-01/D-02). Nothing here reads a source; failures are count-only.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

import polars as pl

from booth_review.people.registry import PeopleRegistry, Person, register_names
from booth_review.people.roles import Role


def working_registry(registry: PeopleRegistry, people: pl.DataFrame) -> PeopleRegistry:
    """people.csv plus every person the 506 pass already added (provisional
    persons included), so a backup name reuses the same person_id."""
    persons: dict[str, Person] = dict(registry.persons)
    for row in people.iter_rows(named=True):
        person_id = row["person_id"]
        if person_id in persons:
            continue
        role: Role = "pbp" if row["usual_role"] == "pbp" else "unknown"
        if row["usual_role"] == "analyst":
            role = "analyst"
        persons[person_id] = Person(
            person_id=person_id,
            canonical_name=row["canonical_name"],
            variants=tuple(row["variants"] or (row["canonical_name"],)),
            usual_role=role,
            role_override=None,
        )
    return PeopleRegistry(persons)


def register_provisional(
    working: PeopleRegistry,
    name_counts: Counter[str],
    name_seasons: Mapping[str, tuple[int, int]],
) -> tuple[PeopleRegistry, list[str], list[dict[str, object]], list[dict[str, object]]]:
    """Register the unknown names. Returns (registry, new person ids,
    review_people_new rows, people-table rows), the rows sorted/ordered by id."""
    ids_before = set(working.persons)
    if name_counts:
        working = register_names(working, dict(name_counts))
    new_ids = sorted(set(working.persons) - ids_before)
    new_name_rows: list[dict[str, object]] = []
    people_rows: list[dict[str, object]] = []
    for person_id in new_ids:
        person = working.persons[person_id]
        seasons = [name_seasons[v] for v in person.variants if v in name_seasons]
        new_name_rows.append(
            {
                "name": person.canonical_name,
                "occurrences": sum(name_counts[v] for v in person.variants if v in name_counts),
                "season_first": min(lo for lo, _ in seasons) if seasons else None,
                "season_last": max(hi for _, hi in seasons) if seasons else None,
                "provisional_id": person_id,
            }
        )
        people_rows.append(
            {
                "person_id": person_id,
                "canonical_name": person.canonical_name,
                "variants": sorted(person.variants),
                "usual_role": person.usual_role,
                "registered": False,
            }
        )
    return working, new_ids, new_name_rows, people_rows
