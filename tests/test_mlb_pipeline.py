"""`run_mlb_build` and the `booth-review mlb` command group on a synthetic vault."""

from __future__ import annotations

import functools
import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from mlb_pipeline_support import make_reference, make_vault

from booth_review.cli import main
from booth_review.config import DataPaths
from booth_review.mlb import commands as mlb_commands
from booth_review.mlb import pipeline
from booth_review.mlb.collect_cli import load_mlb_rr_windows
from booth_review.mlb.pipeline import run_mlb_build
from booth_review.mlb.tables import MLB_TABLES, REVIEW_KEYS
from booth_review.sources.ratingsref.collector import SITEMAP_URL

_TRAIN = 3  # synthetic bundles hold a handful of games, not the 5000 the real table needs
_SEASONS = [2025, 2026]


def _digests(paths: DataPaths) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in MLB_TABLES:
        frame = pl.read_parquet(paths.processed / f"{name}.parquet")
        out[name] = hashlib.sha256(repr(frame.to_dicts()).encode()).hexdigest()
    for review in sorted(paths.interim.glob("review_mlb_*.csv")):
        out[review.name] = hashlib.sha256(review.read_bytes()).hexdigest()
    return out


def _build(paths: DataPaths, ref: Path, **kwargs: object):  # type: ignore[no-untyped-def]
    return run_mlb_build(
        paths,
        ref,
        _SEASONS,
        commit=False,
        we_min_train_games=_TRAIN,
        **kwargs,  # type: ignore[arg-type]
    )


def test_build_writes_every_table_and_review(git_vault: DataPaths, tmp_path: Path) -> None:
    paths = git_vault
    make_vault(paths)
    ref = make_reference(tmp_path / "ref")

    outcome = _build(paths, ref)

    for name in MLB_TABLES:
        assert (paths.processed / f"{name}.parquet").is_file(), name
    for key in REVIEW_KEYS:
        assert (paths.interim / f"review_mlb_{key}.csv").is_file(), key
    assert set(outcome.written) >= {f"processed/{n}.parquet" for n in MLB_TABLES}
    assert not outcome.committed


def test_build_report_counts_and_pending(git_vault: DataPaths, tmp_path: Path) -> None:
    paths = git_vault
    make_vault(paths)
    ref = make_reference(tmp_path / "ref")

    counts = _build(paths, ref).counts

    for key in (
        "disagreements",
        "rr_ambiguous_doubleheader",
        "rr_conflict",
        "rr_per_network",
        "unresolved_names",
        "map_ambiguous",
        "quality_pending",
    ):
        assert key in counts, key
    assert counts["quality_pending"] == 1  # no Retrosheet 2026 yet
    assert counts["unresolved_names"] >= 2  # the invented postseason crew names
    assert counts["games"] >= 2
    assert any(k.startswith("crew_named_") for k in counts)
    apple = pl.read_parquet(paths.processed / "mlb_apple_booths.parquet")
    assert apple["quality_status"].to_list() == ["pending"]


def test_build_with_2026_results_is_ready(git_vault: DataPaths, tmp_path: Path) -> None:
    paths = git_vault
    make_vault(paths, with_2026=True)
    ref = make_reference(tmp_path / "ref")

    outcome = _build(paths, ref)

    assert outcome.counts["quality_pending"] == 0
    apple = pl.read_parquet(paths.processed / "mlb_apple_booths.parquet")
    assert apple["quality_status"].to_list() == ["ready"]
    assert apple["excitement_n"].to_list() == [1]
    lineups = pl.read_parquet(paths.processed / "mlb_lineups.parquet")
    assert lineups["game_key"].n_unique() >= 2  # the 2026 game and the postseason games
    we = pl.read_parquet(paths.processed / "mlb_we_table.parquet")
    assert we.height > 0 and we["p"].is_between(0, 1).all()


def test_rr_figure_attaches_to_the_listed_postseason_telecast(
    git_vault: DataPaths, tmp_path: Path
) -> None:
    paths = git_vault
    make_vault(paths)
    ref = make_reference(tmp_path / "ref")

    outcome = _build(paths, ref)

    telecasts = pl.read_parquet(paths.processed / "mlb_telecasts.parquet")
    wild_card = telecasts.filter(pl.col("round") == "wild_card").row(0, named=True)
    assert wild_card["rr_viewers"] == 4_000_000 and wild_card["rr_cause"] is None
    assert wild_card["rr_source_url"] == "https://example.invalid/figure"
    assert outcome.counts["rr_records"] == 2


def test_two_builds_are_byte_identical(git_vault: DataPaths, tmp_path: Path) -> None:
    paths = git_vault
    make_vault(paths, with_2026=True)
    ref = make_reference(tmp_path / "ref")

    _build(paths, ref)
    first = _digests(paths)
    _build(paths, ref)

    assert _digests(paths) == first


def test_build_touches_only_mlb_outputs(git_vault: DataPaths, tmp_path: Path) -> None:
    paths = git_vault
    make_vault(paths, with_2026=True)
    ref = make_reference(tmp_path / "ref")
    cfb = paths.processed / "games.parquet"
    cfb.write_bytes(b"cfb")
    nfl = paths.interim / "review_nfl_people.csv"
    nfl.parent.mkdir(parents=True, exist_ok=True)
    nfl.write_bytes(b"nfl")

    _build(paths, ref)

    assert cfb.read_bytes() == b"cfb"
    assert nfl.read_bytes() == b"nfl"
    names = {p.name for p in paths.processed.iterdir()}
    assert {n for n in names if n.startswith("mlb_")} == {f"{t}.parquet" for t in MLB_TABLES}


def test_site_data_before_its_builder_exists_stops_early(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = git_vault
    make_vault(paths)
    ref = make_reference(tmp_path / "ref")
    monkeypatch.setattr(pipeline, "SITE_DATA_BUILDER", None)

    with pytest.raises(Exception, match="site data builder not available"):
        _build(paths, ref, site_data=True)

    assert not list(paths.processed.glob("mlb_*"))


def test_commit_is_scoped_and_count_only(git_vault: DataPaths, tmp_path: Path) -> None:
    paths = git_vault
    make_vault(paths, with_2026=True)
    ref = make_reference(tmp_path / "ref")
    (paths.interim / "review_nfl_people.csv").write_text("raw_name\n", encoding="utf-8")

    outcome = run_mlb_build(paths, ref, _SEASONS, commit=True, we_min_train_games=_TRAIN)

    assert outcome.committed
    vault = str(paths.vault)
    subject = subprocess.run(
        ["git", "-C", vault, "log", "-1", "--format=%s"], capture_output=True, text=True, check=True
    ).stdout.strip()
    files = subprocess.run(
        ["git", "-C", vault, "show", "--name-only", "--format=", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert subject.startswith("build: mlb 2025-2026 (")
    assert len(subject) <= 120
    assert files
    for name in files:
        assert name.startswith(("processed/mlb_", "interim/review_mlb_")), name
    untracked = subprocess.run(
        ["git", "-C", vault, "status", "--short"], capture_output=True, text=True, check=True
    ).stdout
    assert "review_nfl_people.csv" in untracked  # left alone


# -- the `booth-review mlb` command group --------------------------------------------------


@pytest.fixture
def cli_vault(git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DataPaths:
    """A git vault holding the synthetic raw files, with the reference tables wired in."""
    make_vault(git_vault, with_2026=True, with_rr=False)
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(make_reference(tmp_path / "ref")))
    return git_vault


def test_mlb_help_lists_every_subcommand_by_its_exact_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["mlb", "--help"])
    assert stop.value.code == 0
    out = capsys.readouterr().out
    # AGENTS.md and the docs name these strings; do not rename them.
    for name in ("build", "gaps", "rr-backfill", "freeze", "people"):
        assert name in out


def test_mlb_build_command_prints_counts_only_and_commits(
    cli_vault: DataPaths, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        mlb_commands, "run_mlb_build", functools.partial(run_mlb_build, we_min_train_games=_TRAIN)
    )

    assert main(["mlb", "build"]) == 0

    out = capsys.readouterr().out
    assert "mlb games" in out and "crew coverage 2026" in out and "unresolved names" in out
    for private in ("Fixture", "Last", "XAA", "alpha"):
        assert private not in out
    subject = subprocess.run(
        ["git", "-C", str(cli_vault.vault), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert subject.startswith("build: mlb 2014-2026")


def test_mlb_build_no_commit_leaves_the_log_alone(
    cli_vault: DataPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        mlb_commands, "run_mlb_build", functools.partial(run_mlb_build, we_min_train_games=_TRAIN)
    )

    def count() -> str:
        return subprocess.run(
            ["git", "-C", str(cli_vault.vault), "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    before = count()

    assert main(["mlb", "build", "--season", "2025-2026", "--no-commit"]) == 0

    assert count() == before


def test_mlb_unexpected_error_is_withheld_with_exit_3(
    cli_vault: DataPaths, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The real table needs thousands of training games, so the synthetic vault fails loudly.
    assert main(["mlb", "build", "--no-commit"]) == 3
    err = capsys.readouterr().err
    assert "error: unexpected ValueError; details withheld" in err
    assert "BOOTH_REVIEW_DEBUG=1" in err
    assert "training games" not in err

    monkeypatch.setenv("BOOTH_REVIEW_DEBUG", "1")
    with pytest.raises(ValueError, match="training games"):
        main(["mlb", "build", "--no-commit"])


def test_mlb_build_site_data_flag_stops_before_the_builder_exists(
    cli_vault: DataPaths, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MLB_SITE_ENABLED", "true")
    monkeypatch.setattr(pipeline, "SITE_DATA_BUILDER", None)
    monkeypatch.setattr(
        mlb_commands, "run_mlb_build", functools.partial(run_mlb_build, we_min_train_games=_TRAIN)
    )

    # With no builder the env switch alone only skips; the flag is explicit and stops.
    assert main(["mlb", "build", "--no-commit"]) == 0
    assert "builder not available yet; skipped" in capsys.readouterr().out
    assert main(["mlb", "build", "--no-commit", "--site-data"]) != 0
    assert "site data builder not available" in capsys.readouterr().err


def test_mlb_gaps_relay_prints_counts_by_network_and_writes_locally(
    cli_vault: DataPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["mlb", "gaps", "--relay"]) == 0

    out = capsys.readouterr().out
    assert "mlb relay gaps: 1 telecast(s)" in out and "fox_net: 1" in out
    assert (cli_vault.interim / "review_mlb_relay_gaps.csv").is_file()
    assert main(["mlb", "gaps"]) == 2


def test_mlb_people_writes_the_review_and_apply_reads_decisions(
    cli_vault: DataPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["mlb", "people", "--season", "2025"]) == 0
    assert "unresolved" in capsys.readouterr().out
    review = cli_vault.interim / "review_mlb_people.csv"
    assert review.read_text(encoding="utf-8").splitlines()[0] == "raw_name,count,decision"
    assert main(["mlb", "people", "--season", "2025", "--apply"]) == 0


# -- rr-backfill ----------------------------------------------------------------------------

_LM = "2026-01-01T00:00:00+00:00"
_IN_2025 = "mlb-aces-bravos-2025-10-04"
_IN_2026 = "mlb-aces-bravos-2026-06-10"
_OUT_2025 = "mlb-aces-bravos-2025-06-02"
_RR_ROBOTS = "https://ratingsreference.com/robots.txt"


def _sitemap() -> bytes:
    urls = "".join(
        f"<url><loc>https://ratingsreference.com/telecast/{slug}</loc><lastmod>{_LM}</lastmod></url>\n"
        for slug in (_IN_2025, _IN_2026, _OUT_2025)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "</urlset>\n"
    ).encode()


def _rr_url(slug: str) -> str:
    return f"https://ratingsreference.com/api/telecast/{slug}.json"


def test_rr_backfill_dry_run_prints_counts_and_writes_nothing(
    cli_vault: DataPaths,
    mock_transport_factory,
    patched_client,
    capsys,  # type: ignore[no-untyped-def]
) -> None:
    folder = cli_vault.raw / "ratingsref" / "sitemap"
    folder.mkdir(parents=True)
    (folder / "2026-01-01.xml").write_bytes(_sitemap())
    handle = mock_transport_factory({})
    patched_client(handle)

    assert main(["mlb", "rr-backfill", "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "mlb rr windows 2" in out and "planned records 2" in out
    assert handle.requests == []
    assert load_mlb_rr_windows(cli_vault) is None


def test_rr_backfill_real_run_stores_windows_and_scopes_refresh(
    cli_vault: DataPaths,
    mock_transport_factory,
    patched_client,
    capsys,  # type: ignore[no-untyped-def]
) -> None:
    body = lambda slug: json.dumps({"telecast": {"id": slug}}).encode()  # noqa: E731
    handle = mock_transport_factory(
        {
            _RR_ROBOTS: (404, b"nf", {}),
            SITEMAP_URL: (200, _sitemap(), {}),
            _rr_url(_IN_2025): (200, body(_IN_2025), {}),
            _rr_url(_IN_2026): (200, body(_IN_2026), {}),
        }
    )
    patched_client(handle)

    assert main(["mlb", "rr-backfill"]) == 0

    assert load_mlb_rr_windows(cli_vault) == [
        (date(2025, 9, 30), date(2025, 10, 5)),
        (date(2026, 6, 5), date(2026, 12, 31)),
    ]
    assert all(_OUT_2025 not in r.url for r in handle.requests)
    assert (cli_vault.raw / "mlb/ratingsref/telecast/2025" / f"{_IN_2025}.json").is_file()
    vault = str(cli_vault.vault)
    subject = subprocess.run(
        ["git", "-C", vault, "log", "-1", "--format=%s"], capture_output=True, text=True, check=True
    ).stdout
    files = subprocess.run(
        ["git", "-C", vault, "show", "--name-only", "--format=", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert subject.startswith("collect: mlb_ratingsref 2025-2026")
    assert "ledger/mlb_rr_windows.json" in files
    capsys.readouterr()

    # The stored windows now scope the hand-run refresh: the out-of-window entry is never selected.
    cli_vault.rr_lastmod.write_text(
        json.dumps(
            {
                _OUT_2025: {
                    "lastmod": "2026-02-01T00:00:00+00:00",
                    "fetched_at": "x",
                    "record_url": "",
                },
            }
        ),
        encoding="utf-8",
    )
    assert main(["refresh", "ratingsref", "--league", "mlb", "--dry-run"]) == 0
    assert _OUT_2025 not in capsys.readouterr().out


def test_rr_backfill_cap_stops_before_the_window_that_would_exceed_it(
    cli_vault: DataPaths,
    mock_transport_factory,
    patched_client,
    capsys,  # type: ignore[no-untyped-def]
) -> None:
    handle = mock_transport_factory(
        {
            _RR_ROBOTS: (404, b"nf", {}),
            SITEMAP_URL: (200, _sitemap(), {}),
            _rr_url(_IN_2025): (200, b'{"telecast": {"id": "x"}}', {}),
        }
    )
    patched_client(handle)

    assert main(["mlb", "rr-backfill", "--max-requests", "1", "--no-commit"]) == 0

    out = capsys.readouterr().out
    assert "fetched 1" in out and "stopped: --max-requests 1 reached" in out
    assert all(_IN_2026 not in r.url for r in handle.requests)
