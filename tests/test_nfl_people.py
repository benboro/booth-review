"""NFL crew resolution and people registration on the synthetic people table."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from booth_review.errors import ReferenceTableError
from booth_review.nfl.people import (
    REVIEW_NFL_PEOPLE_COLUMNS,
    read_people_decisions,
    register_nfl_people,
    resolve_crew,
)
from booth_review.people.registry import load_people

FIXTURE = Path(__file__).parent / "fixtures" / "nfl" / "reference"


@pytest.fixture
def ref(tmp_path: Path) -> Path:
    dest = tmp_path / "ref"
    shutil.copytree(FIXTURE, dest)
    return dest


def test_resolve_crew_positions_and_placeholders(ref: Path) -> None:
    registry = load_people(ref)
    crew = resolve_crew(("Ana Fixture", "TBA", "Bo Fixture", "Unknown Person"), registry)
    assert crew.pbp_person_id == "ana-fixture"
    assert crew.analyst_person_id == "bo-fixture"
    assert crew.sideline_person_ids == ()
    assert crew.unresolved_names == ("Unknown Person",)
    one = resolve_crew(("Ana Fixture",), registry)
    assert one.pbp_person_id == "ana-fixture"
    assert one.analyst_person_id is None


def test_new_person_registered_unknown_role(ref: Path) -> None:
    result = register_nfl_people(ref, {"New Caller": 3})
    assert result.counts["new_persons"] == 1
    assert result.existing_matches == ()
    person = load_people(ref).persons["new-caller"]
    assert person.usual_role == "unknown"
    assert load_people(ref).persons["ana-fixture"].usual_role == "pbp"


def test_existing_match_leaves_people_csv_byte_identical(ref: Path) -> None:
    before = (ref / "people.csv").read_bytes()
    result = register_nfl_people(ref, {"ANA FIXTURE": 2, "Ana Fixture": 5})
    assert (ref / "people.csv").read_bytes() == before
    by_name = {m.raw_name: m for m in result.existing_matches}
    assert by_name["ANA FIXTURE"].person_id == "ana-fixture"
    assert by_name["ANA FIXTURE"].spelling_known is False
    assert by_name["Ana Fixture"].spelling_known is True
    assert result.counts["new_variants"] == 0


def test_approved_variant_appended_only_for_that_person(ref: Path) -> None:
    result = register_nfl_people(
        ref, {"ANA FIXTURE": 2}, approved_variants={"ANA FIXTURE": "ana-fixture"}
    )
    assert result.counts["new_variants"] == 1
    registry = load_people(ref)
    assert "ANA FIXTURE" in registry.persons["ana-fixture"].variants
    assert registry.persons["bo-fixture"].variants == ("Bo Fixture",)
    assert registry.persons["ana-fixture"].usual_role == "pbp"


def test_wrong_person_approval_is_invalid_and_ignored(ref: Path) -> None:
    before = (ref / "people.csv").read_bytes()
    result = register_nfl_people(
        ref, {"ANA FIXTURE": 2}, approved_variants={"ANA FIXTURE": "bo-fixture"}
    )
    assert result.counts["invalid_decisions"] == 1
    assert result.counts["new_variants"] == 0
    assert (ref / "people.csv").read_bytes() == before


def test_dry_run_writes_nothing(ref: Path) -> None:
    path = ref / "people.csv"
    before, mtime = path.read_bytes(), path.stat().st_mtime_ns
    result = register_nfl_people(ref, {"New Caller": 1}, dry_run=True)
    assert result.counts["new_persons"] == 1
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == mtime


def test_delimiter_name_error_has_no_name(ref: Path) -> None:
    with pytest.raises(ReferenceTableError) as err:
        register_nfl_people(ref, {"Bad|Name": 1})
    assert "Bad" not in str(err.value)


def test_read_people_decisions(tmp_path: Path) -> None:
    path = tmp_path / "review.csv"
    rows = [
        "ANA FIXTURE,ana-fixture,2,False,add-variant",
        "Other Name,bo-fixture,1,False,",
        "Third Name,bo-fixture,1,False,keep",
        "Fourth Name,bo-fixture,1,False,merge-everything",
    ]
    path.write_text(
        ",".join(REVIEW_NFL_PEOPLE_COLUMNS) + "\n" + "\n".join(rows) + "\n", encoding="utf-8"
    )
    approvals, invalid = read_people_decisions(path)
    assert approvals == {"ANA FIXTURE": "ana-fixture"}
    assert invalid == 1
    assert read_people_decisions(tmp_path / "missing.csv") == ({}, 0)
