"""Two-pass transcription diff and merge (04.19 D-01, D-08).

Aligns pass A and pass B per chart, reports disagreements, and builds rows.csv
from pass A plus the resolutions. Error messages carry counts only, never a
cell value.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from booth_review.build.io import write_review_csv
from booth_review.errors import BoothReviewError, ReferenceTableError
from booth_review.reference import read_reference_csv_numbered
from booth_review.sources.smw.chart_order import ChartOrderEntry
from booth_review.sources.smw.rows import PASS_COLUMNS, ROWS_COLUMNS, load_pass_csv

DIFF_COLUMNS = ("chart_file", "row", "column", "pass_a", "pass_b", "kind")
RESOLUTION_COLUMNS = ("chart_file", "row", "column", "value", "how")
KNOWN_DISAGREEMENT_COLUMNS = ("chart_file", "row", "explanation")
_HOW = ("pass_a", "pass_b", "third_look", "gate_reread")
_CELL_COLUMNS = tuple(c for c in PASS_COLUMNS if c not in ("chart_file", "row"))
_WS_RE = re.compile(r"\s+")


class SmwMergeError(BoothReviewError):
    """Raised when passes cannot be diffed or merged."""


@dataclass(frozen=True)
class DiffEntry:
    chart_file: str
    row: str
    column: str
    pass_a: str
    pass_b: str
    kind: str  # cell | row_count | missing_chart


def _norm(text: str) -> str:
    return _WS_RE.sub(" ", text.strip())


def load_pass_dir(path: Path) -> dict[str, list[dict[str, str]]]:
    """Read every <stem>.csv in a pass folder, keyed by chart_file."""
    charts: dict[str, list[dict[str, str]]] = {}
    if not path.is_dir():
        return charts
    for csv_path in sorted(path.glob("*.csv")):
        rows = load_pass_csv(csv_path)
        expected = f"{csv_path.stem}.png"
        if any(r["chart_file"] != expected for r in rows):
            raise SmwMergeError(f"{csv_path.name}: chart_file column disagrees with the file name")
        if rows:
            charts[expected] = sorted(rows, key=lambda r: int(r["row"]))
    return charts


def diff_passes(pass_a: Path, pass_b: Path, charts: Sequence[str]) -> list[DiffEntry]:
    a_charts = load_pass_dir(pass_a)
    b_charts = load_pass_dir(pass_b)
    entries: list[DiffEntry] = []
    for chart in sorted(set(charts) | set(a_charts) | set(b_charts)):
        in_a, in_b = chart in a_charts, chart in b_charts
        if not (in_a and in_b):
            entries.append(
                DiffEntry(chart, "", "", "x" if in_a else "", "x" if in_b else "", "missing_chart")
            )
            continue
        rows_a, rows_b = a_charts[chart], b_charts[chart]
        if len(rows_a) != len(rows_b):
            entries.append(
                DiffEntry(chart, "", "", str(len(rows_a)), str(len(rows_b)), "row_count")
            )
            continue
        for ra, rb in zip(rows_a, rows_b, strict=True):
            if ra["row"] != rb["row"]:
                entries.append(
                    DiffEntry(chart, "", "", str(len(rows_a)), str(len(rows_b)), "row_count")
                )
                break
            for column in _CELL_COLUMNS:
                if _norm(ra[column]) != _norm(rb[column]):
                    entries.append(
                        DiffEntry(chart, ra["row"], column, ra[column], rb[column], "cell")
                    )
    return entries


def write_diff_csv(path: Path, entries: Sequence[DiffEntry]) -> None:
    write_review_csv(
        path,
        DIFF_COLUMNS,
        [
            {
                "chart_file": e.chart_file,
                "row": e.row,
                "column": e.column,
                "pass_a": e.pass_a,
                "pass_b": e.pass_b,
                "kind": e.kind,
            }
            for e in entries
        ],
    )


def load_resolutions(path: Path) -> dict[tuple[str, int, str], tuple[str, str]]:
    """(chart_file, row, column) -> (value, how); strict, line-cited."""

    def fail(line_no: int, what: str) -> ReferenceTableError:
        return ReferenceTableError(f"{path.name}: line {line_no}: {what}")

    out: dict[tuple[str, int, str], tuple[str, str]] = {}
    for line_no, raw in read_reference_csv_numbered(path, RESOLUTION_COLUMNS, required=False):
        cell = raw["row"]
        if not (cell.isascii() and cell.isdecimal()) or int(cell) <= 0:
            raise fail(line_no, "row must be a positive integer")
        if raw["column"] not in _CELL_COLUMNS:
            raise fail(line_no, "column is not a resolvable column")
        if raw["how"] not in _HOW:
            raise fail(line_no, "how is not a known value")
        key = (raw["chart_file"], int(cell), raw["column"])
        if key in out:
            raise fail(line_no, "duplicate resolution")
        out[key] = (raw["value"], raw["how"])
    return out


def _pair_key(row: Mapping[str, str]) -> tuple[str, frozenset[str]]:
    teams = frozenset(_norm(row[c]).casefold() for c in ("away", "home"))
    return (_norm(row["date"]), teams)


def merge_rows(
    pass_a: Path,
    pass_c: Path | None,
    diff: Sequence[DiffEntry],
    resolutions: Mapping[tuple[str, int, str], tuple[str, str]],
    chart_order: Mapping[str, ChartOrderEntry],
) -> list[dict[str, str]]:
    """Build rows.csv content; refuses while any diff entry is unresolved."""
    charts = load_pass_dir(pass_a)
    c_charts = load_pass_dir(pass_c) if pass_c is not None else {}
    for chart, rows in c_charts.items():
        charts[chart] = rows

    unresolved_cells = sum(
        1
        for e in diff
        if e.kind == "cell"
        and e.chart_file not in c_charts
        and (e.chart_file, int(e.row), e.column) not in resolutions
    )
    unresolved_charts = len({e.chart_file for e in diff if e.kind != "cell"} - set(c_charts))
    if unresolved_cells or unresolved_charts:
        raise SmwMergeError(
            f"{unresolved_cells} unresolved cell(s), {unresolved_charts} unresolved chart(s)"
        )

    merged: list[dict[str, str]] = []
    for chart, rows in charts.items():
        for row in rows:
            out = {c: row[c] for c in PASS_COLUMNS}
            out["superseded_by"] = ""
            if chart not in c_charts:
                for column in _CELL_COLUMNS:
                    hit = resolutions.get((chart, int(row["row"]), column))
                    if hit is not None:
                        out[column] = hit[0]
            merged.append(out)

    missing_order = {r["chart_file"] for r in merged} - set(chart_order)
    if missing_order:
        raise SmwMergeError(f"{len(missing_order)} chart(s) missing from chart order")

    def rank(row: Mapping[str, str]) -> int:
        return chart_order[row["chart_file"]].rank

    merged.sort(key=lambda r: (rank(r), int(r["row"])))

    groups: dict[tuple[str, frozenset[str]], list[dict[str, str]]] = {}
    for row in merged:
        if chart_order[row["chart_file"]].chart_kind == "season_top":
            continue
        groups.setdefault(_pair_key(row), []).append(row)
    for group in groups.values():
        if len(group) < 2:
            continue
        winner = max(group, key=rank)
        for row in group:
            if row is not winner and rank(row) < rank(winner):
                row["superseded_by"] = f"{winner['chart_file']}:{winner['row']}"
    return merged


def write_rows_csv(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    write_review_csv(path, ROWS_COLUMNS, rows)
