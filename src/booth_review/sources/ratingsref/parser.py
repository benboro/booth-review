"""Ratings Reference per-telecast JSON record parsing.

Keeps every claim (headline selection is a later-plan resolve-stage concern)
and every unknown field via pydantic's extra="allow", so the inventory can
list fields this research session didn't enumerate. The large `peers` block
is still dropped before validation -- except RR's own current-figure pick for
this telecast (rr_current_claim_id/rr_current_status), which JOIN-04's
disagreement log needs (research Pattern 2) and is extracted before `peers`
is discarded. RR's own pick is treated as best-effort, not authoritative
(research Assumption A3): a status other than "found" means "not comparable,"
never a guess.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from booth_review.errors import ParseError

RRCurrentStatus = Literal["found", "no_peers", "no_self_row", "multiple_current"]


class RRTelecast(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    event_date: date
    title: str | None = None
    networks: list[str] = []
    teams: list[str] = []
    kind: str | None = None
    # Real records carry an int tier level (e.g. 1, 2); the initial research
    # session assumed a string label ("national"), so both are accepted.
    tier: int | str | None = None


class RRClaim(BaseModel):
    model_config = ConfigDict(extra="allow")

    metric_type: str
    status: str
    value: float | None = None
    unit: str | None = None
    cut: str | None = None
    supersedes_id: str | None = None
    era_id: str | None = None
    measured_by: str | None = None
    measurement_method: str | None = None
    publisher: str | None = None
    source_url: str | None = None
    first_published: str | None = None
    confidence: float | None = None
    carrier_network: str | None = None
    composite_of: list[str] | None = None


class RRRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    telecast: RRTelecast
    claims: list[RRClaim] = []
    figures_last_changed: str | None = None
    built_at: str | None = None
    about: dict[str, object] | None = None
    rr_current_claim_id: str | None = None
    rr_current_status: RRCurrentStatus = "no_peers"

    @property
    def record_url(self) -> str:
        return f"https://ratingsreference.com/telecast/{self.telecast.id}"


def _rr_current(data: dict[str, Any]) -> tuple[str | None, RRCurrentStatus]:
    """RR's own current-figure pick for this telecast, read from the (about
    to be dropped) peers block. A pick is accepted only when exactly one row
    both belongs to this telecast (`telecast_id` == this record's own
    `telecast.id`) and is marked `current`; a crafted or malformed peers
    block (T-03-05) never causes an arbitrary pick or a crash -- zero
    matching rows, more than one, or no peers block at all all resolve to a
    "not comparable" status instead.
    """
    telecast = data.get("telecast")
    if not isinstance(telecast, dict):
        return None, "no_peers"
    self_id = telecast.get("id")
    if not isinstance(self_id, str):
        return None, "no_peers"

    peers = data.get("peers")
    if not isinstance(peers, dict):
        return None, "no_peers"
    rows = peers.get("rows")
    if not isinstance(rows, list):
        return None, "no_peers"

    current_claim_ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue  # malformed row: skipped, never raises
        if row.get("telecast_id") != self_id or not row.get("current"):
            continue
        claim_id = row.get("claim_id")
        if isinstance(claim_id, str):
            current_claim_ids.append(claim_id)

    if not current_claim_ids:
        return None, "no_self_row"
    if len(current_claim_ids) > 1:
        return None, "multiple_current"
    return current_claim_ids[0], "found"


def parse_record(content: bytes) -> RRRecord:
    """Parse a Ratings Reference /api/telecast/<id>.json body into an RRRecord."""
    try:
        data: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ParseError(f"ratingsref record: invalid JSON: {exc}") from exc

    if isinstance(data, dict):
        rr_current_claim_id, rr_current_status = _rr_current(data)
        data = {key: value for key, value in data.items() if key != "peers"}
        data["rr_current_claim_id"] = rr_current_claim_id
        data["rr_current_status"] = rr_current_status

    try:
        return RRRecord.model_validate(data)
    except ValidationError as exc:
        fields = ", ".join(".".join(str(part) for part in err["loc"]) for err in exc.errors())
        raise ParseError(f"ratingsref record: validation failed for fields: {fields}") from exc
