"""Usual-role inference from two-person crews (D-03, D-04).

A person's usual role (play-by-play or analyst) is learned only from crews
where the position is unambiguous: the first name listed in a two-person
crew is play-by-play, the second is analyst. Sideline reporters (out of
scope as a role, D-04) end up unknown because 506 rarely lists them at all
and never in a way that accumulates the two-person-crew evidence this module
requires; a play-by-play or analyst role filter therefore never matches them.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Literal

Role = Literal["pbp", "analyst", "unknown"]

# A person needs at least this many two-person-crew appearances before a
# usual role is inferred at all; fewer stays unknown rather than guessing
# from a single data point.
MIN_TWO_PERSON_APPEARANCES = 2
# ...and at least this share of those appearances in one position.
ROLE_SHARE = 2 / 3

_POSITION_ROLE: tuple[Role, Role] = ("pbp", "analyst")


def infer_usual_roles(crews: Iterable[Sequence[str]]) -> dict[str, Role]:
    """`crews`: one person_id sequence per crew, any length; only two-person
    crews contribute counts (D-03). A person_id with at least
    MIN_TWO_PERSON_APPEARANCES such appearances and at least ROLE_SHARE of
    them in one position gets that role; otherwise unknown, including anyone
    seen only in 1-, 3-, or 4-person crews (absent from the returned dict
    entirely in that case).
    """
    counts: dict[str, Counter[Role]] = {}
    for crew in crews:
        if len(crew) != 2:
            continue
        for position, person_id in enumerate(crew):
            counts.setdefault(person_id, Counter())[_POSITION_ROLE[position]] += 1

    usual: dict[str, Role] = {}
    for person_id, role_counts in counts.items():
        total = sum(role_counts.values())
        if total < MIN_TWO_PERSON_APPEARANCES:
            usual[person_id] = "unknown"
            continue
        top_role, top_count = role_counts.most_common(1)[0]
        usual[person_id] = top_role if top_count / total >= ROLE_SHARE else "unknown"
    return usual


def crew_roles(
    crew: Sequence[str], usual: Mapping[str, Role], overrides: Mapping[str, Role]
) -> list[Role]:
    """Roles for one crew, in listed order. A two-person crew is always
    [pbp, analyst] by position (D-03); any other size falls back, per
    person, to that person's role_override, else their usual role, else
    unknown.
    """
    if len(crew) == 2:
        return [_POSITION_ROLE[0], _POSITION_ROLE[1]]
    return [overrides.get(person_id, usual.get(person_id, "unknown")) for person_id in crew]
