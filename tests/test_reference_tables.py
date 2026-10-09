"""Guard over every public data/reference/*.csv table (D-05/D-06, T-03-39):
only known files, an exact header match to each table's own column
constant, a working loader, no game-level column name in any header, and
every person_overrides.csv person_id resolving to a real people.csv row.
crew_overrides.csv is the one documented exception to D-05/D-06 (04.3 D-01):
its rows carry hand-confirmed booths, each cited to a public source_url.

Runs against the real data/reference/ folder (not a synthetic fixture) --
this is the guard over what actually gets published.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from booth_review.build.bowls import BOWL_COLUMNS, load_bowls
from booth_review.build.crew_overrides import CREW_OVERRIDE_COLUMNS, load_crew_overrides
from booth_review.build.rivalries import RIVALRY_COLUMNS, load_rivalries
from booth_review.build.venues import VENUE_LOCATION_COLUMNS, load_venue_locations
from booth_review.contract.models import crew_source_url_problem
from booth_review.flags.era import ERA_COLUMNS, load_eras
from booth_review.flags.events import EVENT_COLUMNS, load_event_flags
from booth_review.people.registry import (
    PEOPLE_COLUMNS,
    PERSON_OVERRIDE_COLUMNS,
    REVIEWED_COLUMNS,
    load_people,
    load_person_overrides,
    load_reviewed,
)
from booth_review.reference import read_reference_csv, read_reference_csv_numbered
from booth_review.resolve.networks import (
    NETWORK_COLUMNS,
    NETWORK_RARITY_COLUMNS,
    PRIMARY_OVERRIDE_COLUMNS,
    load_network_rarity,
    load_networks,
    load_primary_overrides,
)
from booth_review.resolve.overrides import GAME_OVERRIDE_COLUMNS, load_game_overrides
from booth_review.resolve.teams import TEAM_CROSSWALK_COLUMNS, load_team_crosswalk

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = REPO_ROOT / "data" / "reference"

# The Plan 09 combined-figures table's column constant and loader don't exist
# yet in this wave's ordering (03-09 runs after this plan); imported lazily
# so this module still loads, and its own header/loader check is skipped
# below -- but only while the module is genuinely absent, never when
# combined_figures.csv itself already exists on disk.
try:
    from booth_review.build.combined import COMBINED_COLUMNS as _COMBINED_COLUMNS
    from booth_review.build.combined import load_combined_figures as _load_combined_figures
except ImportError:
    _COMBINED_COLUMNS = None
    _load_combined_figures = None

Loader = Callable[[Path], object]

KNOWN_TABLES: dict[str, tuple[tuple[str, ...] | None, Loader | None]] = {
    "measurement_eras.csv": (ERA_COLUMNS, load_eras),
    "event_flags.csv": (EVENT_COLUMNS, load_event_flags),
    "team_crosswalk.csv": (TEAM_CROSSWALK_COLUMNS, load_team_crosswalk),
    "game_overrides.csv": (GAME_OVERRIDE_COLUMNS, load_game_overrides),
    "people.csv": (PEOPLE_COLUMNS, load_people),
    "people_reviewed.csv": (REVIEWED_COLUMNS, load_reviewed),
    "person_overrides.csv": (PERSON_OVERRIDE_COLUMNS, load_person_overrides),
    "networks.csv": (NETWORK_COLUMNS, load_networks),
    "network_rarity.csv": (NETWORK_RARITY_COLUMNS, load_network_rarity),
    "primary_network_overrides.csv": (PRIMARY_OVERRIDE_COLUMNS, load_primary_overrides),
    "combined_figures.csv": (_COMBINED_COLUMNS, _load_combined_figures),
    "bowls.csv": (BOWL_COLUMNS, load_bowls),
    "rivalries.csv": (RIVALRY_COLUMNS, load_rivalries),
    "crew_overrides.csv": (CREW_OVERRIDE_COLUMNS, load_crew_overrides),
    "venue_locations.csv": (VENUE_LOCATION_COLUMNS, load_venue_locations),
}

# 04.3 D-01: the one documented exception to Phase 3 D-05/D-06. Each row records a
# main-feed booth that a cited public source (network press release, school game
# notes, reputable outlet) already publishes; source_url is mandatory. No other
# table may record who called which game.
_D05_EXCEPTIONS: frozenset[str] = frozenset({"crew_overrides.csv"})

# Column names that would signal a game-level row (who called which game, a
# figure, a matchup) leaking into a names-only or pointer-only public table
# (D-05/D-06).
_FORBIDDEN_COLUMNS: frozenset[str] = frozenset(
    {
        "crew",
        "crew_raw",
        "crew_names",
        "viewers",
        "value",
        "headline_value",
        "matchup",
        "away_raw",
        "home_raw",
        "telecast_id",
        "date_et",
        "kickoff",
    }
)


def _header(path: Path) -> Sequence[str]:
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    return first_line.split(",")


def test_only_known_tables() -> None:
    csv_files = {p.name for p in REFERENCE_DIR.glob("*.csv")}
    unknown = csv_files - set(KNOWN_TABLES)
    assert not unknown, f"unrecognized data/reference file(s): {sorted(unknown)}"


@pytest.mark.parametrize("name", sorted(KNOWN_TABLES))
def test_headers_and_loaders(name: str) -> None:
    path = REFERENCE_DIR / name
    columns, loader = KNOWN_TABLES[name]

    if columns is None or loader is None:
        if path.is_file():
            pytest.fail(f"{name}: file exists but its column constant/loader is not importable")
        pytest.skip(f"{name}: not yet present in this wave's ordering")

    if not path.is_file():
        pytest.skip(f"{name}: file not yet present")

    assert tuple(_header(path)) == columns
    loader(REFERENCE_DIR)  # must not raise


# A row keyed to one game or telecast that also names a person, a role, or a
# crew slot records who called which game, even with no forbidden column name.
# (person_overrides.csv keys on a 506 row pointer, not a game: D-06 allows it.)
_GAME_KEY_COLUMNS: frozenset[str] = frozenset({"cfbd_game_id", "rr_telecast_id", "telecast_id"})
_CREW_COLUMNS: frozenset[str] = frozenset({"person_id", "role", "crew_position"})


def _game_level_columns(header: set[str]) -> set[str]:
    found = set(_FORBIDDEN_COLUMNS & header)
    if header & _GAME_KEY_COLUMNS and header & _CREW_COLUMNS:
        found |= header & (_GAME_KEY_COLUMNS | _CREW_COLUMNS)
    return found


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ({"cfbd_game_id", "official_name"}, set()),
        ({"season", "pointer", "position", "person_id"}, set()),
        ({"cfbd_game_id", "person_id"}, {"cfbd_game_id", "person_id"}),
        ({"rr_telecast_id", "role"}, {"rr_telecast_id", "role"}),
        ({"network_id", "crew_raw"}, {"crew_raw"}),
    ],
)
def test_game_level_columns_detects_who_called_which_game(
    header: set[str], expected: set[str]
) -> None:
    assert _game_level_columns(header) == expected


def test_no_game_level_columns() -> None:
    for path in sorted(REFERENCE_DIR.glob("*.csv")):
        if path.name in _D05_EXCEPTIONS:
            continue
        overlap = _game_level_columns(set(_header(path)))
        assert not overlap, f"{path.name}: game-level column(s) found: {sorted(overlap)}"


def test_person_override_ids_exist() -> None:
    people_rows = read_reference_csv(REFERENCE_DIR / "people.csv", PEOPLE_COLUMNS)
    people_ids = {row["person_id"] for row in people_rows}

    override_rows = read_reference_csv(
        REFERENCE_DIR / "person_overrides.csv", PERSON_OVERRIDE_COLUMNS
    )
    for row in override_rows:
        assert row["person_id"] in people_ids, f"unknown person_id in person_overrides.csv: {row!r}"


def test_d05_exceptions_are_exactly_the_tables_with_game_level_columns() -> None:
    # Every exception must still earn it (a stale entry would silently exempt
    # a table), and no other table may carry game-level columns.
    with_game_level = {
        path.name for path in REFERENCE_DIR.glob("*.csv") if _game_level_columns(set(_header(path)))
    }
    assert with_game_level == _D05_EXCEPTIONS


def test_crew_override_rows_have_source_url() -> None:
    rows = read_reference_csv_numbered(REFERENCE_DIR / "crew_overrides.csv", CREW_OVERRIDE_COLUMNS)
    for line_no, row in rows:
        problem = crew_source_url_problem(row["source_url"])
        assert problem is None, f"crew_overrides.csv line {line_no}: source_url {problem}"


def test_crew_override_person_ids_exist() -> None:
    people_rows = read_reference_csv(REFERENCE_DIR / "people.csv", PEOPLE_COLUMNS)
    people_ids = {row["person_id"] for row in people_rows}
    rows = read_reference_csv_numbered(REFERENCE_DIR / "crew_overrides.csv", CREW_OVERRIDE_COLUMNS)
    for line_no, row in rows:
        assert row["person_id"] in people_ids, (
            f"crew_overrides.csv line {line_no}: unknown person_id"
        )


def test_rivalry_teams_use_canonical_crosswalk_names() -> None:
    rivalries = load_rivalries(REFERENCE_DIR)
    assert rivalries
    crosswalk = read_reference_csv(REFERENCE_DIR / "team_crosswalk.csv", TEAM_CROSSWALK_COLUMNS)
    non_canonical = {row["variant"] for row in crosswalk if row["variant"] != row["canonical"]}
    for rivalry in rivalries:
        assert rivalry.team_a not in non_canonical, f"{rivalry.rivalry_id}: team_a is a variant"
        assert rivalry.team_b not in non_canonical, f"{rivalry.rivalry_id}: team_b is a variant"


# -- not accidentally gitignored (same pattern as tests/test_gitignore.py) ---------------------


def _git_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    empty_config = tmp_path / "empty-gitconfig"
    empty_config.write_text("", encoding="utf-8")
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = str(empty_config)
    return env


def test_reference_not_ignored(tmp_path: Path) -> None:
    env = _git_env(tmp_path)
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", "data/reference/people.csv"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, "expected data/reference/people.csv to not be ignored"
