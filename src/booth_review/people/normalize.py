"""Person-name normalization for the people layer (JOIN-03).

Adapted from resolve.names._fold (D-02), with one deliberate difference: a
person's suffix (Jr., Sr., II, III, IV) is never folded away, since it is the
one thing that distinguishes some real people (Mike Golic vs Mike Golic Jr.).
Hyphens and periods become spaces (not stripped), so "Jr." and "Jr" fold
identically and a hyphenated surname stays one token group.
"""

from __future__ import annotations

import re
import unicodedata

# Same apostrophe-like marks as resolve.names._APOSTROPHE_CHARS, restated
# locally rather than imported so this module (and its slug/role siblings)
# never depends on resolve/, a later-plan package with a different purpose
# (team names, not person names).
_APOSTROPHE_CHARS = "'’ʻʼ`"  # noqa: RUF001
_NON_WORD_RE = re.compile(r"[^\w\s]", re.UNICODE)
_HYPHEN_PERIOD_RE = re.compile(r"[-.]")

# A crew slot 506 fills with a non-name placeholder rather than leaving
# blank. Folded (lowercase, punctuation collapsed) so "N/A" and "n a" both
# match.
PLACEHOLDER_NAMES: frozenset[str] = frozenset({"tba", "tbd", "n a", "various", "none"})

# Folded suffix tokens kept distinct from the base name (D-02): a generic,
# not team- or person-specific, list.
SUFFIXES: tuple[str, ...] = ("jr", "sr", "ii", "iii", "iv")


def fold_person(name: str) -> str:
    """Fold `name` to a comparable form: hyphens/periods become spaces,
    unicode diacritics and okina/apostrophe marks are stripped, the result is
    casefolded, remaining punctuation collapses to whitespace, and whitespace
    is collapsed. A suffix (Jr., Sr., II, III, IV) is preserved as an
    ordinary trailing token, so "Mike Golic" and "Mike Golic Jr." fold to
    different strings.
    """
    despaced = _HYPHEN_PERIOD_RE.sub(" ", name)
    decomposed = unicodedata.normalize("NFKD", despaced)
    without_marks = "".join(
        ch for ch in decomposed if not unicodedata.combining(ch) and ch not in _APOSTROPHE_CHARS
    )
    folded = without_marks.casefold()
    spaced = _NON_WORD_RE.sub(" ", folded)
    return " ".join(spaced.split())


def is_placeholder(name: str) -> bool:
    """True for a 506 crew-slot placeholder ("TBA", "TBD", "Various", ...),
    never a real name.
    """
    return fold_person(name) in PLACEHOLDER_NAMES


def split_suffix(folded: str) -> tuple[str, str | None]:
    """`folded` (already passed through fold_person) split into (base,
    suffix); suffix is None when the last token isn't one of SUFFIXES.
    """
    tokens = folded.split()
    if tokens and tokens[-1] in SUFFIXES:
        return " ".join(tokens[:-1]), tokens[-1]
    return folded, None


def surname(folded: str) -> str:
    """The last token of `folded` before any suffix; "" for an empty name."""
    base, _suffix = split_suffix(folded)
    tokens = base.split()
    return tokens[-1] if tokens else ""
