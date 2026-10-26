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
    names_nfl_week_page,
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


def _l2026() -> list[NflListing506]:
    return _load("nfl_2026_wk04_synthetic.html", 2026, 4)


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
    for loader in (_l2014, _l2016, _l2025, _l2026):
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


def test_italic_city_on_national_line_in_every_shape() -> None:
    # Real pages italicize the host city as "in City", "(City)" or "(in City)".
    html = (
        b"<html><body><article>"
        b"<b><font size='5'>NATIONAL BROADCASTS</font></b><br/>"
        b"<li><b>Sunday Morning:</b> A Team vs B Team <i>in Testville</i> "
        b"(NFLN; Pat Example, Sam Sample)</li>"
        b"<li><b>Sunday Morning:</b> C Team vs D Team <i>(New Testville)</i> "
        b"(9:30 AM ET, CBS) (Pat Example, Sam Sample)</li>"
        b"<li><b>Sunday Morning:</b> E Team vs F Team <i>(in Testville)</i> (FOX) "
        b"(Sam Sample)</li>"
        b"<li><b>Sunday Night:</b> G Team @ H Team <i>(NFLN)</i></li>"
        b"</article></body></html>"
    )
    listings = parse_nfl_week_page(html, season=2023, week=5)
    assert [(x.away_raw, x.home_raw, x.intl_city, x.network_raw) for x in listings] == [
        ("A Team", "B Team", "Testville", "NFLN"),
        ("C Team", "D Team", "New Testville", "CBS"),
        ("E Team", "F Team", "Testville", "FOX"),
        ("G Team", "H Team", None, "NFLN"),
    ]
    assert listings[0].crew_names == ("Pat Example", "Sam Sample")
    assert listings[1].crew_names == ("Pat Example", "Sam Sample")
    assert listings[1].national_time_et_raw == "9:30 AM ET"


def test_simulcast_second_network_is_not_crew() -> None:
    html = (
        b"<html><body><article>"
        b"<b><font size='5'>NATIONAL BROADCASTS</font></b><br/>"
        b"<li><b>Thursday Night:</b> A Team @ B Team (CBS; NFLN)</li>"
        b"<li><b>Thursday Night:</b> C Team @ D Team (NBC; NFLN; Pat Example, Sam Sample)</li>"
        b"</article></body></html>"
    )
    listings = parse_nfl_week_page(html, season=2016, week=2)
    assert [(x.network_raw, x.crew_names) for x in listings] == [
        ("CBS", ()),
        ("NBC", ("Pat Example", "Sam Sample")),
    ]


def test_unclosed_national_item_never_takes_the_next_header_as_crew() -> None:
    # The closing </li> sits inside a comment, so the item swallows the next window header.
    html = (
        b"<html><body><article>"
        b"<b><font size='5'>NATIONAL BROADCASTS</font></b><br/>"
        b"<li><b>Monday Night:</b> C Team @ D Team (ESPN/ABC)<!--<font>notes</font></li>-->"
        b"<hr/><br/><br/>"
        b'<p><b><font size="5">CBS EARLY</font></b></p><br/>'
        b'<div id="game"><div id="matchup">E Team @ F Team</div>'
        b'<div id="anncrs">Pat Example, Sam Sample</div></div>'
        b"</article></body></html>"
    )
    listings = parse_nfl_week_page(html, season=2022, week=1)
    assert [(x.network_raw, x.crew_names) for x in listings] == [
        ("ESPN/ABC", ()),
        ("CBS", ("Pat Example", "Sam Sample")),
    ]


_NFL_HEAD = (
    '<link rel="canonical" href="https://506sports.com/nfl.php?yr=2026&wk=6">'
    "<title>506 Sports - NFL Maps: Week 6, 2026</title>"
)


def _page(body: str, head: str = _NFL_HEAD) -> bytes:
    return (
        f'<!DOCTYPE html><html><head><meta charset="utf-8">{head}</head>'
        f"<body><article>{body}</article></body></html>"
    ).encode()


def _card(matchup: str, time: str, network: str, crew: str) -> str:
    return (
        f'<div id="cgame"><div id="cmatchup">{matchup}</div><div id="ctime">{time}</div>'
        f'<div id="cntwk">{network}</div><div id="canncrs">{crew}</div></div>'
    )


def _game(matchup: str, crew: str) -> str:
    return f'<div id="game"><div id="matchup">{matchup}</div><div id="anncrs">{crew}</div></div>'


def test_2026_cards_are_national_lines_with_network_time_and_crew() -> None:
    national = [x for x in _l2026() if x.is_national_line]
    assert [x.network_raw for x in national] == ["Prime Video", "NFLN", "NBC", "ESPN/ABC"]
    assert {x.window for x in national} == {"national"}
    assert [x.national_time_et_raw for x in national] == [
        "8:00 ET",
        "9:30 AM ET",
        "8:00 ET",
        "8:00 ET",
    ]
    assert national[0].away_raw == "Coral Bay Pelicans"
    assert national[0].home_raw == "Timber Mill Jacks"
    assert national[0].neutral_site is False


def test_2026_card_crew_drops_affiliate_line() -> None:
    national = [x for x in _l2026() if x.is_national_line]
    assert national[0].crew_names == ("Pat Example", "Sam Sample")
    assert national[1].crew_names == ("Lee Placeholder", "Kim Invented", "Jo Imaginary")
    names = " ".join(n for x in _l2026() for n in x.crew_names)
    assert "also" not in names
    assert "WXXX" not in names


def test_2026_card_intl_city_never_leaks_into_team() -> None:
    intl = [x for x in _l2026() if x.is_national_line][1]
    assert intl.intl_city == "Testville"
    assert intl.neutral_site is True
    assert intl.away_raw == "Dune Rock Camels"
    assert intl.home_raw == "Frost Hollow Elk"


def test_2026_regional_games_keep_window_headers() -> None:
    regional = [x for x in _l2026() if not x.is_national_line]
    assert [(x.network_raw, x.window) for x in regional] == [("CBS", "early")] * 2 + [
        ("FOX", "late")
    ] * 4
    assert regional[0].crew_names == ("Morgan Dummy", "Casey Faux")


def test_2026_card_page_passes_smoke_check() -> None:
    html = (FIXTURES / "nfl_2026_wk04_synthetic.html").read_bytes()
    result = nfl_smoke_check(html, season=2026, week=4)
    assert result.passed, result.reason
    assert (result.games, result.regional, result.regional_with_crew) == (10, 6, 6)


def test_mixed_page_reads_cards_li_lines_and_regional_rows_in_order() -> None:
    body = (
        '<b><font size="5">NATIONAL BROADCASTS</font></b><br/>'
        "<li><b>Thursday Night:</b> Glen Rock Lynx @ Fort Lantern Kings (NBC)</li>"
        + _card("Red Cliff Stags @ Bay Point Marlins", "Sun 8:00 ET", "NBC", "Ann Fiction, Bo Stub")
        + '<p><b><font size="5">FOX SINGLE</font></b></p>'
        + _game("Iron Ridge Bears @ Clearwater Pilots", "Cy Madeup, Di Notreal")
        + _card("Salt Flat Badgers @ Ember Hill Drakes", "Mon 8:15 ET", "ESPN", "Ed Faux, Flo Mock")
        + _game("Sunset Pass Vipers @ Granite Peak Bisons", "Gus Sample, Hal Example")
    )
    listings = parse_nfl_week_page(_page(body), season=2026, week=6)
    assert [(x.home_raw, x.is_national_line, x.network_raw, x.window) for x in listings] == [
        ("Fort Lantern Kings", True, "NBC", "national"),
        ("Bay Point Marlins", True, "NBC", "national"),
        ("Clearwater Pilots", False, "FOX", "single"),
        ("Ember Hill Drakes", True, "ESPN", "national"),
        # A card never changes the window header the regional rows sit under.
        ("Granite Peak Bisons", False, "FOX", "single"),
    ]
    assert [x.source_row_index for x in listings] == [0, 1, 2, 3, 4]


def test_card_without_readable_matchup_is_skipped() -> None:
    body = _card("Crews to be announced", "Sun 1:00 ET", "CBS", "") + _game(
        "Iron Ridge Bears @ Clearwater Pilots", "Cy Madeup, Di Notreal"
    )
    listings = parse_nfl_week_page(_page(body), season=2026, week=6)
    assert [x.home_raw for x in listings] == ["Clearwater Pilots"]


def test_card_with_tba_time_and_no_crew() -> None:
    body = _card("Red Cliff Stags @ Bay Point Marlins", "Sun TBA", "NBC", "")
    (listing,) = parse_nfl_week_page(_page(body), season=2026, week=6)
    assert listing.national_time_et_raw is None
    assert listing.crew_names == ()


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (_NFL_HEAD, True),
        ("<title>506 Sports - NFL Maps: Week 6, 2026</title>", True),
        ('<link rel="canonical" href="https://506sports.com/ncaaf.php?yr=2026&wk=6">', False),
        (
            '<link rel="canonical" href="https://506sports.com/ncaaf.php?yr=2026&wk=6">'
            "<title>506 Sports - NFL Maps: Week 6, 2026</title>",
            False,
        ),
        ('<link rel="canonical" href="https://506sports.com/mlb.php?yr=2026&wk=6">', False),
        ("<title>506 Sports - College Football: Week 6, 2026</title>", False),
        ("", None),
        ("<title> </title>", None),
    ],
)
def test_names_nfl_week_page(head: str, expected: bool | None) -> None:
    assert names_nfl_week_page(_page("", head).decode()) is expected


def test_nfl_cards_accepted_but_cfb_canonical_rejected_whatever_the_markup() -> None:
    body = _card(
        "Red Cliff Stags @ Bay Point Marlins", "Sun 8:00 ET", "NBC", "Ann Fiction, Bo Stub"
    )
    assert len(parse_nfl_week_page(_page(body), season=2026, week=6)) == 1
    cfb_head = '<link rel="canonical" href="https://506sports.com/ncaaf.php?yr=2026&wk=6">'
    regional = '<p><b><font size="5">FOX SINGLE</font></b></p>' + _game(
        "Iron Ridge Bears @ Clearwater Pilots", "Cy Madeup, Di Notreal"
    )
    for page_body in (body, regional):
        with pytest.raises(ParseError, match="not an nfl week page"):
            parse_nfl_week_page(_page(page_body, cfb_head), season=2026, week=6)


def test_page_naming_nothing_falls_back_to_markup() -> None:
    card = _card(
        "Red Cliff Stags @ Bay Point Marlins", "Sun 8:00 ET", "NBC", "Ann Fiction, Bo Stub"
    )
    with pytest.raises(ParseError, match="not an nfl week page"):
        parse_nfl_week_page(_page(card, ""), season=2026, week=6)
    regional = '<p><b><font size="5">FOX SINGLE</font></b></p>' + _game(
        "Iron Ridge Bears @ Clearwater Pilots", "Cy Madeup, Di Notreal"
    )
    assert len(parse_nfl_week_page(_page(regional, ""), season=2026, week=6)) == 1


def test_card_crew_split_across_lines_keeps_each_name() -> None:
    crew = "Ann Fiction, Bo Stub<br/>Cy Madeup<br/><font>also WXXX Harbor City</font>"
    body = _card("Red Cliff Stags @ Bay Point Marlins", "Sun 8:00 ET", "NBC", crew)
    (listing,) = parse_nfl_week_page(_page(body), season=2026, week=6)
    assert listing.crew_names == ("Ann Fiction", "Bo Stub", "Cy Madeup")
