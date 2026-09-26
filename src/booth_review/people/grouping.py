"""Suspicious-pair detection for the people-review step (D-02).

The only *automatic* merge in the people layer is an exact match after
fold_person (registry.register_names): every heuristic here only proposes a
row for the vault review file (review.py); a human confirms or overrides it
at the Task 3 checkpoint. NICKNAME_GROUPS is a generic, common-English-name
heuristic that (like every reason below) only ever proposes a review row --
never an automatic merge.
"""

from __future__ import annotations

import difflib
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from booth_review.people.normalize import split_suffix, surname
from booth_review.people.registry import Decision, PeopleRegistry

Reason = Literal["suffix_only", "nickname", "similar_first", "near_spelling", "possible_two_people"]

# Common English first-name forms (generic heuristic only, per the module
# docstring): grouped so "Chris" and "Christopher" propose a review row for
# a shared surname, but never merge automatically.
NICKNAME_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"bill", "will", "william"}),
    frozenset({"bob", "rob", "robert"}),
    frozenset({"mike", "michael"}),
    frozenset({"chris", "christopher"}),
    frozenset({"dave", "david"}),
    frozenset({"jim", "jimmy", "james"}),
    frozenset({"joe", "joseph"}),
    frozenset({"tom", "thomas"}),
    frozenset({"dan", "danny", "daniel"}),
    frozenset({"matt", "matthew"}),
    frozenset({"steve", "stephen", "steven"}),
    frozenset({"tony", "anthony"}),
    frozenset({"ben", "benjamin"}),
    frozenset({"sam", "samuel"}),
    frozenset({"nick", "nicholas"}),
    frozenset({"jon", "jonathan"}),
    frozenset({"ed", "eddie", "edward"}),
    frozenset({"rick", "rich", "richard"}),
    frozenset({"andy", "andrew"}),
    frozenset({"pat", "patrick"}),
    frozenset({"tim", "timothy"}),
    frozenset({"greg", "gregory"}),
    frozenset({"jeff", "jeffrey"}),
    frozenset({"ken", "kenny", "kenneth"}),
    frozenset({"charlie", "chuck", "charles"}),
    frozenset({"kate", "katie", "kathryn", "katherine"}),
    frozenset({"liz", "beth", "elizabeth"}),
    frozenset({"jen", "jenny", "jennifer"}),
)

_NEAR_SPELLING_RATIO = 0.85
_SIMILAR_FIRST_RATIO = 0.8
_RARE_MAX_COUNT = 2
_FREQUENT_MIN_COUNT = 10
_OVERLAP_HOURS = 3.0


@dataclass(frozen=True)
class Appearance:
    """One crew-slot occurrence of a folded name: the listing's ET date and
    kickoff (kickoff_et is None when 506 didn't publish a time), the raw
    network text, and the whole crew's folded names (for the "never share a
    crew" check -- two people can't call the same game together and also be
    the same person).
    """

    date_et: date
    kickoff_et: datetime | None
    network_raw: str | None
    crew_folded: tuple[str, ...]


@dataclass(frozen=True)
class NameStats:
    raw_spellings: tuple[str, ...]
    folded: str
    count: int
    seasons: frozenset[int]
    networks: Counter[str]
    appearances: tuple[Appearance, ...]


@dataclass(frozen=True)
class SuspiciousPair:
    reason: Reason
    name_a: str
    name_b: str
    stats_a: NameStats
    stats_b: NameStats


def _representative(stats: NameStats) -> str:
    """A deterministic, human-readable raw spelling to label this folded
    group with in a review row: the lexically smallest of its observed raw
    spellings. Any of them resolves to the same person via the registry
    once registered, so which one is picked doesn't affect correctness.
    """
    return min(stats.raw_spellings)


def _same_nickname_group(first_a: str, first_b: str) -> bool:
    return first_a != first_b and any(
        first_a in group and first_b in group for group in NICKNAME_GROUPS
    )


def _similar_first(first_a: str, first_b: str) -> bool:
    if not first_a or not first_b:
        return False
    if first_a[0] == first_b[0]:
        return True
    if first_a.startswith(first_b) or first_b.startswith(first_a):
        return True
    return difflib.SequenceMatcher(None, first_a, first_b).ratio() >= _SIMILAR_FIRST_RATIO


def _classify_surname_pair(a: NameStats, b: NameStats) -> Reason | None:
    base_a, suffix_a = split_suffix(a.folded)
    base_b, suffix_b = split_suffix(b.folded)
    if base_a == base_b and suffix_a != suffix_b:
        return "suffix_only"

    tokens_a = a.folded.split()
    tokens_b = b.folded.split()
    first_a = tokens_a[0] if tokens_a else ""
    first_b = tokens_b[0] if tokens_b else ""
    if not first_a or not first_b or first_a == first_b:
        return None

    if _same_nickname_group(first_a, first_b):
        return "nickname"
    if _similar_first(first_a, first_b):
        return "similar_first"
    return None


def _kickoffs_overlap(a: Appearance, b: Appearance) -> bool:
    if a.date_et != b.date_et:
        return False
    if a.kickoff_et is None or b.kickoff_et is None:
        return True
    delta_hours = abs((a.kickoff_et - b.kickoff_et).total_seconds()) / 3600
    return delta_hours <= _OVERLAP_HOURS


def _never_share_crew(a: NameStats, b: NameStats) -> bool:
    if any(b.folded in appearance.crew_folded for appearance in a.appearances):
        return False
    return not any(a.folded in appearance.crew_folded for appearance in b.appearances)


def _never_overlap(a: NameStats, b: NameStats) -> bool:
    return not any(
        _kickoffs_overlap(app_a, app_b) for app_a in a.appearances for app_b in b.appearances
    )


def _share_network(a: NameStats, b: NameStats) -> bool:
    return bool(set(a.networks) & set(b.networks))


def _has_self_overlap(stats: NameStats) -> bool:
    """True when `stats`' own appearances include two listings on the same
    ET date, on different networks, with kickoffs within _OVERLAP_HOURS (or
    either kickoff unknown) -- one raw string that may really be two people
    both working the same day (D-09-style MegaCast/alt-cast aside; this is
    the person-identity analog).
    """
    appearances = stats.appearances
    for i, app_a in enumerate(appearances):
        for app_b in appearances[i + 1 :]:
            if app_a.network_raw == app_b.network_raw:
                continue
            if _kickoffs_overlap(app_a, app_b):
                return True
    return False


def find_suspicious_pairs(
    stats: Mapping[str, NameStats],
    reviewed: set[frozenset[str]],
    registry: PeopleRegistry,
) -> list[SuspiciousPair]:
    """Flag suspicious name pairs (and self-referential possible_two_people
    entries) from `stats` (keyed by fold_person(name)). `reviewed` is a set
    of {folded_a, folded_b} pairs (a length-1 frozenset for a
    possible_two_people self-entry) already recorded in
    people_reviewed.csv; a pair already merged into the same registry
    person is also skipped. Deterministically sorted by (reason, name_a,
    name_b).
    """

    flagged: set[frozenset[str]] = set()

    def _already_resolved(folded_a: str, folded_b: str) -> bool:
        key = frozenset((folded_a, folded_b))
        if key in reviewed or key in flagged:
            return True
        person_id_a = registry.lookup(folded_a)
        person_id_b = registry.lookup(folded_b)
        return person_id_a is not None and person_id_a == person_id_b

    pairs: list[SuspiciousPair] = []

    by_surname: dict[str, list[NameStats]] = {}
    for entry in stats.values():
        by_surname.setdefault(surname(entry.folded), []).append(entry)

    # Surname-bucketed reasons (suffix_only, nickname, similar_first) run
    # first and claim a pair via `flagged`, so a pair sharing a surname is
    # never *also* re-flagged as near_spelling below (D-02's "a few dozen
    # rows" scale: one row per pair, not one per reason it happens to fit).
    for group in by_surname.values():
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                if _already_resolved(a.folded, b.folded):
                    continue
                reason = _classify_surname_pair(a, b)
                if reason is None:
                    continue
                flagged.add(frozenset((a.folded, b.folded)))
                pairs.append(
                    SuspiciousPair(
                        reason=reason,
                        name_a=_representative(a),
                        name_b=_representative(b),
                        stats_a=a,
                        stats_b=b,
                    )
                )

    all_entries = list(stats.values())
    rare = [e for e in all_entries if e.count <= _RARE_MAX_COUNT]
    frequent = [e for e in all_entries if e.count >= _FREQUENT_MIN_COUNT]
    for r in rare:
        for f in frequent:
            if r.folded == f.folded or _already_resolved(r.folded, f.folded):
                continue
            ratio = difflib.SequenceMatcher(None, r.folded, f.folded).ratio()
            if ratio >= _NEAR_SPELLING_RATIO:
                flagged.add(frozenset((r.folded, f.folded)))
                pairs.append(
                    SuspiciousPair(
                        reason="near_spelling",
                        name_a=_representative(r),
                        name_b=_representative(f),
                        stats_a=r,
                        stats_b=f,
                    )
                )

    for entry in all_entries:
        if frozenset({entry.folded}) in reviewed:
            continue
        if _has_self_overlap(entry):
            name = _representative(entry)
            pairs.append(
                SuspiciousPair(
                    reason="possible_two_people",
                    name_a=name,
                    name_b=name,
                    stats_a=entry,
                    stats_b=entry,
                )
            )

    pairs.sort(key=lambda p: (p.reason, p.name_a, p.name_b))
    return pairs


def propose_decision(pair: SuspiciousPair) -> Decision:
    """suffix_only always proposes "different" (D-02: Jr./Sr./II/III stay
    distinct). possible_two_people always proposes "one" (benefit of the
    doubt; a genuine two-people case needs a pointer-only person_overrides
    row, not a name-level split, since both occurrences share one string).
    nickname/similar_first/near_spelling propose "same" only when the two
    names never appear in the same crew, never appear in overlapping games
    on one date, and do share at least one network -- otherwise "different".
    """
    if pair.reason == "suffix_only":
        return "different"
    if pair.reason == "possible_two_people":
        return "one"
    if (
        _never_share_crew(pair.stats_a, pair.stats_b)
        and _never_overlap(pair.stats_a, pair.stats_b)
        and _share_network(pair.stats_a, pair.stats_b)
    ):
        return "same"
    return "different"
