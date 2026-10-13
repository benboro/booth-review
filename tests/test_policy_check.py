"""04.19 D-10: the TVRG / AA robots.txt and terms re-check and its ledger.

Every test drives a mock transport or a synthetic ledger; no request leaves
the machine. Pages are invented.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from booth_review import cli
from booth_review.cli import main
from booth_review.config import HOST_POLICIES, DataPaths
from booth_review.sources.policy import (
    POLICY_LEDGER,
    PolicyCheck,
    append_policy_check,
    crawl_delay_for,
    latest_policy_check,
    legal_link,
    policy_fresh,
    sitemap_urls,
)

_TVRG = "https://www.thetvratingsguide.com"
_AA = "https://awfulannouncing.com"
_ALLOW = b"User-agent: *\nAllow: /\n"
_HOME = b"<html><body><footer>Copyright Example</footer></body></html>"
_ARCHIVE = b"<html><body><h3>Northfield at Silverlake viewership</h3></body></html>"


def _git(vault: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(vault), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _last_commit(vault: Path) -> tuple[str, set[str]]:
    subject = _git(vault, "log", "-1", "--format=%s")
    files = set(_git(vault, "show", "--name-only", "--format=", "HEAD").splitlines())
    return subject, files


def _ledger(paths: DataPaths) -> list[dict[str, object]]:
    path = paths.vault / POLICY_LEDGER
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


@pytest.fixture
def gap_month(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the offline table build: the earliest gap month is September 2021."""
    monkeypatch.setattr(cli, "_earliest_gap_month", lambda _paths: (2021, 9))


def _tvrg_responses(robots: bytes) -> dict[str, tuple[int, bytes, dict[str, str]]]:
    return {
        f"{_TVRG}/robots.txt": (200, robots, {}),
        f"{_TVRG}/": (200, _HOME, {}),
        f"{_TVRG}/2021/09/": (200, _ARCHIVE, {}),
    }


# -- robots parsing --------------------------------------------------------------------


def test_crawl_delay_reads_our_group_before_the_wildcard() -> None:
    text = (
        "User-agent: *\nCrawl-delay: 2\n\n"
        "User-agent: booth-review\nCrawl-delay: 9\nAllow: /\n"
        "Sitemap: https://awfulannouncing.com/sitemap_index.xml\n"
    )
    assert crawl_delay_for(text) == 9.0
    assert crawl_delay_for("User-agent: *\nCrawl-delay: 2\n") == 2.0
    assert crawl_delay_for("User-agent: *\nAllow: /\n") is None
    assert crawl_delay_for("User-agent: *\nCrawl-delay: soon\n") is None
    assert sitemap_urls(text) == ["https://awfulannouncing.com/sitemap_index.xml"]


def test_legal_link_resolves_relative_hrefs() -> None:
    html = b'<footer><a href="/legal">Legal  Information</a><a href="/x">Other</a></footer>'
    assert legal_link(html, f"{_AA}/disclaimer") == f"{_AA}/legal"
    assert legal_link(b"<p>nothing</p>", f"{_AA}/disclaimer") is None


# -- tvrg ----------------------------------------------------------------------------------


def test_tvrg_policy_check_allowed_writes_a_robots_ok_line(
    git_vault, mock_transport_factory, patched_client, gap_month, capsys
) -> None:
    paths = git_vault
    handle = mock_transport_factory(_tvrg_responses(_ALLOW))
    patched_client(handle)

    assert main(["collect", "tvrg", "--policy-check"]) == 0

    assert [r.url for r in handle.requests] == [
        f"{_TVRG}/robots.txt",
        f"{_TVRG}/",
        f"{_TVRG}/2021/09/",
    ]
    assert (paths.raw / "tvrg" / "_policy" / _today() / "home.html").read_bytes() == _HOME
    assert (paths.raw / "tvrg" / "index" / "2021-09.html").read_bytes() == _ARCHIVE
    (line,) = _ledger(paths)
    assert line["source"] == "tvrg"
    assert line["robots_ok"] is True
    assert line["crawl_delay"] is None
    assert line["terms_ok"] is None
    subject, files = _last_commit(paths.vault)
    assert subject == "collect: tvrg policy (fetched 2, cached 0, not_modified 0, failed 0)"
    assert POLICY_LEDGER in files
    for name in files:
        assert name.startswith(("raw/tvrg/", "raw/_robots/", "ledger/")), name
    out = capsys.readouterr().out
    assert "robots ok" in out
    assert "http" not in out  # count-only output


def test_tvrg_policy_check_disallow_exits_4_before_any_page(
    git_vault, mock_transport_factory, patched_client, gap_month, capsys
) -> None:
    handle = mock_transport_factory(_tvrg_responses(b"User-agent: *\nDisallow: /\n"))
    patched_client(handle)

    assert main(["collect", "tvrg", "--policy-check"]) == 4

    assert [r.url for r in handle.requests] == [f"{_TVRG}/robots.txt"]
    (line,) = _ledger(git_vault)
    assert line["robots_ok"] is False
    assert line["terms_ok"] is None
    subject, _files = _last_commit(git_vault.vault)
    assert subject.startswith("collect: tvrg policy (")
    assert "PolicyRobotsError" in capsys.readouterr().err


def test_tvrg_policy_check_long_crawl_delay_exits_4(
    git_vault, mock_transport_factory, patched_client, gap_month
) -> None:
    robots = b"User-agent: *\nAllow: /\nCrawl-delay: 30\n"
    handle = mock_transport_factory(_tvrg_responses(robots))
    patched_client(handle)

    assert main(["collect", "tvrg", "--policy-check"]) == 4

    assert [r.url for r in handle.requests] == [f"{_TVRG}/robots.txt"]
    (line,) = _ledger(git_vault)
    assert line["robots_ok"] is False
    assert line["crawl_delay"] == 30.0
    assert HOST_POLICIES["www.thetvratingsguide.com"].min_interval_s < 30.0


def test_tvrg_short_crawl_delay_passes(
    git_vault, mock_transport_factory, patched_client, gap_month
) -> None:
    robots = b"User-agent: *\nAllow: /\nCrawl-delay: 2\n"
    patched_client(mock_transport_factory(_tvrg_responses(robots)))
    assert main(["collect", "tvrg", "--policy-check"]) == 0
    (line,) = _ledger(git_vault)
    assert line["robots_ok"] is True
    assert line["crawl_delay"] == 2.0


def test_same_day_rerun_judges_the_cached_robots_and_sends_nothing(
    git_vault, mock_transport_factory, patched_client, gap_month
) -> None:
    patched_client(mock_transport_factory(_tvrg_responses(_ALLOW)))
    assert main(["collect", "tvrg", "--policy-check"]) == 0

    handle = mock_transport_factory({})
    patched_client(handle)
    assert main(["collect", "tvrg", "--policy-check", "--confirm-terms"]) == 0
    assert handle.requests == []
    lines = _ledger(git_vault)
    assert [line["terms_ok"] for line in lines] == [None, True]
    assert lines[1]["checked_at"] == lines[0]["checked_at"]  # the robots read it stands on


# -- confirm-terms and freshness -----------------------------------------------------------


def test_confirm_terms_without_a_fresh_check_exits_4(git_vault, capsys) -> None:
    assert main(["collect", "aa", "--confirm-terms"]) == 4
    assert _ledger(git_vault) == []
    assert "run --policy-check first" in capsys.readouterr().err


def test_confirm_terms_after_a_check_appends_terms_ok(
    git_vault, mock_transport_factory, patched_client, gap_month
) -> None:
    patched_client(mock_transport_factory(_tvrg_responses(_ALLOW)))
    assert main(["collect", "tvrg", "--policy-check"]) == 0
    now = datetime.now(UTC)
    assert not policy_fresh(git_vault, "tvrg", now)

    assert main(["collect", "tvrg", "--confirm-terms"]) == 0

    lines = _ledger(git_vault)
    assert len(lines) == 2
    assert lines[1]["terms_ok"] is True
    assert lines[1]["robots_ok"] is True
    assert policy_fresh(git_vault, "tvrg", now)
    assert not policy_fresh(git_vault, "aa", now)
    subject, files = _last_commit(git_vault.vault)
    assert subject == "collect: tvrg policy (confirmed 1)"
    assert files == {POLICY_LEDGER}


def test_confirm_terms_refuses_a_robots_blocked_newest_line(git_vault) -> None:
    now = datetime.now(UTC)
    append_policy_check(git_vault, PolicyCheck("aa", now, True, None, None))
    append_policy_check(git_vault, PolicyCheck("aa", now, False, None, None))
    assert main(["collect", "aa", "--confirm-terms", "--no-commit"]) == 4


def _paths(tmp_path: Path) -> DataPaths:
    return DataPaths(vault=tmp_path / "vault")


def test_policy_fresh_needs_robots_and_terms_within_30_days(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    now = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
    assert not policy_fresh(paths, "tvrg", now)

    append_policy_check(paths, PolicyCheck("tvrg", now - timedelta(days=31), True, None, True))
    assert not policy_fresh(paths, "tvrg", now)

    append_policy_check(paths, PolicyCheck("tvrg", now - timedelta(days=2), True, None, None))
    assert not policy_fresh(paths, "tvrg", now)

    append_policy_check(paths, PolicyCheck("tvrg", now - timedelta(days=2), True, None, True))
    assert policy_fresh(paths, "tvrg", now)
    assert policy_fresh(paths, "tvrg", now - timedelta(days=3)) is False  # check in the future

    # A newer robots-blocked line wins over the earlier go.
    append_policy_check(paths, PolicyCheck("tvrg", now - timedelta(days=1), False, 30.0, None))
    assert not policy_fresh(paths, "tvrg", now)
    latest = latest_policy_check(paths, "tvrg")
    assert latest is not None
    assert latest.crawl_delay == 30.0


def test_no_mode_is_a_clear_error(git_vault, capsys) -> None:
    assert main(["collect", "tvrg"]) == 2
    assert "needs --season" in capsys.readouterr().err


def test_collect_paths_cover_the_policy_ledger() -> None:
    for source in ("tvrg", "aa"):
        assert f"raw/{source}" in cli._COLLECT_PATHS[source]
        assert POLICY_LEDGER in cli._COLLECT_PATHS[source]
        assert "raw/_robots" in cli._COLLECT_PATHS[source]


# -- aa ------------------------------------------------------------------------------------


_AA_ROBOTS = (
    b"User-agent: *\nDisallow: /2006/\n\nSitemap: https://awfulannouncing.com/sitemap_index.xml\n"
)
_SITEMAP = b"<?xml version='1.0'?><sitemapindex></sitemapindex>"


def test_aa_policy_check_skips_an_external_legal_page_and_samples_the_sitemap(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    disclaimer = b'<p>Disclaimer.</p><a href="https://parent.example/legal">Legal Information</a>'
    handle = mock_transport_factory(
        {
            f"{_AA}/robots.txt": (200, _AA_ROBOTS, {}),
            f"{_AA}/disclaimer": (200, disclaimer, {}),
            f"{_AA}/sitemap_index.xml": (200, _SITEMAP, {}),
        }
    )
    patched_client(handle)

    assert main(["collect", "aa", "--policy-check"]) == 0

    assert "parent.example" not in " ".join(r.url for r in handle.requests)
    assert (git_vault.raw / "aa" / "_policy" / _today() / "disclaimer.html").is_file()
    assert (git_vault.raw / "aa" / "index" / "sitemap-1.xml").read_bytes() == _SITEMAP
    out = capsys.readouterr().out
    assert "external legal page not fetched" in out
    assert "sitemaps 1" in out
    (line,) = _ledger(git_vault)
    assert line["source"] == "aa"
    assert line["robots_ok"] is True


def test_aa_policy_check_fetches_an_on_host_legal_page(
    git_vault, mock_transport_factory, patched_client
) -> None:
    disclaimer = b'<a href="/legal-information">Legal Information</a>'
    handle = mock_transport_factory(
        {
            f"{_AA}/robots.txt": (200, b"User-agent: *\nAllow: /\n", {}),
            f"{_AA}/disclaimer": (200, disclaimer, {}),
            f"{_AA}/legal-information": (200, b"<p>Terms</p>", {}),
        }
    )
    patched_client(handle)

    assert main(["collect", "aa", "--policy-check", "--confirm-terms"]) == 0

    assert (git_vault.raw / "aa" / "_policy" / _today() / "legal.html").is_file()
    (line,) = _ledger(git_vault)
    assert line["terms_ok"] is True


def test_aa_confirm_terms_is_withheld_when_a_policy_page_failed(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    handle = mock_transport_factory(
        {
            f"{_AA}/robots.txt": (200, b"User-agent: *\nAllow: /\n", {}),
            f"{_AA}/disclaimer": (404, b"nf", {}),
        }
    )
    patched_client(handle)

    assert main(["collect", "aa", "--policy-check", "--confirm-terms"]) == 4
    (line,) = _ledger(git_vault)
    assert line["robots_ok"] is True
    assert line["terms_ok"] is None
    assert "terms not confirmed" in capsys.readouterr().err
