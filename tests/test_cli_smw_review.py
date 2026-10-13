"""`review smw-diff` and `review smw-merge` (04.19 D-01): offline, counts only."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from smw_helpers import CHARTS, FIXTURES, PAGE, TINY_PNG, pass_line, write_pass

from booth_review.cli import main


def _season(root: Path, *, b_viewers: str | None = None) -> Path:
    folder = root / "2022"
    folder.mkdir(parents=True)
    (folder / "season-page.html").write_text(PAGE, encoding="utf-8")
    tdir = folder / "transcription"
    for chart in CHARTS:
        (folder / chart).write_bytes(TINY_PNG)
        write_pass(tdir / "pass-a", chart, pass_line(chart, 1, "Silverlake", "Northfield", "5M"))
        other = b_viewers if (b_viewers and chart == CHARTS[1]) else "5M"
        write_pass(tdir / "pass-b", chart, pass_line(chart, 1, "Silverlake", "Northfield", other))
    return folder


def test_diff_writes_csv_and_prints_counts(tmp_path, capsys):
    folder = _season(tmp_path, b_viewers="4M")
    assert main(["review", "smw-diff", "--season", "2022", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "charts 3, cell diffs 1, row-count diffs 0, missing charts 0" in out
    lines = (folder / "transcription" / "diff.csv").read_text().splitlines()
    assert len(lines) == 2
    assert "Silverlake" not in out


def test_diff_fixture_passes(tmp_path, capsys):
    folder = tmp_path / "2022"
    (folder / "transcription").mkdir(parents=True)
    (folder / "week1synthetic.png").write_bytes(TINY_PNG)
    for name in ("pass-a", "pass-b"):
        shutil.copytree(FIXTURES / name, folder / "transcription" / name)
    assert main(["review", "smw-diff", "--season", "2022", "--root", str(tmp_path)]) == 0
    assert "cell diffs 1" in capsys.readouterr().out


def test_check_pass_never_opens_other_pass(tmp_path, capsys):
    folder = _season(tmp_path)
    pass_b = folder / "transcription" / "pass-b"
    pass_b.chmod(0o000)
    try:
        if os.access(pass_b, os.R_OK):
            pytest.skip("permissions are not enforced for this user")
        code = main(
            ["review", "smw-diff", "--season", "2022", "--root", str(tmp_path), "--check-pass", "a"]
        )
    finally:
        pass_b.chmod(0o755)
    assert code == 0
    assert "pass a: charts covered 3 of 3, rows 3" in capsys.readouterr().out
    assert not (folder / "transcription" / "diff.csv").exists()


def test_check_pass_schema_error_is_line_cited(tmp_path, capsys):
    folder = _season(tmp_path)
    (folder / "transcription" / "pass-a" / "week5cfb.csv").write_text(
        "chart_file,row\nweek5cfb.png,1\n"
    )
    code = main(
        ["review", "smw-diff", "--season", "2022", "--root", str(tmp_path), "--check-pass", "a"]
    )
    assert code in (3, 4)
    assert "week5cfb.csv" in capsys.readouterr().err


def test_merge_refuses_unresolved_then_writes_rows(tmp_path, capsys):
    folder = _season(tmp_path, b_viewers="4M")
    args = ["--season", "2022", "--root", str(tmp_path)]
    assert main(["review", "smw-merge", *args]) == 4
    assert "1 unresolved cell(s)" in capsys.readouterr().out
    assert not (folder / "transcription" / "rows.csv").exists()

    (folder / "transcription" / "resolutions.csv").write_text(
        "chart_file,row,column,value,how\nweek5cfb.png,1,viewers,5M,third_look\n"
    )
    assert main(["review", "smw-merge", *args]) == 0
    assert "rows 3 from 3 chart(s)" in capsys.readouterr().out
    assert (folder / "transcription" / "rows.csv").is_file()
