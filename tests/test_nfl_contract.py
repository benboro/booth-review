"""Tests for the NFL site-data contract (999.5 D-07): validation, broken
variants, banned analysis-only names, schema drift, and the CFB pin.

Everything here is synthetic: invented franchises and people, example.com URLs.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from booth_review.contract import models as cfb_models
from booth_review.contract import nfl_models
from booth_review.contract.nfl_models import (
    NFL_GAME_FIELDS,
    NFL_SCHEMA_VERSION,
    NFL_SLOTS,
    NFL_VIEW_CATEGORIES,
    NflSiteData,
    validate_nfl_site_data,
)
from booth_review.contract.nfl_schema import SCHEMA_PATH, render_schema

Payload = dict[str, Any]
Mutator = Callable[[Payload], None]

REPO = Path(__file__).resolve().parent.parent

# sha256 of docs/site-data.schema.json recorded at the start of phase 999.5 plan 02.
# Re-pinned at 04.19 Plan 08: contract 2.4.0 adds telecasts.figure_source.
# Re-pinned at 04.19 Plan 41: contract 2.5.0 adds coverage matched_crew_backup.
# Re-pinned at Phase 10 Plan 03: contract 2.6.0 adds lookups.booths and the booth column.
# Re-pinned at Phase 18 Plan 01: CFB contract 2.7.0 adds telecasts_scheduled, lookups.weeks,
# freshness.weekend.
# Re-pinned at Phase 18 Plan 13 (F1): the three CFB blocks gain the week label column.
# Re-pinned at Phase 18 Plan 13 (F7): telecasts_scheduled gains the ESPN Press Room crew columns.
CFB_SCHEMA_SHA256 = "3e3b4d0720f20bf3a98cfcd95e684a3ff6e3ca2c14c11828f931d30481e8009f"

INVENTED_STRINGS = ("Northfield Lanterns", "Harbor City", "Ada Quill", "example.com")


def _minimal_payload() -> Payload:
    """A tiny valid payload: two games (one rated, one unrated), one row per block."""
    return {
        "schema_version": "2.2.0",
        "freshness": {
            "season": 2026,
            "in_progress": True,
            "through_week": 3,
            "viewership_through_week": 2,
            "crews_default_season": 2025,
        },
        "constants": {
            "viewership_scope": "window",
            "coverage_normalized": False,
            "excitement_method": "GEI-style",
            "low_n_threshold": 8,
        },
        "lookups": {
            "franchises": [
                {"id": "f1", "name": "Northfield Lanterns"},
                {"id": "f2", "name": "Harbor City Gulls"},
            ],
            "team_names": [
                {"name": "Northfield Lanterns", "short": "NFL"},
                {"name": "Harbor City Gulls", "short": "HCG"},
            ],
            "networks": [
                {"id": "fox", "name": "Fox", "family": "fox"},
                {"id": "cbs", "name": "CBS", "family": "cbs"},
            ],
            "network_groups": [
                {"id": "fox", "name": "Fox", "flagship": "AGOTW", "members": [0, 1]},
            ],
            "view_categories": [
                {"id": i, "label": label, "window_level": w} for i, label, w in NFL_VIEW_CATEGORIES
            ],
            "people": [{"id": "p1", "name": "Ada Quill"}],
            "venues": [],
            "eras": [
                {
                    "id": "e1",
                    "label": "Invented era",
                    "start": None,
                    "end": None,
                    "source_url": "https://example.com/era",
                }
            ],
            "slots": list(NFL_SLOTS),
        },
        "games": {
            "season": [2025, 2026],
            "week": [1, 2],
            "date": ["2025-09-07", "2026-09-13"],
            "kickoff": ["2025-09-07T13:00:00-04:00", None],
            "home": [0, 1],
            "away": [1, 0],
            "home_name": [0, 1],
            "away_name": [1, 0],
            "home_points": [27, None],
            "away_points": [24, None],
            "final_margin": [3, None],
            "slot": [10, 11],
            "standalone": [False, False],
            "agotw": [True, False],
            "cbs_national": [False, False],
            "international": [False, False],
            "flexed": [True, False],
            "original_slot": [11, None],
            "original_network": [1, None],
            "change_url": ["https://example.com/wiki/change", None],
            "network": [0, None],
            "crew": [[{"person": 0, "role": "pbp"}], []],
            "crew_source": ["506", None],
            "crew_source_url": [None, None],
            "excitement": [1.5, None],
            "viewers": [9000000, None],
            "scope": ["window", None],
            "era": [0, None],
            "rr_url": ["https://example.com/rr/1", None],
            "source_url": ["https://example.com/src/1", None],
            "cause": [None, "pending"],
            "place": [None, None],
        },
        "upcoming": {name: [] for name in nfl_models.NflUpcomingColumns.model_fields},
        "special": {
            "franchise": [0],
            "season": [2025],
            "games": [17],
            "standalone_total": [1],
            "standalone_christmas": [0],
            "standalone_thanksgiving": [0],
            "standalone_black_friday": [0],
            "standalone_international": [0],
            "standalone_tnf": [1],
            "standalone_snf": [0],
            "standalone_mnf": [0],
            "standalone_saturday": [0],
            "standalone_friday": [0],
            "standalone_sunday_early": [0],
            "standalone_sunday_late": [0],
            "standalone_other": [0],
            "solo_thursday": [1],
            "solo_sunday": [0],
            "solo_monday": [0],
            "solo_holiday": [0],
            "solo_other": [0],
            "agotw": [1],
            "cbs_national": [0],
            "international": [2],
            "international_other": [1],
            "flexed": [1],
            "special": [2],
            "agotw_rate": [0.5],
            "cbs_national_rate": [None],
        },
        "season_weeks": {
            "season": [2025],
            "fox_doubleheader_weeks": [2],
            "fox_ambiguous_weeks": [0],
            "cbs_doubleheader_weeks": [0],
            "cbs_ambiguous_weeks": [0],
        },
        "booths": {
            "season": [2025],
            "network_group": [0],
            "rank": [1],
            "rank_source": ["published"],
            "is_lead": [True],
            "pbp_person": [0],
            "analyst_person": [None],
            "games": [1],
            "flagship_games": [1],
            "fill_in_games": [0],
            "lineup_games": [0],
            "raw_n_margin": [1],
            "raw_n_excitement": [1],
            "raw_n_viewers": [1],
            "raw_mean_abs_margin": [3.0],
            "raw_mean_excitement": [1.5],
            "raw_mean_viewers": [9000000.0],
            "adj_n_margin": [1],
            "adj_n_excitement": [1],
            "adj_margin_resid": [0.1],
            "adj_margin_se": [1.0],
            "adj_excitement_resid": [0.2],
            "adj_excitement_se": [1.0],
            "low_n": [True],
            "game_list": [[0]],
        },
        "viewership": {
            "category": [0],
            "season": [2025],
            "era": [0],
            "games": [1],
            "mean_viewers": [9000000.0],
            "viewership_resid": [None],
            "viewership_se": [None],
            "low_n": [True],
            "game_list": [[0]],
        },
    }


def _load() -> Payload:
    return copy.deepcopy(_minimal_payload())


def test_minimal_payload_validates() -> None:
    data = validate_nfl_site_data(_load())
    n = len(data.games.season)
    for name in type(data.games).model_fields:
        assert len(getattr(data.games, name)) == n, name


def _set(block: str, column: str, i: int, value: object) -> Mutator:
    def mutate(d: Payload) -> None:
        d[block][column][i] = value

    return mutate


def _top_extra(d: Payload) -> None:
    d["pregame_spread"] = []


def _block_extra(d: Payload) -> None:
    d["games"]["pregame_spread"] = [1.0, 2.0]


def _misaligned(d: Payload) -> None:
    d["games"]["week"] = [1]


def _add_booth_row(d: Payload, **changes: object) -> None:
    b = d["booths"]
    for name, col in list(b.items()):
        b[name] = [*col, copy.deepcopy(col[0])]
    for name, value in changes.items():
        b[name][1] = value


def _two_leads(d: Payload) -> None:
    _add_booth_row(d, rank=2)


def _rank_gap(d: Payload) -> None:
    _add_booth_row(d, rank=3, is_lead=False)


def _lead_not_rank_one(d: Payload) -> None:
    d["booths"]["rank"][0] = 2
    _add_booth_row(d, rank=1, is_lead=False)


def _mixed_rank_source(d: Payload) -> None:
    _add_booth_row(d, rank=2, is_lead=False, rank_source="inferred")


def _unknown_rank_source(d: Payload) -> None:
    d["booths"]["rank_source"][0] = "guessed"


def _games_ranked_with_a_lead(d: Payload) -> None:
    d["booths"]["rank_source"][0] = "games"


def _booth_game_list_short(d: Payload) -> None:
    d["booths"]["game_list"][0] = []


def _flagship_over_games(d: Payload) -> None:
    d["booths"]["flagship_games"][0] = 2


def _flagship_in_flagshipless_group(d: Payload) -> None:
    d["lookups"]["network_groups"][0]["flagship"] = None


def _viewership_duplicate(d: Payload) -> None:
    v = d["viewership"]
    for name, col in list(v.items()):
        v[name] = [*col, copy.deepcopy(col[0])]


def _viewership_game_list_short(d: Payload) -> None:
    d["viewership"]["game_list"][0] = []


def _viewership_zero_games(d: Payload) -> None:
    d["viewership"]["games"][0] = 0
    d["viewership"]["game_list"][0] = []


def _lineup_without_pbp(d: Payload) -> None:
    d["games"]["crew_source"][0] = "published_lineup"
    d["games"]["crew_source_url"][0] = "https://example.com/lineup"
    d["games"]["crew"][0] = [{"person": 0, "role": "analyst"}]


def _lineup_without_url(d: Payload) -> None:
    d["games"]["crew_source"][0] = "published_lineup"


def _lineup_http_url(d: Payload) -> None:
    d["games"]["crew_source"][0] = "published_lineup"
    d["games"]["crew_source_url"][0] = "http://example.com/lineup"


def _source_none_with_crew(d: Payload) -> None:
    d["games"]["crew_source"][0] = None


def _source_506_without_crew(d: Payload) -> None:
    d["games"]["crew_source"][1] = "506"


def _url_without_lineup(d: Payload) -> None:
    d["games"]["crew_source_url"][0] = "https://example.com/lineup"


def _network_in_two_groups(d: Payload) -> None:
    d["lookups"]["network_groups"].append(
        {"id": "cbs", "name": "CBS", "flagship": None, "members": [1]}
    )


def _network_in_no_group(d: Payload) -> None:
    d["lookups"]["network_groups"][0]["members"] = [0]


def _categories_reordered(d: Payload) -> None:
    d["lookups"]["view_categories"].reverse()


def _bad_family(d: Payload) -> None:
    d["lookups"]["networks"][0]["family"] = "abc"


def _solo_sum(d: Payload) -> None:
    d["special"]["solo_other"][0] = 1


def _solo_thursday(d: Payload) -> None:
    d["special"]["solo_thursday"][0] = 0
    d["special"]["solo_other"][0] = 1


def _solo_holiday(d: Payload) -> None:
    d["special"]["solo_thursday"][0] = 0
    d["special"]["solo_holiday"][0] = 1


def _old_block(d: Payload) -> None:
    d["fox_booths"] = d["booths"]


def _old_agotw_block(d: Payload) -> None:
    d["agotw_viewership"] = d["viewership"]


def _booth_volatility_column(d: Payload) -> None:
    d["booths"]["raw_mean_volatility"] = [None]


def _booth_spread_column(d: Payload) -> None:
    d["booths"]["raw_mean_abs_spread"] = [None]


def _booth_pregame_spread(d: Payload) -> None:
    d["booths"]["pregame_spread"] = [None]


def _slots_reordered(d: Payload) -> None:
    d["lookups"]["slots"] = list(reversed(NFL_SLOTS))


def _unreferenced_person(d: Payload) -> None:
    d["lookups"]["people"].append({"id": "p2", "name": "Cy Fable"})


def _unreferenced_network(d: Payload) -> None:
    d["lookups"]["networks"].append({"id": "nbc", "name": "NBC"})


def _viewers_with_cause(d: Payload) -> None:
    d["games"]["cause"][0] = "none"


def _unrated_without_cause(d: Payload) -> None:
    d["games"]["cause"][1] = None


def _scope_on_unrated(d: Payload) -> None:
    d["games"]["scope"][1] = "game"


def _era_on_unrated(d: Payload) -> None:
    d["games"]["era"][1] = 0


def _one_point_null(d: Payload) -> None:
    d["games"]["away_points"][0] = None


def _margin_mismatch(d: Payload) -> None:
    d["games"]["final_margin"][0] = 4


def _margin_without_points(d: Payload) -> None:
    d["games"]["final_margin"][1] = 0


MUTATORS: list[tuple[str, Mutator]] = [
    ("top_extra", _top_extra),
    ("block_extra", _block_extra),
    ("misaligned", _misaligned),
    ("bad_version", lambda d: d.update(schema_version="1.0.0")),
    ("home_idx", _set("games", "home", 0, 2)),
    ("away_idx", _set("games", "away", 0, -1)),
    ("home_name_idx", _set("games", "home_name", 0, 2)),
    ("away_name_idx", _set("games", "away_name", 0, 5)),
    ("slot_idx", _set("games", "slot", 0, 12)),
    ("original_slot_idx", _set("games", "original_slot", 0, 12)),
    ("original_network_idx", _set("games", "original_network", 0, 9)),
    ("network_idx", _set("games", "network", 0, 9)),
    ("crew_person_idx", _set("games", "crew", 0, [{"person": 3, "role": "pbp"}])),
    ("era_idx", _set("games", "era", 0, 4)),
    ("special_franchise_idx", _set("special", "franchise", 0, 7)),
    ("booth_pbp_idx", _set("booths", "pbp_person", 0, 7)),
    ("booth_analyst_idx", _set("booths", "analyst_person", 0, 7)),
    ("booth_group_idx", _set("booths", "network_group", 0, 7)),
    ("viewership_era_idx", _set("viewership", "era", 0, 7)),
    ("viewership_category_idx", _set("viewership", "category", 0, 12)),
    ("booth_game_list", _set("booths", "game_list", 0, [5])),
    ("viewership_game_list", _set("viewership", "game_list", 0, [-1])),
    ("two_leads", _two_leads),
    ("rank_gap", _rank_gap),
    ("lead_not_rank_one", _lead_not_rank_one),
    ("mixed_rank_source", _mixed_rank_source),
    ("unknown_rank_source", _unknown_rank_source),
    ("games_ranked_with_a_lead", _games_ranked_with_a_lead),
    ("booth_game_list_short", _booth_game_list_short),
    ("flagship_over_games", _flagship_over_games),
    ("flagship_in_flagshipless_group", _flagship_in_flagshipless_group),
    ("viewership_duplicate", _viewership_duplicate),
    ("viewership_game_list_short", _viewership_game_list_short),
    ("viewership_zero_games", _viewership_zero_games),
    ("lineup_without_pbp", _lineup_without_pbp),
    ("lineup_without_url", _lineup_without_url),
    ("lineup_http_url", _lineup_http_url),
    ("source_none_with_crew", _source_none_with_crew),
    ("source_506_without_crew", _source_506_without_crew),
    ("url_without_lineup", _url_without_lineup),
    ("network_in_two_groups", _network_in_two_groups),
    ("network_in_no_group", _network_in_no_group),
    ("categories_reordered", _categories_reordered),
    ("bad_family", _bad_family),
    ("solo_sum", _solo_sum),
    ("solo_thursday", _solo_thursday),
    ("solo_holiday", _solo_holiday),
    ("old_fox_booths_block", _old_block),
    ("old_agotw_block", _old_agotw_block),
    ("booth_volatility_column", _booth_volatility_column),
    ("booth_spread_column", _booth_spread_column),
    ("booth_pregame_spread", _booth_pregame_spread),
    ("viewers_zero", _set("games", "viewers", 0, 0)),
    ("viewers_with_cause", _viewers_with_cause),
    ("unrated_without_cause", _unrated_without_cause),
    ("scope_on_unrated", _scope_on_unrated),
    ("era_on_unrated", _era_on_unrated),
    ("one_point_null", _one_point_null),
    ("margin_mismatch", _margin_mismatch),
    ("margin_without_points", _margin_without_points),
    ("excitement_nan", _set("games", "excitement", 0, float("nan"))),
    ("excitement_inf", _set("games", "excitement", 0, float("inf"))),
    ("standalone_total", _set("special", "standalone_total", 0, 2)),
    ("special_identity", _set("special", "special", 0, 3)),
    ("international_other", _set("special", "international_other", 0, 3)),
    ("slots_reordered", _slots_reordered),
    ("unreferenced_person", _unreferenced_person),
    ("unreferenced_network", _unreferenced_network),
    ("ambiguous_over_doubleheader", _set("season_weeks", "fox_ambiguous_weeks", 0, 3)),
]


@pytest.mark.parametrize("mutate", [m for _, m in MUTATORS], ids=[n for n, _ in MUTATORS])
def test_broken_variant_raises(mutate: Mutator) -> None:
    data = _load()
    mutate(data)
    with pytest.raises(ValidationError):
        validate_nfl_site_data(data)


@pytest.mark.parametrize("mutate", [m for _, m in MUTATORS], ids=[n for n, _ in MUTATORS])
def test_errors_never_echo_values(mutate: Mutator) -> None:
    data = _load()
    mutate(data)
    with pytest.raises(ValidationError) as exc:
        validate_nfl_site_data(data)
    text = str(exc.value)
    for needle in INVENTED_STRINGS:
        assert needle not in text


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
    "pregame_spread",
    "coverage_share",
    "spread",
    "crew_names",
    "wp",
    "home_wp",
    "pbp",
    "raw_mean_abs_spread",
    "raw_n_spread",
    "raw_mean_volatility",
    "raw_n_volatility",
    "generated_at",
    "game_type",
    "status",
}


def test_no_banned_field_names() -> None:
    models = _all_models(NflSiteData)
    assert len(models) > 10
    names = {name for model in models for name in model.model_fields}
    assert not names & BANNED_NAMES


def test_every_model_forbids_extras_strictly() -> None:
    for model in _all_models(NflSiteData):
        cfg = model.model_config
        assert cfg.get("extra") == "forbid", model.__name__
        assert cfg.get("strict") is True, model.__name__
        assert cfg.get("frozen") is True, model.__name__


def test_nfl_game_fields_pinned() -> None:
    assert NFL_GAME_FIELDS == (
        "season",
        "week",
        "date",
        "kickoff",
        "home",
        "away",
        "home_name",
        "away_name",
        "home_points",
        "away_points",
        "final_margin",
        "slot",
        "standalone",
        "agotw",
        "cbs_national",
        "international",
        "flexed",
        "original_slot",
        "original_network",
        "change_url",
        "network",
        "crew",
        "crew_source",
        "crew_source_url",
        "excitement",
        "viewers",
        "scope",
        "era",
        "rr_url",
        "source_url",
        "cause",
        "place",
    )


def test_slots_match_the_999_4_slot_names() -> None:
    from booth_review.nfl.rules import SlotName

    assert tuple(SlotName.__args__) == NFL_SLOTS  # type: ignore[attr-defined]
    assert nfl_models.NflSlotLabel.__args__ == NFL_SLOTS  # type: ignore[attr-defined]


def test_schema_file_matches_models() -> None:
    committed = json.loads((REPO / SCHEMA_PATH).read_text())
    assert committed == render_schema(), (
        "docs/nfl-data.schema.json is out of date -- run "
        "`uv run python -m booth_review.contract.nfl_schema` and commit the result"
    )


def test_schema_version_pinned() -> None:
    assert NFL_SCHEMA_VERSION == "2.2.0"
    assert render_schema()["$id"] == "booth-review/nfl-data/2.2.0"


def test_cfb_contract_unchanged() -> None:
    assert cfb_models.SCHEMA_VERSION == "2.7.0"
    digest = hashlib.sha256((REPO / "docs" / "site-data.schema.json").read_bytes()).hexdigest()
    assert digest == CFB_SCHEMA_SHA256


# --- the committed synthetic fixture -----------------------------------------

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "contract" / "nfl-data.fixture.json"


def _fixture() -> Payload:
    data: Payload = json.loads(FIXTURE_PATH.read_text())
    return data


def test_fixture_validates() -> None:
    data = validate_nfl_site_data(_fixture())
    n = len(data.games.season)
    assert n >= 35
    for name in type(data.games).model_fields:
        assert len(getattr(data.games, name)) == n, name


def test_fixture_is_current() -> None:
    from nfl_site_fixture import build_fixture, render

    assert FIXTURE_PATH.read_text() == render(build_fixture()), (
        "tests/fixtures/contract/nfl-data.fixture.json is out of date -- run "
        "`uv run python tests/nfl_site_fixture.py` and commit the result"
    )


def test_fixture_uses_only_example_hosts() -> None:
    import re

    hosts = set(re.findall(r"https?://([^/\"]+)", FIXTURE_PATH.read_text()))
    assert hosts == {"example.com"}


def test_fixture_covers_every_view_case() -> None:
    d = _fixture()
    g, s = d["games"], d["special"]
    assert any(x > 0 for x in s["international_other"])
    assert any(u is not None for u in g["change_url"])
    assert any(x is not None for x in g["original_slot"])
    assert any(f for f in g["flexed"])
    assert None in g["network"]
    assert None in g["excitement"]
    assert {"pending", "regional", "none"} <= set(g["cause"])
    assert {"window", "game"} <= set(g["scope"])
    assert any(m == 0 for m in g["final_margin"])
    assert any(m is None for m in g["final_margin"])
    assert any(e["role"] == "unknown" for crew in g["crew"] for e in crew)
    b, v, lk = d["booths"], d["viewership"], d["lookups"]
    assert any(b["low_n"])
    assert any(f > 0 for f in b["fill_in_games"])
    assert any(n > 0 for n in b["lineup_games"])
    assert {"published", "override", "inferred", "games"} == set(b["rank_source"])
    assert any(n == 0 for n in b["games"])
    assert "published_lineup" in g["crew_source"]
    assert any(c == [] for c in g["crew"])
    cats = [c["id"] for c in lk["view_categories"]]
    seen = {cats[c] for c in v["category"]}
    assert {"agotw", "cbs_national", "snf", "mnf", "tnf", "thanksgiving", "christmas"} <= seen
    assert len(set(v["era"])) >= 2
    assert any(x for x in v["low_n"])
    assert any(r is None for r in v["viewership_resid"])
    for col in ("solo_thursday", "solo_sunday", "solo_monday", "solo_holiday", "solo_other"):
        assert any(x > 0 for x in s[col]), col
    assert any(
        sum(1 for gg, _ in zip(b["network_group"], b["season"], strict=True) if gg == gi) == 1
        for gi in range(len(lk["network_groups"]))
    )
    w = d["season_weeks"]
    zero = [
        i
        for i in range(len(w["season"]))
        if w["fox_doubleheader_weeks"][i] - w["fox_ambiguous_weeks"][i] <= 0
    ]
    assert zero
    assert any(w["fox_ambiguous_weeks"])
    assert d["freshness"]["in_progress"] is True


def test_fixture_errors_never_echo_names_or_urls() -> None:
    d = _fixture()
    d["games"]["home"][0] = 99
    d["games"]["viewers"][0] = 0
    with pytest.raises(ValidationError) as exc:
        validate_nfl_site_data(d)
    text = str(exc.value)
    names = [f["name"] for f in d["lookups"]["franchises"]] + [
        p["name"] for p in d["lookups"]["people"]
    ]
    for needle in [*names, "example.com"]:
        assert needle not in text


# -- WR-04: every float is finite, and the file is never written with NaN ------------------

_FLOAT_COLUMNS = (
    ("games", "excitement"),
    ("special", "agotw_rate"),
    ("special", "cbs_national_rate"),
    ("booths", "raw_mean_abs_margin"),
    ("booths", "raw_mean_excitement"),
    ("booths", "raw_mean_viewers"),
    ("booths", "adj_margin_resid"),
    ("booths", "adj_margin_se"),
    ("booths", "adj_excitement_resid"),
    ("booths", "adj_excitement_se"),
    ("viewership", "mean_viewers"),
    ("viewership", "viewership_resid"),
    ("viewership", "viewership_se"),
)


def test_float_column_list_covers_every_float_field() -> None:
    found = set()
    for block in ("games", "special", "booths", "viewership"):
        model = NflSiteData.model_fields[block].annotation
        assert isinstance(model, type) and issubclass(model, BaseModel)
        for name, field in model.model_fields.items():
            if "float" in str(field.annotation):
                found.add((block, name))
    assert found == set(_FLOAT_COLUMNS)


@pytest.mark.parametrize(("block", "column"), _FLOAT_COLUMNS)
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_floats_are_rejected_by_position(block: str, column: str, bad: float) -> None:
    payload = _load()
    payload[block][column][0] = bad
    with pytest.raises(ValidationError) as err:
        validate_nfl_site_data(payload)
    from booth_review.build.site_data import _contract_error_summary

    message = _contract_error_summary(err.value)
    assert f"{block}.{column}[0]: must be finite" in message
    assert "nan" not in message.lower()
    assert "inf" not in message.lower().replace("finite", "")


def test_bare_nan_in_a_file_fails_by_position_only() -> None:
    from booth_review.build.site_assembly import nfl_site_payload_from_bytes
    from booth_review.errors import SiteBuildError

    payload = _load()
    payload["viewership"]["viewership_se"][0] = float("nan")
    raw = json.dumps(payload).encode("utf-8")
    assert b"NaN" in raw
    with pytest.raises(SiteBuildError) as err:
        nfl_site_payload_from_bytes(raw)
    assert "viewership.viewership_se[0]: must be finite" in str(err.value)


def test_serializers_never_emit_nan() -> None:
    from booth_review.build.nfl_site_data import nfl_site_payload_bytes

    site = validate_nfl_site_data(_load())
    body = nfl_site_payload_bytes(site)
    assert b"NaN" not in body and b"Infinity" not in body
    # A model that skipped validation still cannot be written as invalid JSON.
    booths = site.booths.model_copy(update={"adj_margin_se": [float("nan")]})
    broken = site.model_copy(update={"booths": booths})
    with pytest.raises(ValueError):
        nfl_site_payload_bytes(broken)


# --- Phase 18 Plan 01: upcoming block and freshness.weekend (contract 2.1.0) ---


def _fixture() -> Payload:
    data: Payload = json.loads(FIXTURE_PATH.read_text())
    return data


def _set_upcoming(column: str, i: int, value: object) -> Payload:
    data = _fixture()
    data["upcoming"][column][i] = value
    return data


def test_fixture_upcoming_covers_every_weekend_state() -> None:
    site = validate_nfl_site_data(_fixture())
    u = site.upcoming
    assert len(u.season) == 10
    assert site.freshness.weekend is not None
    assert site.freshness.weekend.week == 5
    assert sorted(r for r in u.booth_rank if r is not None) == [1, 2]
    assert "slot" in u.network_basis
    assert None in u.kickoff and None in u.network and any(u.neutral)


def test_upcoming_network_basis_null_exactly_when_network_null() -> None:
    with pytest.raises(ValidationError, match=r"upcoming\.network_basis\[0\]"):
        validate_nfl_site_data(_set_upcoming("network_basis", 0, None))
    with pytest.raises(ValidationError, match=r"upcoming\.network_basis\[8\]"):
        validate_nfl_site_data(_set_upcoming("network_basis", 8, "slot"))
    with pytest.raises(ValidationError, match=r"upcoming\.network_basis\.0"):
        validate_nfl_site_data(_set_upcoming("network_basis", 0, "wikipedia"))


def test_upcoming_kickoff_null_forces_slot_null_and_date_rule() -> None:
    with pytest.raises(ValidationError, match=r"upcoming\.slot\[7\]"):
        validate_nfl_site_data(_set_upcoming("slot", 7, 9))
    with pytest.raises(ValidationError, match=r"upcoming\.date\[0\]"):
        validate_nfl_site_data(_set_upcoming("date", 0, None))
    validate_nfl_site_data(_set_upcoming("date", 7, None))


def test_upcoming_booth_rank_needs_a_crew() -> None:
    with pytest.raises(ValidationError, match=r"upcoming\.booth_rank\[2\]"):
        validate_nfl_site_data(_set_upcoming("booth_rank", 2, 1))


def test_upcoming_game_already_in_games_is_rejected_count_only() -> None:
    data = _fixture()
    g = data["games"]
    for column in ("season", "week", "home", "away"):
        data["upcoming"][column][0] = g[column][0]
    with pytest.raises(ValidationError) as info:
        validate_nfl_site_data(data)
    assert "games/upcoming: 1 game(s) appear more than once" in str(info.value)


def test_upcoming_rejects_a_published_lineup_source_and_extra_keys() -> None:
    with pytest.raises(ValidationError, match=r"upcoming\.crew_source\.0"):
        validate_nfl_site_data(_set_upcoming("crew_source", 0, "published_lineup"))
    data = _fixture()
    data["upcoming"]["viewers"] = [None] * len(data["upcoming"]["season"])
    with pytest.raises(ValidationError, match=r"upcoming\.viewers"):
        validate_nfl_site_data(data)


# --- Phase 24 Plan 06: place and lookups.venues (contract 2.2.0) ---


def _venue(name: str = "Fixture Field") -> dict[str, object]:
    return {
        "name": name,
        "city": "Faketown",
        "state": "TX",
        "country": "US",
        "lat": 29.7,
        "lon": -95.4,
    }


def test_old_schema_version_is_rejected() -> None:
    data = _load()
    data["schema_version"] = "2.1.0"
    with pytest.raises(ValidationError, match="schema_version"):
        validate_nfl_site_data(data)


def test_place_index_must_be_in_range_and_venues_must_be_referenced() -> None:
    data = _load()
    data["lookups"]["venues"] = [_venue()]
    with pytest.raises(ValidationError, match=r"lookups\.venues\[0\]"):
        validate_nfl_site_data(data)
    data["games"]["place"][0] = 0
    validate_nfl_site_data(data)
    data["games"]["place"][0] = 1
    with pytest.raises(ValidationError, match=r"games\.place\[0\]"):
        validate_nfl_site_data(data)


def test_upcoming_place_references_count_and_must_match_length() -> None:
    data = _fixture()
    n = len(data["upcoming"]["season"])
    data["upcoming"]["place"][0] = len(data["lookups"]["venues"])
    with pytest.raises(ValidationError, match=r"upcoming\.place\[0\]"):
        validate_nfl_site_data(data)
    data = _fixture()
    data["upcoming"]["place"] = data["upcoming"]["place"][: n - 1]
    with pytest.raises(ValidationError, match=r"upcoming\.place"):
        validate_nfl_site_data(data)


def test_fixture_has_placed_null_and_foreign_places() -> None:
    site = validate_nfl_site_data(_fixture())
    assert any(p is not None for p in site.games.place)
    assert any(p is None for p in site.games.place)
    assert any(p is not None for p in site.upcoming.place)
    assert any(v.country == "GB" for v in site.lookups.venues)


def test_venue_coordinates_are_range_checked() -> None:
    data = _load()
    data["lookups"]["venues"] = [{**_venue(), "lat": 95.0}]
    data["games"]["place"][0] = 0
    with pytest.raises(ValidationError, match=r"venues\.0\.lat"):
        validate_nfl_site_data(data)
