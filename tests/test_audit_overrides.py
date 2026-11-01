"""Tests for the crew-override release pre-flight (booth-review audit overrides)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import polars as pl
import pytest

from booth_review.audit.overrides import TELECASTS, check_overrides_exist, release_problems
from booth_review.build.crew_overrides import CREW_OVERRIDE_COLUMNS

SOURCE = "no-506-crew,outlet,Example Outlet,https://example.com/synthetic-schedule"


def _write_overrides(ref: Path, rows: list[str]) -> None:
    ref.mkdir(parents=True, exist_ok=True)
    body = "\n".join([",".join(CREW_OVERRIDE_COLUMNS), *rows]) + "\n"
    (ref / "crew_overrides.csv").write_text(body, encoding="utf-8")


def _write_telecasts(path: Path, rows: list[tuple[int, str, str, bool | None]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        rows,
        schema={
            "game_id": pl.Int64,
            "network_id": pl.Utf8,
            "feed_type": pl.Utf8,
            "plotted": pl.Boolean,
        },
        orient="row",
    ).write_parquet(path)


def _booth(game: int, network: str) -> list[str]:
    return [
        f"{game},{network},0,person-a,pbp,{SOURCE}",
        f"{game},{network},1,person-b,analyst,{SOURCE}",
    ]


def test_all_plotted_passes(tmp_path: Path) -> None:
    _write_overrides(tmp_path / "ref", _booth(1, "net-a"))
    _write_telecasts(tmp_path / "telecasts.parquet", [(1, "net-a", "main", True)])
    result = check_overrides_exist(tmp_path / "ref", tmp_path / "telecasts.parquet")
    assert result.telecasts == 1
    assert result.missing_lines == ()


def test_missing_and_alt_only_telecasts_are_flagged_by_first_line(
    tmp_path: Path,
) -> None:
    rows = _booth(1, "net-a") + _booth(3, "net-b") + _booth(9, "net-a")
    _write_overrides(tmp_path / "ref", rows)
    _write_telecasts(
        tmp_path / "telecasts.parquet",
        [
            (1, "net-a", "main", True),
            (3, "net-b", "alt", True),  # exists only as an alt feed
        ],
    )
    result = check_overrides_exist(tmp_path / "ref", tmp_path / "telecasts.parquet")
    assert result.telecasts == 3
    # Header is line 1, so telecast 3 starts on line 4, game 9 on line 6.
    assert result.missing_lines == (4, 6)


def test_unrated_and_null_plotted_main_telecasts_pass(tmp_path: Path) -> None:
    rows = _booth(1, "net-a") + _booth(2, "net-a") + _booth(4, "net-a")
    _write_overrides(tmp_path / "ref", rows)
    _write_telecasts(
        tmp_path / "telecasts.parquet",
        [
            (1, "net-a", "main", True),
            (2, "net-a", "main", False),
            (4, "net-a", "main", None),
        ],
    )
    result = check_overrides_exist(tmp_path / "ref", tmp_path / "telecasts.parquet")
    assert result.telecasts == 3
    assert result.missing_lines == ()


def test_wrong_network_is_flagged(tmp_path: Path) -> None:
    _write_overrides(tmp_path / "ref", _booth(1, "net-b"))
    _write_telecasts(tmp_path / "telecasts.parquet", [(1, "net-a", "main", True)])
    result = check_overrides_exist(tmp_path / "ref", tmp_path / "telecasts.parquet")
    assert result.missing_lines == (2,)


def test_missing_telecasts_table_raises(tmp_path: Path) -> None:
    _write_overrides(tmp_path / "ref", _booth(1, "net-a"))
    with pytest.raises(FileNotFoundError):
        check_overrides_exist(tmp_path / "ref", tmp_path / "telecasts.parquet")


def _cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str]:
    from booth_review.cli import main

    monkeypatch.setenv("BOOTH_REVIEW_VAULT", str(tmp_path / "vault"))
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(tmp_path / "ref"))
    code = main(["audit", "overrides"])
    return code, capsys.readouterr().out


def test_cli_exit_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_overrides(tmp_path / "ref", _booth(1, "net-a") + _booth(2, "net-a"))
    table = tmp_path / "vault" / "processed" / "telecasts.parquet"

    code, out = _cli(tmp_path, monkeypatch, capsys)
    assert code == 2
    assert "no telecasts.parquet" in out

    _write_telecasts(table, [(1, "net-a", "main", True), (2, "net-a", "main", True)])
    code, out = _cli(tmp_path, monkeypatch, capsys)
    assert code == 0
    assert "2 telecasts checked, 0 missing" in out

    _write_telecasts(table, [(1, "net-a", "main", True), (2, "net-a", "alt", True)])
    code, out = _cli(tmp_path, monkeypatch, capsys)
    assert code == 1
    assert "line(s) 4 name a telecast" in out
    # Count-only: no cell of the CSV is echoed.
    assert "person-a" not in out and "example.com" not in out


# -- release mode -----------------------------------------------------------------


def _g(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def synced(tmp_path: Path, isolated_git_env: None) -> tuple[Path, Path, Path]:
    """A bare origin and a vault clone with a committed, pushed telecasts table,
    plus a reference directory whose one override targets a plotted telecast."""
    origin = tmp_path / "origin.git"
    vault = tmp_path / "vault"
    _g(tmp_path, "init", "--bare", "-q", "-b", "main", str(origin))
    _g(tmp_path, "clone", "-q", str(origin), str(vault))
    _g(vault, "config", "user.name", "Test Bot")
    _g(vault, "config", "user.email", "bot@example.com")
    _g(vault, "checkout", "-q", "-b", "main")
    _write_telecasts(vault / TELECASTS, [(1, "net-a", "main", True), (2, "net-a", "main", False)])
    _g(vault, "add", str(TELECASTS))
    _g(vault, "commit", "-q", "-m", "build")
    _g(vault, "push", "-q", "-u", "origin", "main")
    ref = tmp_path / "ref"
    _write_overrides(ref, _booth(1, "net-a"))
    return origin, vault, ref


def test_release_synced_vault_passes(synced: tuple[Path, Path, Path]) -> None:
    _, vault, ref = synced
    assert release_problems(vault, ref) == []


def test_release_refuses_vault_behind_origin(
    synced: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    origin, vault, ref = synced
    other = tmp_path / "other"
    _g(tmp_path, "clone", "-q", str(origin), str(other))
    _g(other, "config", "user.name", "Other")
    _g(other, "config", "user.email", "o@example.com")
    (other / "note.txt").write_text("x", encoding="utf-8")
    _g(other, "add", "note.txt")
    _g(other, "commit", "-q", "-m", "job run")
    _g(other, "push", "-q", "origin", "main")
    assert any("differs from its origin" in p for p in release_problems(vault, ref))


def test_release_refuses_locally_rebuilt_telecasts(synced: tuple[Path, Path, Path]) -> None:
    # A local `build --no-commit` rewrote the table: plotted now, not in the commit.
    _, vault, ref = synced
    _write_telecasts(vault / TELECASTS, [(1, "net-a", "main", True), (2, "net-a", "main", True)])
    problems = release_problems(vault, ref)
    assert any("differs from its last commit" in p for p in problems)


def test_release_refuses_untracked_telecasts(synced: tuple[Path, Path, Path]) -> None:
    _, vault, ref = synced
    _g(vault, "rm", "-q", "--cached", str(TELECASTS))
    _g(vault, "commit", "-q", "-m", "untrack")
    _g(vault, "push", "-q", "origin", "main")
    assert any("not committed" in p for p in release_problems(vault, ref))


def test_release_refuses_missing_overrides_file(synced: tuple[Path, Path, Path]) -> None:
    _, vault, ref = synced
    (ref / "crew_overrides.csv").unlink()
    assert any("crew_overrides.csv is missing" in p for p in release_problems(vault, ref))


def test_release_refuses_branch_without_upstream(synced: tuple[Path, Path, Path]) -> None:
    _, vault, ref = synced
    _g(vault, "checkout", "-q", "-b", "local-only")
    assert release_problems(vault, ref) == ["the vault branch has no upstream"]


def test_cli_release_uses_explicit_paths_over_env(
    synced: tuple[Path, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from booth_review.cli import main

    _, vault, ref = synced
    monkeypatch.setenv("BOOTH_REVIEW_VAULT", str(tmp_path / "nowhere"))
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(tmp_path / "nowhere"))
    args = ["audit", "overrides", "--release", "--vault", str(vault), "--reference", str(ref)]
    assert main(args) == 0
    assert "1 telecasts checked, 0 missing" in capsys.readouterr().out

    _write_overrides(ref, _booth(1, "net-a") + _booth(9, "net-a"))
    assert main(args) == 1
    assert "line(s) 4 name a telecast" in capsys.readouterr().out


def test_cli_release_needs_both_paths(capsys: pytest.CaptureFixture[str]) -> None:
    from booth_review.cli import main

    assert main(["audit", "overrides", "--release"]) == 2
    assert "needs --vault and --reference" in capsys.readouterr().out


def test_cli_headerless_csv_echoes_no_cell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from booth_review.cli import main

    ref = tmp_path / "ref"
    ref.mkdir()
    # No header: the loader's header-mismatch message would quote this data row.
    (ref / "crew_overrides.csv").write_text(_booth(1, "net-a")[0] + "\n", encoding="utf-8")
    _write_telecasts(tmp_path / "vault" / TELECASTS, [(1, "net-a", "main", True)])
    monkeypatch.setenv("BOOTH_REVIEW_VAULT", str(tmp_path / "vault"))
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(ref))
    assert main(["audit", "overrides"]) == 1
    captured = capsys.readouterr()
    assert "could not be read" in captured.out
    for cell in ("person-a", "net-a", "example.com", "Example Outlet"):
        assert cell not in captured.out + captured.err
