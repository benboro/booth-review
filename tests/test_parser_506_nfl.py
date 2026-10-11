"""Tests for the 506 Sports NFL week-page parser.

All fixtures under tests/fixtures/nfl/sports506/ are synthetic: invented teams
and people that copy only the real pages' HTML structure.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from booth_review.errors import ParseError
from booth_review.sources.sports506.nfl_parser import (
    NflListing506,
    nfl_smoke_check,
    parse_nfl_week_page,
)

FIXTURES = Path(__file__).parent / "fixtures" / "nfl" / "sports506"
CFB_FIXTURES = Path(__file__).parent / "fixtures" / "sports506"


def _load(name: str, season: int, week: int) -> list[NflListing506]:
    return parse_nfl_week_page((FIXTURES / name).read_bytes(), season=season, week=week)


def _l2014() -> list[NflListing506]:
    return _load("nfl_2014_wk03_synthetic.html", 2014, 3)


def _l2016() -> list[NflListing506]:
    return _load("nfl_2016_wk05_synthetic.html", 2016, 5)


def _l2025() -> list[NflListing506]:
    return _load("nfl_2025_wk10_synthetic.html", 2025, 10)


def test_2014_table_layout_networks_and_windows() -> None:
    listings = _l2014()
    assert len(listings) == 11
    assert [(x.network_raw, x.window) for x in listings[:1]] == [("CBS", "early")]
    assert {(x.network_raw, x.window) for x in listings} == {
        ("CBS", "early"),
        ("FOX", "late"),
        ("FOX", "single"),
    }
    assert not any(x.is_national_line for x in listings)


def test_2014_crew_order_and_region_bracket_stripped() -> None:
    first = _l2014()[0]
    assert first.away_raw == "Harbor City Gulls"
    assert first.home_raw == "Pine Ridge Miners"
    assert first.crew_names == ("Pat Example", "Sam Sample")
    for listing in _l2014():
        for name in listing.crew_names:
            assert "[" not in name
            assert "AK" not in name


def test_three_person_crew_keeps_order() -> None:
    second = _l2014()[1]
    assert second.crew_names == ("Lee Placeholder", "Kim Invented", "Jo Imaginary")


def test_trailing_note_and_intl_city_never_leak_into_team() -> None:
    listings = _l2014()
    assert listings[2].home_raw == "Stone Harbor Wolves"
    neutral = listings[3]
    assert neutral.neutral_site is True
    assert neutral.home_raw == "Oak Valley Hawks"
    assert neutral.intl_city == "Testville"
    assert listings[0].neutral_site is False
    assert listings[0].intl_city is None


def test_no_game_rows_are_skipped() -> None:
    for listing in _l2014() + _l2016() + _l2025():
        assert "NO GAME" not in listing.away_raw + listing.home_raw


def test_2016_national_block_listings() -> None:
    national = [x for x in _l2016() if x.is_national_line]
    assert [x.network_raw for x in national] == ["NBC", "NBC", "ESPN"]
    assert all(x.window == "national" for x in national)
    assert all(x.crew_names == () for x in national)
    assert national[0].away_raw == "Coral Bay Pelicans"
    assert national[0].home_raw == "Timber Mill Jacks"


def test_2016_regional_windows_and_crew() -> None:
    regional = [x for x in _l2016() if not x.is_national_line]
    assert len(regional) == 10
    assert regional[0].network_raw == "CBS"
    assert regional[0].window == "single"
    assert regional[0].crew_names == ("Pat Example", "Sam Sample")
    assert regional[-1].window == "late"


def test_2025_div_layout_skips_nogame_and_updates() -> None:
    regional = [x for x in _l2025() if not x.is_national_line]
    assert len(regional) == 10
    assert regional[0].home_raw == "Pine Ridge Miners"
    assert regional[0].crew_names == ("Pat Example", "Sam Sample")
    assert regional[2].home_raw == "Stone Harbor Wolves"
    texts = " ".join(x.away_raw + x.home_raw for x in _l2025())
    assert "QVT" not in texts
    assert "Pine Ridge: PR" not in texts


def test_2025_national_lines_network_crew_and_intl() -> None:
    national = [x for x in _l2025() if x.is_national_line]
    assert [x.network_raw for x in national] == ["Amazon", "NFLN", "NBC", "ESPN/ABC"]
    intl = national[1]
    assert intl.intl_city == "Testville"
    assert intl.neutral_site is True
    assert intl.home_raw == "Frost Hollow Elk"
    assert intl.crew_names == ("Pat Example", "Sam Sample")
    assert national[3].crew_names == ()
    assert national[3].home_raw == "Slate Run Lions"


def test_source_row_index_monotonic_and_stable() -> None:
    for loader in (_l2014, _l2016, _l2025):
        first = loader()
        indexes = [x.source_row_index for x in first]
        assert indexes == sorted(set(indexes))
        assert indexes == [x.source_row_index for x in loader()]


def test_listing_carries_season_and_week() -> None:
    assert {(x.season, x.week) for x in _l2025()} == {(2025, 10)}


def test_window_header_variants_do_not_crash() -> None:
    html = (
        b"<html><body><article>"
        b'<p><b><font size="5">WEEK 18 GAMES</font></b></p>'
        b"<table><tr><td></td><td><strong>A Team @ B Team</strong> -- Pat Example</td></tr></table>"
        b'<p><b><font size="5">FOX (LATE)</font></b></p>'
        b"<table><tr><td></td><td><strong>C Team @ D Team</strong> -- Sam Sample</td></tr></table>"
        b"</article></body></html>"
    )
    listings = parse_nfl_week_page(html, season=2025, week=18)
    assert [x.window for x in listings] == ["other", "late"]
    assert listings[0].network_raw == ""
    assert listings[1].network_raw == "FOX"


def test_smoke_check_passes_with_crewless_national_lines() -> None:
    html = (FIXTURES / "nfl_2016_wk05_synthetic.html").read_bytes()
    result = nfl_smoke_check(html, season=2016, week=5)
    assert result.passed
    assert result.games == 13
    assert result.regional == 10
    assert result.regional_with_crew == 10
    assert result.reason is None


def test_smoke_check_uses_expected_games() -> None:
    html = (FIXTURES / "nfl_2016_wk05_synthetic.html").read_bytes()
    result = nfl_smoke_check(html, season=2016, week=5, expected_games=16)
    assert not result.passed
    assert result.reason is not None


def test_smoke_check_fails_low_regional_crew_share() -> None:
    rows = "".join(
        f"<tr><td></td><td><strong>T{i} Team @ U{i} Team</strong> -- </td></tr>" for i in range(10)
    )
    html = (
        '<html><body><article><p><b><font size="5">CBS EARLY</font></b></p>'
        f"<table>{rows}</table></article></body></html>"
    ).encode()
    result = nfl_smoke_check(html, season=2014, week=1)
    assert not result.passed
    assert result.regional_with_crew == 0


def test_smoke_check_never_raises() -> None:
    result = nfl_smoke_check(b"", season=2014, week=1)
    assert not result.passed
    assert result.reason is not None


def test_cfb_page_raises_print_safe_parse_error() -> None:
    html = (CFB_FIXTURES / "week_synthetic.html").read_bytes()
    with pytest.raises(ParseError) as excinfo:
        parse_nfl_week_page(html, season=2025, week=5)
    message = str(excinfo.value)
    assert "season 2025" in message
    assert "week 5" in message
    assert "Northfield" not in message
    assert "<" not in message


def test_empty_body_raises_parse_error() -> None:
    with pytest.raises(ParseError, match="season 2014 week 1"):
        parse_nfl_week_page(b"", season=2014, week=1)


def test_three_cell_row_reads_crew_from_next_cell() -> None:
    html = (
        b"<html><body><article>"
        b'<p><b><font size="5">CBS SINGLE</font></b></p>'
        b"<table><tr><td></td><td><strong>A Team @ B Team</strong></td>"
        b"<td>Pat Example, Sam Sample</td></tr></table>"
        b"</article></body></html>"
    )
    (listing,) = parse_nfl_week_page(html, season=2017, week=10)
    assert listing.crew_names == ("Pat Example", "Sam Sample")
    assert listing.network_raw == "CBS"


def test_bold_network_inside_national_line_is_not_a_window_header() -> None:
    html = (
        b"<html><body><article>"
        b"<b><font size='5'>NATIONAL BROADCASTS</font></b><br/>"
        b"<li><b>Sunday 1:00 ET:</b> A Team @ B Team (<b>NFLN</b>)<br/>"
        b"Pat Example, Sam Sample<br/><font size='2'>local stations</font></li>"
        b"<li><b>Monday Night:</b> C Team @ D Team (<b>ESPN</b>)</li>"
        b'<p><b><font size="5">FOX EARLY</font></b></p>'
        b"<table><tr><td></td><td><strong>E Team @ F Team</strong> -- Sam Sample</td></tr></table>"
        b"</article></body></html>"
    )
    listings = parse_nfl_week_page(html, season=2022, week=15)
    assert [(x.network_raw, x.is_national_line) for x in listings] == [
        ("NFLN", True),
        ("ESPN", True),
        ("FOX", False),
    ]
    assert listings[0].crew_names == ("Pat Example", "Sam Sample")


def test_header_nested_in_unclosed_national_item_still_resets_window() -> None:
    html = (
        b"<html><body><article>"
        b"<b><font size='5'>NATIONAL BROADCASTS</font></b><br/>"
        b"<li><b>Monday Night:</b> C Team @ D Team (ESPN)<br/>"
        b'<p><b><font size="5">CBS EARLY</font></b></p>'
        b'<div id="game"><div id="matchup">E Team @ F Team</div>'
        b'<div id="anncrs">Pat Example, Sam Sample</div></div>'
        b"</article></body></html>"
    )
    listings = parse_nfl_week_page(html, season=2022, week=1)
    assert [(x.network_raw, x.window, x.is_national_line) for x in listings] == [
        ("ESPN", "national", True),
        ("CBS", "early", False),
    ]
