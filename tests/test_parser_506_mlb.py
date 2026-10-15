"""Tests for the 506 MLB parser against synthetic fixtures."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from booth_review.errors import ParseError
from booth_review.mlb.constants import MLB_SMOKE_MIN_LISTINGS
from booth_review.sources.sports506.mlb_parser import (
    MlbListing506,
    MlbOutletCell,
    detect_layout,
    discover_mlb_season_labels,
    mlb_smoke_check,
    parse_mlb_page,
    parse_outlet_cell,
)

FIXTURES = Path(__file__).parent / "fixtures" / "mlb" / "sports506"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture(scope="module")
def week() -> bytes:
    return _read("week_cgame_synthetic.html")


@pytest.fixture(scope="module")
def week_listings(week: bytes) -> dict[str, MlbListing506]:
    page = parse_mlb_page(week, season=2099, label="3")
    return {f"{item.away_raw}|{item.game_number}": item for item in page.listings}


def test_detect_layouts() -> None:
    assert detect_layout(_read("week_cgame_synthetic.html").decode()) == "cgame"
    assert detect_layout(_read("round_cgame_noheader_synthetic.html").decode()) == "cgame"
    assert detect_layout(_read("fox_map_synthetic.html").decode()) == "map"
    assert detect_layout("<html></html>") == "unknown"


def test_unknown_layout_rejected_with_count_only_reason() -> None:
    with pytest.raises(ParseError) as exc:
        parse_mlb_page(b"<html><body>secret page text</body></html>", season=2099, label="3")
    assert "secret" not in str(exc.value)
    assert "2099" in str(exc.value)


def test_plain_row(week_listings: dict[str, MlbListing506]) -> None:
    row = week_listings["Alpha City|0"]
    assert row.home_raw == "Bravo Town"
    assert row.game_date == date(2099, 6, 5)
    assert row.time_et == "7:00 PM ET"
    assert row.crew_names == ("Pat Example", "Alex Sample", "Sam Case")
    assert row.outlets == (MlbOutletCell("Apple TV+", False, None, None),)
    assert not row.neutral
    assert not row.not_played


def test_bold_wrapper_stripped(week_listings: dict[str, MlbListing506]) -> None:
    assert week_listings["Delta Bay|0"].home_raw == "Echo Park"


def test_neutral_with_venue_note(week_listings: dict[str, MlbListing506]) -> None:
    row = week_listings["Foxtrot Falls|0"]
    assert row.neutral
    assert row.home_raw == "Golf Harbor"
    assert row.venue_note == "Faraway, XX"
    assert len(row.crew_names) == 4


def test_marked_doubleheader(week_listings: dict[str, MlbListing506]) -> None:
    assert week_listings["Hotel Heights|1"].home_raw == "India Island"
    assert week_listings["Hotel Heights|2"].time_et == "6:00 PM ET"


def test_unmarked_same_pair_pair_numbered_by_time(week: bytes) -> None:
    unmarked = week.replace(b" (Game 1)", b"").replace(b" (Game 2)", b"")
    page = parse_mlb_page(unmarked, season=2099, label="3")
    hotel = [i for i in page.listings if i.away_raw == "Hotel Heights"]
    assert [(i.game_number, i.time_et) for i in hotel] == [
        (1, "1:00 PM ET"),
        (2, "6:00 PM ET"),
    ]


def test_series_prefix_and_neutral_order() -> None:
    page = parse_mlb_page(_read("round_cgame_noheader_synthetic.html"), season=2099, label="WC")
    first = page.listings[0]
    assert (first.series_game, first.away_raw, first.home_raw) == (1, "Alpha City", "Bravo Town")
    assert page.listings[2].series_game == 2  # bold wrapper plus prefix


def test_not_played(week: bytes) -> None:
    page = parse_mlb_page(week, season=2099, label="3")
    played = [i for i in page.listings if i.not_played]
    assert [i.away_raw for i in played] == ["Xray Xing"]
    assert played[0].home_raw == "Yankee Yard"


def test_starred_empty_crew(week_listings: dict[str, MlbListing506]) -> None:
    row = week_listings["Juliet Junction|0"]
    assert row.outlets[0].starred
    assert row.crew_names == ()
    assert not row.local_simulcast


def test_local_simulcast(week_listings: dict[str, MlbListing506]) -> None:
    row = week_listings["Lima Lake|0"]
    assert row.local_simulcast
    assert row.crew_names == ()
    assert row.outlets[0].raw_name == "ESPN Unltd"


def test_two_starred_outlets_one_cell(week_listings: dict[str, MlbListing506]) -> None:
    cells = week_listings["Nova Nook|0"].outlets
    assert [(c.raw_name, c.starred) for c in cells] == [("MLBN", True), ("ESPN Unltd", True)]


def test_sister_outlet_dropped(week_listings: dict[str, MlbListing506]) -> None:
    assert week_listings["Papa Peak|0"].outlets == (MlbOutletCell("Peacock", False, None, None),)
    assert week_listings["Romeo Ridge|0"].outlets == (MlbOutletCell("TBS", False, None, None),)


def test_regional_tail_kept_as_local_outlet() -> None:
    assert parse_outlet_cell("XNET / NESN") == (MlbOutletCell("XNET", False, None, "NESN"),)


def test_fox_window_marker(week_listings: dict[str, MlbListing506]) -> None:
    assert week_listings["Victor Vale|0"].outlets == (MlbOutletCell("FOX", False, "red", None),)


def test_outlet_cell_edge_cases() -> None:
    assert parse_outlet_cell("TBS*") == (MlbOutletCell("TBS", True, None, None),)
    assert parse_outlet_cell("MLBN alt*")[0].raw_name == "MLBN alt"
    assert parse_outlet_cell("") == ()


def test_live_page_outlet_spellings() -> None:
    assert parse_outlet_cell("FOX (\U0001f534 on map)") == (
        MlbOutletCell("FOX", False, "red", None),
    )
    assert parse_outlet_cell("MLBN*ESPN Unltd") == (
        MlbOutletCell("MLBN", True, None, None),
        MlbOutletCell("ESPN Unltd", False, None, None),
    )


def test_non_game_rows_collected(week: bytes) -> None:
    page = parse_mlb_page(week, season=2099, label="3")
    kinds = sorted(r.kind for r in page.non_game)
    assert kinds == ["all_star", "blank", "home_run_derby"]
    assert all(i.away_raw not in ("", "All-Star Game") for i in page.listings)


def test_round_note_names_never_read() -> None:
    content = _read("round_cgame_header_synthetic.html")
    page = parse_mlb_page(content, season=2099, label="WS")
    assert page.listings[0].round_header == "World Series"
    assert page.listings[0].crew_names == ("Pat Example", "Sam Case", "Taylor Mark")
    assert "Quinn" not in repr(page)
    assert "Notetwo" not in repr(page)


def test_map_layout_yields_no_listings_and_ignores_comments() -> None:
    page = parse_mlb_page(_read("fox_map_synthetic.html"), season=2099, label="1")
    assert page.layout == "map"
    assert page.listings == ()
    assert "Hidden" not in repr(page)
    assert "Commented" not in repr(page)


def test_discover_labels(week: bytes) -> None:
    expected = (*(str(n) for n in range(1, 29)), "WC", "DS", "CS", "WS")
    assert discover_mlb_season_labels(week) == expected


def test_smoke_passes_weekly_with_mostly_crewless_rows(week: bytes) -> None:
    assert mlb_smoke_check(week, season=2099, label="3") is None


def test_smoke_passes_round_pages() -> None:
    header = _read("round_cgame_header_synthetic.html")
    assert mlb_smoke_check(header, season=2099, label="WS") is None
    noheader = _read("round_cgame_noheader_synthetic.html")
    assert mlb_smoke_check(noheader, season=2099, label="WC") is None


def test_smoke_fails_too_few_listings() -> None:
    page = _read("round_cgame_noheader_synthetic.html")
    reason = mlb_smoke_check(page, season=2099, label="3")
    assert reason is not None
    assert str(MLB_SMOKE_MIN_LISTINGS) in reason


def test_smoke_fails_low_outlet_share(week: bytes) -> None:
    blank = week.decode()
    for name in ("Apple TV+", "FS1", "ESPN", "TBS", "MLBN*", "Netflix", "FOX", "Peacock*"):
        blank = blank.replace(f'<div id="cntwk">{name}</div>', '<div id="cntwk"></div>')
    reason = mlb_smoke_check(blank.encode(), season=2099, label="3")
    assert reason is not None
    assert "have an outlet" in reason


def test_smoke_fails_round_without_crews() -> None:
    page = _read("round_cgame_header_synthetic.html").decode()
    page = page.replace("Pat Example, Sam Case, Taylor Mark", "")
    reason = mlb_smoke_check(page.encode(), season=2099, label="WS")
    assert reason is not None
    assert "name a crew" in reason
    assert "Pat" not in reason


def test_smoke_reason_for_unknown_layout_is_count_only() -> None:
    reason = mlb_smoke_check(b"<html><body>page text</body></html>", season=2099, label="3")
    assert reason is not None
    assert "page text" not in reason
