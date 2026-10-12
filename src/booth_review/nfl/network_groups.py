"""NFL network groups and each group's flagship window (D-03, D-04, D-21).

Every NFL network id belongs to exactly one group; a null network belongs to none.
Peacock sits under NBC and the Disney networks under `espn_abc` (D-21).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import polars as pl


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


def with_network_group(frame: pl.DataFrame) -> pl.DataFrame:
    """Add a nullable `network_group` column derived from `network_id`."""
    return frame.with_columns(
        pl.col("network_id")
        .replace_strict(GROUP_OF_NETWORK, default=None, return_dtype=pl.String)
        .alias("network_group")
    )


def flagship_expr() -> pl.Expr:
    """True for a game in its network group's flagship window (D-03, D-04).

    Reads `network_group`, `is_agotw`, `late_national_status`, `is_cbs_national` and
    `slot_name`. Uses slot_name rather than is_standalone so a Monday doubleheader game
    still counts as the MNF flagship.
    """
    group = pl.col("network_group")
    return (
        (
            (
                (group == "fox")
                & pl.col("is_agotw")
                & (pl.col("late_national_status") != "ambiguous")
            )
            | ((group == "cbs") & pl.col("is_cbs_national"))
            | ((group == "nbc") & (pl.col("slot_name") == "SNF"))
            | ((group == "espn_abc") & (pl.col("slot_name") == "MNF"))
            | ((group == "prime") & (pl.col("slot_name") == "TNF"))
        )
        .fill_null(False)
        .alias("is_flagship")
    )


#: Site pill families (plan 07).
NETWORK_FAMILY: Mapping[str, str] = {
    "abc": "disney",
    "espn": "disney",
    "espn2": "disney",
    "espn_plus": "disney",
    "espn_deportes": "disney",
    "fox": "fox",
    "cbs": "cbs",
    "nbc": "nbc",
    "peacock": "nbc",
    "prime": "other",
    "nfln": "other",
    "netflix": "other",
    "youtube": "other",
    "yahoo": "other",
}
