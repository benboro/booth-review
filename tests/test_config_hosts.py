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


@pytest.mark.parametrize("host", ["www.sportsmediawatch.com", "espnpressroom.com"])
def test_smw_and_espnpr_are_never_fetched(host: str) -> None:
    """Hand-saved or manual sources have no host policy, so the client refuses them."""
    import httpx2

    from booth_review.errors import UnknownHostError
    from booth_review.transport.client import PoliteClient

    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, content=b"", request=request)

    client = PoliteClient(
        transport=httpx2.MockTransport(handler), clock=lambda: 0.0, sleep=lambda _s: None
    )
    assert host not in HOST_POLICIES
    with pytest.raises(UnknownHostError):
        client.fetch(f"https://{host}/")
    assert sent == []
