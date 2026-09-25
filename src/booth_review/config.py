"""Project-wide configuration: user agent, host politeness policy, and paths.

Only this module reads the CFBD_API_KEY environment variable / .env entry.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from booth_review import __version__
from booth_review.errors import MissingApiKeyError
from booth_review.transport.types import Source

USER_AGENT = f"booth-review/{__version__} (+https://github.com/benboro/booth-review)"


@dataclass(frozen=True)
class HostPolicy:
    """Per-host politeness and retry policy."""

    min_interval_s: float
    jitter_s: float
    retry_mode: Literal["standard", "connect_only"]


HOST_POLICIES: dict[str, HostPolicy] = {
    "506sports.com": HostPolicy(min_interval_s=10.0, jitter_s=0.0, retry_mode="standard"),
    "ratingsreference.com": HostPolicy(min_interval_s=2.0, jitter_s=1.0, retry_mode="standard"),
    "api.collegefootballdata.com": HostPolicy(
        min_interval_s=1.0, jitter_s=0.0, retry_mode="connect_only"
    ),
}

HOST_SOURCE: dict[str, Source] = {
    "506sports.com": "sports506",
    "ratingsreference.com": "ratingsref",
    "api.collegefootballdata.com": "cfbd",
}

CFBD_BASE_URL = "https://api.collegefootballdata.com"
CFBD_FLOOR_DEFAULT = 250


@dataclass(frozen=True)
class DataPaths:
    """Filesystem layout of the data vault (data/vault/ by default)."""

    vault: Path

    @property
    def raw(self) -> Path:
        return self.vault / "raw"

    @property
    def interim(self) -> Path:
        return self.vault / "interim"

    @property
    def processed(self) -> Path:
        return self.vault / "processed"

    @property
    def ledger(self) -> Path:
        return self.vault / "ledger"

    @property
    def spike(self) -> Path:
        return self.vault / "spike"

    @property
    def manifest(self) -> Path:
        return self.ledger / "requests.jsonl"

    @property
    def cfbd_ledger(self) -> Path:
        return self.ledger / "cfbd_ledger.jsonl"

    @property
    def frozen(self) -> Path:
        return self.ledger / "frozen.json"

    @property
    def rr_lastmod(self) -> Path:
        return self.ledger / "rr_lastmod.json"

    @property
    def audit(self) -> Path:
        return self.vault / "audit"

    @property
    def job_state(self) -> Path:
        return self.ledger / "job_state.json"

    @classmethod
    def from_env(cls) -> DataPaths:
        vault = os.environ.get("BOOTH_REVIEW_VAULT")
        return cls(vault=Path(vault) if vault else Path("data/vault"))


def load_cfbd_key(env_file: Path = Path(".env")) -> str:
    """Return the CFBD API key from the environment, else from `env_file`.

    Raises MissingApiKeyError (never containing key text) when absent or empty.
    """
    key = os.environ.get("CFBD_API_KEY")
    if key:
        return key

    if env_file.is_file():
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() != "CFBD_API_KEY":
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            if value:
                return value

    raise MissingApiKeyError("CFBD_API_KEY is not set in the environment or .env file")
