from __future__ import annotations

from pathlib import Path

import pytest

from booth_review.sources.smw.chart_order import ChartOrderEntry
from booth_review.sources.smw.diff import (
    SmwMergeError,
    diff_passes,
    load_resolutions,
    merge_rows,
)
from booth_review.sources.smw.rows import PASS_COLUMNS

HEADER = ",".join(PASS_COLUMNS) + "\n"


def line(chart: str, n: int, away="Silverlake", home="Northfield", date="10/1", viewers="5.83M"):
    return f"{chart},{n},Sat,{date},,{away},{home},ABC,2.1,{viewers},\n"


def write(folder: Path, chart: str, *lines: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{chart.removesuffix('.png')}.csv").write_text(HEADER + "".join(lines))


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    return tmp_path / "a", tmp_path / "b", tmp_path / "c"


def order(*specs: tuple[str, str, int]) -> dict[str, ChartOrderEntry]:
    return {f: ChartOrderEntry(f, "", "2022-10", 0, k, r) for f, k, r in specs}  # type: ignore[arg-type]


def test_identical(dirs) -> None:
    a, b, _ = dirs
    for d in (a, b):
        write(d, "w1.png", line("w1.png", 1))
    assert diff_passes(a, b, ["w1.png"]) == []


def test_cell_diff_and_whitespace_and_case(dirs) -> None:
    a, b, _ = dirs
    write(a, "w1.png", line("w1.png", 1, away="Silverlake  FC", viewers="5.83M"))
    write(b, "w1.png", line("w1.png", 1, away=" Silverlake FC ", viewers="5.38M"))
    entries = diff_passes(a, b, ["w1.png"])
    assert [(e.kind, e.column) for e in entries] == [("cell", "viewers")]
    write(b, "w1.png", line("w1.png", 1, away="silverlake FC", viewers="5.83M"))
    assert [e.column for e in diff_passes(a, b, ["w1.png"])] == ["away"]


def test_row_count_and_missing(dirs) -> None:
    a, b, _ = dirs
    write(a, "x.png", line("x.png", 1))
    write(b, "x.png", line("x.png", 1, viewers="1M"), line("x.png", 2))
    write(a, "y.png", line("y.png", 1))
    write(a, "ok.png", line("ok.png", 1))
    write(b, "ok.png", line("ok.png", 1))
    entries = diff_passes(a, b, ["x.png", "y.png", "ok.png", "none.png"])
    kinds = {(e.chart_file, e.kind) for e in entries}
    assert kinds == {
        ("x.png", "row_count"),
        ("y.png", "missing_chart"),
        ("none.png", "missing_chart"),
    }
    none = next(e for e in entries if e.chart_file == "none.png")
    assert none.pass_a == "" and none.pass_b == ""


def test_chart_file_mismatch_is_count_only(dirs) -> None:
    a, b, _ = dirs
    write(a, "x.png", line("other.png", 1, away="Zephyrville"))
    with pytest.raises(SmwMergeError) as exc:
        diff_passes(a, b, ["x.png"])
    assert "Zephyrville" not in str(exc.value)


def test_merge_refuses_unresolved(dirs) -> None:
    a, b, _ = dirs
    write(a, "w1.png", line("w1.png", 1, away="Zephyrville"))
    write(b, "w1.png", line("w1.png", 1, away="Zephyrvile", viewers="1M"))
    diff = diff_passes(a, b, ["w1.png"])
    with pytest.raises(
        SmwMergeError, match=r"2 unresolved cell\(s\), 0 unresolved chart\(s\)"
    ) as exc:
        merge_rows(a, None, diff, {}, order(("w1.png", "weekly", 1)))
    assert "Zephyr" not in str(exc.value)


def test_merge_applies_resolutions_and_gate_reread(dirs, tmp_path: Path) -> None:
    a, b, _ = dirs
    write(a, "w1.png", line("w1.png", 1, viewers="5.83M"), line("w1.png", 2, home="Riverbend"))
    write(b, "w1.png", line("w1.png", 1, viewers="5.38M"), line("w1.png", 2, home="Riverbend"))
    res = tmp_path / "resolutions.csv"
    res.write_text(
        "chart_file,row,column,value,how\n"
        "w1.png,1,viewers,5.9M,third_look\n"
        "w1.png,2,home,Riverbund,gate_reread\n"
    )
    resolutions = load_resolutions(res)
    merged = merge_rows(
        a, None, diff_passes(a, b, ["w1.png"]), resolutions, order(("w1.png", "weekly", 1))
    )
    assert merged[0]["viewers"] == "5.9M"
    assert merged[1]["home"] == "Riverbund"


def test_pass_c_replaces_chart_and_clears_row_count(dirs) -> None:
    a, b, c = dirs
    write(a, "x.png", line("x.png", 1))
    write(b, "x.png", line("x.png", 1), line("x.png", 2))
    write(c, "x.png", line("x.png", 1, viewers="9M"), line("x.png", 2))
    diff = diff_passes(a, b, ["x.png"])
    merged = merge_rows(a, c, diff, {}, order(("x.png", "weekly", 1)))
    assert len(merged) == 2 and merged[0]["viewers"] == "9M"


def test_supersession(dirs) -> None:
    a, _, _ = dirs
    write(a, "w1.png", line("w1.png", 1), line("w1.png", 2, away="Riverbend", home="Hilltop"))
    write(a, "w2.png", line("w2.png", 1, away="Northfield", home="Silverlake"))
    write(a, "top.png", line("top.png", 1))
    merged = merge_rows(
        a,
        None,
        [],
        {},
        order(("w1.png", "weekly", 1), ("w2.png", "weekly", 2), ("top.png", "season_top", 3)),
    )
    by_key = {(r["chart_file"], r["row"]): r["superseded_by"] for r in merged}
    assert by_key[("w1.png", "1")] == "w2.png:1"
    assert by_key[("w2.png", "1")] == ""
    assert by_key[("top.png", "1")] == ""
    assert by_key[("w1.png", "2")] == ""


def test_resolution_validation(tmp_path: Path) -> None:
    res = tmp_path / "r.csv"
    res.write_text("chart_file,row,column,value,how\nw.png,1,viewers,5M,guess\n")
    from booth_review.errors import ReferenceTableError

    with pytest.raises(ReferenceTableError, match="line 2"):
        load_resolutions(res)
