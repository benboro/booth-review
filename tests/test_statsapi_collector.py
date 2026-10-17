"""Offline tests for the gated Stats API collector: synthetic bodies, mock transport."""

from __future__ import annotations

import json
from datetime import date

import pytest

from booth_review import config
from booth_review.config import HOST_POLICIES, HostPolicy
from booth_review.errors import RunCapError
from booth_review.mlb.constants import STATSAPI_MAX_REQUESTS
from booth_review.mlb.layout import statsapi_schedule_path
from booth_review.sources.statsapi.collector import (
    STATSAPI_HOST,
    STATSAPI_HOST_POLICY_KWARGS,
    StatsApiCollector,
    StatsApiInvalidError,
    StatsApiRefused,
    plan_dates,
    statsapi_route_closed,
)
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient

_D1, _D2 = date(2026, 4, 24), date(2026, 5, 1)
_ROBOTS = f"https://{STATSAPI_HOST}/robots.txt"


def _url(day: date) -> str:
    return (
        f"https://{STATSAPI_HOST}/api/v1/schedule?sportId=1&date={day.isoformat()}&hydrate=lineups"
    )


def test_plan_dedupes_and_shapes_requests() -> None:
    reqs = plan_dates([_D2, _D1, _D1], max_requests=10)
    assert [r.url for r in reqs] == [_url(_D1), _url(_D2)]
    assert reqs[0].source == "mlb_statsapi"
    assert reqs[0].cache_path == statsapi_schedule_path(_D1)
    assert dict(reqs[0].headers) == {"Accept": "application/json"}


def test_plan_caps_are_enforced() -> None:
    days = [date(2026, 4, 1 + i) for i in range(5)]
    with pytest.raises(RunCapError):
        plan_dates(days, max_requests=4)
    many = [date(2026, 5, 1) + (date(2026, 5, 2) - date(2026, 5, 1)) * i for i in range(61)]
    assert len(many) > STATSAPI_MAX_REQUESTS
    with pytest.raises(RunCapError):
        plan_dates(many, max_requests=1000)


def test_plan_rejects_other_years() -> None:
    with pytest.raises(ValueError, match="calendar year"):
        plan_dates([date(2025, 9, 1)], max_requests=5)


def test_statsapi_host_not_enabled() -> None:
    assert STATSAPI_HOST not in HOST_POLICIES
    assert STATSAPI_HOST not in config.HOST_SOURCE


def _collector(vault_paths, handle, monkeypatch) -> StatsApiCollector:
    policy = HostPolicy(**STATSAPI_HOST_POLICY_KWARGS)  # type: ignore[arg-type]
    policies = {**HOST_POLICIES, STATSAPI_HOST: policy}
    monkeypatch.setitem(config.HOST_SOURCE, STATSAPI_HOST, "mlb_statsapi")
    client = PoliteClient(
        transport=handle.transport,
        clock=lambda: 0.0,
        sleep=lambda s: None,
        host_policies=policies,
    )
    return StatsApiCollector(RawCache(vault_paths, client), vault_paths)


def test_dry_run_sends_nothing(vault_paths, mock_transport_factory, monkeypatch) -> None:
    handle = mock_transport_factory({})
    summary = _collector(vault_paths, handle, monkeypatch).run(
        plan_dates([_D1, _D2], max_requests=5), dry_run=True
    )
    assert summary.planned == 2
    assert summary.fetched == 0
    assert handle.requests == []


def test_200_is_cached_with_structure_booleans(
    vault_paths, mock_transport_factory, monkeypatch
) -> None:
    body = json.dumps({"copyright": "x", "dates": [{"games": [{"lineups": {}}]}]}).encode()
    handle = mock_transport_factory({_ROBOTS: (404, b"nf", {}), _url(_D1): (200, body, {})})
    summary = _collector(vault_paths, handle, monkeypatch).run(plan_dates([_D1], max_requests=5))
    assert summary.fetched == 1
    assert summary.has_dates
    assert summary.has_lineups
    assert summary.top_level_keys == ("copyright", "dates")
    assert (vault_paths.raw / statsapi_schedule_path(_D1)).read_bytes() == body
    assert all(isinstance(v, int) for v in summary.counts().values())


@pytest.mark.parametrize("status", [406, 403, 404, 429])
def test_first_4xx_is_terminal(vault_paths, mock_transport_factory, monkeypatch, status) -> None:
    handle = mock_transport_factory(
        {_ROBOTS: (404, b"nf", {}), _url(_D1): (status, b"no", {}), _url(_D2): (200, b"{}", {})}
    )
    col = _collector(vault_paths, handle, monkeypatch)
    with pytest.raises(StatsApiRefused) as info:
        col.run(plan_dates([_D1, _D2], max_requests=5))
    assert info.value.status_class == "4xx"
    schedule_calls = [r for r in handle.requests if "/api/v1/" in r.url]
    assert len(schedule_calls) == 1


def test_non_json_200_not_cached(vault_paths, mock_transport_factory, monkeypatch) -> None:
    handle = mock_transport_factory({_ROBOTS: (404, b"nf", {}), _url(_D1): (200, b"<html>", {})})
    with pytest.raises(StatsApiInvalidError):
        _collector(vault_paths, handle, monkeypatch).run(plan_dates([_D1], max_requests=5))
    assert not (vault_paths.raw / statsapi_schedule_path(_D1)).exists()


def test_refusal_is_persisted_so_a_second_run_sends_nothing(
    vault_paths, mock_transport_factory, monkeypatch
) -> None:
    handle = mock_transport_factory({_ROBOTS: (404, b"nf", {}), _url(_D1): (406, b"no", {})})
    with pytest.raises(StatsApiRefused):
        _collector(vault_paths, handle, monkeypatch).run(plan_dates([_D1], max_requests=5))
    assert statsapi_route_closed(vault_paths)
    sent = len(handle.requests)

    again = mock_transport_factory({_ROBOTS: (404, b"nf", {}), _url(_D2): (200, b"{}", {})})
    with pytest.raises(StatsApiRefused):
        _collector(vault_paths, again, monkeypatch).run(plan_dates([_D2], max_requests=5))
    assert again.requests == []
    assert sent >= 1


def test_route_open_without_refusal(vault_paths) -> None:
    assert not statsapi_route_closed(vault_paths)
