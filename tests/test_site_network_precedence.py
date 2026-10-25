"""G3: the site's network precedence names every network the crosswalks can produce.

site/modules/network.js NETWORK_PRECEDENCE orders the networks shown together. An id the list
lacks sorts after every listed one, so a crosswalk id missing from it (MLB Network as `mlbn`,
for example) would fall behind a streaming service. This reads the public crosswalks in
data/reference/ and the list from the JS source.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NETWORK_JS = ROOT / "site" / "modules" / "network.js"
REFERENCE = ROOT / "data" / "reference"


def _precedence() -> list[str]:
    text = NETWORK_JS.read_text(encoding="utf-8")
    match = re.search(r"NETWORK_PRECEDENCE = Object\.freeze\(\[(.*?)\]\)", text, re.DOTALL)
    assert match, "NETWORK_PRECEDENCE not found in network.js"
    return re.findall(r"'([^']+)'", match.group(1))


def _crosswalk_ids() -> set[str]:
    ids: set[str] = set()
    files = sorted(REFERENCE.glob("*networks.csv"))
    assert files, "no network crosswalks found"
    for path in files:
        with path.open(encoding="utf-8", newline="") as fh:
            ids.update(row["network_id"] for row in csv.DictReader(fh) if row["network_id"])
    return ids


def test_every_crosswalk_network_id_is_in_the_precedence_list() -> None:
    missing = sorted(_crosswalk_ids() - set(_precedence()))
    assert missing == [], f"network ids missing from NETWORK_PRECEDENCE: {missing}"


def test_precedence_list_has_no_dead_or_repeated_ids() -> None:
    order = _precedence()
    assert len(order) == len(set(order)), "an id is listed twice"
    dead = sorted(set(order) - _crosswalk_ids())
    assert dead == [], f"ids in NETWORK_PRECEDENCE that no crosswalk produces: {dead}"


def test_each_family_runs_broadcast_then_cable_then_streaming() -> None:
    """Within a family in networks.csv, no streaming id ranks above a broadcast or cable id,
    and no cable id above a broadcast id."""
    tiers = {"broadcast": 0, "cable": 1, "streaming": 2}
    rank = {nid: k for k, nid in enumerate(_precedence())}
    by_family: dict[str, dict[str, int]] = {}
    with (REFERENCE / "networks.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["tier"] in tiers:
                by_family.setdefault(row["family"], {})[row["network_id"]] = tiers[row["tier"]]
    for family, members in by_family.items():
        ordered = sorted(members, key=lambda nid: rank[nid])
        seq = [members[nid] for nid in ordered]
        assert seq == sorted(seq), (family, ordered)
