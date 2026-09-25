"""Offline tests for CfbdBudget: allow-list, floor, unknown-budget, run cap,
and ledger accounting. No network; FetchRequest/FetchResponse are built by
hand and fed directly to before_fetch/after_fetch.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from booth_review.errors import (
    BudgetFloorError,
    BudgetUnknownError,
    EndpointNotAllowedError,
    RunCapError,
)
from booth_review.transport.budget import ALLOWED_ENDPOINTS, CfbdBudget, parse_info
from booth_review.transport.types import FetchRequest, FetchResponse, Source

CFBD_BASE = "https://api.collegefootballdata.com"


def _req(
    endpoint: str | None,
    *,
    params: tuple[tuple[str, str], ...] = (),
    source: Source = "cfbd",
    season: int | None = 2025,
) -> FetchRequest:
    return FetchRequest(
        source=source,
        season=season,
        url=f"{CFBD_BASE}{endpoint or ''}",
        cache_path=f"cfbd/{(endpoint or 'none').strip('/')}.json",
        endpoint=endpoint,
        params=params,
        kind="page",
    )


def _resp(
    *,
    status: int = 200,
    content: bytes = b"{}",
    call_limit_remaining: int | None = None,
    fetched_at: datetime | None = None,
) -> FetchResponse:
    return FetchResponse(
        status_code=status,
        content=content,
        etag=None,
        last_modified=None,
        call_limit_remaining=call_limit_remaining,
        final_url=f"{CFBD_BASE}/x",
        fetched_at=fetched_at or datetime(2026, 9, 24, 18, 0, 0, tzinfo=UTC),
    )


def _info_resp(remaining: int, *, header: int | None = None) -> FetchResponse:
    body = json.dumps(
        {
            "remainingCalls": remaining,
            "monthlyLimit": 1000,
            "usedCalls": 1000 - remaining,
            "resetAt": "2026-10-01T00:00:00Z",
        }
    ).encode("utf-8")
    return _resp(content=body, call_limit_remaining=header if header is not None else remaining)


@dataclass
class _Clock:
    dt: datetime

    def __call__(self) -> datetime:
        return self.dt


def test_before_fetch_ignores_non_cfbd_source(tmp_path: Path) -> None:
    ledger = tmp_path / "cfbd_ledger.jsonl"
    budget = CfbdBudget(ledger)
    req = _req(None, source="sports506", season=2025)
    budget.before_fetch(req)  # must not raise
    budget.after_fetch(req, _resp())
    assert not ledger.exists()


@pytest.mark.parametrize("endpoint", ["/metrics/wp", "/plays", "/talent", None])
def test_disallowed_endpoint_raises(tmp_path: Path, endpoint: str | None) -> None:
    budget = CfbdBudget(tmp_path / "cfbd_ledger.jsonl")
    with pytest.raises(EndpointNotAllowedError):
        budget.before_fetch(_req(endpoint))


def test_allowed_endpoints_pass_allow_list(tmp_path: Path) -> None:
    budget = CfbdBudget(tmp_path / "cfbd_ledger.jsonl")
    budget.after_fetch(_req("/info"), _info_resp(900))
    for endpoint in sorted(ALLOWED_ENDPOINTS):
        budget.before_fetch(_req(endpoint))  # must not raise


def test_empty_ledger_unknown_budget_but_info_allowed(tmp_path: Path) -> None:
    budget = CfbdBudget(tmp_path / "cfbd_ledger.jsonl")
    with pytest.raises(BudgetUnknownError):
        budget.before_fetch(_req("/games"))
    budget.before_fetch(_req("/info"))  # must not raise


def test_info_response_sets_last_known_remaining(tmp_path: Path) -> None:
    budget = CfbdBudget(tmp_path / "cfbd_ledger.jsonl")
    budget.after_fetch(_req("/info"), _info_resp(600, header=600))
    assert budget.last_known_remaining() == 600
    budget.before_fetch(_req("/games"))  # must not raise


def test_floor_boundary(tmp_path: Path) -> None:
    at_floor = CfbdBudget(tmp_path / "a.jsonl", floor=250)
    at_floor.after_fetch(_req("/info"), _info_resp(250))
    with pytest.raises(BudgetFloorError):
        at_floor.before_fetch(_req("/games"))

    above_floor = CfbdBudget(tmp_path / "b.jsonl", floor=250)
    above_floor.after_fetch(_req("/info"), _info_resp(251))
    above_floor.before_fetch(_req("/games"))  # must not raise


def test_month_rollover_forgets_previous_month(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 9, 24, 12, 0, 0, tzinfo=UTC))
    budget = CfbdBudget(tmp_path / "cfbd_ledger.jsonl", now=clock)
    budget.after_fetch(_req("/info"), _info_resp(600, header=600))
    assert budget.last_known_remaining() == 600

    clock.dt = datetime(2026, 10, 1, 0, 5, 0, tzinfo=UTC)
    assert budget.last_known_remaining() is None
    with pytest.raises(BudgetUnknownError):
        budget.before_fetch(_req("/games"))


def test_discrepancy_flagged_and_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    ledger = tmp_path / "cfbd_ledger.jsonl"
    budget = CfbdBudget(ledger)
    caplog.set_level(logging.WARNING)
    budget.after_fetch(_req("/info"), _info_resp(590, header=600))

    lines = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert lines[-1]["discrepancy"] is True

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "600" in message
    assert "590" in message


def test_after_fetch_records_full_schema(tmp_path: Path) -> None:
    ledger = tmp_path / "cfbd_ledger.jsonl"
    budget = CfbdBudget(ledger, tag="spike")
    budget.after_fetch(_req("/info"), _info_resp(900, header=900))

    line = json.loads(ledger.read_text(encoding="utf-8").strip())
    expected_keys = {
        "event",
        "endpoint",
        "params",
        "called_at",
        "month",
        "status",
        "call_limit_remaining_header",
        "info_remaining_calls",
        "info_reset_at",
        "counted_against_quota",
        "discrepancy",
        "tag",
    }
    assert set(line.keys()) == expected_keys
    assert line["event"] == "call"
    assert line["endpoint"] == "/info"
    assert line["tag"] == "spike"


def test_after_fetch_records_500_response(tmp_path: Path) -> None:
    ledger = tmp_path / "cfbd_ledger.jsonl"
    budget = CfbdBudget(ledger)
    budget.after_fetch(_req("/games", params=(("year", "2025"),)), _resp(status=500))

    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["status"] == 500
    assert entry["counted_against_quota"] is True


def test_counted_against_quota_data_vs_info(tmp_path: Path) -> None:
    ledger = tmp_path / "cfbd_ledger.jsonl"
    budget = CfbdBudget(ledger)
    budget.after_fetch(_req("/games", params=(("year", "2025"),)), _resp())
    budget.after_fetch(_req("/info"), _info_resp(900, header=900))

    lines = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["counted_against_quota"] is True
    assert lines[1]["counted_against_quota"] is None

    budget.record_info_probe(before=900, after=900)
    budget.after_fetch(_req("/info"), _info_resp(900, header=900))

    lines = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert lines[-1]["counted_against_quota"] is False


def test_run_cap_raises_on_third_counted_call(tmp_path: Path) -> None:
    ledger = tmp_path / "cfbd_ledger.jsonl"
    budget = CfbdBudget(ledger, max_calls=2)
    # Probe /info as free first so it never itself consumes a run-cap slot;
    # this isolates the cap to the two counted /games calls below.
    budget.record_info_probe(before=900, after=900)
    budget.after_fetch(_req("/info"), _info_resp(900, header=900))
    assert budget.run_calls == 0

    for remaining in (899, 898):
        req = _req("/games", params=(("year", "2025"),))
        budget.before_fetch(req)
        budget.after_fetch(req, _resp(call_limit_remaining=remaining))

    assert budget.run_calls == 2
    with pytest.raises(RunCapError):
        budget.before_fetch(_req("/games", params=(("year", "2025"),)))


def test_run_cap_counts_info_calls_when_probe_unknown(tmp_path: Path) -> None:
    ledger = tmp_path / "cfbd_ledger.jsonl"
    budget = CfbdBudget(ledger, max_calls=2)

    for _ in range(2):
        req = _req("/info")
        budget.before_fetch(req)
        budget.after_fetch(req, _info_resp(900, header=900))

    assert budget.run_calls == 2
    with pytest.raises(RunCapError):
        budget.before_fetch(_req("/info"))


def test_run_cap_ignores_info_calls_once_probe_confirms_free(tmp_path: Path) -> None:
    ledger = tmp_path / "cfbd_ledger.jsonl"
    budget = CfbdBudget(ledger, max_calls=1)
    budget.record_info_probe(before=900, after=900)

    for _ in range(3):
        req = _req("/info")
        budget.before_fetch(req)  # must not raise: /info never counts once known free
        budget.after_fetch(req, _info_resp(900, header=900))

    assert budget.run_calls == 0


def test_record_info_probe_results(tmp_path: Path) -> None:
    ledger = tmp_path / "cfbd_ledger.jsonl"
    budget = CfbdBudget(ledger)
    assert budget.record_info_probe(before=600, after=600) is False
    assert budget.record_info_probe(before=600, after=599) is True
    assert budget.record_info_probe(before=600, after=590) is None

    lines = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert [line["event"] for line in lines] == ["info_cost_probe"] * 3
    assert [line["counted_against_quota"] for line in lines] == [False, True, None]


def test_summary_returns_counts_by_endpoint_and_tag(tmp_path: Path) -> None:
    ledger = tmp_path / "cfbd_ledger.jsonl"
    budget = CfbdBudget(ledger, tag="spike")
    budget.after_fetch(_req("/info"), _info_resp(900, header=900))
    budget.after_fetch(_req("/games", params=(("year", "2025"),)), _resp(call_limit_remaining=899))
    budget.after_fetch(_req("/games", params=(("year", "2025"),)), _resp(call_limit_remaining=898))

    summary = budget.summary()
    assert summary.by_endpoint == {"/info": 1, "/games": 2}
    assert summary.by_tag == {"spike": 3}
    assert summary.calls_counted == 2
    assert summary.last_remaining == 898
    assert summary.floor == 250
    assert summary.info_counts_against_quota is None


def test_ledger_never_contains_bearer_or_authorization(tmp_path: Path) -> None:
    ledger = tmp_path / "cfbd_ledger.jsonl"
    budget = CfbdBudget(ledger)
    budget.after_fetch(_req("/info"), _info_resp(900, header=900))
    budget.after_fetch(
        _req("/games", params=(("year", "2025"), ("seasonType", "both"))),
        _resp(call_limit_remaining=899),
    )

    raw = ledger.read_text(encoding="utf-8")
    assert "Authorization" not in raw
    assert "Bearer" not in raw


def test_parse_info_reads_documented_fields() -> None:
    snapshot = parse_info(
        json.dumps(
            {
                "remainingCalls": 743,
                "monthlyLimit": 1000,
                "usedCalls": 257,
                "resetAt": "2026-10-01T00:00:00Z",
            }
        ).encode("utf-8")
    )
    assert snapshot.remaining_calls == 743
    assert snapshot.monthly_limit == 1000
    assert snapshot.used_calls == 257
    assert snapshot.reset_at == "2026-10-01T00:00:00Z"
