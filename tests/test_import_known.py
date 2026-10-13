"""Offline tests for `booth-review import known` (04.19 D-02, D-10), synthetic data only.

The cached posts are the invented fixtures under tests/fixtures/tvrg,
tests/fixtures/aa and tests/fixtures/espnpr; nothing is fetched.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from booth_review.cli import main
from booth_review.config import DataPaths

_FIXTURES = Path(__file__).parent / "fixtures"
TVRG_SLUG = "2022-10-saturday-cable-ratings-10122-invented"
AA_SLUG = "silverlake-northfield-week-5-fox-cfb-ratings"
ESPNPR_SLUG = "synthetic-saturday-viewership-grows-on-espn-networks"
HEADER = "chart_file,row,explanation\n"


def _cache_posts(paths: DataPaths) -> None:
    tvrg = paths.raw / "tvrg" / "2022" / "posts"
    tvrg.mkdir(parents=True)
    (tvrg / f"{TVRG_SLUG}.html").write_bytes(
        (_FIXTURES / "tvrg" / "post_synthetic.html").read_bytes()
    )
    aa = paths.raw / "aa" / "2022" / "posts"
    aa.mkdir(parents=True)
    (aa / f"{AA_SLUG}.html").write_bytes((_FIXTURES / "aa" / "post_synthetic.html").read_bytes())


def _csv(tmp_path: Path, body: str, name: str = "known_disagreements.csv") -> Path:
    path = tmp_path / "incoming" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def _remote_head(paths: DataPaths) -> tuple[str, list[str]]:
    git = ["git", "--git-dir", str(paths.vault.parent / "remote.git")]
    subject = subprocess.run(
        [*git, "log", "-1", "--format=%s"], capture_output=True, text=True, check=True
    ).stdout.strip()
    touched = subprocess.run(
        [*git, "show", "--name-only", "--format=", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return subject, touched


def _manifest(paths: DataPaths) -> list[dict]:
    if not paths.manifest.is_file():
        return []
    return [json.loads(x) for x in paths.manifest.read_text(encoding="utf-8").splitlines()]


def test_imports_a_valid_file_with_a_scoped_count_only_commit(git_vault, tmp_path) -> None:
    paths = git_vault
    _cache_posts(paths)
    src = _csv(tmp_path, f"{TVRG_SLUG},1,TVRG prints an earlier fast-national figure\n")

    argv = ["import", "known", "--source", "tvrg", "--season", "2022", "--from", str(src)]
    assert main(argv) == 0

    dest = paths.raw / "tvrg" / "2022" / "known_disagreements.csv"
    assert dest.read_bytes() == src.read_bytes()
    subject, touched = _remote_head(paths)
    assert subject == "import: tvrg 2022 (imported 1, skipped 0)"
    # The cached post stays untracked: the commit names only its own paths.
    assert sorted(touched) == ["ledger/requests.jsonl", "raw/tvrg/2022/known_disagreements.csv"]
    (entry,) = _manifest(paths)
    assert entry["origin"] == "manual"
    assert entry["path"] == "tvrg/2022/known_disagreements.csv"
    assert entry["source"] == "tvrg"
    assert entry["season"] == 2022

    # Rerun with the same file: skipped, nothing new written.
    assert main([*argv, "--no-commit"]) == 0
    assert len(_manifest(paths)) == 1


def test_aa_file_imports_too(git_vault, tmp_path) -> None:
    _cache_posts(git_vault)
    src = _csv(tmp_path, f"{AA_SLUG},1,AA rounds the network figure\n")
    argv = ["import", "known", "--source", "aa", "--season", "2022", "--from", str(src)]
    assert main([*argv, "--no-commit"]) == 0
    assert (git_vault.raw / "aa" / "2022" / "known_disagreements.csv").is_file()


@pytest.mark.parametrize(
    "body",
    [
        f"{TVRG_SLUG},x,not a line number\n",
        f"{TVRG_SLUG},0,zero is not a line\n",
        f"{TVRG_SLUG},1,\n",
        f"{TVRG_SLUG},1,{'y' * 201}\n",
        "Not A Slug.png,1,bad slug\n",
        f"{TVRG_SLUG},1,first\n{TVRG_SLUG},1,duplicate\n",
        f"{TVRG_SLUG},99,no such row in the cached post\n",
        f"{TVRG_SLUG},2,line 2 is a blank row, not a parsed row\n",
        "2022-10-another-post,1,no such cached post\n",
    ],
)
def test_invalid_file_exits_4_and_writes_nothing(git_vault, tmp_path, capsys, body: str) -> None:
    _cache_posts(git_vault)
    src = _csv(tmp_path, body)
    argv = ["import", "known", "--source", "tvrg", "--season", "2022", "--from", str(src)]
    assert main(argv) == 4
    out = capsys.readouterr().out
    assert "problems 1" in out
    assert "no such" not in out and "first" not in out  # no cell text in output
    assert not (git_vault.raw / "tvrg" / "2022" / "known_disagreements.csv").exists()
    assert _manifest(git_vault) == []


def test_an_unreadable_cached_post_still_refuses_the_import(git_vault, tmp_path, capsys) -> None:
    # The build skips such a post (CR-01); the import stays strict.
    _cache_posts(git_vault)
    bad = git_vault.raw / "tvrg" / "2022" / "posts" / "2022-10-unreadable.html"
    bad.write_text("<html><body>SENTINEL</body></html>", encoding="utf-8")
    src = _csv(tmp_path, f"{TVRG_SLUG},1,TVRG prints an earlier fast-national figure\n")
    argv = ["import", "known", "--source", "tvrg", "--season", "2022", "--from", str(src)]
    assert main([*argv, "--no-commit"]) == 4
    captured = capsys.readouterr()
    assert "problems 1" in captured.out
    assert "SENTINEL" not in captured.out + captured.err
    assert not (git_vault.raw / "tvrg" / "2022" / "known_disagreements.csv").exists()


def test_changed_file_needs_force(git_vault, tmp_path) -> None:
    _cache_posts(git_vault)
    first = _csv(tmp_path, f"{TVRG_SLUG},1,first explanation\n")
    base = ["import", "known", "--source", "tvrg", "--season", "2022", "--no-commit"]
    assert main([*base, "--from", str(first)]) == 0
    second = _csv(tmp_path, f"{TVRG_SLUG},1,second explanation\n", name="other.csv")
    assert main([*base, "--from", str(second)]) == 4
    dest = git_vault.raw / "tvrg" / "2022" / "known_disagreements.csv"
    assert dest.read_bytes() == first.read_bytes()
    assert main([*base, "--from", str(second), "--force"]) == 0
    assert dest.read_bytes() == second.read_bytes()


def test_season_outside_wave_b_is_refused(git_vault, tmp_path) -> None:
    _cache_posts(git_vault)
    src = _csv(tmp_path, f"{TVRG_SLUG},1,why\n")
    argv = ["import", "known", "--source", "tvrg", "--season", "2025", "--from", str(src)]
    assert main([*argv, "--no-commit"]) == 4


def test_espnpr_file_validates_against_the_imported_ratings_releases(git_vault, tmp_path) -> None:
    ratings = git_vault.raw / "espnpr" / "2022" / "ratings"
    ratings.mkdir(parents=True)
    (ratings / f"{ESPNPR_SLUG}.html").write_bytes(
        (_FIXTURES / "espnpr" / "ratings_synthetic.html").read_bytes()
    )
    base = ["import", "known", "--source", "espnpr", "--season", "2022", "--no-commit"]
    bad = _csv(tmp_path, f"{ESPNPR_SLUG},99,no such row\n", name="bad.csv")
    assert main([*base, "--from", str(bad)]) == 4
    src = _csv(tmp_path, f"{ESPNPR_SLUG},4,ESPN rounds to 0.1M\n")
    assert main([*base, "--from", str(src)]) == 0
    dest = git_vault.raw / "espnpr" / "2022" / "known_disagreements.csv"
    assert dest.read_bytes() == src.read_bytes()


@pytest.mark.parametrize("source", ["smw", "other"])
def test_other_sources_are_rejected(git_vault, tmp_path, source: str) -> None:
    src = _csv(tmp_path, "week5cfb.png,1,why\n")
    with pytest.raises(SystemExit) as exc:
        main(["import", "known", "--source", source, "--season", "2022", "--from", str(src)])
    assert exc.value.code == 2


def test_missing_from_file_exits_4(git_vault, tmp_path) -> None:
    missing = tmp_path / "nope.csv"
    argv = ["import", "known", "--source", "aa", "--season", "2022", "--from", str(missing)]
    assert main([*argv, "--no-commit"]) == 4
