"""Resolve MLB club and network names through the data/reference/ crosswalks.

Nothing is guessed: a name no crosswalk row covers resolves to the unresolved sentinel.
Seasons are calendar years.
"""

from __future__ import annotations

from dataclasses import dataclass

from booth_review.mlb.reference import (
    MlbClubs,
    MlbReference,
    MlbTeamCrosswalkRow,
    normalize_mlb_variant,
)


@dataclass(frozen=True)
class ResolvedMlbTeam:
    club_id: str | None
    display_name: str | None
    league: str | None
    division: str | None


_UNRESOLVED = ResolvedMlbTeam(None, None, None, None)


def _in_range(season: int, lo: int | None, hi: int | None) -> bool:
    return (lo is None or season >= lo) and (hi is None or season <= hi)


class MlbTeamResolver:
    """Source-specific crosswalk rows beat "any" rows; season ranges are inclusive."""

    def __init__(self, clubs: MlbClubs, crosswalk: tuple[MlbTeamCrosswalkRow, ...]) -> None:
        self._clubs = clubs
        self._index: dict[tuple[str, str], list[MlbTeamCrosswalkRow]] = {}
        for row in crosswalk:
            self._index.setdefault((row.source, normalize_mlb_variant(row.variant)), []).append(row)

    @classmethod
    def from_reference(cls, ref: MlbReference) -> MlbTeamResolver:
        return cls(ref.clubs, ref.crosswalk)

    def _club(self, club_id: str, season: int) -> ResolvedMlbTeam:
        entries = self._clubs.names[club_id]
        entry = next((e for e in entries if _in_range(season, e.season_from, e.season_to)), None)
        if entry is None:
            before = [e for e in entries if e.season_from is not None and season < e.season_from]
            entry = min(before, key=lambda e: e.season_from or 0) if before else entries[-1]
        return ResolvedMlbTeam(club_id, entry.display_name, entry.league, entry.division)

    def resolve(self, source: str, raw: str, season: int) -> ResolvedMlbTeam:
        key = normalize_mlb_variant(raw.strip())
        sources = (source,) if source == "any" else (source, "any")
        for lookup in sources:
            for row in self._index.get((lookup, key), ()):
                if _in_range(season, row.season_from, row.season_to):
                    return self._club(row.club_id, season)
        return _UNRESOLVED


@dataclass(frozen=True)
class ResolvedMlbNetwork:
    network_id: str | None
    family: str | None


_NET_UNRESOLVED = ResolvedMlbNetwork(None, None)


def _net_key(text: str) -> str:
    return " ".join(text.casefold().split())


class MlbNetworkResolver:
    def __init__(self, ref: MlbReference) -> None:
        self._index = {
            (row.source, _net_key(row.variant)): ResolvedMlbNetwork(row.network_id, row.family)
            for row in ref.networks
        }

    @classmethod
    def from_reference(cls, ref: MlbReference) -> MlbNetworkResolver:
        return cls(ref)

    def resolve(self, source: str, raw: str) -> ResolvedMlbNetwork:
        return self._index.get((source, _net_key(raw)), _NET_UNRESOLVED)
