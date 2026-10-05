"""Public bowl-name crosswalk loader (D-17/D-18).

data/reference/bowls.csv is keyed by CFBD game id and holds reviewed display
names only: the official name for that season (sponsor included) and the core
bowl name. It never holds CFBD notes text. A row with empty names and
at_bowl=true means the game was at a bowl whose name is explicitly unknown
(D-18); at_bowl=false rows (CFP first round, national championship) must
carry no names. Errors cite file and line (and the id scalar for id errors),
never a name.

The franchise column is a stable kebab slug grouping a bowl across sponsor
changes and renames (D-07); it is set exactly when core_name is set.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from booth_review.errors import ReferenceTableError
from booth_review.reference import SLUG_PATTERN, read_reference_csv_numbered

BOWL_COLUMNS = ("cfbd_game_id", "official_name", "core_name", "at_bowl", "franchise")


@dataclass(frozen=True)
class BowlEntry:
    official_name: str | None
    core_name: str | None
    at_bowl: bool
    franchise: str | None = None


def load_bowls(reference_dir: Path) -> dict[int, BowlEntry]:
    """Read bowls.csv (not required) into cfbd_game_id -> BowlEntry."""
    path = reference_dir / "bowls.csv"
    raw_rows = read_reference_csv_numbered(path, BOWL_COLUMNS, required=False)

    def fail(line_no: int, what: str) -> ReferenceTableError:
        return ReferenceTableError(f"{path.name}: line {line_no}: {what}")

    entries: dict[int, BowlEntry] = {}
    for line_no, raw in raw_rows:
        try:
            game_id = int(raw["cfbd_game_id"])
        except ValueError:
            raise fail(line_no, f"invalid cfbd_game_id {raw['cfbd_game_id']!r}") from None
        if game_id in entries:
            raise fail(line_no, f"duplicate cfbd_game_id {game_id}")

        at_bowl_text = raw["at_bowl"]
        if at_bowl_text not in ("true", "false"):
            raise fail(line_no, "at_bowl must be true or false")
        at_bowl = at_bowl_text == "true"

        official = raw["official_name"] or None
        core = raw["core_name"] or None
        if not at_bowl and (official is not None or core is not None):
            raise fail(line_no, "names must be empty when at_bowl is false")
        if (official is None) != (core is None):
            raise fail(line_no, "official_name and core_name must be set together")
        if official is not None and core is not None and core not in official:
            raise fail(line_no, "core_name is not part of official_name")
        franchise = raw["franchise"] or None
        if core is not None and franchise is None:
            raise fail(line_no, "franchise must be set when core_name is set")
        if core is None and franchise is not None:
            raise fail(line_no, "franchise must be empty when core_name is empty")
        if franchise is not None and not SLUG_PATTERN.fullmatch(franchise):
            raise fail(line_no, "franchise must be lowercase ASCII words joined by single hyphens")
        entries[game_id] = BowlEntry(official, core, at_bowl, franchise)
    return entries
