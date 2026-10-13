"""04.19 D-10/D-11: Awful Announcing sitemap parsing and the gap-week data pass.

Every sitemap and post is invented (tests/fixtures/aa/); every request goes
to a mock transport, so nothing leaves the machine.
"""

from __future__ import annotations

import random
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from booth_review import cli
from booth_review.build.gaps import regular_weeks_by_date
from booth_review.cli import main
from booth_review.config import DataPaths
from booth_review.errors import ParseError
from booth_review.sources.aa.collector import (
    AaCollector,
    gap_weeks,
    post_request,
    wanted_entry,
)
from booth_review.sources.aa.index import (
    UrlEntry,
    ordered_post_sitemaps,
    parse_sitemap,
    select_post_sitemaps,
    week_of_slug,
    year_of_slug,
)
from booth_review.sources.policy import PolicyCheck, append_policy_check
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient

_FIXTURES = Path(__file__).parent / "fixtures" / "aa"
_HOST = "https://awfulannouncing.com"
_ALLOW = b"User-agent: *\nAllow: /\n"
_INDEX = (_FIXTURES / "sitemap_index_synthetic.xml").read_bytes()
_CHILD = (_FIXTURES / "sitemap_synthetic.xml").read_bytes()


def _post(url: str) -> bytes:
    """An invented roundup the build can read: an on-host canonical link, no figure."""
    return (
        f'<html><head><link rel="canonical" href="{url}"></head>'
        "<body><p>Invented roundup.</p></body></html>"
    ).encode()


_WEEK5 = (
    f"{_HOST}/college-football/2022-college-football-week-5-viewership-silverlake-northfield.html"
)
_WEEK4 = f"{_HOST}/college-football/college-football-week-4-viewership-2022-lakeside.html"
_GAME = f"{_HOST}/college-football/silverlake-northfield-week-5-espn-cfb-ratings.html"
_NETWORK = f"{_HOST}/ratings/silverlake-fox-week-4-viewership-down.html"
_NO_WEEK = f"{_HOST}/ratings/example-northfield-college-football-most-watched.html"
_KEPT = [_WEEK5, _WEEK4, _GAME, _NETWORK, _NO_WEEK]
_GAP = date(2022, 10, 1)
_WEEK_OF = {_GAP: {5}, date(2022, 9, 24): {4}}


# -- sitemap parser --------------------------------------------------------------------


def test_parse_index_lists_on_host_children_with_lastmod() -> None:
    sitemap = parse_sitemap(_INDEX)
    assert sitemap.kind == "index"
    assert [ref.name for ref in sitemap.sitemaps] == [
        "post-sitemap",
        "post-sitemap2",
        "post-sitemap3",
        "post-sitemap4",
        "post-sitemap5",
        "post-sitemap6",
        "attachment-sitemap",
    ]
    assert sitemap.skipped == 1  # the off-host child
    by_name = {ref.name: ref for ref in sitemap.sitemaps}
    assert by_name["post-sitemap2"].lastmod is None  # WordPress's "-0001-11-30"
    assert by_name["post-sitemap"].post_number == 1
    assert by_name["post-sitemap5"].post_number == 5
    assert by_name["attachment-sitemap"].post_number is None


def test_parse_urlset_keeps_only_https_on_host_urls() -> None:
    sitemap = parse_sitemap(_CHILD)
    assert sitemap.kind == "urlset"
    assert len(sitemap.urls) == 14
    assert sitemap.skipped == 2
    assert all(entry.url.startswith(f"{_HOST}/") for entry in sitemap.urls)
    assert sitemap.urls[0].slug == "2022-college-football-week-5-viewership-silverlake-northfield"
    assert sitemap.urls[0].category == "college-football"
    assert UrlEntry(f"{_HOST}/bare-slug.html", None).category == ""


@pytest.mark.parametrize(
    "xml",
    [
        b'<?xml version="1.0"?><!DOCTYPE urlset [<!ENTITY x "boom">]><urlset>&x;</urlset>',
        b'<?xml version="1.0"?><!ENTITY x SYSTEM "file:///etc/passwd"><urlset/>',
        b"<?xml version='1.0'?><!doctype urlset><urlset/>",
    ],
)
def test_doctype_and_entities_are_refused(xml: bytes) -> None:
    with pytest.raises(ParseError, match="DOCTYPE/ENTITY"):
        parse_sitemap(xml)


def test_invalid_xml_and_unknown_root_raise_parse_error() -> None:
    with pytest.raises(ParseError):
        parse_sitemap(b"<urlset><url>")
    with pytest.raises(ParseError):
        parse_sitemap(b"<html/>")


def test_ordered_post_sitemaps_keep_the_climbing_dated_run() -> None:
    refs = parse_sitemap(_INDEX).sitemaps
    # post-sitemap.xml's late lastmod sits above every later child, so it is dropped.
    assert [ref.name for ref in ordered_post_sitemaps(refs)] == [
        "post-sitemap3",
        "post-sitemap4",
        "post-sitemap5",
        "post-sitemap6",
    ]


def test_select_post_sitemaps_spans_the_window() -> None:
    refs = parse_sitemap(_INDEX).sitemaps
    names = [r.name for r in select_post_sitemaps(refs, date(2022, 10, 1), date(2022, 10, 22))]
    assert names == ["post-sitemap5"]
    names = [r.name for r in select_post_sitemaps(refs, date(2022, 9, 1), date(2023, 1, 30))]
    assert names == ["post-sitemap4", "post-sitemap5", "post-sitemap6"]
    assert select_post_sitemaps(refs, date(2024, 9, 1), date(2024, 12, 1)) == []


def test_slug_week_and_year() -> None:
    assert week_of_slug("2022-college-football-week-5-viewership-x") == 5
    assert week_of_slug("college-football-week-12-viewership") == 12
    assert week_of_slug("silverlake-week-0-nbc-cfb-ratings") == 0
    assert week_of_slug("weekly-viewership") is None
    assert week_of_slug("midweek-5-ratings") is None
    assert year_of_slug("2022-college-football-week-5-viewership") == 2022
    assert year_of_slug("college-football-week-4-viewership-2022-x") == 2022
    assert year_of_slug("college-football-week-4-viewership") is None


# -- gap-week selection ----------------------------------------------------------------


def test_wanted_entry_keeps_only_gap_week_or_gap_date_college_ratings_posts() -> None:
    entries = parse_sitemap(_CHILD).urls
    weeks = gap_weeks({_GAP}, _WEEK_OF)
    assert weeks == {5}
    kept = [entry.url for entry in entries if wanted_entry(entry, 2022, weeks, [_GAP])]
    # Dropped: week 6, a 2021 slug, a preview with no ratings word, an NFL slug,
    # a non-college ratings post, a no-week post outside 0-7 days, a stale
    # yearless week slug, the schedules and nfl categories.
    assert kept == _KEPT
    assert not wanted_entry(UrlEntry(_WEEK5, None), 2023, weeks, [_GAP])
    assert not wanted_entry(UrlEntry(_NO_WEEK, None), 2022, weeks, [_GAP])
    assert not wanted_entry(UrlEntry(_GAME, None), 2022, weeks, [])


def test_postseason_gap_dates_plan_nothing() -> None:
    assert gap_weeks({date(2023, 1, 2)}, _WEEK_OF) == set()


def test_regular_weeks_by_date_skips_postseason() -> None:
    games = pl.DataFrame(
        {
            "season": [2022, 2022, 2022, 2020],
            "week": [5, 5, 1, 5],
            "season_type": ["regular", "regular", "postseason", "regular"],
            "date_et": [_GAP, _GAP, date(2023, 1, 2), date(2020, 10, 3)],
        }
    )
    assert regular_weeks_by_date(games) == {_GAP: {5}}


def test_post_request_path() -> None:
    req = post_request(2022, UrlEntry(_WEEK5, None))
    assert req.cache_path == (
        "aa/2022/posts/2022-college-football-week-5-viewership-silverlake-northfield.html"
    )
    assert req.source == "aa" and req.season == 2022


@pytest.fixture
def cache(vault_paths: DataPaths, mock_transport_factory, fake_clock) -> RawCache:
    handle = mock_transport_factory({})
    client = PoliteClient(
        transport=handle.transport,
        clock=fake_clock.now,
        sleep=fake_clock.sleep,
        rng=random.Random(0),
    )
    return RawCache(vault_paths, client)


def test_plan_grows_as_the_index_is_cached(cache: RawCache, vault_paths: DataPaths) -> None:
    collector = AaCollector(cache, _WEEK_OF)
    assert [req.cache_path for req in collector.plan(2022, {_GAP})] == ["aa/index/sitemap-1.xml"]

    index = vault_paths.raw / "aa" / "index"
    index.mkdir(parents=True)
    (index / "sitemap-1.xml").write_bytes(_INDEX)
    assert [req.cache_path for req in collector.plan(2022, {_GAP})] == [
        "aa/index/sitemap-1.xml",
        "aa/index/post-sitemap5.xml",
    ]

    (index / "post-sitemap5.xml").write_bytes(_CHILD)
    plan = collector.plan(2022, {_GAP})
    assert [req.url for req in plan[2:]] == _KEPT


def test_no_week_gap_plans_nothing(cache: RawCache) -> None:
    assert AaCollector(cache, _WEEK_OF).plan(2022, {date(2023, 1, 2)}) == []


# -- CLI data pass ---------------------------------------------------------------------


def _git(vault: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(vault), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _fresh(paths: DataPaths) -> None:
    append_policy_check(
        paths, PolicyCheck("aa", datetime.now(UTC), robots_ok=True, crawl_delay=None, terms_ok=True)
    )


@pytest.fixture
def one_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli, "_second_source_gaps", lambda _paths, _seasons: ({2022: {_GAP}}, _WEEK_OF)
    )


def _responses() -> dict[str, tuple[int, bytes, dict[str, str]]]:
    return {
        f"{_HOST}/robots.txt": (200, _ALLOW, {}),
        f"{_HOST}/sitemap_index.xml": (200, _INDEX, {}),
        f"{_HOST}/post-sitemap5.xml": (200, _CHILD, {}),
        **{url: (200, _post(url), {}) for url in _KEPT},
    }


def test_aa_refuses_without_a_fresh_policy_check(
    git_vault, mock_transport_factory, patched_client, one_gap, capsys
) -> None:
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    assert main(["collect", "aa", "--season", "2022"]) == 4
    assert handle.requests == []


def test_aa_dry_run_sends_nothing(
    git_vault, mock_transport_factory, patched_client, one_gap, capsys
) -> None:
    _fresh(git_vault)
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    assert main(["collect", "aa", "--season", "2022", "--dry-run"]) == 0
    assert handle.requests == []
    assert "planned 1, cached 0, new 1" in capsys.readouterr().out


def test_aa_live_pass_walks_index_child_then_week_posts(
    git_vault, mock_transport_factory, patched_client, one_gap
) -> None:
    _fresh(git_vault)
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    assert main(["collect", "aa", "--season", "2022"]) == 0
    assert [r.url for r in handle.requests] == [
        f"{_HOST}/robots.txt",
        f"{_HOST}/sitemap_index.xml",
        f"{_HOST}/post-sitemap5.xml",
        *_KEPT,
    ]
    posts = git_vault.raw / "aa" / "2022" / "posts"
    assert len(list(posts.iterdir())) == 5
    subject = _git(git_vault.vault, "log", "-1", "--format=%s")
    assert subject == "collect: aa 2022 (fetched 7, cached 0, not_modified 0, failed 0)"


def test_aa_live_pass_never_caches_a_post_the_build_could_not_read(
    git_vault, mock_transport_factory, patched_client, one_gap, capsys
) -> None:
    _fresh(git_vault)
    responses = _responses()
    responses[_KEPT[0]] = (200, b"<html><body><p>No canonical link.</p></body></html>", {})
    patched_client(mock_transport_factory(responses))
    assert main(["collect", "aa", "--season", "2022"]) == 4
    assert "fetched 6, cached 0, not_modified 0, failed 1" in capsys.readouterr().out
    posts = git_vault.raw / "aa" / "2022" / "posts"
    assert len(list(posts.iterdir())) == 4


def test_aa_max_requests_caps_new_fetches(
    git_vault, mock_transport_factory, patched_client, one_gap, capsys
) -> None:
    _fresh(git_vault)
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    assert main(["collect", "aa", "--season", "2022", "--max-requests", "2"]) == 0
    pages = [r.url for r in handle.requests if not r.url.endswith("/robots.txt")]
    assert pages == [f"{_HOST}/sitemap_index.xml", f"{_HOST}/post-sitemap5.xml"]
    assert "stopped: --max-requests 2 reached" in capsys.readouterr().out
    subject = _git(git_vault.vault, "log", "-1", "--format=%s")
    assert subject == "collect: aa 2022 (fetched 2, cached 0, not_modified 0, failed 0)"


def test_aa_failed_post_exits_4(git_vault, mock_transport_factory, patched_client, one_gap) -> None:
    _fresh(git_vault)
    responses = _responses()
    responses[_WEEK4] = (404, b"", {})
    handle = mock_transport_factory(responses)
    patched_client(handle)
    assert main(["collect", "aa", "--season", "2022"]) == 4
