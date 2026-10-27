"""Draft rows for data/reference/nfl_stadium_locations.csv (Phase 24, D-05).

Reads cached stadium articles from the vault, offline, and proposes one row per id.
Coordinates come only from the article's microformat; an uncached or unparsable
article leaves lat/lon blank with a note. The user confirms every row before it is
copied into data/reference/.
"""

from __future__ import annotations

import csv
from pathlib import Path

from booth_review.config import DataPaths
from booth_review.nfl.layout import (
    NFL_WIKIPEDIA_STADIUM_PAGES,
    wikipedia_stadium_owner,
    wikipedia_stadium_path,
    wikipedia_stadium_url,
)
from booth_review.sources.wikipedia.stadium_parser import parse_stadium_coordinates

DRAFT_COLUMNS = (
    "stadium_id",
    "name",
    "city",
    "state",
    "country",
    "lat",
    "lon",
    "source_url",
    "note",
)
DEFAULT_OUT = Path("data/incoming/nfl-stadiums")


def _known(reference_dir: Path) -> dict[str, dict[str, str]]:
    path = reference_dir / "nfl_stadiums.csv"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["stadium_id"]: row for row in csv.DictReader(handle)}


def build_draft_rows(paths: DataPaths, reference_dir: Path) -> list[dict[str, str]]:
    known = _known(reference_dir)
    rows: list[dict[str, str]] = []
    for stadium_id, title in NFL_WIKIPEDIA_STADIUM_PAGES:
        have = known.get(stadium_id, {})
        row = dict.fromkeys(DRAFT_COLUMNS, "")
        row["stadium_id"] = stadium_id
        row["name"] = have.get("stadium", "")
        row["country"] = have.get("country", "")
        row["source_url"] = wikipedia_stadium_url(title)
        cached = paths.raw / wikipedia_stadium_path(wikipedia_stadium_owner(stadium_id))
        if not cached.is_file():
            row["note"] = "article not cached"
        else:
            coords = parse_stadium_coordinates(cached.read_bytes())
            if coords is None:
                row["note"] = "no coordinates in article"
            else:
                row["lat"], row["lon"] = f"{coords[0]:.4f}", f"{coords[1]:.4f}"
        rows.append(row)
    return rows


def write_draft(rows: list[dict[str, str]], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "draft.csv"
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DRAFT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return target
