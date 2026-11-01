"""Phase 27 AAC-02/AAC-03: the AA announcing-schedule post parser.

Every page is invented (tests/fixtures/aa/schedule_synthetic.html and string
variants of it): invented teams, networks and people in the observed structure.
Nothing is fetched.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from booth_review.sources.aa.crews import (
    AaCrewsParseError,
    ParsedCrews,
    crews_cache_path,
    parse_crews,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "aa" / "schedule_synthetic.html"
_HTML = _FIXTURE.read_text(encoding="utf-8")
_URL = "https://awfulannouncing.com/college-football/invented-week-10-announcing-schedule.html"
_META = '<meta property="article:modified_time" content="2026-11-05T18:30:00+00:00" />\n'
_LD_MODIFIED = ',"dateModified":"2026-11-05T18:30:00+00:00"'


def _parse(html: str = _HTML) -> ParsedCrews:
    return parse_crews(html, season=2026)


def test_fixture_yields_whole_booths_and_counted_skips() -> None:
    parsed = _parse()
    assert parsed.url == _URL
    assert len(parsed.booths) == 3
    assert parsed.tbd == 1
    assert parsed.unparsed == 2
    assert parsed.no_pbp == 1


def test_first_booth_drops_the_reporter_and_keeps_post_order() -> None:
    booth = _parse().booths[0]
    assert booth.season == 2026
    assert booth.date_et == date(2026, 11, 6)
    assert booth.kickoff == "8:00 p.m."
    assert (booth.away_raw, booth.home_raw) == ("Alpha State", "Beta Tech")
    assert booth.network_raw == "Net1"
    assert booth.people == (("Ann Archer", "pbp"), ("Bo Baker", "analyst"))
    assert booth.source_url == _URL
    assert booth.pointer == "invented-week-10-announcing-schedule:1"


def test_header_with_and_without_comma_both_date_in_the_season() -> None:
    booths = _parse().booths
    assert booths[0].date_et == date(2026, 11, 6)  # "Friday November 6"
    assert booths[1].date_et == date(2026, 11, 7)  # "Saturday, November 7"


def test_two_analysts_keep_both_in_order_and_names_survive() -> None:
    booth = _parse().booths[1]
    assert booth.people == (
        ("Dee Dunn Jr.", "pbp"),
        ("Eli O'Neil III", "analyst"),
        ("José Núñez", "analyst"),
    )


def test_rank_text_stays_in_the_raw_team() -> None:
    booth = _parse().booths[1]
    assert booth.away_raw == "No. 12 Gamma"
    assert booth.home_raw == "Delta"
    assert booth.network_raw == "Net2"


def test_ad_div_adds_no_booth_and_no_unparsed_count() -> None:
    parsed = _parse()
    assert all("PGRp" not in name for booth in parsed.booths for name, _ in booth.people)
    # The ad sits between games 2 and 3; line numbers stay consecutive.
    assert [b.pointer.rsplit(":", 1)[1] for b in parsed.booths] == ["1", "2", "3"]


def test_vs_line_strips_the_trailing_city_and_keeps_multi_outlet_network() -> None:
    booth = _parse().booths[2]
    assert (booth.away_raw, booth.home_raw) == ("Team C", "Team D")
    assert booth.network_raw == "Net+/Local ABC"
    assert booth.people == (("Fay Fox", "pbp"), ("Gus Gray", "analyst"))


def test_tbd_line_is_counted_and_yields_no_booth() -> None:
    parsed = _parse()
    assert parsed.tbd == 1
    assert all(b.away_raw != "Echo U" for b in parsed.booths)


def test_unknown_role_tag_is_unparsed_never_guessed() -> None:
    parsed = _parse()
    assert all(b.away_raw != "Golf" for b in parsed.booths)


def test_line_without_a_time_and_network_part_is_unparsed() -> None:
    parsed = _parse()
    assert all(b.away_raw != "India" for b in parsed.booths)
    assert parsed.unparsed == 2  # the sideline line and this one


def test_analyst_only_crew_is_counted_no_pbp() -> None:
    parsed = _parse()
    assert parsed.no_pbp == 1
    assert all(b.away_raw != "Kilo" for b in parsed.booths)


def test_modified_time_prefers_the_meta_tag() -> None:
    parsed = _parse()
    assert parsed.modified == datetime(2026, 11, 5, 18, 30, tzinfo=UTC)
    assert parsed.published == datetime(2026, 11, 3, 15, 0, tzinfo=UTC)
    assert parsed.modified is not None and parsed.modified.tzinfo is not None


def test_modified_time_falls_back_to_ld_json() -> None:
    parsed = _parse(_HTML.replace(_META, ""))
    assert parsed.modified == datetime(2026, 11, 5, 18, 30, tzinfo=UTC)


def test_modified_time_is_none_without_meta_or_ld_json() -> None:
    parsed = _parse(_HTML.replace(_META, "").replace(_LD_MODIFIED, ""))
    assert parsed.modified is None


def test_naive_modified_time_becomes_none() -> None:
    naive = _HTML.replace("2026-11-05T18:30:00+00:00", "2026-11-05T18:30:00")
    assert _parse(naive).modified is None


def test_off_host_canonical_raises_a_count_only_error() -> None:
    off = _HTML.replace("https://awfulannouncing.com", "https://example.invalid")
    with pytest.raises(AaCrewsParseError) as info:
        _parse(off)
    assert "Alpha" not in str(info.value)
    assert "example.invalid" not in str(info.value)


def test_missing_canonical_raises() -> None:
    bare = "\n".join(
        line for line in _HTML.splitlines() if "canonical" not in line and "og:url" not in line
    )
    with pytest.raises(AaCrewsParseError):
        _parse(bare)


def test_missing_entry_content_raises_without_page_text() -> None:
    no_body = _HTML.replace('class="entry-content"', 'class="other"')
    with pytest.raises(AaCrewsParseError) as info:
        _parse(no_body)
    assert "Alpha" not in str(info.value)


def test_cache_path_zero_pads_the_week() -> None:
    assert crews_cache_path(2026, "9") == "aa/crews/2026/wk-09.html"
    assert crews_cache_path(2026, "12") == "aa/crews/2026/wk-12.html"


def test_cache_path_rejects_a_non_numeric_label() -> None:
    with pytest.raises(ValueError, match="label"):
        crews_cache_path(2026, "x")


# -- Phase 27 review WR-04: header drift is never a silently empty page ----------


@pytest.mark.parametrize(
    "header",
    ["Saturday, November 7th", "Saturday, Nov. 7:", "Saturday November 7th:"],
    ids=["ordinal", "abbrev-colon", "ordinal-colon"],
)
def test_ordinal_and_colon_headers_still_date_the_games(header: str) -> None:
    html = _HTML.replace("Saturday, November 7", header)
    booths = _parse(html).booths
    assert len(booths) == 3
    assert booths[1].date_et == date(2026, 11, 7)


def test_unrecognised_headers_reject_the_page_with_a_count_only_error() -> None:
    html = _HTML.replace("Friday November 6", "Friday the sixth").replace(
        "Saturday, November 7", "Saturday the seventh"
    )
    with pytest.raises(AaCrewsParseError) as info:
        _parse(html)
    message = str(info.value)
    assert "unparsed game lines" in message and "missing" in message
    for text in ("Alpha", "Archer", "seventh", "Net1"):
        assert text not in message


def test_game_lines_before_the_first_header_are_counted_unparsed() -> None:
    """Only the first header drifts: the games above the second header count as
    unparsed (they were silently dropped), the rest still parse."""
    parsed = _parse(_HTML.replace("Friday November 6", "Friday the sixth"))
    assert len(parsed.booths) == 2
    assert parsed.unparsed == 2 + 1
    assert parsed.booths[0].date_et == date(2026, 11, 7)


def test_intro_prose_before_the_header_is_not_a_game_line() -> None:
    assert _parse().unparsed == 2  # the fixture's intro and site header add nothing


def test_page_with_headers_and_only_unparsed_lines_is_rejected() -> None:
    body = (
        "<h3><u>Saturday, November 7</u></h3>\n"
        "<p><strong>Golf at Hotel (7:00 p.m., Net5): </strong>Gil Grant (sideline)</p>\n"
    )
    start = _HTML.index("<h3>")
    end = _HTML.index("<p>Closing invented prose")
    with pytest.raises(AaCrewsParseError):
        _parse(_HTML[:start] + body + _HTML[end:])


def test_page_with_only_tbd_crews_is_valid_and_empty() -> None:
    body = (
        "<h3><u>Saturday, November 7</u></h3>\n"
        "<p><strong>Echo U at Foxtrot (7:00 p.m., Net4): </strong>TBD</p>\n"
    )
    start = _HTML.index("<h3>")
    end = _HTML.index("<p>Closing invented prose")
    parsed = _parse(_HTML[:start] + body + _HTML[end:])
    assert parsed.booths == [] and parsed.tbd == 1 and parsed.unparsed == 0
