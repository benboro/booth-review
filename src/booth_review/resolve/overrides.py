"""Pointer-only game-match override table (D-06): every column is a pointer,
an action, a target CFBD game id, and a fixed-vocabulary reason code --
never a crew, a figure, or matchup text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from booth_review.errors import ReferenceTableError
from booth_review.reference import read_reference_csv_numbered
from booth_review.sources.ratingsref.parser import RRRecord
from booth_review.sources.sports506.parser import Listing506

GAME_OVERRIDE_COLUMNS = ("source", "season", "pointer", "action", "cfbd_game_id", "reason")

REASON_CODES: frozenset[str] = frozenset(
    {
        "date-shift",
        "name-variant",
        "not-fbs",
        "not-a-game",
        "duplicate-listing",
        "wrong-auto-match",
        "other",
    }
)

OverrideAction = Literal["match", "exclude"]
OverrideSource = Literal["sports506", "ratingsref"]

_SOURCES: frozenset[str] = frozenset({"sports506", "ratingsref"})
_ACTIONS: frozenset[str] = frozenset({"match", "exclude"})

# sports506: "<week_label>:<source_row_index>" (week_label is 0-16 or "B").
_SPORTS506_POINTER_RE = re.compile(r"^([0-9]{1,2}|B):[0-9]+$")
# ratingsref: the RR telecast id/slug.
_RATINGSREF_POINTER_RE = re.compile(r"^cfb-[a-z0-9-]+$")


@dataclass(frozen=True)
class GameOverride:
    source: OverrideSource
    season: int
    pointer: str
    action: OverrideAction
    cfbd_game_id: int | None
    reason: str


def pointer_for_listing(listing: Listing506) -> str:
    """ "<week_label>:<source_row_index>", the sports506 pointer format."""
    return f"{listing.week_label}:{listing.source_row_index}"


def pointer_for_record(record: RRRecord) -> str:
    """The RR telecast id, the ratingsref pointer format."""
    return record.telecast.id


def _validate_pointer(source: str, pointer: str, *, path_name: str, line_no: int) -> None:
    pattern = _SPORTS506_POINTER_RE if source == "sports506" else _RATINGSREF_POINTER_RE
    if not pattern.match(pointer):
        raise ReferenceTableError(
            f"{path_name}: line {line_no}: malformed pointer {pointer!r} for source {source!r}"
        )


def load_game_overrides(reference_dir: Path) -> dict[tuple[str, int, str], GameOverride]:
    """Read game_overrides.csv (not required). Raises ReferenceTableError on
    a reason outside REASON_CODES, a malformed pointer, a "match" row with no
    cfbd_game_id, or a duplicate (source, season, pointer) key.
    """
    path = reference_dir / "game_overrides.csv"
    raw_rows = read_reference_csv_numbered(path, GAME_OVERRIDE_COLUMNS, required=False)

    overrides: dict[tuple[str, int, str], GameOverride] = {}
    for line_no, raw in raw_rows:
        source = raw["source"]
        if source not in _SOURCES:
            raise ReferenceTableError(f"{path.name}: line {line_no}: invalid source {source!r}")
        try:
            season = int(raw["season"])
        except ValueError:
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: invalid season {raw['season']!r}"
            ) from None

        pointer = raw["pointer"]
        _validate_pointer(source, pointer, path_name=path.name, line_no=line_no)

        action = raw["action"]
        if action not in _ACTIONS:
            raise ReferenceTableError(f"{path.name}: line {line_no}: invalid action {action!r}")

        reason = raw["reason"]
        if reason not in REASON_CODES:
            raise ReferenceTableError(f"{path.name}: line {line_no}: invalid reason {reason!r}")

        cfbd_game_id: int | None = None
        if raw["cfbd_game_id"]:
            try:
                cfbd_game_id = int(raw["cfbd_game_id"])
            except ValueError:
                raise ReferenceTableError(
                    f"{path.name}: line {line_no}: invalid cfbd_game_id {raw['cfbd_game_id']!r}"
                ) from None
        if action == "match" and cfbd_game_id is None:
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: a match action requires cfbd_game_id"
            )

        key = (source, season, pointer)
        if key in overrides:
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: duplicate override for {key!r}"
            )

        overrides[key] = GameOverride(
            source=source,  # type: ignore[arg-type]
            season=season,
            pointer=pointer,
            action=action,  # type: ignore[arg-type]
            cfbd_game_id=cfbd_game_id,
            reason=reason,
        )
    return overrides
