"""04.19 D-10/D-11: The TV Ratings Guide index parser and gap-only data pass.

Every page is invented (tests/fixtures/tvrg/); every request goes to a mock
transport, so nothing leaves the machine.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from booth_review import cli
from booth_review.cli import main
from booth_review.config import DataPaths
from booth_review.sources.gapcollect import RequestBudget, safe_slug
from booth_review.sources.policy import PolicyCheck, append_policy_check
from booth_review.sources.tvrg.collector import (
    TvrgCollector,
    index_months,
    post_request,
    select_posts,
)
from booth_review.sources.tvrg.index import (
    PostRef,
    is_ratings_title,
    parse_archive,
    post_url,
    title_date,
)
from booth_review.transport.cache import RawCache

_FIXTURES = Path(__file__).parent / "fixtures" / "tvrg"
_HOST = "https://www.thetvratingsguide.com"
_ALLOW = b"User-agent: *\nAllow: /\n"
_ARCHIVE = (_FIXTURES / "archive_synthetic.html").read_bytes()
_OLDER = f"{_HOST}/search?updated-max=2022-10-01T10:00:00-07:00&max-results=5"
_PAGE2 = (
    b"<html><body><h3 class='post-title entry-title'>"
    b"<a href='https://www.thetvratingsguide.com/2022/10/friday-cable-ratings-93022-example.html'>"
    b"Friday Cable Ratings 9/30/22: Example Late Show</a></h3></body></html>"
)
_EMPTY_ARCHIVE = b"<html><body><p>No posts.</p></body></html>"
_POST = b"<html><body><p>Invented post body.</p></body></html>"

_SAT_CABLE = f"{_HOST}/2022/10/saturday-cable-ratings-10122-silverlake.html"
_SAT_TV = f"{_HOST}/2022/10/saturday-tv-ratings-10122-northfield.html"
_FRI_TV = f"{_HOST}/2022/10/friday-tv-ratings-93022-example-drama.html"
_SUN_CABLE = f"{_HOST}/2022/10/sunday-cable-ratings-10222-lakeside.html"
_FRI_CABLE = f"{_HOST}/2022/10/friday-cable-ratings-93022-example.html"
_GAP = date(2022, 10, 1)


# -- index parser --------------------------------------------------------------------


def test_parse_archive_reads_main_posts_then_sidebar_and_the_older_link() -> None:
    page = parse_archive(_ARCHIVE)
    urls = [post.url for post in page.posts]
    assert urls == [
        _SAT_CABLE,
        _SAT_TV,
        _FRI_TV,
        f"{_HOST}/2022/10/monday-tv-ratings-10322-lakeside.html",
        f"{_HOST}/2022/10/example-show-renewed-for-season-3.html",
        _SUN_CABLE,
        f"{_HOST}/2022/10/thursday-cable-ratings-92922-example.html",
    ]
    first = page.posts[0]
    # The main column's full title wins over the sidebar's truncated one.
    assert first.title == "Saturday Cable Ratings 10/1/22: Silverlake Rolls"
    assert first.published == date(2022, 10, 3)
    assert page.posts[5].published is None
    assert page.next_url == _OLDER


def test_parse_archive_ignores_off_host_http_and_non_post_links() -> None:
    urls = {post.url for post in parse_archive(_ARCHIVE).posts}
    assert not any("example.com" in url or url.startswith("http:") for url in urls)
    assert f"{_HOST}/search/label/Ratings" not in urls
    assert post_url(f"{_HOST}/2022/10/") is None
    assert post_url(f"{_HOST}/2022/10/a-post.html?m=1") is None
    assert post_url("https://thetvratingsguide.com/2022/10/a-post.html") is None
    assert post_url(f"{_HOST}/2022/10/a-post.html#comments") == f"{_HOST}/2022/10/a-post.html"


def test_parse_archive_has_no_next_url_without_a_static_pager() -> None:
    assert parse_archive(_PAGE2).next_url is None
    pager = b"<a class='blog-pager-older-link' href='https://example.com/search?x=1'>Older</a>"
    assert parse_archive(pager).next_url is None


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Saturday Cable Ratings 10/1/22: Silverlake Rolls", date(2022, 10, 1)),
        ("Saturday TV Ratings 9/3/2022: Example", date(2022, 9, 3)),
        ("Saturday 10.1.2022 Ratings", date(2022, 10, 1)),
        ("Sunday Cable Ratings 13/40/22: Bad Date", None),
        ("Example Show Season 2 Episode 9", None),
        ("Ratings 10/1.22 mixed separators", None),
    ],
)
def test_title_date(title: str, expected: date | None) -> None:
    assert title_date(title) == expected


def test_is_ratings_title_needs_the_word_and_a_date() -> None:
    assert is_ratings_title("Friday TV Ratings 9/30/22: Example")
    assert not is_ratings_title("Predict the Future Ratings: Example")
    assert not is_ratings_title("Friday Recap 9/30/22")


# -- gap-only selection ----------------------------------------------------------------


def test_index_months_adds_the_following_month() -> None:
    assert index_months({date(2022, 10, 1)}) == [(2022, 10), (2022, 11)]
    assert index_months({date(2022, 12, 31), date(2022, 12, 30)}) == [(2022, 12), (2023, 1)]


def test_select_posts_keeps_ratings_posts_within_one_day_exact_first() -> None:
    posts = parse_archive(_ARCHIVE).posts
    picked = [post.url for post in select_posts(posts, {_GAP})]
    assert picked == [_SAT_CABLE, _SAT_TV, _FRI_TV, _SUN_CABLE]


def test_select_posts_drops_duplicates() -> None:
    post = PostRef(_SAT_TV, "Saturday TV Ratings 10/1/22: X", None)
    assert select_posts([post, post], {_GAP}) == [post]


def test_post_request_paths_are_sanitized() -> None:
    req = post_request(2022, f"{_HOST}/2022/10/Saturday_TV.Ratings.html")
    assert req.cache_path == "tvrg/2022/posts/2022-10-saturday-tv-ratings.html"
    assert req.source == "tvrg" and req.season == 2022
    assert safe_slug("A--b__C!") == "a-b-c"


@pytest.fixture
def cache(vault_paths: DataPaths, mock_transport_factory, fake_clock) -> RawCache:
    import random

    from booth_review.transport.client import PoliteClient

    handle = mock_transport_factory({})
    client = PoliteClient(
        transport=handle.transport,
        clock=fake_clock.now,
        sleep=fake_clock.sleep,
        rng=random.Random(0),
    )
    return RawCache(vault_paths, client)


def test_plan_requests_archives_before_any_index_is_cached(
    cache: RawCache, vault_paths: DataPaths
) -> None:
    collector = TvrgCollector(cache)
    plan = collector.plan(2022, {_GAP})
    assert [req.url for req in plan] == [f"{_HOST}/2022/10/", f"{_HOST}/2022/11/"]
    assert [req.cache_path for req in plan] == [
        "tvrg/index/2022-10.html",
        "tvrg/index/2022-11.html",
    ]
    assert collector.plan_posts(2022, {_GAP}) == []


def test_plan_reads_posts_from_cached_archives_and_follows_the_pager(
    cache: RawCache, vault_paths: DataPaths
) -> None:
    index = vault_paths.raw / "tvrg" / "index"
    index.mkdir(parents=True)
    (index / "2022-10.html").write_bytes(_ARCHIVE)
    collector = TvrgCollector(cache)
    index_plan = collector.plan_index(2022, {_GAP})
    assert [req.cache_path for req in index_plan] == [
        "tvrg/index/2022-10.html",
        "tvrg/index/2022-10-p2.html",
        "tvrg/index/2022-11.html",
    ]
    assert index_plan[1].url == _OLDER
    posts = collector.plan_posts(2022, {_GAP})
    assert [req.url for req in posts] == [_SAT_CABLE, _SAT_TV, _FRI_TV, _SUN_CABLE]
    assert posts[0].cache_path == (
        "tvrg/2022/posts/2022-10-saturday-cable-ratings-10122-silverlake.html"
    )


def test_no_gap_dates_plans_nothing(cache: RawCache) -> None:
    assert TvrgCollector(cache).plan(2022, set()) == []


# -- CLI data pass ---------------------------------------------------------------------


def _fresh(paths: DataPaths, *, age: timedelta = timedelta(0), terms: bool | None = True) -> None:
    append_policy_check(
        paths,
        PolicyCheck(
            "tvrg",
            datetime.now(UTC) - age,
            robots_ok=True,
            crawl_delay=None,
            terms_ok=terms,
        ),
    )


@pytest.fixture
def one_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli, "_second_source_gaps", lambda _paths, _seasons: ({2022: {_GAP}}, {_GAP: {5}})
    )


def _responses() -> dict[str, tuple[int, bytes, dict[str, str]]]:
    return {
        f"{_HOST}/robots.txt": (200, _ALLOW, {}),
        f"{_HOST}/2022/10/": (200, _ARCHIVE, {}),
        _OLDER: (200, _PAGE2, {}),
        f"{_HOST}/2022/11/": (200, _EMPTY_ARCHIVE, {}),
        _SAT_CABLE: (200, _POST, {}),
        _SAT_TV: (200, _POST, {}),
        _FRI_TV: (200, _POST, {}),
        _SUN_CABLE: (200, _POST, {}),
        _FRI_CABLE: (200, _POST, {}),
    }


def _git(vault: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(vault), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.mark.parametrize(
    ("age", "terms"),
    [(timedelta(days=31), True), (timedelta(0), None)],
    ids=["stale", "terms-not-confirmed"],
)
def test_data_pass_refuses_without_a_fresh_approved_policy_check(
    git_vault, mock_transport_factory, patched_client, one_gap, capsys, age, terms
) -> None:
    _fresh(git_vault, age=age, terms=terms)
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    assert main(["collect", "tvrg", "--season", "2022"]) == 4
    assert handle.requests == []
    assert "policy check older than 30 days or not approved" in capsys.readouterr().err


def test_data_pass_refuses_with_no_ledger(
    git_vault, mock_transport_factory, patched_client, one_gap
) -> None:
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    assert main(["collect", "tvrg", "--season", "2022"]) == 4
    assert handle.requests == []


def test_dry_run_prints_counts_and_sends_nothing(
    git_vault, mock_transport_factory, patched_client, one_gap, capsys
) -> None:
    _fresh(git_vault)
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    head = _git(git_vault.vault, "rev-parse", "HEAD")
    assert main(["collect", "tvrg", "--season", "2022", "--dry-run"]) == 0
    assert handle.requests == []
    out = capsys.readouterr().out
    assert "planned 2, cached 0, new 2" in out
    assert "http" not in out  # counts only
    assert _git(git_vault.vault, "rev-parse", "HEAD") == head


def test_live_pass_fetches_archives_then_gap_posts_and_commits(
    git_vault, mock_transport_factory, patched_client, one_gap, capsys
) -> None:
    _fresh(git_vault)
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    assert main(["collect", "tvrg", "--season", "2022"]) == 0
    assert [r.url for r in handle.requests] == [
        f"{_HOST}/robots.txt",
        f"{_HOST}/2022/10/",
        _OLDER,
        _SAT_CABLE,
        _SAT_TV,
        _FRI_CABLE,
        _FRI_TV,
        _SUN_CABLE,
        f"{_HOST}/2022/11/",
    ]
    ua = handle.requests[1].headers["user-agent"]
    assert ua.startswith("booth-review/")
    posts = git_vault.raw / "tvrg" / "2022" / "posts"
    assert len(list(posts.iterdir())) == 5
    subject = _git(git_vault.vault, "log", "-1", "--format=%s")
    assert subject == "collect: tvrg 2022 (fetched 8, cached 0, not_modified 0, failed 0)"
    files = set(_git(git_vault.vault, "show", "--name-only", "--format=", "HEAD").splitlines())
    assert all(f.startswith(("raw/tvrg/", "raw/_robots/", "ledger/")) for f in files), files

    # A second run serves everything from the cache: no page is re-fetched.
    handle2 = mock_transport_factory(_responses())
    patched_client(handle2)
    assert main(["collect", "tvrg", "--season", "2022"]) == 0
    assert [r.url for r in handle2.requests] == []


def test_max_requests_stops_after_the_cap_and_commits_partial_work(
    git_vault, mock_transport_factory, patched_client, one_gap, capsys
) -> None:
    _fresh(git_vault)
    handle = mock_transport_factory(_responses())
    patched_client(handle)
    assert main(["collect", "tvrg", "--season", "2022", "--max-requests", "2"]) == 0
    pages = [r.url for r in handle.requests if not r.url.endswith("/robots.txt")]
    assert pages == [f"{_HOST}/2022/10/", _OLDER]
    out = capsys.readouterr().out
    assert "stopped: --max-requests 2 reached" in out
    subject = _git(git_vault.vault, "log", "-1", "--format=%s")
    assert subject == "collect: tvrg 2022 (fetched 2, cached 0, not_modified 0, failed 0)"


def test_robots_disallow_stops_the_run_with_exit_4(
    git_vault, mock_transport_factory, patched_client, one_gap, capsys
) -> None:
    _fresh(git_vault)
    responses = _responses()
    responses[f"{_HOST}/robots.txt"] = (200, b"User-agent: *\nDisallow: /\n", {})
    handle = mock_transport_factory(responses)
    patched_client(handle)
    assert main(["collect", "tvrg", "--season", "2022"]) == 4
    assert [r.url for r in handle.requests] == [f"{_HOST}/robots.txt"]
    assert "error:" in capsys.readouterr().err


def test_long_crawl_delay_stops_the_run(
    git_vault, mock_transport_factory, patched_client, one_gap
) -> None:
    _fresh(git_vault)
    responses = _responses()
    responses[f"{_HOST}/robots.txt"] = (200, b"User-agent: *\nCrawl-delay: 30\n", {})
    handle = mock_transport_factory(responses)
    patched_client(handle)
    assert main(["collect", "tvrg", "--season", "2022"]) == 4
    assert [r.url for r in handle.requests] == [f"{_HOST}/robots.txt"]


def test_season_outside_2021_2024_is_refused(git_vault, capsys) -> None:
    assert main(["collect", "tvrg", "--season", "2019"]) == 2
    assert "2021-2024" in capsys.readouterr().err


def test_season_with_policy_check_is_refused(git_vault, capsys) -> None:
    assert main(["collect", "tvrg", "--season", "2022", "--policy-check"]) == 2


def test_request_budget_counts_only_new_pages(cache: RawCache, vault_paths: DataPaths) -> None:
    index = vault_paths.raw / "tvrg" / "index"
    index.mkdir(parents=True)
    (index / "2022-10.html").write_bytes(_ARCHIVE)
    budget = RequestBudget(1)
    cached_req, new_req = TvrgCollector(cache).plan_index(2022, {_GAP})[:2]
    assert budget.allows(cache, cached_req) and budget.spent == 0
    assert budget.allows(cache, new_req) and budget.spent == 1
    assert not budget.allows(cache, new_req) and budget.exhausted
