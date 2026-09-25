"""SPIKE-02 game selection: the 20-game mix (D-06/D-08), drawn only from
rated_hint candidates, saved to selection.csv so a rerun never reshuffles.

Claude's discretion on the exact 20 games, within the required mix (01-CONTEXT):
at least 2 rematches, 2 neutral-site games, a post-DST November game, a late
or Hawaii game, and a CFP/MegaCast game, drawn deliberately to include hard
names so the measured join rate isn't inflated by easy matches.
"""

from __future__ import annotations

import csv
import io
import random
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from booth_review.errors import BoothReviewError
from booth_review.sources.cfbd.parser import CfbdGame
from booth_review.sources.ratingsref.sitemap import SitemapEntry
from booth_review.spike.names import normalize_team, significant_tokens, to_et_datetime
from booth_review.transport.cache import atomic_write_bytes

DEFAULT_SEED = 2025
TARGET_COUNT = 20

_POST_DST_NOVEMBER_START = date(2025, 11, 3)
_POST_DST_NOVEMBER_END = date(2025, 11, 30)
_LATE_HOUR_ET = 22
_CFP_KEYWORDS = ("cfp", "college football playoff", "national championship")
_DIRECTIONAL_WORDS = {"north", "south", "east", "west"}

_REQUIRED_CATEGORIES: tuple[tuple[str, int], ...] = (
    ("rematch", 2),
    ("neutral", 2),
    ("post_dst_november", 1),
    ("late_or_hawaii", 1),
    ("cfp", 1),
)

_SELECTION_FIELDS = ("cfbd_game_id", "categories")


class SelectionError(BoothReviewError):
    """Raised when no rated_hint candidate exists for a required category."""


@dataclass(frozen=True)
class Candidate:
    """One 2025 CFBD game, flagged with the SPIKE-02 selection categories
    and whether an RR sitemap entry near it hints it's rated.
    """

    game: CfbdGame
    week: int
    et_date: date
    categories: frozenset[str]
    rated_hint: bool


@dataclass(frozen=True)
class Selection:
    """One selected game and the categories it was chosen for (plus
    "name_stress" when its teams carry a diacritic, a directional word, or
    parentheses).
    """

    cfbd_game_id: int
    categories: tuple[str, ...]


def _team_pair_key(game: CfbdGame) -> frozenset[int | str]:
    if game.home_id is not None and game.away_id is not None:
        return frozenset({game.home_id, game.away_id})
    return frozenset({normalize_team(game.home_team), normalize_team(game.away_team)})


def _has_diacritics_directional_or_parens(text: str) -> bool:
    if "(" in text or ")" in text:
        return True
    decomposed = unicodedata.normalize("NFKD", text)
    if any(unicodedata.combining(ch) for ch in decomposed):
        return True
    tokens = {tok.strip(".,").casefold() for tok in text.split()}
    return bool(tokens & _DIRECTIONAL_WORDS)


def build_candidates(
    games: Sequence[CfbdGame], rr_entries: Sequence[SitemapEntry]
) -> list[Candidate]:
    """Flag every game in `games` with the SPIKE-02 selection categories,
    and whether an RR sitemap entry within one day shares a significant
    token with each team (rated_hint).
    """
    pair_counts: dict[frozenset[int | str], int] = {}
    for g in games:
        key = _team_pair_key(g)
        pair_counts[key] = pair_counts.get(key, 0) + 1

    candidates: list[Candidate] = []
    for g in games:
        et_dt = to_et_datetime(g.start_date)
        et_d = et_dt.date()
        home_tokens = significant_tokens(g.home_team)
        away_tokens = significant_tokens(g.away_team)
        home_norm = normalize_team(g.home_team)
        away_norm = normalize_team(g.away_team)

        categories: set[str] = set()
        if g.neutral_site:
            categories.add("neutral")
        if _POST_DST_NOVEMBER_START <= et_d <= _POST_DST_NOVEMBER_END:
            categories.add("post_dst_november")
        if et_dt.hour >= _LATE_HOUR_ET or "hawaii" in home_norm or "hawaii" in away_norm:
            categories.add("late_or_hawaii")
        notes = (g.notes or "").lower()
        if any(kw in notes for kw in _CFP_KEYWORDS):
            categories.add("cfp")
        if pair_counts[_team_pair_key(g)] >= 2:
            categories.add("rematch")

        rated_hint = False
        for entry in rr_entries:
            if abs((entry.event_date - et_d).days) > 1:
                continue
            entry_tokens = significant_tokens(entry.telecast_id)
            if (home_tokens & entry_tokens) and (away_tokens & entry_tokens):
                rated_hint = True
                break

        candidates.append(
            Candidate(
                game=g,
                week=g.week,
                et_date=et_d,
                categories=frozenset(categories),
                rated_hint=rated_hint,
            )
        )
    return candidates


def select_games(candidates: Sequence[Candidate], *, seed: int = DEFAULT_SEED) -> list[Selection]:
    """Pick exactly 20 games from the rated_hint candidates, covering the
    required category mix, deterministic for a given `seed`.

    Raises SelectionError naming any required category with zero rated_hint
    candidates. Only ever draws from rated_hint candidates.
    """
    pool = sorted((c for c in candidates if c.rated_hint), key=lambda c: c.game.id)
    rng = random.Random(seed)

    for category, _needed in _REQUIRED_CATEGORIES:
        if not any(category in c.categories for c in pool):
            raise SelectionError(f"no rated_hint candidate for category {category!r}")

    order: list[int] = []
    by_id: dict[int, Candidate] = {}
    tags: dict[int, set[str]] = {}

    def _select(c: Candidate, tag: str | None) -> None:
        gid = c.game.id
        if gid not in by_id:
            by_id[gid] = c
            tags[gid] = set()
            order.append(gid)
        if tag:
            tags[gid].add(tag)

    # -- rematch: prefer both meetings of one pair when both are rated_hint --
    rematch_pool = [c for c in pool if "rematch" in c.categories]
    pair_groups: dict[frozenset[int | str], list[Candidate]] = {}
    for c in rematch_pool:
        pair_groups.setdefault(_team_pair_key(c.game), []).append(c)
    full_pairs = sorted(
        (members for members in pair_groups.values() if len(members) >= 2),
        key=lambda members: members[0].game.id,
    )
    if full_pairs:
        chosen_pair = full_pairs[rng.randrange(len(full_pairs))]
        for c in sorted(chosen_pair, key=lambda c: c.game.id)[:2]:
            _select(c, "rematch")

    remaining_rematch = [c for c in rematch_pool if c.game.id not in by_id]
    rematch_have = sum(1 for gid in tags if "rematch" in tags[gid])
    while rematch_have < 2 and remaining_rematch:
        idx = rng.randrange(len(remaining_rematch))
        c = remaining_rematch.pop(idx)
        _select(c, "rematch")
        rematch_have += 1

    # -- other required categories --
    for category, needed in _REQUIRED_CATEGORIES:
        if category == "rematch":
            continue
        cat_pool = [c for c in pool if category in c.categories]
        have = sum(1 for gid in tags if category in tags[gid])
        for c in cat_pool:
            if have >= needed:
                break
            if c.game.id in by_id and category not in tags[c.game.id]:
                tags[c.game.id].add(category)
                have += 1
        remaining = [c for c in cat_pool if c.game.id not in by_id]
        while have < needed and remaining:
            idx = rng.randrange(len(remaining))
            c = remaining.pop(idx)
            _select(c, category)
            have += 1

    # -- fill the rest: stratified draw across weeks so picks aren't bunched --
    by_week: dict[int, list[Candidate]] = {}
    for c in pool:
        if c.game.id not in by_id:
            by_week.setdefault(c.week, []).append(c)
    weeks = sorted(by_week)
    while len(order) < TARGET_COUNT and weeks:
        progressed = False
        for week in list(weeks):
            if len(order) >= TARGET_COUNT:
                break
            bucket = by_week.get(week, [])
            if not bucket:
                continue
            idx = rng.randrange(len(bucket))
            c = bucket.pop(idx)
            _select(c, None)
            progressed = True
        weeks = [w for w in weeks if by_week.get(w)]
        if not progressed:
            break

    selections: list[Selection] = []
    for gid in order:
        c = by_id[gid]
        cats = set(tags[gid])
        if _has_diacritics_directional_or_parens(
            c.game.home_team
        ) or _has_diacritics_directional_or_parens(c.game.away_team):
            cats.add("name_stress")
        selections.append(Selection(cfbd_game_id=gid, categories=tuple(sorted(cats))))
    return selections


def save_selection(path: Path, selections: Sequence[Selection]) -> None:
    """Write selection.csv (cfbd_game_id, categories) atomically, categories
    pipe-joined. A rerun that loads this file never reshuffles (D-06).
    """
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_SELECTION_FIELDS)
    writer.writeheader()
    for s in selections:
        writer.writerow({"cfbd_game_id": s.cfbd_game_id, "categories": "|".join(s.categories)})
    atomic_write_bytes(path, buf.getvalue().encode("utf-8"))


def load_selection(path: Path) -> list[Selection] | None:
    """Load a previously saved selection.csv, or None if it doesn't exist yet."""
    if not path.is_file():
        return None
    selections: list[Selection] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            cats = tuple(c for c in row["categories"].split("|") if c)
            selections.append(Selection(cfbd_game_id=int(row["cfbd_game_id"]), categories=cats))
    return selections
