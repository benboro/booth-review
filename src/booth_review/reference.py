"""The strict reader/writer every data/reference/*.csv table goes through.

data/reference is public (`.gitignore` allows it explicitly, `data/README.md`
lists it as always committed). Every table declares its exact columns so no
game-level row, crew, figure, or free text beyond the declared columns can be
added by accident (D-05, D-06 public-table safety; the one documented
exception is crew_overrides.csv, 04.3 D-01, whose rows each cite a public
source_url): a header that doesn't
match exactly is rejected, a row with more cells than the header is rejected,
and a cell that a spreadsheet would read as a formula is rejected -- naming
only the file and line number, never the offending content, so an error
message can never leak what almost got written.
"""

from __future__ import annotations

import csv
import io
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from booth_review.errors import ReferenceTableError
from booth_review.transport.cache import atomic_write_bytes

# Stable ASCII kebab ids for named games; never renamed once shipped.
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# A cell starting with any of these is interpreted as a formula by Excel/
# Sheets (classic CSV/formula injection) when opened in a spreadsheet. Same
# prefixes as resolve.names.csv_safe, restated locally rather than imported
# so this foundational module never depends on a later-plan package.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _is_formula_like(value: str) -> bool:
    return value.startswith(_FORMULA_PREFIXES) or value.strip().startswith(_FORMULA_PREFIXES)


def reference_dir() -> Path:
    """data/reference/, or BOOTH_REVIEW_REFERENCE when set and non-empty
    (mirrors config.DataPaths.from_env's env-override pattern, so tests can
    point at a synthetic fixture directory without a real data/reference/).
    """
    env = os.environ.get("BOOTH_REVIEW_REFERENCE")
    return Path(env) if env else Path("data/reference")


def read_reference_csv(
    path: Path, columns: tuple[str, ...], *, required: bool = False
) -> list[dict[str, str]]:
    """Read `path` as a strict CSV: the header must equal `columns` exactly
    (no missing, extra, or reordered column). Returns [] for a missing file
    when `required` is False; raises ReferenceTableError naming the file when
    `required` is True. Every value is whitespace-stripped; fully blank rows
    are skipped. A row with more cells than the header, or any cell
    beginning with =, +, -, @, a tab, or a carriage return, raises
    ReferenceTableError naming the file and line number only.

    A loader that reports its own per-row errors uses
    `read_reference_csv_numbered` instead, so its line numbers stay right
    when the file has blank spacer rows.
    """
    return [row for _, row in read_reference_csv_numbered(path, columns, required=required)]


def read_reference_csv_numbered(
    path: Path, columns: tuple[str, ...], *, required: bool = False
) -> list[tuple[int, dict[str, str]]]:
    """`read_reference_csv`, with each row paired with the physical line it
    starts on (the header is line 1; skipped blank rows still count), so a
    loader's error cites the line a user sees in an editor.
    """
    if not path.is_file():
        if required:
            raise ReferenceTableError(f"{path.name}: missing required reference table")
        return []

    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            raise ReferenceTableError(
                f"{path.name}: empty file, expected header {columns}"
            ) from None
        if tuple(header) != columns:
            raise ReferenceTableError(
                f"{path.name}: header {tuple(header)!r} does not match expected {columns!r}"
            )

        rows: list[tuple[int, dict[str, str]]] = []
        # reader.line_num counts physical lines read so far, blank rows
        # included, so a row starts one line past where the last one ended
        # (a quoted cell can carry a newline, so a row may span lines).
        last_line = reader.line_num
        for raw_row in reader:
            line_no = last_line + 1
            last_line = reader.line_num
            if not raw_row or all(cell.strip() == "" for cell in raw_row):
                continue
            if len(raw_row) > len(columns):
                raise ReferenceTableError(f"{path.name}: line {line_no}: unexpected extra column")
            values = list(raw_row) + [""] * (len(columns) - len(raw_row))
            for value in values:
                # Checked both before and after stripping (WR-13): a cell
                # like " =HYPERLINK(...)" must not pass the check and then
                # be returned stripped to a formula.
                if _is_formula_like(value):
                    raise ReferenceTableError(
                        f"{path.name}: line {line_no}: cell begins with a disallowed character"
                    )
            rows.append(
                (
                    line_no,
                    {col: value.strip() for col, value in zip(columns, values, strict=True)},
                )
            )
        return rows


def write_reference_csv(
    path: Path, columns: tuple[str, ...], rows: Sequence[Mapping[str, str]]
) -> None:
    """Write `rows` to `path` with `columns` as the header, LF line endings,
    and rows in the order given. A write then read (read_reference_csv)
    returns identical dicts. A cell read_reference_csv would reject (one
    beginning with a formula character) raises ReferenceTableError before
    anything is written, so a write can never produce an unreadable file;
    callers csv_safe free text first.
    """
    for line_no, row in enumerate(rows, start=2):
        if any(_is_formula_like(row.get(col, "")) for col in columns):
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: cell begins with a disallowed character"
            )
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({col: row.get(col, "") for col in columns})
    atomic_write_bytes(path, buf.getvalue().encode("utf-8"))
