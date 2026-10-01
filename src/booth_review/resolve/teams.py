"""Season-ranged team-name crosswalk and the resolver applied before any
listing/record is matched to a CFBD game (JOIN-01).

Generic rules only (AGENTS.md's crosswalk-only rule): `clean_team_text`
strips only the structural wrapper a source adds around a name (a 506
trailing location note, an RR slug prefix), never a per-team spelling fix.
Everything a season's crosswalk and the direct normalized-name match both
miss is a JOIN-01 name-matching problem for the review file
(`resolve/diagnose.py`), never a guess or a parser change.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from booth_review.errors import ReferenceTableError
from booth_review.reference import read_reference_csv_numbered
from booth_review.resolve.names import normalize_team
from booth_review.sources.cfbd.parser import CfbdGame

TEAM_CROSSWALK_COLUMNS = (
    "source",
    "variant",
    "canonical",
    "cfbd_team_id",
    "season_from",
    "season_to",
    "note",
)

TeamSource = Literal["sports506", "ratingsref", "cfbd", "any"]

_SOURCES: frozenset[str] = frozenset({"sports506", "ratingsref", "cfbd", "any"})
_MAX_NOTE_LEN = 80

# A trailing 506 "(in <city>)"/"(at <city>)" location note, kept verbatim by
# the 506 parser on a neutral-site home team; stripping it is structural
# (every such note has this shape), not a per-team fix.
_LOCATION_NOTE_RE = re.compile(r"\s*\((?:in|at)\s+[^)]*\)\s*$", re.IGNORECASE)
_RR_SLUG_PREFIX = "cfb-"


@dataclass(frozen=True)
class TeamCrosswalkRow:
    source: TeamSource
    variant: str
    canonical: str
    cfbd_team_id: int
    season_from: int | None
    season_to: int | None
    note: str


def _parse_optional_int(value: str, *, path_name: str, field: str) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise ReferenceTableError(f"{path_name}: invalid {field}: {value!r}") from None


_OPEN_LOW = -(10**9)
_OPEN_HIGH = 10**9


def _ranges_overlap(
    a_from: int | None, a_to: int | None, b_from: int | None, b_to: int | None
) -> bool:
    """True when two inclusive season ranges (None = open-ended) share a season."""
    lo = max(
        a_from if a_from is not None else _OPEN_LOW, b_from if b_from is not None else _OPEN_LOW
    )
    hi = min(a_to if a_to is not None else _OPEN_HIGH, b_to if b_to is not None else _OPEN_HIGH)
    return lo <= hi


def load_team_crosswalk(reference_dir: Path) -> list[TeamCrosswalkRow]:
    """Read team_crosswalk.csv (not required: an empty/missing table just
    means every name must resolve through the direct normalized-name match).
    Raises ReferenceTableError naming the file and line number on an invalid
    source, a non-integer cfbd_team_id/season, a note over 80 characters, or
    the same (source, normalized variant) mapped to two different
    cfbd_team_ids over overlapping season ranges (the resolver would
    otherwise silently use whichever row came first).
    """
    path = reference_dir / "team_crosswalk.csv"
    raw_rows = read_reference_csv_numbered(path, TEAM_CROSSWALK_COLUMNS, required=False)

    rows: list[TeamCrosswalkRow] = []
    seen: dict[tuple[str, str], list[tuple[int | None, int | None, int]]] = {}
    for line_no, raw in raw_rows:
        source = raw["source"]
        if source not in _SOURCES:
            raise ReferenceTableError(f"{path.name}: line {line_no}: invalid source {source!r}")
        if not raw["cfbd_team_id"]:
            raise ReferenceTableError(f"{path.name}: line {line_no}: cfbd_team_id is required")
        try:
            cfbd_team_id = int(raw["cfbd_team_id"])
        except ValueError:
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: invalid cfbd_team_id {raw['cfbd_team_id']!r}"
            ) from None
        season_from = _parse_optional_int(
            raw["season_from"], path_name=path.name, field="season_from"
        )
        season_to = _parse_optional_int(raw["season_to"], path_name=path.name, field="season_to")
        note = raw["note"]
        if len(note) > _MAX_NOTE_LEN:
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: note exceeds {_MAX_NOTE_LEN} characters"
            )
        normalized_variant = normalize_team(clean_team_text(raw["variant"], source))  # type: ignore[arg-type]
        variant_key = (source, normalized_variant)
        for other_from, other_to, other_id in seen.get(variant_key, ()):
            if other_id != cfbd_team_id and _ranges_overlap(
                season_from, season_to, other_from, other_to
            ):
                raise ReferenceTableError(
                    f"{path.name}: line {line_no}: variant {raw['variant']!r} maps to "
                    f"cfbd_team_id {cfbd_team_id}, conflicting with an earlier row's "
                    f"{other_id} over overlapping seasons"
                )
        seen.setdefault(variant_key, []).append((season_from, season_to, cfbd_team_id))
        rows.append(
            TeamCrosswalkRow(
                source=source,  # type: ignore[arg-type]
                variant=raw["variant"],
                canonical=raw["canonical"],
                cfbd_team_id=cfbd_team_id,
                season_from=season_from,
                season_to=season_to,
                note=note,
            )
        )
    return rows


def clean_team_text(raw: str, source: TeamSource) -> str:
    """Strip a source-specific structural wrapper before normalization: a
    trailing 506 "(in <city>)"/"(at <city>)" location note for sports506, or
    the "cfb-" slug prefix for ratingsref. Generic and structural only, never
    a per-team fix; a name carrying no such wrapper is returned unchanged.
    """
    text = raw.strip()
    if source == "sports506":
        return _LOCATION_NOTE_RE.sub("", text).strip()
    if source == "ratingsref":
        return text[len(_RR_SLUG_PREFIX) :] if text.startswith(_RR_SLUG_PREFIX) else text
    return text


@dataclass(frozen=True)
class ResolvedTeam:
    team_id: int | None
    canonical: str | None
    method: Literal["crosswalk", "direct", "unresolved"]


class TeamResolver:
    """Resolves a raw team-name string from a given source and season to a
    CFBD team id.

    Source-specific crosswalk rows beat "any"-source rows, which beat a
    direct normalized-name match against that season's CFBD teams (built
    from every game's home/away side, all divisions). Neither tier ever
    falls back to a guess (JOIN-01): no match at all, or more than one
    distinct team sharing the same normalized name in a season, resolves
    "unresolved".
    """

    def __init__(
        self,
        games_by_season: Mapping[int, Sequence[CfbdGame]],
        crosswalk: Sequence[TeamCrosswalkRow],
    ) -> None:
        self._direct: dict[int, dict[str, set[tuple[int, str]]]] = {}
        ids_by_season: dict[int, set[int]] = {}
        for season, games in games_by_season.items():
            index: dict[str, set[tuple[int, str]]] = {}
            ids: set[int] = set()
            for game in games:
                for team_id, name in (
                    (game.home_id, game.home_team),
                    (game.away_id, game.away_team),
                ):
                    if team_id is None:
                        continue
                    index.setdefault(normalize_team(name), set()).add((team_id, name))
                    ids.add(team_id)
            self._direct[season] = index
            ids_by_season[season] = ids

        self._crosswalk: dict[tuple[str, str], list[TeamCrosswalkRow]] = {}
        for row in crosswalk:
            variant_key = normalize_team(clean_team_text(row.variant, row.source))
            self._crosswalk.setdefault((row.source, variant_key), []).append(row)

        self._validate_crosswalk_ids(ids_by_season, crosswalk)
        self._cache: dict[tuple[str, str, int], ResolvedTeam] = {}

    @staticmethod
    def _validate_crosswalk_ids(
        ids_by_season: Mapping[int, set[int]],
        crosswalk: Sequence[TeamCrosswalkRow],
    ) -> None:
        for row in crosswalk:
            in_range_seasons = [
                season
                for season in ids_by_season
                if (row.season_from is None or season >= row.season_from)
                and (row.season_to is None or season <= row.season_to)
            ]
            if not in_range_seasons:
                continue
            if not any(row.cfbd_team_id in ids_by_season[season] for season in in_range_seasons):
                raise ReferenceTableError(
                    f"team_crosswalk.csv: {row.variant!r} -> cfbd_team_id {row.cfbd_team_id} "
                    "appears in none of its in-range seasons' CFBD games"
                )

    def resolve(self, source: TeamSource, raw: str, season: int) -> ResolvedTeam:
        cache_key = (source, raw, season)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        cleaned = clean_team_text(raw, source)
        normalized = normalize_team(cleaned)

        lookup_sources = (source,) if source == "any" else (source, "any")
        for lookup_source in lookup_sources:
            for row in self._crosswalk.get((lookup_source, normalized), ()):
                in_range = (row.season_from is None or season >= row.season_from) and (
                    row.season_to is None or season <= row.season_to
                )
                if in_range:
                    result = ResolvedTeam(
                        team_id=row.cfbd_team_id, canonical=row.canonical, method="crosswalk"
                    )
                    self._cache[cache_key] = result
                    return result

        candidates = self._direct.get(season, {}).get(normalized, set())
        if len(candidates) == 1:
            team_id, name = next(iter(candidates))
            result = ResolvedTeam(team_id=team_id, canonical=name, method="direct")
        else:
            result = ResolvedTeam(team_id=None, canonical=None, method="unresolved")
        self._cache[cache_key] = result
        return result
