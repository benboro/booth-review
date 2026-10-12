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
    NflSiteData,
    validate_nfl_site_data,
)
from booth_review.contract.nfl_schema import SCHEMA_PATH, render_schema

Payload = dict[str, Any]
Mutator = Callable[[Payload], None]

REPO = Path(__file__).resolve().parent.parent

# sha256 of docs/site-data.schema.json recorded at the start of phase 999.5 plan 02.
CFB_SCHEMA_SHA256 = "b5c7ab15bd07f21b9d021ddd570ec3c0af349b741a01cd9cd491eb243de0bbe7"

INVENTED_STRINGS = ("Northfield Lanterns", "Harbor City", "Ada Quill", "example.com")


def _minimal_payload() -> Payload:
    """A tiny valid payload: two games (one rated, one unrated), one row per block."""
    return {
        "schema_version": "1.0.0",
        "freshness": {
            "season": 2026,
            "in_progress": True,
            "through_week": 3,
            "viewership_through_week": 2,
            "fox_default_season": 2025,
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
            "networks": [{"id": "fox", "name": "Fox"}, {"id": "cbs", "name": "CBS"}],
            "people": [{"id": "p1", "name": "Ada Quill"}],
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
            "excitement": [1.5, None],
            "viewers": [9000000, None],
            "scope": ["window", None],
            "era": [0, None],
            "rr_url": ["https://example.com/rr/1", None],
            "source_url": ["https://example.com/src/1", None],
            "cause": [None, "pending"],
        },
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
        "fox_booths": {
            "season": [2025],
            "group": ["lead"],
            "rank": [1],
            "pbp_person": [0],
            "analyst_person": [None],
            "games": [1],
            "fill_in_games": [0],
            "raw_n_margin": [1],
            "raw_n_excitement": [1],
            "raw_n_volatility": [0],
            "raw_mean_abs_margin": [3.0],
            "raw_mean_excitement": [1.5],
            "raw_mean_volatility": [None],
            "adj_n_margin": [1],
            "adj_n_excitement": [1],
            "adj_n_volatility": [0],
            "adj_margin_resid": [0.1],
            "adj_margin_se": [1.0],
            "adj_excitement_resid": [0.2],
            "adj_excitement_se": [1.0],
            "adj_volatility_resid": [None],
            "adj_volatility_se": [None],
            "low_n": [True],
            "game_list": [[0]],
        },
        "agotw_viewership": {
            "season": [2025],
            "era": [0],
            "group": ["lead"],
            "pbp_person": [0],
            "analyst_person": [None],
            "games": [1],
            "fill_in_games": [0],
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


def _two_leads(d: Payload) -> None:
    b = d["fox_booths"]
    for name, col in list(b.items()):
        b[name] = [*col, copy.deepcopy(col[0])]
    b["rank"][1] = 2


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


def _pooled_with_person(d: Payload) -> None:
    d["fox_booths"]["group"][0] = "others_pooled"


MUTATORS: list[tuple[str, Mutator]] = [
    ("top_extra", _top_extra),
    ("block_extra", _block_extra),
    ("misaligned", _misaligned),
    ("bad_version", lambda d: d.update(schema_version="1.0.1")),
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
    ("fox_pbp_idx", _set("fox_booths", "pbp_person", 0, 7)),
    ("fox_analyst_idx", _set("fox_booths", "analyst_person", 0, 7)),
    ("agotw_era_idx", _set("agotw_viewership", "era", 0, 7)),
    ("agotw_pbp_idx", _set("agotw_viewership", "pbp_person", 0, 7)),
    ("agotw_analyst_idx", _set("agotw_viewership", "analyst_person", 0, 7)),
    ("fox_game_list", _set("fox_booths", "game_list", 0, [5])),
    ("agotw_game_list", _set("agotw_viewership", "game_list", 0, [-1])),
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
    ("two_leads", _two_leads),
    ("pooled_with_person", _pooled_with_person),
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
        "excitement",
        "viewers",
        "scope",
        "era",
        "rr_url",
        "source_url",
        "cause",
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
    assert NFL_SCHEMA_VERSION == "1.0.0"
    assert render_schema()["$id"] == "booth-review/nfl-data/1.0.0"


def test_cfb_contract_unchanged() -> None:
    assert cfb_models.SCHEMA_VERSION == "2.3.0"
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
    b, a = d["fox_booths"], d["agotw_viewership"]
    assert {"lead", "other", "others_pooled"} == set(b["group"])
    assert any(b["low_n"])
    assert any(f > 0 for f in b["fill_in_games"])
    assert len(set(a["era"])) >= 2
    assert len(set(zip(a["pbp_person"], a["analyst_person"], strict=True))) >= 2
    assert any(x for x in a["low_n"])
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
    ("fox_booths", "raw_mean_abs_margin"),
    ("fox_booths", "raw_mean_excitement"),
    ("fox_booths", "raw_mean_volatility"),
    ("fox_booths", "adj_margin_resid"),
    ("fox_booths", "adj_margin_se"),
    ("fox_booths", "adj_excitement_resid"),
    ("fox_booths", "adj_excitement_se"),
    ("fox_booths", "adj_volatility_resid"),
    ("fox_booths", "adj_volatility_se"),
    ("agotw_viewership", "mean_viewers"),
    ("agotw_viewership", "viewership_resid"),
    ("agotw_viewership", "viewership_se"),
)


def test_float_column_list_covers_every_float_field() -> None:
    found = set()
    for block in ("games", "special", "fox_booths", "agotw_viewership"):
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
    payload["agotw_viewership"]["viewership_se"][0] = float("nan")
    raw = json.dumps(payload).encode("utf-8")
    assert b"NaN" in raw
    with pytest.raises(SiteBuildError) as err:
        nfl_site_payload_from_bytes(raw)
    assert "agotw_viewership.viewership_se[0]: must be finite" in str(err.value)


def test_serializers_never_emit_nan() -> None:
    from booth_review.build.nfl_site_data import nfl_site_payload_bytes

    site = validate_nfl_site_data(_load())
    body = nfl_site_payload_bytes(site)
    assert b"NaN" not in body and b"Infinity" not in body
    # A model that skipped validation still cannot be written as invalid JSON.
    booths = site.fox_booths.model_copy(update={"adj_margin_se": [float("nan")]})
    broken = site.model_copy(update={"fox_booths": booths})
    with pytest.raises(ValueError):
        nfl_site_payload_bytes(broken)
