"""NFL input loader and 506 listing match on synthetic data."""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest
from nfl_join_helpers import games, listing, sched_row, schedule_csv

from booth_review.config import DataPaths
from booth_review.errors import VaultStateError
from booth_review.nfl.inputs import NflInputs, load_nfl_inputs
from booth_review.nfl.layout import NFLVERSE_SCHEDULES_PATH, nfl_506_path, nfl_rr_path
from booth_review.nfl.listings import match_506_listings
from booth_review.nfl.teams import NflNetworkResolver, NflTeamResolver
from booth_review.sources.sports506.nfl_parser import NflListing506

FIXTURE = Path(__file__).parent / "fixtures" / "nfl" / "reference"


@pytest.fixture(scope="module")
def ref(tmp_path_factory: pytest.TempPathFactory) -> Path:
    dest = tmp_path_factory.mktemp("ref") / "ref"
    shutil.copytree(FIXTURE, dest)
    return dest


def inputs_with(listings: list[NflListing506]) -> NflInputs:
    by_week: dict[tuple[int, int], tuple[NflListing506, ...]] = {}
    for item in listings:
        by_week[(item.season, item.week)] = (*by_week.get((item.season, item.week), ()), item)
    return NflInputs(
        games=games(),
        listings=by_week,
        listing_parse_failures=0,
        rr_records={},
        changes={},
        pbp_paths={},
    )


def resolvers(ref: Path) -> tuple[NflTeamResolver, NflNetworkResolver]:
    return NflTeamResolver.from_reference_dir(ref), NflNetworkResolver.from_reference_dir(ref)


def test_match_pair_unordered_and_crew(ref: Path) -> None:
    teams, nets = resolvers(ref)
    # listed home-first relative to nflverse: unordered pair still matches
    inputs = inputs_with([listing("Otters", "Gulls", crew=["Pat Example", "Lee Sample"])])
    matches, reviews = match_506_listings(inputs, teams, nets)
    assert reviews == []
    match = matches["g1"]
    assert match.network_id == "fox"
    assert match.window == "early"
    assert match.crew_names == ("Pat Example", "Lee Sample")


def test_unmatched_and_unresolved_go_to_review(ref: Path) -> None:
    teams, nets = resolvers(ref)
    inputs = inputs_with(
        [
            listing("Moles", "Pine Elks", idx=1, week=9),  # no game that week
            listing("Nonexistent Team", "Gulls", idx=2),
        ]
    )
    matches, reviews = match_506_listings(inputs, teams, nets)
    assert matches == {}
    assert {(r.source_row_index, r.reason) for r in reviews} == {
        (1, "no-game"),
        (2, "unresolved-team"),
    }


def test_conflicting_networks_leave_network_none(ref: Path) -> None:
    teams, nets = resolvers(ref)
    inputs = inputs_with(
        [listing("Gulls", "Otters", "FOX", idx=1), listing("Gulls", "Otters", "CBS", idx=2)]
    )
    matches, reviews = match_506_listings(inputs, teams, nets)
    assert matches["g1"].network_id is None
    assert [r.reason for r in reviews] == ["conflict", "conflict"]


def test_same_network_duplicates_merge_crew(ref: Path) -> None:
    teams, nets = resolvers(ref)
    inputs = inputs_with(
        [listing("Gulls", "Otters", idx=1), listing("Gulls", "Otters", idx=2, crew=["Pat Example"])]
    )
    matches, reviews = match_506_listings(inputs, teams, nets)
    assert reviews == []
    assert matches["g1"].crew_names == ("Pat Example",)


def _vault(tmp_path: Path) -> DataPaths:
    paths = DataPaths(vault=tmp_path / "vault")
    sched = paths.raw / NFLVERSE_SCHEDULES_PATH
    sched.parent.mkdir(parents=True)
    sched.write_bytes(schedule_csv([sched_row("g1", 3, "2015-09-27", "HCG", "OTT")]))
    return paths


def test_loader_reads_only_nfl_namespace(tmp_path: Path) -> None:
    paths = _vault(tmp_path)
    page = paths.raw / nfl_506_path(2015, 3)
    page.parent.mkdir(parents=True)
    page.write_bytes(b"<html>not a page</html>")  # unparsable: counted, not fatal
    rr = paths.raw / nfl_rr_path(2015, "nfl-x")
    rr.parent.mkdir(parents=True)
    rr.write_bytes(json.dumps({"telecast": {"id": "nfl-x", "event_date": "2015-09-27"}}).encode())
    cfb = paths.raw / "ratingsref" / "telecast" / "2015" / "cfb-a-b-2015-09-05.json"
    cfb.parent.mkdir(parents=True)
    cfb.write_bytes(json.dumps({"telecast": {"id": "cfb-a", "event_date": "2015-09-05"}}).encode())
    loaded = load_nfl_inputs(paths, [2015])
    assert len(loaded.games) == 1
    assert loaded.listing_parse_failures == 1
    assert [r.telecast.id for r in loaded.rr_records[2015]] == ["nfl-x"]
    assert loaded.changes == {}
    assert loaded.games[0].gameday == date(2015, 9, 27)


def test_loader_requires_schedule(tmp_path: Path) -> None:
    with pytest.raises(VaultStateError):
        load_nfl_inputs(DataPaths(vault=tmp_path / "vault"), [2015])
