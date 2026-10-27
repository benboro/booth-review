"""The build-time serif glyph guard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from booth_review.build.serif_glyphs import check_serif_text
from booth_review.build.site_data import write_site_data
from booth_review.config import DataPaths
from booth_review.contract.models import validate_site_data
from booth_review.errors import SiteBuildError

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_supported_names_pass() -> None:
    names = [
        "Hawai\u02bbi",
        "Texas A&M",
        "Jos\u00e9",
        "2014\u20132026",
        "\u201cQ\u201d",
        "Bowl\u2019s",
    ]
    assert check_serif_text(names, where="x") is None


def test_missing_character_names_codepoint_and_where() -> None:
    with pytest.raises(SiteBuildError) as info:
        check_serif_text(["Ωmega"], where="site-data teams")
    assert "U+03A9" in str(info.value)
    assert "site-data teams" in str(info.value)


def test_several_missing_characters_listed_once_sorted() -> None:
    with pytest.raises(SiteBuildError) as info:
        check_serif_text(["Ωx", "Ω★", "Жy"], where="w")
    message = str(info.value)
    assert message.count("U+03A9") == 1
    assert message.index("U+03A9") < message.index("U+0416") < message.index("U+2605")


def test_write_site_data_rejects_a_team_name_the_subset_lacks(tmp_path: Path) -> None:
    fixture = REPO_ROOT / "tests" / "fixtures" / "contract" / "site-data.fixture.json"
    site = validate_site_data(json.loads(fixture.read_text(encoding="utf-8")))
    bad_team = site.lookups.teams[0].model_copy(update={"name": "Ωmega State"})
    teams = [bad_team, *site.lookups.teams[1:]]
    bad = site.model_copy(update={"lookups": site.lookups.model_copy(update={"teams": teams})})
    with pytest.raises(SiteBuildError, match="U\\+03A9"):
        write_site_data(DataPaths(vault=tmp_path), bad)
    assert not (tmp_path / "processed").exists()
