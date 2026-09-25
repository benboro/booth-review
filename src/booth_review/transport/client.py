"""PoliteClient: the single door every outbound request passes through.

This is the only module under src/booth_review allowed to import httpx2 (D-14).
"""

from __future__ import annotations

import logging
import random
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
    RobotsDisallowedError,
    RobotsUnavailableError,
    UnknownHostError,
)
from booth_review.transport.types import FetchResponse, Validators

logger = logging.getLogger("booth_review.transport")

RobotsListener = Callable[[str, FetchResponse], None]

_RETRY_ATTEMPTS = 4


class _RetryableStatus(Exception):
    """Internal signal that a response's status code should be retried."""


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
            follow_redirects=True,
            timeout=httpx2.Timeout(30.0, connect=10.0),
            transport=transport,
        )
        self._clock = clock
        self._sleep = sleep
        self._rng = rng if rng is not None else random.Random()
        self._host_policies = host_policies
        self._last_request_end: dict[str, float] = {}
        self._robots: dict[str, robotparser.RobotFileParser] = {}
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
    ) -> FetchResponse:
        host = httpx2.URL(url).host
        policy = self._host_policies.get(host)
        if policy is None:
            raise UnknownHostError(f"host not in allow-list: {host}")

        self._ensure_robots(host, policy)
        rp = self._robots[host]
        if not rp.can_fetch(USER_AGENT, url):
            raise RobotsDisallowedError(f"robots.txt disallows {url}")

        headers: dict[str, str] = {}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        return self._send(host, policy, url, validators=validators, headers=headers)

    def _ensure_robots(self, host: str, policy: HostPolicy) -> None:
        if host in self._robots:
            return
        robots_url = f"https://{host}/robots.txt"
        try:
            resp = self._send(host, policy, robots_url, validators=None, headers={})
        except FetchError as exc:
            raise RobotsUnavailableError(f"could not fetch robots.txt for {host}") from exc

        rp = robotparser.RobotFileParser()
        rp.set_url(robots_url)
        # allow_all/disallow_all are real, documented RobotFileParser attributes
        # (see CPython's urllib/robotparser.py) that typeshed's stub omits.
        if resp.status_code in (401, 403):
            rp.disallow_all = True  # type: ignore[attr-defined]
        elif resp.status_code >= 500:
            raise RobotsUnavailableError(
                f"robots.txt fetch failed with status {resp.status_code} for {host}"
            )
        elif resp.status_code == 200:
            rp.parse(resp.content.decode("utf-8", errors="replace").splitlines())
        else:
            # 404 and other 4xx (except 401/403) mean allow-all, matching
            # RobotFileParser's own stdlib fetch method's 4xx handling.
            rp.allow_all = True  # type: ignore[attr-defined]

        self._robots[host] = rp
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
    ) -> FetchResponse:
        req_headers = dict(headers)
        if validators is not None:
            if validators.etag:
                req_headers["If-None-Match"] = validators.etag
            if validators.last_modified:
                req_headers["If-Modified-Since"] = validators.last_modified

        def attempt() -> httpx2.Response:
            self._pace(host, policy)
            try:
                response = self._client.get(url, headers=req_headers)
            finally:
                self._last_request_end[host] = self._clock()
            return response

        try:
            if policy.retry_mode == "standard":
                response = self._send_with_standard_retries(attempt)
            else:
                response = self._send_with_connect_only_retries(attempt)
        except httpx2.TransportError as exc:
            raise FetchError(f"transport failure fetching {url}") from exc

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

        fetch_resp = FetchResponse(
            status_code=response.status_code,
            content=response.content,
            etag=response.headers.get("ETag"),
            last_modified=response.headers.get("Last-Modified"),
            call_limit_remaining=call_limit_remaining,
            final_url=str(response.url),
            fetched_at=datetime.now(UTC),
        )
        logger.info(
            "fetch host=%s path=%s status=%s bytes=%d",
            host,
            httpx2.URL(url).path,
            fetch_resp.status_code,
            len(fetch_resp.content),
        )
        return fetch_resp

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

    def _send_with_connect_only_retries(
        self, attempt: Callable[[], httpx2.Response]
    ) -> httpx2.Response:
        """Retry only on connection failures; never on a status code or read
        timeout, since a request that reached the server may already have
        been counted against a budget (CFBD's monthly quota).
        """
        for attempt_ctx in stamina.retry_context(
            on=(httpx2.ConnectError, httpx2.ConnectTimeout), attempts=_RETRY_ATTEMPTS
        ):
            with attempt_ctx:
                return attempt()
        raise AssertionError("retry loop exited without returning")  # pragma: no cover
