"""FLAG-03/FLAG-04: event flags, including the CFBD model-break flag, from a
dated public table (data/reference/event_flags.csv) -- never from a date
literal in code.

Two row kinds share one table: "event" rows (a dated window, optionally
scoped to a network list) and "model_break" rows (every telecast whose
season is at or after season_from, regardless of network).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, cast

from booth_review.errors import ReferenceTableError
from booth_review.reference import read_reference_csv

EVENT_COLUMNS = (
    "flag_id",
    "kind",
    "label",
    "start_date",
    "end_date",
    "season_from",
    "networks",
    "source_url",
    "note",
)

EventKind = Literal["event", "model_break"]

_ID_RE = re.compile(r"^[a-z0-9-]+$")
_KINDS = ("event", "model_break")


@dataclass(frozen=True)
class EventFlag:
    flag_id: str
    kind: EventKind
    label: str
    start: date | None
    end: date | None
    season_from: int | None
    networks: frozenset[str]
    source_url: str
    note: str


def _parse_date(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def load_event_flags(reference_dir: Path) -> list[EventFlag]:
    """Load and validate event_flags.csv. "event" rows require start_date
    and end_date (start <= end) and a blank season_from; "model_break" rows
    require an int season_from and blank dates. networks is a pipe-separated
    list of network ids (blank means every network). flag_id is a unique
    lowercase-digit-hyphen slug; source_url is required and https://.
    """
    path = reference_dir / "event_flags.csv"
    rows = read_reference_csv(path, EVENT_COLUMNS, required=True)

    flags: list[EventFlag] = []
    seen_ids: set[str] = set()
    for row in rows:
        flag_id = row["flag_id"]
        if not _ID_RE.match(flag_id):
            raise ReferenceTableError(f"{path.name}: invalid flag_id {flag_id!r}")
        if flag_id in seen_ids:
            raise ReferenceTableError(f"{path.name}: duplicate flag_id {flag_id!r}")
        seen_ids.add(flag_id)

        kind_raw = row["kind"]
        if kind_raw not in _KINDS:
            raise ReferenceTableError(f"{path.name}: {flag_id}: invalid kind {kind_raw!r}")
        kind = cast(EventKind, kind_raw)

        source_url = row["source_url"]
        if not source_url.startswith("https://"):
            raise ReferenceTableError(
                f"{path.name}: {flag_id}: source_url must start with https://"
            )

        networks = frozenset(v for v in row["networks"].split("|") if v)
        for network_id in networks:
            if not _ID_RE.match(network_id):
                raise ReferenceTableError(
                    f"{path.name}: {flag_id}: invalid network id {network_id!r}"
                )

        start = _parse_date(row["start_date"])
        end = _parse_date(row["end_date"])
        season_from_raw = row["season_from"]
        season_from = int(season_from_raw) if season_from_raw else None

        if kind == "event":
            if start is None or end is None:
                raise ReferenceTableError(
                    f"{path.name}: {flag_id}: event rows require start_date and end_date"
                )
            if season_from is not None:
                raise ReferenceTableError(
                    f"{path.name}: {flag_id}: event rows must leave season_from blank"
                )
            if start > end:
                raise ReferenceTableError(
                    f"{path.name}: {flag_id}: start_date must not be after end_date"
                )
        else:
            if season_from is None:
                raise ReferenceTableError(
                    f"{path.name}: {flag_id}: model_break rows require season_from"
                )
            if start is not None or end is not None:
                raise ReferenceTableError(
                    f"{path.name}: {flag_id}: model_break rows must leave dates blank"
                )

        flags.append(
            EventFlag(
                flag_id=flag_id,
                kind=kind,
                label=row["label"],
                start=start,
                end=end,
                season_from=season_from,
                networks=networks,
                source_url=source_url,
                note=row["note"],
            )
        )
    return flags


def event_flags_for(
    air_date: date, season: int, network_id: str | None, flags: Sequence[EventFlag]
) -> list[str]:
    """Sorted flag ids applying to a telecast on `air_date`/`season` on
    `network_id`. An "event" row applies when start <= air_date <= end and
    (its networks list is blank, or network_id is one of them). A
    "model_break" row applies whenever season >= its season_from, regardless
    of network.
    """
    matched: list[str] = []
    for flag in flags:
        if flag.kind == "event":
            if flag.start is None or flag.end is None:
                continue
            if not (flag.start <= air_date <= flag.end):
                continue
            if flag.networks and (network_id is None or network_id not in flag.networks):
                continue
            matched.append(flag.flag_id)
        else:
            if flag.season_from is not None and season >= flag.season_from:
                matched.append(flag.flag_id)
    return sorted(matched)
