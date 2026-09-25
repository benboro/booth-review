"""Behavioral tests for PoliteClient: UA, robots, pacing, allow-list, retries."""

from __future__ import annotations

import random
from collections.abc import Callable

import httpx2
import pytest

from booth_review.config import USER_AGENT
from booth_review.errors import (
    FetchError,
    RobotsDisallowedError,
    RobotsUnavailableError,
    UnknownHostError,
)
from booth_review.transport.client import PoliteClient
from booth_review.transport.types import Validators

Handler = Callable[[httpx2.Request], httpx2.Response]


def _client(
    handler: Handler,
    *,
    fake_clock=None,
    rng: random.Random | None = None,
) -> PoliteClient:
    kwargs: dict = {"transport": httpx2.MockTransport(handler)}
    if fake_clock is not None:
        kwargs["clock"] = fake_clock.now
        kwargs["sleep"] = fake_clock.sleep
    if rng is not None:
        kwargs["rng"] = rng
    return PoliteClient(**kwargs)


def _recording_handler(
    responses: dict[str, tuple[int, bytes, dict[str, str]]],
    log: list[httpx2.Request],
) -> Handler:
    def handler(request: httpx2.Request) -> httpx2.Response:
        log.append(request)
        key = str(request.url)
        if key not in responses:
            raise AssertionError(f"no response configured for {key}")
        status, body, headers = responses[key]
        return httpx2.Response(status, content=body, headers=headers, request=request)

    return handler


ALLOW_ALL_ROBOTS = (404, b"not found", {})


# -- User agent -------------------------------------------------------------


def test_user_agent_sent_on_page_and_robots_requests() -> None:
    log: list[httpx2.Request] = []
    responses = {
        "https://506sports.com/robots.txt": ALLOW_ALL_ROBOTS,
        "https://506sports.com/ncaaf.php?yr=2025&wk=1": (200, b"<html></html>", {}),
    }
    client = _client(_recording_handler(responses, log))

    client.fetch("https://506sports.com/ncaaf.php?yr=2025&wk=1")

    assert len(log) == 2
    for req in log:
        assert req.headers["user-agent"] == USER_AGENT


# -- Robots handling ----------------------------------------------------------


def test_robots_404_allows_all() -> None:
    log: list[httpx2.Request] = []
    responses = {
        "https://506sports.com/robots.txt": ALLOW_ALL_ROBOTS,
        "https://506sports.com/ncaaf.php?yr=2025&wk=1": (200, b"ok", {}),
    }
    client = _client(_recording_handler(responses, log))

    resp = client.fetch("https://506sports.com/ncaaf.php?yr=2025&wk=1")

    assert resp.status_code == 200


def test_robots_disallow_blocks_page_and_page_never_requested() -> None:
    log: list[httpx2.Request] = []
    robots_body = b"User-agent: *\nDisallow: /ncaaf.php\n"
    responses = {
        "https://506sports.com/robots.txt": (200, robots_body, {}),
        "https://506sports.com/ncaaf.php?yr=2025&wk=1": (200, b"ok", {}),
    }
    client = _client(_recording_handler(responses, log))

    with pytest.raises(RobotsDisallowedError):
        client.fetch("https://506sports.com/ncaaf.php?yr=2025&wk=1")

    requested_urls = [str(req.url) for req in log]
    assert requested_urls == ["https://506sports.com/robots.txt"]


def test_robots_403_disallows_all() -> None:
    log: list[httpx2.Request] = []
    responses = {
        "https://506sports.com/robots.txt": (403, b"forbidden", {}),
        "https://506sports.com/ncaaf.php?yr=2025&wk=1": (200, b"ok", {}),
    }
    client = _client(_recording_handler(responses, log))

    with pytest.raises(RobotsDisallowedError):
        client.fetch("https://506sports.com/ncaaf.php?yr=2025&wk=1")


def test_robots_5xx_raises_unavailable() -> None:
    log: list[httpx2.Request] = []
    responses = {
        "https://506sports.com/robots.txt": (503, b"boom", {}),
    }
    client = _client(_recording_handler(responses, log))

    with pytest.raises(RobotsUnavailableError):
        client.fetch("https://506sports.com/ncaaf.php?yr=2025&wk=1")


def test_robots_fetched_once_per_host() -> None:
    log: list[httpx2.Request] = []
    responses = {
        "https://506sports.com/robots.txt": ALLOW_ALL_ROBOTS,
        "https://506sports.com/ncaaf.php?yr=2025&wk=1": (200, b"ok", {}),
        "https://506sports.com/ncaaf.php?yr=2025&wk=2": (200, b"ok", {}),
    }
    client = _client(_recording_handler(responses, log))

    client.fetch("https://506sports.com/ncaaf.php?yr=2025&wk=1")
    client.fetch("https://506sports.com/ncaaf.php?yr=2025&wk=2")

    robots_requests = [req for req in log if str(req.url).endswith("/robots.txt")]
    assert len(robots_requests) == 1


def test_robots_listener_notified() -> None:
    log: list[httpx2.Request] = []
    responses = {
        "https://506sports.com/robots.txt": ALLOW_ALL_ROBOTS,
        "https://506sports.com/ncaaf.php?yr=2025&wk=1": (200, b"ok", {}),
    }
    client = _client(_recording_handler(responses, log))
    seen: list[tuple[str, int]] = []
    client.add_robots_listener(lambda host, resp: seen.append((host, resp.status_code)))

    client.fetch("https://506sports.com/ncaaf.php?yr=2025&wk=1")

    assert seen == [("506sports.com", 404)]


# -- Pacing -------------------------------------------------------------------


def test_pacing_first_request_to_host_does_not_sleep(fake_clock) -> None:
    log: list[httpx2.Request] = []
    responses = {
        "https://506sports.com/robots.txt": ALLOW_ALL_ROBOTS,
        "https://506sports.com/ncaaf.php?yr=2025&wk=1": (200, b"ok", {}),
    }
    client = _client(_recording_handler(responses, log), fake_clock=fake_clock)

    client.fetch("https://506sports.com/ncaaf.php?yr=2025&wk=1")

    # Only the page request (the second request to this host) waits;
    # the robots.txt fetch, as the first request, never calls sleep().
    assert fake_clock.sleeps == [10.0]


def test_pacing_506_sleeps_10s_between_requests(fake_clock) -> None:
    log: list[httpx2.Request] = []
    responses = {
        "https://506sports.com/robots.txt": ALLOW_ALL_ROBOTS,
        "https://506sports.com/ncaaf.php?yr=2025&wk=1": (200, b"ok", {}),
        "https://506sports.com/ncaaf.php?yr=2025&wk=2": (200, b"ok", {}),
    }
    client = _client(_recording_handler(responses, log), fake_clock=fake_clock)

    client.fetch("https://506sports.com/ncaaf.php?yr=2025&wk=1")
    fake_clock.sleeps.clear()
    client.fetch("https://506sports.com/ncaaf.php?yr=2025&wk=2")

    assert fake_clock.sleeps == [10.0]


def test_pacing_ratingsref_sleeps_in_jitter_range(fake_clock) -> None:
    log: list[httpx2.Request] = []
    responses = {
        "https://ratingsreference.com/robots.txt": ALLOW_ALL_ROBOTS,
        "https://ratingsreference.com/api/telecast/a.json": (200, b"{}", {}),
        "https://ratingsreference.com/api/telecast/b.json": (200, b"{}", {}),
    }
    client = _client(
        _recording_handler(responses, log), fake_clock=fake_clock, rng=random.Random(0)
    )

    client.fetch("https://ratingsreference.com/api/telecast/a.json")
    fake_clock.sleeps.clear()
    client.fetch("https://ratingsreference.com/api/telecast/b.json")

    assert len(fake_clock.sleeps) == 1
    assert 2.0 <= fake_clock.sleeps[0] <= 3.0


def test_pacing_cfbd_sleeps_1s(fake_clock) -> None:
    log: list[httpx2.Request] = []
    responses = {
        "https://api.collegefootballdata.com/robots.txt": ALLOW_ALL_ROBOTS,
        "https://api.collegefootballdata.com/games?year=2025": (200, b"[]", {}),
        "https://api.collegefootballdata.com/games?year=2024": (200, b"[]", {}),
    }
    client = _client(_recording_handler(responses, log), fake_clock=fake_clock)

    client.fetch("https://api.collegefootballdata.com/games?year=2025")
    fake_clock.sleeps.clear()
    client.fetch("https://api.collegefootballdata.com/games?year=2024")

    assert fake_clock.sleeps == [1.0]


# -- Host allow-list ------------------------------------------------------------


def test_unknown_host_raises_and_sends_nothing() -> None:
    log: list[httpx2.Request] = []
    client = _client(_recording_handler({}, log))

    with pytest.raises(UnknownHostError):
        client.fetch("https://www.sportsmediawatch.com/2025/09/some-article")

    assert log == []


def test_redirect_to_unknown_host_raises() -> None:
    log: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        log.append(request)
        url = str(request.url)
        if url == "https://506sports.com/robots.txt":
            status, body, headers = ALLOW_ALL_ROBOTS
            return httpx2.Response(status, content=body, headers=headers, request=request)
        if url == "https://506sports.com/redirected.php":
            return httpx2.Response(
                302, headers={"Location": "https://evil-mirror.example.com/"}, request=request
            )
        if url == "https://evil-mirror.example.com/":
            return httpx2.Response(200, content=b"ok", request=request)
        raise AssertionError(f"unexpected url {url}")

    client = _client(handler)

    with pytest.raises(UnknownHostError):
        client.fetch("https://506sports.com/redirected.php")


# -- Conditional requests / 304 -------------------------------------------------


def test_304_returned_without_raising() -> None:
    log: list[httpx2.Request] = []
    responses = {
        "https://ratingsreference.com/robots.txt": ALLOW_ALL_ROBOTS,
        "https://ratingsreference.com/api/telecast/a.json": (304, b"", {}),
    }
    client = _client(_recording_handler(responses, log))

    resp = client.fetch("https://ratingsreference.com/api/telecast/a.json")

    assert resp.status_code == 304


def test_conditional_headers_sent_only_when_validators_given() -> None:
    log: list[httpx2.Request] = []
    responses = {
        "https://ratingsreference.com/robots.txt": ALLOW_ALL_ROBOTS,
        "https://ratingsreference.com/api/telecast/a.json": (200, b"{}", {}),
    }
    client = _client(_recording_handler(responses, log))

    client.fetch("https://ratingsreference.com/api/telecast/a.json")
    page_request = next(r for r in log if str(r.url).endswith("a.json"))
    assert "if-none-match" not in page_request.headers
    assert "if-modified-since" not in page_request.headers

    log2: list[httpx2.Request] = []
    client2 = _client(_recording_handler(responses, log2))
    client2.fetch(
        "https://ratingsreference.com/api/telecast/a.json",
        validators=Validators(etag='"abc"', last_modified="Wed, 21 Oct 2015 07:28:00 GMT"),
    )
    page_request2 = next(r for r in log2 if str(r.url).endswith("a.json"))
    assert page_request2.headers["if-none-match"] == '"abc"'
    assert page_request2.headers["if-modified-since"] == "Wed, 21 Oct 2015 07:28:00 GMT"


# -- Retry policy ----------------------------------------------------------------


def test_ratingsref_retries_503_503_200() -> None:
    log: list[httpx2.Request] = []
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        log.append(request)
        url = str(request.url)
        if url == "https://ratingsreference.com/robots.txt":
            status, body, headers = ALLOW_ALL_ROBOTS
            return httpx2.Response(status, content=body, headers=headers, request=request)
        if url == "https://ratingsreference.com/api/telecast/a.json":
            call_count["n"] += 1
            if call_count["n"] < 3:
                return httpx2.Response(503, content=b"busy", request=request)
            return httpx2.Response(200, content=b"{}", request=request)
        raise AssertionError(f"unexpected url {url}")

    client = _client(handler)

    resp = client.fetch("https://ratingsreference.com/api/telecast/a.json")

    assert resp.status_code == 200
    assert call_count["n"] == 3


def test_cfbd_no_retry_on_503() -> None:
    log: list[httpx2.Request] = []
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        log.append(request)
        url = str(request.url)
        if url == "https://api.collegefootballdata.com/robots.txt":
            status, body, headers = ALLOW_ALL_ROBOTS
            return httpx2.Response(status, content=body, headers=headers, request=request)
        if url == "https://api.collegefootballdata.com/games?year=2025":
            call_count["n"] += 1
            return httpx2.Response(503, content=b"busy", request=request)
        raise AssertionError(f"unexpected url {url}")

    client = _client(handler)

    resp = client.fetch("https://api.collegefootballdata.com/games?year=2025")

    assert resp.status_code == 503
    assert call_count["n"] == 1


def test_cfbd_retries_on_connect_error() -> None:
    log: list[httpx2.Request] = []
    call_count = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        log.append(request)
        url = str(request.url)
        if url == "https://api.collegefootballdata.com/robots.txt":
            status, body, headers = ALLOW_ALL_ROBOTS
            return httpx2.Response(status, content=body, headers=headers, request=request)
        if url == "https://api.collegefootballdata.com/games?year=2025":
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise httpx2.ConnectError("boom", request=request)
            return httpx2.Response(200, content=b"[]", request=request)
        raise AssertionError(f"unexpected url {url}")

    client = _client(handler)

    resp = client.fetch("https://api.collegefootballdata.com/games?year=2025")

    assert resp.status_code == 200
    assert call_count["n"] == 2


def test_fetch_error_after_retries_exhausted() -> None:
    log: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        log.append(request)
        url = str(request.url)
        if url == "https://506sports.com/robots.txt":
            status, body, headers = ALLOW_ALL_ROBOTS
            return httpx2.Response(status, content=body, headers=headers, request=request)
        raise httpx2.ConnectError("still down", request=request)

    client = _client(handler)

    with pytest.raises(FetchError):
        client.fetch("https://506sports.com/ncaaf.php?yr=2025&wk=1")


# -- Bearer token -----------------------------------------------------------------


def test_bearer_token_added_to_page_request_only() -> None:
    log: list[httpx2.Request] = []
    responses = {
        "https://api.collegefootballdata.com/robots.txt": ALLOW_ALL_ROBOTS,
        "https://api.collegefootballdata.com/games?year=2025": (200, b"[]", {}),
    }
    client = _client(_recording_handler(responses, log))

    client.fetch(
        "https://api.collegefootballdata.com/games?year=2025", bearer_token="secret-token"
    )

    robots_request = next(r for r in log if str(r.url).endswith("/robots.txt"))
    page_request = next(r for r in log if str(r.url).endswith("/games?year=2025"))
    assert "authorization" not in robots_request.headers
    assert page_request.headers["authorization"] == "Bearer secret-token"


# -- X-CallLimit-Remaining ----------------------------------------------------------


def test_call_limit_remaining_parses_int() -> None:
    log: list[httpx2.Request] = []
    responses = {
        "https://api.collegefootballdata.com/robots.txt": ALLOW_ALL_ROBOTS,
        "https://api.collegefootballdata.com/games?year=2025": (
            200,
            b"[]",
            {"X-CallLimit-Remaining": "742"},
        ),
    }
    client = _client(_recording_handler(responses, log))

    resp = client.fetch("https://api.collegefootballdata.com/games?year=2025")

    assert resp.call_limit_remaining == 742


def test_call_limit_remaining_missing_gives_none() -> None:
    log: list[httpx2.Request] = []
    responses = {
        "https://api.collegefootballdata.com/robots.txt": ALLOW_ALL_ROBOTS,
        "https://api.collegefootballdata.com/games?year=2025": (200, b"[]", {}),
    }
    client = _client(_recording_handler(responses, log))

    resp = client.fetch("https://api.collegefootballdata.com/games?year=2025")

    assert resp.call_limit_remaining is None


def test_call_limit_remaining_non_integer_gives_none() -> None:
    log: list[httpx2.Request] = []
    responses = {
        "https://api.collegefootballdata.com/robots.txt": ALLOW_ALL_ROBOTS,
        "https://api.collegefootballdata.com/games?year=2025": (
            200,
            b"[]",
            {"X-CallLimit-Remaining": "not-a-number"},
        ),
    }
    client = _client(_recording_handler(responses, log))

    resp = client.fetch("https://api.collegefootballdata.com/games?year=2025")

    assert resp.call_limit_remaining is None
