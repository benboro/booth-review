"""NFL completeness, freeze, drift and the nfl gaps/freeze commands (synthetic vault)."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from nfl_join_helpers import sched_row, schedule_csv

from booth_review.cli import main
from booth_review.config import DataPaths
from booth_review.nfl import freeze as nfl_freeze
from booth_review.nfl.freeze import (
    freeze_nfl_seasons,
    nfl_completeness,
    parse_nfl_waiver,
    schedule_drift,
)
from booth_review.nfl.layout import (
    NFLVERSE_SCHEDULES_PATH,
    nfl_506_path,
    nfl_rr_path,
    nflverse_pbp_path,
    wikipedia_path,
)

TODAY = date(2026, 10, 10)
SOURCES = ("nfl_sports506", "nfl_ratingsref", "nfl_nflverse", "nfl_wikipedia")


@pytest.fixture(autouse=True)
def _pass_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        nfl_freeze, "nfl_smoke_check", lambda *a, **k: SimpleNamespace(passed=b"good" in a[0])
    )


def _write(paths: DataPaths, rel: str, data: bytes) -> None:
    target = paths.raw / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _schedule(paths: DataPaths, extra: str = "") -> None:
    rows = [
        sched_row("a", 1, "2015-09-13", "AAA", "BBB", stadium=extra or "Invented Field"),
        sched_row("b", 2, "2015-09-20", "AAA", "BBB"),
        sched_row("c", 1, "2016-09-11", "AAA", "BBB", season="2016"),
    ]
    _write(paths, NFLVERSE_SCHEDULES_PATH, schedule_csv(rows))


def _seed(paths: DataPaths, season: int = 2015, *, skip: str = "") -> None:
    if skip != "nfl_nflverse":
        _schedule(paths)
        _write(paths, nflverse_pbp_path(season), b"pbp")
    if skip != "nfl_sports506":
        for week in range(1, 18):
            _write(paths, nfl_506_path(season, week), b"good")
    if skip != "nfl_wikipedia":
        _write(paths, wikipedia_path(season), b"article")
    if skip != "nfl_ratingsref":
        _write(paths, nfl_rr_path(season, "1"), b"{}")


def test_completeness_ok(vault_paths: DataPaths) -> None:
    _seed(vault_paths)
    result = nfl_completeness(vault_paths, 2015)
    assert result.ok and not result.reasons
    assert result.evidence["nfl_sports506"] == 17


@pytest.mark.parametrize("source", SOURCES)
def test_each_missing_piece_has_a_reason(vault_paths: DataPaths, source: str) -> None:
    _seed(vault_paths, skip=source)
    result = nfl_completeness(vault_paths, 2015)
    assert not result.ok
    assert set(result.reasons) == {source}


def test_failed_smoke_check_blocks(vault_paths: DataPaths) -> None:
    _seed(vault_paths)
    _write(vault_paths, nfl_506_path(2015, 4), b"junk")
    result = nfl_completeness(vault_paths, 2015)
    assert "failed smoke check weeks 4" in result.reasons["nfl_sports506"]


def test_freeze_refused_before_date(vault_paths: DataPaths) -> None:
    _seed(vault_paths)
    result = freeze_nfl_seasons(vault_paths, [2015], date(2016, 2, 20))
    assert 2015 in result.refused and not result.frozen
    assert json.loads(vault_paths.frozen.read_text()) == {
        "sports506": [],
        "ratingsref": [],
        "cfbd": [],
    }
    assert not (vault_paths.audit / "nfl_freeze.json").exists()


def test_freeze_writes_only_nfl_keys(vault_paths: DataPaths) -> None:
    _seed(vault_paths)
    before = vault_paths.frozen.read_text()
    result = freeze_nfl_seasons(vault_paths, [2015], TODAY)
    assert result.frozen == (2015,) and not result.refused
    data = json.loads(vault_paths.frozen.read_text())
    for source in SOURCES:
        assert data[source] == [2015]
    old = json.loads(before)
    assert {k: data[k] for k in old} == old
    record = json.loads((vault_paths.audit / "nfl_freeze.json").read_text())
    assert record["seasons"] == [2015]
    assert record["evidence"]["2015"]["nfl_sports506"] == 17
    assert len(record["schedule_digest"]["2015"]) == 64


def test_incomplete_refuses_and_waiver_passes(vault_paths: DataPaths) -> None:
    _seed(vault_paths, skip="nfl_wikipedia")
    refused = freeze_nfl_seasons(vault_paths, [2015], TODAY)
    assert "nfl_wikipedia" in refused.refused[2015]
    ok = freeze_nfl_seasons(vault_paths, [2015], TODAY, waivers=[(2015, "nfl_wikipedia")])
    assert ok.frozen == (2015,) and ok.waived == ("2015:nfl_wikipedia",)
    record = json.loads((vault_paths.audit / "nfl_freeze.json").read_text())
    assert record["waivers"] == ["2015:nfl_wikipedia"]


def test_dry_run_writes_nothing(vault_paths: DataPaths) -> None:
    _seed(vault_paths)
    result = freeze_nfl_seasons(vault_paths, [2015], TODAY, dry_run=True)
    assert result.frozen == (2015,) and result.written == ()
    assert "nfl_sports506" not in json.loads(vault_paths.frozen.read_text())


def test_drift_detected(vault_paths: DataPaths) -> None:
    _seed(vault_paths)
    freeze_nfl_seasons(vault_paths, [2015], TODAY)
    assert schedule_drift(vault_paths) == []
    _schedule(vault_paths, extra="Changed Field")
    assert schedule_drift(vault_paths) == [2015]


def test_parse_waiver() -> None:
    assert parse_nfl_waiver("2015:nfl_wikipedia") == (2015, "nfl_wikipedia")
    for bad in ("2015:sports506", "x", "2015:"):
        with pytest.raises(argparse.ArgumentTypeError):
            parse_nfl_waiver(bad)


def _git(paths: DataPaths, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(paths.vault), *args], check=True, capture_output=True, text=True
    ).stdout


def test_cli_freeze_dry_run_commit_and_drift(
    git_vault: DataPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(git_vault)
    assert main(["nfl", "freeze", "--season", "2015", "--dry-run"]) == 0
    assert "2015: would freeze" in capsys.readouterr().out
    assert "nfl_sports506" not in json.loads(git_vault.frozen.read_text())

    before = int(_git(git_vault, "rev-list", "--count", "HEAD").strip())
    assert main(["nfl", "freeze", "--season", "2015"]) == 0
    assert int(_git(git_vault, "rev-list", "--count", "HEAD").strip()) == before + 1
    lines = _git(git_vault, "show", "--name-only", "--format=%s", "HEAD").splitlines()
    assert lines[0] == "freeze: nfl 2015-2015 (seasons 1, waived 0)"
    assert sorted(x for x in lines[1:] if x) == ["audit/nfl_freeze.json", "ledger/frozen.json"]

    assert main(["nfl", "freeze", "--check-drift"]) == 0
    _schedule(git_vault, extra="Changed Field")
    assert main(["nfl", "freeze", "--check-drift"]) == 4
    assert "drift: 1 season" in capsys.readouterr().out


def test_cli_freeze_refused_exit_4(git_vault: DataPaths) -> None:
    _seed(git_vault, skip="nfl_ratingsref")
    assert main(["nfl", "freeze", "--season", "2015", "--no-commit"]) == 4


def test_cli_gaps(git_vault: DataPaths, capsys: pytest.CaptureFixture[str]) -> None:
    _seed(git_vault)
    (git_vault.raw / nfl_506_path(2015, 1)).unlink()
    (git_vault.raw / nfl_506_path(2015, 2)).unlink()
    assert main(["nfl", "gaps", "--season", "2015"]) == 0
    out = capsys.readouterr().out
    assert "nfl 506 2015: judged 2, missing 2" in out
    assert "missing weeks: 1, 2" in out
    assert main(["nfl", "gaps", "--season", "2030"]) == 0


def test_cli_gaps_without_schedule_errors(git_vault: DataPaths) -> None:
    assert main(["nfl", "gaps", "--season", "2015"]) == 2


def test_no_path_leaks_module_text() -> None:
    assert "506sports" not in Path(nfl_freeze.__file__).read_text()
