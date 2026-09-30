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

import copy
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from booth_review.contract.models import crew_source_url_problem
from booth_review.errors import CrewOverrideError, ReferenceTableError
from booth_review.people.registry import PeopleRegistry
from booth_review.reference import read_reference_csv_numbered

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


@dataclass(frozen=True)
class CrewOverride:
    cfbd_game_id: int
    network_id: str
    people: tuple[tuple[str, str], ...]  # (person_id, role), ordered by crew_position
    reason: str
    source_kind: str
    source_name: str
    source_url: str


def _parse_ascii_int(cell: str) -> int | None:
    """Plain ASCII digits only: int() alone would also take "1_000", signs,
    surrounding whitespace, and non-ASCII (Unicode) digits."""
    if not (cell.isascii() and cell.isdecimal()):
        return None
    return int(cell)


def load_crew_overrides(reference_dir: Path) -> dict[tuple[int, str], CrewOverride]:
    """Read crew_overrides.csv (not required) into (game id, network id) -> CrewOverride."""
    path = reference_dir / "crew_overrides.csv"
    raw_rows = read_reference_csv_numbered(path, CREW_OVERRIDE_COLUMNS, required=False)

    def fail(line_no: int, what: str) -> ReferenceTableError:
        return ReferenceTableError(f"{path.name}: line {line_no}: {what}")

    # key -> list of (line_no, position, person_id, role, reason, kind, name, url)
    grouped: dict[tuple[int, str], list[tuple[int, int, str, str, str, str, str, str]]] = {}
    for line_no, raw in raw_rows:
        game_id = _parse_ascii_int(raw["cfbd_game_id"])
        if game_id is None:
            raise fail(line_no, "cfbd_game_id must be an integer")
        # No sign is accepted, so a position is never negative (and
        # read_reference_csv already rejects a cell starting with "-").
        position = _parse_ascii_int(raw["crew_position"])
        if position is None:
            raise fail(line_no, "crew_position must be an integer")
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
        url_problem = crew_source_url_problem(url)
        if url_problem is not None:
            raise fail(line_no, f"source_url {url_problem}")
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
        for expected, row in enumerate(ordered):
            if row[1] != expected:
                # Cite the first row that breaks the 0, 1, 2, ... run.
                raise fail(row[0], "crew_position must run contiguously from 0")
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


@dataclass(frozen=True)
class CrewOverrideResult:
    telecasts: pl.DataFrame
    telecast_people: pl.DataFrame
    season_counts: dict[int, dict[str, int]]
    statuses: dict[str, str]  # telecast_id -> patched | redundant | differs | correction
    counts: dict[str, int]  # applied, patched, redundant, differs, corrections, rows


def apply_crew_overrides(
    telecasts: pl.DataFrame,
    telecast_people: pl.DataFrame,
    overrides: Mapping[tuple[int, str], CrewOverride],
    registry: PeopleRegistry,
    season_counts: Mapping[int, Mapping[str, int]],
) -> CrewOverrideResult:
    """Replace the main-feed crew of each override telecast with the override's
    full booth (D-08); the override always wins (D-09). Alt and Spanish rows
    are kept. Failures are count-only (D-04). Inputs are not mutated.

    Status follows the PRE-override 506 match. `patched`: 506 listed no main
    crew; the only status that sets `crew_patched` and flips `crew_matched`.
    `redundant`: 506 lists the same people; the 506 rows and attribution are
    kept untouched. `correction`/`differs`: 506 lists another crew; the
    override's booth replaces it. Every status but `redundant` carries the
    `crew_source_url`/`crew_source_label` pair, since the shown crew is the
    override's. So `crew_matched & ~crew_patched` is exactly the 506 match.
    """
    new_counts = {season: dict(counts) for season, counts in copy.deepcopy(season_counts).items()}
    counts = dict.fromkeys(("applied", "patched", "redundant", "differs", "corrections", "rows"), 0)
    if not overrides:
        return CrewOverrideResult(telecasts, telecast_people, new_counts, {}, counts)

    unknown = sum(
        1
        for override in overrides.values()
        for person_id, _ in override.people
        if person_id not in registry.persons
    )
    if unknown:
        raise CrewOverrideError(f"crew_overrides.csv: {unknown} row(s) name an unknown person_id")

    mains = telecasts.filter((pl.col("feed_type") == "main") & pl.col("plotted").fill_null(False))
    by_key = {
        (row["game_id"], row["network_id"]): row
        for row in mains.select(
            "telecast_id", "game_id", "network_id", "season", "rated", "crew_matched"
        )
        .join(telecasts.select("telecast_id", "rr_telecast_ids"), on="telecast_id")
        .iter_rows(named=True)
    }
    unplotted = sum(
        len(override.people) for key, override in overrides.items() if key not in by_key
    )
    if unplotted:
        raise CrewOverrideError(
            f"crew_overrides.csv: {unplotted} row(s) name a telecast the build does not plot"
        )

    existing_main: dict[str, set[str]] = {}
    for row in telecast_people.filter(pl.col("feed_type") == "main").iter_rows(named=True):
        existing_main.setdefault(row["telecast_id"], set()).add(row["person_id"])

    statuses: dict[str, str] = {}
    new_rows: list[dict[str, object]] = []
    for key, override in overrides.items():
        target = by_key[key]
        telecast_id = target["telecast_id"]
        current = existing_main.get(telecast_id, set())
        wanted = {person_id for person_id, _ in override.people}
        if not target["crew_matched"]:
            status = "patched"
            if target["rated"]:
                bucket = new_counts.setdefault(target["season"], {})
                bucket["rated_with_crew"] = bucket.get("rated_with_crew", 0) + 1
                bucket["records_with_crew"] = bucket.get("records_with_crew", 0) + len(
                    target["rr_telecast_ids"] or []
                )
        elif current == wanted:
            status = "redundant"
        else:
            status = "correction" if override.reason == "correction" else "differs"
        statuses[telecast_id] = status
        if status == "redundant":
            continue  # 506 already lists this booth; keep its rows and attribution.
        for position, (person_id, role) in enumerate(override.people):
            new_rows.append(
                {
                    "telecast_id": telecast_id,
                    "person_id": person_id,
                    "role": role,
                    "feed_type": "main",
                    "crew_position": position,
                    "s506_pointer": None,
                    "source": CREW_OVERRIDE_SOURCE,
                }
            )

    patched_ids = [tid for tid, status in statuses.items() if status == "patched"]
    sourced_ids = [tid for tid, status in statuses.items() if status != "redundant"]
    kept = telecast_people.filter(
        ~(pl.col("telecast_id").is_in(sourced_ids) & (pl.col("feed_type") == "main"))
    )
    added = pl.DataFrame(new_rows, schema=telecast_people.schema)
    people_out = pl.concat([kept, added]).sort(["telecast_id", "person_id", "feed_type"])

    frame = telecasts
    if "crew_patched" not in frame.columns:
        frame = frame.with_columns(pl.lit(False).alias("crew_patched"))
    for column in ("crew_source_url", "crew_source_label"):
        if column not in frame.columns:
            frame = frame.with_columns(pl.lit(None, dtype=pl.Utf8).alias(column))
    url_by_id = {by_key[key]["telecast_id"]: o.source_url for key, o in overrides.items()}
    label_by_id = {by_key[key]["telecast_id"]: o.source_name for key, o in overrides.items()}
    patched = pl.col("telecast_id").is_in(patched_ids)
    sourced = pl.col("telecast_id").is_in(sourced_ids)
    telecasts_out = frame.with_columns(
        pl.when(patched).then(True).otherwise(pl.col("crew_matched")).alias("crew_matched"),
        pl.when(patched).then(True).otherwise(pl.col("crew_patched")).alias("crew_patched"),
        pl.when(sourced)
        .then(pl.col("telecast_id").replace_strict(url_by_id, default=None, return_dtype=pl.Utf8))
        .otherwise(pl.col("crew_source_url"))
        .alias("crew_source_url"),
        pl.when(sourced)
        .then(pl.col("telecast_id").replace_strict(label_by_id, default=None, return_dtype=pl.Utf8))
        .otherwise(pl.col("crew_source_label"))
        .alias("crew_source_label"),
    )

    counts["applied"] = len(statuses)
    counts["patched"] = sum(1 for v in statuses.values() if v == "patched")
    counts["redundant"] = sum(1 for v in statuses.values() if v == "redundant")
    counts["differs"] = sum(1 for v in statuses.values() if v == "differs")
    counts["corrections"] = sum(1 for v in statuses.values() if v == "correction")
    counts["rows"] = len(new_rows)
    return CrewOverrideResult(telecasts_out, people_out, new_counts, statuses, counts)


REVIEW_CREW_GAPS_COLUMNS = (
    "cfbd_game_id",
    "network_id",
    "season",
    "date_et",
    "game_type",
    "playoff_round",
    "away_team",
    "home_team",
    "gap_kind",
    "s506_pointer",
    "other_feed_crew",
    "crew_network_mismatch",
    "override_status",
)

_HAS_506_CREW_STATUSES = frozenset({"redundant", "differs", "correction"})


def crew_gap_rows(
    telecasts: pl.DataFrame,
    games: pl.DataFrame,
    telecast_people: pl.DataFrame,
    statuses: Mapping[str, str],
    unmatched_506_dates: Collection[str],
) -> list[dict[str, object]]:
    """One row per plotted main telecast with no 506 main crew, classified, plus
    one has-506-crew row per redundant/differs/correction override (D-05, D-09).

    Pass the PRE-override frames so the gap set is "no 506 main crew".
    Vault-only (interim/review_crew_overrides.csv); never logged or published.
    Callers and tests never hard-code a gap count.
    """
    non_main = set(telecast_people.filter(pl.col("feed_type") != "main")["telecast_id"].to_list())
    game_by_id = {row["game_id"]: row for row in games.iter_rows(named=True)}
    rows: list[dict[str, object]] = []
    plotted_main = telecasts.filter((pl.col("feed_type") == "main") & pl.col("plotted"))
    for tel in plotted_main.iter_rows(named=True):
        telecast_id = tel["telecast_id"]
        status = statuses.get(telecast_id)
        if tel["crew_matched"]:
            if status not in _HAS_506_CREW_STATUSES:
                continue
            gap_kind = "has-506-crew"
        elif tel["s506_pointer"] is not None:
            gap_kind = "no-506-crew"
        elif telecast_id in non_main:
            gap_kind = "main-crew-missing"
        elif tel["date_et"].isoformat() in unmatched_506_dates:
            gap_kind = "join-miss-suspect"
        else:
            gap_kind = "no-506-listing"
        game = game_by_id.get(tel["game_id"], {})
        rows.append(
            {
                "cfbd_game_id": tel["game_id"],
                "network_id": tel["network_id"],
                "season": tel["season"],
                "date_et": tel["date_et"],
                "game_type": game.get("game_type"),
                "playoff_round": game.get("playoff_round"),
                "away_team": game.get("away_team"),
                "home_team": game.get("home_team"),
                "gap_kind": gap_kind,
                "s506_pointer": tel["s506_pointer"],
                "other_feed_crew": telecast_id in non_main,
                "crew_network_mismatch": tel["crew_network_mismatch"],
                "override_status": status if status is not None else "missing",
            }
        )
    rows.sort(key=lambda r: (r["season"], r["date_et"], r["cfbd_game_id"], r["network_id"]))
    return rows
