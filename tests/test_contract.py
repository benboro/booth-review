"""Tests for the site-data contract (D-13/D-14): fixture validation, broken
variants, and schema drift.

The fixture at tests/fixtures/contract/site-data.fixture.json is fully
synthetic: invented teams, people, networks, and publishers, and
example.com source URLs only -- never a real announcer or team name.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from booth_review.contract.models import SITE_DATA_FIELDS, TelecastColumns, validate_site_data
from booth_review.contract.schema import SCHEMA_PATH, render_schema

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "contract" / "site-data.fixture.json"


def _load_fixture() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(FIXTURE_PATH.read_text())
    return data


def test_fixture_validates() -> None:
    data = _load_fixture()
    site_data = validate_site_data(data)
    n = len(site_data.telecasts.season)
    for name in TelecastColumns.model_fields:
        assert len(getattr(site_data.telecasts, name)) == n, name


def test_fixture_has_a_late_time_slot() -> None:
    data = _load_fixture()
    assert "late" in data["telecasts"]["time_slot"]


def _add_unknown_top_level_key(data: dict[str, Any]) -> dict[str, Any]:
    data["unexpected_top_level_field"] = "nope"
    return data


def _add_unknown_telecast_column(data: dict[str, Any]) -> dict[str, Any]:
    n = len(data["telecasts"]["season"])
    data["telecasts"]["venue"] = ["Example Field"] * n
    return data


def _drop_element_from_viewers(data: dict[str, Any]) -> dict[str, Any]:
    data["telecasts"]["viewers"] = data["telecasts"]["viewers"][:-1]
    return data


def _out_of_range_network_index(data: dict[str, Any]) -> dict[str, Any]:
    data["telecasts"]["network"][0] = len(data["lookups"]["networks"])
    return data


def _out_of_range_crew_person_index(data: dict[str, Any]) -> dict[str, Any]:
    data["telecasts"]["crew"][0][0]["person"] = len(data["lookups"]["people"])
    return data


def _zero_viewers(data: dict[str, Any]) -> dict[str, Any]:
    data["telecasts"]["viewers"][0] = 0
    return data


def _excitement_as_string(data: dict[str, Any]) -> dict[str, Any]:
    data["telecasts"]["excitement"][0] = "7.1"
    return data


def _wrong_schema_version(data: dict[str, Any]) -> dict[str, Any]:
    data["schema_version"] = "0.9.0"
    return data


def _combined_feeds_below_two(data: dict[str, Any]) -> dict[str, Any]:
    # Any index works; the model_validator flags a non-null value below 2
    # regardless of whether that index previously held combined_feeds data.
    data["telecasts"]["combined_feeds"][0] = 1
    return data


def _empty_rr_urls(data: dict[str, Any]) -> dict[str, Any]:
    data["telecasts"]["rr_urls"][0] = []
    return data


def _out_of_range_home_conference_index(data: dict[str, Any]) -> dict[str, Any]:
    data["telecasts"]["home_conference"][0] = len(data["lookups"]["conferences"])
    return data


def _out_of_range_away_conference_index(data: dict[str, Any]) -> dict[str, Any]:
    data["telecasts"]["away_conference"][0] = len(data["lookups"]["conferences"])
    return data


def _game_type_championship_not_in_enum(data: dict[str, Any]) -> dict[str, Any]:
    data["telecasts"]["game_type"][0] = "championship"
    return data


def _playoff_round_on_non_playoff_game(data: dict[str, Any]) -> dict[str, Any]:
    # index 0 is game_type "regular" in the fixture.
    data["telecasts"]["playoff_round"][0] = "semifinal"
    return data


def _conference_entry_with_extra_key(data: dict[str, Any]) -> dict[str, Any]:
    data["lookups"]["conferences"][0]["region"] = "Midwest"
    return data


def _schema_version_1_0_0(data: dict[str, Any]) -> dict[str, Any]:
    data["schema_version"] = "1.0.0"
    return data


def _schema_version_1_1_0(data: dict[str, Any]) -> dict[str, Any]:
    data["schema_version"] = "1.1.0"
    return data


def _time_slot_evening_not_in_enum(data: dict[str, Any]) -> dict[str, Any]:
    data["telecasts"]["time_slot"][0] = "evening"
    return data


_BROKEN_VARIANTS = [
    pytest.param(_add_unknown_top_level_key, id="unknown-top-level-key"),
    pytest.param(_add_unknown_telecast_column, id="unknown-telecast-column"),
    pytest.param(_drop_element_from_viewers, id="misaligned-viewers-length"),
    pytest.param(_out_of_range_network_index, id="out-of-range-network-index"),
    pytest.param(_out_of_range_crew_person_index, id="out-of-range-crew-person-index"),
    pytest.param(_zero_viewers, id="zero-viewers"),
    pytest.param(_excitement_as_string, id="excitement-as-string"),
    pytest.param(_wrong_schema_version, id="wrong-schema-version"),
    pytest.param(_combined_feeds_below_two, id="combined-feeds-below-two"),
    pytest.param(_empty_rr_urls, id="empty-rr-urls"),
    pytest.param(_out_of_range_home_conference_index, id="out-of-range-home-conference-index"),
    pytest.param(_out_of_range_away_conference_index, id="out-of-range-away-conference-index"),
    pytest.param(_game_type_championship_not_in_enum, id="game-type-championship-not-in-enum"),
    pytest.param(_playoff_round_on_non_playoff_game, id="playoff-round-on-non-playoff-game"),
    pytest.param(_conference_entry_with_extra_key, id="conference-entry-with-extra-key"),
    pytest.param(_schema_version_1_0_0, id="schema-version-1-0-0"),
    pytest.param(_schema_version_1_1_0, id="schema-version-1-1-0"),
    pytest.param(_time_slot_evening_not_in_enum, id="time-slot-evening-not-in-enum"),
]


@pytest.mark.parametrize("mutate", _BROKEN_VARIANTS)
def test_broken_variant_raises(mutate: Any) -> None:
    data = copy.deepcopy(_load_fixture())
    broken = mutate(data)
    with pytest.raises(ValidationError):
        validate_site_data(broken)


def test_schema_file_matches_models() -> None:
    committed = json.loads(SCHEMA_PATH.read_text())
    assert committed == render_schema(), (
        "docs/site-data.schema.json is out of date -- run "
        "`uv run python -m booth_review.contract.schema` and commit the result"
    )


def test_site_data_fields_match_columns() -> None:
    assert tuple(TelecastColumns.model_fields) == SITE_DATA_FIELDS


def test_fixture_has_no_cfbd_only_fields() -> None:
    cfbd_only = {
        "conference",
        "venue",
        "home_win_probability",
        "spread",
        "excitement_index_raw",
        "game_id",
        "home_classification",
        "away_classification",
        "playoff",
        "is_cfp",
    }
    assert cfbd_only.isdisjoint(TelecastColumns.model_fields)
