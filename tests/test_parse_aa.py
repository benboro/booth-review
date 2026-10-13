"""04.19 D-10/D-17/D-21: Awful Announcing post parser.

Every post is invented (tests/fixtures/aa/post_synthetic.html and the small
inline pages below): invented teams, networks and figures in the observed
structure. Nothing is fetched.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from booth_review.sources.aa.collector import post_request
from booth_review.sources.aa.index import UrlEntry
from booth_review.sources.aa.parser import (
    AaParseError,
    parse_aa_viewers,
    parse_post,
    post_slug,
    post_url_from_html,
)
from booth_review.sources.second_rows import SecondSourceRow

_FIXTURES = Path(__file__).parent / "fixtures" / "aa"
_HTML = (_FIXTURES / "post_synthetic.html").read_text(encoding="utf-8")
_URL = (
    "https://awfulannouncing.com/college-football/silverlake-northfield-week-5-fox-cfb-ratings.html"
)
_SLUG = "silverlake-northfield-week-5-fox-cfb-ratings"


def _by_line(html: str = _HTML, url: str = _URL) -> dict[int, SecondSourceRow]:
    parsed = parse_post(html, url=url, season=2022)
    return {int(row.pointer.rsplit(":", 1)[1]): row for row in parsed.rows}


def _page(
    *paragraphs: str, headline: str = "Invented headline", published: str | None = None
) -> str:
    stamp = published or "2022-10-03T14:00:00+00:00"
    ld = f'{{"@type":"Article","headline":"{headline}","datePublished":"{stamp}"}}'
    body = "".join(f"<p>{text}</p>" for text in paragraphs)
    return (
        f'<html><head><script type="application/ld+json">{ld}</script></head>'
        f'<body><div class="entry-content">{body}</div></body></html>'
    )


def test_canonical_url_and_slug_match_the_collector_cache_name() -> None:
    assert post_url_from_html(_HTML) == _URL
    assert post_slug(_URL) == _SLUG
    assert post_request(2022, UrlEntry(url=_URL, lastmod=None)).cache_path == (
        f"aa/2022/posts/{_SLUG}.html"
    )


def test_game_average_sentence_is_one_figure_row() -> None:
    row = _by_line()[1]
    assert row.source == "aa"
    assert row.pointer == f"{_SLUG}:1"
    assert row.kind == "figure"
    assert row.viewers == 5_200_000
    assert (row.away_raw, row.home_raw, row.network_raw) == ("Silverlake", "Northfield", "FOX")
    # Posted Monday 10/3 (ET); no weekday named, so the game is the Saturday before.
    assert row.date_et == date(2022, 10, 1)
    assert row.rank == date(2022, 10, 3).toordinal()
    assert row.chart_kind == "post"
    assert row.source_url == _URL
    assert row.superseded is False


def test_published_time_is_read_as_utc_for_the_settle_tie_break() -> None:
    # WR-07: the ld+json datePublished, as UTC, breaks a same-rank tie.
    assert {row.published for row in _by_line().values()} == {"2022-10-03T14:00:00Z"}


def test_every_mention_kind_and_the_ignored_count() -> None:
    parsed = parse_post(_HTML, url=_URL, season=2022)
    kinds = {int(row.pointer.rsplit(":", 1)[1]): row.kind for row in parsed.rows}
    assert kinds == {
        1: "figure",
        4: "needs_review",  # two figures in one sentence
        5: "needs_review",
        6: "needs_review",  # last year
        7: "simulcast",  # ABC and ESPN2
        8: "needs_review",  # combined multi-game total
        9: "figure",  # roundup line
        10: "figure",  # roundup line, comma integer
    }
    # Line 2 is a peak, line 3 a streaming-only number, plus the embedded post.
    assert parsed.ignored == 3
    assert all(row.viewers is None for row in parsed.rows if row.kind != "figure")
    assert all(row.away_raw == "" for row in parsed.rows if row.kind == "needs_review")


def test_roundup_lines() -> None:
    rows = _by_line()
    assert (rows[9].away_raw, rows[9].home_raw, rows[9].network_raw) == (
        "Lakeshore",
        "Riverbend",
        "ESPN",
    )
    assert rows[9].viewers == 1_900_000
    assert (rows[10].away_raw, rows[10].home_raw, rows[10].network_raw) == (
        "Hilltop",
        "Eastmoor",
        "NBC",
    )
    assert rows[10].viewers == 850_000
    assert rows[7].network_raw == "ABC & ESPN2"


def test_unit_rule() -> None:
    assert parse_aa_viewers("5.2 million") == 5_200_000
    assert parse_aa_viewers("3.563 million") == 3_563_000
    assert parse_aa_viewers("1.9M") == 1_900_000
    assert parse_aa_viewers("922,000") == 922_000
    for text in ("a million", "20%", "", "1o.3 million"):
        assert parse_aa_viewers(text) is None


def test_the_game_resolves_through_a_one_game_headline_and_a_named_weekday() -> None:
    html = _page(
        "The contest averaged 4.4 million viewers on NBC Friday night.",
        headline="Riverbend&#8217;s upset win over Lakeshore delivers for NBC",
    )
    (row,) = _by_line(html).values()
    assert row.kind == "figure"
    assert (row.away_raw, row.home_raw, row.network_raw) == ("Riverbend", "Lakeshore", "NBC")
    assert row.date_et == date(2022, 9, 30)  # the Friday before Monday 10/3


def test_the_game_without_a_one_game_headline_goes_to_review() -> None:
    html = _page(
        "The game averaged 4.4 million viewers on NBC.",
        headline="Riverbend-Lakeshore and Hilltop-Eastmoor lead the week",
    )
    (row,) = _by_line(html).values()
    assert row.kind == "needs_review"


def test_network_subject_and_last_night() -> None:
    html = _page(
        "NBC drew 2.2 million viewers for the Riverbend-Lakeshore game last night.",
        published="2022-10-07T13:00:00+00:00",
    )
    (row,) = _by_line(html).values()
    assert row.kind == "figure"
    assert (row.away_raw, row.home_raw, row.network_raw) == ("Riverbend", "Lakeshore", "NBC")
    assert row.viewers == 2_200_000
    assert row.date_et == date(2022, 10, 6)


def test_trailing_comparison_does_not_disqualify_the_figure() -> None:
    html = _page(
        "Hilltop&#8217;s win over Eastmoor averaged 2.0 million viewers on ABC, "
        "the network&#8217;s best invented window since 2015."
    )
    (row,) = _by_line(html).values()
    assert row.kind == "figure"
    assert row.network_raw == "ABC"


def test_unstated_network_is_left_blank_for_review() -> None:
    (row,) = _by_line(_page("Hilltop&#8217;s win over Eastmoor drew 2.0 million viewers.")).values()
    assert row.kind == "figure"
    assert row.network_raw == ""


def test_sentence_splitting_keeps_abbreviations_together() -> None:
    html = _page(
        "No. 4 Hilltop&#8217;s win over N.C. Eastmoor averaged 2.0 million viewers on ABC at "
        "8 p.m. ET. A second sentence has no figure."
    )
    (row,) = _by_line(html).values()
    assert row.kind == "figure"
    assert (row.away_raw, row.home_raw) == ("No. 4 Hilltop", "N.C. Eastmoor")


def test_missing_publish_date_leaves_the_date_empty() -> None:
    html = (
        '<html><body><div class="entry-content"><p>Hilltop&#8217;s win over Eastmoor averaged '
        "2.0 million viewers on ABC.</p></div></body></html>"
    )
    (row,) = _by_line(html).values()
    assert row.date_et is None
    assert row.rank == 0


@pytest.mark.parametrize(
    "url",
    [
        "http://awfulannouncing.com/college-football/post.html",
        "https://awfulannouncing.example.com/college-football/post.html",
        "https://www.thetvratingsguide.com/2022/10/post.html",
    ],
)
def test_off_host_or_plain_http_url_raises_count_only(url: str) -> None:
    with pytest.raises(AaParseError) as exc:
        parse_post(_HTML, url=url, season=2022)
    assert url not in str(exc.value)
    assert "Silverlake" not in str(exc.value)
