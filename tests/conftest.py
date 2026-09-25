"""Shared test fixtures: offline retry mode, mock transport, fake clock, vault paths.

Tests import httpx2 only through these helpers or directly in test files;
package code outside transport/client.py never imports it.
"""

from __future__ import annotations

import json
import random
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import httpx2
import pytest
import stamina

from booth_review.config import DataPaths
from booth_review.transport.client import PoliteClient

MockResponseSpec = tuple[int, bytes, dict[str, str]]


@pytest.fixture(autouse=True, scope="session")
def _stamina_testing_mode() -> Iterator[None]:
    """Make retries instant (no real waiting) but still exercise retry logic."""
    with stamina.set_testing(True, attempts=4):
        yield


@dataclass
class RecordedRequest:
    method: str
    url: str
    headers: dict[str, str]


@dataclass
class MockTransportHandle:
    transport: httpx2.MockTransport
    requests: list[RecordedRequest] = field(default_factory=list)


@pytest.fixture
def mock_transport_factory() -> Callable[[dict[str, MockResponseSpec]], MockTransportHandle]:
    """Build an httpx2.MockTransport from {url: (status, body, headers)}.

    Every request the transport receives is recorded (method, URL, headers)
    on the returned handle's `.requests` list.
    """

    def _build(responses: dict[str, MockResponseSpec]) -> MockTransportHandle:
        handle = MockTransportHandle(transport=None)  # type: ignore[arg-type]

        def handler(request: httpx2.Request) -> httpx2.Response:
            handle.requests.append(
                RecordedRequest(
                    method=request.method,
                    url=str(request.url),
                    headers=dict(request.headers),
                )
            )
            key = str(request.url)
            if key not in responses:
                raise AssertionError(f"mock_transport_factory: no response configured for {key}")
            status, body, headers = responses[key]
            return httpx2.Response(status, content=body, headers=headers, request=request)

        handle.transport = httpx2.MockTransport(handler)
        return handle

    return _build


@dataclass
class FakeClock:
    """A controllable stand-in for time.monotonic / time.sleep."""

    _now: float = 0.0
    sleeps: list[float] = field(default_factory=list)

    def now(self) -> float:
        return self._now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._now += seconds


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def vault_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DataPaths:
    """Create a throwaway vault under tmp_path and point BOOTH_REVIEW_VAULT at it."""
    vault_root = tmp_path / "vault"
    paths = DataPaths(vault=vault_root)
    for directory in (paths.raw, paths.interim, paths.processed, paths.ledger, paths.spike):
        directory.mkdir(parents=True, exist_ok=True)
    paths.frozen.write_text(
        json.dumps({"sports506": [], "ratingsref": [], "cfbd": []}), encoding="utf-8"
    )
    monkeypatch.setenv("BOOTH_REVIEW_VAULT", str(vault_root))
    return paths


@pytest.fixture
def isolated_git_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Blocks the operator's global/system git config from leaking into tests."""
    empty_config = tmp_path / "empty-gitconfig"
    empty_config.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_config))


@pytest.fixture
def git_vault(tmp_path: Path, isolated_git_env: None, monkeypatch: pytest.MonkeyPatch) -> DataPaths:
    """A real bare-remote + clone vault under tmp_path, wired for the CLI.

    Creates the D-01 folders and ledger/frozen.json, pushes a seed commit,
    points BOOTH_REVIEW_VAULT at the clone, chdir's into tmp_path (so a
    developer's real .env at the repo root is never read by
    `load_cfbd_key()`), and clears CFBD_API_KEY by default.
    """
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-q", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
    )

    vault = tmp_path / "vault"
    subprocess.run(["git", "clone", "-q", str(remote), str(vault)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(vault), "config", "user.name", "Test Bot"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(vault), "config", "user.email", "test-bot@example.com"],
        check=True,
        capture_output=True,
    )

    paths = DataPaths(vault=vault)
    for directory in (paths.raw, paths.interim, paths.processed, paths.ledger, paths.spike):
        directory.mkdir(parents=True, exist_ok=True)
    paths.frozen.write_text(
        json.dumps({"sports506": [], "ratingsref": [], "cfbd": []}), encoding="utf-8"
    )

    subprocess.run(["git", "-C", str(vault), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(vault), "commit", "-q", "-m", "init: seed"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(vault), "push", "-q", "origin", "main"], check=True, capture_output=True
    )

    monkeypatch.setenv("BOOTH_REVIEW_VAULT", str(vault))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CFBD_API_KEY", raising=False)
    return paths


@pytest.fixture
def patched_client(
    monkeypatch: pytest.MonkeyPatch, fake_clock: FakeClock
) -> Callable[[MockTransportHandle], None]:
    """Monkeypatch booth_review.runtime.make_client to build a PoliteClient on
    a given mock transport with a fake clock, so CLI tests never sleep.
    """

    def _patch(handle: MockTransportHandle) -> None:
        def _make_client() -> PoliteClient:
            return PoliteClient(
                transport=handle.transport,
                clock=fake_clock.now,
                sleep=fake_clock.sleep,
                rng=random.Random(0),
            )

        monkeypatch.setattr("booth_review.runtime.make_client", _make_client)

    return _patch
