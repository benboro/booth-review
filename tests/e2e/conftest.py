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

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import ConsoleMessage, Error, Page, Playwright, Route

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


@pytest.fixture(scope="session")
def site_url(site_dist: Path) -> Iterator[str]:
    """Serve `site_dist` via a subprocess `python -m http.server` on an
    OS-assigned port (RESEARCH Pitfall 1); yields its base URL.
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
            str(site_dist),
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
def fixture_raw(site_dist: Path) -> dict[str, Any]:
    """The built site-data.json, parsed (the same content the browser fetches)."""
    return json.loads((site_dist / "site-data.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture
def guarded_page(page: Page, site_url: str) -> Iterator[Page]:
    """`page`, wired to abort and record any request leaving `site_url`'s
    origin (SITE-19), and to record any console error mentioning CSP.
    Teardown fails the test if either list is non-empty.
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

    yield page

    if off_origin:
        hosts = sorted({urlsplit(url).hostname for url in off_origin})
        raise AssertionError(f"off-origin requests were made to: {hosts}")
    if csp_errors:
        raise AssertionError(f"Content-Security-Policy violations logged: {csp_errors}")
