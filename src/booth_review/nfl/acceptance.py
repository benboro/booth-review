"""2014-2015 build acceptance (roadmap): every regular-season standalone game
must carry a non-empty set of Ratings Reference networks.

The gate reads `rr_network_ids`, never the single `rr_network_id`, which is
null by design for multi-network simulcasts (2014-2015 TNF on CBS and NFL
Network, 2015 MNF on ESPN and ABC). Those pass and are reported in
`multi_network`. Standalone games from 2016 on without an RR network are only
counted, never failing.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

ACCEPTANCE_SEASONS = (2014, 2015)
REASON_NO_RR_NETWORK = "no-rr-network"


@dataclass(frozen=True)
class AcceptanceResult:
    unmatched: int
    rows: tuple[dict[str, object], ...]
    informational_2016_plus: int
    multi_network: int


def check_acceptance(frame: pl.DataFrame) -> AcceptanceResult:
    if frame.height == 0:
        return AcceptanceResult(0, (), 0, 0)
    standalone = frame.filter((pl.col("game_type") == "REG") & pl.col("is_standalone"))
    matched = pl.col("rr_network_ids").list.len() > 0
    gate = standalone.filter(pl.col("season").is_in(ACCEPTANCE_SEASONS))
    missing = gate.filter(~matched).sort(["season", "week", "game_id"])
    rows = tuple(
        {
            "season": r["season"],
            "week": r["week"],
            "game_id": r["game_id"],
            "game_date": r["game_date"],
            "reason": REASON_NO_RR_NETWORK,
        }
        for r in missing.select("season", "week", "game_id", "game_date").to_dicts()
    )
    multi = gate.filter(pl.col("rr_network_ids").list.len() >= 2).height
    later = standalone.filter(~pl.col("season").is_in(ACCEPTANCE_SEASONS) & ~matched).height
    return AcceptanceResult(
        unmatched=len(rows), rows=rows, informational_2016_plus=later, multi_network=multi
    )
