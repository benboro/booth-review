"""Local stations never resolve to a national network (2026-10-31).

506 lists local simulcasts by station or market ("ABC North Dakota / MW+",
"KMYS CW35 San Antonio"). Those are not the national ABC, CBS, NBC, FOX or
The CW telecast, so they map to `local-broadcast-affiliate`, and that network
sits at the lowest tier so the rights-holder it simulcasts (MW+, ESPN+, a
conference network) stays primary. These tests run against the real
data/reference/networks.csv.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

from booth_review.resolve.networks import load_networks, primary_network

REFERENCE = Path("data/reference")
LOCAL = "local-broadcast-affiliate"

# Every outlet string that may resolve to a national broadcast network. A new
# variant has to be added here on purpose: a market name, a station's call
# letters or channel number means a local station, which maps to LOCAL instead.
NATIONAL_VARIANTS: dict[str, set[str]] = {
    "abc": {"ABC", "ABC*"},
    "cbs": {"CBS"},
    "nbc": {"NBC"},
    "fox": {"FOX", "FOX*"},
    "cw": {"CW", "CW NETWORK", "The CW", "The CW Network"},
}

# US call letters (K or W plus two or three letters) as a separate word.
_CALL_SIGN = re.compile(r"\b[KW][A-Z]{2,3}\b")


def _rows() -> list[dict[str, str]]:
    with (REFERENCE / "networks.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_national_broadcast_networks_take_only_listed_variants() -> None:
    found: dict[str, set[str]] = {network: set() for network in NATIONAL_VARIANTS}
    for row in _rows():
        if row["network_id"] in found:
            found[row["network_id"]].add(row["variant"])
    for network, variants in found.items():
        unexpected = sorted(variants - NATIONAL_VARIANTS[network])
        assert not unexpected, (
            f"{network}: {unexpected} would put a local station on the national network; "
            f"map it to {LOCAL}, or add it to NATIONAL_VARIANTS if it really is national"
        )


def test_call_sign_variants_never_map_to_a_national_network() -> None:
    offenders = [
        row["variant"]
        for row in _rows()
        if row["network_id"] in NATIONAL_VARIANTS and _CALL_SIGN.search(row["variant"])
    ]
    assert offenders == []


def test_local_broadcast_affiliate_is_the_lowest_tier() -> None:
    tiers = {row["tier"] for row in _rows() if row["network_id"] == LOCAL}
    assert tiers == {"other"}


@pytest.mark.parametrize(
    ("outlets", "expected"),
    [
        ("ABC North Dakota / MW+", "mountain-west-network"),
        ("MW+ / ABC North Dakota", "mountain-west-network"),
        ("KMYS CW35 San Antonio / ESPN+", "espn-plus"),
        ("WBRC FOX 6 (Birmingham)", LOCAL),
        ("ABC North Dakota", LOCAL),
        ("ABC", "abc"),
    ],
)
def test_local_simulcast_never_takes_primary_from_the_rights_holder(
    outlets: str, expected: str
) -> None:
    table = load_networks(REFERENCE, required=True)
    result = primary_network([outlets], 2026, table)
    assert result.network_id == expected
    assert "abc" not in result.outlets or outlets == "ABC"
