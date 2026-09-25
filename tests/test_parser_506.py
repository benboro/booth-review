"""Tests for the 506 Sports week-page parser.

All fixtures under tests/fixtures/sports506/ are synthetic: invented teams,
people, and networks that copy only the real pages' HTML structure, never a
real 506 row (D-07). Real cached 2025 pages are used only by the module-level
smoke check in the plan's own verification command, never by these tests.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from booth_review.errors import ParseError
from booth_review.sources.sports506.parser import Listing506, parse_week_page

FIXTURES = Path(__file__).parent / "fixtures" / "sports506"
_EASTERN = ZoneInfo("America/New_York")


def _week_listings() -> list[Listing506]:
    html = (FIXTURES / "week_synthetic.html").read_bytes()
    return parse_week_page(html, season=2025, week_label="5")


def _bowl_listings() -> list[Listing506]:
    html = (FIXTURES / "bowls_synthetic.html").read_bytes()
    return parse_week_page(html, season=2025, week_label="B")


def test_parse_week_page_returns_one_listing_per_row_in_page_order() -> None:
    listings = _week_listings()
    assert len(listings) == 4
    assert [listing.source_row_index for listing in listings] == [0, 1, 2, 3]


def test_ranked_home_game_splits_rank_and_leaves_neutral_false() -> None:
    listing = _week_listings()[0]
    assert listing.away_raw == "Northfield State"
    assert listing.away_rank == 12
    assert listing.home_raw == "Lakeshore Tech"
    assert listing.home_rank is None
    assert listing.neutral is False


def test_vs_row_is_neutral() -> None:
    listing = _week_listings()[1]
    assert listing.away_raw == "Riverside Poly"
    assert listing.home_raw == "Granite College"
    assert listing.neutral is True


def test_kickoff_et_is_aware_eastern_datetime_on_the_listed_date() -> None:
    listing = _week_listings()[0]
    assert listing.date_et == date(2025, 9, 25)
    assert listing.kickoff_et is not None
    assert listing.kickoff_et.tzinfo == _EASTERN
    assert listing.kickoff_et.hour == 19
    assert listing.kickoff_et.minute == 30
    assert listing.kickoff_et.date() == date(2025, 9, 25)


def test_tba_time_gives_none_kickoff_but_keeps_date() -> None:
    listing = _week_listings()[1]
    assert listing.kickoff_et is None
    assert listing.date_et == date(2025, 9, 25)


def test_crew_raw_and_crew_names_split_on_delimiter() -> None:
    listing = _week_listings()[0]
    assert listing.crew_raw == "Pat Example, Jordan Sample"
    assert listing.crew_names == ("Pat Example", "Jordan Sample")


def test_row_with_no_crew_gives_none_and_empty_tuple() -> None:
    listing = _week_listings()[1]
    assert listing.crew_raw is None
    assert listing.crew_names == ()


def test_three_person_crew_and_alt_cast_feed_kind() -> None:
    listing = _week_listings()[2]
    assert listing.crew_names == ("Taylor Case", "Morgan Field", "Casey Vale")
    assert listing.feed_kind == "alt"


def test_ordinary_row_gets_main_feed_kind() -> None:
    listing = _week_listings()[0]
    assert listing.feed_kind == "main"


def test_missing_network_gives_unknown_feed_kind() -> None:
    listing = _week_listings()[3]
    assert listing.network_raw is None
    assert listing.feed_kind == "unknown"


def test_name_suffix_is_preserved_in_crew_names() -> None:
    listing = _week_listings()[3]
    assert "Drew Case Jr." in listing.crew_names


def test_bowls_fixture_keeps_game_label() -> None:
    listings = _bowl_listings()
    assert listings[0].game_label == "Frostbite Bowl"
    assert listings[1].game_label == "Frontier Bowl (CFP Quarterfinal)"


def test_bowls_fixture_ranked_neutral_row() -> None:
    listing = _bowl_listings()[1]
    assert listing.away_raw == "Prairie State"
    assert listing.away_rank == 4
    # The trailing "(in <city>)" location suffix that 506 writes into the
    # home team's own text is kept verbatim, per the plan's structural-only
    # cleanup rule (rank split, whitespace collapse, crew split — nothing
    # else touches a team name).
    assert listing.home_raw == "Union City (in Example City)"
    assert listing.home_rank == 1
    assert listing.neutral is True


def test_bowls_fixture_rolls_the_year_over_from_december_to_january() -> None:
    listings = _bowl_listings()
    december_row = listings[0]
    january_row = listings[1]
    assert december_row.date_et == date(2025, 12, 16)
    assert january_row.date_et == date(2026, 1, 1)


def test_bowls_fixture_drops_row_with_no_teams_named_yet() -> None:
    listings = _bowl_listings()
    # The fixture's third <div id="cgame"> (a championship placeholder with
    # no matchup text yet) must never surface as a listing with empty teams.
    assert len(listings) == 2
    for listing in listings:
        assert listing.away_raw
        assert listing.home_raw


def test_empty_bytes_raises_parse_error() -> None:
    with pytest.raises(ParseError):
        parse_week_page(b"", season=2025, week_label="5")


def test_html_with_no_schedule_table_raises_parse_error() -> None:
    html = b"<html><body><p>not a schedule page</p></body></html>"
    with pytest.raises(ParseError):
        parse_week_page(html, season=2025, week_label="5")
