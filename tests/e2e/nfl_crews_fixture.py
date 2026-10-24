"""Synthetic NFL Crews overlay for the Phase 15 Crews, Viewership and pick tests.

`build_nfl_crews_raw(base)` deep-copies the built synthetic `nfl-data.json` and appends
invented people, games and booth rows (the frozen contract fixture file is never edited).
Nothing here reads `data/vault`; every person, game and figure is invented.

Each `CASE_*` constant documents the rows the Crews table must show for that case, so later
plans assert against the constants, not magic numbers. Pooled rows are keyed
`(network group, play-by-play person, analyst)`; per-season rows are the booth rows with
games. The base fixture's own rows stay as they are, so the totals include them.

Residual samples come from `random.Random(15)`. The shipped fixture shows booth residuals
and standard errors at three decimals (the builder passes the upstream values through
unrounded), so the overlay rounds the same way. Pooling those rounded per-season
`(n, mean, se)` values differs from `POOL_ORACLE` (computed from the raw samples with
`mean_se`) by at most 0.0005 in the mean and well under `POOL_TOLERANCE` in the SE.
"""

from __future__ import annotations

import copy
import random
from typing import Any

import polars as pl

from booth_review.nfl.adjust import LOW_N, mean_se

# Network group indexes in the base fixture's lookups (members: fox 0, cbs 1, nbc 2 and 5).
GROUP_FOX = 0
GROUP_CBS = 1
GROUP_NBC = 2
_GROUP_NETWORK = {GROUP_FOX: 0, GROUP_CBS: 1, GROUP_NBC: 2}

#: Pooled mean and SE from the shipped three-decimal rounding may differ from the oracle
#: by up to this much (a comment-stated bound; the mean differs by at most 0.0005).
POOL_TOLERANCE = 0.01

# -- Expected cases ---------------------------------------------------------------------------
# The Crews table pages 25 rows at a time; CASE_MANY adds enough pairs that the pooled table
# is longer than one page. Counts are filled in after the build (see the bottom of the module).
CASE_MANY = {"group": "fox", "season": 2025, "pairs": 24, "prefix": "synth-many"}
# Orchestrator ruling 1: one PBP with analyst A1 in 2024-2025 and A2 in 2026 in one group:
# three season rows, two pooled pair rows, one catalog key `fox:synth-pbp-two`.
CASE_TWO_ANALYSTS = {
    "group": "fox",
    "pbp": "synth-pbp-two",
    "analysts": {"synth-an-two-a": [2024, 2025], "synth-an-two-b": [2026]},
    "catalog_key": "fox:synth-pbp-two",
    "pooled_rows": 2,
    "season_rows": 3,
}
# D-01: one pair in fox 2024 and cbs 2025, which are two pooled rows (the group is in the key).
CASE_MOVED = {
    "pbp": "synth-pbp-move",
    "analyst": "synth-an-move",
    "groups": {2024: "fox", 2025: "cbs"},
    "pooled_rows": 2,
}
# A pair season whose adjusted margin residual is null although its adjusted n is above zero.
CASE_NULL_RESID = {"pbp": "synth-pbp-nullr", "analyst": "synth-an-nullr", "season": 2025, "n": 3}
# A pair season with adj_n_margin = 1: a mean, and a null standard error.
CASE_N1 = {"pbp": "synth-pbp-one", "analyst": "synth-an-one", "season": 2025, "n": 1}
# Two seasons with n 5 and 4: each is flagged low-n per season, the pooled n of 9 is not.
CASE_LOW_POOL = {
    "pbp": "synth-pbp-lowp",
    "analyst": "synth-an-lowp",
    "ns": {2024: 5, 2025: 4},
    "pooled_n": 9,
}
# A pair whose games carry era 0 in 2024 and era 1 in 2025: a cross-era pooled row.
CASE_CROSS_ERA = {
    "pbp": "synth-pbp-era",
    "analyst": "synth-an-era",
    "eras": {2024: 0, 2025: 1},
    "ns": {2024: 6, 2025: 6},
}
# One game of this row's list has scope "window" (a window-level figure).
CASE_WINDOW = {"pbp": "synth-pbp-win", "analyst": "synth-an-win", "season": 2025, "window_games": 1}
# One game of this row's list names an analyst other than the row's analyst_person.
CASE_FILL_IN = {
    "pbp": "synth-pbp-fill",
    "analyst": "synth-an-fill",
    "fill_in": "synth-an-sub",
    "season": 2025,
    "games": 4,
    "fill_in_games": 1,
}
# A row with analyst_person null (a play-by-play voice alone).
CASE_NULL_ANALYST = {"pbp": "synth-pbp-solo", "season": 2025, "games": 3}
# A person who is the PBP of one row and the analyst on another row's games.
CASE_MIXED_SEAT = {
    "person": "synth-mix-seat",
    "pbp_row": {"group": "fox", "season": 2025, "analyst": "synth-an-mixa"},
    "analyst_row": {"group": "cbs", "season": 2025, "pbp": "synth-pbp-mixb"},
}

#: Pooled `(n, mean, se)` of the adjusted margin residual from the raw samples, keyed
#: `"<group id>:<pbp slug>:<analyst slug>"`, for the pooled cases.
POOL_ORACLE: dict[str, tuple[int, float | None, float | None]] = {}
#: The same for the adjusted excitement residual.
POOL_ORACLE_EXCITEMENT: dict[str, tuple[int, float | None, float | None]] = {}

_GROUP_IDS = {GROUP_FOX: "fox", GROUP_CBS: "cbs", GROUP_NBC: "nbc"}
_ERA_OF_SEASON = {2024: 0, 2025: 1, 2026: 1}

EXPECT_POOLED_ROWS = 0
EXPECT_SEASON_ROWS = 0


class _Builder:
    def __init__(self, base: dict[str, Any]) -> None:
        self.raw = copy.deepcopy(base)
        self.games = self.raw["games"]
        self.booths = self.raw["booths"]
        self.people = self.raw["lookups"]["people"]
        self.person_index = {p["id"]: i for i, p in enumerate(self.people)}
        self.template = {k: v[14] for k, v in self.games.items()}  # a cbs 2024 game, rated
        self.rng = random.Random(15)
        self.counter = 0
        # Pairs visible to the pool oracle: key -> (margin samples, excitement samples)
        self.samples: dict[str, tuple[list[float], list[float]]] = {}

    def person(self, slug: str) -> int:
        if slug not in self.person_index:
            self.person_index[slug] = len(self.people)
            self.people.append({"id": slug, "name": slug.replace("-", " ").title()})
        return self.person_index[slug]

    def _game(
        self,
        season: int,
        network: int,
        crew: list[dict[str, Any]],
        *,
        scope: str = "game",
        era: int | None = None,
    ) -> int:
        """Append one game (every column) and return its index."""
        n = len(self.games["season"])
        row = dict(self.template)
        k = self.counter
        self.counter += 1
        home = k % 6
        away = (k + 1) % 6
        row.update(
            season=season,
            date=f"{season}-{9 + k % 3:02d}-{10 + k % 18:02d}",
            kickoff=f"{season}-{9 + k % 3:02d}-{10 + k % 18:02d}T13:00:00-04:00",
            home=home,
            away=away,
            network=network,
            crew=crew,
            final_margin=1 + k % 21,
            excitement=round(2.0 + (k % 70) / 10, 3),
            viewers=6_000_000 + 100_000 * (k % 40),
            era=_ERA_OF_SEASON[season] if era is None else era,
            scope=scope,
            week=1 + k % 17,
        )
        for col in self.games:
            self.games[col].append(row[col])
        return n

    def row(
        self,
        season: int,
        group: int,
        pbp: str,
        analyst: str | None,
        n_games: int,
        *,
        n_adj: int | None = None,
        null_resid: bool = False,
        window: int = 0,
        fill_in: str | None = None,
        era: int | None = None,
        rank: int = 9,
        pool_key: str | None = None,
    ) -> None:
        """Append `n_games` games and one booth row; residuals come from the seeded RNG."""
        pbp_i = self.person(pbp)
        an_i = None if analyst is None else self.person(analyst)
        crew = [{"person": pbp_i, "role": "pbp"}]
        if an_i is not None:
            crew.append({"person": an_i, "role": "analyst"})
        game_list: list[int] = []
        for j in range(n_games):
            this_crew = crew
            if fill_in is not None and j == n_games - 1:
                this_crew = [crew[0], {"person": self.person(fill_in), "role": "analyst"}]
            scope = "window" if j < window else "game"
            game_list.append(
                self._game(season, _GROUP_NETWORK[group], this_crew, scope=scope, era=era)
            )
        n_adj = n_games if n_adj is None else n_adj
        margin = [round(self.rng.gauss(0.5, 3.0), 3) for _ in range(n_adj)]
        exc = [round(self.rng.gauss(-0.2, 0.8), 3) for _ in range(n_adj)]
        _, m_mean, m_se = mean_se(pl.Series(margin, dtype=pl.Float64))
        _, e_mean, e_se = mean_se(pl.Series(exc, dtype=pl.Float64))
        if pool_key is not None:
            acc = self.samples.setdefault(pool_key, ([], []))
            acc[0].extend(margin)
            acc[1].extend(exc)

        def r3(x: float | None) -> float | None:
            return None if x is None else round(x, 3)

        views = [self.games["viewers"][g] for g in game_list]
        values: dict[str, Any] = {
            "season": season,
            "network_group": group,
            "pbp_person": pbp_i,
            "analyst_person": an_i,
            "rank": rank,
            "rank_source": "inferred",
            "games": n_games,
            "game_list": game_list,
            "is_lead": False,
            "flagship_games": 0,
            "lineup_games": 0,
            "fill_in_games": 0 if fill_in is None else 1,
            "raw_n_margin": n_games,
            "raw_mean_abs_margin": round(
                sum(self.games["final_margin"][g] for g in game_list) / n_games, 4
            ),
            "raw_n_excitement": n_games,
            "raw_mean_excitement": round(
                sum(self.games["excitement"][g] for g in game_list) / n_games, 4
            ),
            "raw_n_viewers": n_games,
            "raw_mean_viewers": round(sum(views) / n_games, 4),
            "adj_n_margin": n_adj,
            "adj_margin_resid": None if null_resid else r3(m_mean),
            "adj_margin_se": None if null_resid else r3(m_se),
            "adj_n_excitement": n_adj,
            "adj_excitement_resid": r3(e_mean),
            "adj_excitement_se": r3(e_se),
            "low_n": n_adj < LOW_N,
        }
        for col in self.booths:
            self.booths[col].append(values[col])


def build_nfl_crews_raw(base: dict[str, Any]) -> dict[str, Any]:
    """The built synthetic `nfl-data.json` plus every NFL Crews case. The input is not mutated."""
    global EXPECT_POOLED_ROWS, EXPECT_SEASON_ROWS
    b = _Builder(base)
    POOL_ORACLE.clear()
    POOL_ORACLE_EXCITEMENT.clear()

    def key(group: int, pbp: str, analyst: str) -> str:
        return f"{_GROUP_IDS[group]}:{pbp}:{analyst}"

    # CASE_MANY: 24 distinct one-season pairs on fox 2025, one to three games each.
    for i in range(CASE_MANY["pairs"]):
        b.row(2025, GROUP_FOX, f"synth-many-pbp-{i:02d}", f"synth-many-an-{i:02d}", 1 + i % 3)

    # CASE_TWO_ANALYSTS: one PBP, two analysts on one group.
    pbp = CASE_TWO_ANALYSTS["pbp"]
    for analyst, seasons in CASE_TWO_ANALYSTS["analysts"].items():  # type: ignore[attr-defined]
        for season in seasons:
            b.row(
                season,
                GROUP_FOX,
                pbp,
                analyst,
                9,
                rank=2,
                pool_key=key(GROUP_FOX, pbp, analyst),
            )

    # CASE_MOVED: the same pair on fox then cbs.
    b.row(2024, GROUP_FOX, CASE_MOVED["pbp"], CASE_MOVED["analyst"], 5, rank=3)
    b.row(2025, GROUP_CBS, CASE_MOVED["pbp"], CASE_MOVED["analyst"], 5, rank=3)

    b.row(
        CASE_NULL_RESID["season"],
        GROUP_CBS,
        CASE_NULL_RESID["pbp"],
        CASE_NULL_RESID["analyst"],
        CASE_NULL_RESID["n"],
        null_resid=True,
    )
    b.row(
        CASE_N1["season"],
        GROUP_NBC,
        CASE_N1["pbp"],
        CASE_N1["analyst"],
        CASE_N1["n"],
    )
    for season, n in CASE_LOW_POOL["ns"].items():  # type: ignore[attr-defined]
        b.row(
            season,
            GROUP_NBC,
            CASE_LOW_POOL["pbp"],
            CASE_LOW_POOL["analyst"],
            n,
            pool_key=key(GROUP_NBC, CASE_LOW_POOL["pbp"], CASE_LOW_POOL["analyst"]),  # type: ignore[arg-type]
        )
    for season, n in CASE_CROSS_ERA["ns"].items():  # type: ignore[attr-defined]
        b.row(
            season,
            GROUP_CBS,
            CASE_CROSS_ERA["pbp"],
            CASE_CROSS_ERA["analyst"],
            n,
            era=CASE_CROSS_ERA["eras"][season],  # type: ignore[index]
            pool_key=key(GROUP_CBS, CASE_CROSS_ERA["pbp"], CASE_CROSS_ERA["analyst"]),  # type: ignore[arg-type]
        )
    b.row(
        CASE_WINDOW["season"],
        GROUP_NBC,
        CASE_WINDOW["pbp"],
        CASE_WINDOW["analyst"],
        4,
        window=CASE_WINDOW["window_games"],
    )
    b.row(
        CASE_FILL_IN["season"],
        GROUP_NBC,
        CASE_FILL_IN["pbp"],
        CASE_FILL_IN["analyst"],
        CASE_FILL_IN["games"],
        fill_in=CASE_FILL_IN["fill_in"],
    )
    b.row(CASE_NULL_ANALYST["season"], GROUP_CBS, CASE_NULL_ANALYST["pbp"], None, 3)
    seat = CASE_MIXED_SEAT["person"]
    b.row(2025, GROUP_FOX, seat, CASE_MIXED_SEAT["pbp_row"]["analyst"], 4)  # type: ignore[index]
    b.row(2025, GROUP_CBS, CASE_MIXED_SEAT["analyst_row"]["pbp"], seat, 4)  # type: ignore[index]

    for k, (margin, exc) in b.samples.items():
        POOL_ORACLE[k] = mean_se(pl.Series(margin, dtype=pl.Float64))
        POOL_ORACLE_EXCITEMENT[k] = mean_se(pl.Series(exc, dtype=pl.Float64))

    cols = b.booths
    pairs = {
        (cols["network_group"][i], cols["pbp_person"][i], cols["analyst_person"][i])
        for i in range(len(cols["season"]))
        if cols["games"][i] > 0
    }
    EXPECT_SEASON_ROWS = sum(1 for g in cols["games"] if g > 0)
    EXPECT_POOLED_ROWS = len(pairs)
    return b.raw
