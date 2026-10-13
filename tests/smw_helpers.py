"""Builders for synthetic SMW season folders (invented rows, tiny PNGs)."""

from __future__ import annotations

import contextlib
from pathlib import Path

from booth_review.sources.smw.chart_order import parse_chart_order
from booth_review.sources.smw.diff import (
    SmwMergeError,
    diff_passes,
    load_resolutions,
    merge_rows,
    write_diff_csv,
    write_rows_csv,
)
from booth_review.sources.smw.rows import PASS_COLUMNS

FIXTURES = Path(__file__).parent / "fixtures" / "smw"
PAGE = (FIXTURES / "season-page.synthetic.html").read_text(encoding="utf-8")
CHARTS = ("week2cfb-1.png", "week5cfb.png", "champweekcfb.png")
HEADER = ",".join(PASS_COLUMNS) + "\n"

# 8-byte signature, then a 13-byte IHDR chunk (length, type, data, crc).
TINY_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + bytes(13) + bytes(4)


def pass_line(chart: str, n: int, away: str, home: str, viewers: str) -> str:
    return f"{chart},{n},Sat,10/1,,{away},{home},ABC,2.1,{viewers},\n"


def write_pass(folder: Path, chart: str, *lines: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{chart.removesuffix('.png')}.csv").write_text(HEADER + "".join(lines))


def build_season(folder: Path, *, viewers: str = "5.83M", b_viewers: str | None = None) -> Path:
    """A complete reconciled 2022 folder; `b_viewers` makes pass B disagree (unresolved)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "season-page.html").write_text(PAGE, encoding="utf-8")
    teams = {
        "week2cfb-1.png": ("Silverlake", "Northfield"),
        "week5cfb.png": ("Riverbend", "Hilltop"),
        "champweekcfb.png": ("Eastmoor", "Westgate"),
    }
    tdir = folder / "transcription"
    for chart, (away, home) in teams.items():
        (folder / chart).write_bytes(TINY_PNG)
        write_pass(tdir / "pass-a", chart, pass_line(chart, 1, away, home, viewers))
        other = b_viewers if (b_viewers is not None and chart == "week5cfb.png") else viewers
        write_pass(tdir / "pass-b", chart, pass_line(chart, 1, away, home, other))
    with contextlib.suppress(SmwMergeError):  # unresolved: diff.csv written, rows.csv not
        reconcile(folder)
    return folder


def reconcile(folder: Path) -> None:
    """Write diff.csv and rows.csv the way the review commands do."""
    tdir = folder / "transcription"
    charts = sorted(p.name for p in folder.glob("*.png"))
    diff = diff_passes(tdir / "pass-a", tdir / "pass-b", charts)
    write_diff_csv(tdir / "diff.csv", diff)
    order = parse_chart_order(
        (folder / "season-page.html").read_text(encoding="utf-8"), set(charts)
    )
    pass_c = tdir / "pass-c"
    merged = merge_rows(
        tdir / "pass-a",
        pass_c if pass_c.is_dir() else None,
        diff,
        load_resolutions(tdir / "resolutions.csv"),
        order.entries,
    )
    write_rows_csv(tdir / "rows.csv", merged)
