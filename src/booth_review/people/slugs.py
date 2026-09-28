"""Stable, readable person_id slugs (D-01).

A person_id is assigned once, at first registration, and never renamed by
later code (register_names never changes an existing person's id; a later
spelling becomes a variant instead). assign_slug is the only place a fresh
id is picked, for a genuinely new person or a user-directed split.
"""

from __future__ import annotations

from booth_review.people.normalize import fold_person

_SLUG_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")


def slugify(name: str) -> str:
    """`name` folded (fold_person) then joined with hyphens, ASCII a-z0-9
    only: "Jac Collinsworth" -> "jac-collinsworth", "Mike Golic Jr." ->
    "mike-golic-jr".
    """
    tokens = []
    for token in fold_person(name).split():
        cleaned = "".join(ch for ch in token if ch in _SLUG_CHARS)
        if cleaned:
            tokens.append(cleaned)
    return "-".join(tokens)


def assign_slug(base: str, taken: set[str]) -> str:
    """`base` if it isn't in `taken`, else `base`-2, `base`-3, ... until one
    is free.
    """
    if base not in taken:
        return base
    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"
