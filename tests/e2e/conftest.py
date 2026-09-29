"""Playwright harness for the D-15 browser smoke tests.

Every module under `tests/e2e/` is collected only with `-m e2e` (the default
`uv run pytest` deselects them via `pyproject.toml`'s `addopts`). The harness
builds `dist/site` with `booth-review site --fixture` once per session,
serves it with a `python -m http.server` **subprocess** (never an in-process
thread: `pytest-socket`'s `--disable-socket` patches this process's own
`socket` module and would block an in-process server's `bind`/`accept`, but
has no visibility into a separate OS process -- RESEARCH Common Pitfall 1),
and wraps every test's `page` fixture with a route guard that aborts any
request leaving the site's own origin (D-15, SITE-19) and fails the test if
one was attempted. Every fixture here serves only the synthetic contract
fixture -- never real collected data (AGENTS.md: the vault is private and
never goes into fixtures or logs).
"""

from __future__ import annotations

import copy
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Browser, ConsoleMessage, Error, Page, Playwright, Route

from booth_review.cli import main

_PORT_RE = re.compile(r"port (\d+)")
_SERVER_START_TIMEOUT = 15.0


@pytest.fixture(scope="session", autouse=True)
def _chromium_available(playwright: Playwright) -> None:
    """Skip locally (fail in CI) when Chromium isn't installed (RESEARCH Pitfall 2)."""
    try:
        browser = playwright.chromium.launch()
        browser.close()
    except Error as exc:
        message = str(exc).lower()
        if "doesn't exist" in message or "does not exist" in message:
            if os.environ.get("CI"):
                pytest.fail(
                    "Chromium missing in CI: run `uv run playwright install --with-deps chromium`"
                )
            pytest.skip("Chromium not installed; run `uv run playwright install chromium`")
        raise


@pytest.fixture(scope="session")
def site_dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build dist/site from the synthetic contract fixture (D-14/D-15)."""
    out = tmp_path_factory.mktemp("site") / "site"
    returncode = main(["site", "--fixture", "--out", str(out)])
    assert returncode == 0, f"booth-review site --fixture exited {returncode}"
    return out


def _serve_directory(directory: Path) -> Iterator[str]:
    """Serve `directory` via a subprocess `python -m http.server` on an
    OS-assigned port (RESEARCH Pitfall 1); yields its base URL, then
    terminates the subprocess on teardown.

    A plain generator (not a fixture) so both `site_url` (the fixture build,
    below) and `test_site_realdata.py`'s own real-data build can each wrap it
    in their own fixture at whatever scope they need, without duplicating
    the subprocess/port-detection logic.
    """
    proc = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-m",
            "http.server",
            "0",
            "--bind",
            "127.0.0.1",
            "--directory",
            str(directory),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.stdout is not None
    lines: queue.Queue[str] = queue.Queue()

    def _pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line)

    reader = threading.Thread(target=_pump, daemon=True)
    reader.start()

    deadline = time.monotonic() + _SERVER_START_TIMEOUT
    port: int | None = None
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        try:
            line = lines.get(timeout=max(remaining, 0))
        except queue.Empty:
            break
        match = _PORT_RE.search(line)
        if match:
            port = int(match.group(1))
            break

    if port is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        raise RuntimeError("http.server did not report a port within 15 seconds")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="session")
def site_url(site_dist: Path) -> Iterator[str]:
    """Serve `site_dist` (the fixture build); yields its base URL."""
    yield from _serve_directory(site_dist)


@pytest.fixture(scope="session")
def fixture_raw(site_dist: Path) -> dict[str, Any]:
    """The built site-data.json, parsed (the same content the browser fetches)."""
    return json.loads((site_dist / "site-data.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture
def serve_round(fixture_raw: dict[str, Any]) -> Callable[[Page, str | None], None]:
    """Returns `serve(page, round_)`: makes `page` load the synthetic contract
    fixture with telecast 5's (the only CFP game's) `playoff_round` replaced by
    `round_`, so a test can see every CFP round without growing the shared
    fixture (whose 12-dot counts many tests rely on). Call it before opening
    the app; a later route wins over the origin guard's catch-all.
    """

    def _serve(page: Page, round_: str | None) -> None:
        raw = copy.deepcopy(fixture_raw)
        raw["telecasts"]["playoff_round"][5] = round_
        page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))

    return _serve


def _install_guard(page: Page, site_url: str) -> tuple[list[str], list[str]]:
    """Wires `page` to abort and record any request leaving `site_url`'s
    origin (SITE-19), and to record any console error mentioning CSP.
    Returns the two lists it appends to, for the caller's own teardown.
    """
    off_origin: list[str] = []
    csp_errors: list[str] = []
    allowed_prefix = site_url + "/"

    def _route(route: Route) -> None:
        url = route.request.url
        if url.startswith(allowed_prefix) or url.startswith("data:") or url.startswith("blob:"):
            route.continue_()
        else:
            off_origin.append(url)
            route.abort()

    page.route("**/*", _route)

    def _on_console(msg: ConsoleMessage) -> None:
        if msg.type == "error" and "Content Security Policy" in msg.text:
            csp_errors.append(msg.text)

    page.on("console", _on_console)

    return off_origin, csp_errors


def _assert_guard_clean(off_origin: list[str], csp_errors: list[str]) -> None:
    if off_origin:
        hosts = sorted({urlsplit(url).hostname for url in off_origin})
        raise AssertionError(f"off-origin requests were made to: {hosts}")
    if csp_errors:
        raise AssertionError(f"Content-Security-Policy violations logged: {csp_errors}")


@pytest.fixture
def guarded_page(page: Page, site_url: str) -> Iterator[Page]:
    """`page`, wired to abort and record any request leaving `site_url`'s
    origin (SITE-19), and to record any console error mentioning CSP.
    Teardown fails the test if either list is non-empty.
    """
    off_origin, csp_errors = _install_guard(page, site_url)
    yield page
    _assert_guard_clean(off_origin, csp_errors)


@pytest.fixture
def mobile_page(browser: Browser, site_url: str) -> Iterator[Page]:
    """A guarded `page` from a fresh mobile context (390x844, touch, D-15/SITE-18)."""
    context = browser.new_context(
        viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True
    )
    page = context.new_page()
    off_origin, csp_errors = _install_guard(page, site_url)
    try:
        yield page
    finally:
        context.close()
    _assert_guard_clean(off_origin, csp_errors)


@pytest.fixture
def open_app(site_url: str) -> Callable[[Page, str], None]:
    """Returns `open(page, query="")`: navigates to `index.html<query>` and
    waits for `app.js`'s bootstrap to finish (`window.__testHooks.ready`)."""

    def _open(page: Page, query: str = "") -> None:
        page.goto(f"{site_url}/index.html{query}")
        page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")

    return _open
