"""04.19 D-12/D-13: the ESPN Press Room booth and viewership parser.

Every page is invented (tests/fixtures/espnpr/*.html and the inline pages
below): invented teams, people and figures in the structure 04.19-37 recorded.
Nothing is fetched.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from booth_review.sources.espnpr import parser as espnpr_parser
from booth_review.sources.espnpr.parser import (
    EspnPrBooth,
    EspnPrParseError,
    parse_booths,
    parse_espnpr_viewers,
    parse_viewership,
    viewership_url_from_html,
)
from booth_review.sources.second_rows import SecondSourceRow, host_matches

_FIXTURES = Path(__file__).parent / "fixtures" / "espnpr"
_COMMENTATORS = (_FIXTURES / "commentators_synthetic.html").read_text(encoding="utf-8")
_RELEASE = (_FIXTURES / "release_synthetic.html").read_text(encoding="utf-8")
_RATINGS = (_FIXTURES / "ratings_synthetic.html").read_text(encoding="utf-8")
_SEASON_URL = "https://espnpressroom.com/2026-27-espn-college-football-commentators-schedule/"
_RELEASE_SLUG = "synthetic-week-6-college-football-coverage-across-espn-networks"
_RELEASE_URL = f"https://espnpressroom.com/press-release/{_RELEASE_SLUG}/"
_RATINGS_SLUG = "synthetic-saturday-viewership-grows-on-espn-networks"
_RATINGS_URL = f"https://espnpressroom.com/press-release/{_RATINGS_SLUG}/"


# -- inline page builders (invented content) -------------------------------------------------


def _release_page(slug: str, body: str, *, published: str = "2022-11-01T13:00:00-04:00") -> str:
    return f"""<!DOCTYPE html><html><head><title>Synthetic - ESPN Press Room</title>
<link rel="canonical" href="https://espnpressroom.com/press-release/{slug}/" />
<meta property="article:published_time" content="{published}" />
</head><body class="press-release-template-default single single-press-release">
<article class="press-release-content"><div class="brxe-post-content">
{body}
</div></article></body></html>"""


def _schedule(rows: str, *, fourth: str = "Platform") -> str:
    return f"""<p><strong>College Football on ESPN &#8211; WEEK 6</strong></p>
<table><tbody>
<tr><td><strong>Date</strong></td><td><strong>Time (ET)</strong></td>
<td><strong>Game/Commentators</strong></td><td><strong>{fourth}</strong></td></tr>
{rows}
</tbody></table>"""


def _viewers_table(heading: str, rows: str) -> str:
    return f"""<p><strong>{heading}</strong></p>
<table><tbody>
<tr><td><strong>Rank</strong></td><td><strong>Window</strong></td>
<td><strong>Matchup</strong></td><td><strong>P2+ Viewers</strong></td></tr>
{rows}
</tbody></table>"""


def _booths(html: str, slug: str = "synthetic-schedule", season: int = 2022) -> list[EspnPrBooth]:
    url = f"https://espnpressroom.com/press-release/{slug}/"
    return parse_booths(html, url=url, season=season).booths


def _viewership(body: str, slug: str = "synthetic-ratings", **kw: str) -> list[SecondSourceRow]:
    url = f"https://espnpressroom.com/press-release/{slug}/"
    return parse_viewership(_release_page(slug, body, **kw), url=url, season=2022).rows


# -- booths ----------------------------------------------------------------------------------


def test_commentators_page_gives_booths_in_printed_order() -> None:
    parsed = parse_booths(_COMMENTATORS, url=_SEASON_URL, season=2026)
    first, second = parsed.booths
    assert first == EspnPrBooth(
        season=2026,
        date_et=date(2026, 10, 17),
        kickoff="Noon",
        away_raw="Silverlake",
        home_raw="Northfield",
        network_raw="ABC",
        tv_names=("Avery Quill", "Rowan Pike", "Jules Marten"),
        source_url=_SEASON_URL,
        pointer="wk-7:1",
    )
    # The date is carried down; the TV: line is the booth and the Radio: line is dropped.
    assert second.date_et == date(2026, 10, 17)
    assert second.kickoff == "3:30 p.m."
    assert (second.away_raw, second.home_raw) == ("Eastbrook", "Westmere")
    assert second.tv_names == ("Casey Lorn", "Drew Fallow")
    assert second.network_raw == "ESPN/ESPN Radio"
    assert second.pointer == "wk-7:2"
    # The ESPN+ row has no crew line: no booth, counted.
    assert parsed.skipped == 1
    assert parsed.radio_dropped == 1


def test_weekly_release_drops_the_radio_only_row() -> None:
    parsed = parse_booths(_RELEASE, url=_RELEASE_URL, season=2022)
    (booth,) = parsed.booths
    assert booth.pointer == f"{_RELEASE_SLUG}:1"
    assert booth.date_et == date(2022, 10, 8)
    assert (booth.away_raw, booth.home_raw) == ("Silverlake", "Northfield")
    assert booth.network_raw == "ABC/ESPN+"
    assert booth.tv_names == ("Avery Quill", "Rowan Pike", "Jules Marten")
    # The ESPN Radio row's crew is a radio crew; it never becomes a TV booth.
    assert all("Kit Barrow" not in b.tv_names for b in parsed.booths)
    assert parsed.skipped == 1
    assert parsed.radio_dropped == 1


def test_wrapped_networks_ranks_and_footnote_marks() -> None:
    rows = """
<tr><td><strong>Sat, Sept 7</strong></td><td>7:30 p.m.</td>
<td><strong>T-No. 12 Hilltop at No. 3 Riverbend*</strong><br>Morgan Pike, Avery Lane</td>
<td>ABC/ESPN Radio/<br>SEC Network</td></tr>
<tr><td>&nbsp;</td><td>9 p.m.</td>
<td><strong>Lakeshore at Eastbrook</strong><br>Casey Lorn, Drew Fallow</td>
<td>ESPN/Disney+</td></tr>"""
    first, second = _booths(_release_page("synthetic-schedule", _schedule(rows)))
    assert first.network_raw == "ABC/ESPN Radio/SEC Network"
    assert (first.away_raw, first.home_raw) == ("Hilltop", "Riverbend")
    assert first.date_et == date(2022, 9, 7)
    assert second.network_raw == "ESPN/Disney+"
    assert second.date_et == date(2022, 9, 7)


def test_neutral_site_event_name_stays_out_of_the_team_fields() -> None:
    rows = """
<tr><td><strong>Sat, Aug 27</strong></td><td>Noon</td>
<td><strong>Synthetic Kickoff Classic: No. 5 Foxhollow vs. Granite Bay</strong><br>
Morgan Pike, Avery Lane, Jules Marten</td><td>ESPN</td></tr>
<tr><td>&nbsp;</td><td>3:30 p.m.</td>
<td><strong>Synthetic Showcase &#8211; Hilltop vs. Lakeshore</strong><br>
Casey Lorn, Drew Fallow</td><td>ABC</td></tr>"""
    first, second = _booths(_release_page("synthetic-schedule", _schedule(rows)))
    assert (first.away_raw, first.home_raw) == ("Foxhollow", "Granite Bay")
    assert (second.away_raw, second.home_raw) == ("Hilltop", "Lakeshore")


def test_rows_without_a_clean_booth_are_skipped_and_counted() -> None:
    rows = """
<tr><td><strong>Sat, Oct 1</strong></td><td>Noon</td>
<td><strong>Hilltop at Lakeshore</strong><br>Morgan Pike, Avery Lane<br>Casey Lorn, Drew Fallow</td>
<td>ESPN</td></tr>
<tr><td>&nbsp;</td><td>1 p.m.</td>
<td><strong>Eastbrook at Westmere</strong><br>Morgan Pike</td><td>ESPNU</td></tr>
<tr><td>&nbsp;</td><td>2 p.m.</td>
<td><strong>Foxhollow at Granite Bay</strong><br>Spanish: Kit Barrow, Sam Ellery</td>
<td>ESPN Deportes</td></tr>
<tr><td>&nbsp;</td><td>4 p.m.</td>
<td><strong>Silverlake at Northfield</strong><br>Radio: Kit Barrow, Sam Ellery</td>
<td>ESPN/ESPN Radio</td></tr>"""
    parsed = parse_booths(
        _release_page("synthetic-schedule", _schedule(rows)),
        url="https://espnpressroom.com/press-release/synthetic-schedule/",
        season=2022,
    )
    assert parsed.booths == []
    assert parsed.skipped == 4
    assert parsed.radio_dropped == 1


def test_a_missing_first_date_skips_until_a_date_is_printed() -> None:
    rows = """
<tr><td>&nbsp;</td><td>Noon</td>
<td><strong>Hilltop at Lakeshore</strong><br>Morgan Pike, Avery Lane</td><td>ESPN</td></tr>
<tr><td><strong>Mon, Jan 2</strong></td><td>8 p.m.</td>
<td><strong>Eastbrook vs. Westmere</strong><br>Casey Lorn, Drew Fallow</td><td>ESPN</td></tr>"""
    parsed = parse_booths(
        _release_page("synthetic-schedule", _schedule(rows)),
        url="https://espnpressroom.com/press-release/synthetic-schedule/",
        season=2022,
    )
    (booth,) = parsed.booths
    assert parsed.skipped == 1
    # January belongs to the season that began the previous August.
    assert booth.date_et == date(2023, 1, 2)
    assert booth.pointer == "synthetic-schedule:2"


def test_2026_style_header_and_where_to_watch_also_parse() -> None:
    rows = """
<tr><td><strong>Fri, Oct 14</strong></td><td>8 p.m.</td>
<td><strong>Hilltop at Lakeshore</strong><br>Morgan Pike, Avery Lane</td>
<td>ESPN2&nbsp;</td></tr>"""
    (booth,) = _booths(
        _release_page("synthetic-schedule", _schedule(rows, fourth="Where to Watch"))
    )
    assert booth.network_raw == "ESPN2"
    assert booth.kickoff == "8 p.m."


def test_booth_parser_refuses_off_host_and_non_schedule_pages() -> None:
    with pytest.raises(EspnPrParseError, match="host"):
        parse_booths(_COMMENTATORS, url="https://elsewhere.example.com/x/", season=2026)
    with pytest.raises(EspnPrParseError, match="schedule"):
        parse_booths(_RATINGS, url=_RATINGS_URL, season=2022)
    with pytest.raises(EspnPrParseError) as exc:
        parse_booths("<html><body>nothing</body></html>", url=_RELEASE_URL, season=2022)
    assert "nothing" not in str(exc.value)


# -- viewership ------------------------------------------------------------------------------


def _by_line(rows: list[SecondSourceRow]) -> dict[int, SecondSourceRow]:
    return {int(row.pointer.rsplit(":", 1)[1]): row for row in rows}


def test_ratings_fixture_rows_in_document_order() -> None:
    parsed = parse_viewership(_RATINGS, url=_RATINGS_URL, season=2022)
    rows = _by_line(parsed.rows)
    assert sorted(rows) == [1, 2, 3, 4, 5, 6]
    published = date(2022, 11, 1).toordinal() * 10

    prose = rows[1]
    assert (prose.kind, prose.viewers, prose.network_raw) == ("figure", 5_200_000, "ABC")
    assert (prose.away_raw, prose.home_raw) == ("Silverlake", "Northfield")
    assert prose.date_et == date(2022, 10, 29)  # the Saturday before the release
    assert prose.rank == published
    # A window average never loads; a MegaCast total is a multi-feed figure.
    assert rows[2].kind == "needs_review" and rows[2].viewers is None
    assert rows[3].kind == "multi_feed" and rows[3].viewers is None

    table = rows[4]
    assert (table.kind, table.viewers, table.network_raw) == ("figure", 5_200_000, "ABC")
    assert table.date_et == date(2022, 10, 29)
    assert table.rank == published + 2  # the table outranks prose in one release
    assert (rows[5].away_raw, rows[5].home_raw) == ("Eastbrook", "Westmere")
    assert rows[5].date_et == date(2022, 9, 24)
    assert rows[5].viewers == 3_700_000

    bullet = rows[6]
    # The lead-in names no network, so the matcher sends the row to review.
    assert (bullet.kind, bullet.viewers, bullet.network_raw) == ("figure", 1_900_000, "")
    assert (bullet.away_raw, bullet.home_raw) == ("foxhollow", "granite bay")
    assert bullet.rank == published + 1

    for row in parsed.rows:
        assert row.source == "espnpr"
        assert row.season == 2022
        assert row.chart_kind == "post"
        assert row.source_url == _RATINGS_URL
        assert host_matches("espnpr", row.source_url)
        assert row.pointer.startswith(f"{_RATINGS_SLUG}:")
        assert row.superseded is False


def test_simulcast_megacast_and_unknown_suffix_are_classified() -> None:
    body = """
<p>Eastbrook-Westmere averaged 6.1 million viewers across ABC and ESPN2.</p>
<p>Hilltop-Lakeshore drew 2.4 million viewers on the ESPN MegaCast.</p>
""" + _viewers_table(
        "Most-watched synthetic games on ESPN",
        "<tr><td><strong>1</strong></td><td>Night</td><td>Oct. 8: Foxhollow at Granite Bay</td>"
        "<td>5.2f</td></tr>"
        "<tr><td><strong>3</strong></td><td>Night</td><td>Oct. 8: Riverbend at Silverlake</td>"
        "<td>TBA</td></tr>",
    )
    kinds = [(row.kind, row.viewers) for row in _viewership(body)]
    assert kinds == [
        ("simulcast", None),
        ("multi_feed", None),
        ("unknown_suffix", None),
        ("no_figure", None),
    ]


def test_averaging_sentences_and_whole_millions_never_load() -> None:
    body = """
<p>Saturday primetime games are averaging 4.1 million viewers on ABC.</p>
<p>Hilltop-Lakeshore drew 5 million viewers on ABC.</p>
<p>The season opener at Granite Bay (2.2 million, ESPN) set a mark.</p>
<p>ESPN on cable:</p>
<ul><li>hilltop at lakeshore: 3 million</li></ul>
"""
    rows = _viewership(body)
    assert [row.kind for row in rows] == ["needs_review"] * 4
    assert all(row.viewers is None and not row.network_raw for row in rows)


def test_bullet_network_comes_only_from_an_unambiguous_lead_in() -> None:
    body = """
<p>Viewers for the most-watched synthetic games on ESPN2:</p>
<ul><li>hilltop at lakeshore: 1.4 million</li><li>eastbrook vs. westmere: 1.1M</li></ul>
<p>The most-watched games across all cable networks were on ESPN:</p>
<ul><li>foxhollow vs. granite bay: 2.1 million</li></ul>
"""
    rows = _viewership(body)
    assert [(r.network_raw, r.viewers) for r in rows] == [
        ("ESPN2", 1_400_000),
        ("ESPN2", 1_100_000),
        ("", 2_100_000),
    ]
    assert all(row.kind == "figure" for row in rows)


@pytest.mark.parametrize(
    ("heading", "network"),
    [
        ("ABC Leads With 7 of the Top 10 Games Across All Networks", "ABC"),
        ("Most-watched synthetic games on ESPN networks", ""),
        ("Most-watched synthetic games on ABC and ESPN", ""),
        ("Synthetic combined ABC audience", ""),
        ("Most-watched synthetic games", ""),
    ],
)
def test_table_network_comes_from_the_heading_above_it(heading: str, network: str) -> None:
    body = _viewers_table(
        heading,
        "<tr><td><strong>2</strong></td><td>Afternoon</td><td>Sept. 3: Hilltop vs. Lakeshore</td>"
        "<td>4.4 Million</td></tr>",
    )
    (row,) = _viewership(body)
    assert row.network_raw == network
    assert row.kind == "figure"
    assert row.viewers == 4_400_000
    assert row.date_et == date(2022, 9, 3)


def test_an_unreadable_table_matchup_goes_to_review() -> None:
    body = _viewers_table(
        "Most-watched synthetic games on ABC",
        "<tr><td><strong>2</strong></td><td>Night</td><td>Synthetic doubleheader</td>"
        "<td>4.4 Million</td></tr>",
    )
    (row,) = _viewership(body)
    assert row.kind == "needs_review"
    assert row.viewers is None


def test_a_later_release_outranks_an_earlier_one() -> None:
    body = "<p>Hilltop-Lakeshore averaged 2.4 million viewers on ESPN.</p>"
    (early,) = _viewership(body, slug="early", published="2022-10-04T12:00:00-04:00")
    (late,) = _viewership(body, slug="late", published="2022-10-11T12:00:00-04:00")
    assert late.rank > early.rank
    assert early.date_et == date(2022, 10, 1)


@pytest.mark.parametrize(
    ("printed", "viewers"),
    [
        ("5.2 million", 5_200_000),
        ("5.2 Million", 5_200_000),
        ("5.2M", 5_200_000),
        ("904K", 904_000),
        ("904 thousand", 904_000),
        ("5,200,000", 5_200_000),
        ("5.2f", None),
        ("5.2", None),
        ("TBA", None),
        ("", None),
    ],
)
def test_viewer_units(printed: str, viewers: int | None) -> None:
    assert parse_espnpr_viewers(printed) == viewers


def test_viewership_parser_refuses_other_pages_count_only() -> None:
    with pytest.raises(EspnPrParseError, match="ratings"):
        parse_viewership(_RELEASE, url=_RELEASE_URL, season=2022)
    with pytest.raises(EspnPrParseError, match="host"):
        parse_viewership(_RATINGS, url="http://espnpressroom.com/press-release/x/", season=2022)
    assert viewership_url_from_html(_RATINGS) == _RATINGS_URL
    assert viewership_url_from_html(_RELEASE) is None
    assert viewership_url_from_html(_COMMENTATORS) is None


def test_parser_reads_text_only() -> None:
    source = Path(espnpr_parser.__file__).read_text(encoding="utf-8")
    for forbidden in ("httpx", "PoliteClient", "urlopen", "requests", "subprocess", "eval("):
        assert forbidden not in source
