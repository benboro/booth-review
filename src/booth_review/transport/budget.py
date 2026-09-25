"""CfbdBudget: the FetchGuard that makes CFBD overspend structurally impossible.

Applies a literal endpoint allow-list, keeps a persistent monthly JSONL ledger
in the vault (data/vault/ledger/cfbd_ledger.jsonl), refuses calls below the
floor or with an unknown budget, enforces a per-run cap, and cross-checks
X-CallLimit-Remaining against /info, including an empirical probe of whether
/info itself counts against the quota (FOUND-03, D-12).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from booth_review.config import CFBD_FLOOR_DEFAULT
from booth_review.errors import (
    BudgetFloorError,
    BudgetUnknownError,
    EndpointNotAllowedError,
    RunCapError,
)
from booth_review.transport.types import FetchGuard, FetchRequest, FetchResponse

logger = logging.getLogger(__name__)

ALLOWED_ENDPOINTS: frozenset[str] = frozenset(
    {
        "/games",
        "/games/media",
        "/metrics/wp/pregame",
        "/lines",
        "/rankings",
        "/teams/fbs",
        "/info",
    }
)

# Header vs. /info disagreements up to this many calls apart are normal
# rounding/timing noise; beyond it, flag a discrepancy (Pitfall 4).
_DISCREPANCY_THRESHOLD = 2


@dataclass(frozen=True)
class InfoSnapshot:
    """Parsed fields from CFBD's documented /info UserInfo response body."""

    remaining_calls: int | None
    monthly_limit: int | None
    used_calls: int | None
    reset_at: str | None


def parse_info(content: bytes) -> InfoSnapshot:
    """Parse a /info response body into an InfoSnapshot.

    Missing fields become None rather than raising: a schema drift on CFBD's
    side shouldn't crash budget accounting, only degrade it to "unknown".
    """
    data: dict[str, Any] = json.loads(content)
    return InfoSnapshot(
        remaining_calls=data.get("remainingCalls"),
        monthly_limit=data.get("monthlyLimit"),
        used_calls=data.get("usedCalls"),
        reset_at=data.get("resetAt"),
    )


@dataclass(frozen=True)
class BudgetSummary:
    """A month's CFBD call accounting, read back from the ledger."""

    month: str
    calls_counted: int
    by_endpoint: dict[str, int]
    by_tag: dict[str, int]
    last_remaining: int | None
    info_counts_against_quota: bool | None
    floor: int


def _default_now() -> datetime:
    return datetime.now(UTC)


class CfbdBudget(FetchGuard):
    """FetchGuard enforcing the CFBD allow-list, floor, and per-run cap.

    Every CFBD call that is actually sent is recorded in `ledger_path`, an
    append-only JSONL file (one line per event). Ledger lines never carry
    request/response headers beyond the parsed X-CallLimit-Remaining number.
    """

    def __init__(
        self,
        ledger_path: Path,
        *,
        floor: int = CFBD_FLOOR_DEFAULT,
        max_calls: int | None = None,
        tag: str | None = None,
        now: Callable[[], datetime] = _default_now,
    ) -> None:
        self._ledger_path = ledger_path
        self._floor = floor
        self._max_calls = max_calls
        self._tag = tag
        self._now = now
        self.run_calls = 0

    # -- FetchGuard protocol --------------------------------------------

    def before_fetch(self, req: FetchRequest) -> None:
        if req.source != "cfbd":
            return
        if req.endpoint not in ALLOWED_ENDPOINTS:
            raise EndpointNotAllowedError(f"CFBD endpoint not allowed: {req.endpoint!r}")

        is_info = req.endpoint == "/info"
        if not is_info:
            remaining = self.last_known_remaining()
            if remaining is None:
                raise BudgetUnknownError(
                    "CFBD remaining-call budget is unknown this month; call /info first"
                )
            if remaining - 1 < self._floor:
                raise BudgetFloorError(
                    f"CFBD call would drop remaining calls below the floor of {self._floor}"
                )

        self._check_run_cap(is_info=is_info)

    def after_fetch(self, req: FetchRequest, resp: FetchResponse) -> None:
        if req.source != "cfbd":
            return

        is_info = req.endpoint == "/info"
        called_at = self._now()
        month = called_at.strftime("%Y-%m")

        info_remaining: int | None = None
        info_reset_at: str | None = None
        discrepancy = False

        if is_info and resp.status_code == 200:
            snapshot = parse_info(resp.content)
            info_remaining = snapshot.remaining_calls
            info_reset_at = snapshot.reset_at
            if (
                info_remaining is not None
                and resp.call_limit_remaining is not None
                and abs(info_remaining - resp.call_limit_remaining) > _DISCREPANCY_THRESHOLD
            ):
                discrepancy = True
                logger.warning(
                    "CFBD budget discrepancy: header=%s info=%s",
                    resp.call_limit_remaining,
                    info_remaining,
                )

        counted: bool | None = self.info_counts_against_quota() if is_info else True

        logger.info(
            "CFBD call: endpoint=%s status=%s remaining_header=%s remaining_info=%s",
            req.endpoint,
            resp.status_code,
            resp.call_limit_remaining,
            info_remaining,
        )

        self._append(
            {
                "event": "call",
                "endpoint": req.endpoint,
                "params": dict(req.params),
                "called_at": called_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "month": month,
                "status": resp.status_code,
                "call_limit_remaining_header": resp.call_limit_remaining,
                "info_remaining_calls": info_remaining,
                "info_reset_at": info_reset_at,
                "counted_against_quota": counted,
                "discrepancy": discrepancy,
                "tag": self._tag,
            }
        )

        if self._would_count_toward_run_cap(is_info=is_info):
            self.run_calls += 1

    # -- Budget queries ---------------------------------------------------

    def last_known_remaining(self, month: str | None = None) -> int | None:
        target_month = month or self._now().strftime("%Y-%m")
        result: int | None = None
        for line in self._read_lines():
            if line.get("event") != "call" or line.get("month") != target_month:
                continue
            candidates = [
                v
                for v in (
                    line.get("call_limit_remaining_header"),
                    line.get("info_remaining_calls"),
                )
                if v is not None
            ]
            if candidates:
                result = min(candidates)
        return result

    def info_counts_against_quota(self) -> bool | None:
        result: bool | None = None
        for line in self._read_lines():
            if line.get("event") == "info_cost_probe":
                result = line.get("counted_against_quota")
        return result

    def record_info_probe(self, before: int, after: int) -> bool | None:
        """Record an empirical two-call probe of whether /info itself counts.

        Returns False when before == after (free), True when it dropped by
        exactly one (counted), or None when other traffic makes the result
        inconclusive.
        """
        delta = before - after
        counted: bool | None
        if delta == 0:
            counted = False
        elif delta == 1:
            counted = True
        else:
            counted = None

        called_at = self._now()
        self._append(
            {
                "event": "info_cost_probe",
                "before": before,
                "after": after,
                "delta": delta,
                "counted_against_quota": counted,
                "called_at": called_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "month": called_at.strftime("%Y-%m"),
                "tag": self._tag,
            }
        )
        return counted

    def summary(self, month: str | None = None) -> BudgetSummary:
        target_month = month or self._now().strftime("%Y-%m")
        by_endpoint: dict[str, int] = {}
        by_tag: dict[str, int] = {}
        calls_counted = 0
        for line in self._read_lines():
            if line.get("event") != "call" or line.get("month") != target_month:
                continue
            endpoint = line.get("endpoint")
            if isinstance(endpoint, str):
                by_endpoint[endpoint] = by_endpoint.get(endpoint, 0) + 1
            tag = line.get("tag")
            if isinstance(tag, str):
                by_tag[tag] = by_tag.get(tag, 0) + 1
            if line.get("counted_against_quota"):
                calls_counted += 1
        return BudgetSummary(
            month=target_month,
            calls_counted=calls_counted,
            by_endpoint=by_endpoint,
            by_tag=by_tag,
            last_remaining=self.last_known_remaining(target_month),
            info_counts_against_quota=self.info_counts_against_quota(),
            floor=self._floor,
        )

    # -- Internals ----------------------------------------------------------

    def _would_count_toward_run_cap(self, *, is_info: bool) -> bool:
        # Data calls always count. /info counts unless a probe has proven it
        # free; an unrecorded probe is treated conservatively as counting.
        return not is_info or self.info_counts_against_quota() is not False

    def _check_run_cap(self, *, is_info: bool) -> None:
        if self._max_calls is None:
            return
        if self._would_count_toward_run_cap(is_info=is_info) and self.run_calls >= self._max_calls:
            raise RunCapError(f"run cap of {self._max_calls} CFBD calls reached")

    def _append(self, entry: dict[str, Any]) -> None:
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self._ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True))
            fh.write("\n")

    def _read_lines(self) -> Iterator[dict[str, Any]]:
        if not self._ledger_path.is_file():
            return
        with self._ledger_path.open(encoding="utf-8") as fh:
            for raw_line in fh:
                stripped = raw_line.strip()
                if stripped:
                    yield json.loads(stripped)
