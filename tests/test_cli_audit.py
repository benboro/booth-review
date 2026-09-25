"""CLI-level tests for `booth-review audit completeness` and `booth-review freeze`.

Every test drives `cli.main(argv)` against a real (throwaway, tmp_path-rooted)
git vault via the `git_vault` fixture. Neither command ever builds a
PoliteClient (vault-only), so no `patched_client`/`mock_transport_factory`
wiring is needed here -- an accidental network call would surface as a real
connection attempt, blocked by pytest-socket (`--disable-socket`).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from booth_review.audit.completeness import CFBD_SEASON_ENDPOINTS
from booth_review.cli import main
from booth_review.config import DataPaths
from booth_review.errors import FrozenSeasonError
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient
from booth_review.transport.types import FetchRequest

FIXTURES = Path(__file__).parent / "fixtures" / "sports506"
_WEEK_TEMPLATE = (FIXTURES / "week_synthetic.html").read_bytes()


def _page(season: int, label: str, *, nav_labels: list[str]) -> bytes:
    text = _WEEK_TEMPLATE.decode("utf-8")
    text = text.replace("yr=2025&wk=5", f"yr={season}&wk={label}")
    text = text.replace("Week 5, 2025", f"Week {label}, {season}")
    anchors = "".join(
        f'<a href="ncaaf.php?yr={season}&wk={nav_label}">wk {nav_label}</a>'
        for nav_label in nav_labels
    )
    text = text.replace("<body>", f"<body><nav>{anchors}</nav>", 1)
    return text.encode("utf-8")


def _slug(season: int) -> str:
    return f"cfb-alpha-vs-beta-{season}-09-06"


def _seed_complete_season(paths: DataPaths, season: int) -> None:
    label = "0"
    (paths.raw / "sports506" / str(season)).mkdir(parents=True, exist_ok=True)
    (paths.raw / "sports506" / str(season) / f"wk-{label.zfill(2)}.html").write_bytes(
        _page(season, label, nav_labels=[label])
    )
    for name in CFBD_SEASON_ENDPOINTS:
        endpoint_path = paths.raw / "cfbd" / name / f"{season}.json"
        endpoint_path.parent.mkdir(parents=True, exist_ok=True)
        endpoint_path.write_text(json.dumps([{"id": 1}]), encoding="utf-8")

    slug = _slug(season)
    sitemap_path = paths.raw / "ratingsref" / "sitemap" / "2026-09-25.xml"
    sitemap_path.parent.mkdir(parents=True, exist_ok=True)
    sitemap_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>https://ratingsreference.com/telecast/{slug}</loc>"
        f"<lastmod>2026-01-01</lastmod></url>"
        "</urlset>",
        encoding="utf-8",
    )

    record_path = paths.raw / "ratingsref" / "telecast" / str(season) / f"{slug}.json"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text("{}", encoding="utf-8")
    paths.rr_lastmod.write_text(
        json.dumps(
            {
                slug: {
                    "lastmod": "2026-01-01",
                    "fetched_at": "2026-01-01T00:00:00Z",
                    "record_url": "x",
                }
            }
        ),
        encoding="utf-8",
    )


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


# -- --help --------------------------------------------------------------------------------


def test_audit_completeness_help_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["audit", "completeness", "--help"])
    assert exc.value.code == 0


def test_freeze_help_exits_0_and_lists_flags(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["freeze", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--waive" in out
    assert "--dry-run" in out
    assert "--no-commit" in out


# -- audit completeness -----------------------------------------------------------------------


def test_audit_completeness_cli_incomplete_season_prints_per_source_status_exits_4(
    git_vault: DataPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["audit", "completeness", "--season", "2025", "--no-commit"])

    assert exit_code == 4
    out = capsys.readouterr().out
    # No RR sitemap is cached at all, so the RR cell lists zero telecasts,
    # which is incomplete rather than vacuously complete.
    assert "season 2025: sports506=incomplete cfbd=incomplete ratingsref=incomplete" in out


def test_audit_completeness_cli_complete_season_exits_0_and_commits(
    git_vault: DataPaths,
) -> None:
    paths = git_vault
    _seed_complete_season(paths, 2025)
    remote = paths.vault.parent / "remote.git"

    exit_code = main(["audit", "completeness", "--season", "2025"])

    assert exit_code == 0
    assert (paths.audit / "completeness.json").is_file()
    assert (paths.audit / "completeness.md").is_file()
    assert (
        _remote_head_subject(remote) == "audit: completeness 2025-2025 (complete 1, incomplete 0)"
    )


def test_audit_completeness_cli_no_commit_writes_files_but_does_not_commit(
    git_vault: DataPaths,
) -> None:
    paths = git_vault
    remote = paths.vault.parent / "remote.git"
    log_count = _remote_log_count(remote)

    main(["audit", "completeness", "--season", "2025", "--no-commit"])

    assert (paths.audit / "completeness.json").is_file()
    assert _remote_log_count(remote) == log_count


# -- freeze -------------------------------------------------------------------------------


def test_freeze_cli_dry_run_writes_nothing_and_prints(git_vault: DataPaths) -> None:
    paths = git_vault
    _seed_complete_season(paths, 2020)

    exit_code = main(["freeze", "--season", "2020", "--dry-run"])

    assert exit_code == 0
    assert not (paths.audit / "completeness.json").exists()
    frozen = json.loads(paths.frozen.read_text(encoding="utf-8"))
    assert frozen == {"sports506": [], "ratingsref": [], "cfbd": []}


def test_freeze_cli_refusal_prints_reasons_and_exits_4(
    git_vault: DataPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    # No data seeded for 2020 at all: every cell incomplete, no waivers given.
    exit_code = main(["freeze", "--season", "2020"])

    assert exit_code == 4
    err = capsys.readouterr().err
    assert "freeze refused:" in err
    assert "2020:sports506" in err


def test_freeze_cli_success_commits_with_count_only_message(git_vault: DataPaths) -> None:
    paths = git_vault
    _seed_complete_season(paths, 2020)
    remote = paths.vault.parent / "remote.git"

    exit_code = main(["freeze", "--season", "2020"])

    assert exit_code == 0
    frozen = json.loads(paths.frozen.read_text(encoding="utf-8"))
    assert frozen["sports506"] == [2020]
    assert _remote_head_subject(remote) == "freeze: all 2020-2020 (seasons 1, waived 0)"


def test_freeze_cli_waive_flag_allows_incomplete_cell(git_vault: DataPaths) -> None:
    paths = git_vault
    _seed_complete_season(paths, 2020)
    slug = _slug(2020)
    (paths.raw / "ratingsref" / "telecast" / "2020" / f"{slug}.json").unlink()

    exit_code = main(["freeze", "--season", "2020", "--waive", "2020:ratingsref"])

    assert exit_code == 0
    frozen = json.loads(paths.frozen.read_text(encoding="utf-8"))
    assert frozen["ratingsref"] == [2020]


def test_freeze_cli_waive_unknown_source_is_argparse_error(git_vault: DataPaths) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["freeze", "--season", "2020", "--waive", "2020:bogus"])
    assert exc.value.code == 2


def test_freeze_cli_waive_malformed_is_argparse_error(git_vault: DataPaths) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["freeze", "--season", "2020", "--waive", "not-a-waiver"])
    assert exc.value.code == 2


# -- post-freeze: FrozenSeasonError through RawCache (via the CLI) ----------------------------


def test_freeze_cli_then_uncached_sports506_request_raises_frozen_season_error(
    git_vault: DataPaths, mock_transport_factory
) -> None:
    paths = git_vault
    _seed_complete_season(paths, 2020)

    exit_code = main(["freeze", "--season", "2020"])
    assert exit_code == 0

    handle = mock_transport_factory({})
    client = PoliteClient(transport=handle.transport, clock=lambda: 0.0, sleep=lambda _s: None)
    cache = RawCache(paths, client)
    req = FetchRequest(
        source="sports506",
        season=2020,
        url="https://506sports.com/ncaaf.php?yr=2020&wk=9",
        cache_path="sports506/2020/wk-09.html",
    )

    with pytest.raises(FrozenSeasonError):
        cache.get_or_fetch(req)
    assert handle.requests == []
