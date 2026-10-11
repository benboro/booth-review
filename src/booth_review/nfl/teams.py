"""Resolve NFL team and network names through the data/reference/ crosswalks (D-14).

Nothing is guessed: a name no crosswalk row covers resolves to None.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from booth_review.nfl.reference import (
    NflFranchises,
    NflNetworkRow,
    NflTeamCrosswalkRow,
    load_nfl_franchises,
    load_nfl_networks,
    load_nfl_team_crosswalk,
    normalize_nfl_variant,
)


@dataclass(frozen=True)
class ResolvedNflTeam:
    franchise_id: str | None
    display_name: str | None
    method: Literal["crosswalk", "unresolved"]


_UNRESOLVED = ResolvedNflTeam(None, None, "unresolved")


class NflTeamResolver:
    """Source-specific crosswalk rows beat "any" rows; season ranges are inclusive."""

    def __init__(self, franchises: NflFranchises, crosswalk: Sequence[NflTeamCrosswalkRow]) -> None:
        self._franchises = franchises
        self._index: dict[tuple[str, str], list[NflTeamCrosswalkRow]] = {}
        for row in crosswalk:
            self._index.setdefault((row.source, normalize_nfl_variant(row.variant)), []).append(row)

    @classmethod
    def from_reference_dir(cls, reference_dir: Path) -> NflTeamResolver:
        return cls(load_nfl_franchises(reference_dir), load_nfl_team_crosswalk(reference_dir))

    def display_name(self, franchise_id: str, season: int) -> str:
        entries = self._franchises.names[franchise_id]
        for entry in entries:
            if (entry.season_from is None or season >= entry.season_from) and (
                entry.season_to is None or season <= entry.season_to
            ):
                return entry.display_name
        # Outside every listed range: fall back to the nearest listed name.
        before = [e for e in entries if e.season_from is not None and season < e.season_from]
        if before:
            return min(before, key=lambda e: e.season_from or 0).display_name
        return entries[-1].display_name

    def resolve(self, source: str, raw: str, season: int) -> ResolvedNflTeam:
        key = normalize_nfl_variant(raw.strip())
        sources = (source,) if source == "any" else (source, "any")
        for lookup in sources:
            for row in self._index.get((lookup, key), ()):
                if (row.season_from is None or season >= row.season_from) and (
                    row.season_to is None or season <= row.season_to
                ):
                    return ResolvedNflTeam(
                        row.franchise_id, self.display_name(row.franchise_id, season), "crosswalk"
                    )
        return _UNRESOLVED


def _net_key(text: str) -> str:
    return " ".join(text.casefold().split())


class NflNetworkResolver:
    def __init__(self, rows: Sequence[NflNetworkRow]) -> None:
        self._index = {(row.source, _net_key(row.variant)): row.network_id for row in rows}

    @classmethod
    def from_reference_dir(cls, reference_dir: Path) -> NflNetworkResolver:
        return cls(load_nfl_networks(reference_dir))

    def resolve(self, source: str, raw: str) -> str | None:
        return self._index.get((source, _net_key(raw)))
