"""MLB completeness, freeze, Retrosheet drift and the `mlb freeze` command (synthetic vault)."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date
from pathlib import Path

import pytest
from mlb_games_support import gameinfo_row
from mlb_pipeline_support import bundle

from booth_review.cli import main
from booth_review.config import DataPaths
from booth_review.mlb import freeze as mlb_freeze
from booth_review.mlb.collect_cli import write_mlb_rr_windows
from booth_review.mlb.freeze import (
    accept_retrosheet_drift,
    freeze_mlb_seasons,
    mlb_completeness,
    parse_mlb_waiver,
    retrosheet_drift,
)
from booth_review.mlb.layout import (
    MLB_ROUNDS,
    MLB_SOURCES,
    mlb_506_path,
    mlb_rr_path,
    mlb_wikipedia_path,
    retrosheet_asset_path,
)

TODAY = date(2026, 10, 10)
SEASON = 2019


@pytest.fixture(autouse=True)
def _pass_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mlb_freeze, "mlb_smoke_check", lambda content, **_k: None if b"good" in content else "bad"
    )


def _write(paths: DataPaths, rel: str, data: bytes) -> None:
    target = paths.raw / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _bundle(paths: DataPaths, season: int = SEASON, runs: int = 4) -> None:
    rows = [gameinfo_row("G1", "XAA", "XBB", f"{season}0401", "regular", season=season, hruns=runs)]
    _write(paths, retrosheet_asset_path(f"{season}csvs.zip"), bundle(season, rows, {}))


def _seed(paths: DataPaths, season: int = SEASON, *, skip: str = "") -> None:
    if skip != "mlb_retrosheet":
        _bundle(paths, season)
    if skip != "mlb_sports506":
        for label in MLB_ROUNDS:
            _write(paths, mlb_506_path(season, label), b"good")
    if skip != "mlb_wikipedia":
        _write(paths, mlb_wikipedia_path(season), b"article")
    if skip != "mlb_ratingsref":
        _write(paths, mlb_rr_path(season, "mlb-aa-bb-2019-10-05"), b"{}")
        write_mlb_rr_windows(paths, [(date(2019, 10, 1), date(2019, 10, 31))])


def test_completeness_ok(vault_paths: DataPaths) -> None:
    _seed(vault_paths)
    result = mlb_completeness(vault_paths, SEASON)
    assert result.ok and not result.reasons
    assert result.evidence["mlb_sports506"] == len(MLB_ROUNDS)


@pytest.mark.parametrize("source", [s for s in MLB_SOURCES if s != "mlb_relay"])
def test_each_missing_piece_has_a_reason(vault_paths: DataPaths, source: str) -> None:
    _seed(vault_paths, skip=source)
    result = mlb_completeness(vault_paths, SEASON)
    assert not result.ok
    assert set(result.reasons) == {source}


def test_failed_smoke_check_blocks(vault_paths: DataPaths) -> None:
    _seed(vault_paths)
    _write(vault_paths, mlb_506_path(SEASON, "WS"), b"junk")
    assert (
        "failed smoke check rounds WS"
        in mlb_completeness(vault_paths, SEASON).reasons["mlb_sports506"]
    )


def test_freeze_refused_before_the_march_first_freeze_date(vault_paths: DataPaths) -> None:
    _seed(vault_paths)
    result = freeze_mlb_seasons(vault_paths, [SEASON], date(2020, 2, 28))
    assert SEASON in result.refused and not result.frozen
    assert not (vault_paths.audit / "mlb_freeze.json").exists()
    assert freeze_mlb_seasons(vault_paths, [SEASON], date(2020, 3, 1)).frozen == (SEASON,)


def test_freezing_2026_is_refused_in_this_phase(vault_paths: DataPaths) -> None:
    _seed(vault_paths, 2026)
    result = freeze_mlb_seasons(vault_paths, [2026], date(2027, 6, 1))
    assert 2026 in result.refused and not result.frozen
    assert "not frozen in this phase" in result.refused[2026]


def test_freeze_writes_only_mlb_keys(vault_paths: DataPaths) -> None:
    cfb = {"sports506": [2014], "ratingsref": [2019], "cfbd": [2018]}
    vault_paths.frozen.write_text(json.dumps({**cfb, "nfl_nflverse": [2015]}), encoding="utf-8")
    _seed(vault_paths)

    result = freeze_mlb_seasons(vault_paths, [SEASON], TODAY)

    assert result.frozen == (SEASON,) and not result.refused
    data = json.loads(vault_paths.frozen.read_text())
    for source in MLB_SOURCES:
        assert data[source] == [SEASON]
    assert {k: data[k] for k in cfb} == cfb
    assert data["nfl_nflverse"] == [2015]
    record = json.loads((vault_paths.audit / "mlb_freeze.json").read_text())
    assert record["seasons"] == [SEASON]
    assert len(record["retrosheet_digest"][str(SEASON)]) == 64


def test_incomplete_refuses_and_waiver_passes(vault_paths: DataPaths) -> None:
    _seed(vault_paths, skip="mlb_wikipedia")
    assert SEASON in freeze_mlb_seasons(vault_paths, [SEASON], TODAY).refused

    waived = freeze_mlb_seasons(vault_paths, [SEASON], TODAY, waivers=[(SEASON, "mlb_wikipedia")])

    assert waived.frozen == (SEASON,)
    assert waived.waived == (f"{SEASON}:mlb_wikipedia",)


def test_dry_run_writes_nothing(vault_paths: DataPaths) -> None:
    _seed(vault_paths)
    before = vault_paths.frozen.read_text()
    result = freeze_mlb_seasons(vault_paths, [SEASON], TODAY, dry_run=True)
    assert result.frozen == (SEASON,)
    assert vault_paths.frozen.read_text() == before
    assert not (vault_paths.audit / "mlb_freeze.json").exists()


def test_drift_detected_and_accepted(vault_paths: DataPaths) -> None:
    _seed(vault_paths)
    freeze_mlb_seasons(vault_paths, [SEASON], TODAY)
    assert retrosheet_drift(vault_paths) == []

    _bundle(vault_paths, runs=9)  # a semi-annual Retrosheet re-issue changed a score
    assert retrosheet_drift(vault_paths) == [SEASON]

    result = accept_retrosheet_drift(vault_paths, [SEASON], date(2026, 11, 1))
    assert result.accepted == (SEASON,)
    assert retrosheet_drift(vault_paths) == []
    record = json.loads((vault_paths.audit / "mlb_freeze.json").read_text())
    assert record["drift_accepted"][str(SEASON)] == ["2026-11-01T00:00:00Z"]


def test_accept_drift_refuses_a_season_that_is_not_frozen(vault_paths: DataPaths) -> None:
    _seed(vault_paths)
    result = accept_retrosheet_drift(vault_paths, [SEASON], TODAY)
    assert result.not_frozen == (SEASON,) and not result.written


def test_parse_waiver() -> None:
    assert parse_mlb_waiver("2016:mlb_wikipedia") == (2016, "mlb_wikipedia")
    for bad in ("2016:nfl_wikipedia", "2016", "x:mlb_relay", "2016:wikipedia"):
        with pytest.raises(argparse.ArgumentTypeError):
            parse_mlb_waiver(bad)


def _git(paths: DataPaths, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(paths.vault), *args], check=True, capture_output=True, text=True
    ).stdout


def test_cli_freeze_dry_run_refusal_and_2026(
    git_vault: DataPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(git_vault)
    assert main(["mlb", "freeze", "--season", str(SEASON), "--dry-run"]) == 0
    assert f"{SEASON}: would freeze" in capsys.readouterr().out
    assert "mlb_retrosheet" not in json.loads(git_vault.frozen.read_text())

    before = int(_git(git_vault, "rev-list", "--count", "HEAD"))
    assert main(["mlb", "freeze", "--season", str(SEASON)]) == 0
    assert int(_git(git_vault, "rev-list", "--count", "HEAD")) == before + 1
    lines = _git(git_vault, "show", "--name-only", "--format=%s", "HEAD").splitlines()
    assert lines[0] == f"freeze: mlb {SEASON}-{SEASON} (seasons 1, waived 0)"
    assert sorted(x for x in lines[1:] if x) == ["audit/mlb_freeze.json", "ledger/frozen.json"]

    assert main(["mlb", "freeze", "--check-drift"]) == 0
    _bundle(git_vault, runs=9)
    assert main(["mlb", "freeze", "--check-drift"]) == 4
    assert main(["mlb", "freeze", "--accept-drift", "--season", str(SEASON)]) == 0
    assert main(["mlb", "freeze", "--check-drift"]) == 0

    assert main(["mlb", "freeze", "--season", "2026", "--no-commit"]) == 4
    assert "not frozen in this phase" in capsys.readouterr().err


def test_cli_freeze_incomplete_exits_4(git_vault: DataPaths) -> None:
    _seed(git_vault, skip="mlb_ratingsref")
    assert main(["mlb", "freeze", "--season", str(SEASON), "--no-commit"]) == 4


def test_module_text_has_no_source_urls() -> None:
    assert "506sports" not in Path(mlb_freeze.__file__).read_text()
