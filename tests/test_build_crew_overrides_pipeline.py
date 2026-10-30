"""Crew-override wiring in the real build (04.3-04): the vault gap list, the
patched and differing cases, the loud count-only failure, and the sentinel
leak check. Synthetic data only.
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from test_cli_build import _seed_build_raw

from booth_review.build.crew_overrides import REVIEW_CREW_GAPS_COLUMNS
from booth_review.build.pipeline import BuildOutcome, run_build
from booth_review.cli import main
from booth_review.config import DataPaths
from booth_review.errors import CrewOverrideError

_REFERENCE_FIXTURES = Path(__file__).parent / "fixtures" / "reference"
_SENTINEL = "SENTINEL ZEBRA HARBOR CREW NOTE"
_HEADER = (
    "cfbd_game_id,network_id,crew_position,person_id,role,reason,"
    "source_kind,source_name,source_url\n"
)
_URL = "https://example.com/pr/500005"


def _vault(git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _seed_build_raw(git_vault)
    games_file = git_vault.raw / "cfbd" / "games" / "2025.json"
    games = json.loads(games_file.read_text(encoding="utf-8"))
    for game in games:
        if game["id"] == 500005:
            game["notes"] = _SENTINEL
    games_file.write_text(json.dumps(games), encoding="utf-8")

    reference = tmp_path / "reference_ext"
    shutil.copytree(_REFERENCE_FIXTURES, reference)
    with (reference / "network_rarity.csv").open("a", encoding="utf-8", newline="") as rarity_fh:
        rarity_fh.write(
            "ecn,false\necn2,false\nespn,false\nespn2,false\nespnu,false\nespn-deportes,false\n"
        )
    with (reference / "networks.csv").open("a", encoding="utf-8", newline="") as fh:
        fh.write("ECN,ecn,Example Cable Network,family-ecn,cable,main,,,\n")
        fh.write("ECN2,ecn2,Example Cable Network 2,family-ecn,cable,main,,,\n")
        fh.write("ESPN,espn,ESPN,family-espn,cable,main,,,\n")
        fh.write("ESPN2,espn2,ESPN2,family-espn,cable,main,,,\n")
        fh.write("ESPNU,espnu,ESPNU,family-espn,cable,main,,,\n")
        fh.write("ESPN Deportes,espn-deportes,ESPN Deportes,family-espn,cable,spanish,,,\n")
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(reference))
    return reference


def _write_overrides(reference: Path, rows: list[str]) -> None:
    (reference / "crew_overrides.csv").write_text(_HEADER + "".join(rows), encoding="utf-8")


def _telecast(paths: DataPaths, game_id: int) -> dict[str, Any]:
    frame = pl.read_parquet(paths.vault / "processed" / "telecasts.parquet")
    rows = frame.filter(
        (pl.col("game_id") == game_id)
        & (pl.col("network_id") == "ecn")
        & (pl.col("feed_type") == "main")
    ).to_dicts()
    assert len(rows) == 1
    return rows[0]


def _gap_rows(paths: DataPaths) -> list[dict[str, str]]:
    path = paths.vault / "interim" / "review_crew_overrides.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _coverage_all(paths: DataPaths, season: int) -> dict[str, str]:
    with (paths.vault / "processed" / "coverage.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["season"] == str(season) and row["network_id"] == "ALL":
                return row
    raise AssertionError("no ALL coverage row")


def _people_for(paths: DataPaths, telecast_id: str) -> pl.DataFrame:
    return pl.read_parquet(paths.vault / "processed" / "telecast_people.parquet").filter(
        pl.col("telecast_id") == telecast_id
    )


def _metrics_row(paths: DataPaths, season: int) -> dict[str, str]:
    with (paths.audit / "build_metrics.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["season"] == str(season):
                return row
    raise AssertionError("no build_metrics row")


def _baseline(git_vault: DataPaths, reference: Path) -> BuildOutcome:
    return run_build(git_vault, reference, commit=False, accept_baseline=False)


def test_no_overrides_file_writes_gap_list(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _vault(git_vault, tmp_path, monkeypatch)
    outcome = _baseline(git_vault, reference)
    assert outcome.counts["crew_overrides_applied"] == 0

    path = git_vault.vault / "interim" / "review_crew_overrides.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        assert tuple(next(csv.reader(fh))) == REVIEW_CREW_GAPS_COLUMNS
    telecasts = pl.read_parquet(git_vault.vault / "processed" / "telecasts.parquet")
    expected = telecasts.filter(
        (pl.col("feed_type") == "main") & pl.col("plotted") & ~pl.col("crew_matched")
    ).height
    rows = _gap_rows(git_vault)
    assert len(rows) == expected
    assert outcome.counts["crew_gaps_unpatched"] == expected
    assert all(r["override_status"] == "missing" for r in rows)


def test_override_patches_a_telecast_with_no_506_crew(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _vault(git_vault, tmp_path, monkeypatch)
    before = _baseline(git_vault, reference)
    target = _telecast(git_vault, 500005)
    assert target["plotted"] and target["rated"]
    assert not target["crew_matched"]
    assert target["s506_pointer"] is None
    assert _people_for(git_vault, target["telecast_id"]).is_empty()
    season = target["season"]
    matched_before = int(_coverage_all(git_vault, season)["matched_crew"])
    records = len(target["rr_telecast_ids"])
    metrics_before = _metrics_row(git_vault, season)

    _write_overrides(
        reference,
        [
            f"500005,ecn,0,jac-collinsworth,pbp,no-506-listing,press-release,PR,{_URL}\n",
            f"500005,ecn,1,cris-collinsworth,analyst,no-506-listing,press-release,PR,{_URL}\n",
        ],
    )
    after = _baseline(git_vault, reference)

    people = _people_for(git_vault, target["telecast_id"])
    assert people.height == 2
    assert set(people["source"].to_list()) == {"crew_override"}
    assert after.counts["crew_overrides_applied"] == 1
    assert after.counts["crew_overrides_patched"] == 1
    assert after.counts["crew_overrides_corrections"] == 0
    assert after.counts["records_with_crew"] == before.counts["records_with_crew"] + records
    # The AUDIT-03 metrics keep a 506-only count the override never raises.
    metrics_after = _metrics_row(git_vault, season)
    assert int(metrics_after["records_with_crew"]) == (
        int(metrics_before["records_with_crew"]) + records
    )
    assert metrics_after["records_with_506_crew"] == metrics_before["records_with_506_crew"]
    assert int(metrics_before["records_with_506_crew"]) == int(metrics_before["records_with_crew"])
    assert after.counts["crew_gaps_unpatched"] == before.counts["crew_gaps_unpatched"] - 1

    coverage = _coverage_all(git_vault, season)
    assert coverage["crew_patched"] == "1"
    assert int(coverage["matched_crew"]) == matched_before + 1

    site: dict[str, Any] = json.loads(
        (git_vault.vault / "processed" / "site-data.json").read_text(encoding="utf-8")
    )
    dots = site["dots"] if "dots" in site else site["telecasts"]
    index = dots["crew_source_url"].index(_URL)
    assert dots["crew_source_label"][index] == "PR"
    assert dots["crew"][index]

    gap = [r for r in _gap_rows(git_vault) if r["cfbd_game_id"] == "500005"]
    assert [r["override_status"] for r in gap] == ["patched"]


def test_differing_override_is_a_warning_not_a_failure(
    git_vault: DataPaths,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reference = _vault(git_vault, tmp_path, monkeypatch)
    _baseline(git_vault, reference)
    target = _telecast(git_vault, 500001)
    assert target["crew_matched"]
    current = set(_people_for(git_vault, target["telecast_id"])["person_id"].to_list())
    wanted = [p for p in ("dale-harlow", "kris-venn") if p not in current]
    assert len(wanted) == 2

    _write_overrides(
        reference,
        [
            f"500001,ecn,0,{wanted[0]},pbp,no-506-crew,outlet,Outlet,https://example.com/a\n",
            f"500001,ecn,1,{wanted[1]},analyst,no-506-crew,outlet,Outlet,https://example.com/a\n",
        ],
    )
    capsys.readouterr()
    assert main(["build", "--no-commit"]) == 0
    captured = capsys.readouterr()
    out = captured.out
    assert "crew overrides differing from 506: 1" in out
    assert "crew gaps unpatched" in out
    # Flagged per row by its public crew_overrides.csv line, without blocking.
    assert (
        "warning: crew_overrides.csv line 2: booth differs from the crew 506 lists "
        "but reason is not correction" in captured.err
    )
    assert captured.err.count("warning: crew_overrides.csv") == 1
    gap = [r for r in _gap_rows(git_vault) if r["cfbd_game_id"] == "500001"]
    assert [(r["gap_kind"], r["override_status"]) for r in gap] == [("has-506-crew", "differs")]


def test_patch_and_correction_counts_reach_the_build_output(
    git_vault: DataPaths,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reference = _vault(git_vault, tmp_path, monkeypatch)
    _baseline(git_vault, reference)
    listed = _telecast(git_vault, 500001)
    assert listed["crew_matched"]
    current = set(_people_for(git_vault, listed["telecast_id"])["person_id"].to_list())
    wanted = [p for p in ("dale-harlow", "kris-venn") if p not in current]
    assert len(wanted) == 2
    assert not _telecast(git_vault, 500005)["crew_matched"]

    url = "https://example.com/a"
    _write_overrides(
        reference,
        [
            f"500001,ecn,0,{wanted[0]},pbp,correction,outlet,Outlet,{url}\n",
            f"500001,ecn,1,{wanted[1]},analyst,correction,outlet,Outlet,{url}\n",
            f"500005,ecn,0,jac-collinsworth,pbp,no-506-listing,press-release,PR,{_URL}\n",
            f"500005,ecn,1,cris-collinsworth,analyst,no-506-listing,press-release,PR,{_URL}\n",
        ],
    )
    outcome = _baseline(git_vault, reference)
    assert outcome.counts["crew_overrides_applied"] == 2
    assert outcome.counts["crew_overrides_patched"] == 1
    assert outcome.counts["crew_overrides_corrections"] == 1
    assert outcome.counts["crew_overrides_differs"] == 0

    capsys.readouterr()
    assert main(["build", "--no-commit"]) == 0
    out = capsys.readouterr().out
    assert "crew overrides patching a telecast 506 gave no crew: 1" in out
    assert "crew overrides correcting 506: 1" in out
    assert "crew overrides differing from 506" not in out
    assert outcome.crew_override_differs_lines == ()


def test_unknown_person_fails_count_only_and_writes_no_site_data(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _vault(git_vault, tmp_path, monkeypatch)
    _write_overrides(
        reference,
        ["500005,ecn,0,nobody-here,pbp,no-506-listing,outlet,Outlet,https://example.com/a\n"],
    )
    with pytest.raises(CrewOverrideError) as info:
        run_build(git_vault, reference, commit=False, accept_baseline=False)
    assert _SENTINEL not in str(info.value)
    assert "nobody-here" not in str(info.value)
    assert not (git_vault.vault / "processed" / "site-data.json").exists()


def test_sentinel_never_reaches_output_or_commit_message(
    git_vault: DataPaths,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reference = _vault(git_vault, tmp_path, monkeypatch)
    _write_overrides(
        reference,
        [
            f"500005,ecn,0,jac-collinsworth,pbp,no-506-listing,outlet,Outlet,{_URL}\n",
            f"500005,ecn,1,cris-collinsworth,analyst,no-506-listing,outlet,Outlet,{_URL}\n",
        ],
    )
    assert main(["build"]) == 0
    captured = capsys.readouterr()
    assert _SENTINEL not in captured.out
    assert _SENTINEL not in captured.err
    subject = subprocess.run(
        ["git", "-C", str(git_vault.vault), "log", "-1", "--format=%B"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert _SENTINEL not in subject
    review = (git_vault.vault / "interim" / "review_crew_overrides.csv").read_text(encoding="utf-8")
    assert "500005" in review


# -- the regression guard and rated games 506 lists with no crew -------------------------------

_SILVERLAKE_RR = "cfb-silverlake-west-hawaii-state-2025-09-20.json"  # game 500006, 506 row 1:4
_IRONPEAK_RR = "cfb-ironpeak-foxhollow-2025-11-08.json"  # game 500005, no 506 listing


def _blank_506_crew(paths: DataPaths) -> None:
    page = paths.raw / "sports506" / "2025" / "wk-01.html"
    html = page.read_text(encoding="utf-8")
    cell = '<div id="cntwk">ECN2</div><div id="canncrs">Casey Vale</div>'
    assert html.count(cell) == 1
    page.write_text(
        html.replace(cell, '<div id="cntwk">ECN2</div><div id="canncrs"></div>'), encoding="utf-8"
    )


def test_newly_rated_game_with_a_blank_506_crew_does_not_block(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = _vault(git_vault, tmp_path, monkeypatch)
    _blank_506_crew(git_vault)
    rr_dir = git_vault.raw / "ratingsref" / "telecast" / "2025"
    held = {name: (rr_dir / name).read_bytes() for name in (_SILVERLAKE_RR, _IRONPEAK_RR)}
    for name in held:
        (rr_dir / name).unlink()
    accepted = run_build(git_vault, reference, commit=False, accept_baseline=True)
    assert accepted.counts["join08_rate_x10000"] == 10000
    site_data = git_vault.vault / "processed" / "site-data.json"
    site_before = site_data.read_bytes()

    # RR now rates the blank-crew game: the denominator grows, no crew is lost.
    (rr_dir / _SILVERLAKE_RR).write_bytes(held[_SILVERLAKE_RR])
    explained = run_build(git_vault, reference, commit=False, accept_baseline=False)

    assert explained.blocked is False
    assert explained.reasons == ()
    assert [(d.season, d.games) for d in explained.explained] == [(2025, 1)]
    assert site_data.read_bytes() != site_before  # processed data and site data written
    gap = [r for r in _gap_rows(git_vault) if r["cfbd_game_id"] == "500006"]
    assert [(r["gap_kind"], r["override_status"]) for r in gap] == [("no-506-crew", "missing")]
    report = (git_vault.audit / "regression.csv").read_text(encoding="utf-8")
    assert "2025,match_rate,1.0,0.8571428571428571,explained" in report.splitlines()

    # A rated game with no 506 listing at all still blocks, gap or not.
    (rr_dir / _IRONPEAK_RR).write_bytes(held[_IRONPEAK_RR])
    site_before = site_data.read_bytes()
    blocked = run_build(git_vault, reference, commit=False, accept_baseline=False)

    assert blocked.blocked is True
    assert blocked.reasons == ("season 2025: match_rate 0.75 below baseline 1.0",)
    assert blocked.explained == ()
    assert site_data.read_bytes() == site_before
