"""NFL reference tables, loaders and resolvers, on synthetic fixture tables."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from booth_review.errors import ReferenceTableError
from booth_review.nfl.reference import (
    load_nfl_booth_ranks,
    load_nfl_franchises,
    load_nfl_lead_booth_overrides,
    load_nfl_networks,
    load_nfl_stadium_overrides,
    load_nfl_stadiums,
    load_nfl_team_crosswalk,
    load_nfl_week_overrides,
)
from booth_review.nfl.teams import NflNetworkResolver, NflTeamResolver

FIXTURE = Path(__file__).parent / "fixtures" / "nfl" / "reference"


@pytest.fixture
def ref(tmp_path: Path) -> Path:
    dest = tmp_path / "ref"
    shutil.copytree(FIXTURE, dest)
    return dest


def _append(ref: Path, name: str, line: str) -> None:
    path = ref / name
    path.write_text(path.read_text(encoding="utf-8") + line + "\n", encoding="utf-8")


def _rewrite(ref: Path, name: str, old: str, new: str) -> None:
    path = ref / name
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_fixture_loads(ref: Path) -> None:
    assert load_nfl_franchises(ref).ids() >= {"gulls", "otters"}
    assert load_nfl_team_crosswalk(ref)
    assert load_nfl_stadiums(ref) == {"FAKE01": "GB", "FAKE02": "DE"}
    assert load_nfl_networks(ref)
    assert ("fox", 2018) in load_nfl_lead_booth_overrides(ref)
    assert (2018, 5, "fox") in load_nfl_week_overrides(ref)


def test_team_resolver_ranges_and_display_names(ref: Path) -> None:
    resolver = NflTeamResolver.from_reference_dir(ref)
    assert resolver.resolve("nflverse", "HCG", 2015).franchise_id == "gulls"
    assert resolver.resolve("nflverse", "HCG", 2017).franchise_id is None
    assert resolver.resolve("nflverse", "LAG", 2017).franchise_id == "gulls"
    assert resolver.display_name("gulls", 2016) == "Harbor City Gulls"
    assert resolver.display_name("gulls", 2017) == "Lakeshore Gulls"
    assert resolver.resolve("nflverse", "HCG", 2016).display_name == "Harbor City Gulls"
    # "any" rows serve every source; a range outside the row is unresolved
    assert resolver.resolve("sports506", "Hill Moles", 2020).franchise_id == "moles"
    assert resolver.resolve("sports506", "Harbor City Gulls", 2019).franchise_id is None
    unresolved = resolver.resolve("nflverse", "ZZZ", 2020)
    assert (unresolved.franchise_id, unresolved.display_name, unresolved.method) == (
        None,
        None,
        "unresolved",
    )


def test_source_specific_beats_any(ref: Path) -> None:
    _append(ref, "nfl_team_crosswalk.csv", "sports506,Moles,elks,,,")
    resolver = NflTeamResolver.from_reference_dir(ref)
    assert resolver.resolve("sports506", "Moles", 2020).franchise_id == "elks"
    assert resolver.resolve("ratingsref", "Moles", 2020).franchise_id == "moles"


def test_network_resolver(ref: Path) -> None:
    resolver = NflNetworkResolver.from_reference_dir(ref)
    assert resolver.resolve("sports506", " fox ") == "fox"
    assert resolver.resolve("ratingsref", "NFL  Network") == "nfln"
    assert resolver.resolve("ratingsref", "Nowhere") is None


def test_yahoo_is_a_known_network_id(ref: Path) -> None:
    # The 2015 London game streamed only on Yahoo; without the id its RR record had no network.
    _append(ref, "nfl_networks.csv", "ratingsref,Yahoo,yahoo,")
    resolver = NflNetworkResolver.from_reference_dir(ref)
    assert resolver.resolve("ratingsref", "Yahoo") == "yahoo"


@pytest.mark.parametrize(
    ("name", "old", "new"),
    [
        ("nfl_franchises.csv", "franchise_id,", "franchise,"),
        ("nfl_team_crosswalk.csv", "sports506,Gulls", "bogus,Gulls"),
        ("nfl_team_crosswalk.csv", "ELK,elks", "ELK,nope"),
        ("nfl_networks.csv", "sports506,NFLN,nfln", "sports506,NFLN,nflx"),
        ("nfl_stadiums.csv", ",GB,", ",gb,"),
        ("nfl_week_overrides.csv", "https://example.com/agotw", ""),
        ("nfl_week_overrides.csv", "https://example.com/agotw", "http://example.com/agotw"),
        ("nfl_week_overrides.csv", ",fox,", ",nbc,"),
        ("nfl_lead_booth_overrides.csv", "ana-fixture", "nobody"),
    ],
)
def test_loader_rejections(ref: Path, name: str, old: str, new: str) -> None:
    _rewrite(ref, name, old, new)
    with pytest.raises(ReferenceTableError):
        for loader in (
            load_nfl_franchises,
            load_nfl_team_crosswalk,
            load_nfl_stadiums,
            load_nfl_networks,
            load_nfl_lead_booth_overrides,
            load_nfl_week_overrides,
        ):
            loader(ref)


def test_crosswalk_overlap_conflict(ref: Path) -> None:
    _append(ref, "nfl_team_crosswalk.csv", "nflverse,OTT,moles,,,")
    with pytest.raises(ReferenceTableError):
        load_nfl_team_crosswalk(ref)


def test_franchise_range_overlap(ref: Path) -> None:
    _append(ref, "nfl_franchises.csv", "gulls,2016,2018,Overlap Gulls,Gulls,")
    with pytest.raises(ReferenceTableError):
        load_nfl_franchises(ref)


def test_duplicate_keys(ref: Path) -> None:
    _append(ref, "nfl_stadiums.csv", "FAKE01,Dup,GB,https://example.com/x,")
    with pytest.raises(ReferenceTableError):
        load_nfl_stadiums(ref)
    _append(
        ref,
        "nfl_week_overrides.csv",
        "2018,5,fox,2018_05_X_Y,https://example.com/a,agotw-text-source",
    )
    with pytest.raises(ReferenceTableError):
        load_nfl_week_overrides(ref)
    _append(
        ref, "nfl_lead_booth_overrides.csv", "2018,fox,bo-fixture,close-call,https://example.com/b"
    )
    with pytest.raises(ReferenceTableError):
        load_nfl_lead_booth_overrides(ref)


def test_error_messages_hide_cell_content(ref: Path) -> None:
    _append(ref, "nfl_networks.csv", "sports506,SECRETVARIANT,badid,")
    with pytest.raises(ReferenceTableError) as exc:
        load_nfl_networks(ref)
    assert "SECRETVARIANT" not in str(exc.value)
    assert "badid" not in str(exc.value)


_OVERRIDE_HEADER = "nflverse_game_id,stadium_id,source_url,note"


def _overrides(ref: Path, *rows: str) -> None:
    (ref / "nfl_stadium_overrides.csv").write_text(
        "\n".join((_OVERRIDE_HEADER, *rows)) + "\n", encoding="utf-8"
    )


def test_stadium_overrides_load_and_missing_table_is_empty(ref: Path) -> None:
    assert load_nfl_stadium_overrides(ref) == {}
    _overrides(ref, "g1,FAKE01,https://example.com/g1,", "g2,FAKE02,https://example.com/g2,x")
    assert load_nfl_stadium_overrides(ref) == {"g1": "FAKE01", "g2": "FAKE02"}


@pytest.mark.parametrize(
    "rows",
    [
        ("g1,NOPE99,https://example.com/g1,",),  # stadium not in nfl_stadiums.csv
        ("g1,FAKE01,https://example.com/a,", "g1,FAKE02,https://example.com/b,"),  # duplicate
        ("g1,FAKE01,http://example.com/g1,",),  # not https
        (",FAKE01,https://example.com/g1,",),  # no game id
    ],
)
def test_stadium_overrides_reject_bad_rows(ref: Path, rows: tuple[str, ...]) -> None:
    _overrides(ref, *rows)
    with pytest.raises(ReferenceTableError) as exc:
        load_nfl_stadium_overrides(ref)
    assert "NOPE99" not in str(exc.value) and "g1" not in str(exc.value)


def _ranks(ref: Path, *rows: str) -> None:
    header = "network,season,rank,pbp,analyst,source_url"
    (ref / "nfl_booth_ranks.csv").write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")


_URL = "https://example.com/lineup"


def test_booth_ranks_load(ref: Path) -> None:
    _ranks(
        ref,
        f"fox,2026,2,Bo Fixture,Ana Fixture,{_URL}",
        f"fox,2026,1,Ana Fixture,Bo Fixture,{_URL}",
    )
    ranks = load_nfl_booth_ranks(ref)[("fox", 2026)]
    assert [(r.rank, r.pbp_person_id, r.analyst_person_id) for r in ranks] == [
        (1, "ana-fixture", "bo-fixture"),
        (2, "bo-fixture", "ana-fixture"),
    ]


def test_booth_ranks_missing_file_is_empty(ref: Path) -> None:
    (ref / "nfl_booth_ranks.csv").unlink()
    assert load_nfl_booth_ranks(ref) == {}


@pytest.mark.parametrize(
    "rows",
    [
        [f"espn,2026,1,Ana Fixture,Bo Fixture,{_URL}"],
        ["fox,2026,1,Ana Fixture,Bo Fixture,http://example.com/x"],
        [f"fox,2026,1,Ana Fixture,Bo Fixture,{_URL}", f"fox,2026,1,Bo Fixture,Ana Fixture,{_URL}"],
        [f"fox,2026,1,Ana Fixture,Bo Fixture,{_URL}", f"fox,2026,3,Bo Fixture,Ana Fixture,{_URL}"],
        [f"fox,2026,1,Ana Fixture,Bo Fixture,{_URL}", f"fox,2026,2,Ana Fixture,Bo Fixture,{_URL}"],
    ],
)
def test_booth_ranks_rejections(ref: Path, rows: list[str]) -> None:
    _ranks(ref, *rows)
    with pytest.raises(ReferenceTableError):
        load_nfl_booth_ranks(ref)


def test_booth_ranks_unresolved_name_hides_name(ref: Path) -> None:
    _ranks(ref, f"fox,2026,1,Zed Nobody,Bo Fixture,{_URL}")
    with pytest.raises(ReferenceTableError) as exc:
        load_nfl_booth_ranks(ref)
    assert "line 2" in str(exc.value)
    assert "Nobody" not in str(exc.value)


def test_override_network_must_be_group_id(ref: Path) -> None:
    _rewrite(ref, "nfl_lead_booth_overrides.csv", "2018,fox,", "2018,espn,")
    with pytest.raises(ReferenceTableError):
        load_nfl_lead_booth_overrides(ref)


def test_override_header_only_is_empty(ref: Path) -> None:
    (ref / "nfl_lead_booth_overrides.csv").write_text(
        "season,network_id,person_id,reason,source_url\n", encoding="utf-8"
    )
    assert load_nfl_lead_booth_overrides(ref) == {}
