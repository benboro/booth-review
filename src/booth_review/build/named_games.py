"""Named-game build rules: D-07/D-08 franchise grouping and D-13 rivalry resolution.

Pure functions over the bowl crosswalk and the games table. The only free-text
CFBD field read is the private `notes` column, as a build-time yes/no test for a
conference title game (D-13); its text never leaves this module. Every error is
count-only: it never names a team or a bowl.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import polars as pl

from booth_review.build.bowls import BowlEntry
from booth_review.build.rivalries import Rivalry
from booth_review.contract.models import RESERVED_GAME_SLUGS
from booth_review.errors import BowlCrosswalkError, VaultStateError


@dataclass(frozen=True)
class Franchise:
    slug: str
    name: str
    former: tuple[str, ...]


# A conference title game carries "championship" in CFBD's notes, which CFBD
# fills for them from the 2022 season on. Matched case-insensitively and only
# as a yes/no test; the notes text is never stored, shipped, or printed.
_TITLE_GAME_NOTE = re.compile(r"championship", re.IGNORECASE)


@dataclass(frozen=True)
class RivalryResolution:
    by_game: dict[int, str]
    rematches_demoted: int
    title_games_excluded: int


def build_franchises(
    entries: Mapping[int, BowlEntry], season_by_game: Mapping[int, int]
) -> dict[str, Franchise]:
    """Group shipped bowl rows by franchise; label with the latest-season core name.

    Every shipped postseason game contributes, rated or not (04.13 D-14), so the
    Game picker lists every game the chart can show.
    """
    rows: list[tuple[int, int, str, str | None]] = []  # season, game_id, core, franchise
    for game_id, season in season_by_game.items():
        entry = entries.get(game_id)
        if entry is None or not entry.at_bowl or entry.core_name is None:
            continue
        rows.append((season, game_id, entry.core_name, entry.franchise))

    missing = sum(1 for _, _, _, franchise in rows if franchise is None)
    if missing:
        raise BowlCrosswalkError(f"telecasts: {missing} shipped bowl row(s) without a franchise")

    grouped: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    for season, game_id, core, franchise in rows:
        assert franchise is not None
        grouped[franchise].append((season, game_id, core))

    overlapping = sum(
        1
        for members in grouped.values()
        if any(n > 1 for n in Counter(season for season, _, _ in members).values())
    )
    if overlapping:
        raise VaultStateError(f"bowls.csv: {overlapping} franchise(s) with two games in one season")

    result: dict[str, Franchise] = {}
    for slug, members in grouped.items():
        label = max(members)[2]
        first_season: dict[str, int] = {}
        for season, _, core in sorted(members):
            first_season.setdefault(core, season)
        former = tuple(
            core
            for core, _ in sorted(first_season.items(), key=lambda kv: (kv[1], kv[0]))
            if core != label
        )
        result[slug] = Franchise(slug, label, former)
    return result


def resolve_rivalry_games(games: pl.DataFrame, rivalries: Sequence[Rivalry]) -> RivalryResolution:
    """Tag the first regular-season meeting of each rivalry pair per season (D-13).

    Conference title games marked in CFBD's notes are skipped before the
    first-meeting rule runs and counted in `title_games_excluded`.
    """
    ids_by_name: dict[str, set[int]] = defaultdict(set)
    for team_col, id_col in (("home_team", "home_id"), ("away_team", "away_id")):
        for name, team_id in games.select(team_col, id_col).unique().iter_rows():
            if name is not None and team_id is not None:
                ids_by_name[name].add(team_id)

    not_found = 0
    ambiguous = 0
    for rivalry in rivalries:
        for name in (rivalry.team_a, rivalry.team_b):
            found = ids_by_name.get(name)
            if not found:
                not_found += 1
            elif len(found) > 1:
                ambiguous += 1
    if not_found:
        raise VaultStateError(
            f"rivalries.csv: {not_found} team name(s) not found in the games table"
        )
    if ambiguous:
        raise VaultStateError(
            f"rivalries.csv: {ambiguous} team name(s) map to more than one team id"
        )

    by_pair: dict[frozenset[int], Rivalry] = {}
    shared = 0
    for rivalry in rivalries:
        (id_a,) = ids_by_name[rivalry.team_a]
        (id_b,) = ids_by_name[rivalry.team_b]
        pair = frozenset((id_a, id_b))
        if pair in by_pair:
            shared += 1
        else:
            by_pair[pair] = rivalry
    if shared:
        raise VaultStateError(f"rivalries.csv: {shared} rivalr(ies) share a team pair")

    regular = games.filter(pl.col("game_type") == "regular").sort("start_utc", "game_id")
    seen: set[tuple[int, frozenset[int]]] = set()
    by_game: dict[int, str] = {}
    demoted = 0
    excluded = 0
    for game_id, season, home_id, away_id, notes in regular.select(
        "game_id", "season", "home_id", "away_id", "notes"
    ).iter_rows():
        pair = frozenset((home_id, away_id))
        hit = by_pair.get(pair)
        if hit is None:
            continue
        # CFBD labels conference title games "regular". One marked by its notes is
        # never the rivalry game and does not use up the season's first meeting, so
        # a title game played before the rivalry game (or instead of it) stays
        # untagged. Seasons whose notes don't mark title games fall back on the
        # first-meeting rule below, which demotes a later rematch.
        if notes is not None and _TITLE_GAME_NOTE.search(notes):
            excluded += 1
            continue
        key = (season, pair)
        if key in seen:
            demoted += 1
            continue
        seen.add(key)
        if hit.season_from is not None and season < hit.season_from:
            continue
        if hit.season_to is not None and season > hit.season_to:
            continue
        by_game[game_id] = hit.rivalry_id
    return RivalryResolution(by_game, demoted, excluded)


def check_game_slugs(franchise_slugs: Iterable[str], rivalry_ids: Iterable[str]) -> None:
    """Fail when slugs repeat across franchises and rivalries or use a CFP slug."""
    counts = Counter(franchise_slugs)
    counts.update(rivalry_ids)
    bad = sum(1 for slug, n in counts.items() if n > 1 or slug in RESERVED_GAME_SLUGS)
    if bad:
        raise VaultStateError(f"named games: {bad} slug(s) collide or use a reserved CFP slug")
