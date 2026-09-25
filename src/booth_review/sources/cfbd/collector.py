"""CfbdCollector: plans and fetches allow-listed CFBD season data.

Every call goes through RawCache with a CfbdBudget guard wired in, so the
allow-list, floor, and per-run cap are enforced there; this module only
builds requests for the six known endpoints (plus /info) and never targets
anything outside ENDPOINTS (FOUND-03, D-12).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from urllib.parse import urlencode

from booth_review.config import CFBD_BASE_URL
from booth_review.errors import MissingApiKeyError
from booth_review.sources.base import BatchSummary, run_requests
from booth_review.transport.budget import CfbdBudget, InfoSnapshot, parse_info
from booth_review.transport.cache import RawCache
from booth_review.transport.types import FetchRequest

# name -> (API path, whether the call passes seasonType=both)
ENDPOINTS: dict[str, tuple[str, bool]] = {
    "games": ("/games", True),
    "media": ("/games/media", True),
    "wp_pregame": ("/metrics/wp/pregame", True),
    "lines": ("/lines", True),
    "rankings": ("/rankings", True),
    "teams_fbs": ("/teams/fbs", False),
}


class CfbdCollector:
    """Plans, dry-runs, and fetches one season of allow-listed CFBD data."""

    def __init__(self, cache: RawCache, budget: CfbdBudget, token: str | None) -> None:
        self._cache = cache
        self._budget = budget
        self._token = token

    def plan(self, season: int, names: Sequence[str]) -> list[FetchRequest]:
        requests: list[FetchRequest] = []
        for name in names:
            if name not in ENDPOINTS:
                raise ValueError(f"unknown CFBD endpoint name: {name!r}")
            path, wants_season_type = ENDPOINTS[name]
            params: list[tuple[str, str]] = [("year", str(season))]
            if wants_season_type:
                params.append(("seasonType", "both"))
            sorted_params = tuple(sorted(params))
            query = urlencode(sorted_params)
            requests.append(
                FetchRequest(
                    source="cfbd",
                    season=season,
                    url=f"{CFBD_BASE_URL}{path}?{query}",
                    cache_path=f"cfbd/{name}/{season}.json",
                    endpoint=path,
                    params=sorted_params,
                )
            )
        return requests

    def run(self, season: int, names: Sequence[str], *, dry_run: bool) -> BatchSummary:
        requests = self.plan(season, names)
        if not dry_run and self._token is None:
            raise MissingApiKeyError("CFBD_API_KEY is not set; cannot run a live CFBD collection")
        return run_requests(
            self._cache,
            requests,
            source="cfbd",
            season_label=str(season),
            dry_run=dry_run,
            bearer_token=self._token,
        )

    def info(self) -> InfoSnapshot:
        if self._token is None:
            raise MissingApiKeyError("CFBD_API_KEY is not set; cannot call /info")
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        req = FetchRequest(
            source="cfbd",
            season=None,
            url=f"{CFBD_BASE_URL}/info",
            cache_path=f"cfbd/info/{timestamp}.json",
            endpoint="/info",
        )
        result = self._cache.get_or_fetch(req, bearer_token=self._token)
        return parse_info(result.content)

    def probe_info_cost(self) -> bool | None:
        before = self.info()
        after = self.info()
        if before.remaining_calls is None or after.remaining_calls is None:
            return None
        return self._budget.record_info_probe(before.remaining_calls, after.remaining_calls)
