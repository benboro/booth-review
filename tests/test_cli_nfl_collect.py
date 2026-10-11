"""Offline CLI tests for the NFL collection commands (plan 999.4-07).

Each test drives `cli.main(argv)` against a throwaway git vault and a mock
transport, so no request leaves the machine. Pages and records are synthetic.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from booth_review import cli
from booth_review.cli import main
from booth_review.seasons import season_of
from booth_review.sources.ratingsref.collector import SITEMAP_URL

_FIX = Path(__file__).parent / "fixtures" / "nfl"
_NFL_PAGE_2014 = (_FIX / "sports506" / "nfl_2014_wk03_synthetic.html").read_bytes()
_CFB_PAGE = (Path(__file__).parent / "fixtures" / "sports506" / "week_synthetic.html").read_bytes()

_RR_ROBOTS = "https://ratingsreference.com/robots.txt"
_GH_ROBOTS = {
    "https://api.github.com/robots.txt": (404, b"nf", {}),
    "https://raw.githubusercontent.com/robots.txt": (404, b"nf", {}),
    "https://release-assets.githubusercontent.com/robots.txt": (404, b"nf", {}),
}
_API = "https://api.github.com/repos/nflverse/nflverse-data"
_SCHEDULES = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"


def _git(vault: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(vault), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _last_commit(vault: Path) -> tuple[str, set[str]]:
    subject = _git(vault, "log", "-1", "--format=%s")
    files = set(_git(vault, "show", "--name-only", "--format=", "HEAD").splitlines())
    return subject, files


def _commit_count(vault: Path) -> int:
    return int(_git(vault, "rev-list", "--count", "HEAD"))


def _sitemap(entries: list[tuple[str, str]]) -> bytes:
    urls = "".join(
        f"<url><loc>https://ratingsreference.com/telecast/{slug}</loc>"
        f"<lastmod>{lm}</lastmod></url>\n"
        for slug, lm in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}</urlset>\n"
    ).encode()


def _rr_url(slug: str) -> str:
    return f"https://ratingsreference.com/api/telecast/{slug}.json"


_LM = "2026-01-01T00:00:00+00:00"
_NFL_SLUG = "nfl-aa-bb-2015-10-04"
_CFB_SLUG = "cfb-cc-dd-2015-10-03"


# -- ratingsref ----------------------------------------------------------------------


def test_collect_ratingsref_nfl_fetches_only_nfl_and_commits_scoped_paths(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    paths = git_vault
    handle = mock_transport_factory(
        {
            _RR_ROBOTS: (404, b"nf", {}),
            SITEMAP_URL: (
                200,
                _sitemap([(_NFL_SLUG, _LM), (_CFB_SLUG, _LM)]),
                {},
            ),
            _rr_url(_NFL_SLUG): (200, json.dumps({"telecast": {"id": _NFL_SLUG}}).encode(), {}),
        }
    )
    patched_client(handle)

    assert main(["collect", "ratingsref", "--league", "nfl", "--season", "2015"]) == 0

    assert all(_CFB_SLUG not in r.url for r in handle.requests)
    assert (paths.raw / "nfl/ratingsref/telecast/2015" / f"{_NFL_SLUG}.json").is_file()
    subject, files = _last_commit(paths.vault)
    assert subject.startswith("collect: nfl_ratingsref ")
    assert "fetched" in subject
    assert _NFL_SLUG not in subject
    assert files
    for name in files:
        assert name.startswith(
            ("raw/nfl/ratingsref/", "raw/ratingsref/sitemap/", "raw/_robots/", "ledger/")
        ), name


def test_collect_ratingsref_default_league_is_cfb(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    handle = mock_transport_factory({})
    patched_client(handle)
    assert main(["collect", "ratingsref", "--season", "2025", "--dry-run"]) == 0
    # a dry run reads only the cache: nothing is requested, and the CFB path is used
    assert handle.requests == []


def test_collect_ratingsref_nfl_rejects_sitemap_only(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    handle = mock_transport_factory({})
    patched_client(handle)
    code = main(["collect", "ratingsref", "--league", "nfl", "--season", "2015", "--sitemap-only"])
    assert code == 3
    assert handle.requests == []
    assert "--sitemap-only" in capsys.readouterr().err


def test_refresh_nfl_without_nfl_lastmod_exits_nonzero_with_backfill_hint(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    paths = git_vault
    paths.rr_lastmod.write_text(
        json.dumps(
            {_CFB_SLUG: {"lastmod": _LM, "fetched_at": "2025-12-01T00:00:00Z", "record_url": ""}}
        ),
        encoding="utf-8",
    )
    handle = mock_transport_factory({})
    patched_client(handle)
    code = main(["refresh", "ratingsref", "--league", "nfl"])
    assert code == 3
    assert handle.requests == []
    assert "--league nfl" in capsys.readouterr().err


def test_refresh_nfl_defaults_to_cap_40_and_cfb_to_100(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, int]] = []

    class _Stop(Exception):
        pass

    def fake_refresh(self, *, current_season, cap, dry_run):  # type: ignore[no-untyped-def]
        seen.append((self._league, cap))
        raise _Stop

    monkeypatch.setattr(cli.RatingsRefCollector, "refresh", fake_refresh)
    monkeypatch.setattr(cli, "build_runtime", _fake_runtime)
    for argv in (["refresh", "ratingsref"], ["refresh", "ratingsref", "--league", "nfl"]):
        with pytest.raises(_Stop):
            main([*argv, "--dry-run"])
    assert seen == [("cfb", 100), ("nfl", 40)]
    with pytest.raises(_Stop):
        main(["refresh", "ratingsref", "--league", "nfl", "--cap", "7", "--dry-run"])
    assert seen[-1] == ("nfl", 7)


def _fake_runtime(*, with_budget: bool = False, **_: object):  # type: ignore[no-untyped-def]
    import types

    class _Client:
        def close(self) -> None:
            return None

    return types.SimpleNamespace(
        cache=types.SimpleNamespace(counters={}),
        paths=None,
        vault=types.SimpleNamespace(lock=lambda: None),
        client=_Client(),
    )


def test_refresh_commit_paths_for_cfb_are_the_original_set() -> None:
    assert set(cli._COLLECT_PATHS["ratingsref"]) == {
        "raw/ratingsref",
        "raw/_robots",
        "ledger/requests.jsonl",
        "ledger/rr_lastmod.json",
        "ledger/rr_lastmod.jsonl",
    }


def test_nfl_collect_path_entries() -> None:
    assert "raw/nfl/ratingsref" in cli._COLLECT_PATHS["nfl_ratingsref"]
    assert cli._COLLECT_PATHS["nfl_sports506"] == ("raw/nfl/sports506", "ledger/requests.jsonl")
    assert "raw/nfl/nflverse" in cli._COLLECT_PATHS["nfl_nflverse"]
    assert "raw/nfl/wikipedia" in cli._COLLECT_PATHS["nfl_wikipedia"]


# -- import 506 ----------------------------------------------------------------------


def test_import_506_nfl_sends_no_requests_and_commits_nfl_paths(
    git_vault, mock_transport_factory, patched_client, tmp_path
) -> None:
    paths = git_vault
    folder = tmp_path / "saved"
    folder.mkdir()
    (folder / "page.html").write_bytes(_NFL_PAGE_2014)
    handle = mock_transport_factory({})
    patched_client(handle)

    code = main(["import", "506", "--league", "nfl", "--season", "2014", "--from", str(folder)])

    assert handle.requests == []
    assert code in (0, 4)  # 4: other weeks of the season are still missing
    assert (paths.raw / "nfl/sports506/2014/wk-03.html").is_file()
    subject, files = _last_commit(paths.vault)
    assert subject.startswith("import: nfl_sports506 2014")
    for name in files:
        assert name.startswith("raw/nfl/sports506/") or name == "ledger/requests.jsonl", name


def test_import_506_cfb_warns_about_legacy_root_pages(
    git_vault, mock_transport_factory, patched_client, tmp_path, monkeypatch, capsys
) -> None:
    root = tmp_path / "data" / "incoming" / "506"
    root.mkdir(parents=True)
    (root / "w5.html").write_bytes(_CFB_PAGE)
    handle = mock_transport_factory({})
    patched_client(handle)

    main(["import", "506", "--season", "2025", "--no-commit"])

    out = capsys.readouterr().out
    assert "warning: 1 page(s) imported from data/incoming/506/" in out
    assert "data/incoming/506/cfb/" in out
    assert handle.requests == []


def test_import_506_cfb_without_root_pages_prints_no_warning(
    git_vault, mock_transport_factory, patched_client, tmp_path, capsys
) -> None:
    handle = mock_transport_factory({})
    patched_client(handle)
    main(["import", "506", "--season", "2025", "--no-commit"])
    assert "warning:" not in capsys.readouterr().out


# -- nflverse ------------------------------------------------------------------------


def _pq(n: int = 40) -> bytes:
    return b"PAR1" + b"x" * (n - 8) + b"PAR1"


def _nflverse_responses() -> dict:
    asset_url = f"{_API}/releases/assets/910001"
    listing = json.dumps(
        [
            {
                "id": 910001,
                "name": "play_by_play_2014.parquet",
                "size": 40,
                "updated_at": "2026-01-02T00:00:00Z",
            }
        ]
    ).encode()
    return {
        **_GH_ROBOTS,
        _SCHEDULES: (200, (_FIX / "nflverse" / "games_synthetic.csv").read_bytes(), {}),
        f"{_API}/releases/tags/pbp": (
            200,
            (_FIX / "nflverse" / "release_pbp_synthetic.json").read_bytes(),
            {},
        ),
        f"{_API}/releases/900001/assets?per_page=100&page=1": (200, listing, {}),
        asset_url: (
            302,
            b"",
            {"Location": "https://release-assets.githubusercontent.com/signed/abc?sig=1"},
        ),
        "https://release-assets.githubusercontent.com/signed/abc?sig=1": (200, _pq(), {}),
    }


def test_collect_nflverse_dry_run_sends_nothing(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    handle = mock_transport_factory({})
    patched_client(handle)
    assert main(["collect", "nflverse", "--season", "2014-2015", "--dry-run"]) == 0
    assert handle.requests == []
    assert "planned" in capsys.readouterr().out


def test_collect_nflverse_fetches_hosts_commits_counts_and_scopes_token(
    git_vault, mock_transport_factory, patched_client, capsys, monkeypatch
) -> None:
    paths = git_vault
    monkeypatch.setenv("GITHUB_TOKEN", "sentinel-token")
    handle = mock_transport_factory(_nflverse_responses())
    patched_client(handle)

    assert main(["collect", "nflverse", "--season", "2014"]) == 0

    hosts = {r.url.split("/")[2] for r in handle.requests}
    assert {"raw.githubusercontent.com", "api.github.com"} <= hosts
    for r in handle.requests:
        host = r.url.split("/")[2]
        if host == "api.github.com" and not r.url.endswith("robots.txt"):
            assert r.headers.get("authorization") == "Bearer sentinel-token"
        else:
            assert "authorization" not in r.headers, r.url
    assert (paths.raw / "nfl/nflverse/pbp/play_by_play_2014.parquet").is_file()
    subject, files = _last_commit(paths.vault)
    assert subject.startswith("collect: nfl_nflverse 2014 (")
    assert "sentinel-token" not in subject
    assert "ledger/nfl_nflverse_assets.jsonl" in files
    for name in files:
        assert name.startswith(("raw/nfl/nflverse/", "raw/_robots/", "ledger/")), name
    captured = capsys.readouterr()
    assert "sentinel-token" not in captured.out + captured.err


def test_collect_nflverse_schedules_only_skips_pbp(
    git_vault, mock_transport_factory, patched_client, monkeypatch
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    handle = mock_transport_factory(_nflverse_responses())
    patched_client(handle)
    assert main(["collect", "nflverse", "--season", "2014", "--schedules-only"]) == 0
    assert not [r.url for r in handle.requests if "api.github.com" in r.url]
    assert any(r.url == _SCHEDULES for r in handle.requests)


def test_collect_nflverse_pbp_only_skips_schedules_and_refresh_is_conditional(
    git_vault, mock_transport_factory, patched_client, monkeypatch
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    handle = mock_transport_factory(_nflverse_responses())
    patched_client(handle)
    assert main(["collect", "nflverse", "--season", "2014", "--pbp-only"]) == 0
    assert all(r.url != _SCHEDULES for r in handle.requests)

    responses = _nflverse_responses()
    responses[_SCHEDULES] = (200, b"a,b\n", {"ETag": '"abc"'})
    handle2 = mock_transport_factory(responses)
    patched_client(handle2)
    assert main(["collect", "nflverse", "--season", "2014", "--schedules-only"]) == 0

    responses[_SCHEDULES] = (304, b"", {})
    handle3 = mock_transport_factory(responses)
    patched_client(handle3)
    assert (
        main(["collect", "nflverse", "--season", "2014", "--schedules-only", "--refresh-schedules"])
        == 0
    )
    sent = [r for r in handle3.requests if r.url == _SCHEDULES]
    assert sent[0].headers.get("if-none-match") == '"abc"'


def test_collect_nflverse_schedules_and_pbp_only_are_exclusive() -> None:
    with pytest.raises(SystemExit):
        main(["collect", "nflverse", "--schedules-only", "--pbp-only"])


def test_collect_nflverse_unknown_host_stops_with_4_class_name_only(
    git_vault, mock_transport_factory, patched_client, capsys, monkeypatch
) -> None:
    from booth_review.errors import UnknownHostError

    def boom(self, *, refresh, dry_run):  # type: ignore[no-untyped-def]
        raise UnknownHostError("secret-host.example")

    monkeypatch.setattr(cli.NflverseCollector, "run_schedules", boom)
    handle = mock_transport_factory({})
    patched_client(handle)
    before = _commit_count(git_vault.vault)
    code = main(["collect", "nflverse", "--season", "2014"])
    assert code == 4
    err = capsys.readouterr().err
    assert "UnknownHostError" in err
    assert "secret-host" not in err
    assert _commit_count(git_vault.vault) == before  # nothing was fetched, so no commit


# -- wikipedia -----------------------------------------------------------------------

_WIKI_ROBOTS = {"https://en.wikipedia.org/robots.txt": (404, b"nf", {})}


def _wiki_url(season: int) -> str:
    return f"https://en.wikipedia.org/wiki/{season}_NFL_season"


def test_collect_wikipedia_fetches_two_articles_and_serves_cache_after(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    paths = git_vault
    page = (_FIX / "wikipedia" / "season_2014_synthetic.html").read_bytes()
    handle = mock_transport_factory(
        {**_WIKI_ROBOTS, _wiki_url(2014): (200, page, {}), _wiki_url(2015): (200, page, {})}
    )
    patched_client(handle)

    assert main(["collect", "wikipedia", "--league", "nfl", "--season", "2014-2015"]) == 0
    articles = [r for r in handle.requests if "_NFL_season" in r.url]
    assert len(articles) == 2
    subject, files = _last_commit(paths.vault)
    assert subject.startswith("collect: nfl_wikipedia 2014-2015 (fetched 2")
    for name in files:
        assert name.startswith(("raw/nfl/wikipedia/", "raw/_robots/", "ledger/")), name

    handle2 = mock_transport_factory({})
    patched_client(handle2)
    assert main(["collect", "wikipedia", "--season", "2014-2015", "--refresh"]) == 0
    assert handle2.requests == []  # completed seasons are never re-read


def test_collect_wikipedia_refresh_rereads_only_the_current_season(
    git_vault, mock_transport_factory, patched_client
) -> None:
    from datetime import UTC, datetime

    current = season_of(datetime.now(UTC).date())
    page = (_FIX / "wikipedia" / "season_2014_synthetic.html").read_bytes()
    responses = {
        **_WIKI_ROBOTS,
        _wiki_url(current - 1): (200, page, {}),
        _wiki_url(current): (200, page, {}),
    }
    patched_client(mock_transport_factory(responses))
    assert main(["collect", "wikipedia", "--season", f"{current - 1}-{current}"]) == 0

    handle = mock_transport_factory({**_WIKI_ROBOTS, _wiki_url(current): (200, page + b"x", {})})
    patched_client(handle)
    assert main(["collect", "wikipedia", "--season", f"{current - 1}-{current}", "--refresh"]) == 0
    articles = [r.url for r in handle.requests if "_NFL_season" in r.url]
    assert articles == [_wiki_url(current)]


def test_collect_wikipedia_dry_run_sends_nothing(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    handle = mock_transport_factory({})
    patched_client(handle)
    before = _commit_count(git_vault.vault)
    assert main(["collect", "wikipedia", "--season", "2014", "--dry-run"]) == 0
    assert handle.requests == []
    assert _commit_count(git_vault.vault) == before
    assert "planned 1" in capsys.readouterr().out
