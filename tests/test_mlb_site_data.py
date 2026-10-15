"""The MLB site-data builder and its commands (phase 09 plan 26).

Everything is synthetic: invented clubs, people, tables and URLs. Nothing is read from a
real vault and no request is sent.
"""

from __future__ import annotations

import functools
import json
import shutil
import subprocess
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from mlb_pipeline_support import make_reference, make_vault

from booth_review.build import site_assembly as sa
from booth_review.build.mlb_site_data import (
    MLB_SITE_DATA_PATH,
    MlbSiteInputs,
    build_mlb_site_data,
    load_mlb_site_inputs,
    mlb_site_payload_bytes,
    write_mlb_site_data,
)
from booth_review.build.site_assembly import assemble_site, load_mlb_site_payload
from booth_review.cli import main
from booth_review.config import DataPaths
from booth_review.contract.mlb_models import MLB_GAME_FIELDS, validate_mlb_site_data
from booth_review.errors import SiteBuildError
from booth_review.mlb import commands as mlb_commands
from booth_review.mlb import pipeline
from booth_review.mlb.pipeline import run_mlb_build

REPO_ROOT = Path(__file__).resolve().parents[1]
CFB_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "contract" / "site-data.fixture.json"
CANARY = "invented-private-canary-text"
TRAIN = 3

PEOPLE_CSV = (
    "person_id,canonical_name,variants,usual_role,role_override\n"
    "p1,Pia One,Pia One,pbp,\n"
    "p2,Quin Two,Quin Two,analyst,\n"
    "p3,Rex Three,Rex Three,pbp,\n"
    "p4,Sol Four,Sol Four,analyst,\n"
    "p5,Tia Five,Tia Five,pbp,\n"
    "p6,Uri Six,Uri Six,analyst,\n"
)
ERA = "rr-fixture-era-4"
RR = "https://ratingsreference.example/telecast/"
SRC = "https://source.example/figure/"

GAME_SCHEMA: dict[str, Any] = {
    "game_key": pl.String,
    "season": pl.Int32,
    "game_date": pl.Date,
    "series_league": pl.String,
    "series_game": pl.Int8,
    "home_score": pl.Int32,
    "pregame_stakes": pl.Float64,
    "wp_excitement": pl.Float64,
}
TELECAST_SCHEMA: dict[str, Any] = {
    "game_key": pl.String,
    "season": pl.Int32,
    "game_date": pl.Date,
    "away_club": pl.String,
    "home_club": pl.String,
    "game_number": pl.Int8,
    "network_id": pl.String,
    "production": pl.String,
    "round": pl.String,
    "series_game": pl.Int8,
    "pbp_person_id": pl.String,
    "analyst_person_ids": pl.List(pl.String),
    "crew_source": pl.String,
    "crew_source_url": pl.String,
    "press_url": pl.String,
    "press_name": pl.String,
    "crew_named": pl.Boolean,
    "booth_key": pl.String,
    "rr_cause": pl.String,
    "rr_viewers": pl.Float64,
    "rr_label": pl.String,
    "rr_url": pl.String,
    "rr_source_url": pl.String,
    "rr_era_id": pl.String,
}
LINEUP_SCHEMA: dict[str, Any] = {
    "game_key": pl.String,
    "side": pl.String,
    "slot": pl.Int8,
    "player_id": pl.String,
    "name": pl.String,
    "position": pl.Int8,
    "starter_uncertain": pl.Boolean,
}
BOOTH_SCHEMA: dict[str, Any] = {
    "booth_key": pl.String,
    "pbp_person_id": pl.String,
    "analyst_person_ids": pl.List(pl.String),
    "rank_label": pl.String,
    "games": pl.Int64,
    "crew_listed": pl.Int64,
    "relay_crews": pl.Int64,
    "stakes_n": pl.Int64,
    "stakes_raw": pl.Float64,
    "stakes_adj": pl.Float64,
    "stakes_adj_se": pl.Float64,
    "excitement_raw": pl.Float64,
    "excitement_adj": pl.Float64,
    "excitement_adj_se": pl.Float64,
    "strength_prior": pl.Float64,
    "low_n": pl.Boolean,
    "quality_status": pl.String,
}
SUMMARY_SCHEMA: dict[str, Any] = {
    "apple_games": pl.Int64,
    "rr_rated": pl.Int64,
    "lead_games": pl.Int64,
    "others_games": pl.Int64,
    "stakes_adj_diff": pl.Float64,
    "stakes_adj_diff_se": pl.Float64,
    "excitement_adj_diff": pl.Float64,
    "excitement_adj_diff_se": pl.Float64,
}
BOOTH_STRUCT = pl.Struct(
    {
        "booth_key": pl.String,
        "pbp_person_id": pl.String,
        "analyst_person_ids": pl.List(pl.String),
        "games": pl.Int64,
    }
)
POST_SCHEMA: dict[str, Any] = {
    "season": pl.Int32,
    "round": pl.String,
    "league": pl.String,
    "network_id": pl.String,
    "booths": pl.List(BOOTH_STRUCT),
    "games": pl.Int64,
    "crew_listed": pl.Int64,
    "coverage_num": pl.Int64,
    "coverage_den": pl.Int64,
    "mean_excitement": pl.Float64,
    "excitement_n": pl.Int64,
    "viewers_mean": pl.Float64,
    "viewers_n": pl.Int64,
    "game_list": pl.List(pl.String),
}
POST_SEASON_SCHEMA: dict[str, Any] = {
    "season": pl.Int32,
    "coverage_num": pl.Int64,
    "coverage_den": pl.Int64,
    "coverage_pct": pl.Float64,
    "below_bar": pl.Boolean,
}


def key(day: str, away: str, home: str, number: int = 0) -> str:
    return f"{day}|{away}|{home}|{number}"


A1 = key("2026-04-03", "alpha", "bravo")
A2 = key("2026-04-10", "alpha", "charlie")
A3 = key("2026-04-17", "bravo", "delta")
B1 = key("2026-04-04", "charlie", "delta")  # FOX regular season: never ships
B2 = key("2026-04-05", "delta", "alpha")  # Apple, but a partner production: never ships
W1 = key("2025-10-01", "charlie", "delta")
W2 = key("2025-10-02", "charlie", "delta")
D1 = key("2019-10-04", "alpha", "bravo")
S1 = key("2014-10-21", "charlie", "alpha")
O1 = key("2013-10-21", "charlie", "alpha")  # before 2014: never ships
LINEUP_GAMES = (A1, W1)


def _telecast(
    game: str,
    network: str,
    *,
    production: str = "own",
    rnd: str | None = None,
    pbp: str | None = None,
    analysts: tuple[str, ...] = (),
    source: str | None = None,
    url: str | None = None,
    press: tuple[str, str] | None = None,
    booth: str | None = None,
    cause: str | None = None,
    viewers: float | None = None,
    series_game: int | None = None,
) -> dict[str, Any]:
    day, away, home, number = game.split("|")
    return {
        "game_key": game,
        "season": int(day[:4]),
        "game_date": date.fromisoformat(day),
        "away_club": away,
        "home_club": home,
        "game_number": int(number),
        "network_id": network,
        "production": production,
        "round": rnd,
        "series_game": series_game,
        "pbp_person_id": pbp,
        "analyst_person_ids": list(analysts),
        "crew_source": source,
        "crew_source_url": url,
        "press_url": press[0] if press else None,
        "press_name": press[1] if press else None,
        "crew_named": pbp is not None and bool(analysts),
        "booth_key": booth,
        "rr_cause": cause,
        "rr_viewers": viewers,
        "rr_label": "per-game" if viewers else None,
        "rr_url": f"{RR}{game[:10]}" if viewers else None,
        "rr_source_url": f"{SRC}{game[:10]}" if viewers else None,
        "rr_era_id": ERA if viewers else None,
    }


def _game(
    game: str,
    *,
    league: str | None = None,
    series_game: int | None = None,
    score: int | None = None,
    stakes: float | None = None,
    excitement: float | None = None,
) -> dict[str, Any]:
    return {
        "game_key": game,
        "season": int(game[:4]),
        "game_date": date.fromisoformat(game[:10]),
        "series_league": league,
        "series_game": series_game,
        "home_score": score,
        "pregame_stakes": stakes,
        "wp_excitement": excitement,
    }


def _lineup(game: str) -> list[dict[str, Any]]:
    rows = []
    for side in ("away", "home"):
        for slot in range(10):
            rows.append(
                {
                    "game_key": game,
                    "side": side,
                    "slot": slot,
                    "player_id": f"{side[0]}{game[:4]}{slot}",
                    "name": f"Player {side} {slot}",
                    "position": 1 if slot == 0 else slot + 1 if slot < 9 else 10,
                    "starter_uncertain": side == "home" and slot == 9,
                }
            )
    return rows


def _booth(
    booth: str,
    pbp: str,
    analysts: list[str],
    label: str | None,
    games: int,
    *,
    ready: bool,
    relay: int = 0,
    low_n: bool = False,
) -> dict[str, Any]:
    return {
        "booth_key": booth,
        "pbp_person_id": pbp,
        "analyst_person_ids": analysts,
        "rank_label": label,
        "games": games,
        "crew_listed": games,
        "relay_crews": relay,
        "stakes_n": games if ready else 0,
        "stakes_raw": 0.4 if ready else None,
        "stakes_adj": 0.1 if ready else None,
        "stakes_adj_se": 0.05 if ready else None,
        "excitement_raw": 1.2 if ready else None,
        "excitement_adj": -0.2 if ready else None,
        "excitement_adj_se": 0.3 if ready else None,
        "strength_prior": 0.52,
        "low_n": low_n,
        "quality_status": "ready" if ready else "pending",
    }


def _cells() -> list[dict[str, Any]]:
    def booth(key_: str, pbp: str, analysts: list[str], games: int) -> dict[str, Any]:
        return {
            "booth_key": key_,
            "pbp_person_id": pbp,
            "analyst_person_ids": analysts,
            "games": games,
        }

    return [
        {
            "season": 2014,
            "round": "world_series",
            "league": None,
            "network_id": "fox_net",
            "booths": [],
            "games": 1,
            "crew_listed": 0,
            "coverage_num": 0,
            "coverage_den": 1,
            "mean_excitement": 2.4,
            "excitement_n": 1,
            "viewers_mean": None,
            "viewers_n": 0,
            "game_list": [S1],
        },
        {
            "season": 2019,
            "round": "division",
            "league": "AL",
            "network_id": "tbs",
            "booths": [],
            "games": 1,
            "crew_listed": 0,
            "coverage_num": 0,
            "coverage_den": 1,
            "mean_excitement": None,
            "excitement_n": 0,
            "viewers_mean": None,
            "viewers_n": 0,
            "game_list": [D1],
        },
        {
            "season": 2025,
            "round": "wild_card",
            "league": "NL",
            "network_id": "tbs",
            "booths": [
                booth("tbs|2025|p5", "p5", ["p6"], 1),
                booth("tbs|2025|p1", "p1", ["p2"], 1),
            ],
            "games": 2,
            "crew_listed": 1,
            "coverage_num": 2,
            "coverage_den": 2,
            "mean_excitement": 2.0,
            "excitement_n": 1,
            "viewers_mean": 5_000_000.0,
            "viewers_n": 1,
            "game_list": [W1, W2],
        },
    ]


def make_tables(paths: DataPaths, *, ready: bool = True) -> None:
    """Write a small invented set of the seven tables a build produces."""
    games = [
        _game(A1, score=4, stakes=0.4 if ready else None, excitement=1.2 if ready else None),
        _game(A2, score=2 if ready else None),
        _game(A3),
        _game(B1),
        _game(B2),
        _game(W1, league="NL", series_game=1, score=3, excitement=2.0),
        _game(W2, league="NL", series_game=2),
        _game(D1, league="AL", series_game=1),
        _game(S1, league="AL", series_game=1, excitement=2.4),
        _game(O1),
    ]
    relay = ("https://press.example/release", "Invented Press Room")
    telecasts = [
        _telecast(
            A1, "apple", pbp="p1", analysts=("p2",), source="506", url="https://s.example/506",
            booth="apple|2026|p1", viewers=3_500_000.0,
        ),
        _telecast(
            A2, "apple", pbp="p3", analysts=("p4",), source="relay", url="https://s.example/post",
            press=relay, booth="apple|2026|p3", cause="per_network",
        ),
        _telecast(A3, "apple"),
        _telecast(B1, "fox_net", pbp="p1", analysts=("p2",), source="506", url="https://s/x"),
        _telecast(B2, "apple", production="partner", pbp="p5", source="506", url="https://s/y"),
        _telecast(A1, "mlbn"),
        _telecast(
            W1, "tbs", rnd="wild_card", pbp="p5", analysts=("p6",), source="wikipedia",
            url="https://en.wikipedia.org/wiki/Invented", viewers=5_000_000.0,
            cause="window_level", series_game=1,
        ),
        _telecast(
            W2, "tbs", rnd="wild_card", pbp="p1", analysts=("p2",), source="506",
            url="https://s.example/506w", cause="conflict", series_game=2,
        ),
        _telecast(D1, "tbs", rnd="division", cause="ambiguous_doubleheader", series_game=1),
        _telecast(S1, "fox_net", rnd="world_series", series_game=1),
        _telecast(O1, "fox_net", rnd="world_series", series_game=1),
    ]  # fmt: skip
    lineups = [r for g in LINEUP_GAMES for r in _lineup(g)]
    booths = [
        _booth("apple|2026|p3", "p3", ["p4"], "#2", 1, ready=ready, relay=1, low_n=True),
        _booth("apple|2026|p1", "p1", ["p2"], "Lead", 1, ready=ready, low_n=True),
    ]
    summary = {
        "apple_games": 3,
        "rr_rated": 1,
        "lead_games": 1,
        "others_games": 1,
        "stakes_adj_diff": 0.3,
        "stakes_adj_diff_se": 0.1,
        "excitement_adj_diff": -0.4,
        "excitement_adj_diff_se": 0.2,
    }
    seasons = [
        {"season": s, "coverage_num": 0, "coverage_den": 1, "coverage_pct": 0.0, "below_bar": True}
        for s in (2014, 2019, 2025)
    ]
    tables = {
        "mlb_games": pl.DataFrame(games, schema=GAME_SCHEMA),
        "mlb_telecasts": pl.DataFrame(telecasts, schema=TELECAST_SCHEMA),
        "mlb_lineups": pl.DataFrame(lineups, schema=LINEUP_SCHEMA),
        "mlb_apple_booths": pl.DataFrame(booths, schema=BOOTH_SCHEMA),
        "mlb_apple_summary": pl.DataFrame([summary], schema=SUMMARY_SCHEMA),
        "mlb_postseason_booths": pl.DataFrame(_cells(), schema=POST_SCHEMA),
        "mlb_postseason_seasons": pl.DataFrame(seasons, schema=POST_SEASON_SCHEMA),
    }
    paths.processed.mkdir(parents=True, exist_ok=True)
    for name, frame in tables.items():
        frame.write_parquet(paths.processed / f"{name}.parquet")


def replace_table(
    paths: DataPaths, name: str, change: Callable[[pl.DataFrame], pl.DataFrame]
) -> None:
    path = paths.processed / f"{name}.parquet"
    change(pl.read_parquet(path)).write_parquet(path)


@pytest.fixture
def reference(tmp_path: Path) -> Path:
    ref = make_reference(tmp_path / "ref")
    (ref / "people.csv").write_text(PEOPLE_CSV, encoding="utf-8")
    return ref


@pytest.fixture
def tables(git_vault: DataPaths) -> DataPaths:
    make_tables(git_vault)
    return git_vault


def _site(paths: DataPaths, ref: Path) -> dict[str, Any]:
    site = build_mlb_site_data(load_mlb_site_inputs(paths, ref))
    return site.model_dump(mode="json")


def _games_by_key(paths: DataPaths, ref: Path) -> dict[str, dict[str, Any]]:
    data = _site(paths, ref)
    g = data["games"]
    clubs = data["lookups"]["clubs"]
    out = {}
    for i in range(len(g["season"])):
        row = {name: g[name][i] for name in g}
        k = key(row["date"], clubs[row["away"]]["id"], clubs[row["home"]]["id"], row["game_number"])
        out[k] = row
    return out


# -- Task 1: the payload ----------------------------------------------------------------


def test_payload_validates_and_bytes_are_deterministic(tables: DataPaths, reference: Path) -> None:
    first = build_mlb_site_data(load_mlb_site_inputs(tables, reference))
    second = build_mlb_site_data(load_mlb_site_inputs(tables, reference))

    body = mlb_site_payload_bytes(first)
    assert body == mlb_site_payload_bytes(second)
    assert not body.endswith(b"\n")
    assert b'": ' not in body and b'", ' not in body
    assert validate_mlb_site_data(json.loads(body)) == first
    assert json.dumps(json.loads(body), separators=(",", ":"), sort_keys=True).encode() == body


def test_only_view_feeding_games_ship(tables: DataPaths, reference: Path) -> None:
    shipped = _games_by_key(tables, reference)

    assert set(shipped) == {A1, A2, A3, W1, W2, D1, S1}
    assert B1 not in shipped and B2 not in shipped and O1 not in shipped
    assert [g["season"] for g in shipped.values()] == sorted(g["season"] for g in shipped.values())
    # Every postseason game since 2014 ships; regular-season games ship only for Apple.
    assert {g["round"] for g in shipped.values() if g["season"] == 2026} == {"regular"}


def test_no_analysis_only_field_ships(tables: DataPaths, reference: Path) -> None:
    data = _site(tables, reference)
    text = json.dumps(data)

    assert tuple(data["games"]) == MLB_GAME_FIELDS
    assert "is_exclusive" not in text and "crew_names" not in text and "production" not in text
    assert "mlbn" not in text and "partner" not in text
    # The scope value "window" appears only as a viewership scope, never as a key.
    assert "window" not in set(data["games"]) and "window" not in set(data)


def test_pending_comes_from_the_data_and_turns_ready_without_code(
    git_vault: DataPaths, reference: Path
) -> None:
    make_tables(git_vault, ready=False)
    pending = _site(git_vault, reference)

    assert pending["freshness"]["quality_pending"] is True
    assert set(pending["apple_booths"]["quality_status"]) == {"pending"}
    for column in ("raw_stakes", "adj_stakes", "raw_excitement", "adj_excitement"):
        assert pending["apple_booths"][column] == [None, None]
    # The table row holds differences; while pending they must not ship.
    assert pending["apple_summary"]["lead_minus_others_stakes"] is None
    assert pending["apple_summary"]["lead_minus_others_excitement_se"] is None

    make_tables(git_vault, ready=True)
    ready = _site(git_vault, reference)
    assert ready["freshness"]["quality_pending"] is False
    assert ready["freshness"]["retrosheet_through_season"] == 2026
    assert set(ready["apple_booths"]["quality_status"]) == {"ready"}
    assert ready["apple_summary"]["lead_minus_others_stakes"] == pytest.approx(0.3)
    assert ready["apple_summary"]["n_lead"] == 1 and ready["apple_summary"]["n_others"] == 1


def test_apple_booths_are_ranked_lead_first(tables: DataPaths, reference: Path) -> None:
    data = _site(tables, reference)
    people = [p["name"] for p in data["lookups"]["people"]]
    booths = data["apple_booths"]

    assert booths["rank_label"] == ["Lead", "#2"]
    assert [people[i] for i in booths["pbp"]] == ["Pia One", "Rex Three"]
    assert booths["relay_crews"] == [0, 1]
    shipped = _games_by_key(tables, reference)
    dates = [row["date"] for row in shipped.values()]
    assert [dates[i] for i in booths["game_list"][0]] == ["2026-04-03"]
    assert [dates[i] for i in booths["game_list"][1]] == ["2026-04-10"]


def test_credits_ship_with_crews_and_figures(tables: DataPaths, reference: Path) -> None:
    shipped = _games_by_key(tables, reference)

    relay = shipped[A2]
    assert relay["crew_source"] == "relay"
    assert relay["crew_source_url"] == "https://s.example/post"
    assert relay["press_url"] == "https://press.example/release"
    assert relay["press_name"] == "Invented Press Room"
    wiki = shipped[W1]
    assert wiki["crew_source"] == "wikipedia"
    assert wiki["crew_source_url"] == "https://en.wikipedia.org/wiki/Invented"
    assert wiki["press_url"] is None and wiki["press_name"] is None
    rated = shipped[A1]
    assert rated["viewers"] == 3_500_000
    assert rated["rr_url"].startswith(RR) and rated["source_url"].startswith(SRC)
    assert rated["cause"] is None and rated["scope"] == "game"
    assert rated["viewership_label"] == "per-game"
    assert rated["era"] == 0


def test_cause_values_map_from_the_match_causes(tables: DataPaths, reference: Path) -> None:
    shipped = _games_by_key(tables, reference)

    assert shipped[A2]["cause"] == "per_network"
    assert shipped[A3]["cause"] == "pending"  # a 2026 game with no figure yet
    assert shipped[W2]["cause"] == "conflict"
    assert shipped[D1]["cause"] == "ambiguous_doubleheader"
    assert shipped[S1]["cause"] == "none"  # an old game with no explanation
    # A window-level figure ships its viewers with a window scope and no cause.
    assert shipped[W1]["viewers"] == 5_000_000
    assert shipped[W1]["scope"] == "window" and shipped[W1]["cause"] is None


def test_series_fields_follow_the_round(tables: DataPaths, reference: Path) -> None:
    shipped = _games_by_key(tables, reference)

    assert shipped[A1]["series_game"] is None and shipped[A1]["series_league"] is None
    assert shipped[W1]["series_game"] == 1 and shipped[W1]["series_league"] == 1  # NL
    assert shipped[D1]["series_league"] == 0  # AL
    # The game table carries a league on the World Series game; the file drops it.
    assert shipped[S1]["round"] == "world_series" and shipped[S1]["series_league"] is None


def test_lineups_ship_only_for_present_games(tables: DataPaths, reference: Path) -> None:
    data = _site(tables, reference)
    shipped = _games_by_key(tables, reference)

    assert shipped[A1]["lineup_status"] == "present"
    assert shipped[W1]["lineup_status"] == "present"
    assert shipped[A2]["lineup_status"] == "pending"  # 2026, waiting for Retrosheet
    assert shipped[S1]["lineup_status"] == "missing"  # an older game Retrosheet has no lineup for
    assert shipped[A2]["lineup_start"] is None
    lineups = data["lineups"]
    assert len(lineups["game"]) == 40
    used = {lineups["player"][i] for i in range(len(lineups["player"]))}
    assert used == set(range(len(data["lookups"]["players"])))
    ids = {p["id"] for p in data["lookups"]["players"]}
    assert ids == {f"{s}{y}{n}" for s in "ah" for y in ("2026", "2025") for n in range(10)}
    for g in (shipped[A1], shipped[W1]):
        start, end = g["lineup_start"], g["lineup_end"]
        assert end - start == 19
    assert set(lineups["position"]) == {"P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"}


def test_postseason_cells_and_season_coverage(tables: DataPaths, reference: Path) -> None:
    data = _site(tables, reference)
    post, seasons = data["postseason"], data["postseason_seasons"]

    assert post["season"] == [2014, 2019, 2025]
    assert post["league"] == [None, 0, 1]
    assert [len(x) for x in post["game_list"]] == [1, 1, 2]
    assert len(post["booths"][2]) == 2 and post["booths"][0] == []
    assert seasons == {
        "season": [2014, 2019, 2025],
        "coverage_num": [0, 0, 2],
        "coverage_den": [1, 1, 2],
    }
    assert data["constants"]["coverage_bar"] == pytest.approx(0.95)
    assert data["constants"]["low_n_threshold"] == 10


def test_lookups_hold_only_what_ships(tables: DataPaths, reference: Path) -> None:
    data = _site(tables, reference)
    lookups = data["lookups"]

    assert {p["name"] for p in lookups["people"]} == {
        "Pia One",
        "Quin Two",
        "Rex Three",
        "Sol Four",
        "Tia Five",
        "Uri Six",
    }
    assert {n["id"] for n in lookups["networks"]} == {"apple", "tbs", "fox_net"}
    assert [n["name"] for n in lookups["networks"] if n["id"] == "apple"] == ["Apple TV+"]
    assert {e["id"] for e in lookups["eras"]} == {ERA}
    assert [r["id"] for r in lookups["leagues"]] == ["AL", "NL"]


def test_a_contract_violation_names_positions_only(tables: DataPaths, reference: Path) -> None:
    def break_relay(frame: pl.DataFrame) -> pl.DataFrame:
        return frame.with_columns(
            pl.when(pl.col("game_key") == A2)
            .then(None)
            .otherwise(pl.col("press_url"))
            .alias("press_url"),
            pl.when(pl.col("game_key") == A2)
            .then(pl.lit(CANARY))
            .otherwise(pl.col("press_name"))
            .alias("press_name"),
        )

    replace_table(tables, "mlb_telecasts", break_relay)

    with pytest.raises(SiteBuildError) as caught:
        build_mlb_site_data(load_mlb_site_inputs(tables, reference))
    message = str(caught.value)
    assert "games.press_url[" in message
    assert CANARY not in message and "Rex Three" not in message


def test_a_missing_table_and_a_missing_column_name_the_file(
    tables: DataPaths, reference: Path
) -> None:
    replace_table(tables, "mlb_games", lambda f: f.drop("wp_excitement"))
    with pytest.raises(SiteBuildError, match=r"mlb_games\.parquet: missing column"):
        load_mlb_site_inputs(tables, reference)

    (tables.processed / "mlb_lineups.parquet").unlink()
    replace_table(tables, "mlb_games", lambda f: f)  # leave the broken table alone
    (tables.processed / "mlb_games.parquet").unlink()
    with pytest.raises(SiteBuildError, match=r"mlb_games\.parquet not found"):
        load_mlb_site_inputs(tables, reference)


def test_unknown_person_is_a_position_only_error(tables: DataPaths, reference: Path) -> None:
    replace_table(
        tables,
        "mlb_telecasts",
        lambda f: f.with_columns(
            pl.when(pl.col("game_key") == A1)
            .then(pl.lit(CANARY))
            .otherwise(pl.col("pbp_person_id"))
            .alias("pbp_person_id")
        ),
    )

    with pytest.raises(SiteBuildError) as caught:
        build_mlb_site_data(load_mlb_site_inputs(tables, reference))
    assert CANARY not in str(caught.value)
    assert "games.crew[" in str(caught.value)


def test_written_file_matches_the_payload_bytes(tables: DataPaths, reference: Path) -> None:
    site = build_mlb_site_data(load_mlb_site_inputs(tables, reference))

    rel = write_mlb_site_data(tables, site)

    assert rel == MLB_SITE_DATA_PATH == "processed/mlb-data.json"
    assert (tables.vault / rel).read_bytes() == mlb_site_payload_bytes(site)


# -- Task 2: commands and the build hook ------------------------------------------------


def _subject(vault: DataPaths, n: int = 1) -> str:
    return subprocess.run(
        ["git", "-C", str(vault.vault), "log", f"-{n}", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _last_commit_files(vault: DataPaths) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(vault.vault), "show", "--name-only", "--format=", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(line for line in out.splitlines() if line)


@pytest.fixture
def cli(tables: DataPaths, reference: Path, monkeypatch: pytest.MonkeyPatch) -> DataPaths:
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(reference))
    return tables


def test_site_data_command_writes_and_commits_only_that_path(
    cli: DataPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["mlb", "site-data"]) == 0

    out = capsys.readouterr().out
    assert "mlb site data: 7 games, 2 lineups" in out
    assert (cli.vault / "processed/mlb-data.json").is_file()
    assert _subject(cli) == "build: mlb_site 2026 (games 7, lineups 2)"
    assert _last_commit_files(cli) == ["processed/mlb-data.json"]
    for private in ("Pia", "Rex", "alpha", "tbs"):
        assert private not in out


def test_site_data_command_no_commit(cli: DataPaths) -> None:
    before = _subject(cli)

    assert main(["mlb", "site-data", "--no-commit"]) == 0

    assert (cli.vault / "processed/mlb-data.json").is_file()
    assert _subject(cli) == before


def test_site_data_command_is_listed_and_fails_cleanly_without_tables(
    git_vault: DataPaths,
    reference: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(reference))
    with pytest.raises(SystemExit):
        main(["mlb", "--help"])
    assert "site-data" in capsys.readouterr().out

    assert main(["mlb", "site-data"]) != 0
    assert "mlb_games.parquet not found" in capsys.readouterr().err


@pytest.fixture
def built(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[DataPaths, Path]:
    make_vault(git_vault, with_2026=True, with_rr=False)
    ref = make_reference(tmp_path / "ref")
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(ref))
    monkeypatch.setattr(
        mlb_commands, "run_mlb_build", functools.partial(run_mlb_build, we_min_train_games=TRAIN)
    )
    return git_vault, ref


def test_build_site_data_flag_writes_in_the_same_commit(
    built: tuple[DataPaths, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    paths, _ref = built

    assert main(["mlb", "build", "--site-data"]) == 0

    assert (paths.vault / "processed/mlb-data.json").is_file()
    assert "processed/mlb-data.json" in _last_commit_files(paths)
    assert "processed/mlb_games.parquet" in _last_commit_files(paths)
    assert _subject(paths).startswith("build: mlb 2014-2026")
    assert "failed" not in capsys.readouterr().out
    validate_mlb_site_data(json.loads((paths.vault / "processed/mlb-data.json").read_bytes()))


def test_build_without_the_flag_writes_no_site_file(built: tuple[DataPaths, Path]) -> None:
    paths, _ref = built

    assert main(["mlb", "build"]) == 0

    assert not (paths.vault / "processed/mlb-data.json").exists()


def test_env_switch_turns_site_data_on_only_when_exactly_true(
    built: tuple[DataPaths, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, _ref = built
    monkeypatch.setenv("MLB_SITE_ENABLED", "True")
    assert main(["mlb", "build", "--no-commit"]) == 0
    assert not (paths.vault / "processed/mlb-data.json").exists()

    monkeypatch.setenv("MLB_SITE_ENABLED", "true")
    assert main(["mlb", "build", "--no-commit"]) == 0
    assert (paths.vault / "processed/mlb-data.json").is_file()


def test_a_builder_failure_never_blocks_the_table_commit(
    built: tuple[DataPaths, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths, _ref = built

    def boom(_paths: DataPaths, _reference: Path) -> str:
        raise SiteBuildError(CANARY)

    monkeypatch.setattr(pipeline, "SITE_DATA_BUILDER", boom)

    assert main(["mlb", "build", "--site-data"]) == 0

    captured = capsys.readouterr()
    assert "mlb site data: failed (tables committed)" in captured.out
    assert CANARY not in captured.out + captured.err
    assert _subject(paths).startswith("build: mlb 2014-2026")
    assert "processed/mlb_games.parquet" in _last_commit_files(paths)
    assert not (paths.vault / "processed/mlb-data.json").exists()


def test_site_data_still_stops_early_when_no_builder_is_available(
    built: tuple[DataPaths, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, ref = built
    monkeypatch.setattr(pipeline, "SITE_DATA_BUILDER", None)

    with pytest.raises(Exception, match="site data builder not available"):
        run_mlb_build(paths, ref, [2025, 2026], commit=False, site_data=True)

    assert not list(paths.processed.glob("mlb_*"))


def test_pending_to_ready_on_a_real_build_needs_no_code_change(
    git_vault: DataPaths, tmp_path: Path
) -> None:
    ref = make_reference(tmp_path / "ref")
    make_vault(git_vault, with_2026=False, with_rr=False)
    run_mlb_build(git_vault, ref, [2025, 2026], commit=False, we_min_train_games=TRAIN)
    before = _site(git_vault, ref)

    make_vault(git_vault, with_2026=True, with_rr=False)
    run_mlb_build(git_vault, ref, [2025, 2026], commit=False, we_min_train_games=TRAIN)
    after = _site(git_vault, ref)

    assert before["freshness"]["quality_pending"] is True
    assert before["freshness"]["retrosheet_through_season"] == 2025
    assert set(before["apple_booths"]["quality_status"]) == {"pending"}
    assert after["freshness"]["quality_pending"] is False
    assert after["freshness"]["retrosheet_through_season"] == 2026
    assert set(after["apple_booths"]["quality_status"]) == {"ready"}


def test_two_real_builds_give_identical_site_bytes(git_vault: DataPaths, tmp_path: Path) -> None:
    ref = make_reference(tmp_path / "ref")
    make_vault(git_vault, with_2026=True)
    run_mlb_build(git_vault, ref, [2025, 2026], commit=False, we_min_train_games=TRAIN)
    first = mlb_site_payload_bytes(build_mlb_site_data(load_mlb_site_inputs(git_vault, ref)))
    run_mlb_build(git_vault, ref, [2025, 2026], commit=False, we_min_train_games=TRAIN)
    second = mlb_site_payload_bytes(build_mlb_site_data(load_mlb_site_inputs(git_vault, ref)))

    assert first == second


# -- the written file feeds `site --mlb` --------------------------------------------------


def test_assembly_consumes_the_written_file(
    cli: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert main(["mlb", "site-data", "--no-commit"]) == 0
    src = tmp_path / "_src"
    shutil.copytree(REPO_ROOT / "site", src, ignore=shutil.ignore_patterns("node_modules"))
    (src / "sports" / "mlb").mkdir(exist_ok=True)
    (src / "sports" / "mlb" / "index.js").write_text("// synthetic placeholder\n", "utf-8")
    docs = tmp_path / "_docs"
    shutil.copytree(REPO_ROOT / "docs", docs)
    with (docs / "methodology.md").open("a", encoding="utf-8") as fh:
        fh.write("\n<!-- mlb:start -->\n\n## MLB: Synthetic section\n\n<!-- mlb:end -->\n")
    monkeypatch.delenv("CFBD_API_KEY", raising=False)
    written = cli.vault / "processed/mlb-data.json"
    out = tmp_path / "out"

    result = assemble_site(
        source=CFB_FIXTURE,
        out_dir=out,
        site_src=src,
        docs=docs,
        mlb=True,
        mlb_payload=load_mlb_site_payload(written),
    )

    assert result.mlb_games == 7
    assert (out / "mlb-data.json").read_bytes() == written.read_bytes()
    assert sa.MLB_DATA_FILE == "mlb-data.json"


def test_inputs_type_is_exported() -> None:
    assert MlbSiteInputs.__name__ == "MlbSiteInputs"
