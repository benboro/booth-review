"""The SMW transcription row schema and its unit and exclusion rules (04.19 D-03, D-21).

Every printed row is accepted as printed; this module, not the transcriber,
converts units and decides which rows carry a usable figure. Error messages
cite the file name, line numbers and counts only, never a cell value.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path

from booth_review.errors import ReferenceTableError
from booth_review.reference import read_reference_csv_numbered
from booth_review.sources.second_rows import RowKind, SecondSourceRow
from booth_review.sources.smw.chart_order import ChartOrderEntry

PASS_COLUMNS = (
    "chart_file",
    "row",
    "weekday",
    "date",
    "kickoff",
    "away",
    "home",
    "network",
    "rating",
    "viewers",
    "note",
)
ROWS_COLUMNS = (*PASS_COLUMNS, "superseded_by")

_VIEWERS_RE = re.compile(r"^(\d+(?:\.\d+)?)([MK])$")
_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})$")
_CHART_FILE_RE = re.compile(r"^[A-Za-z0-9._-]+\.png$")
_SPACED_PLUS_RE = re.compile(r"\s\+\s")
# 2021 postseason charts print the game or bowl name before the away team in one
# GAME cell ("<name>: <team>"); the transcription keeps it as printed.
_GAME_NAME_PREFIX_RE = re.compile(r"^[^:/]+:\s+(?=\S)")
# A one-cell game shape: "A / B", "A @ B", "A at B", "A vs B".
_GAME_SHAPE_RE = re.compile(r"/|\s(?:@|at|vs\.?)\s", re.IGNORECASE)


def parse_viewers(printed: str) -> int | None:
    """5.83M -> 5830000, 904K -> 904000; anything else (n/a, bare numbers) -> None."""
    text = printed.strip().upper().replace(",", "")
    match = _VIEWERS_RE.match(text)
    if match is None:
        return None
    scale = 1_000_000 if match.group(2) == "M" else 1_000
    return round(float(match.group(1)) * scale)


def parse_chart_date(printed: str, season: int) -> date | None:
    """Charts print M/D; months 1-7 belong to season + 1, months 8-12 to season."""
    match = _DATE_RE.match(printed.strip())
    if match is None:
        return None
    month, day = int(match.group(1)), int(match.group(2))
    year = season + 1 if month <= 7 else season
    try:
        return date(year, month, day)
    except ValueError:
        return None


def away_team_text(printed: str) -> str:
    """The away cell without a leading "<game or bowl name>: " segment, for team
    resolution; a cell with no such segment comes back unchanged."""
    return _GAME_NAME_PREFIX_RE.sub("", printed, count=1)


def _is_regional(row: Mapping[str, str]) -> bool:
    away, home, note = row.get("away", ""), row.get("home", ""), row.get("note", "")
    if any("regional action" in cell.lower() for cell in (away, home, note)):
        return True
    # The transcription brief marks a cell that stacks several games (a BTN window
    # printed without "or") with the note "multi-game cell".
    if "multi-game cell" in note.lower():
        return True
    return any(" or " in cell.lower() or cell.count("/") > 1 for cell in (away, home))


def _is_non_game(row: Mapping[str, str]) -> bool:
    """A broadcast label spanning the row (a studio show, an awards telecast): text in
    away, an empty home cell, and no game shape in the text."""
    away, home = row.get("away", "").strip(), row.get("home", "").strip()
    return home == "" and away != "" and _GAME_SHAPE_RE.search(away) is None


def classify_row(
    row: Mapping[str, str], *, parse: Callable[[str], int | None] = parse_viewers
) -> RowKind:
    """Label a row; precedence: simulcast, multi_feed, regional, non_game, non_nielsen,
    no_figure, unknown_suffix, figure. `parse` is the source's own unit rule (SMW's
    M/K suffixes by default; TVRG and AA pass theirs)."""
    network = row.get("network", "")
    # A simulcast prints two networks joined by "&", by a comma ("NET1, NET2") or by a
    # spaced "+" ("NET1 + NET2"); an unspaced "+" is part of a name (ESPN+, Bally+ Ariz).
    if "&" in network or "," in network or _SPACED_PLUS_RE.search(network):
        return "simulcast"
    if "MEGA" in network.upper().split():
        return "multi_feed"
    if _is_regional(row):
        return "regional"
    if _is_non_game(row):
        return "non_game"
    if "not nielsen" in row.get("note", "").lower():
        return "non_nielsen"
    viewers = row.get("viewers", "").strip()
    # A cell with no digit at all ("n/a", "not disclosed", blank) states that the
    # chart has no figure; only a number with an unknown suffix goes to review.
    if not any(ch.isdigit() for ch in viewers):
        return "no_figure"
    if parse(viewers) is None:
        return "unknown_suffix"
    return "figure"


def _load(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    def fail(line_no: int, what: str) -> ReferenceTableError:
        return ReferenceTableError(f"{path.name}: line {line_no}: {what}")

    numbered = read_reference_csv_numbered(path, columns, required=True)
    seen: dict[tuple[str, int], int] = {}
    out: list[dict[str, str]] = []
    for line_no, raw in numbered:
        if not _CHART_FILE_RE.match(raw["chart_file"]):
            raise fail(line_no, "chart_file is not a plain .png name")
        cell = raw["row"]
        if not (cell.isascii() and cell.isdecimal()) or int(cell) <= 0:
            raise fail(line_no, "row must be a positive integer")
        key = (raw["chart_file"], int(cell))
        if key in seen:
            raise fail(line_no, "duplicate (chart_file, row)")
        seen[key] = line_no
        out.append(raw)
    if "superseded_by" in columns:
        for line_no, raw in numbered:
            target = raw["superseded_by"]
            if not target:
                continue
            chart_file, _, row_text = target.rpartition(":")
            if (
                not (row_text.isascii() and row_text.isdecimal())
                or (
                    chart_file,
                    int(row_text),
                )
                not in seen
            ):
                raise fail(line_no, "superseded_by must name an existing row")
    return out


def load_pass_csv(path: Path) -> list[dict[str, str]]:
    """Read one transcription pass file (PASS_COLUMNS), strictly."""
    return _load(path, PASS_COLUMNS)


def load_rows_csv(path: Path) -> list[dict[str, str]]:
    """Read the merged rows.csv (ROWS_COLUMNS), strictly."""
    return _load(path, ROWS_COLUMNS)


def smw_second_rows(
    rows: Sequence[Mapping[str, str]],
    chart_order: Mapping[str, ChartOrderEntry],
    *,
    season: int,
    source_url: str,
) -> list[SecondSourceRow]:
    """One SecondSourceRow per rows.csv row; viewers only for kind "figure"."""
    missing = {row["chart_file"] for row in rows} - set(chart_order)
    if missing:
        raise ReferenceTableError(f"rows.csv: {len(missing)} chart(s) missing from chart_order")
    result: list[SecondSourceRow] = []
    for row in rows:
        entry = chart_order[row["chart_file"]]
        kind = classify_row(row)
        result.append(
            SecondSourceRow(
                source="smw",
                season=season,
                pointer=f"{row['chart_file']}:{row['row']}",
                date_et=parse_chart_date(row["date"], season),
                away_raw=away_team_text(row["away"]),
                home_raw=row["home"],
                network_raw=row["network"],
                viewers=parse_viewers(row["viewers"]) if kind == "figure" else None,
                kind=kind,
                chart_kind=entry.chart_kind,
                rank=entry.rank,
                source_url=source_url,
                superseded=bool(row.get("superseded_by", "")),
            )
        )
    return result
