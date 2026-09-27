"""Atomic writers for the build layer's outputs: Parquet processed tables
(D-12) and CSV review/diagnostic files, both written by temp-file-then-
replace so a crash never leaves a partial file at the real path (T-03-27).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import polars as pl

from booth_review.resolve.names import csv_safe
from booth_review.transport.cache import atomic_write_bytes


def write_parquet_atomic(frame: pl.DataFrame, path: Path) -> None:
    """Write `frame` to `path` as Parquet, atomically: to a temp sibling file
    first, then Path.replace over the target. The temp file name matches the
    vault's existing ".tmp-*" ignore convention, so a crash leftover is never
    mistaken for real output.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".tmp-{path.name}")
    try:
        frame.write_parquet(tmp_path)
        tmp_path.replace(path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def write_review_csv(
    path: Path,
    columns: Sequence[str],
    rows: Iterable[Mapping[str, object]],
) -> None:
    """Write a header plus `rows` to `path`, atomically: LF line endings,
    every str cell passed through csv_safe (WR-04, formula-injection-safe),
    and a missing/None cell written empty. Rows are written in the order
    given -- sorting, if any, is the caller's job.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        safe_row: dict[str, object] = {}
        for column in columns:
            value = row.get(column)
            safe_row[column] = csv_safe(value) if isinstance(value, str) else value
        writer.writerow(safe_row)
    atomic_write_bytes(path, buf.getvalue().encode("utf-8"))
