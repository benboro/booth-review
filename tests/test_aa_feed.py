"""Awful Announcing feed watch: parse, match, state, poll (synthetic fixtures only)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx2
import pytest

from booth_review.config import DataPaths
from booth_review.errors import ParseError, VaultStateError
from booth_review.sources.aa.feed import (
    AA_FEED_CANDIDATES,
    FeedEntry,
    FeedNotVerifiedError,
    FeedStatusError,
    FeedWatchState,
    check_week,
    is_cfb_schedule_post,
    load_feed_state,
    match_week_post,
    parse_feed,
    record_blind_week,
    save_feed_state,
    verify_feed,
    week_key,
    week_start_et,
)
from booth_review.transport.client import PoliteClient

FIXTURES = Path(__file__).parent / "fixtures" / "aa"
FEED = (FIXTURES / "feed_schedules_synthetic.xml").read_bytes()
ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 3, 21, 30, tzinfo=ET)
CURRENT = "https://awfulannouncing.com/schedules/your-2026-week-10-college-football-announcing-schedule.html"
FEED_URL = AA_FEED_CANDIDATES["schedules"]


def _entry(link: str, title: str = "", cats: tuple[str, ...] = ("Schedules",)) -> FeedEntry:
    return FeedEntry(link, NOW, cats, title)


def _base(slug: str) -> str:
    return f"https://awfulannouncing.com/schedules/{slug}.html"


# -- parse ---------------------------------------------------------------------------------


def test_parse_feed_reads_link_date_categories_and_title() -> None:
    entries = parse_feed(FEED)
    assert len(entries) == 6
    first = entries[0]
    assert first.link == CURRENT
    assert first.pub_date is not None and first.pub_date.tzinfo is not None
    assert first.categories == ("Schedules", "College Football")
    assert "College Football" in first.title


def test_parse_feed_never_exposes_body_text() -> None:
    assert "SENTINEL" not in repr(parse_feed(FEED))


def test_parse_feed_refuses_doctype() -> None:
    with pytest.raises(ParseError):
        parse_feed((FIXTURES / "feed_doctype_synthetic.xml").read_bytes())


def test_parse_feed_malformed_raises() -> None:
    with pytest.raises(ParseError):
        parse_feed(b"<rss><channel><item>")


def test_parse_feed_empty_channel() -> None:
    assert parse_feed(b'<rss version="2.0"><channel></channel></rss>') == []


# -- match ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slug",
    [
        "your-2024-week-4-college-football-announcing-schedule",
        "week-11-cfb-announcing-schedule",
        "2023-college-football-week-3-announcers",
        "week-one-college-football-announcing-schedule-2024",
    ],
)
def test_is_cfb_schedule_post_accepts_slug_variants(slug: str) -> None:
    assert is_cfb_schedule_post(_entry(_base(slug)))


def test_is_cfb_schedule_post_rejections() -> None:
    assert not is_cfb_schedule_post(_entry(_base("nfl-week-16-announcing-schedule")))
    news = "https://awfulannouncing.com/college-football/coach-says-something.html"
    assert not is_cfb_schedule_post(_entry(news, "Coach says something", ("College Football",)))
    assert not is_cfb_schedule_post(
        _entry("https://example.com/schedules/week-4-college-football-announcing-schedule.html")
    )
    assert not is_cfb_schedule_post(
        _entry(_base("week-4-college-football-announcing-schedule") + "?utm=1")
    )
    assert not is_cfb_schedule_post(
        _entry(
            "http://awfulannouncing.com/schedules/week-4-college-football-announcing-schedule.html"
        )
    )


def test_match_week_post_picks_only_the_current_week_cfb_schedule() -> None:
    assert match_week_post(parse_feed(FEED), NOW) == CURRENT


def test_match_week_post_ignores_previous_week() -> None:
    entries = [e for e in parse_feed(FEED) if e.link != CURRENT]
    assert match_week_post(entries, NOW) is None
    next_week = datetime(2026, 11, 10, 10, 0, tzinfo=ET)
    assert match_week_post(parse_feed(FEED), next_week) is None


def test_match_week_post_never_compares_week_numbers() -> None:
    entry = FeedEntry(
        _base("week-3-college-football-announcing-schedule"),
        datetime(2026, 11, 3, 12, 0, tzinfo=ET),
        ("Schedules",),
        "",
    )
    assert match_week_post([entry], NOW) == entry.link


def test_week_start_et_is_monday_midnight() -> None:
    assert week_start_et(NOW) == datetime(2026, 11, 2, 0, 0, tzinfo=ET)
    with pytest.raises(ValueError):
        week_start_et(datetime(2026, 11, 3, 21, 30))  # noqa: DTZ001


# -- state ---------------------------------------------------------------------------------


def _state(**kw: object) -> FeedWatchState:
    base: dict[str, object] = {
        "verified_feed_url": FEED_URL,
        "verified_at": None,
        "etag": None,
        "last_modified": None,
        "checked_at": None,
        "weeks": {},
        "blind_weeks": [],
    }
    base.update(kw)
    return FeedWatchState(**base)  # type: ignore[arg-type]


def test_load_missing_is_empty(vault_paths: DataPaths) -> None:
    state = load_feed_state(vault_paths)
    assert state.weeks == {} and state.blind_weeks == [] and state.verified_feed_url is None


def test_load_invalid_raises(vault_paths: DataPaths) -> None:
    path = vault_paths.ledger / "aa_feed_watch.json"
    path.write_text("{nope", encoding="utf-8")
    with pytest.raises(VaultStateError):
        load_feed_state(vault_paths)
    path.write_text(json.dumps({"weeks": []}), encoding="utf-8")
    with pytest.raises(VaultStateError):
        load_feed_state(vault_paths)


def test_load_old_file_without_blind_weeks(vault_paths: DataPaths) -> None:
    (vault_paths.ledger / "aa_feed_watch.json").write_text(
        json.dumps({"weeks": {"2026-10": CURRENT}}), encoding="utf-8"
    )
    state = load_feed_state(vault_paths)
    assert state.blind_weeks == [] and state.weeks == {"2026-10": CURRENT}


def test_save_sorts_and_dedupes(vault_paths: DataPaths) -> None:
    save_feed_state(vault_paths, _state(blind_weeks=["2026-11", "2026-10", "2026-11"]))
    raw = json.loads((vault_paths.ledger / "aa_feed_watch.json").read_text(encoding="utf-8"))
    assert raw["blind_weeks"] == ["2026-10", "2026-11"]


@pytest.mark.parametrize(
    "state",
    [
        _state(weeks={"2026-10": "https://example.com/x"}),
        _state(weeks={"2026-10": CURRENT + "?a=1"}),
        _state(weeks={"2026-10": CURRENT + "<b>"}),
        _state(verified_feed_url="https://example.com/feed/"),
        _state(weeks={"bad key": CURRENT}),
        _state(blind_weeks=["x"]),
    ],
)
def test_save_refuses_bad_values(vault_paths: DataPaths, state: FeedWatchState) -> None:
    with pytest.raises(ValueError):
        save_feed_state(vault_paths, state)


def test_record_blind_week(vault_paths: DataPaths) -> None:
    save_feed_state(vault_paths, _state(etag='"v1"', weeks={"2026-09": CURRENT}))
    assert record_blind_week(vault_paths, season=2026, label="10") is True
    path = vault_paths.ledger / "aa_feed_watch.json"
    before = path.read_bytes()
    assert record_blind_week(vault_paths, season=2026, label="10") is False
    assert path.read_bytes() == before
    state = load_feed_state(vault_paths)
    assert state.blind_weeks == ["2026-10"]
    assert state.weeks == {"2026-09": CURRENT} and state.etag == '"v1"'


# -- poll ----------------------------------------------------------------------------------


class _Server:
    def __init__(
        self, feed: bytes = FEED, status: int = 200, headers: dict[str, str] | None = None
    ):
        self.feed = feed
        self.status = status
        self.headers = headers or {
            "ETag": '"abc"',
            "Last-Modified": "Tue, 03 Nov 2026 20:00:00 GMT",
        }
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/robots.txt":
            return httpx2.Response(200, content=b"User-agent: *\nAllow: /\n")
        self.requests.append(request)
        return httpx2.Response(self.status, content=self.feed, headers=self.headers)


def _client(server: _Server) -> PoliteClient:
    return PoliteClient(
        transport=httpx2.MockTransport(server), clock=lambda: 0.0, sleep=lambda s: None
    )


def _manifest_rows(paths: DataPaths) -> list[dict]:
    if not paths.manifest.is_file():
        return []
    return [json.loads(x) for x in paths.manifest.read_text(encoding="utf-8").splitlines()]


def test_check_week_requires_verified_feed(vault_paths: DataPaths) -> None:
    server = _Server()
    with pytest.raises(FeedNotVerifiedError):
        check_week(_client(server), vault_paths, season=2026, label="10", now=NOW)
    assert server.requests == []


def test_check_week_linked_week_makes_no_request(vault_paths: DataPaths) -> None:
    save_feed_state(vault_paths, _state(weeks={"2026-10": CURRENT}))
    server = _Server()
    result = check_week(_client(server), vault_paths, season=2026, label="10", now=NOW)
    assert (result.url, result.requested) == (CURRENT, False)
    assert server.requests == []


def test_check_week_blind_week_makes_no_request(vault_paths: DataPaths) -> None:
    save_feed_state(vault_paths, _state(blind_weeks=["2026-10"]))
    server = _Server()
    result = check_week(_client(server), vault_paths, season=2026, label="10", now=NOW)
    assert (result.url, result.requested, result.status) == (None, False, None)
    assert server.requests == []


def test_check_week_sends_validators_and_handles_304(vault_paths: DataPaths) -> None:
    save_feed_state(
        vault_paths, _state(etag='"old"', last_modified="Mon, 02 Nov 2026 00:00:00 GMT")
    )
    server = _Server(feed=b"", status=304, headers={})
    result = check_week(_client(server), vault_paths, season=2026, label="10", now=NOW)
    assert (result.url, result.requested, result.status) == (None, True, 304)
    req = server.requests[0]
    assert req.headers["If-None-Match"] == '"old"'
    assert req.headers["If-Modified-Since"] == "Mon, 02 Nov 2026 00:00:00 GMT"
    state = load_feed_state(vault_paths)
    assert state.etag == '"old"' and state.checked_at is not None


def test_check_week_200_stores_link_and_first_url_wins(vault_paths: DataPaths) -> None:
    save_feed_state(vault_paths, _state())
    server = _Server()
    result = check_week(_client(server), vault_paths, season=2026, label="10", now=NOW)
    assert (result.url, result.requested, result.status) == (CURRENT, True, 200)
    state = load_feed_state(vault_paths)
    assert state.weeks == {week_key(2026, "10"): CURRENT}
    assert state.etag == '"abc"' and state.last_modified and state.checked_at
    # A later, different matching URL for the same key never replaces the first.
    save_feed_state(vault_paths, _state(weeks={}, blind_weeks=[]))
    other = FEED.replace(b"your-2026-week-10-college", b"your-2026-week-ten-college")
    check_week(_client(_Server(other)), vault_paths, season=2026, label="10", now=NOW)
    first = load_feed_state(vault_paths).weeks["2026-10"]
    later = FEED.replace(b"your-2026-week-10-college", b"changed-college")
    save_feed_state(vault_paths, _state(weeks={"2026-10": first}))
    again = check_week(_client(_Server(later)), vault_paths, season=2026, label="10", now=NOW)
    assert again.url == first


def test_check_week_other_status_raises_after_audit(vault_paths: DataPaths) -> None:
    save_feed_state(vault_paths, _state())
    with pytest.raises(FeedStatusError) as info:
        check_week(
            _client(_Server(status=500, headers={})), vault_paths, season=2026, label="10", now=NOW
        )
    assert info.value.status == 500
    assert len(_manifest_rows(vault_paths)) == 1


def test_one_pathless_manifest_row_per_request(vault_paths: DataPaths) -> None:
    save_feed_state(vault_paths, _state())
    check_week(_client(_Server()), vault_paths, season=2026, label="10", now=NOW)
    rows = _manifest_rows(vault_paths)
    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "aa" and row["url"] == FEED_URL
    assert row["path"] is None and row["sha256"] is None and row["bytes"] is None


def test_body_text_never_reaches_vault_or_logs(
    vault_paths: DataPaths, caplog: pytest.LogCaptureFixture
) -> None:
    save_feed_state(vault_paths, _state())
    with caplog.at_level(logging.DEBUG):
        check_week(_client(_Server()), vault_paths, season=2026, label="10", now=NOW)
        verify_feed(_client(_Server()), vault_paths, "schedules", NOW)
    for path in vault_paths.vault.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert b"SENTINEL" not in data, path
    assert "SENTINEL" not in caplog.text
    assert not (vault_paths.raw / "aa").exists()


def test_verify_feed_records_verified_feed_and_clears_validators(vault_paths: DataPaths) -> None:
    save_feed_state(
        vault_paths,
        _state(verified_feed_url=None, etag='"x"', last_modified="y", weeks={"2026-09": CURRENT}),
    )
    server = _Server()
    result = verify_feed(_client(server), vault_paths, "schedules", NOW)
    assert "If-None-Match" not in server.requests[0].headers
    assert result.verified and result.entries == 6
    assert CURRENT in result.cfb_links
    assert any("nfl-week-9" in link for link in result.other_schedule_links)
    state = load_feed_state(vault_paths)
    assert state.verified_feed_url == FEED_URL and state.verified_at is not None
    assert state.etag is None and state.last_modified is None
    assert state.weeks == {"2026-09": CURRENT}


def test_verify_feed_without_cfb_post_leaves_state(vault_paths: DataPaths) -> None:
    feed = b'<rss version="2.0"><channel><item><title>x</title><link>https://awfulannouncing.com/media/x.html</link></item></channel></rss>'
    result = verify_feed(_client(_Server(feed)), vault_paths, "site", NOW)
    assert not result.verified
    assert load_feed_state(vault_paths).verified_feed_url is None


def test_verify_feed_unknown_candidate(vault_paths: DataPaths) -> None:
    with pytest.raises(ValueError):
        verify_feed(_client(_Server()), vault_paths, "bogus", NOW)


def test_utc_now_is_accepted(vault_paths: DataPaths) -> None:
    save_feed_state(vault_paths, _state())
    now = datetime(2026, 11, 4, 2, 30, tzinfo=UTC)  # Tue 21:30 ET
    result = check_week(_client(_Server()), vault_paths, season=2026, label="10", now=now)
    assert result.url == CURRENT


def test_match_week_post_keeps_a_post_dated_just_after_now() -> None:
    entry = FeedEntry(
        _base("week-10-college-football-announcing-schedule"),
        NOW + timedelta(minutes=5),
        ("Schedules",),
        "",
    )
    assert match_week_post([entry], NOW) == entry.link


def test_naive_pubdate_is_utc() -> None:
    xml = (
        b'<rss version="2.0"><channel><item><title>t</title>'
        b"<link>https://awfulannouncing.com/schedules/x.html</link>"
        b"<pubDate>Tue, 03 Nov 2026 12:00:00 -0000</pubDate></item></channel></rss>"
    )
    pub = parse_feed(xml)[0].pub_date
    assert pub is not None and pub.utcoffset() == timedelta(0)


def test_category_names_are_normalized() -> None:
    link = "https://awfulannouncing.com/media/week-4-college-football-announcing-schedule.html"
    assert is_cfb_schedule_post(_entry(link, "", ("College Football",)))
    assert is_cfb_schedule_post(_entry(link, "", ("Schedules",)))


def test_plural_schedules_token_is_accepted_but_other_leagues_still_rejected() -> None:
    assert is_cfb_schedule_post(_entry(_base("week-4-college-football-announcing-schedules")))
    assert not is_cfb_schedule_post(_entry(_base("week-4-nfl-college-announcing-schedules")))


def test_save_refuses_a_url_with_whitespace(vault_paths: DataPaths) -> None:
    bad = _state(weeks={"2026-10": "https://awfulannouncing.com/schedules/a b.html"})
    with pytest.raises(ValueError):
        save_feed_state(vault_paths, bad)
