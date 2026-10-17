"""Generator for the synthetic MLB site-data fixture (phase 09 plan 10).

Everything here is invented: clubs, people, players, scores, viewer counts and
example.org URLs. Nothing is read from the vault. `build_fixture()` returns a
payload that already passed `validate_mlb_site_data`, and `main()` writes it to
tests/fixtures/contract/mlb-data.fixture.json in the same compact, key-sorted form
the MLB builder will use; tests/test_mlb_contract.py checks the committed file
equals this output.

Run: uv run python tests/mlb_site_fixture.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from booth_review.contract.mlb_models import (
    MLB_ROUNDS,
    MlbAppleBoothColumns,
    MlbGameColumns,
    MlbLineupColumns,
    MlbPostseasonColumns,
    validate_mlb_site_data,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "contract" / "mlb-data.fixture.json"

# Club, network and person indexes.
GULLS, LANTERNS, FOXES, OWLS, HERONS, BEARS = 0, 1, 2, 3, 4, 5
APPLE, FOX, TBS, ESPN = 0, 1, 2, 3
AL, NL = 0, 1

PEOPLE = [
    "Ada Quill",
    "Ben Marlow",
    "Cy Fable",
    "Dee Hart",
    "Eli Stroud",
    "Fay Lorn",
    "Gus Penn",
    "Hana Voss",
    "Ivo Reed",
]

POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]

GAME_DEFAULTS: dict[str, Any] = {
    "season": 2026,
    "date": "2026-04-05",
    "game_number": 0,
    "away": GULLS,
    "home": LANTERNS,
    "round": "regular",
    "series_league": None,
    "series_game": None,
    "network": None,
    "network_source": None,
    "network_source_url": None,
    "crew": [],
    "crew_source": None,
    "crew_source_url": None,
    "press_url": None,
    "press_name": None,
    "wp_excitement": None,
    "stakes": None,
    "viewers": None,
    "viewership_label": None,
    "scope": None,
    "era": None,
    "rr_url": None,
    "source_url": None,
    "cause": "pending",
    "lineup_status": "pending",
    "lineup_start": None,
    "lineup_end": None,
}


def _crew(pbp: int, analyst: int) -> list[dict[str, Any]]:
    return [{"person": pbp, "role": "pbp"}, {"person": analyst, "role": "analyst"}]


def _game(**changes: Any) -> dict[str, Any]:
    row = dict(GAME_DEFAULTS)
    row.update(changes)
    return row


def _relay(pbp: int, analyst: int, n: int) -> dict[str, Any]:
    return {
        "crew": _crew(pbp, analyst),
        "crew_source": "relay",
        "crew_source_url": f"https://example.org/relay/post-{n}",
        "press_url": f"https://example.org/press/release-{n}",
        "press_name": "Invented Press Room",
    }


def _506(pbp: int, analyst: int) -> dict[str, Any]:
    return {
        "crew": _crew(pbp, analyst),
        "crew_source": "506",
        "crew_source_url": "https://example.org/506/mlb-week",
    }


def _wiki(pbp: int, analyst: int, year: int) -> dict[str, Any]:
    return {
        "crew": _crew(pbp, analyst),
        "crew_source": "wikipedia",
        "crew_source_url": f"https://example.org/wiki/{year}_Invented_Series",
    }


def _outlet_506() -> dict[str, Any]:
    return {"network_source": "506", "network_source_url": None}


def _outlet_wiki(year: int) -> dict[str, Any]:
    return {
        "network_source": "wikipedia",
        "network_source_url": f"https://example.org/wiki/{year}_Invented_Series",
    }


def _rated(viewers: int, n: int, scope: str = "game") -> dict[str, Any]:
    return {
        "viewers": viewers,
        "viewership_label": "Viewers",
        "scope": scope,
        "era": 0,
        "rr_url": f"https://example.org/rr/telecast-{n}",
        "source_url": f"https://example.org/source/figure-{n}",
        "cause": None,
    }


def _lineup_rows(game: int, first_player: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    player = first_player
    for side in ("away", "home"):
        rows.append(_lineup_row(game, side, 0, player, "P", False))
        player += 1
        for slot, pos in enumerate(POSITIONS, start=1):
            rows.append(_lineup_row(game, side, slot, player, pos, side == "home" and slot == 9))
            player += 1
    return rows


def _lineup_row(
    game: int, side: str, slot: int, player: int, position: str, uncertain: bool
) -> dict[str, Any]:
    return {
        "game": game,
        "side": side,
        "slot": slot,
        "player": player,
        "position": position,
        "starter_uncertain": uncertain,
    }


def _games() -> list[dict[str, Any]]:
    apple = {"network": APPLE, **_outlet_506()}
    games = [
        # 0-5: Apple 2026 regular season
        _game(game_number=0, date="2026-04-03", **apple, **_relay(0, 1, 1), stakes=None),
        _game(
            game_number=0,
            date="2026-04-10",
            away=FOXES,
            home=OWLS,
            **apple,
            **_506(0, 1),
            **_rated(1_800_000, 1),
        ),
        _game(game_number=0, date="2026-04-17", away=HERONS, home=BEARS, **apple, **_506(2, 3)),
        _game(game_number=0, date="2026-04-24", away=OWLS, home=GULLS, **apple, **_relay(2, 3, 2)),
        _game(
            game_number=0,
            date="2026-05-01",
            away=BEARS,
            home=FOXES,
            **apple,
            **_506(4, 5),
            cause="none",
        ),
        _game(game_number=0, date="2026-05-08", away=LANTERNS, home=HERONS, **apple),
        # 6: 2014 wild card, no crew, lineup present
        _game(
            season=2014,
            date="2014-09-30",
            round="wild_card",
            series_league=AL,
            series_game=1,
            network=TBS,
            **_outlet_wiki(2014),
            wp_excitement=1.2,
            cause="none",
            lineup_status="present",
            lineup_start=0,
            lineup_end=19,
        ),
        # 7: 2014 World Series, Wikipedia crew, rated
        _game(
            season=2014,
            date="2014-10-21",
            away=FOXES,
            home=GULLS,
            round="world_series",
            series_game=1,
            network=FOX,
            **_outlet_wiki(2014),
            wp_excitement=2.4,
            lineup_status="missing",
            **_wiki(6, 7, 2014),
            **_rated(12_000_000, 2),
        ),
        # 8, 9: 2019 division series, per-network and an ambiguous doubleheader
        _game(
            season=2019,
            date="2019-10-04",
            round="division",
            series_league=AL,
            series_game=1,
            network=TBS,
            **_outlet_wiki(2019),
            wp_excitement=0.9,
            cause="per_network",
            lineup_status="missing",
            **_wiki(8, 7, 2019),
        ),
        _game(
            season=2019,
            date="2019-10-05",
            round="division",
            series_league=AL,
            series_game=2,
            network=TBS,
            **_outlet_wiki(2019),
            wp_excitement=1.6,
            cause="ambiguous_doubleheader",
            lineup_status="missing",
            **_wiki(8, 7, 2019),
        ),
        # 10: 2019 NLCS, rated
        _game(
            season=2019,
            date="2019-10-12",
            away=BEARS,
            home=OWLS,
            round="lcs",
            series_league=NL,
            series_game=1,
            network=FOX,
            **_outlet_wiki(2019),
            wp_excitement=1.1,
            lineup_status="missing",
            **_wiki(6, 7, 2019),
            **_rated(5_500_000, 3, scope="window"),
        ),
        # 11: 2025 wild card, 506 crew, conflicting figures
        _game(
            season=2025,
            date="2025-09-30",
            away=BEARS,
            home=FOXES,
            round="wild_card",
            series_league=NL,
            series_game=1,
            network=ESPN,
            **_outlet_506(),
            wp_excitement=1.4,
            cause="conflict",
            lineup_status="missing",
            **_506(2, 3),
        ),
        # 12: 2025 World Series, 506 crew, regional
        _game(
            season=2025,
            date="2025-10-24",
            away=GULLS,
            home=OWLS,
            round="world_series",
            series_game=1,
            network=FOX,
            **_outlet_506(),
            wp_excitement=2.0,
            cause="regional",
            lineup_status="missing",
            **_506(6, 7),
        ),
        # 13: 2026 ALCS, relay crew
        _game(
            date="2026-10-13",
            round="lcs",
            series_league=AL,
            series_game=1,
            network=FOX,
            **_outlet_506(),
            **_relay(0, 1, 3),
        ),
        # 14: 2026 NLDS, crew not listed
        _game(
            date="2026-10-06",
            away=BEARS,
            home=FOXES,
            round="division",
            series_league=NL,
            series_game=1,
            network=TBS,
            **_outlet_506(),
        ),
    ]
    return games


def _columns(rows: list[dict[str, Any]], names: tuple[str, ...]) -> dict[str, list[Any]]:
    return {name: [row[name] for row in rows] for name in names}


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _postseason(games: list[dict[str, Any]]) -> dict[str, list[Any]]:
    cells: list[tuple[int, str, int | None, list[int], list[int], list[list[int]]]] = [
        (2014, "wild_card", AL, [TBS], [6], []),
        (2014, "world_series", None, [FOX], [7], [[6, 7]]),
        (2019, "division", AL, [TBS], [8, 9], [[8, 7]]),
        (2019, "lcs", NL, [FOX], [10], [[6, 7]]),
        # A split cell: the round aired on two outlets.
        (2025, "wild_card", NL, [ESPN, TBS], [11], [[2, 3]]),
        (2025, "world_series", None, [FOX], [12], [[6, 7]]),
        (2026, "lcs", AL, [FOX], [13], [[0, 1]]),
        (2026, "division", NL, [TBS], [14], []),
    ]
    out: dict[str, list[Any]] = {name: [] for name in MlbPostseasonColumns.model_fields}
    for season, rnd, league, networks, idx, booths in cells:
        rows = [games[i] for i in idx]
        listed = sum(1 for r in rows if r["crew"])
        # A window-level audience is not one game's figure, so it stays out of the cell mean.
        viewers = [r["viewers"] for r in rows if r["viewers"] is not None and r["scope"] == "game"]
        wps = [r["wp_excitement"] for r in rows if r["wp_excitement"] is not None]
        out["season"].append(season)
        out["round"].append(rnd)
        out["league"].append(league)
        out["networks"].append(networks)
        wiki = {r["network_source_url"] for r in rows if r["network_source"] == "wikipedia"}
        out["outlet_source_url"].append(min(wiki) if wiki else None)
        out["booths"].append(booths)
        out["games"].append(len(rows))
        out["crew_listed"].append(listed)
        out["coverage_num"].append(listed)
        out["coverage_den"].append(len(rows))
        out["mean_excitement"].append(_mean(wps))
        out["excitement_n"].append(len(wps))
        out["viewers_mean"].append(_mean([float(v) for v in viewers]))
        out["viewers_n"].append(len(viewers))
        out["game_list"].append(idx)
    return out


# Postseason games that had no own-production outlet: counted in the season, in no cell.
NO_OUTLET_GAMES = {2019: 1}


def _seasons(post: dict[str, list[Any]]) -> dict[str, list[Any]]:
    seasons = sorted(set(post["season"]))
    num = [
        sum(n for s, n in zip(post["season"], post["coverage_num"], strict=True) if s == y)
        for y in seasons
    ]
    den = [
        sum(n for s, n in zip(post["season"], post["coverage_den"], strict=True) if s == y)
        + NO_OUTLET_GAMES.get(y, 0)
        for y in seasons
    ]
    return {"season": seasons, "coverage_num": num, "coverage_den": den}


def _apple_booths() -> dict[str, list[Any]]:
    rows = [
        ("Lead", 0, 1, [0, 1], 1, False),
        ("#2", 2, 3, [2, 3], 1, False),
        ("#3", 4, 5, [4], 0, True),
    ]
    out: dict[str, list[Any]] = {name: [] for name in MlbAppleBoothColumns.model_fields}
    for label, pbp, analyst, games, relay, low_n in rows:
        out["rank_label"].append(label)
        out["pbp"].append(pbp)
        out["analyst"].append(analyst)
        out["games"].append(len(games))
        out["crew_listed"].append(len(games))
        out["relay_crews"].append(relay)
        out["raw_stakes"].append(None)
        out["raw_stakes_n"].append(0)
        out["adj_stakes"].append(None)
        out["adj_stakes_se"].append(None)
        out["raw_excitement"].append(None)
        out["adj_excitement"].append(None)
        out["adj_excitement_se"].append(None)
        out["strength_prior"].append(None)
        out["low_n"].append(low_n)
        out["quality_status"].append("pending")
        out["game_list"].append(games)
    return out


def build_fixture() -> dict[str, Any]:
    games = _games()
    lineups = _lineup_rows(6, 0)
    post = _postseason(games)
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "freshness": {
            "season": 2026,
            "in_progress": True,
            "retrosheet_through_season": 2025,
            "quality_pending": True,
        },
        "constants": {
            "excitement_method": "WE-swing",
            "stakes_method": "pregame leverage",
            "low_n_threshold": 8,
            "coverage_bar": 0.8,
        },
        "lookups": {
            "clubs": [
                {"id": "gulls", "name": "Harbor City Gulls", "league": "AL", "division": "East"},
                {
                    "id": "lanterns",
                    "name": "Northfield Lanterns",
                    "league": "AL",
                    "division": "East",
                },
                {"id": "foxes", "name": "Quarry Hill Foxes", "league": "NL", "division": "West"},
                {"id": "owls", "name": "Mesa Verde Owls", "league": "NL", "division": "West"},
                {"id": "herons", "name": "Lakeshore Herons", "league": "AL", "division": "Central"},
                {"id": "bears", "name": "Pine Ridge Bears", "league": "NL", "division": "Central"},
            ],
            "team_names": [
                {
                    "club": 0,
                    "name": "Harbor City Gulls",
                    "short": "HCG",
                    "season_start": 2000,
                    "season_end": None,
                },
                {
                    "club": 1,
                    "name": "Northfield Lanterns",
                    "short": "NFL",
                    "season_start": 2000,
                    "season_end": None,
                },
                {
                    "club": 2,
                    "name": "Quarry Hill Foxes",
                    "short": "QHF",
                    "season_start": 2000,
                    "season_end": None,
                },
                {
                    "club": 3,
                    "name": "Mesa Verde Owls",
                    "short": "MVO",
                    "season_start": 2000,
                    "season_end": None,
                },
                {
                    "club": 4,
                    "name": "Lakeshore Herons",
                    "short": "LKH",
                    "season_start": 2000,
                    "season_end": None,
                },
                {
                    "club": 5,
                    "name": "Pine Ridge Bears",
                    "short": "PRB",
                    "season_start": 2000,
                    "season_end": None,
                },
            ],
            "networks": [
                {"id": "apple", "name": "Apple TV", "family": "apple"},
                {"id": "fox", "name": "Fox", "family": "fox"},
                {"id": "tbs", "name": "TBS", "family": "tbs"},
                {"id": "espn", "name": "ESPN", "family": "disney"},
            ],
            "people": [{"id": f"p{k}", "name": name} for k, name in enumerate(PEOPLE)],
            "players": [
                {"id": f"inv{k:03d}", "name": f"Invented Player {k:02d}"} for k in range(20)
            ],
            "rounds": list(MLB_ROUNDS),
            "leagues": [
                {"id": "AL", "name": "American League"},
                {"id": "NL", "name": "National League"},
            ],
            "eras": [
                {
                    "id": "e1",
                    "label": "Invented era",
                    "start": None,
                    "end": None,
                    "source_url": "https://example.org/era",
                }
            ],
        },
        "games": _columns(games, tuple(MlbGameColumns.model_fields)),
        "lineups": _columns(lineups, tuple(MlbLineupColumns.model_fields)),
        "apple_booths": _apple_booths(),
        "apple_summary": {
            "lead_minus_others_stakes": None,
            "lead_minus_others_stakes_se": None,
            "lead_minus_others_excitement": None,
            "lead_minus_others_excitement_se": None,
            "n_lead": 2,
            "n_others": 3,
            "rr_rated": 1,
            "apple_games": 6,
        },
        "postseason": post,
        "postseason_seasons": _seasons(post),
    }
    validate_mlb_site_data(payload)
    return payload


def render(obj: dict[str, Any]) -> str:
    """Compact, key-sorted JSON with no trailing newline, as the MLB builder writes."""
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, allow_nan=False)


def main() -> int:
    FIXTURE_PATH.write_text(render(build_fixture()))
    print(f"wrote {FIXTURE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
