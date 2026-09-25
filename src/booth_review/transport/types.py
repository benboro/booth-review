"""Shared request/response contracts for the transport, cache, and budget layers.

These dataclasses and the FetchGuard protocol are the shapes later plans
(cache, budget, collectors) import; they carry no behavior of their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

Source = Literal["sports506", "ratingsref", "cfbd"]


@dataclass(frozen=True)
class Validators:
    """Conditional-request validators carried over from a prior fetch."""

    etag: str | None
    last_modified: str | None


@dataclass(frozen=True)
class FetchRequest:
    """A single planned fetch, identified well enough to cache and to log."""

    source: Source
    season: int | None
    url: str
    """Full URL including its query string. CFBD params are urlencoded in
    sorted order; 506 keeps its documented yr=YYYY&wk=N order."""
    cache_path: str
    """POSIX path relative to data/vault/raw/."""
    endpoint: str | None = None
    """CFBD API path such as "/games"; None for other sources."""
    params: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    """CFBD query params, for the ledger only."""
    kind: Literal["page", "robots"] = "page"


@dataclass(frozen=True)
class FetchResponse:
    """The result of a fetch, regardless of final HTTP status."""

    status_code: int
    content: bytes
    etag: str | None
    last_modified: str | None
    call_limit_remaining: int | None
    """Parsed from the X-CallLimit-Remaining header."""
    final_url: str
    fetched_at: datetime
    """Timezone-aware UTC."""


class FetchGuard(Protocol):
    """A hook that can veto or observe fetches (cache, budget, freeze guard)."""

    def before_fetch(self, req: FetchRequest) -> None:
        """Raise to refuse the fetch before it is sent."""
        ...

    def after_fetch(self, req: FetchRequest, resp: FetchResponse) -> None:
        """Observe a completed fetch."""
        ...
