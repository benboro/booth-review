"""04.19 D-10/D-17/D-21: The TV Ratings Guide post parser.

Every post is invented (tests/fixtures/tvrg/post_synthetic.html and the inline
broadcast page below): invented teams, networks and figures in the observed
structure. Nothing is fetched.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from booth_review.sources.second_rows import SecondSourceRow
from booth_review.sources.smw.rows import classify_row
from booth_review.sources.tvrg.collector import post_request
from booth_review.sources.tvrg.parser import (
    TvrgParseError,
    parse_post,
    parse_tvrg_viewers,
    post_slug,
    post_url_from_html,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "tvrg"
_HTML = (_FIXTURES / "post_synthetic.html").read_text(encoding="utf-8")
_URL = "https://www.thetvratingsguide.com/2022/10/saturday-cable-ratings-10122-invented.html"
_SLUG = "2022-10-saturday-cable-ratings-10122-invented"


def _parsed() -> dict[str, SecondSourceRow]:
    parsed = parse_post(_HTML, url=_URL, season=2022)
    return {row.pointer.split(":")[1]: row for row in parsed.rows}


def test_canonical_url_and_slug_match_the_collector_cache_name() -> None:
    assert post_url_from_html(_HTML) == _URL
    assert post_slug(_URL) == _SLUG
    assert post_request(2022, _URL).cache_path == f"tvrg/2022/posts/{_SLUG}.html"


def test_college_game_row_is_a_figure_in_millions() -> None:
    row = _parsed()["1"]
    assert row.source == "tvrg"
    assert row.pointer == f"{_SLUG}:1"
    assert row.kind == "figure"
    assert row.viewers == 1_230_000
    assert (row.away_raw, row.home_raw) == ("Silverlake", "Northfield")
    assert row.network_raw == "ESPN2"
    assert row.date_et == date(2022, 10, 1)
    assert row.rank == date(2022, 10, 1).toordinal()
    assert row.chart_kind == "post"
    assert row.source_url == _URL
    assert row.superseded is False


def test_published_time_is_read_as_utc_for_the_settle_tie_break() -> None:
    # WR-07: two posts of one air date tie on rank; the later published one wins.
    assert {row.published for row in _parsed().values()} == {""}  # the fixture has none
    stamped = _HTML.replace(
        "</head>",
        "</head><abbr class='published updated' title='2022-10-03T09:15:00-07:00'>Oct 3</abbr>",
        1,
    )
    assert "<abbr" in stamped
    rows = parse_post(stamped, url=_URL, season=2022).rows
    assert {row.published for row in rows} == {"2022-10-03T16:15:00Z"}


def test_every_row_kind_and_the_ignored_count() -> None:
    parsed = parse_post(_HTML, url=_URL, season=2022)
    kinds = {row.pointer.split(":")[1]: row.kind for row in parsed.rows}
    assert kinds == {
        "1": "figure",
        "3": "unknown_suffix",  # 0.98f: never a figure
        "5": "simulcast",  # ABC/ESPN2
        "6": "non_game",  # College Football Countdown
        "9": "no_figure",  # TBA
        "10": "needs_review",  # three teams, no clean split
        "11": "figure",  # 1-decimal value, conference-branded label
    }
    # Blank row, reality show, NFL preseason, high school, rerun, highlights label.
    assert parsed.ignored == 6
    assert all(row.viewers is None for row in parsed.rows if row.kind != "figure")
    one_decimal = next(row for row in parsed.rows if row.pointer.endswith(":11"))
    assert one_decimal.viewers == 500_000
    assert one_decimal.network_raw == "Valley Conference Network"


def test_unit_rule() -> None:
    assert parse_tvrg_viewers("1.23") == 1_230_000
    assert parse_tvrg_viewers("0.5") == 500_000
    assert parse_tvrg_viewers("12.04") == 12_040_000
    for text in ("0.98f", "TBA", "", "1.2M", "n/a"):
        assert parse_tvrg_viewers(text) is None


def test_ampersand_network_is_a_simulcast_through_the_shared_rules() -> None:
    row = {"network": "ABC & ESPN2", "away": "A", "home": "B", "viewers": "2.00"}
    assert classify_row(row, parse=parse_tvrg_viewers) == "simulcast"
    row = {"network": "ESPN MEGA", "away": "A", "home": "B", "viewers": "2.00"}
    assert classify_row(row, parse=parse_tvrg_viewers) == "multi_feed"


_BROADCAST = """<html><head>
<link href='https://www.thetvratingsguide.com/2022/10/saturday-tv-ratings-10122-x.html'
 rel='canonical'/>
<title>Saturday TV Ratings 10/1/22: Invented - The TV Ratings Guide</title></head><body>
<div class='post-body entry-content'>
<table><tr><td>lead</td><td>lead</td></tr></table>
<table>
<tr><td><p><span>Time</span></p></td><td><p><span>Show</span></p></td>
<td><p><span>18-49 Rating/Share</span></p></td><td><p><span>Viewers (mil)</span></p></td>
<td><p><span>Network</span></p></td></tr>
<tr><td>8 PM</td><td>College Football: Hilltop v. Riverbend</td><td>1.10/6</td><td>4.56</td>
<td>ABC</td></tr>
<tr><td></td><td>Invented Drama (R)</td><td>0.20/1</td><td>2.00</td><td>CBS</td></tr>
<tr><td>8:30 PM</td><td>Invented Comedy</td><td>0.10/1</td><td>0.90</td><td>NBC</td></tr>
</table></div></body></html>"""


def test_broadcast_layout_reads_columns_by_header() -> None:
    url = "https://www.thetvratingsguide.com/2022/10/saturday-tv-ratings-10122-x.html"
    parsed = parse_post(_BROADCAST, url=url, season=2022)
    assert parsed.ignored == 2
    (row,) = parsed.rows
    assert (row.away_raw, row.home_raw, row.network_raw) == ("Hilltop", "Riverbend", "ABC")
    assert row.viewers == 4_560_000
    assert row.pointer == "2022-10-saturday-tv-ratings-10122-x:1"


@pytest.mark.parametrize(
    "url",
    [
        "http://www.thetvratingsguide.com/2022/10/saturday-cable-ratings-10122-invented.html",
        "https://thetvratingsguide.example.com/2022/10/saturday-cable-ratings-10122-invented.html",
        "https://www.sportsmediawatch.com/2022/10/post.html",
    ],
)
def test_off_host_or_plain_http_url_raises_count_only(url: str) -> None:
    with pytest.raises(TvrgParseError) as exc:
        parse_post(_HTML, url=url, season=2022)
    assert "Silverlake" not in str(exc.value)
    assert url not in str(exc.value)


def test_post_without_a_data_table_has_no_rows() -> None:
    html = "<html><div class='post-body entry-content'><p>No table.</p></div></html>"
    parsed = parse_post(html, url=_URL, season=2022)
    assert parsed.rows == []
    assert parsed.ignored == 0


def test_tables_outside_the_post_body_are_never_read() -> None:
    html = (
        "<html><title>Saturday Cable Ratings 10/1/22</title>"
        "<table><tr><td>Show</td><td>Network</td><td>Viewers</td></tr>"
        "<tr><td>College Football: Silverlake v. Northfield</td><td>ESPN</td><td>1.00</td></tr>"
        "</table><div class='post-body entry-content'></div></html>"
    )
    assert parse_post(html, url=_URL, season=2022).rows == []
