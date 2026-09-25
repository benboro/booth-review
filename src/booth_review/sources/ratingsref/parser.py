"""Ratings Reference per-telecast JSON record parsing.

Keeps every claim (headline selection is a later-plan resolve-stage concern)
and every unknown field via pydantic's extra="allow", so the inventory can
list fields this research session didn't enumerate. The large `peers` block
is dropped before validation; it's ignored by this project.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from booth_review.errors import ParseError


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

    @property
    def record_url(self) -> str:
        return f"https://ratingsreference.com/telecast/{self.telecast.id}"


def parse_record(content: bytes) -> RRRecord:
    """Parse a Ratings Reference /api/telecast/<id>.json body into an RRRecord."""
    try:
        data: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ParseError(f"ratingsref record: invalid JSON: {exc}") from exc

    if isinstance(data, dict):
        data = {key: value for key, value in data.items() if key != "peers"}

    try:
        return RRRecord.model_validate(data)
    except ValidationError as exc:
        fields = ", ".join(".".join(str(part) for part in err["loc"]) for err in exc.errors())
        raise ParseError(f"ratingsref record: validation failed for fields: {fields}") from exc
