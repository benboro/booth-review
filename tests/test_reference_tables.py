"""Guard over every public data/reference/*.csv table (D-05/D-06, T-03-39):
only known files, an exact header match to each table's own column
constant, a working loader, no game-level column name in any header, and
every person_overrides.csv person_id resolving to a real people.csv row.

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
from booth_review.reference import read_reference_csv
from booth_review.resolve.networks import (
    NETWORK_COLUMNS,
    PRIMARY_OVERRIDE_COLUMNS,
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
    "primary_network_overrides.csv": (PRIMARY_OVERRIDE_COLUMNS, load_primary_overrides),
    "combined_figures.csv": (_COMBINED_COLUMNS, _load_combined_figures),
    "bowls.csv": (BOWL_COLUMNS, load_bowls),
}

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


def test_no_game_level_columns() -> None:
    for path in sorted(REFERENCE_DIR.glob("*.csv")):
        header = set(_header(path))
        overlap = _FORBIDDEN_COLUMNS & header
        assert not overlap, f"{path.name}: game-level column(s) found: {sorted(overlap)}"


def test_person_override_ids_exist() -> None:
    people_rows = read_reference_csv(REFERENCE_DIR / "people.csv", PEOPLE_COLUMNS)
    people_ids = {row["person_id"] for row in people_rows}

    override_rows = read_reference_csv(
        REFERENCE_DIR / "person_overrides.csv", PERSON_OVERRIDE_COLUMNS
    )
    for row in override_rows:
        assert row["person_id"] in people_ids, f"unknown person_id in person_overrides.csv: {row!r}"


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
