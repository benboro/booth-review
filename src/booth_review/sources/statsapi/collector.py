"""StatsApiCollector: per-date schedule requests with lineups hydrated (D-05).

Disabled by policy: statsapi.mlb.com is absent from HOST_POLICIES, so the polite
client refuses it. Any 4xx ends the run at once; there is no retry, header
variation or alternate endpoint (D-04). Output is counts, booleans and key names
only; response bodies are never logged.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from booth_review.config import DataPaths
from booth_review.errors import BoothReviewError, FetchError, ParseError, RunCapError
from booth_review.mlb.constants import STATSAPI_MAX_REQUESTS
from booth_review.mlb.layout import statsapi_schedule_path
from booth_review.transport.cache import Manifest, RawCache
from booth_review.transport.types import FetchRequest

logger = logging.getLogger(__name__)

STATSAPI_HOST = "statsapi.mlb.com"
STATSAPI_SEASON = 2026
STATSAPI_MAX_BYTES = 5 * 1024 * 1024
STATSAPI_HEADERS: tuple[tuple[str, str], ...] = (("Accept", "application/json"),)

# For plan 09-28 to use when (and only when) the user approves one request. A
# "budgeted" host retries only 502/503, never a 4xx, so a refusal stays terminal.
STATSAPI_HOST_POLICY_KWARGS: dict[str, object] = {
    "min_interval_s": 5.0,
    "jitter_s": 1.0,
    "retry_mode": "budgeted",
}


class StatsApiRefused(BoothReviewError):
    """The host answered 4xx. Terminal: nothing is retried or varied."""

    def __init__(self, status_class: str) -> None:
        super().__init__(f"statsapi refused the request ({status_class}); run stopped")
        self.status_class = status_class


def statsapi_route_closed(paths: DataPaths) -> bool:
    """True once the manifest holds any 4xx for the Stats API.

    A refusal ends the route for good (D-04): the ledger outlives the process, so a
    later run sends nothing instead of retrying or trying another date.
    """
    for entry in Manifest(paths.manifest).entries():
        status = entry.get("status")
        if (
            entry.get("source") == "mlb_statsapi"
            and isinstance(status, int)
            and 400 <= status < 500
        ):
            return True
    return False


class StatsApiInvalidError(ParseError):
    """A 200 that is not acceptable JSON. Count-only message."""


@dataclass(frozen=True)
class StatsApiSummary:
    planned: int
    fetched: int
    cached: int
    has_dates: bool
    has_lineups: bool
    top_level_keys: tuple[str, ...]
    dry_run: bool = False

    def counts(self) -> dict[str, int]:
        return {"planned": self.planned, "fetched": self.fetched, "cached": self.cached}


def plan_dates(days: Iterable[date], *, max_requests: int) -> list[FetchRequest]:
    """One schedule-with-lineups request per distinct date, sorted, capped."""
    unique = sorted(set(days))
    for day in unique:
        if day.year != STATSAPI_SEASON:
            raise ValueError(f"date outside the {STATSAPI_SEASON} calendar year")
    cap = min(STATSAPI_MAX_REQUESTS, max_requests)
    if len(unique) > cap:
        raise RunCapError(f"{len(unique)} dates planned, cap is {cap}")
    return [
        FetchRequest(
            source="mlb_statsapi",
            season=STATSAPI_SEASON,
            url=f"https://{STATSAPI_HOST}/api/v1/schedule?sportId=1&date={day.isoformat()}&hydrate=lineups",
            cache_path=statsapi_schedule_path(day),
            headers=STATSAPI_HEADERS,
        )
        for day in unique
    ]


def _validate(content: bytes) -> None:
    if len(content) > STATSAPI_MAX_BYTES:
        raise StatsApiInvalidError("response exceeds the size cap")
    try:
        json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise StatsApiInvalidError("response is not valid JSON") from exc


class StatsApiCollector:
    def __init__(self, cache: RawCache, paths: DataPaths) -> None:
        self._cache = cache
        self._paths = paths

    def run(self, requests: Sequence[FetchRequest], *, dry_run: bool = False) -> StatsApiSummary:
        if dry_run:
            return StatsApiSummary(len(requests), 0, 0, False, False, (), dry_run=True)
        if statsapi_route_closed(self._paths):
            raise StatsApiRefused("earlier 4xx on record")
        fetched = cached = 0
        has_dates = has_lineups = False
        keys: set[str] = set()
        for req in requests:
            try:
                result = self._cache.get_or_fetch(req, validate=_validate)
            except FetchError as exc:
                status = exc.status_code
                if status is not None and 400 <= status < 500:
                    raise StatsApiRefused(f"{status // 100}xx") from exc
                raise
            if result.outcome == "cached":
                cached += 1
            else:
                fetched += 1
            data = json.loads(result.content)
            if isinstance(data, dict):
                keys.update(str(k) for k in data)
                dates = data.get("dates")
                if isinstance(dates, list):
                    has_dates = True
                    has_lineups = has_lineups or "lineups" in result.content.decode("utf-8")
        return StatsApiSummary(
            len(requests), fetched, cached, has_dates, has_lineups, tuple(sorted(keys))
        )
