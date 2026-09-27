"""CLI-level tests for `booth-review build` (D-12, AUDIT-01/03) and
`booth-review review` (Plans 04/05/06/09's review tools under one CLI).

Every test drives a real (throwaway, tmp_path-rooted) git vault via the
`git_vault` fixture, seeded with the same raw fixture files `build_vault`
uses (conftest.py's own fixture, not edited here) and an extended copy of
`build_reference`'s reference tables. `pytest-socket` stays enabled
(`--disable-socket`): the build/review path never builds an HTTP client, so
an accidental network call would surface as a real connection attempt.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from booth_review.build.pipeline import run_build
from booth_review.build.regression import load_baseline
from booth_review.cli import main
from booth_review.config import DataPaths

_SPIKE_FIXTURES = Path(__file__).parent / "fixtures" / "spike"
_BUILD_FIXTURES = Path(__file__).parent / "fixtures" / "build"
_REFERENCE_FIXTURES = Path(__file__).parent / "fixtures" / "reference"

_COMMIT_MESSAGE_RE = re.compile(
    r"^build: all \d{4}-\d{4} \(telecasts \d+, matched \d+, blocked [01]\)$"
)


def _seed_build_raw(paths: DataPaths) -> None:
    """The exact raw-file layout conftest.py's `build_vault` fixture seeds,
    reused here so a real `git_vault` (not `build_vault`, which isn't a real
    git working copy) gets the same 2025 build-layer input.
    """
    games_dir = paths.raw / "cfbd" / "games"
    games_dir.mkdir(parents=True, exist_ok=True)
    (games_dir / "2025.json").write_bytes((_SPIKE_FIXTURES / "cfbd_games_2025.json").read_bytes())

    for endpoint in ("lines", "rankings", "media", "wp_pregame", "teams_fbs"):
        endpoint_dir = paths.raw / "cfbd" / endpoint
        endpoint_dir.mkdir(parents=True, exist_ok=True)
        (endpoint_dir / "2025.json").write_bytes(
            (_BUILD_FIXTURES / "cfbd" / f"{endpoint}_2025.json").read_bytes()
        )

    sports506_dir = paths.raw / "sports506" / "2025"
    sports506_dir.mkdir(parents=True, exist_ok=True)
    (sports506_dir / "wk-01.html").write_bytes((_SPIKE_FIXTURES / "506_wk-01.html").read_bytes())
    (sports506_dir / "wk-B.html").write_bytes((_SPIKE_FIXTURES / "506_wk-B.html").read_bytes())

    rr_dir = paths.raw / "ratingsref" / "telecast" / "2025"
    rr_dir.mkdir(parents=True, exist_ok=True)
    for record_path in sorted((_SPIKE_FIXTURES / "rr_records").glob("*.json")):
        (rr_dir / record_path.name).write_bytes(record_path.read_bytes())

    subprocess.run(["git", "-C", str(paths.vault), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(paths.vault), "commit", "-q", "-m", "test: seed raw fixture"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(paths.vault), "push", "-q", "origin", "main"],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def build_git_vault(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> DataPaths:
    """A real git vault seeded with build_vault's 2025 raw fixture, plus an
    extended data/reference/ (ECN/ESPN rows the real spike RR/506 fixtures'
    own outlet text needs -- same extension test_build_tables.py's own
    vault_reference fixture uses).
    """
    _seed_build_raw(git_vault)

    extended = tmp_path / "reference_ext"
    shutil.copytree(_REFERENCE_FIXTURES, extended)
    with (extended / "networks.csv").open("a", encoding="utf-8", newline="") as fh:
        fh.write("ECN,ecn,Example Cable Network,family-ecn,cable,main,,,\n")
        fh.write("ECN2,ecn2,Example Cable Network 2,family-ecn,cable,main,,,\n")
        fh.write("ESPN,espn,ESPN,family-espn,cable,main,,,\n")
        fh.write("ESPN2,espn2,ESPN2,family-espn,cable,main,,,\n")
        fh.write("ESPNU,espnu,ESPNU,family-espn,cable,main,,,\n")
        fh.write("ESPN Deportes,espn-deportes,ESPN Deportes,family-espn,cable,spanish,,,\n")
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(extended))

    return git_vault


def _remote_head_subject(remote: Path) -> str:
    result = subprocess.run(
        ["git", "--git-dir", str(remote), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _remote_log_count(remote: Path) -> int:
    result = subprocess.run(
        ["git", "--git-dir", str(remote), "log", "--oneline"],
        capture_output=True,
        text=True,
        check=True,
    )
    return len(result.stdout.splitlines())


def _remote(paths: DataPaths) -> Path:
    return paths.vault.parent / "remote.git"


# -- --help ------------------------------------------------------------------------------


def test_build_help_exits_0() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["build", "--help"])
    assert exc.value.code == 0


@pytest.mark.parametrize("subcommand", ["teams", "people", "networks", "combined"])
def test_review_subcommand_help_exits_0(subcommand: str) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["review", subcommand, "--help"])
    assert exc.value.code == 0


# -- run_build: writes every table, is not blocked with no baseline -----------------------


def test_run_build_writes_every_table_and_is_not_blocked_with_no_baseline(
    build_git_vault: DataPaths,
) -> None:
    paths = build_git_vault
    from booth_review.reference import reference_dir

    outcome = run_build(paths, reference_dir(), commit=False, accept_baseline=False)

    assert outcome.blocked is False
    assert outcome.accepted is False
    for rel_path in (
        "processed/games.parquet",
        "processed/telecasts.parquet",
        "processed/viewership.parquet",
        "processed/telecast_flags.parquet",
        "processed/people.parquet",
        "processed/telecast_people.parquet",
        "processed/coverage.csv",
        "processed/coverage_publishers.csv",
        "audit/build_metrics.csv",
        "audit/regression.csv",
        "processed/site-data.json",
    ):
        assert rel_path in outcome.written, rel_path
        assert (paths.vault / rel_path).is_file(), rel_path
    assert any(p.startswith("interim/review_") for p in outcome.written)


# -- commit: exactly one count-only commit, scoped to written paths -----------------------


def test_build_cli_commits_once_with_count_only_message_scoped_to_written_paths(
    build_git_vault: DataPaths,
) -> None:
    paths = build_git_vault
    remote = _remote(paths)
    log_count_before = _remote_log_count(remote)

    unrelated = paths.vault / "interim" / "unrelated_untracked.txt"
    unrelated.write_text("not part of this build\n", encoding="utf-8")

    exit_code = main(["build"])

    assert exit_code == 0
    assert _remote_log_count(remote) == log_count_before + 1
    subject = _remote_head_subject(remote)
    assert _COMMIT_MESSAGE_RE.match(subject), subject

    status = subprocess.run(
        ["git", "-C", str(paths.vault), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "interim/unrelated_untracked.txt" in status
    assert "?? interim/unrelated_untracked.txt" in status


# -- regression guard: accept-baseline, then a real drop blocks -----------------------------


def test_accept_baseline_then_dropped_input_blocks_exit_4_and_leaves_site_data_unchanged(
    build_git_vault: DataPaths,
) -> None:
    paths = build_git_vault

    accept_exit = main(["build", "--accept-baseline"])
    assert accept_exit == 0
    assert load_baseline(paths) is not None
    site_data_path = paths.vault / "processed" / "site-data.json"
    before_bytes = site_data_path.read_bytes()

    rr_dir = paths.raw / "ratingsref" / "telecast" / "2025"
    one_record = next(iter(sorted(rr_dir.glob("*.json"))))
    one_record.unlink()

    exit_code = main(["build"])

    assert exit_code == 4
    assert site_data_path.read_bytes() == before_bytes


def test_accept_baseline_on_a_blocked_build_writes_new_baseline_and_site_data(
    build_git_vault: DataPaths,
) -> None:
    paths = build_git_vault

    assert main(["build", "--accept-baseline"]) == 0

    rr_dir = paths.raw / "ratingsref" / "telecast" / "2025"
    one_record = next(iter(sorted(rr_dir.glob("*.json"))))
    one_record.unlink()
    assert main(["build"]) == 4

    exit_code = main(["build", "--accept-baseline"])

    assert exit_code == 0
    baseline = load_baseline(paths)
    assert baseline is not None


def test_regression_reasons_name_only_season_and_metric(
    build_git_vault: DataPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = build_git_vault
    assert main(["build", "--accept-baseline"]) == 0

    rr_dir = paths.raw / "ratingsref" / "telecast" / "2025"
    one_record = next(iter(sorted(rr_dir.glob("*.json"))))
    one_record.unlink()

    capsys.readouterr()
    exit_code = main(["build"])
    out = capsys.readouterr().out

    assert exit_code == 4
    assert "2025" in out
    regression_csv = (paths.audit / "regression.csv").read_text(encoding="utf-8")
    assert "blocked" in regression_csv


# -- review: never commits, prints counts only ----------------------------------------------


def test_review_people_scan_and_apply_never_commit(build_git_vault: DataPaths) -> None:
    paths = build_git_vault
    remote = _remote(paths)
    log_count_before = _remote_log_count(remote)

    scan_exit = main(["review", "people"])
    apply_exit = main(["review", "people", "--apply"])

    assert scan_exit == 0
    assert apply_exit == 0
    assert _remote_log_count(remote) == log_count_before


def test_review_teams_never_commits(build_git_vault: DataPaths) -> None:
    remote = _remote(build_git_vault)
    log_count_before = _remote_log_count(remote)

    exit_code = main(["review", "teams"])

    assert exit_code == 0
    assert _remote_log_count(remote) == log_count_before


def test_review_networks_never_commits(build_git_vault: DataPaths) -> None:
    remote = _remote(build_git_vault)
    log_count_before = _remote_log_count(remote)

    exit_code = main(["review", "networks"])

    assert exit_code == 0
    assert _remote_log_count(remote) == log_count_before


def test_review_combined_never_commits(build_git_vault: DataPaths) -> None:
    remote = _remote(build_git_vault)
    log_count_before = _remote_log_count(remote)

    exit_code = main(["review", "combined"])

    assert exit_code == 0
    assert _remote_log_count(remote) == log_count_before


# -- no HTTP client is ever built on the build/review path -----------------------------------


def test_build_and_review_never_open_a_socket(build_git_vault: DataPaths) -> None:
    # pytest-socket (--disable-socket) is on globally; reaching this
    # assertion at all means no real connection attempt happened above.
    assert main(["build"]) in (0, 4)
    assert main(["review", "people"]) == 0


def test_cli_build_json_output_round_trips(build_git_vault: DataPaths) -> None:
    paths = build_git_vault
    main(["build", "--no-commit"])
    body = json.loads((paths.vault / "processed" / "site-data.json").read_text(encoding="utf-8"))
    assert body["schema_version"] == "1.0.0"


# -- WR-01 / WR-02: ordering and scope of a blocked or failing build ---------------------------


def test_blocked_build_leaves_processed_tables_and_coverage_untouched(
    build_git_vault: DataPaths,
) -> None:
    paths = build_git_vault
    assert main(["build", "--accept-baseline"]) == 0
    processed_before = {
        p.name: p.read_bytes() for p in sorted(paths.processed.iterdir()) if p.is_file()
    }
    assert "telecasts.parquet" in processed_before
    assert "coverage.csv" in processed_before

    rr_dir = paths.raw / "ratingsref" / "telecast" / "2025"
    next(iter(sorted(rr_dir.glob("*.json")))).unlink()

    outcome = run_build(
        paths, Path(os.environ["BOOTH_REVIEW_REFERENCE"]), commit=False, accept_baseline=False
    )

    assert outcome.blocked is True
    assert not any(p.startswith("processed/") for p in outcome.written)
    assert "audit/regression.csv" in outcome.written
    processed_after = {
        p.name: p.read_bytes() for p in sorted(paths.processed.iterdir()) if p.is_file()
    }
    assert processed_after == processed_before


def test_accept_baseline_never_writes_a_baseline_when_site_data_fails(
    build_git_vault: DataPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    from booth_review.build import pipeline
    from booth_review.errors import VaultStateError

    paths = build_git_vault

    def _fail(*_args: object, **_kwargs: object) -> None:
        raise VaultStateError("synthetic site-data failure")

    monkeypatch.setattr(pipeline, "build_site_data", _fail)

    with pytest.raises(VaultStateError):
        run_build(
            paths,
            Path(os.environ["BOOTH_REVIEW_REFERENCE"]),
            commit=False,
            accept_baseline=True,
        )

    assert load_baseline(paths) is None
    assert not (paths.processed / "telecasts.parquet").exists()


# -- WR-03: an unexpected build error prints only its type -------------------------------------


def test_unexpected_build_error_prints_only_its_type(
    build_git_vault: DataPaths,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from booth_review import cli

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise KeyError("zz-sentinel-vault-value")

    monkeypatch.setattr(cli, "run_build", _boom)
    monkeypatch.delenv("BOOTH_REVIEW_DEBUG", raising=False)

    exit_code = main(["build", "--no-commit"])

    captured = capsys.readouterr()
    assert exit_code == 3
    assert "KeyError" in captured.err
    assert "zz-sentinel-vault-value" not in captured.err + captured.out
