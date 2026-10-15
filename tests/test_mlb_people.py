"""MLB crew resolution and the people review flow on the synthetic people table."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from booth_review.config import DataPaths
from booth_review.mlb.people import (
    REVIEW_MLB_PEOPLE_COLUMNS,
    read_people_decisions,
    register_mlb_people,
    resolve_crew,
)
from booth_review.mlb.reference import load_mlb_booth_ranks
from booth_review.people.registry import load_people
from booth_review.reference import read_reference_csv

FIXTURE = Path(__file__).parent / "fixtures" / "mlb" / "reference"


@pytest.fixture
def ref(tmp_path: Path) -> Path:
    dest = tmp_path / "ref"
    shutil.copytree(FIXTURE, dest)
    return dest


@pytest.fixture
def paths(tmp_path: Path) -> DataPaths:
    vault = tmp_path / "vault"
    (vault / "interim").mkdir(parents=True)
    return DataPaths(vault)


def _review(paths: DataPaths) -> Path:
    return paths.interim / "review_mlb_people.csv"


def test_resolve_crew_known_and_unknown(ref: Path) -> None:
    crew = resolve_crew(("Ana Fixture", "Bo Fixture", "Nobody Known"), load_people(ref))
    assert crew.pbp_person_id == "ana-fixture"
    assert crew.analyst_person_id == "bo-fixture"
    assert crew.sideline_person_ids == ()
    solo = resolve_crew(("Mystery Voice",), load_people(ref))
    assert solo.pbp_person_id is None
    assert solo.unresolved_names == ("Mystery Voice",)


def test_dry_run_lists_unresolved_rank_unresolved_and_crew_names(
    ref: Path, paths: DataPaths
) -> None:
    ranks = load_mlb_booth_ranks(ref / "mlb_booth_ranks.csv", load_people(ref))
    assert ranks.unresolved
    before = (ref / "people.csv").read_bytes()
    result = register_mlb_people(
        paths, ref, ["Ana Fixture", "Crew Newcomer", "Crew Newcomer"], ranks.unresolved
    )
    assert (ref / "people.csv").read_bytes() == before
    rows = read_reference_csv(_review(paths), REVIEW_MLB_PEOPLE_COLUMNS)
    names = [r["raw_name"] for r in rows]
    assert names == sorted(set(names))
    assert "Crew Newcomer" in names
    assert ranks.unresolved[0].raw_name in names
    assert "Ana Fixture" not in names
    assert all(r["decision"] == "" for r in rows)
    assert result.counts["new_persons"] == 0


def test_rank_unresolved_applied_then_rerun_has_no_unresolved(ref: Path, paths: DataPaths) -> None:
    ranks = load_mlb_booth_ranks(ref / "mlb_booth_ranks.csv", load_people(ref))
    register_mlb_people(paths, ref, [], ranks.unresolved)
    rows = read_reference_csv(_review(paths), REVIEW_MLB_PEOPLE_COLUMNS)
    text = _review(paths).read_text().splitlines()
    marked = [line + "add" if line.split(",")[0] == "Newcomer Analyst" else line for line in text]
    marked[0] = text[0]
    _review(paths).write_text("\n".join(marked) + "\n")
    assert len(rows) >= 1
    result = register_mlb_people(paths, ref, [], ranks.unresolved, apply=True)
    assert result.counts["new_persons"] == 1
    again = load_mlb_booth_ranks(ref / "mlb_booth_ranks.csv", load_people(ref))
    assert all(u.raw_name != "Newcomer Analyst" for u in again.unresolved)


def test_apply_only_registers_marked_rows(ref: Path, paths: DataPaths) -> None:
    register_mlb_people(paths, ref, ["Marked Caller", "Unmarked Caller"])
    path = _review(paths)
    lines = path.read_text().splitlines()
    lines = [
        line + "add"
        if line.startswith("Marked Caller")
        else line + "maybe"
        if line.startswith("Unmarked")
        else line
        for line in lines
    ]
    path.write_text("\n".join(lines) + "\n")
    adds, invalid = read_people_decisions(path)
    assert adds == ("Marked Caller",)
    assert invalid == 1
    result = register_mlb_people(paths, ref, ["Marked Caller", "Unmarked Caller"], apply=True)
    assert result.counts["new_persons"] == 1
    registry = load_people(ref)
    assert registry.lookup("Marked Caller") is not None
    assert registry.lookup("Unmarked Caller") is None


def test_rerun_dry_run_keeps_prior_decisions(ref: Path, paths: DataPaths) -> None:
    register_mlb_people(paths, ref, ["Marked Caller"])
    path = _review(paths)
    path.write_text(path.read_text().rstrip("\n") + "add\n")
    register_mlb_people(paths, ref, ["Marked Caller"])
    rows = read_reference_csv(path, REVIEW_MLB_PEOPLE_COLUMNS)
    assert rows[0]["decision"] == "add"


def test_real_reference_keeps_chris_and_chip_caray_apart_and_folds_variants() -> None:
    registry = load_people(Path(__file__).parent.parent / "data" / "reference")
    chris = registry.lookup("Chris Caray")
    chip = registry.lookup("Chip Caray")
    assert chris is not None
    assert chip is not None
    assert chris != chip
    for a, b in (
        ("A.J. Pierzynski", "AJ Pierzynski"),
        ("C.J. Nitkowski", "CJ Nitkowski"),
        ("C.C. Sabathia", "CC Sabathia"),
        ("Eduardo Perez", "Eduardo Pérez"),
        ("Matt Gubicza", "Mark Gubicza"),
        ("Ryan Rolland-Smith", "Ryan Rowland-Smith"),
        ("Ryan Spilborgs", "Ryan Spilborghs"),
    ):
        assert registry.lookup(a) is not None
        assert registry.lookup(a) == registry.lookup(b)
