"""Wikipedia scheduling-change match on synthetic data."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from nfl_join_helpers import games

from booth_review.nfl.changes import match_schedule_changes
from booth_review.nfl.inputs import NflInputs
from booth_review.nfl.layout import wikipedia_url
from booth_review.nfl.teams import NflNetworkResolver, NflTeamResolver
from booth_review.sources.wikipedia.parser import ChangesResult, ScheduleChange, UnparsedChange

FIXTURE = Path(__file__).parent / "fixtures" / "nfl" / "reference"


@pytest.fixture
def ref(tmp_path: Path) -> Path:
    dest = tmp_path / "ref"
    shutil.copytree(FIXTURE, dest)
    return dest


def change(a: str, b: str, week: int = 5, **over: object) -> ScheduleChange:
    base: dict[str, object] = {
        "season": 2015,
        "week": week,
        "team_a_raw": a,
        "team_b_raw": b,
        "original_day": "Sunday",
        "original_time_et": "13:00",
        "original_network_raw": "Fox",
        "new_network_raw": "Amazon Prime Video",
        "new_slot_hint": None,
        "raw_text_hash": f"h-{a}-{b}-{week}",
    }
    base.update(over)
    return ScheduleChange(**base)  # type: ignore[arg-type]


def run(ref: Path, changes: list[ScheduleChange], unparsed=()):
    result = ChangesResult(tuple(changes), tuple(unparsed), 0, True)
    inputs = NflInputs(
        games=games(),
        listings={},
        listing_parse_failures=0,
        rr_records={},
        changes={2015: result},
        pbp_paths={},
    )
    return match_schedule_changes(
        inputs, NflTeamResolver.from_reference_dir(ref), NflNetworkResolver.from_reference_dir(ref)
    )


def test_flex_to_monday_derives_original_sunday_slot(ref: Path) -> None:
    # g4 is Monday 2015-10-12 (week 5); original day Sunday at 1pm -> Sunday early
    matched, reviews = run(ref, [change("Hill Moles", "Otters", original_day="Sunday")])
    assert reviews == []
    got = matched["g4"]
    assert got.original_slot == "Sunday early"
    assert got.original_network_id == "fox"
    assert got.new_network_id == "prime"
    assert got.original_time_et == "13:00"
    assert got.article_url == wikipedia_url(2015)


def test_no_stated_day_uses_game_date(ref: Path) -> None:
    matched, _ = run(ref, [change("Hill Moles", "Otters", original_day=None)])
    assert matched["g4"].original_slot == "MNF"


def test_missing_time_and_network(ref: Path) -> None:
    matched, _ = run(
        ref,
        [
            change(
                "Hill Moles",
                "Otters",
                original_time_et=None,
                original_network_raw=None,
                new_network_raw=None,
            )
        ],
    )
    got = matched["g4"]
    assert got.original_slot is None
    assert got.original_network_id is None
    assert got.new_network_id is None


def test_misses_go_to_review(ref: Path) -> None:
    matched, reviews = run(
        ref,
        [change("Hill Moles", "Otters", week=9), change("Nobody", "Hill Moles")],
        unparsed=[UnparsedChange(2015, 4, "uh", "text")],
    )
    assert matched == {}
    assert sorted(r.reason for r in reviews) == ["no-game", "unparsed", "unresolved-team"]


def test_multiple_changes_keep_first(ref: Path) -> None:
    matched, reviews = run(
        ref,
        [
            change("Hill Moles", "Otters", original_time_et="13:00", raw_text_hash="first"),
            change("Otters", "Hill Moles", original_time_et="16:25", raw_text_hash="second"),
        ],
    )
    assert matched["g4"].raw_text_hash == "first"
    assert [(r.raw_text_hash, r.reason) for r in reviews] == [("second", "multiple-changes")]
