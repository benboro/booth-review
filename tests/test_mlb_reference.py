"""MLB reference loaders and resolvers, on a synthetic fixture."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from booth_review.errors import ReferenceTableError
from booth_review.mlb.reference import (
    load_mlb_booth_ranks,
    load_mlb_crew_overrides,
    load_mlb_reference,
)
from booth_review.mlb.teams import MlbNetworkResolver, MlbTeamResolver
from booth_review.people.registry import load_people

FIXTURE = Path(__file__).parent / "fixtures" / "mlb" / "reference"
URL = "https://example.invalid/x"


@pytest.fixture
def ref(tmp_path: Path) -> Path:
    dest = tmp_path / "ref"
    shutil.copytree(FIXTURE, dest)
    return dest


def _append(ref: Path, name: str, line: str) -> None:
    path = ref / name
    path.write_text(path.read_text(encoding="utf-8") + line + "\n", encoding="utf-8")


def test_fixture_loads(ref: Path) -> None:
    bundle = load_mlb_reference(ref)
    assert bundle.clubs.ids() == {"alpha", "bravo", "charlie", "delta"}
    assert bundle.crosswalk and bundle.networks and bundle.map_overrides
    assert bundle.crew_overrides == ()
    assert len(bundle.booth_ranks.rows) == 3


def test_missing_required_table_names_file_only(ref: Path) -> None:
    (ref / "mlb_networks.csv").unlink()
    with pytest.raises(ReferenceTableError, match=r"mlb_networks\.csv"):
        load_mlb_reference(ref)
    (ref / "mlb_booth_ranks.csv").unlink()
    with pytest.raises(ReferenceTableError, match=r"mlb_booth_ranks\.csv|mlb_networks\.csv"):
        load_mlb_reference(ref)


def test_missing_crew_overrides_is_empty(tmp_path: Path) -> None:
    assert load_mlb_crew_overrides(tmp_path / "mlb_crew_overrides.csv") == []


def test_crew_overrides_read_when_present(tmp_path: Path) -> None:
    path = tmp_path / "mlb_crew_overrides.csv"
    path.write_text(
        "season,game_date,away_club,home_club,game_number,network_id,pbp,analyst_1,analyst_2,"
        f"source_url,note\n2026,2026-05-01,alpha,bravo,1,net_one,Ana Fixture,Bo Fixture,,{URL},\n",
        encoding="utf-8",
    )
    rows = load_mlb_crew_overrides(path)
    assert rows[0].network_id == "net_one" and rows[0].game_number == 1


def test_crosswalk_overlap_rejected(ref: Path) -> None:
    _append(ref, "mlb_team_crosswalk.csv", "506,Bravo,charlie,,,x")
    with pytest.raises(ReferenceTableError, match=r"line \d+"):
        load_mlb_reference(ref)


def test_crosswalk_unknown_club_rejected(ref: Path) -> None:
    _append(ref, "mlb_team_crosswalk.csv", "506,Nowhere,zulu,,,")
    with pytest.raises(ReferenceTableError, match="club_id"):
        load_mlb_reference(ref)


def test_formula_cell_rejected(ref: Path) -> None:
    _append(ref, "mlb_networks.csv", "506,=SUM(A1),net_one,broadcast,")
    with pytest.raises(ReferenceTableError):
        load_mlb_reference(ref)


def test_booth_rank_gap_rejected(ref: Path) -> None:
    _append(ref, "mlb_booth_ranks.csv", f"net_one,2026,3,Ana Fixture,Bo Fixture,{URL}")
    with pytest.raises(ReferenceTableError, match=r"mlb_booth_ranks\.csv: line 5"):
        load_mlb_reference(ref)


def test_booth_rank_http_rejected(ref: Path) -> None:
    _append(ref, "mlb_booth_ranks.csv", "net_one,2026,2,Ana Fixture,Bo Fixture,http://x.test/")
    with pytest.raises(ReferenceTableError, match="https"):
        load_mlb_reference(ref)


def test_booth_rank_duplicate_rejected(ref: Path) -> None:
    _append(ref, "mlb_booth_ranks.csv", f"net_one,2026,1,Ana Fixture,Bo Fixture,{URL}")
    with pytest.raises(ReferenceTableError, match="duplicate"):
        load_mlb_reference(ref)


def test_booth_rank_unresolved_rank_name_is_a_review_row(ref: Path) -> None:
    ranks = load_mlb_booth_ranks(ref / "mlb_booth_ranks.csv", load_people(ref))
    assert len(ranks.unresolved) == 1
    item = ranks.unresolved[0]
    assert (item.file, item.line, item.column, item.raw_name) == (
        "mlb_booth_ranks.csv",
        3,
        "analyst",
        "Newcomer Analyst",
    )
    row = next(r for r in ranks.rows if r.rank == 2)
    assert row.analyst_person_id is None and row.pbp_person_id == "cy-fixture"
    assert ranks.rows[0].pbp_person_id == "ana-fixture"


def test_map_override_validation(ref: Path) -> None:
    _append(ref, "mlb_postseason_map_overrides.csv", f"2026,lcs,AL,cable_two,{URL}")
    with pytest.raises(ReferenceTableError, match="duplicate"):
        load_mlb_reference(ref)


def test_map_override_bad_round_and_league(ref: Path) -> None:
    _append(ref, "mlb_postseason_map_overrides.csv", f"2026,semis,AL,net_one,{URL}")
    with pytest.raises(ReferenceTableError, match="round"):
        load_mlb_reference(ref)


def test_map_override_bad_league(ref: Path) -> None:
    _append(ref, "mlb_postseason_map_overrides.csv", f"2026,division,XX,net_one,{URL}")
    with pytest.raises(ReferenceTableError, match="league"):
        load_mlb_reference(ref)


def test_map_override_http_rejected(ref: Path) -> None:
    _append(ref, "mlb_postseason_map_overrides.csv", "2026,division,AL,net_one,http://x.test")
    with pytest.raises(ReferenceTableError, match="https"):
        load_mlb_reference(ref)


def test_team_resolver_sources_and_ranges(ref: Path) -> None:
    resolver = MlbTeamResolver.from_reference(load_mlb_reference(ref))
    r = resolver.resolve("506", "Alpha City", 2024)
    assert r.club_id == "alpha" and r.display_name == "Alpha City Aces"
    assert r.league == "AL" and r.division == "East"
    assert resolver.resolve("506", "Alpha City", 2026).club_id is None
    assert resolver.resolve("506", "Alpha Bay", 2025).display_name == "Alpha Bay Aces"
    # relocation: one club id, display name by season, via a season-free variant
    assert resolver.resolve("ratingsref", "Aces", 2024).display_name == "Alpha City Aces"
    assert resolver.resolve("ratingsref", "Aces", 2026).display_name == "Alpha Bay Aces"
    # "any" rows only when no source row matches
    assert resolver.resolve("506", "Delta", 2026).club_id == "delta"
    assert resolver.resolve("506", "Bravo", 2026).club_id == "bravo"
    assert resolver.resolve("506", "Nobody", 2026).club_id is None


def test_network_resolver(ref: Path) -> None:
    resolver = MlbNetworkResolver.from_reference(load_mlb_reference(ref))
    r = resolver.resolve("506", "Apple TV+")
    assert (r.network_id, r.family) == ("apple", "apple")
    assert resolver.resolve("506", "  apple   tv+ ").network_id == "apple"
    assert resolver.resolve("506", "Unknown Net").network_id is None
