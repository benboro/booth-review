"""Hand-confirmed crew overrides (04.3): loader, post-pass, and gap rows.

data/reference/crew_overrides.csv is the one documented exception to Phase 3
D-05/D-06 (04.3 D-01): every row records a crew that a cited public source
(a network press release, a school recap, a reputable outlet) already
publishes, so it is not 506's compiled listing. Rows are main-feed only
(D-03), carry an explicit role and position from the source (D-02), and are
keyed by (cfbd_game_id, network_id). Loader errors cite file and line only;
build-time failures are count-only (D-04). Nothing here ever echoes a cell.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from booth_review.errors import ReferenceTableError
from booth_review.reference import read_reference_csv

CREW_OVERRIDE_COLUMNS = (
    "cfbd_game_id",
    "network_id",
    "crew_position",
    "person_id",
    "role",
    "reason",
    "source_kind",
    "source_name",
    "source_url",
)

CREW_OVERRIDE_REASONS = frozenset({"no-506-listing", "no-506-crew", "correction"})
# press-release = tier 1 (network press room), school = tier 2 (athletics
# recap or game notes), outlet = tier 3 (reputable outlet), per D-06.
CREW_SOURCE_KINDS = frozenset({"press-release", "school", "outlet"})
CREW_OVERRIDE_ROLES = frozenset({"pbp", "analyst"})
# The telecast_people.source value for override rows.
CREW_OVERRIDE_SOURCE = "crew_override"
SOURCE_NAME_MAX_LEN = 60

# Same slug pattern as resolve/networks.py _NETWORK_ID_RE.
_NETWORK_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_WHITESPACE_RE = re.compile(r"\s")


@dataclass(frozen=True)
class CrewOverride:
    cfbd_game_id: int
    network_id: str
    people: tuple[tuple[str, str], ...]  # (person_id, role), ordered by crew_position
    reason: str
    source_kind: str
    source_name: str
    source_url: str


def load_crew_overrides(reference_dir: Path) -> dict[tuple[int, str], CrewOverride]:
    """Read crew_overrides.csv (not required) into (game id, network id) -> CrewOverride."""
    path = reference_dir / "crew_overrides.csv"
    raw_rows = read_reference_csv(path, CREW_OVERRIDE_COLUMNS, required=False)

    def fail(line_no: int, what: str) -> ReferenceTableError:
        return ReferenceTableError(f"{path.name}: line {line_no}: {what}")

    # key -> list of (line_no, position, person_id, role, reason, kind, name, url)
    grouped: dict[tuple[int, str], list[tuple[int, int, str, str, str, str, str, str]]] = {}
    for line_no, raw in enumerate(raw_rows, start=2):
        try:
            game_id = int(raw["cfbd_game_id"])
        except ValueError:
            raise fail(line_no, "cfbd_game_id must be an integer") from None
        try:
            position = int(raw["crew_position"])
        except ValueError:
            raise fail(line_no, "crew_position must be an integer") from None
        if position < 0:
            raise fail(line_no, "crew_position must not be negative")
        network_id = raw["network_id"]
        if not _NETWORK_ID_RE.match(network_id):
            raise fail(line_no, "network_id must be a lowercase slug")
        person_id = raw["person_id"]
        if not person_id:
            raise fail(line_no, "person_id must not be empty")
        role = raw["role"]
        if role not in CREW_OVERRIDE_ROLES:
            raise fail(line_no, "role must be pbp or analyst")
        reason = raw["reason"]
        if reason not in CREW_OVERRIDE_REASONS:
            raise fail(line_no, "reason must be no-506-listing, no-506-crew, or correction")
        kind = raw["source_kind"]
        if kind not in CREW_SOURCE_KINDS:
            raise fail(line_no, "source_kind must be press-release, school, or outlet")
        url = raw["source_url"]
        if not url:
            raise fail(line_no, "source_url must not be empty")
        if not url.startswith(("https://", "http://")):
            raise fail(line_no, "source_url must start with https:// or http://")
        if _WHITESPACE_RE.search(url):
            raise fail(line_no, "source_url must not contain whitespace")
        name = raw["source_name"]
        if not name:
            raise fail(line_no, "source_name must not be empty")
        if len(name) > SOURCE_NAME_MAX_LEN:
            raise fail(line_no, f"source_name must be at most {SOURCE_NAME_MAX_LEN} characters")
        if "<" in name or ">" in name:
            raise fail(line_no, "source_name must not contain < or >")

        rows = grouped.setdefault((game_id, network_id), [])
        if any(existing[1] == position for existing in rows):
            raise fail(line_no, "duplicate crew_position for this telecast")
        if any(existing[2] == person_id for existing in rows):
            raise fail(line_no, "person_id listed twice for this telecast")
        first = rows[0] if rows else None
        if first is not None and first[4:] != (reason, kind, name, url):
            raise fail(line_no, "reason and source fields must match the telecast's first row")
        rows.append((line_no, position, person_id, role, reason, kind, name, url))

    overrides: dict[tuple[int, str], CrewOverride] = {}
    for (game_id, network_id), rows in grouped.items():
        ordered = sorted(rows, key=lambda row: row[1])
        if [row[1] for row in ordered] != list(range(len(ordered))):
            raise fail(rows[0][0], "crew_position must run contiguously from 0")
        _, _, _, _, reason, kind, name, url = ordered[0]
        overrides[(game_id, network_id)] = CrewOverride(
            cfbd_game_id=game_id,
            network_id=network_id,
            people=tuple((row[2], row[3]) for row in ordered),
            reason=reason,
            source_kind=kind,
            source_name=name,
            source_url=url,
        )
    return overrides
