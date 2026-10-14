"""Tests for the MLB site-data contract (phase 09 plan 10): validation, broken
variants, banned analysis-only names, schema drift, credit rules and the committed
synthetic fixture.

Everything here is synthetic: invented clubs and people, example.org URLs.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from booth_review.contract.mlb_models import (
    MLB_CAUSES,
    MLB_CREW_SOURCES,
    MLB_GAME_FIELDS,
    MLB_ROUNDS,
    MLB_SCHEMA_VERSION,
    MlbSiteData,
    validate_mlb_site_data,
)
from booth_review.contract.mlb_schema import SCHEMA_PATH, render_schema

Payload = dict[str, Any]
Mutator = Callable[[Payload], None]

REPO = Path(__file__).resolve().parent.parent
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "contract" / "mlb-data.fixture.json"

INVENTED_STRINGS = ("Northfield Lanterns", "Harbor City", "Ada Quill", "example.org")


def _fixture() -> Payload:
    data: Payload = json.loads(FIXTURE_PATH.read_text())
    return data


def _minimal_payload() -> Payload:
    """A tiny valid payload: one relay-crew game and one game with no crew."""
    return {
        "schema_version": "1.0.0",
        "freshness": {
            "season": 2026,
            "in_progress": True,
            "retrosheet_through_season": None,
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
                {"id": "c1", "name": "Northfield Lanterns", "league": "AL", "division": None},
                {"id": "c2", "name": "Harbor City Gulls", "league": None, "division": None},
            ],
            "team_names": [],
            "networks": [{"id": "apple", "name": "Apple TV", "family": "apple"}],
            "people": [{"id": "p1", "name": "Ada Quill"}, {"id": "p2", "name": "Cy Fable"}],
            "players": [],
            "rounds": list(MLB_ROUNDS),
            "leagues": [
                {"id": "AL", "name": "American League"},
                {"id": "NL", "name": "National League"},
            ],
            "eras": [],
        },
        "games": {
            "season": [2026, 2026],
            "date": ["2026-04-03", "2026-04-04"],
            "game_number": [0, 0],
            "away": [0, 1],
            "home": [1, 0],
            "round": ["regular", "regular"],
            "series_league": [None, None],
            "series_game": [None, None],
            "network": [0, 0],
            "crew": [[{"person": 0, "role": "pbp"}, {"person": 1, "role": "analyst"}], []],
            "crew_source": ["relay", None],
            "crew_source_url": ["https://example.org/relay/1", None],
            "press_url": ["https://example.org/press/1", None],
            "press_name": ["Invented Press Room", None],
            "wp_excitement": [None, None],
            "stakes": [None, None],
            "viewers": [None, None],
            "viewership_label": [None, None],
            "scope": [None, None],
            "era": [None, None],
            "rr_url": [None, None],
            "source_url": [None, None],
            "cause": ["pending", "pending"],
            "lineup_status": ["pending", "pending"],
            "lineup_start": [None, None],
            "lineup_end": [None, None],
        },
        "lineups": {
            "game": [],
            "side": [],
            "slot": [],
            "player": [],
            "position": [],
            "starter_uncertain": [],
        },
        "apple_booths": {
            "rank_label": ["Lead booth"],
            "pbp": [0],
            "analyst": [1],
            "games": [1],
            "crew_listed": [1],
            "relay_crews": [1],
            "raw_stakes": [None],
            "raw_stakes_n": [0],
            "adj_stakes": [None],
            "adj_stakes_se": [None],
            "raw_excitement": [None],
            "adj_excitement": [None],
            "adj_excitement_se": [None],
            "strength_prior": [None],
            "low_n": [True],
            "quality_status": ["pending"],
            "game_list": [[0]],
        },
        "apple_summary": {
            "lead_minus_others_stakes": None,
            "lead_minus_others_stakes_se": None,
            "lead_minus_others_excitement": None,
            "lead_minus_others_excitement_se": None,
            "n_lead": 1,
            "n_others": 0,
            "rr_rated": 0,
            "apple_games": 2,
        },
        "postseason": {
            "season": [],
            "round": [],
            "league": [],
            "network": [],
            "booths": [],
            "games": [],
            "crew_listed": [],
            "coverage_num": [],
            "coverage_den": [],
            "mean_excitement": [],
            "excitement_n": [],
            "viewers_mean": [],
            "viewers_n": [],
            "game_list": [],
        },
        "postseason_seasons": {"season": [], "coverage_num": [], "coverage_den": []},
    }


def test_minimal_payload_validates() -> None:
    data = validate_mlb_site_data(copy.deepcopy(_minimal_payload()))
    n = len(data.games.season)
    for name in type(data.games).model_fields:
        assert len(getattr(data.games, name)) == n, name


def _set(block: str, column: str, i: int, value: object) -> Mutator:
    def mutate(d: Payload) -> None:
        d[block][column][i] = value

    return mutate


def _games_extra(name: str) -> Mutator:
    def mutate(d: Payload) -> None:
        d["games"][name] = [None] * len(d["games"]["season"])

    return mutate


def _unreferenced_person(d: Payload) -> None:
    d["lookups"]["people"].append({"id": "px", "name": "Cy Fable"})


def _unreferenced_player(d: Payload) -> None:
    d["lookups"]["players"].append({"id": "px", "name": "Extra Player"})


def _unreferenced_network(d: Payload) -> None:
    d["lookups"]["networks"].append({"id": "nbc", "name": "NBC", "family": "nbc"})


def _duplicate_cell(d: Payload) -> None:
    p = d["postseason"]
    for name, col in list(p.items()):
        p[name] = [*col, copy.deepcopy(col[0])]


def _booth_shape(d: Payload) -> None:
    d["postseason"]["booths"][1] = [[6]]


def _season_sum(d: Payload) -> None:
    d["postseason_seasons"]["coverage_den"][0] += 1


def _summary_nan(d: Payload) -> None:
    d["apple_summary"]["lead_minus_others_stakes"] = float("nan")


def _season_missing(d: Payload) -> None:
    for col in d["postseason_seasons"].values():
        col.pop(0)


def _lineup_wrong_game(d: Payload) -> None:
    d["lineups"]["game"][3] = 0


def _rounds_reordered(d: Payload) -> None:
    d["lookups"]["rounds"].reverse()


def _leagues_reordered(d: Payload) -> None:
    d["lookups"]["leagues"].reverse()


def _quality_flag(d: Payload) -> None:
    d["freshness"]["quality_pending"] = False


def _summary_not_null(d: Payload) -> None:
    d["apple_summary"]["lead_minus_others_stakes"] = 0.1


def _regular_with_series(d: Payload) -> None:
    d["games"]["series_game"][0] = 1


def _ws_with_league(d: Payload) -> None:
    d["games"]["series_league"][7] = 0


def _postseason_regular_round(d: Payload) -> None:
    d["postseason"]["round"][0] = "regular"


MUTATORS: list[tuple[str, Mutator]] = [
    ("top_extra", lambda d: d.update(window=[])),
    ("games_is_exclusive", _games_extra("is_exclusive")),
    ("games_production", _games_extra("production")),
    ("games_raw_crew", _games_extra("raw_crew")),
    ("misaligned", lambda d: d["games"].update(date=["2026-04-03"])),
    ("bad_version", lambda d: d.update(schema_version="2.0.0")),
    ("away_idx", _set("games", "away", 0, 99)),
    ("home_idx", _set("games", "home", 0, -1)),
    ("network_idx", _set("games", "network", 0, 9)),
    ("era_idx", _set("games", "era", 0, 4)),
    ("series_league_idx", _set("games", "series_league", 6, 5)),
    ("crew_person_idx", _set("games", "crew", 0, [{"person": 99, "role": "pbp"}])),
    ("bad_crew_role", _set("games", "crew", 0, [{"person": 0, "role": "color"}])),
    ("booth_pbp_idx", _set("apple_booths", "pbp", 0, 99)),
    ("booth_analyst_idx", _set("apple_booths", "analyst", 0, 99)),
    ("booth_game_list", _set("apple_booths", "game_list", 0, [99])),
    ("booth_game_list_short", _set("apple_booths", "game_list", 0, [0])),
    ("post_league_idx", _set("postseason", "league", 0, 5)),
    ("post_network_idx", _set("postseason", "network", 0, 9)),
    ("post_game_list", _set("postseason", "game_list", 0, [99])),
    ("post_game_list_short", _set("postseason", "game_list", 0, [6, 7])),
    ("lineup_game_idx", _set("lineups", "game", 0, 99)),
    ("lineup_player_idx", _set("lineups", "player", 0, 99)),
    ("lineup_slot", _set("lineups", "slot", 0, 10)),
    ("lineup_wrong_game", _lineup_wrong_game),
    ("team_name_club_idx", lambda d: d["lookups"]["team_names"][0].update(club=99)),
    ("bad_round", _set("games", "round", 0, "semifinal")),
    ("bad_cause", _set("games", "cause", 0, "guess")),
    ("bad_crew_source", _set("games", "crew_source", 0, "guess")),
    ("rounds_reordered", _rounds_reordered),
    ("leagues_reordered", _leagues_reordered),
    ("relay_without_url", _set("games", "crew_source_url", 0, None)),
    ("relay_without_press_url", _set("games", "press_url", 0, None)),
    ("relay_without_press_name", _set("games", "press_name", 0, None)),
    ("relay_press_http", _set("games", "press_url", 0, "http://example.org/press/1")),
    ("press_on_506", _set("games", "press_url", 1, "https://example.org/press/9")),
    ("wikipedia_without_url", _set("games", "crew_source_url", 7, None)),
    ("crew_url_http", _set("games", "crew_source_url", 7, "http://example.org/wiki/x")),
    ("source_none_with_crew", _set("games", "crew_source", 0, None)),
    ("source_without_crew", _set("games", "crew_source", 5, "506")),
    ("viewers_zero", _set("games", "viewers", 1, 0)),
    ("viewers_without_rr_url", _set("games", "rr_url", 1, None)),
    ("viewers_without_source_url", _set("games", "source_url", 1, None)),
    ("viewers_rr_http", _set("games", "rr_url", 1, "http://example.org/rr")),
    ("viewers_with_cause", _set("games", "cause", 1, "none")),
    ("unrated_without_cause", _set("games", "cause", 0, None)),
    ("scope_on_unrated", _set("games", "scope", 0, "game")),
    ("era_on_unrated", _set("games", "era", 0, 0)),
    ("label_on_unrated", _set("games", "viewership_label", 0, "Viewers")),
    ("regular_with_series", _regular_with_series),
    ("ws_with_league", _ws_with_league),
    ("series_game_zero", _set("games", "series_game", 6, 0)),
    ("lineup_present_without_range", _set("games", "lineup_start", 6, None)),
    ("lineup_end_past_block", _set("games", "lineup_end", 6, 99)),
    ("lineup_range_on_pending", _set("games", "lineup_start", 0, 0)),
    ("pending_raw_stakes", _set("apple_booths", "raw_stakes", 0, 1.0)),
    ("pending_adj_excitement", _set("apple_booths", "adj_excitement", 1, 1.0)),
    ("pending_summary", _summary_not_null),
    ("quality_flag", _quality_flag),
    ("crew_listed_over_games", _set("apple_booths", "crew_listed", 0, 3)),
    ("relay_over_listed", _set("apple_booths", "relay_crews", 2, 2)),
    ("bad_quality_status", _set("apple_booths", "quality_status", 0, "ok")),
    ("post_regular_round", _postseason_regular_round),
    ("duplicate_cell", _duplicate_cell),
    ("booth_shape", _booth_shape),
    ("coverage_over_den", _set("postseason", "coverage_num", 0, 5)),
    ("crew_listed_over_games_post", _set("postseason", "crew_listed", 0, 5)),
    ("excitement_n_over_games", _set("postseason", "excitement_n", 0, 5)),
    ("season_sum", _season_sum),
    ("season_missing", _season_missing),
    ("wp_nan", _set("games", "wp_excitement", 0, float("nan"))),
    ("stakes_inf", _set("games", "stakes", 0, float("inf"))),
    ("summary_nan", _summary_nan),
    ("coverage_bar_nan", lambda d: d["constants"].update(coverage_bar=float("nan"))),
    ("unreferenced_person", _unreferenced_person),
    ("unreferenced_player", _unreferenced_player),
    ("unreferenced_network", _unreferenced_network),
]


def _load() -> Payload:
    return _fixture()


@pytest.mark.parametrize("mutate", [m for _, m in MUTATORS], ids=[n for n, _ in MUTATORS])
def test_broken_variant_raises(mutate: Mutator) -> None:
    data = _load()
    mutate(data)
    with pytest.raises(ValidationError):
        validate_mlb_site_data(data)


@pytest.mark.parametrize("mutate", [m for _, m in MUTATORS], ids=[n for n, _ in MUTATORS])
def test_errors_never_echo_values(mutate: Mutator) -> None:
    data = _load()
    mutate(data)
    with pytest.raises(ValidationError) as exc:
        validate_mlb_site_data(data)
    text = str(exc.value)
    for needle in INVENTED_STRINGS:
        assert needle not in text


def test_unchanged_fixture_is_valid_control() -> None:
    validate_mlb_site_data(_load())


def _all_models(root: type[BaseModel]) -> set[type[BaseModel]]:
    """Every pydantic model reachable from `root` through its field annotations."""
    seen: set[type[BaseModel]] = set()
    stack: list[type[BaseModel]] = [root]
    while stack:
        model = stack.pop()
        if model in seen:
            continue
        seen.add(model)
        for field in model.model_fields.values():
            stack.extend(_models_in(field.annotation))
    return seen


def _models_in(annotation: object) -> list[type[BaseModel]]:
    found: list[type[BaseModel]] = []
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        found.append(annotation)
    for arg in getattr(annotation, "__args__", ()):
        found.extend(_models_in(arg))
    return found


BANNED_NAMES = {
    "is_exclusive",
    "production",
    "is_alt",
    "excitementIndex",
    "excitement_index",
    "raw_crew",
    "raw_crews",
    "crew_names",
    "plays",
    "we_table",
    "wp_series",
    "window",
    "generated_at",
    "payload",
}


def test_no_banned_field_names() -> None:
    models = _all_models(MlbSiteData)
    assert len(models) > 10
    names = {name for model in models for name in model.model_fields}
    assert not names & BANNED_NAMES
    assert not [n for n in names if n.startswith("cfbd")]


def test_every_model_forbids_extras_strictly() -> None:
    for model in _all_models(MlbSiteData):
        cfg = model.model_config
        assert cfg.get("extra") == "forbid", model.__name__
        assert cfg.get("strict") is True, model.__name__
        assert cfg.get("frozen") is True, model.__name__


def test_vocabularies_are_pinned() -> None:
    assert MLB_ROUNDS == ("regular", "wild_card", "division", "lcs", "world_series", "tiebreak")
    assert MLB_CAUSES == (
        "pending",
        "none",
        "regional",
        "per_network",
        "ambiguous_doubleheader",
        "conflict",
        "window_level",
    )
    assert MLB_CREW_SOURCES == ("override", "506", "relay", "wikipedia")
    assert "round" in MLB_GAME_FIELDS and "lineup_status" in MLB_GAME_FIELDS


def test_schema_file_matches_models() -> None:
    committed = json.loads((REPO / SCHEMA_PATH).read_text())
    assert committed == render_schema(), (
        "docs/mlb-data.schema.json is out of date -- run "
        "`uv run python -m booth_review.contract.mlb_schema` and commit the result"
    )


def test_schema_version_pinned() -> None:
    assert MLB_SCHEMA_VERSION == "1.0.0"
    assert render_schema()["$id"] == "booth-review/mlb-data/1.0.0"


def test_docs_carry_the_retrosheet_notice() -> None:
    text = (REPO / "docs" / "mlb-data.md").read_text()
    assert "obtained free of charge from and is copyrighted by Retrosheet" in text
    assert "www.retrosheet.org" in text


# --- the committed synthetic fixture -----------------------------------------


def test_fixture_validates() -> None:
    data = validate_mlb_site_data(_fixture())
    n = len(data.games.season)
    assert n >= 15
    for name in type(data.games).model_fields:
        assert len(getattr(data.games, name)) == n, name


def test_fixture_is_current() -> None:
    from mlb_site_fixture import build_fixture, render

    assert FIXTURE_PATH.read_text() == render(build_fixture()), (
        "tests/fixtures/contract/mlb-data.fixture.json is out of date -- run "
        "`uv run python tests/mlb_site_fixture.py` and commit the result"
    )


def test_fixture_uses_only_example_hosts() -> None:
    hosts = set(re.findall(r"https?://([^/\"]+)", FIXTURE_PATH.read_text()))
    assert hosts == {"example.org"}


def test_fixture_covers_every_view_case() -> None:
    d = _fixture()
    g, b, p, ln = d["games"], d["apple_booths"], d["postseason"], d["lineups"]
    assert set(b["quality_status"]) == {"pending"}
    assert d["freshness"]["quality_pending"] is True
    assert any(b["low_n"])
    assert {"relay", "506", "wikipedia"} <= set(g["crew_source"])
    assert any(c == [] for c in g["crew"])
    assert {"per_network", "ambiguous_doubleheader", "pending"} <= set(g["cause"])
    assert any(v is not None for v in g["viewers"]) and any(v is None for v in g["viewers"])
    assert {"present", "pending", "missing"} == set(g["lineup_status"])
    assert {"wild_card", "division", "lcs", "world_series"} <= set(p["round"])
    assert {2014, 2019, 2025, 2026} <= set(p["season"])
    bar = d["constants"]["coverage_bar"]
    assert any(n / m < bar for n, m in zip(p["coverage_num"], p["coverage_den"], strict=True))
    assert any(u for u in ln["starter_uncertain"])
    present = [i for i, s in enumerate(g["lineup_status"]) if s == "present"]
    assert present
    start, end = g["lineup_start"][present[0]], g["lineup_end"][present[0]]
    rows = range(start, end + 1)
    for side in ("away", "home"):
        slots = sorted(ln["slot"][k] for k in rows if ln["side"][k] == side)
        assert slots == list(range(10))
    pending_2026 = [
        i
        for i, (s, y) in enumerate(zip(g["lineup_status"], g["season"], strict=True))
        if s == "pending" and y == 2026
    ]
    assert pending_2026


def test_fixture_errors_never_echo_names_or_urls() -> None:
    d = _fixture()
    d["games"]["home"][0] = 99
    d["games"]["viewers"][1] = 0
    with pytest.raises(ValidationError) as exc:
        validate_mlb_site_data(d)
    text = str(exc.value)
    names = [c["name"] for c in d["lookups"]["clubs"]] + [p["name"] for p in d["lookups"]["people"]]
    for needle in [*names, "example.org"]:
        assert needle not in text


def test_serializer_settings_reject_non_finite() -> None:
    site = validate_mlb_site_data(_fixture())
    body = json.dumps(
        site.model_dump(mode="json"), separators=(",", ":"), sort_keys=True, allow_nan=False
    )
    assert "NaN" not in body and "Infinity" not in body
    assert body == FIXTURE_PATH.read_text()
