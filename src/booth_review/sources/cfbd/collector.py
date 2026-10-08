"""CfbdCollector: plans and fetches allow-listed CFBD season data.

Every call goes through RawCache with a CfbdBudget guard wired in, so the
allow-list, floor, and per-run cap are enforced there; this module only
builds requests for the six per-season endpoints plus the season-less /venues
and /info, and never targets anything outside them (FOUND-03, D-12).

`refresh=True` is used only by the scheduled job (Plan 06), to re-fetch the
current (unfrozen) season's season-level files each run (D-09). A frozen
season still refuses regardless of `refresh`: FreezeGuard exempts only
ratingsref (D-07), never cfbd.
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

# name -> API path, for one-off lists that cover every season. Kept apart from
# ENDPOINTS because ENDPOINTS is iterated as "the six per-season files" by the
# completeness audit, the regression check, the default collect and the
# scheduled job. Venues are one list, collected by hand (`collect cfbd
# --venues`), never by the job.
SEASONLESS_ENDPOINTS: dict[str, str] = {"venues": "/venues"}


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

    def run(
        self, season: int, names: Sequence[str], *, dry_run: bool, refresh: bool = False
    ) -> BatchSummary:
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
            refresh=refresh,
        )

    def plan_static(self, names: Sequence[str]) -> list[FetchRequest]:
        requests: list[FetchRequest] = []
        for name in names:
            if name not in SEASONLESS_ENDPOINTS:
                raise ValueError(f"unknown season-less CFBD endpoint name: {name!r}")
            path = SEASONLESS_ENDPOINTS[name]
            requests.append(
                FetchRequest(
                    source="cfbd",
                    season=None,
                    url=f"{CFBD_BASE_URL}{path}",
                    cache_path=f"cfbd/{name}/all.json",
                    endpoint=path,
                    params=(),
                )
            )
        return requests

    def run_static(self, names: Sequence[str], *, dry_run: bool) -> BatchSummary:
        requests = self.plan_static(names)
        if not dry_run and self._token is None:
            raise MissingApiKeyError("CFBD_API_KEY is not set; cannot run a live CFBD collection")
        return run_requests(
            self._cache,
            requests,
            source="cfbd",
            season_label="all",
            dry_run=dry_run,
            bearer_token=self._token,
            refresh=False,
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

    def ensure_budget_known(self) -> bool:
        """Call /info once when this month's remaining budget is unknown.

        CfbdBudget refuses every data call while the current month has no
        ledger line (BudgetUnknownError), so an unattended caller (the
        scheduled job) runs this before its data calls; the /info response is
        recorded in the ledger by CfbdBudget.after_fetch like any other call.
        Returns True when /info was called, False when the budget was
        already known and nothing was sent.
        """
        if self._budget.last_known_remaining() is not None:
            return False
        self.info()
        return True

    def probe_info_cost(self) -> tuple[InfoSnapshot, bool | None]:
        """Call /info twice and record whether the second call itself counted
        against the budget. Returns the second call's snapshot (for display)
        alongside the probe result (True: counted, False: free, None:
        inconclusive -- see CfbdBudget.record_info_probe).
        """
        before = self.info()
        after = self.info()
        if before.remaining_calls is None or after.remaining_calls is None:
            return after, None
        recorded = self._budget.record_info_probe(before.remaining_calls, after.remaining_calls)
        return after, recorded
