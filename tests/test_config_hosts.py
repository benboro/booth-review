"""HOST_POLICIES and HOST_SOURCE must stay in step."""

from __future__ import annotations

import pytest

from booth_review.config import HOST_POLICIES, HOST_SOURCE


def test_host_policies_and_host_source_share_keys() -> None:
    assert set(HOST_POLICIES) == set(HOST_SOURCE)


@pytest.mark.parametrize(
    ("host", "source"),
    [
        ("raw.githubusercontent.com", "nfl_nflverse"),
        ("api.github.com", "nfl_nflverse"),
        ("release-assets.githubusercontent.com", "nfl_nflverse"),
        ("objects.githubusercontent.com", "nfl_nflverse"),
        ("en.wikipedia.org", "nfl_wikipedia"),
    ],
)
def test_new_nfl_hosts_are_allow_listed(host: str, source: str) -> None:
    assert HOST_SOURCE[host] == source
    assert HOST_POLICIES[host].retry_mode == "standard"
    assert HOST_POLICIES[host].min_interval_s >= 2.0
