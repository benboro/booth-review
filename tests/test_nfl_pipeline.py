"""`booth-review nfl build` / `nfl people` on a git vault with synthetic raw/nfl files."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import polars as pl
import pytest
from nfl_join_helpers import sched_row, schedule_csv

import booth_review.nfl.pipeline as nfl_pipeline
from booth_review.cli import main
from booth_review.config import DataPaths
from booth_review.nfl.layout import NFLVERSE_SCHEDULES_PATH, nfl_506_path, nfl_rr_path

REFERENCE = Path(__file__).parent / "fixtures" / "nfl" / "reference"

PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<link rel="canonical" href="https://506sports.com/nfl.php?yr=2014&wk=1">
<title>506 Sports - NFL Maps: Week 1, 2014</title></head>
<body><div id="content"><div class="inner"><article>
<header><h2>506 Sports - NFL Maps: Week 1, 2014</h2></header>
<p><b><font size="5">CBS SINGLE</font></b></p>
<table>
<tr><td background="x.png" colspan="2" height="444" width="795"> </td></tr>
<tr><td bgcolor="#FF7F7F" width="60"> </td>
<td><strong>Hill Moles @ Pine Elks</strong> -- {crew}</td></tr>
</table>
<hr/>
</article></div></div></body></html>
"""


def _schedule(*, with_playoff: bool = False) -> bytes:
    rows = [
        sched_row(
            "2014_01_OTT_HCG",
            1,
            "2014-09-04",
            "OTT",
            "HCG",
            season="2014",
            weekday="Thursday",
            gametime="20:20",
        ),
        sched_row("2014_01_MOL_ELK", 1, "2014-09-07", "MOL", "ELK", season="2014"),
        sched_row("2014_01_LNX_HRN", 1, "2014-09-07", "LNX", "HRN", season="2014"),
    ]
    if with_playoff:
        rows.append(
            sched_row(
                "2014_20_ELK_HCG",
                20,
                "2015-01-10",
                "ELK",
                "HCG",
                season="2014",
                game_type="WC",
                weekday="Saturday",
                gametime="16:35",
            )
        )
    return schedule_csv(rows)


def _rr(paths: DataPaths, networks: list[str]) -> None:
    record = {
        "telecast": {
            "id": "tnf-1",
            "event_date": "2014-09-04",
            "teams": ["Otters", "Harbor City Gulls"],
            "networks": networks,
            "title": "Invented",
        },
        "claims": [],
    }
    path = paths.raw / nfl_rr_path(2014, "tnf-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


def _seed(paths: DataPaths, *, rr: list[str] | None, crew: str = "Ana Fixture", playoff=False):
    sched = paths.raw / NFLVERSE_SCHEDULES_PATH
    sched.parent.mkdir(parents=True, exist_ok=True)
    sched.write_bytes(_schedule(with_playoff=playoff))
    page = paths.raw / nfl_506_path(2014, 1)
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(PAGE.format(crew=crew), encoding="utf-8")
    if rr is not None:
        _rr(paths, rr)


@pytest.fixture
def vault(git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DataPaths:
    ref = tmp_path / "nfl_ref"
    shutil.copytree(REFERENCE, ref)
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(ref))
    return git_vault


def _git(paths: DataPaths, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(paths.vault), *args], check=True, capture_output=True, text=True
    ).stdout


def _tables(paths: DataPaths) -> pl.DataFrame:
    return pl.read_parquet(paths.processed / "nfl_games.parquet")


def test_build_writes_tables_and_reviews_without_commit(
    vault: DataPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(vault, rr=["NFL Network"])
    assert main(["nfl", "build", "--season", "2014", "--no-commit"]) == 0
    assert (vault.processed / "nfl_games.parquet").is_file()
    assert (vault.processed / "nfl_special_games_by_team_season.parquet").is_file()
    assert (vault.interim / "review_nfl_networks.csv").is_file()
    assert "nfl games 3" in capsys.readouterr().out
    assert not Path("data/processed/nfl_games.parquet").exists()


def test_build_commits_once_scoped_to_nfl_paths(vault: DataPaths) -> None:
    _seed(vault, rr=["NFL Network"])
    before = int(_git(vault, "rev-list", "--count", "HEAD").strip())
    assert main(["nfl", "build", "--season", "2014"]) == 0
    assert int(_git(vault, "rev-list", "--count", "HEAD").strip()) == before + 1
    files = _git(vault, "show", "--name-only", "--format=%s", "HEAD").splitlines()
    subject, paths = files[0], [f for f in files[1:] if f]
    assert subject.startswith("build: nfl 2014-2014 (games 3, standalone 1")
    assert paths
    assert all(p.startswith("processed/nfl_") or p.startswith("interim/review_nfl_") for p in paths)
    assert "raw/" not in subject


TASK1_REVIEWS = (
    "review_nfl_lead_booth.csv",
    "review_nfl_agotw_misses.csv",
    "review_nfl_lead_absent_weeks.csv",
    "review_nfl_single_header_weeks.csv",
    "review_nfl_task1_model.csv",
)


def test_build_writes_task1_table_and_reviews_in_the_same_commit(vault: DataPaths) -> None:
    _seed(vault, rr=["NFL Network"])
    before = int(_git(vault, "rev-list", "--count", "HEAD").strip())
    assert main(["nfl", "build", "--season", "2014"]) == 0
    assert int(_git(vault, "rev-list", "--count", "HEAD").strip()) == before + 1
    task1 = pl.read_parquet(vault.processed / "nfl_task1_crews.parquet")
    assert "coverage_normalized" in task1.columns and "predictors_used" in task1.columns
    files = _git(vault, "show", "--name-only", "--format=%s", "HEAD").splitlines()
    subject, paths = files[0], {f for f in files[1:] if f}
    assert "processed/nfl_task1_crews.parquet" in paths
    for name in TASK1_REVIEWS:
        assert (vault.interim / name).is_file()
        assert f"interim/{name}" in paths
    for key in (
        "seasons_close",
        "seasons_tied",
        "agotw_miss_weeks",
        "skipped_single_header_weeks",
        "ambiguous_fox_weeks",
    ):
        assert f"{key} 0" in subject
    model = (vault.interim / "review_nfl_task1_model.csv").read_text()
    assert "band" in model and "ols" in model


def test_extra_tables_hook_still_replaces_task1(vault: DataPaths) -> None:
    _seed(vault, rr=["NFL Network"])
    outcome = nfl_pipeline.run_nfl_build(
        vault,
        Path(os.environ["BOOTH_REVIEW_REFERENCE"]),
        seasons=[2014],
        include_playoffs=False,
        commit=False,
        check_acceptance=False,
        extra_tables=lambda table, ref: {"nfl_hook_probe": table.frame.head(1)},
    )
    assert "processed/nfl_hook_probe.parquet" in outcome.written
    assert "processed/nfl_task1_crews.parquet" not in outcome.written


def test_acceptance_unmatched_exits_4_and_writes_review(
    vault: DataPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(vault, rr=None)
    code = main(["nfl", "build", "--season", "2014", "--no-commit", "--check-acceptance"])
    assert code == 4
    assert "acceptance: 1 unmatched" in capsys.readouterr().out
    assert "no-rr-network" in (vault.interim / "review_nfl_acceptance.csv").read_text()


def test_acceptance_multi_network_passes(
    vault: DataPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(vault, rr=["NFL Network", "Prime Video"])
    code = main(["nfl", "build", "--season", "2014", "--no-commit", "--check-acceptance"])
    assert code == 0
    assert "acceptance: 0 unmatched (1 multi-network)" in capsys.readouterr().out


def test_override_errors_block_the_build(vault: DataPaths, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(vault, rr=["NFL Network"])
    real = nfl_pipeline.assemble_nfl_games

    def _bad(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        table = real(*args, **kwargs)  # type: ignore[arg-type]
        counts = dict(table.counts)
        counts["override_errors"] = 1
        return type(table)(table.frame, table.reviews, counts, table.through_week)

    monkeypatch.setattr(nfl_pipeline, "assemble_nfl_games", _bad)
    assert main(["nfl", "build", "--season", "2014", "--no-commit"]) == 4
    assert not (vault.processed / "nfl_games.parquet").exists()
    assert (vault.interim / "review_nfl_late_national.csv").is_file()


def test_rebuild_is_byte_identical(vault: DataPaths) -> None:
    _seed(vault, rr=["NFL Network"])
    assert main(["nfl", "build", "--season", "2014", "--no-commit"]) == 0
    first = [
        (vault.processed / n).read_bytes()
        for n in (
            "nfl_games.parquet",
            "nfl_special_games_by_team_season.parquet",
            "nfl_task1_crews.parquet",
        )
    ]
    assert main(["nfl", "build", "--season", "2014", "--no-commit"]) == 0
    second = [
        (vault.processed / n).read_bytes()
        for n in (
            "nfl_games.parquet",
            "nfl_special_games_by_team_season.parquet",
            "nfl_task1_crews.parquet",
        )
    ]
    assert first == second


def test_include_playoffs_adds_rows(vault: DataPaths) -> None:
    _seed(vault, rr=["NFL Network"], playoff=True)
    assert main(["nfl", "build", "--season", "2014", "--no-commit"]) == 0
    assert _tables(vault).height == 3
    assert main(["nfl", "build", "--season", "2014", "--no-commit", "--include-playoffs"]) == 0
    assert _tables(vault).height == 4


def test_gitignore_untouched() -> None:
    assert subprocess.run(["git", "diff", "--quiet", ".gitignore"], check=False).returncode == 0


# -- nfl people -------------------------------------------------------------------------------


def _people_csv() -> Path:
    return Path(os.environ["BOOTH_REVIEW_REFERENCE"]) / "people.csv"


def test_people_scan_writes_review_and_leaves_people_untouched(
    vault: DataPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed(vault, rr=None, crew="ANA FIXTURE, Zed Newperson")
    before = _people_csv().read_bytes()
    assert main(["nfl", "people", "--season", "2014"]) == 0
    assert _people_csv().read_bytes() == before
    review = (vault.interim / "review_nfl_people.csv").read_text().splitlines()
    assert review[0] == "raw_name,person_id,count,spelling_known,decision"
    assert any(line.startswith("ANA FIXTURE,ana-fixture,1,no,") for line in review)
    out = capsys.readouterr().out
    assert "new_persons 1" in out and "existing_matches 1" in out
    assert "Zed" not in out and "ANA" not in out


def test_build_never_overwrites_the_people_decisions_file(vault: DataPaths) -> None:
    # Regression: the build's unresolved-crew review once shared review_nfl_people.csv.
    _seed(vault, rr=None, crew="ANA FIXTURE, Zed Newperson")
    assert main(["nfl", "people", "--season", "2014"]) == 0
    review = vault.interim / "review_nfl_people.csv"
    review.write_text(review.read_text().replace(",no,", ",no,add-variant"))
    decided = review.read_bytes()
    assert main(["nfl", "build", "--season", "2014", "--no-commit"]) == 0
    assert review.read_bytes() == decided
    assert (vault.interim / "review_nfl_crew_names.csv").is_file()
    assert main(["nfl", "people", "--season", "2014"]) == 0
    assert "add-variant" in review.read_text()


def test_people_apply_registers_new_and_only_approved_variants(vault: DataPaths) -> None:
    _seed(vault, rr=None, crew="ANA FIXTURE, Zed Newperson")
    assert main(["nfl", "people", "--season", "2014"]) == 0
    review = vault.interim / "review_nfl_people.csv"
    # all blank decisions: only the new person is added, existing rows untouched
    before = _people_csv().read_text().splitlines()
    assert main(["nfl", "people", "--season", "2014", "--apply"]) == 0
    after = _people_csv().read_text().splitlines()
    assert after[: len(before)] == before and len(after) == len(before) + 1

    review.write_text(review.read_text().replace(",no,", ",no,add-variant"))
    assert main(["nfl", "people", "--season", "2014", "--apply"]) == 0
    final = _people_csv().read_text()
    assert "ANA FIXTURE" in final
    assert "bo-fixture" in final
