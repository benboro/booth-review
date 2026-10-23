"""Synthetic, site-data-shaped crews dataset for the Phase 14 Crews table tests.

`build_crews_raw(fixture_raw)` deep-copies the shared contract fixture and replaces its
telecast blocks, people, networks, flags and booths with a deterministic generated set.
Every person, network and game is invented (no vault data). Each `CASE_*` constant
documents the row the Crews table must show for that case, so later plans assert against
the constants, not magic numbers.

Seasons run 2022..2025. Rated games carry an era flag (`era-ooh-2020` through 2022,
`era-nielsen-2023` from 2023) and, from 2025, the `model-break-2025` flag.
"""

from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Any

# -- Lookup indexes (the shared fixture's first five networks stay as they are) -------------
NET_A = 0  # disney
NET_B = 1  # fox
NET_C = 2  # conference
NET_D = 3  # other
NET_REG1 = 5  # invented, family "conference", not a big-four network
NET_REG2 = 6  # invented, family "other", not a big-four network
FLAG_ERA_A = 0  # era-ooh-2020 (shared fixture)
FLAG_MODEL_BREAK = 3  # model-break-2025 (shared fixture)
FLAG_ERA_B = 5  # era-nielsen-2023 (added here)

# -- Expected cases (each is the outcome later plans assert) ----------------------------------
# D-02: one play-by-play voice whose modal lineup is two analysts; one of its 5 games has
# only the first analyst, so the row's crew is the pbp plus both analysts, 5 games.
CASE_TRIO = {"pbp": "trio-pbp", "analysts": ["trio-a1", "trio-a2"], "games": 5}
# D-03: one exact pair seen on a disney network (2 games) and a fox network (2 games).
CASE_TWO_FAMILIES = {
    "pbp": "fam-pbp",
    "analyst": "fam-ana",
    "families": ["disney", "fox"],
    "games": 4,
}
# D-04: one pair on two non-big-four networks, 2 games each, giving two rows.
CASE_NON_BIG_FOUR = {
    "pbp": "reg-pbp",
    "analyst": "reg-ana",
    "networks": ["Regional One", "Regional Two"],
    "rows": 2,
    "games_per_row": 2,
}
# D-05: one telecast whose main-feed people are all role "unknown" (no pbp).
CASE_NO_PBP = {"people": ["nopbp-x", "nopbp-y"], "games": 1}
# A PBP-resolved crew that lists an `unknown` sideline person in 2 of its 3 games; the
# sideline person must not change the crew.
CASE_SIDELINE = {
    "pbp": "side-pbp",
    "analyst": "side-ana",
    "sideline": "side-rep",
    "games": 3,
    "games_with_sideline": 2,
}
# D-01: a cited booth game (disney 2024, rank 1, tier a) where the regular analyst is
# absent: 3 games with the regular analyst, 1 with the fill-in. The booth index is the same.
CASE_FILL_IN = {
    "pbp": "fill-pbp",
    "regular_analyst": "fill-ana",
    "fill_in": "fill-sub",
    "games": 4,
    "fill_in_games": 1,
    "tier": "a",
}
# A tiered family-season (disney 2024, rank 2, tier b) whose shipped booth analyst
# (`cite-cited`) differs from the most common analyst (`cite-modal`, 3 of 4 games).
CASE_CITED_NOT_MODAL = {
    "pbp": "cite-pbp",
    "cited_analyst": "cite-cited",
    "modal_analyst": "cite-modal",
    "games": 4,
    "tier": "b",
}
# One telecast with no main-feed crew at all.
CASE_NO_CREW = {"games": 1, "network": "net-a"}
# A2(c): two no-PBP telecasts on net-d with the same two people. In game 1 both are role
# `unknown`; in game 2 person X is `analyst` and Y `unknown`. The pooled row tags Y
# "unknown role" and X "unknown role in 1 of 2 games".
CASE_MIXED_UNKNOWN = {
    "x": "mix-x",
    "y": "mix-y",
    "network": "net-d",
    "games": 2,
    "tag_x": "unknown role in 1 of 2 games",
    "tag_y": "unknown role",
}
# D-11: a crew with 9 rated games, all with excitement (>= 8 values).
CASE_FULL_N = {"pbp": "full-pbp", "analyst": "full-ana", "rated": 9, "excitement_values": 9}
# A crew with 3 rated games (1-7) plus 1 unrated game.
CASE_LOW_N = {"pbp": "low-pbp", "analyst": "low-ana", "rated": 3, "unrated": 1}
# A crew with games in 2024 (2 rated) and 2025 (2 rated, model-break flag).
CASE_BREAK = {"pbp": "brk-pbp", "analyst": "brk-ana", "seasons": [2024, 2025], "games": 4}
# A crew whose rated games span two Nielsen eras: 2022 (era-ooh-2020), 2023 (era-nielsen-2023).
CASE_ERA = {
    "pbp": "era-pbp",
    "analyst": "era-ana",
    "era_flags": ["era-ooh-2020", "era-nielsen-2023"],
    "games": 4,
}
# One unrated one-game crew with no figures; it sorts last under any default sort (fewest
# games, no viewers, no excitement, last by name), so it falls past the 25-row cut (D-13).
CASE_PAST_CUT = {"pbp": "zz-cut-pbp", "analyst": "zz-cut-ana", "games": 1}
# 14-08: a crew with 20 games (two pages of 10) and its pbp's other pairing, 3 games with a
# second analyst, so a person row has a two-partner "Worked with" list ordered by count.
CASE_BIG = {
    "pbp": "big-pbp",
    "analyst": "big-ana",
    "other_analyst": "big-ana2",
    "games": 20,
    "other_games": 3,
}
N_FILLER_CREWS = 40  # filler pairs, 2 games each (the first 8 also have an unrated game)

_Role = tuple[str, str]  # (person slug, role)


class _Game:
    def __init__(
        self,
        season: int,
        network: int,
        crew: list[_Role],
        *,
        rated: bool = True,
        viewers: int = 1_000_000,
        excitement: float | None = 6.0,
        booth: str | None = None,
    ) -> None:
        self.season = season
        self.network = network
        self.crew = crew
        self.rated = rated
        self.viewers = viewers
        self.excitement = excitement
        self.booth = booth


def _pair(pbp: str, ana: str) -> list[_Role]:
    return [(pbp, "pbp"), (ana, "analyst")]


def _games() -> list[_Game]:
    g: list[_Game] = []
    # Trio (D-02): 4 games with both analysts, 1 with the first only.
    for i in range(4):
        g.append(
            _Game(
                2024,
                NET_A,
                [("trio-pbp", "pbp"), ("trio-a1", "analyst"), ("trio-a2", "analyst")],
                viewers=900_000 + i * 50_000,
                excitement=5.0 + i,
            )
        )
    g.append(_Game(2024, NET_A, _pair("trio-pbp", "trio-a1"), viewers=700_000, excitement=4.0))
    # One pair in two families (D-03).
    for i in range(2):
        g.append(_Game(2024, NET_A, _pair("fam-pbp", "fam-ana"), viewers=1_100_000 + i * 10_000))
        g.append(_Game(2024, NET_B, _pair("fam-pbp", "fam-ana"), viewers=800_000 + i * 10_000))
    # One pair on two non-big-four networks (D-04).
    for i in range(2):
        g.append(_Game(2023, NET_REG1, _pair("reg-pbp", "reg-ana"), viewers=400_000 + i * 5_000))
        g.append(_Game(2023, NET_REG2, _pair("reg-pbp", "reg-ana"), viewers=300_000 + i * 5_000))
    # D-05: a telecast whose main-feed people are all unknown.
    g.append(_Game(2024, NET_A, [("nopbp-x", "unknown"), ("nopbp-y", "unknown")]))
    # PBP-resolved crew with an unknown sideline person in 2 of 3 games.
    for i in range(3):
        crew = _pair("side-pbp", "side-ana")
        if i < 2:
            crew = [*crew, ("side-rep", "unknown")]
        g.append(_Game(2024, NET_B, crew, viewers=650_000 + i * 20_000))
    # D-01: cited booth with a fill-in (disney 2024, rank 1).
    for _ in range(3):
        g.append(_Game(2024, NET_A, _pair("fill-pbp", "fill-ana"), booth="fill"))
    g.append(_Game(2024, NET_A, _pair("fill-pbp", "fill-sub"), booth="fill"))
    # The cited analyst is not the modal one (disney 2024, rank 2).
    for _ in range(3):
        g.append(_Game(2024, NET_A, _pair("cite-pbp", "cite-modal"), booth="cite"))
    g.append(_Game(2024, NET_A, _pair("cite-pbp", "cite-cited"), booth="cite"))
    # No main-feed crew at all.
    g.append(_Game(2024, NET_A, [], viewers=500_000, excitement=None))
    # A2(c): the same two people, unknown in only one of two no-PBP games.
    g.append(_Game(2024, NET_D, [("mix-x", "unknown"), ("mix-y", "unknown")]))
    g.append(_Game(2024, NET_D, [("mix-x", "analyst"), ("mix-y", "unknown")]))
    # D-11: 9 rated games, all with excitement.
    for i in range(9):
        g.append(
            _Game(
                2023 + i % 3,
                NET_A,
                _pair("full-pbp", "full-ana"),
                viewers=1_500_000 + i * 100_000,
                excitement=4.0 + i * 0.5,
            )
        )
    # 3 rated games plus 1 unrated.
    for i in range(3):
        g.append(
            _Game(
                2024,
                NET_B,
                _pair("low-pbp", "low-ana"),
                viewers=600_000 + i * 30_000,
                excitement=5.5,
            )
        )
    g.append(_Game(2024, NET_B, _pair("low-pbp", "low-ana"), rated=False, excitement=None))
    # Games on both sides of 2025.
    for season in (2024, 2024, 2025, 2025):
        g.append(_Game(season, NET_B, _pair("brk-pbp", "brk-ana"), excitement=6.5))
    # Two Nielsen eras (2022, 2023).
    for season in (2022, 2022, 2023, 2023):
        g.append(_Game(season, NET_A, _pair("era-pbp", "era-ana"), excitement=7.0))
    # 14-08: the 20-game crew and the pbp's 3-game second pairing.
    for i in range(CASE_BIG["games"]):
        g.append(
            _Game(
                2023 + i % 3,
                NET_A,
                _pair("big-pbp", "big-ana"),
                viewers=1_000_000 + i * 20_000,
                excitement=5.0 + i * 0.1,
                rated=i % 7 != 6,
            )
        )
    for i in range(CASE_BIG["other_games"]):
        g.append(_Game(2024, NET_B, _pair("big-pbp", "big-ana2"), viewers=500_000 + i * 10_000))
    # Filler crews so Crew mode has well over 25 rows.
    for i in range(N_FILLER_CREWS):
        pbp, ana = f"filler-{i:02d}-pbp", f"filler-{i:02d}-ana"
        season = 2023 + i % 3
        net = (NET_A, NET_B, NET_C)[i % 3]
        g.append(
            _Game(
                season, net, _pair(pbp, ana), viewers=200_000 + i * 40_000, excitement=3.0 + i * 0.2
            )
        )
        g.append(
            _Game(
                season, net, _pair(pbp, ana), viewers=250_000 + i * 40_000, excitement=3.5 + i * 0.2
            )
        )
        if i < 8:
            g.append(_Game(season, net, _pair(pbp, ana), rated=False, excitement=None))
    # The one-game crew with no figures.
    g.append(_Game(2024, NET_C, _pair("zz-cut-pbp", "zz-cut-ana"), rated=False, excitement=None))
    return g


_BOOTHS = {
    # key: (family, season, pbp, analyst, rank, tier); sorted by family, season, pbp slug
    "cite": ("disney", 2024, "cite-pbp", "cite-cited", 2, "b"),
    "fill": ("disney", 2024, "fill-pbp", "fill-ana", 1, "a"),
}


def _usual_role(slug: str) -> str:
    if slug.endswith("pbp") or slug.endswith("-pbp"):
        return "pbp"
    if slug.endswith(("-x", "-y", "-rep")):
        return "unknown"
    return "analyst"


def build_crews_raw(fixture_raw: dict[str, Any]) -> dict[str, Any]:
    """The shared contract fixture with its games, people, networks, flags and booths
    replaced by the synthetic crews set. The input is never mutated."""
    raw = copy.deepcopy(fixture_raw)
    rated_t = {k: v[0] for k, v in fixture_raw["telecasts"].items()}
    unrated_t = {k: v[0] for k, v in fixture_raw["telecasts_unrated"].items()}

    games = _games()
    slugs = sorted({s for gm in games for s, _ in gm.crew})
    for key in _BOOTHS:
        slugs.extend(s for s in (_BOOTHS[key][2], _BOOTHS[key][3]) if s not in slugs)
    slugs = sorted(set(slugs))
    index = {s: i for i, s in enumerate(slugs)}
    raw["lookups"]["people"] = [
        {
            "id": s,
            "name": s.replace("-", " ").title(),
            "variants": [s.replace("-", " ").title()],
            "usual_role": _usual_role(s),
        }
        for s in slugs
    ]
    raw["lookups"]["networks"] = [
        *fixture_raw["lookups"]["networks"],
        {"id": "net-f", "name": "Regional One", "family": "conference"},
        {"id": "net-g", "name": "Regional Two", "family": "other"},
    ]
    raw["lookups"]["flags"] = [
        *fixture_raw["lookups"]["flags"],
        {
            "id": "era-nielsen-2023",
            "kind": "era",
            "label": "Nielsen era (2023)",
            "source_url": "https://example.com/era-nielsen-2023",
        },
    ]
    booth_keys = sorted(_BOOTHS, key=lambda k: (_BOOTHS[k][0], _BOOTHS[k][1], _BOOTHS[k][2]))
    raw["lookups"]["booths"] = [
        {
            "family": _BOOTHS[k][0],
            "season": _BOOTHS[k][1],
            "pbp": index[_BOOTHS[k][2]],
            "analyst": index[_BOOTHS[k][3]],
            "rank": _BOOTHS[k][4],
            "tier": _BOOTHS[k][5],
            "lead_network": None,
        }
        for k in booth_keys
    ]
    booth_index = {k: i for i, k in enumerate(booth_keys)}

    rated_rows: list[dict[str, Any]] = []
    unrated_rows: list[dict[str, Any]] = []
    n_teams = len(raw["lookups"]["teams"])
    n_venues = len(raw["lookups"]["venues"])
    for n, gm in enumerate(games):
        base = rated_t if gm.rated else unrated_t
        row = copy.deepcopy(base)
        day = date(gm.season, 8, 25) + timedelta(days=n % 120)
        away = n % n_teams
        home = (n * 3 + 1) % n_teams
        if home == away:
            home = (home + 1) % n_teams
        row.update(
            season=gm.season,
            date=day.isoformat(),
            kickoff=f"{day.isoformat()}T15:30:00-04:00",
            time_slot="afternoon",
            away_team=away,
            home_team=home,
            neutral=False,
            away_points=17 + n % 10,
            home_points=24 + n % 14,
            away_rank=None,
            home_rank=None,
            network=gm.network,
            outlets=[gm.network],
            s506_url=f"https://example.com/506/crews/{n}",
            crew_source_url=None,
            crew_source_label=None,
            excitement=gm.excitement,
            home_spread=float(n % 15) - 7.0,
            crew=[{"person": index[s], "role": r, "feed": "main"} for s, r in gm.crew],
            game_type="regular",
            playoff_round=None,
            bowl=None,
            rivalry=None,
            place=n % n_venues,
            booth=booth_index[gm.booth] if gm.booth else None,
        )
        if gm.rated:
            flags = [FLAG_ERA_A if gm.season <= 2022 else FLAG_ERA_B]
            if gm.season >= 2025:
                flags.append(FLAG_MODEL_BREAK)
            row.update(
                viewers=gm.viewers,
                measurement_type="nielsen",
                publisher=0,
                source_url=f"https://example.com/source/crews/{n}",
                rr_urls=[f"https://ratingsreference.com/telecast/cfb-invented-crews-{n}"],
                figure_source="rr",
                flags=flags,
                combined_feeds=None,
            )
            rated_rows.append(row)
        else:
            row.update(cause="none")
            unrated_rows.append(row)

    raw["telecasts"] = {k: [r[k] for r in rated_rows] for k in rated_t}
    raw["telecasts_unrated"] = {k: [r[k] for r in unrated_rows] for k in unrated_t}
    return raw
