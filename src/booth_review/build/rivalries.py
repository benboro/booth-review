"""Curated named FBS rivalries loader (D-12/D-13).

data/reference/rivalries.csv holds well-known named rivalries: a stable id,
the current name, two CFBD canonical team names, and optional season limits.
The build counts only the first regular-season meeting of the pair in a
season, after skipping the conference title games CFBD's notes mark (2022 on;
see build.named_games), so a title game is never the rivalry game. For earlier
seasons a later rematch is demoted. Errors cite file and line only, never a name.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from booth_review.errors import ReferenceTableError
from booth_review.reference import SLUG_PATTERN, read_reference_csv_numbered

RIVALRY_COLUMNS = ("rivalry_id", "name", "team_a", "team_b", "season_from", "season_to")

RESERVED_RIVALRY_IDS = frozenset(
    {"cfp-national-championship", "cfp-semifinal", "cfp-quarterfinal", "cfp-first-round"}
)


@dataclass(frozen=True)
class Rivalry:
    rivalry_id: str
    name: str
    team_a: str
    team_b: str
    season_from: int | None
    season_to: int | None


def load_rivalries(reference_dir: Path) -> list[Rivalry]:
    """Read rivalries.csv (not required) into rows in file order."""
    path = reference_dir / "rivalries.csv"
    raw_rows = read_reference_csv_numbered(path, RIVALRY_COLUMNS, required=False)

    def fail(line_no: int, what: str) -> ReferenceTableError:
        return ReferenceTableError(f"{path.name}: line {line_no}: {what}")

    def season(line_no: int, column: str, text: str) -> int | None:
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            raise fail(line_no, f"{column} must be an integer") from None

    rivalries: list[Rivalry] = []
    ids: set[str] = set()
    names: set[str] = set()
    pairs: set[frozenset[str]] = set()
    for line_no, raw in raw_rows:
        rivalry_id = raw["rivalry_id"]
        if not SLUG_PATTERN.fullmatch(rivalry_id):
            raise fail(line_no, "rivalry_id must be lowercase ASCII words joined by single hyphens")
        if rivalry_id in RESERVED_RIVALRY_IDS:
            raise fail(line_no, "rivalry_id is reserved for a CFP round")
        if rivalry_id in ids:
            raise fail(line_no, "duplicate rivalry_id")
        name, team_a, team_b = raw["name"], raw["team_a"], raw["team_b"]
        if not name or not team_a or not team_b:
            raise fail(line_no, "name, team_a and team_b must be set")
        if "<" in name or ">" in name:
            raise fail(line_no, "name must not contain < or >")
        if name.casefold() in names:
            raise fail(line_no, "duplicate name")
        if team_a == team_b:
            raise fail(line_no, "team_a and team_b must differ")
        pair = frozenset((team_a, team_b))
        if pair in pairs:
            raise fail(line_no, "team pair repeats an earlier row")
        season_from = season(line_no, "season_from", raw["season_from"])
        season_to = season(line_no, "season_to", raw["season_to"])
        if season_from is not None and season_to is not None and season_from > season_to:
            raise fail(line_no, "season_from is after season_to")
        ids.add(rivalry_id)
        names.add(name.casefold())
        pairs.add(pair)
        rivalries.append(Rivalry(rivalry_id, name, team_a, team_b, season_from, season_to))
    return rivalries
