"""Offline CLI tests for the MLB collection commands (plan 09-13).

Each test drives `cli.main(argv)` against a throwaway git vault and a mock
transport, so no request leaves the machine. Pages and records are synthetic.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from booth_review import cli
from booth_review.cli import main
from booth_review.errors import VaultStateError
from booth_review.mlb import collect_cli
from booth_review.mlb.collect_cli import load_mlb_rr_windows, write_mlb_rr_windows
from booth_review.mlb.layout import RETROSHEET_INDEX_PATH, RETROSHEET_INDEX_URL
from booth_review.sources.ratingsref.collector import SITEMAP_URL

_FIX = Path(__file__).parent / "fixtures" / "mlb"
_RR_ROBOTS = "https://ratingsreference.com/robots.txt"
_LM = "2026-01-01T00:00:00+00:00"
_LM2 = "2026-02-01T00:00:00+00:00"
_WINDOWS = [(date(2019, 10, 1), date(2019, 10, 31)), (date(2026, 3, 20), date(2026, 12, 31))]
_REG_2019 = "mlb-aa-bb-2019-06-01"
_POST_2019 = "mlb-cc-dd-2019-10-05"
_REG_2026 = "mlb-ee-ff-2026-04-03"


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


def _body(slug: str) -> bytes:
    return json.dumps({"telecast": {"id": slug}}).encode()


def _seed_sitemap(paths, xml: bytes) -> None:
    folder = paths.raw / "ratingsref" / "sitemap"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "2026-01-01.xml").write_bytes(xml)


# -- windows file --------------------------------------------------------------------


def test_windows_file_round_trip_and_validation(git_vault) -> None:
    paths = git_vault
    assert load_mlb_rr_windows(paths) is None
    assert write_mlb_rr_windows(paths, _WINDOWS) == "ledger/mlb_rr_windows.json"
    assert load_mlb_rr_windows(paths) == _WINDOWS
    with pytest.raises(VaultStateError):
        write_mlb_rr_windows(paths, [_WINDOWS[1], _WINDOWS[0]])
    (paths.vault / "ledger/mlb_rr_windows.json").write_text("{}", encoding="utf-8")
    with pytest.raises(VaultStateError):
        load_mlb_rr_windows(paths)


# -- ratingsref ----------------------------------------------------------------------


def test_collect_ratingsref_mlb_window_scoped_dry_run(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    paths = git_vault
    write_mlb_rr_windows(paths, _WINDOWS)
    _seed_sitemap(paths, _sitemap([(_REG_2019, _LM), (_POST_2019, _LM)]))
    handle = mock_transport_factory({})
    patched_client(handle)

    assert main(["collect", "ratingsref", "--league", "mlb", "--season", "2019", "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert _rr_url(_POST_2019) in out
    assert _rr_url(_REG_2019) not in out
    assert handle.requests == []


def test_collect_ratingsref_mlb_window_scoped_commit(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    paths = git_vault
    write_mlb_rr_windows(paths, _WINDOWS)
    handle = mock_transport_factory(
        {
            _RR_ROBOTS: (404, b"nf", {}),
            SITEMAP_URL: (200, _sitemap([(_REG_2019, _LM), (_POST_2019, _LM)]), {}),
            _rr_url(_POST_2019): (200, _body(_POST_2019), {}),
        }
    )
    patched_client(handle)

    assert main(["collect", "ratingsref", "--league", "mlb", "--season", "2019"]) == 0

    assert all(_REG_2019 not in r.url for r in handle.requests)
    assert (paths.raw / "mlb/ratingsref/telecast/2019" / f"{_POST_2019}.json").is_file()
    subject, files = _last_commit(paths.vault)
    assert subject.startswith("collect: mlb_ratingsref ")
    assert _POST_2019 not in subject
    assert len(subject) <= 120
    for name in files:
        assert name.startswith(
            ("raw/mlb/ratingsref/", "raw/ratingsref/sitemap/", "raw/_robots/", "ledger/")
        ), name


def test_collect_ratingsref_mlb_window_missing_file_exits_2(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    handle = mock_transport_factory({})
    patched_client(handle)
    before = _commit_count(git_vault.vault)
    assert main(["collect", "ratingsref", "--league", "mlb", "--season", "2026"]) == 2
    assert "run booth-review mlb rr-backfill first" in capsys.readouterr().err
    assert handle.requests == []
    assert _commit_count(git_vault.vault) == before


def test_refresh_ratingsref_mlb_window_missing_file_exits_2(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    handle = mock_transport_factory({})
    patched_client(handle)
    assert main(["refresh", "ratingsref", "--league", "mlb"]) == 2
    assert "run booth-review mlb rr-backfill first" in capsys.readouterr().err
    assert handle.requests == []


def test_refresh_ratingsref_mlb_window_passes_stored_windows_and_cap_40(
    monkeypatch: pytest.MonkeyPatch, git_vault
) -> None:
    write_mlb_rr_windows(git_vault, _WINDOWS)
    seen: list[dict] = []

    class _Stop(Exception):
        pass

    def fake_refresh(self, **kwargs):  # type: ignore[no-untyped-def]
        seen.append({"league": self._league, **kwargs})
        raise _Stop

    monkeypatch.setattr(cli.RatingsRefCollector, "refresh", fake_refresh)
    with pytest.raises(_Stop):
        main(["refresh", "ratingsref", "--league", "mlb", "--dry-run"])
    with pytest.raises(_Stop):
        main(["refresh", "ratingsref", "--league", "mlb", "--max-refetch", "7", "--dry-run"])
    assert seen[0]["league"] == "mlb"
    assert seen[0]["cap"] == 40
    assert seen[0]["windows"] == _WINDOWS
    assert seen[1]["cap"] == 7


def test_refresh_ratingsref_mlb_window_never_selects_out_of_window(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    paths = git_vault
    write_mlb_rr_windows(paths, _WINDOWS)
    paths.rr_lastmod.write_text(
        json.dumps(
            {
                _REG_2019: {"lastmod": _LM, "fetched_at": "2026-01-02T00:00:00Z", "record_url": ""},
                "mlb-old-new-2019-10-02": {
                    "lastmod": _LM,
                    "fetched_at": "2026-01-02T00:00:00Z",
                    "record_url": "",
                },
            }
        ),
        encoding="utf-8",
    )
    _seed_sitemap(paths, _sitemap([(_REG_2019, _LM2), (_REG_2026, _LM)]))
    handle = mock_transport_factory({})
    patched_client(handle)

    assert main(["refresh", "ratingsref", "--league", "mlb", "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "selected 1" in out
    assert handle.requests == []


def test_mlb_season_ceiling_is_the_calendar_year(
    monkeypatch: pytest.MonkeyPatch, git_vault, mock_transport_factory, patched_client
) -> None:
    patched_client(mock_transport_factory({}))
    monkeypatch.setattr(cli, "_current_season_ceiling", lambda: 2025)
    monkeypatch.setattr(cli, "mlb_season_ceiling", lambda: 2026)
    write_mlb_rr_windows(git_vault, _WINDOWS)
    _seed_sitemap(git_vault, _sitemap([(_REG_2026, _LM)]))

    assert main(["collect", "ratingsref", "--league", "mlb", "--season", "2026", "--dry-run"]) == 0
    with pytest.raises(SystemExit) as stop:
        main(["collect", "ratingsref", "--league", "nfl", "--season", "2026", "--dry-run"])
    assert stop.value.code == 2


def test_mlb_collect_path_entries() -> None:
    assert "raw/mlb/ratingsref" in cli._COLLECT_PATHS["mlb_ratingsref"]
    assert "ledger/mlb_rr_windows.json" in cli._COLLECT_PATHS["mlb_ratingsref"]
    assert cli._COLLECT_PATHS["mlb_sports506"] == ("raw/mlb/sports506", "ledger/requests.jsonl")
    assert cli._COLLECT_PATHS["mlb_relay"] == ("raw/mlb/relay", "ledger/requests.jsonl")
    assert "raw/mlb/wikipedia" in cli._COLLECT_PATHS["mlb_wikipedia"]
    assert "raw/mlb/retrosheet" in cli._COLLECT_PATHS["mlb_retrosheet"]
    assert "raw/mlb/statsapi" in cli._COLLECT_PATHS["mlb_statsapi"]


# -- import 506 ----------------------------------------------------------------------


def _mlb_page(season: int = 2026) -> bytes:
    text = (_FIX / "sports506" / "week_cgame_synthetic.html").read_text(encoding="utf-8")
    return text.replace("2099", str(season)).encode("utf-8")


def test_import_506_mlb_sends_no_requests_and_commits_mlb_paths(
    git_vault, mock_transport_factory, patched_client, tmp_path, capsys
) -> None:
    handle = mock_transport_factory({})
    patched_client(handle)
    folder = tmp_path / "saved"
    folder.mkdir()
    (folder / "a.html").write_bytes(_mlb_page())

    code = main(["import", "506", "--league", "mlb", "--season", "2026", "--from", str(folder)])

    assert code in (0, 4)
    assert handle.requests == []
    assert (git_vault.raw / "mlb/sports506/2026/wk-03.html").is_file()
    subject, files = _last_commit(git_vault.vault)
    assert subject.startswith("import: mlb_sports506 2026 (")
    for name in files:
        assert name.startswith(("raw/mlb/sports506/2026/", "ledger/")), name


def test_import_506_mlb_inspect_prints_counts_and_writes_nothing(
    git_vault, mock_transport_factory, patched_client, tmp_path, capsys
) -> None:
    patched_client(mock_transport_factory({}))
    folder = tmp_path / "saved"
    folder.mkdir()
    (folder / "a.html").write_bytes(_mlb_page())
    before = _commit_count(git_vault.vault)

    code = main(
        [
            "import",
            "506",
            "--league",
            "mlb",
            "--season",
            "2026",
            "--from",
            str(folder),
            "--inspect",
        ]
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "file 0:" in out
    assert "a.html" not in out
    assert not (git_vault.raw / "mlb").exists()
    assert _commit_count(git_vault.vault) == before


def test_import_506_inspect_is_mlb_only(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    patched_client(mock_transport_factory({}))
    assert main(["import", "506", "--season", "2025", "--inspect"]) == 2
    assert "MLB only" in capsys.readouterr().err


# -- wikipedia -----------------------------------------------------------------------


def test_collect_wikipedia_mlb_fetches_article_and_commits_scoped_paths(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    from booth_review.mlb.layout import mlb_wikipedia_url

    page = (_FIX / "wikipedia" / "postseason_synthetic.html").read_bytes()
    handle = mock_transport_factory(
        {
            "https://en.wikipedia.org/robots.txt": (404, b"nf", {}),
            mlb_wikipedia_url(2014): (200, page, {}),
        }
    )
    patched_client(handle)

    assert main(["collect", "wikipedia", "--league", "mlb", "--season", "2014"]) == 0

    assert (git_vault.raw / "mlb/wikipedia/2014.html").is_file()
    subject, files = _last_commit(git_vault.vault)
    assert subject.startswith("collect: mlb_wikipedia 2014 (fetched 1")
    for name in files:
        assert name.startswith(("raw/mlb/wikipedia/", "raw/_robots/", "ledger/")), name


def test_collect_wikipedia_mlb_dry_run_plans_lists(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    handle = mock_transport_factory({})
    patched_client(handle)
    assert (
        main(
            [
                "collect",
                "wikipedia",
                "--league",
                "mlb",
                "--season",
                "2014-2015",
                "--lists",
                "--dry-run",
            ]
        )
        == 0
    )
    assert "planned" in capsys.readouterr().out
    assert handle.requests == []


def test_collect_wikipedia_lists_is_mlb_only(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    patched_client(mock_transport_factory({}))
    assert main(["collect", "wikipedia", "--season", "2014", "--lists"]) == 2


# -- retrosheet ----------------------------------------------------------------------

_RETRO_BASE = "https://www.retrosheet.org/downloads/"
_RETRO_ROBOTS = {"https://www.retrosheet.org/robots.txt": (404, b"nf", {})}
_ZIP = b"PK\x03\x04" + b"synthetic"


def _seed_retro_index(paths) -> None:
    path = paths.raw / RETROSHEET_INDEX_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((_FIX / "retrosheet" / "csvdownloads_synthetic.html").read_bytes())


def test_collect_retrosheet_index_only_fetches_only_the_index(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    index = (_FIX / "retrosheet" / "csvdownloads_synthetic.html").read_bytes()
    handle = mock_transport_factory({**_RETRO_ROBOTS, RETROSHEET_INDEX_URL: (200, index, {})})
    patched_client(handle)

    assert main(["collect", "retrosheet", "--index-only"]) == 0

    assert [r.url for r in handle.requests if "robots" not in r.url] == [RETROSHEET_INDEX_URL]
    subject, files = _last_commit(git_vault.vault)
    assert subject.startswith("collect: mlb_retrosheet index (")
    for name in files:
        assert name.startswith(("raw/mlb/retrosheet/", "raw/_robots/", "ledger/")), name


def test_collect_retrosheet_list_assets_counts_by_kind_without_requests(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    handle = mock_transport_factory({})
    patched_client(handle)
    _seed_retro_index(git_vault)

    assert main(["collect", "retrosheet", "--list-assets"]) == 0

    out = capsys.readouterr().out
    assert "assets 2" in out
    assert "season_bundle 2" in out
    assert handle.requests == []


def test_collect_retrosheet_season_dry_run_and_missing_asset(
    monkeypatch: pytest.MonkeyPatch, git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    monkeypatch.setattr(collect_cli, "mlb_season_ceiling", lambda: 2100)
    handle = mock_transport_factory({})
    patched_client(handle)
    _seed_retro_index(git_vault)

    assert main(["collect", "retrosheet", "--season", "2099-2100", "--dry-run"]) == 0
    assert "planned 2" in capsys.readouterr().out
    assert handle.requests == []

    before = _commit_count(git_vault.vault)
    assert main(["collect", "retrosheet", "--season", "2098", "--dry-run"]) == 4
    assert "season_bundle 2098" in capsys.readouterr().err
    assert _commit_count(git_vault.vault) == before


def test_collect_retrosheet_season_fetches_assets_and_commits(
    monkeypatch: pytest.MonkeyPatch, git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    monkeypatch.setattr(collect_cli, "mlb_season_ceiling", lambda: 2100)
    _seed_retro_index(git_vault)
    handle = mock_transport_factory(
        {
            **_RETRO_ROBOTS,
            _RETRO_BASE + "2099/2099csvs.zip": (200, _ZIP, {}),
        }
    )
    patched_client(handle)

    assert main(["collect", "retrosheet", "--season", "2099"]) == 0

    subject, _files = _last_commit(git_vault.vault)
    assert subject.startswith("collect: mlb_retrosheet 2099 (")
    assert len(subject) <= 120


# -- relay ---------------------------------------------------------------------------


def _stage_relay(tmp_path: Path, name: str = "crew_relays_valid.csv") -> Path:
    folder = tmp_path / "relay"
    folder.mkdir()
    (folder / "staged.csv").write_bytes((_FIX / "relay" / name).read_bytes())
    return folder


def test_import_relay_commits_relay_paths_without_requests(
    git_vault, mock_transport_factory, patched_client, tmp_path, capsys
) -> None:
    handle = mock_transport_factory({})
    patched_client(handle)
    folder = _stage_relay(tmp_path)

    assert main(["import", "relay", "--from", str(folder)]) == 0

    assert handle.requests == []
    assert (git_vault.raw / "mlb/relay/crew_relays.csv").is_file()
    subject, files = _last_commit(git_vault.vault)
    assert subject.startswith("import: mlb_relay 2026 (rows ")
    assert len(subject) <= 120
    for name in files:
        assert name.startswith(("raw/mlb/relay/", "ledger/")), name

    # a second run is a no-op skip, and a changed file needs --force
    assert main(["import", "relay", "--from", str(folder)]) == 0
    (folder / "staged.csv").write_bytes(
        (folder / "staged.csv").read_bytes().replace(b"Pat Quill", b"Pat Quilt")
    )
    assert main(["import", "relay", "--from", str(folder)]) == 4
    assert main(["import", "relay", "--from", str(folder), "--force"]) == 0


def test_import_relay_validation_failure_exits_4_with_line_reasons_only(
    git_vault, mock_transport_factory, patched_client, tmp_path, capsys
) -> None:
    patched_client(mock_transport_factory({}))
    folder = _stage_relay(tmp_path, "crew_relays_bad_url.csv")

    assert main(["import", "relay", "--from", str(folder)]) == 4

    err = capsys.readouterr().err
    assert "line " in err
    assert "tamirmoore" not in err
    assert not (git_vault.raw / "mlb/relay").exists()


# -- statsapi ------------------------------------------------------------------------


def test_collect_statsapi_dry_run_prints_planned_count_and_urls(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    handle = mock_transport_factory({})
    patched_client(handle)

    assert (
        main(["collect", "statsapi", "--season", "2026", "--dates", "2026-04-24", "--dry-run"]) == 0
    )

    out = capsys.readouterr().out
    assert "planned 1" in out
    assert "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-04-24" in out
    assert handle.requests == []


def test_collect_statsapi_refuses_without_host_policy(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    handle = mock_transport_factory({})
    patched_client(handle)
    before = _commit_count(git_vault.vault)

    code = main(["collect", "statsapi", "--season", "2026", "--dates", "2026-04-24"])

    assert code == 3
    assert "host" in capsys.readouterr().err
    assert handle.requests == []
    assert _commit_count(git_vault.vault) == before


def test_collect_statsapi_default_max_requests_is_one(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    patched_client(mock_transport_factory({}))
    assert (
        main(
            [
                "collect",
                "statsapi",
                "--season",
                "2026",
                "--dates",
                "2026-04-24,2026-05-01",
                "--dry-run",
            ]
        )
        == 2
    )
    assert "cap" in capsys.readouterr().err
