"""NFL network groups and each group's flagship window (D-03, D-04, D-21).

Every NFL network id belongs to exactly one group; a null network belongs to none.
Peacock sits under NBC and the Disney networks under `espn_abc` (D-21).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class NetworkGroup:
    id: str
    name: str
    members: tuple[str, ...]
    flagship: str | None


NETWORK_GROUPS: tuple[NetworkGroup, ...] = (
    NetworkGroup("fox", "Fox", ("fox",), "AGOTW"),
    NetworkGroup("cbs", "CBS", ("cbs",), "Late national"),
    NetworkGroup("nbc", "NBC", ("nbc", "peacock"), "SNF"),
    NetworkGroup(
        "espn_abc",
        "ESPN/ABC",
        ("espn", "abc", "espn2", "espn_plus", "espn_deportes"),
        "MNF",
    ),
    NetworkGroup("prime", "Amazon", ("prime",), "TNF"),
    NetworkGroup("nfln", "NFL Network", ("nfln",), None),
    NetworkGroup("netflix", "Netflix", ("netflix",), None),
    NetworkGroup("youtube", "YouTube", ("youtube",), None),
    NetworkGroup("yahoo", "Yahoo", ("yahoo",), None),
)

NETWORK_GROUP_IDS: frozenset[str] = frozenset(g.id for g in NETWORK_GROUPS)
GROUP_OF_NETWORK: Mapping[str, str] = {m: g.id for g in NETWORK_GROUPS for m in g.members}


def network_group_of(network_id: str | None) -> str | None:
    """The group id for a network id, or None for a null or unknown network."""
    if network_id is None:
        return None
    return GROUP_OF_NETWORK.get(network_id)
