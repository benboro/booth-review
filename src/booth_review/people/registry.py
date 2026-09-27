"""The public people registry (JOIN-03, D-01, D-05): person_id -> canonical
name, name variants, and role.

An id is never renamed once assigned: merging two ids after launch would
break shared URLs (SITE-12), so avoid it. Every table here is names-only
(D-05): no game-level row (who called which game) is ever written to
people.csv or people_reviewed.csv.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from booth_review.errors import ReferenceTableError
from booth_review.people.normalize import fold_person
from booth_review.people.roles import Role
from booth_review.people.slugs import assign_slug, slugify
from booth_review.reference import read_reference_csv, write_reference_csv
from booth_review.resolve.names import csv_safe, csv_unsafe

PEOPLE_COLUMNS = ("person_id", "canonical_name", "variants", "usual_role", "role_override")
REVIEWED_COLUMNS = ("name_a", "name_b", "reason", "decision")
PERSON_OVERRIDE_COLUMNS = ("season", "pointer", "position", "person_id", "reason")

Decision = Literal["same", "different", "one"]
_DECISIONS: frozenset[str] = frozenset({"same", "different", "one"})
_ROLES: frozenset[str] = frozenset({"pbp", "analyst", "unknown"})
_OVERRIDE_REASONS: frozenset[str] = frozenset({"two-people", "other"})
# people_reviewed.csv's fixed reason vocabulary (D-06): grouping.Reason's
# values, restated here because grouping imports this module.
REVIEW_REASONS: frozenset[str] = frozenset(
    {"suffix_only", "nickname", "similar_first", "near_spelling", "possible_two_people"}
)

# person_id: lowercase slug tokens joined by single hyphens (assign_slug's
# output shape).
_PERSON_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# person_overrides pointer: the sports506 "<week_label>:<source_row_index>"
# pointer format (resolve.overrides._SPORTS506_POINTER_RE), restated locally
# since that module models game overrides, not person overrides.
_POINTER_RE = re.compile(r"^([0-9]{1,2}|B):[0-9]+$")


@dataclass(frozen=True)
class Person:
    person_id: str
    canonical_name: str
    variants: tuple[str, ...]
    usual_role: Role
    role_override: Role | None


@dataclass(frozen=True)
class ReviewedPair:
    name_a: str
    name_b: str
    reason: str
    decision: Decision


@dataclass(frozen=True)
class PersonOverride:
    """One person_overrides.csv row: the crew slot at `position` of the 506
    listing at `pointer` (`<week_label>:<source_row_index>`) is `person_id`.

    `position` is 0-based and counts only real names: placeholder entries
    ("TBA" and the like) are removed from the listing's crew before
    counting, so it can differ from the raw 506 column order. The pointer is
    positional too -- re-importing a week page with rows added or removed
    shifts it, so re-check these rows after a `--force` re-import.
    """

    season: int
    pointer: str
    position: int
    person_id: str
    reason: str


def _pick_canonical(raw_names: Sequence[str], name_counts: Mapping[str, int]) -> str:
    """The most frequent raw spelling in `raw_names`, ties broken by lexical
    order. A name absent from `name_counts` counts as 0 (never a KeyError).
    """
    return sorted(raw_names, key=lambda n: (-name_counts.get(n, 0), n))[0]


class PeopleRegistry:
    """An immutable snapshot of the people table: every mutation
    (register_names, apply_decisions, with_usual_roles) returns a new
    PeopleRegistry rather than mutating this one.
    """

    def __init__(self, persons: Mapping[str, Person]) -> None:
        self.persons: dict[str, Person] = dict(persons)
        self._by_variant: dict[str, str] = {}
        for person in self.persons.values():
            for variant in person.variants:
                self._by_variant[fold_person(variant)] = person.person_id

    def lookup(self, name: str) -> str | None:
        """The person_id whose variants include `name` after fold_person
        normalization, or None.
        """
        return self._by_variant.get(fold_person(name))

    def to_rows(self) -> list[dict[str, str]]:
        """A row per person, ready for write_reference_csv. canonical_name
        and every variant pass through csv_safe (T-03-19-style protection):
        both are scraped 506 crew text, written automatically by
        register_names, never reviewed by a human before this write, so a
        name that happens to start with =, +, -, @, a tab, or a carriage
        return must not corrupt (or, via read_reference_csv's strict
        rejection, make unreadable) this public table. Pairs with
        csv_unsafe() in load_people.
        """
        rows: list[dict[str, str]] = []
        for person in sorted(self.persons.values(), key=lambda p: p.person_id):
            rows.append(
                {
                    "person_id": person.person_id,
                    "canonical_name": csv_safe(person.canonical_name),
                    "variants": "|".join(csv_safe(v) for v in sorted(person.variants)),
                    "usual_role": person.usual_role,
                    "role_override": person.role_override or "",
                }
            )
        return rows


def _validate_role(value: str, *, path_name: str, line_no: int, field: str) -> Role:
    if value not in _ROLES:
        raise ReferenceTableError(f"{path_name}: line {line_no}: invalid {field} {value!r}")
    return value  # type: ignore[return-value]


def load_people(reference_dir: Path) -> PeopleRegistry:
    """Read people.csv (not required: an empty/missing table is a fresh
    registry). Raises ReferenceTableError on a duplicate person_id, a
    person_id not matching the slug pattern, a normalized variant owned by
    two people, a canonical_name missing from its own variants list, a
    variant containing the "|" delimiter (defense against a hand-edited
    file corrupting the pipe-joined column), or a role (usual_role or
    role_override) outside pbp|analyst|unknown (role_override may also be
    blank, meaning "no override").
    """
    path = reference_dir / "people.csv"
    raw_rows = read_reference_csv(path, PEOPLE_COLUMNS, required=False)

    persons: dict[str, Person] = {}
    variant_owner: dict[str, str] = {}
    for line_no, raw in enumerate(raw_rows, start=2):
        person_id = raw["person_id"]
        if not _PERSON_ID_RE.match(person_id):
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: invalid person_id {person_id!r}"
            )
        if person_id in persons:
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: duplicate person_id {person_id!r}"
            )

        variants = tuple(csv_unsafe(v) for v in raw["variants"].split("|") if v)
        for variant in variants:
            if "|" in variant:
                raise ReferenceTableError(
                    f"{path.name}: line {line_no}: variant {variant!r} contains '|'"
                )
            key = fold_person(variant)
            owner = variant_owner.get(key)
            if owner is not None and owner != person_id:
                raise ReferenceTableError(
                    f"{path.name}: line {line_no}: variant {variant!r} already owned by {owner!r}"
                )
            variant_owner[key] = person_id

        canonical_name = csv_unsafe(raw["canonical_name"])
        if canonical_name not in variants:
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: canonical_name {canonical_name!r} missing "
                "from variants"
            )

        usual_role = _validate_role(
            raw["usual_role"] or "unknown", path_name=path.name, line_no=line_no, field="usual_role"
        )
        role_override_raw = raw["role_override"]
        role_override: Role | None = None
        if role_override_raw:
            role_override = _validate_role(
                role_override_raw, path_name=path.name, line_no=line_no, field="role_override"
            )

        persons[person_id] = Person(
            person_id=person_id,
            canonical_name=canonical_name,
            variants=variants,
            usual_role=usual_role,
            role_override=role_override,
        )
    return PeopleRegistry(persons)


def write_people(reference_dir: Path, registry: PeopleRegistry) -> None:
    """Write people.csv, refusing (ReferenceTableError, before anything is
    written) a registry load_people would reject for a canonical_name missing
    from its own variants -- a bad registry is never committed to the public
    table.
    """
    broken = sorted(
        person.person_id
        for person in registry.persons.values()
        if person.canonical_name not in person.variants
    )
    if broken:
        raise ReferenceTableError(
            f"people.csv: canonical_name missing from variants for {len(broken)} person_id(s): "
            + ", ".join(broken)
        )
    write_reference_csv(reference_dir / "people.csv", PEOPLE_COLUMNS, registry.to_rows())


def load_reviewed(reference_dir: Path) -> list[ReviewedPair]:
    """Read people_reviewed.csv (not required). Raises ReferenceTableError on
    a decision outside same|different|one or a reason outside REVIEW_REASONS.
    name_a/name_b pass through csv_unsafe (see write_reviewed).
    """
    path = reference_dir / "people_reviewed.csv"
    raw_rows = read_reference_csv(path, REVIEWED_COLUMNS, required=False)

    pairs: list[ReviewedPair] = []
    for line_no, raw in enumerate(raw_rows, start=2):
        decision = raw["decision"]
        if decision not in _DECISIONS:
            raise ReferenceTableError(f"{path.name}: line {line_no}: invalid decision {decision!r}")
        if raw["reason"] not in REVIEW_REASONS:
            raise ReferenceTableError(f"{path.name}: line {line_no}: invalid reason")
        pairs.append(
            ReviewedPair(
                name_a=csv_unsafe(raw["name_a"]),
                name_b=csv_unsafe(raw["name_b"]),
                reason=raw["reason"],
                decision=decision,  # type: ignore[arg-type]
            )
        )
    return pairs


def _ordered_pair(name_a: str, name_b: str) -> tuple[str, str]:
    """name_a <= name_b by fold order (D-02's storage convention), so a pair
    written twice in either original order lands on the same row.
    """
    return (name_a, name_b) if fold_person(name_a) <= fold_person(name_b) else (name_b, name_a)


def write_reviewed(reference_dir: Path, pairs: Sequence[ReviewedPair]) -> None:
    """name_a/name_b pass through csv_safe: like people.csv's canonical_name/
    variants, these are scraped 506 crew text that reach this public table
    without a human proofreading step, so a name starting with =, +, -, @, a
    tab, or a carriage return must not corrupt (or make unreadable) the
    file. Pairs with csv_unsafe() in load_reviewed. A reason outside
    REVIEW_REASONS raises ReferenceTableError before anything is written.
    """
    bad_reasons = sum(1 for pair in pairs if pair.reason not in REVIEW_REASONS)
    if bad_reasons:
        raise ReferenceTableError(
            f"people_reviewed.csv: {bad_reasons} pair(s) with a reason outside the fixed vocabulary"
        )
    ordered_pairs = []
    for pair in pairs:
        name_a, name_b = _ordered_pair(pair.name_a, pair.name_b)
        ordered_pairs.append(replace(pair, name_a=name_a, name_b=name_b))
    ordered_pairs.sort(key=lambda p: (fold_person(p.name_a), fold_person(p.name_b)))

    rows = [
        {
            "name_a": csv_safe(p.name_a),
            "name_b": csv_safe(p.name_b),
            "reason": p.reason,
            "decision": p.decision,
        }
        for p in ordered_pairs
    ]
    write_reference_csv(reference_dir / "people_reviewed.csv", REVIEWED_COLUMNS, rows)


def load_person_overrides(reference_dir: Path) -> list[PersonOverride]:
    """Read person_overrides.csv (not required). Raises ReferenceTableError
    on a non-integer season, a malformed pointer, a position outside 0-3, an
    invalid person_id slug, or a reason outside two-people|other.
    """
    path = reference_dir / "person_overrides.csv"
    raw_rows = read_reference_csv(path, PERSON_OVERRIDE_COLUMNS, required=False)

    overrides: list[PersonOverride] = []
    for line_no, raw in enumerate(raw_rows, start=2):
        try:
            season = int(raw["season"])
        except ValueError:
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: invalid season {raw['season']!r}"
            ) from None

        pointer = raw["pointer"]
        if not _POINTER_RE.match(pointer):
            raise ReferenceTableError(f"{path.name}: line {line_no}: malformed pointer {pointer!r}")

        try:
            position = int(raw["position"])
        except ValueError:
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: invalid position {raw['position']!r}"
            ) from None
        if not 0 <= position <= 3:
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: position out of range {position}"
            )

        person_id = raw["person_id"]
        if not _PERSON_ID_RE.match(person_id):
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: invalid person_id {person_id!r}"
            )

        reason = raw["reason"]
        if reason not in _OVERRIDE_REASONS:
            raise ReferenceTableError(f"{path.name}: line {line_no}: invalid reason {reason!r}")

        overrides.append(
            PersonOverride(
                season=season,
                pointer=pointer,
                position=position,
                person_id=person_id,
                reason=reason,
            )
        )
    return overrides


def check_person_override_ids(
    overrides: Sequence[PersonOverride], registry: PeopleRegistry
) -> None:
    """Raise ReferenceTableError when any person_overrides.csv row names a
    person_id that isn't in people.csv (`registry`), listing every missing
    id. An override must point at a registered person: an unknown id (a
    typo, or one a "same" merge deleted) would otherwise reach
    telecast_people with no people row behind it.
    """
    missing = sorted({o.person_id for o in overrides} - set(registry.persons))
    if missing:
        raise ReferenceTableError(
            f"person_overrides.csv: {len(missing)} person_id(s) not in people.csv: "
            + ", ".join(missing)
        )


def register_names(registry: PeopleRegistry, name_counts: Mapping[str, int]) -> PeopleRegistry:
    """Group `name_counts` (raw spelling -> occurrence count) by fold_person,
    then for each group: if any member already resolves to an existing
    person, append the group's not-yet-seen spellings as new variants of that
    person (its person_id never changes); otherwise register a brand new
    person (canonical = the group's most frequent raw spelling, ties by
    lexical order; id = assign_slug(slugify(canonical), ...)).
    """
    persons = dict(registry.persons)
    taken_ids = set(persons.keys())

    folded_groups: dict[str, list[str]] = {}
    for name in name_counts:
        folded_groups.setdefault(fold_person(name), []).append(name)

    working = PeopleRegistry(persons)
    for raw_names in folded_groups.values():
        existing_id = working.lookup(raw_names[0])
        if existing_id is not None:
            person = persons[existing_id]
            new_variants = tuple(n for n in raw_names if n not in person.variants)
            if new_variants:
                persons[existing_id] = replace(person, variants=person.variants + new_variants)
                working = PeopleRegistry(persons)
            continue

        canonical = _pick_canonical(raw_names, name_counts)
        person_id = assign_slug(slugify(canonical), taken_ids)
        taken_ids.add(person_id)
        persons[person_id] = Person(
            person_id=person_id,
            canonical_name=canonical,
            variants=tuple(sorted(raw_names)),
            usual_role="unknown",
            role_override=None,
        )
        working = PeopleRegistry(persons)
    return PeopleRegistry(persons)


def apply_decisions(
    registry: PeopleRegistry,
    reviewed: Sequence[ReviewedPair],
    name_counts: Mapping[str, int],
    protected_ids: Collection[str] = frozenset(),
) -> PeopleRegistry:
    """Apply each reviewed pair's decision, in order:

    - "same": name_b's person is merged into name_a's person (name_a's
      person_id, canonical_name, usual_role, and role_override never
      change); a no-op if they're already the same person.
    - "different": if name_a and name_b currently resolve to the same
      person (an earlier "same" decision merged them), the variants that
      fold to name_b split back out into a brand new person with a fresh
      slug -- unless the person's canonical_name is one of them, in which
      case the canonical's group stays on the original person_id and the
      other group is split off instead; a no-op if they're already distinct
      persons.
    - "one": no-op (a single string that's really one person; nothing to
      merge or split).

    Applying the same decisions twice yields an identical registry: the
    second pass finds every pair already in its target state and no-ops.

    `protected_ids` (the person_ids person_overrides.csv references) can
    never be deleted: a "same" merge that would remove one raises
    ReferenceTableError instead of orphaning the override.
    """
    persons = dict(registry.persons)
    working = PeopleRegistry(persons)

    for pair in reviewed:
        if pair.decision == "one":
            continue

        person_id_a = working.lookup(pair.name_a)
        person_id_b = working.lookup(pair.name_b)
        if person_id_a is None or person_id_b is None:
            continue

        if pair.decision == "same":
            if person_id_a == person_id_b:
                continue
            if person_id_b in protected_ids:
                raise ReferenceTableError(
                    f"people_reviewed.csv: a 'same' decision would delete person_id "
                    f"{person_id_b!r}, which person_overrides.csv references"
                )
            person_a = persons[person_id_a]
            person_b = persons[person_id_b]
            merged_variants = tuple(sorted(set(person_a.variants) | set(person_b.variants)))
            persons[person_id_a] = replace(person_a, variants=merged_variants)
            del persons[person_id_b]
            working = PeopleRegistry(persons)
        elif pair.decision == "different":
            if person_id_a != person_id_b:
                continue
            merged_person = persons[person_id_a]
            fold_b = fold_person(pair.name_b)
            split_variants = tuple(v for v in merged_person.variants if fold_person(v) == fold_b)
            remaining_variants = tuple(
                v for v in merged_person.variants if fold_person(v) != fold_b
            )
            if not split_variants or not remaining_variants:
                continue
            if merged_person.canonical_name in split_variants:
                # The canonical spelling folds to name_b (write_reviewed
                # stores pairs in fold order, so either side can hold it).
                # Keep the canonical's group on the original person_id -- a
                # public URL (SITE-12) -- and split the other group off
                # instead, so the canonical always stays among its variants.
                split_variants, remaining_variants = remaining_variants, split_variants
            persons[person_id_a] = replace(merged_person, variants=remaining_variants)
            canonical_b = _pick_canonical(split_variants, name_counts)
            new_id = assign_slug(slugify(canonical_b), set(persons.keys()))
            persons[new_id] = Person(
                person_id=new_id,
                canonical_name=canonical_b,
                variants=split_variants,
                usual_role="unknown",
                role_override=None,
            )
            working = PeopleRegistry(persons)
    return PeopleRegistry(persons)


def with_usual_roles(registry: PeopleRegistry, usual: Mapping[str, Role]) -> PeopleRegistry:
    """A copy of `registry` with every person's usual_role set from `usual`
    (default "unknown" for a person_id absent from the mapping); each
    person's role_override is untouched.
    """
    persons = {
        person_id: replace(person, usual_role=usual.get(person_id, "unknown"))
        for person_id, person in registry.persons.items()
    }
    return PeopleRegistry(persons)
