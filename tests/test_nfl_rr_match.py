"""Ratings Reference NFL record match on synthetic data."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest
from nfl_join_helpers import games

from booth_review.nfl.inputs import NflInputs
from booth_review.nfl.rr_match import match_rr_records
from booth_review.nfl.teams import NflNetworkResolver, NflTeamResolver
from booth_review.sources.ratingsref.parser import RRRecord

FIXTURE = Path(__file__).parent / "fixtures" / "nfl" / "reference"


@pytest.fixture
def ref(tmp_path: Path) -> Path:
    dest = tmp_path / "ref"
    shutil.copytree(FIXTURE, dest)
    return dest


def record(slug: str, day: str, *, teams=(), networks=(), claims=()) -> RRRecord:
    return RRRecord.model_validate(
        {
            "telecast": {
                "id": slug,
                "event_date": day,
                "teams": list(teams),
                "networks": list(networks),
                "title": "Invented title",
            },
            "claims": list(claims),
        }
    )


CLAIM = {
    "id": "c1",
    "metric_type": "avg_audience",
    "status": "final",
    "value": 5_000_000,
    "unit": "viewers",
    "cut": "total",
    "era_id": "rr-era-b",
    "measured_by": "Fixture Panel",
    "source_url": "https://example.com/figure",
}


def run(ref: Path, records: list[RRRecord]):
    inputs = NflInputs(
        games=games(),
        listings={},
        listing_parse_failures=0,
        rr_records={2015: tuple(records)},
        changes={},
        pbp_paths={},
    )
    return match_rr_records(
        inputs,
        NflTeamResolver.from_reference_dir(ref),
        NflNetworkResolver.from_reference_dir(ref),
    )


def test_same_date_slug_match_with_headline(ref: Path) -> None:
    rec = record(
        "nfl-moles-otters-2015-10-12", "2015-10-12", networks=["NFL Network"], claims=[CLAIM]
    )
    matches, reviews = run(ref, [rec])
    assert reviews == []
    (m,) = matches["g4"]
    assert m.tier == "date"
    assert m.record_url.endswith("nfl-moles-otters-2015-10-12")
    assert m.network_ids == ("nfln",)
    assert (m.headline_value, m.headline_cut, m.headline_status) == (5_000_000, "total", "final")
    assert m.headline_source_url == "https://example.com/figure"
    assert m.headline_era_id == "rr-era-b"
    assert m.headline_measured_by == "Fixture Panel"


def test_teams_field_beats_slug(ref: Path) -> None:
    rec = record("nfl-weird-slug-2015-09-27", "2015-09-27", teams=["Harbor City Gulls", "Otters"])
    matches, _ = run(ref, [rec])
    assert "g1" in matches


def test_teams_field_league_prefixed_ids_resolve(ref: Path) -> None:
    # Real RR records list teams as league-prefixed ids ("nfl-<team>"), like CFB's "cfb-".
    rec = record("nfl-weird-slug-2015-10-12", "2015-10-12", teams=["nfl-moles", "nfl-otters"])
    matches, reviews = run(ref, [rec])
    assert reviews == []
    assert "g4" in matches


def test_event_word_slug(ref: Path) -> None:
    rec = record("nfl-kickoff-moles-otters-2015-10-12", "2015-10-12")
    matches, _ = run(ref, [rec])
    assert "g4" in matches


def test_date_shift_within_week_collapses_to_earlier_game(ref: Path) -> None:
    # Tuesday record of the Monday game
    rec = record("nfl-moles-otters-2015-10-13", "2015-10-13")
    matches, reviews = run(ref, [rec])
    assert reviews == []
    assert matches["g4"][0].tier == "date-shift"
    assert matches["g4"][0].event_date == date(2015, 10, 13)


def test_shift_does_not_cross_into_next_game(ref: Path) -> None:
    # Gulls/otters play weeks 3 and 4; a record 4 days after week 4 is not a shift.
    rec = record("x-2015-10-08", "2015-10-08", teams=["Harbor City Gulls", "Otters"])
    matches, reviews = run(ref, [rec])
    assert matches == {}
    assert [r.reason for r in reviews] == ["no-game"]


def test_unresolved_and_unmatched_reviews(ref: Path) -> None:
    recs = [
        record("nfl-unknown-things-2015-09-27", "2015-09-27"),
        record("nfl-moles-otters-2015-11-01", "2015-11-01"),
    ]
    matches, reviews = run(ref, recs)
    assert matches == {}
    assert [r.reason for r in reviews] == ["unresolved-team", "no-game"]
