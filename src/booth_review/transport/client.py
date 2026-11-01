"""PoliteClient: the single door every outbound request passes through.

This is the only module under src/booth_review allowed to import httpx2 (D-14).
"""

from __future__ import annotations

import logging
import random
import re
import time
import urllib.robotparser as robotparser
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from types import TracebackType

import httpx2
import stamina

from booth_review.config import HOST_POLICIES, USER_AGENT, HostPolicy
from booth_review.errors import (
    FetchError,
    ResponseTooLargeError,
    RobotsDisallowedError,
    RobotsUnavailableError,
    UnknownHostError,
)
from booth_review.transport.robots import RobotsRules
from booth_review.transport.types import FetchResponse, Validators

logger = logging.getLogger("booth_review.transport")

# The HTTP library logs every request URL, query string included, at INFO. This
# module's own fetch line records host, path, status and size, which is all the
# run logs may carry (AUTO-05).
for _http_logger in ("httpx", "httpx2", "httpcore"):
    logging.getLogger(_http_logger).setLevel(logging.WARNING)

# A Ratings Reference record path names the matchup (`/api/telecast/cfb-<team>-
# <team>-<date>.json`), so the fetch line logs the endpoint with the record id
# masked; the run logs stay counts only (AUTO-05). The manifest keeps the full URL.
_RECORD_PATH_RE = re.compile(r"^(/api/telecast/)[^/]+$")


def _loggable_path(path: str) -> str:
    """Return `path` with any per-record segment replaced by `<record>`."""
    return _RECORD_PATH_RE.sub(r"\1<record>", path)


RobotsListener = Callable[[str, FetchResponse], None]

_RETRY_ATTEMPTS = 4

# Redirects are followed by hand (WR-01) so each hop's host is checked against
# the allow-list and its robots.txt, and paced, before the hop is sent.
_MAX_REDIRECTS = 5

# GitHub release-asset redirects carry short-lived signed query strings; the
# manifest's final_url keeps scheme, host and path only for these hosts.
_STRIP_FINAL_QUERY_HOSTS = frozenset(
    {"release-assets.githubusercontent.com", "objects.githubusercontent.com"}
)

# "budgeted" hosts (CFBD) retry only statuses a gateway returns without
# forwarding the request, with waits sized for a minutes-long outage.
_GATEWAY_STATUSES = frozenset({502, 503})
_BUDGETED_RETRY_ATTEMPTS = 3
_BUDGETED_WAIT_INITIAL_S = 30.0
_BUDGETED_WAIT_MAX_S = 90.0


class _RetryableStatus(Exception):
    """Internal signal that a response's status code should be retried."""


def _read_capped(response: httpx2.Response, request: httpx2.Request, cap: int) -> httpx2.Response:
    """Read a streamed body, aborting once it passes `cap` bytes.

    A redirect is returned unread (its body is never needed). Otherwise the
    body is decoded in chunks and a new in-memory response replaces the stream, so
    nothing larger than `cap` plus one chunk is ever held.
    """
    if response.next_request is not None:
        return response
    try:
        declared = response.headers.get("Content-Length")
        if declared is not None and declared.isdigit() and int(declared) > cap:
            raise ResponseTooLargeError("response is larger than the size cap")
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > cap:
                raise ResponseTooLargeError("response is larger than the size cap")
            chunks.append(chunk)
    finally:
        response.close()
    headers = [
        (k, v)
        for k, v in response.headers.multi_items()
        if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")
    ]
    return httpx2.Response(
        response.status_code, headers=headers, content=b"".join(chunks), request=request
    )


class PoliteClient:
    """Wraps a single httpx2.Client with UA, robots, pacing, and retries."""

    def __init__(
        self,
        *,
        transport: httpx2.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        host_policies: Mapping[str, HostPolicy] = HOST_POLICIES,
    ) -> None:
        self._client = httpx2.Client(
            headers={"User-Agent": USER_AGENT},
            follow_redirects=False,
            timeout=httpx2.Timeout(30.0, connect=10.0),
            transport=transport,
        )
        self._clock = clock
        self._sleep = sleep
        self._rng = rng if rng is not None else random.Random()
        self._host_policies = host_policies
        self._last_request_end: dict[str, float] = {}
        self._robots: dict[str, robotparser.RobotFileParser] = {}
        self._robots_rules: dict[str, RobotsRules] = {}
        self._robots_listeners: list[RobotsListener] = []

    def add_robots_listener(self, fn: RobotsListener) -> None:
        self._robots_listeners.append(fn)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def fetch(
        self,
        url: str,
        *,
        validators: Validators | None = None,
        bearer_token: str | None = None,
        headers: Mapping[str, str] | None = None,
        max_bytes: int | None = None,
    ) -> FetchResponse:
        host = httpx2.URL(url).host
        policy = self._host_policies.get(host)
        if policy is None:
            raise UnknownHostError(f"host not in allow-list: {host}")

        self._check_robots(host, policy, url)

        req_headers: dict[str, str] = {
            k: v for k, v in (headers or {}).items() if k.lower() != "authorization"
        }
        if bearer_token:
            req_headers["Authorization"] = f"Bearer {bearer_token}"
        return self._send(
            host, policy, url, validators=validators, headers=req_headers, max_bytes=max_bytes
        )

    def _check_robots(self, host: str, policy: HostPolicy, url: str) -> None:
        self._ensure_robots(host, policy)
        rp = self._robots[host]
        if not rp.can_fetch(USER_AGENT, url):
            raise RobotsDisallowedError(f"robots.txt disallows {url}")
        if self._robots_rules[host].disallows(url):
            raise RobotsDisallowedError(f"robots.txt wildcard rule disallows {url}")

    def _ensure_robots(self, host: str, policy: HostPolicy) -> None:
        if host in self._robots:
            return
        robots_url = f"https://{host}/robots.txt"
        try:
            # A robots.txt redirect is still allow-listed and paced, but its
            # target's own robots.txt is not consulted (that could loop).
            resp = self._send(
                host, policy, robots_url, validators=None, headers={}, check_robots=False
            )
        except FetchError as exc:
            raise RobotsUnavailableError(f"could not fetch robots.txt for {host}") from exc

        rp = robotparser.RobotFileParser()
        rp.set_url(robots_url)
        # allow_all/disallow_all are real, documented RobotFileParser attributes
        # (see CPython's urllib/robotparser.py) that typeshed's stub omits.
        rules = RobotsRules.allow_all()
        if resp.status_code in (401, 403):
            rp.disallow_all = True  # type: ignore[attr-defined]
        elif resp.status_code >= 500:
            raise RobotsUnavailableError(
                f"robots.txt fetch failed with status {resp.status_code} for {host}"
            )
        elif resp.status_code == 200:
            text_lines = resp.content.decode("utf-8", errors="replace").splitlines()
            rp.parse(text_lines)
            rules = RobotsRules.parse(text_lines, agent=USER_AGENT)
        else:
            # 404 and other 4xx (except 401/403) mean allow-all, matching
            # RobotFileParser's own stdlib fetch method's 4xx handling.
            rp.allow_all = True  # type: ignore[attr-defined]

        self._robots[host] = rp
        self._robots_rules[host] = rules
        for listener in self._robots_listeners:
            listener(host, resp)

    def _pace(self, host: str, policy: HostPolicy) -> None:
        last_end = self._last_request_end.get(host)
        if last_end is None:
            return
        elapsed = self._clock() - last_end
        wait = policy.min_interval_s + self._rng.uniform(0, policy.jitter_s) - elapsed
        if wait > 0:
            self._sleep(wait)

    def _send(
        self,
        host: str,
        policy: HostPolicy,
        url: str,
        *,
        validators: Validators | None,
        headers: dict[str, str],
        check_robots: bool = True,
        max_bytes: int | None = None,
    ) -> FetchResponse:
        req_headers = dict(headers)
        if validators is not None:
            if validators.etag:
                req_headers["If-None-Match"] = validators.etag
            if validators.last_modified:
                req_headers["If-Modified-Since"] = validators.last_modified

        request = self._client.build_request("GET", url, headers=req_headers)
        hop_host, hop_policy = host, policy
        redirects = 0
        while True:
            response = self._send_hop(hop_host, hop_policy, request, url, max_bytes=max_bytes)
            next_request = response.next_request
            if next_request is None:
                break
            # Never read a redirect's body; the next hop is vetted before it is sent.
            response.close()
            redirects += 1
            if redirects > _MAX_REDIRECTS:
                raise FetchError(f"too many redirects fetching {url}")
            hop_host, hop_policy = self._approve_redirect(
                hop_host, next_request, check_robots=check_robots
            )
            request = next_request

        final_host = response.url.host
        if final_host not in self._host_policies:
            raise UnknownHostError(f"redirect left the host allow-list: {final_host}")

        call_limit_remaining: int | None = None
        raw_remaining = response.headers.get("X-CallLimit-Remaining")
        if raw_remaining is not None:
            try:
                call_limit_remaining = int(raw_remaining)
            except ValueError:
                call_limit_remaining = None

        final_url = str(response.url)
        if final_host in _STRIP_FINAL_QUERY_HOSTS:
            final_url = f"{response.url.scheme}://{final_host}{response.url.path}"

        fetch_resp = FetchResponse(
            status_code=response.status_code,
            content=response.content,
            etag=response.headers.get("ETag"),
            last_modified=response.headers.get("Last-Modified"),
            call_limit_remaining=call_limit_remaining,
            final_url=final_url,
            fetched_at=datetime.now(UTC),
        )
        logger.info(
            "fetch host=%s path=%s status=%s bytes=%d",
            host,
            _loggable_path(httpx2.URL(url).path),
            fetch_resp.status_code,
            len(fetch_resp.content),
        )
        return fetch_resp

    def _send_hop(
        self,
        host: str,
        policy: HostPolicy,
        request: httpx2.Request,
        url: str,
        *,
        max_bytes: int | None = None,
    ) -> httpx2.Response:
        """Send one request (no redirect following), paced and retried per
        `host`'s policy."""

        def attempt() -> httpx2.Response:
            self._pace(host, policy)
            try:
                if max_bytes is None:
                    response = self._client.send(request, follow_redirects=False)
                else:
                    response = _read_capped(
                        self._client.send(request, stream=True, follow_redirects=False),
                        request,
                        max_bytes,
                    )
            finally:
                self._last_request_end[host] = self._clock()
            return response

        try:
            if policy.retry_mode == "single":
                return attempt()
            if policy.retry_mode == "standard":
                return self._send_with_standard_retries(attempt)
            return self._send_with_budgeted_retries(attempt)
        except httpx2.TransportError as exc:
            raise FetchError(f"transport failure fetching {url}") from exc

    def _approve_redirect(
        self, from_host: str, request: httpx2.Request, *, check_robots: bool
    ) -> tuple[str, HostPolicy]:
        """Vet a redirect hop before it is sent: its host must be allow-listed
        and (unless fetching robots.txt itself) its robots.txt must allow the
        URL. A hop to another host never carries Authorization."""
        host = request.url.host
        policy = self._host_policies.get(host)
        if policy is None:
            raise UnknownHostError(f"redirect left the host allow-list: {host}")
        if host != from_host:
            request.headers.pop("Authorization", None)
        if check_robots:
            self._check_robots(host, policy, str(request.url))
        return host, policy

    def _send_with_standard_retries(
        self, attempt: Callable[[], httpx2.Response]
    ) -> httpx2.Response:
        """Retry on transport errors and on 429/5xx statuses.

        Every retry attempt goes through pacing again (via `attempt`).
        Once attempts are exhausted, the last response is returned rather
        than raised, so a persistently unhealthy source degrades gracefully.
        """
        last_response: httpx2.Response | None = None

        def _do() -> httpx2.Response:
            nonlocal last_response
            response = attempt()
            last_response = response
            if response.status_code == 429 or response.status_code >= 500:
                raise _RetryableStatus(f"retryable status {response.status_code}")
            return response

        try:
            for attempt_ctx in stamina.retry_context(
                on=(httpx2.TransportError, _RetryableStatus), attempts=_RETRY_ATTEMPTS
            ):
                with attempt_ctx:
                    return _do()
        except _RetryableStatus:
            assert last_response is not None
            return last_response
        raise AssertionError("retry loop exited without returning")  # pragma: no cover

    def _send_with_budgeted_retries(
        self, attempt: Callable[[], httpx2.Response]
    ) -> httpx2.Response:
        """Retry connection failures and gateway 502/503s only.

        Neither reaches the API behind the gateway, so neither is counted
        against a budget (CFBD's monthly quota): a 2026-09-27 CFBD 502 left
        X-CallLimit-Remaining unchanged. A read timeout, 500, 504, or 429 may
        have been served and counted, so none of those is ever retried. The
        gateway waits are long (tens of seconds) because a CFBD outage lasts
        minutes, not milliseconds; once attempts are exhausted the last
        response is returned, as in `_send_with_standard_retries`.
        """
        last_response: httpx2.Response | None = None

        def _do() -> httpx2.Response:
            nonlocal last_response
            response = attempt()
            last_response = response
            if response.status_code in _GATEWAY_STATUSES:
                raise _RetryableStatus(f"gateway status {response.status_code}")
            return response

        try:
            for attempt_ctx in stamina.retry_context(
                on=(httpx2.ConnectError, httpx2.ConnectTimeout, _RetryableStatus),
                attempts=_BUDGETED_RETRY_ATTEMPTS,
                wait_initial=_BUDGETED_WAIT_INITIAL_S,
                wait_max=_BUDGETED_WAIT_MAX_S,
                timeout=None,
            ):
                with attempt_ctx:
                    return _do()
        except _RetryableStatus:
            assert last_response is not None
            return last_response
        raise AssertionError("retry loop exited without returning")  # pragma: no cover
