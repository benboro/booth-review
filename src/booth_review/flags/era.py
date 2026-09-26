"""FLAG-01: measurement-era assignment by the telecast's own air date, from
a dated public table (data/reference/measurement_eras.csv). Ratings
Reference's own `era_id` is used only as a cross-check (`era_check`) --
never to assign an era -- because RR's era_id is coarser than this project's
own dated boundaries and can reflect a claim's report date rather than the
telecast's air date (research Pitfall 2).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from booth_review.errors import ReferenceTableError
from booth_review.reference import read_reference_csv

ERA_COLUMNS = ("era_id", "label", "start_date", "end_date", "rr_era_ids", "source_url", "note")

EraCheck = Literal["agree", "disagree", "not_comparable"]

_ID_RE = re.compile(r"^[a-z0-9-]+$")


@dataclass(frozen=True)
class MeasurementEra:
    era_id: str
    label: str
    start: date | None
    end: date | None
    rr_era_ids: frozenset[str]
    source_url: str
    note: str


def _parse_date(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def load_eras(reference_dir: Path) -> list[MeasurementEra]:
    """Load and validate measurement_eras.csv: contiguous dated eras (no gap
    or overlap), only the first era's start_date and the last era's
    end_date blank, every era_id a lowercase-digit-hyphen slug, and a
    https:// source_url on every row.
    """
    path = reference_dir / "measurement_eras.csv"
    rows = read_reference_csv(path, ERA_COLUMNS, required=True)

    eras: list[MeasurementEra] = []
    for row in rows:
        era_id = row["era_id"]
        if not _ID_RE.match(era_id):
            raise ReferenceTableError(f"{path.name}: invalid era_id {era_id!r}")
        source_url = row["source_url"]
        if not source_url.startswith("https://"):
            raise ReferenceTableError(f"{path.name}: {era_id}: source_url must start with https://")
        eras.append(
            MeasurementEra(
                era_id=era_id,
                label=row["label"],
                start=_parse_date(row["start_date"]),
                end=_parse_date(row["end_date"]),
                rr_era_ids=frozenset(v for v in row["rr_era_ids"].split("|") if v),
                source_url=source_url,
                note=row["note"],
            )
        )

    eras.sort(key=lambda e: (e.start is not None, e.start or date.min))

    for index, era in enumerate(eras):
        is_first = index == 0
        is_last = index == len(eras) - 1
        if is_first:
            if era.start is not None:
                raise ReferenceTableError(
                    f"{path.name}: the first era ({era.era_id}) must have a blank start_date"
                )
        elif era.start is None:
            raise ReferenceTableError(
                f"{path.name}: only the first era may have a blank start_date ({era.era_id})"
            )
        if is_last:
            if era.end is not None:
                raise ReferenceTableError(
                    f"{path.name}: the last era ({era.era_id}) must have a blank end_date"
                )
        elif era.end is None:
            raise ReferenceTableError(
                f"{path.name}: only the last era may have a blank end_date ({era.era_id})"
            )
        if not is_first:
            previous = eras[index - 1]
            if (
                previous.end is None
                or era.start is None
                or era.start != previous.end + timedelta(days=1)
            ):
                raise ReferenceTableError(
                    f"{path.name}: eras {previous.era_id} and {era.era_id} are not contiguous"
                )

    return eras


def era_for(air_date: date, eras: Sequence[MeasurementEra]) -> MeasurementEra:
    """The era covering `air_date` (start inclusive, end inclusive)."""
    for era in eras:
        if (era.start is None or air_date >= era.start) and (
            era.end is None or air_date <= era.end
        ):
            return era
    raise ReferenceTableError(f"no measurement era covers {air_date.isoformat()}")


def era_check(era: MeasurementEra, rr_era_id: str | None) -> EraCheck:
    """Cross-check only (research Pitfall 2): RR's era_id never assigns an
    era; it only reports rough agreement or disagreement with the
    air-date-derived era above. A missing rr_era_id is not comparable.
    """
    if rr_era_id is None:
        return "not_comparable"
    return "agree" if rr_era_id in era.rr_era_ids else "disagree"
