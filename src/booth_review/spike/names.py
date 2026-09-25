"""Team-name normalization and significant-token extraction for the SPIKE-02
hand join (D-06).

Generic rules only (AGENTS.md's crosswalk-only rule): unicode fold, case
fold, punctuation collapse, and a leading rank stripped. No team is
special-cased in code; every name the generic rules miss becomes an entry on
the SPIKE-02 name-matching problem list for Phase 3 (JOIN-01).

Also holds the shared America/New_York conversion used by both
spike/selection.py (candidate flags) and spike/join.py (matching), kept here
rather than in either of those modules to avoid a join.py <-> selection.py
import cycle.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

_LEADING_RANK_RE = re.compile(r"^#?\d+\s+(.+)$")
# Okina and apostrophe-like marks that NFKD doesn't decompose to a combining
# mark: straight apostrophe, right single quote (U+2019), the okina
# (U+02BB MODIFIER LETTER TURNED COMMA), and U+02BC MODIFIER LETTER
# APOSTROPHE. ruff's ambiguous-unicode check (RUF001) flags these marks by
# design; they're the deliberate subject of this constant, not a mistake.
_APOSTROPHE_CHARS = "'’ʻʼ`"  # noqa: RUF001
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)

_STOPWORDS = {"state", "university", "college", "the"}
_MIN_TOKEN_LEN = 4


def _strip_leading_rank(text: str) -> str:
    match = _LEADING_RANK_RE.match(text.strip())
    return match.group(1) if match else text


def _fold(text: str) -> str:
    """Unicode-fold, case-fold, spell out "&", and collapse punctuation to
    single spaces. Shared by normalize_team and significant_tokens so both
    treat diacritics and punctuation the same way.
    """
    text = text.replace("&", " and ")
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        ch for ch in decomposed if not unicodedata.combining(ch) and ch not in _APOSTROPHE_CHARS
    )
    folded = without_marks.casefold()
    spaced = _PUNCT_RE.sub(" ", folded)
    return " ".join(spaced.split())


def normalize_team(text: str) -> str:
    """Fold a team name to a comparable form: strip a leading rank, unicode-
    fold diacritics and okina/apostrophe marks, casefold, spell out "&", and
    collapse punctuation/whitespace. No team-specific fix; anything this
    misses is a SPIKE-02 name-matching problem, not a code change.
    """
    return _fold(_strip_leading_rank(text.strip()))


def significant_tokens(text: str) -> set[str]:
    """Tokens of `text` at least 4 characters, excluding a small generic
    stopword list (state, university, college, the). Used only for the
    "partial" match tier and the rated_hint candidate flag; never for an
    exact-match decision.
    """
    folded = _fold(text)
    return {tok for tok in folded.split() if len(tok) >= _MIN_TOKEN_LEN and tok not in _STOPWORDS}


def load_crosswalk(repo_root: Path) -> dict[str, str]:
    """Read data/reference/team_crosswalk.csv (variant -> canonical) if it
    exists. Returns an empty mapping otherwise; the spike never creates that
    file, so a missing entry stays a name-matching problem, not a fetch or a
    guess.
    """
    path = repo_root / "data" / "reference" / "team_crosswalk.csv"
    if not path.is_file():
        return {}
    mapping: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            variant = row.get("variant")
            canonical = row.get("canonical")
            if variant and canonical:
                mapping[variant] = canonical
    return mapping


def to_et_datetime(dt: datetime) -> datetime:
    """Convert an aware datetime (CFBD's start_date is UTC) to America/New_York."""
    return dt.astimezone(EASTERN)


def to_et_date(dt: datetime) -> date:
    """The America/New_York calendar date of an aware datetime."""
    return to_et_datetime(dt).date()
