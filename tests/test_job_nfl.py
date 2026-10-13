"""Offline tests for the scheduled job's NFL block (plan 999.4-19, D-07 to D-10).

Every run drives ScheduledJob against throwaway git vaults (a local bare remote,
never a real one) and an httpx2.MockTransport, so no request leaves the machine
and no real vault is touched. Schedule rows, sitemap slugs, release listings and
pages are synthetic.

The D-08 isolation tests compare an NFL run against a baseline run on a copy of
the same vault with the SAME CFB outcome and no NFL work (no nflverse schedules
file, so the NFL block is skipped). An NFL failure may add attention items (and so
turn a clean run into exit 4); it may never cause exit 3, a "failed" last_status,
a held-back last_success_at, retry_pending, a key leak, or any change to the CFB
items, counts, commits, build, site or deploy_ready.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
import test_job_runner
from nfl_join_helpers import sched_row, schedule_csv
from test_job_runner import (
    UPDATE_NOW,
    _cfbd_ok_responses,
    _precache_cfbd_season,
    _runtime,
    _seed_required_state,
    _sitemap_xml,
    _update_cfbd_responses,
)

from booth_review import cli
from booth_review.build.pipeline import BuildOutcome
from booth_review.cli import main
from booth_review.config import DataPaths
from booth_review.errors import FetchError, VaultCommitError
from booth_review.job.attention import (
    AttentionItem,
    build_attention_body,
    nfl_506_missing,
    nfl_506_stale,
    nfl_build_blocked,
    nfl_review_due,
    nfl_rr_backlog,
    nfl_schedule_drift,
    nfl_season_past_freeze,
    push_failed,
    step_failed,
)
from booth_review.job.catchup import load_state
from booth_review.job.gaps506 import Gaps506
from booth_review.job.runner import NFL_PBP_REFRESH_WEEKDAYS, JobRunResult, ScheduledJob
from booth_review.nfl.gaps import NflGaps
from booth_review.nfl.layout import NFL_SOURCES, NFLVERSE_SCHEDULES_PATH
from booth_review.nfl.pipeline import NflBuildOutcome
from booth_review.sources.base import BatchSummary
from booth_review.sources.nflverse.collector import NflverseCollector, NflverseSummary
from booth_review.sources.ratingsref.collector import (
    NFL_REFRESH_CAP_DEFAULT,
    SITEMAP_URL,
    RatingsRefCollector,
    RefreshSummary,
)
from booth_review.sources.wikipedia.collector import WikipediaCollector

RUNNER = "booth_review.job.runner"

# The update-mode vault fixture from test_job_runner (2025 CFB build inputs, an
# accepted baseline, a cached RR sitemap), re-exported so pytest finds it here.
update_vault = test_job_runner.update_vault
_FIX = Path(__file__).parent / "fixtures" / "nfl"

# Wednesday 2026-10-14 20:00 ET (a main slot) and Sunday 2026-10-18 10:00 ET.
WED_NOW = datetime(2026, 10, 15, 0, 0, tzinfo=UTC)
SUN_NOW = datetime(2026, 10, 18, 14, 0, tzinfo=UTC)

_API = "https://api.github.com/repos/nflverse/nflverse-data"
_SCHEDULES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
_SIGNED = "https://release-assets.githubusercontent.com/signed/p2026?sig=1"
_WIKI_2026 = "https://en.wikipedia.org/wiki/2026_NFL_season"
_NFL_KNOWN = "nfl-aa-bb-2025-10-05"
_NFL_NEW = "nfl-cc-dd-2026-10-11"
_GH_TOKEN = "SENTINEL-GH-TOKEN-QRS"
_NFL_HOSTS = (
    "raw.githubusercontent.com",
    "api.github.com",
    "release-assets.githubusercontent.com",
    "en.wikipedia.org",
)


# -- vault helpers ------------------------------------------------------------------------


def _git(paths: DataPaths, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(paths.vault), *args], check=True, capture_output=True, text=True
    ).stdout


def _head(paths: DataPaths) -> str:
    return _git(paths, "rev-parse", "HEAD").strip()


@dataclass(frozen=True)
class _Commit:
    subject: str
    files: tuple[str, ...]


def _commits_since(paths: DataPaths, base: str) -> list[_Commit]:
    shas = _git(paths, "rev-list", "--reverse", f"{base}..HEAD").split()
    out: list[_Commit] = []
    for sha in shas:
        subject = _git(paths, "log", "-1", "--format=%s", sha).strip()
        files = _git(paths, "show", "--name-only", "--format=", sha).split()
        out.append(_Commit(subject, tuple(sorted(files))))
    return out


def _schedule_rows(season: int, *, played_week: str | None) -> list[dict[str, str]]:
    rows = [sched_row("future", 9, f"{season}-12-27", "AAA", "BBB", season=str(season))]
    if played_week is not None:
        rows.append(sched_row("played", 1, f"{season}-09-13", "AAA", "BBB", season=str(season)))
    return rows


def _bootstrap_nfl(
    paths: DataPaths,
    *,
    season: int,
    frozen_through: int,
    played_week: str | None = None,
    commit: bool = True,
) -> bytes:
    """Make `paths` an NFL-bootstrapped vault: an nflverse schedules file, NFL
    seasons 2014..frozen_through frozen, and one NFL lastmod line."""
    body = schedule_csv(_schedule_rows(season, played_week=played_week))
    target = paths.raw / NFLVERSE_SCHEDULES_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)

    frozen = json.loads(paths.frozen.read_text(encoding="utf-8"))
    for source in NFL_SOURCES:
        frozen[source] = list(range(2014, frozen_through + 1))
    paths.frozen.write_text(json.dumps(frozen), encoding="utf-8")

    lastmod: dict[str, Any] = {}
    if paths.rr_lastmod.is_file():
        lastmod = json.loads(paths.rr_lastmod.read_text(encoding="utf-8") or "{}")
    lastmod[_NFL_KNOWN] = {
        "lastmod": "2025-10-06T00:00:00+00:00",
        "fetched_at": "2025-10-06T00:00:00Z",
        "record_url": "",
    }
    paths.rr_lastmod.write_text(json.dumps(lastmod), encoding="utf-8")

    if commit:
        _git(paths, "add", "-A")
        _git(paths, "commit", "-q", "-m", "test: nfl bootstrap")
        _git(paths, "push", "-q", "origin", "main")
    return body


def _clone_vault(src: DataPaths, dest_root: Path) -> DataPaths:
    """A byte-for-byte copy of `src`'s working copy and its local bare remote."""
    remote = Path(_git(src, "remote", "get-url", "origin").strip())
    dest_root.mkdir(parents=True)
    shutil.copytree(remote, dest_root / "remote.git", symlinks=True)
    shutil.copytree(src.vault, dest_root / "vault", symlinks=True)
    paths = DataPaths(vault=dest_root / "vault")
    _git(paths, "remote", "set-url", "origin", str(dest_root / "remote.git"))
    return paths


def _is_nfl_item(item: AttentionItem) -> bool:
    return item.kind.startswith("nfl") or (item.kind == "push_failed" and "nfl" in item.line)


def _nfl_counts(counts: dict[str, int]) -> dict[str, int]:
    return {k: v for k, v in counts.items() if k.startswith("nfl_")}


def _cfb_counts(counts: dict[str, int]) -> dict[str, int]:
    return {k: v for k, v in counts.items() if not k.startswith("nfl_")}


# -- collect-only setup (real NFL collectors on a mock transport) ----------------------------


def _collect_vault(paths: DataPaths, *, played_week: str | None = "1") -> bytes:
    _seed_required_state(paths, cfbd_month="2026-10")
    _precache_cfbd_season(paths, 2026)
    return _bootstrap_nfl(paths, season=2026, frozen_through=2025, played_week=played_week)


def _pq(n: int = 40) -> bytes:
    return b"PAR1" + b"x" * (n - 8) + b"PAR1"


def _cfb_responses(sitemap: bytes) -> dict[str, tuple[int, bytes, dict[str, str]]]:
    responses = _cfbd_ok_responses(2026, include_teams_fbs=False)
    responses["https://ratingsreference.com/robots.txt"] = (404, b"nf", {})
    responses[SITEMAP_URL] = (200, sitemap, {})
    return responses


def _nfl_responses(schedules: bytes) -> dict[str, tuple[int, bytes, dict[str, str]]]:
    listing = json.dumps(
        [
            {
                "id": 912026,
                "name": "play_by_play_2026.parquet",
                "size": 40,
                "updated_at": "2026-10-13T00:00:00Z",
            }
        ]
    ).encode()
    return {
        "https://raw.githubusercontent.com/robots.txt": (404, b"nf", {}),
        "https://api.github.com/robots.txt": (404, b"nf", {}),
        "https://release-assets.githubusercontent.com/robots.txt": (404, b"nf", {}),
        "https://en.wikipedia.org/robots.txt": (404, b"nf", {}),
        _SCHEDULES_URL: (200, schedules, {}),
        f"{_API}/releases/tags/pbp": (
            200,
            (_FIX / "nflverse" / "release_pbp_synthetic.json").read_bytes(),
            {},
        ),
        f"{_API}/releases/900001/assets?per_page=100&page=1": (200, listing, {}),
        f"{_API}/releases/assets/912026": (302, b"", {"Location": _SIGNED}),
        _SIGNED: (200, _pq(), {}),
        f"https://ratingsreference.com/api/telecast/{_NFL_NEW}.json": (
            200,
            json.dumps({"telecast": {"id": _NFL_NEW}}).encode(),
            {},
        ),
        _WIKI_2026: (
            200,
            (_FIX / "wikipedia" / "season_2026_empty_synthetic.html").read_bytes(),
            {},
        ),
    }


def _all_responses(schedules: bytes) -> dict[str, tuple[int, bytes, dict[str, str]]]:
    sitemap = _sitemap_xml([(_NFL_NEW, "2026-10-12T00:00:00+00:00")])
    return {**_cfb_responses(sitemap), **_nfl_responses(schedules)}


def _host(url: str) -> str:
    return url.split("/")[2]


def _first_index(handle: Any, predicate: Any) -> int:
    return next(i for i, r in enumerate(handle.requests) if predicate(r.url))


# -- static guards ---------------------------------------------------------------------------


def test_runner_source_never_names_the_506_host() -> None:
    assert "506sports" not in Path("src/booth_review/job/runner.py").read_text(encoding="utf-8")


def test_pbp_refresh_weekdays_are_wednesday_and_thursday() -> None:
    assert frozenset({2, 3}) == NFL_PBP_REFRESH_WEEKDAYS


# -- CFB-only vault: the NFL block is skipped -------------------------------------------------


def test_cfb_only_vault_never_runs_an_nfl_step(
    git_vault, mock_transport_factory, fake_clock, monkeypatch
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-10")
    _precache_cfbd_season(paths, 2026)
    called: list[str] = []
    for target in (
        f"{RUNNER}.find_nfl_506_gaps",
        f"{RUNNER}.schedule_drift",
        f"{RUNNER}.run_nfl_build",
    ):
        monkeypatch.setattr(target, lambda *a, _t=target, **k: called.append(_t))

    handle = mock_transport_factory(_cfb_responses(_sitemap_xml([])))
    runtime = _runtime(paths, handle, now=lambda: WED_NOW, fake_clock=fake_clock)
    head = _head(paths)
    result = ScheduledJob(runtime, token="test-token", now=lambda: WED_NOW, trigger="manual").run()

    assert result.exit_code == 0
    assert not any(_is_nfl_item(item) for item in result.items)
    assert _nfl_counts(result.counts) == {}
    assert called == []
    assert all(_host(r.url) not in _NFL_HOSTS for r in handle.requests)
    assert all("/telecast/nfl-" not in r.url for r in handle.requests)
    assert all("nfl" not in c.subject for c in _commits_since(paths, head))
    state = load_state(paths.job_state)
    assert state.last_status == "ok"
    assert state.last_success_at == WED_NOW


# -- in season: the steps, their order, their commits ----------------------------------------


def test_wednesday_run_collects_every_nfl_source_in_order_with_scoped_commits(
    git_vault, mock_transport_factory, fake_clock, capsys
) -> None:
    paths = git_vault
    schedules = _collect_vault(paths)
    handle = mock_transport_factory(_all_responses(schedules))
    runtime = _runtime(paths, handle, now=lambda: WED_NOW, fake_clock=fake_clock)
    head = _head(paths)

    result = ScheduledJob(
        runtime,
        token="test-token",
        now=lambda: WED_NOW,
        trigger="schedule",
        github_token=_GH_TOKEN,
    ).run()

    # Order: schedules -> pbp -> RR NFL record -> Wikipedia, all after the CFB steps.
    cfb_last = max(
        i
        for i, r in enumerate(handle.requests)
        if _host(r.url) == "api.collegefootballdata.com" or r.url == SITEMAP_URL
    )
    i_sched = _first_index(handle, lambda u: u == _SCHEDULES_URL)
    i_pbp = _first_index(handle, lambda u: u.startswith(_API))
    i_rr = _first_index(handle, lambda u: "/api/telecast/nfl-" in u)
    i_wiki = _first_index(handle, lambda u: u == _WIKI_2026)
    assert cfb_last < i_sched < i_pbp < i_rr < i_wiki

    assert (paths.raw / "nfl/nflverse/pbp/play_by_play_2026.parquet").is_file()
    assert (paths.raw / f"nfl/ratingsref/telecast/2026/{_NFL_NEW}.json").is_file()
    assert (paths.raw / "nfl/wikipedia/2026.html").is_file()

    # Counts gain nfl_* keys; the played week 1 has no hand-saved 506 page.
    nfl = _nfl_counts(result.counts)
    assert nfl["nfl_schedules_failed"] == 0
    assert nfl["nfl_pbp_fetched"] == 1
    assert nfl["nfl_rr_fetched"] == 1
    assert nfl["nfl_wikipedia_fetched"] == 1
    assert nfl["nfl_506_missing"] == 1
    assert "nfl_pbp_skipped" not in nfl
    assert [i for i in result.items if _is_nfl_item(i)] == [nfl_506_missing(2026, ["1"])]
    assert result.exit_code == 4  # the 506 gap is an attention item

    commits = _commits_since(paths, head)
    subjects = [c.subject for c in commits]
    nfl_subjects = [s.split(" (")[0] for s in subjects if s.startswith("job: nfl_")]
    assert nfl_subjects == [
        "job: nfl_schedules 2026",
        "job: nfl_pbp 2026",
        "job: nfl_rr 2014-2026",
        "job: nfl_wikipedia 2026",
        "job: nfl_state 2026",
    ]
    allowed = {
        "job: nfl_schedules": ("raw/nfl/nflverse/", "raw/_robots/", "ledger/requests.jsonl"),
        "job: nfl_pbp": (
            "raw/nfl/nflverse/",
            "raw/_robots/",
            "ledger/requests.jsonl",
            "ledger/nfl_nflverse_assets.jsonl",
        ),
        "job: nfl_rr": (
            "raw/nfl/ratingsref/",
            "raw/ratingsref/sitemap/",
            "raw/_robots/",
            "ledger/requests.jsonl",
            "ledger/rr_lastmod.json",
            "ledger/rr_lastmod.jsonl",
        ),
        "job: nfl_wikipedia": ("raw/nfl/wikipedia/", "raw/_robots/", "ledger/requests.jsonl"),
        "job: nfl_state": ("ledger/nfl_run_reports.jsonl",),
    }
    for commit in commits:
        prefix = next((p for p in allowed if commit.subject.startswith(p + " ")), None)
        if prefix is None:
            # A CFB commit never carries an NFL file (Pitfall 4).
            assert not any(f.startswith("raw/nfl/") for f in commit.files), commit
            continue
        assert commit.files
        for name in commit.files:
            assert name.startswith(allowed[prefix]), (commit.subject, name)
    # CR-02: the CFB state commit comes before every NFL commit; the NFL
    # block's own report commit is last.
    state_index = next(i for i, s in enumerate(subjects) if s.startswith("job: state "))
    assert all(not s.startswith("job: nfl_") for s in subjects[:state_index])
    assert subjects[-1].startswith("job: nfl_state 2026 (attention 1)")
    nfl_report = json.loads(
        (paths.ledger / "nfl_run_reports.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert nfl_report["attention"] == 1
    assert nfl_report["counts"] == nfl
    cfb_report = json.loads(
        (paths.ledger / "run_reports.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert _nfl_counts(cfb_report["counts"]) == {}

    # Every NFL request line in the shared manifest was committed by an NFL commit.
    for sha in _git(paths, "rev-list", f"{head}..HEAD").split():
        subject = _git(paths, "log", "-1", "--format=%s", sha)
        if subject.startswith("job: nfl_"):
            continue
        diff = _git(paths, "show", "--format=", sha, "--", "ledger/requests.jsonl")
        added = [ln for ln in diff.splitlines() if ln.startswith("+{")]
        assert all('"nfl_' not in ln for ln in added), subject
    assert _git(paths, "status", "--porcelain", "--", "raw/nfl", "ledger") == ""

    # GITHUB_TOKEN reaches only api.github.com requests (never raw, assets, RR, wiki, CFBD).
    for request in handle.requests:
        auth = request.headers.get("authorization", "")
        if _host(request.url) == "api.github.com" and not request.url.endswith("robots.txt"):
            assert auth == f"Bearer {_GH_TOKEN}"
        else:
            assert _GH_TOKEN not in auth, request.url
    captured = capsys.readouterr()
    assert _GH_TOKEN not in captured.out + captured.err
    assert "506sports" not in "".join(r.url for r in handle.requests)

    # The saved state describes the CFB run alone (the NFL gap is in the NFL report).
    state = load_state(paths.job_state)
    assert state.last_status == "ok"
    assert state.last_success_at == WED_NOW
    assert state.retry_pending is False


def test_sunday_scheduled_run_skips_pbp_and_a_manual_run_does_not(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    schedules = _collect_vault(paths, played_week=None)
    handle = mock_transport_factory(_all_responses(schedules))
    runtime = _runtime(paths, handle, now=lambda: SUN_NOW, fake_clock=fake_clock)

    result = ScheduledJob(runtime, token="t", now=lambda: SUN_NOW, trigger="schedule").run()

    assert result.counts["nfl_pbp_skipped"] == 1
    assert not any(_host(r.url) == "api.github.com" for r in handle.requests)
    assert any(r.url == _SCHEDULES_URL for r in handle.requests)
    assert any(r.url == _WIKI_2026 for r in handle.requests)
    assert result.exit_code == 0

    later = datetime(2026, 10, 18, 15, 0, tzinfo=UTC)
    handle2 = mock_transport_factory(_all_responses(schedules))
    runtime2 = _runtime(paths, handle2, now=lambda: later, fake_clock=fake_clock)
    manual = ScheduledJob(runtime2, token="t", now=lambda: later, trigger="manual").run()

    assert "nfl_pbp_skipped" not in manual.counts
    assert manual.counts["nfl_pbp_fetched"] == 1
    assert any(_host(r.url) == "api.github.com" for r in handle2.requests)


def test_outside_the_nfl_season_the_block_does_nothing(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _seed_required_state(paths, cfbd_month="2026-04")
    _bootstrap_nfl(paths, season=2025, frozen_through=2024)
    now_value = datetime(2026, 4, 1, 16, 0, tzinfo=UTC)
    handle = mock_transport_factory(
        {
            "https://ratingsreference.com/robots.txt": (404, b"nf", {}),
            SITEMAP_URL: (200, _sitemap_xml([]), {}),
        }
    )
    runtime = _runtime(paths, handle, now=lambda: now_value, fake_clock=fake_clock)
    head = _head(paths)

    result = ScheduledJob(runtime, token="t", now=lambda: now_value, trigger="manual").run()

    assert _nfl_counts(result.counts) == {}
    assert not any(_is_nfl_item(item) for item in result.items)
    assert all(_host(r.url) not in _NFL_HOSTS for r in handle.requests)
    assert all("nfl" not in c.subject for c in _commits_since(paths, head))


def test_dry_run_sends_no_nfl_request_and_makes_no_commit(
    git_vault, mock_transport_factory, fake_clock
) -> None:
    paths = git_vault
    _collect_vault(paths)
    handle = mock_transport_factory({})
    runtime = _runtime(paths, handle, now=lambda: WED_NOW, fake_clock=fake_clock)
    head = _head(paths)

    ScheduledJob(
        runtime,
        token=None,
        now=lambda: WED_NOW,
        trigger="manual",
        dry_run=True,
        github_token=_GH_TOKEN,
    ).run()

    assert handle.requests == []
    assert _head(paths) == head
    assert _git(paths, "status", "--porcelain") == ""


# -- fakes for the NFL collaborators -------------------------------------------------------------

_STEPS = ("schedules", "pbp", "rr", "wikipedia", "gaps", "checks", "build")
_KINDS = ("runtime", "fetch", "commit")
_ERROR_CLASS = {"runtime": "RuntimeError", "fetch": "FetchError", "commit": "VaultCommitError"}
# step -> (step_failed name, commit step name or None when the step makes no commit)
_STEP_NAMES = {
    "schedules": ("nflverse", "nfl_schedules"),
    "pbp": ("nflverse", "nfl_pbp"),
    "rr": ("nfl_rr", "nfl_rr"),
    "wikipedia": ("nfl_wikipedia", "nfl_wikipedia"),
    "gaps": ("nfl_gaps", None),
    "checks": ("nfl_freeze", None),
    "build": ("nfl_build", "nfl_build"),
}
_SECRET = "leak https://example.invalid/x?key=abc123 Team Example"


def _error(kind: str) -> Exception:
    if kind == "runtime":
        return RuntimeError(_SECRET)
    if kind == "fetch":
        return FetchError(_SECRET, status_code=503)
    return VaultCommitError("git subcommand push exited 1")


def _expected_item(step: str, kind: str) -> AttentionItem:
    name, commit_step = _STEP_NAMES[step]
    if kind == "commit" and commit_step is not None:
        return push_failed(commit_step)
    return step_failed(name, _ERROR_CLASS[kind])


def _raises_from_function(step: str, kind: str) -> bool:
    """Collector steps get their VaultCommitError from the vault commit; gaps,
    checks and the build (which commits inside run_nfl_build) raise it directly."""
    return kind != "commit" or step in ("gaps", "checks", "build")


@dataclass
class _NflFakes:
    calls: list[str]
    fail: tuple[str, str] | None = None
    rr_backlog: int = 0
    rr_caps: list[int] | None = None
    gaps: NflGaps | None = None
    drift: tuple[int, ...] = ()
    build_counts: dict[str, int] | None = None
    build_blocked: bool = False
    build_kwargs: list[dict[str, Any]] | None = None

    def hit(self, step: str) -> None:
        self.calls.append(step)
        if self.fail is not None and self.fail[0] == step:
            kind = self.fail[1]
            if _raises_from_function(step, kind):
                raise _error(kind)


def _batch(source: str) -> BatchSummary:
    return BatchSummary(
        source=source,
        season_label="x",
        planned=0,
        cached=0,
        fetched=0,
        not_modified=0,
        failed=0,
        frozen_miss=0,
    )


def _install_fakes(monkeypatch: pytest.MonkeyPatch, fakes: _NflFakes) -> None:
    def run_schedules(self: Any, *, refresh: bool, dry_run: bool) -> BatchSummary:
        fakes.hit("schedules")
        return _batch("nfl_nflverse")

    def run_pbp(self: Any, seasons: Any, *, dry_run: bool) -> NflverseSummary:
        fakes.hit("pbp")
        return NflverseSummary(0, 0, 0, 0, 0, (), 0, 0, dry_run=dry_run)

    real_refresh = RatingsRefCollector.refresh

    def refresh(self: Any, **kwargs: Any) -> RefreshSummary:
        if self._league != "nfl":
            return real_refresh(self, **kwargs)
        fakes.hit("rr")
        if fakes.rr_caps is not None:
            fakes.rr_caps.append(kwargs["cap"])
        return RefreshSummary(
            qualifying=fakes.rr_backlog,
            new=0,
            advanced=fakes.rr_backlog,
            selected=0,
            uncapped_current=0,
            backlog=fakes.rr_backlog,
            fetched=0,
            not_modified=0,
            failed=0,
            dry_run=kwargs["dry_run"],
        )

    def wiki_run(self: Any, seasons: Any, *, refresh: bool = False, dry_run: bool = False) -> Any:
        fakes.hit("wikipedia")
        return [_batch("nfl_wikipedia")]

    def gaps(paths: DataPaths, season: int, now: datetime) -> NflGaps:
        fakes.hit("gaps")
        return fakes.gaps or NflGaps(season, [], [], 0, 0)

    def drift(paths: DataPaths) -> list[int]:
        fakes.hit("checks")
        return list(fakes.drift)

    def build(paths: DataPaths, reference_directory: Path, **kwargs: Any) -> NflBuildOutcome:
        fakes.hit("build")
        if fakes.build_kwargs is not None:
            fakes.build_kwargs.append({"reference": reference_directory, **kwargs})
        return NflBuildOutcome(
            blocked=fakes.build_blocked,
            written=(),
            counts=fakes.build_counts or {"games": 0, "standalone": 0},
            acceptance=None,
            committed=False,
        )

    monkeypatch.setattr(NflverseCollector, "run_schedules", run_schedules)
    monkeypatch.setattr(NflverseCollector, "run_pbp", run_pbp)
    monkeypatch.setattr(RatingsRefCollector, "refresh", refresh)
    monkeypatch.setattr(WikipediaCollector, "run", wiki_run)
    monkeypatch.setattr(f"{RUNNER}.find_nfl_506_gaps", gaps)
    monkeypatch.setattr(f"{RUNNER}.schedule_drift", drift)
    monkeypatch.setattr(f"{RUNNER}.run_nfl_build", build)


def _fail_nfl_commits(runtime: Any, steps: set[str]) -> None:
    """Make the vault commit of each named NFL step raise VaultCommitError."""
    real = runtime.vault.commit_batch

    def commit_batch(message: str, **kwargs: Any) -> bool:
        if any(message.startswith(f"job: {step} ") for step in steps):
            raise VaultCommitError("git subcommand push exited 1")
        return real(message, **kwargs)

    runtime.vault.commit_batch = commit_batch


# -- update-mode run outcome -----------------------------------------------------------------


@dataclass(frozen=True)
class _Outcome:
    exit_code: int
    cfb_items: list[AttentionItem]
    nfl_items: list[AttentionItem]
    cfb_counts: dict[str, int]
    deploy_ready: bool
    key_leak_items: int
    site_built: bool
    last_success_at: datetime | None
    last_attempt_at: datetime | None
    last_status: str | None
    retry_pending: bool
    last_build_at: datetime | None
    cfb_commits: list[_Commit]
    state_attention: int
    all_items: list[AttentionItem]
    nfl_report_attention: int | None


def _normalize_state(commit: _Commit) -> tuple[_Commit, int]:
    match = re.search(r"attention (\d+)", commit.subject)
    assert match is not None, commit.subject
    subject = commit.subject.replace(match.group(0), "attention N")
    return _Commit(subject, commit.files), int(match.group(1))


def _run_update(
    paths: DataPaths,
    root: Path,
    handle_factory: Any,
    fake_clock: Any,
    *,
    fail_commits: set[str] = frozenset(),  # type: ignore[assignment]
    fail_cfb_commit: str | None = None,
) -> _Outcome:
    handle = handle_factory(_update_cfbd_responses())
    runtime = _runtime(paths, handle, now=lambda: UPDATE_NOW, fake_clock=fake_clock)
    if fail_commits:
        _fail_nfl_commits(runtime, fail_commits)
    if fail_cfb_commit is not None:
        _fail_nfl_commits(runtime, {fail_cfb_commit})
    head = _head(paths)
    site_out = root / "site-out"
    result = ScheduledJob(
        runtime,
        token="test-token",
        now=lambda: UPDATE_NOW,
        trigger="manual",
        update=True,
        site_out=site_out,
    ).run()

    commits = _commits_since(paths, head)
    cfb_commits: list[_Commit] = []
    state_attention = -1
    for commit in commits:
        if commit.subject.startswith(("job: nfl_", "build: nfl ")):
            continue
        if commit.subject.startswith("job: state "):
            normalized, state_attention = _normalize_state(commit)
            cfb_commits.append(normalized)
        else:
            cfb_commits.append(commit)
    state = load_state(paths.job_state)
    nfl_reports = paths.ledger / "nfl_run_reports.jsonl"
    nfl_report_attention = (
        json.loads(nfl_reports.read_text(encoding="utf-8").splitlines()[-1])["attention"]
        if nfl_reports.is_file()
        else None
    )
    return _Outcome(
        exit_code=result.exit_code,
        cfb_items=[i for i in result.items if not _is_nfl_item(i)],
        nfl_items=[i for i in result.items if _is_nfl_item(i)],
        cfb_counts=_cfb_counts(result.counts),
        deploy_ready=result.deploy_ready,
        key_leak_items=sum(1 for i in result.items if i.kind == "site_key_check_failed"),
        site_built=(site_out / "index.html").is_file(),
        last_success_at=state.last_success_at,
        last_attempt_at=state.last_attempt_at,
        last_status=state.last_status,
        retry_pending=state.retry_pending,
        last_build_at=state.last_build_at,
        cfb_commits=cfb_commits,
        state_attention=state_attention,
        all_items=list(result.items),
        nfl_report_attention=nfl_report_attention,
    )


def _isolation_runs(
    pristine: DataPaths,
    tmp_path: Path,
    handle_factory: Any,
    fake_clock: Any,
    monkeypatch: pytest.MonkeyPatch,
    step: str,
) -> tuple[_Outcome, dict[str, tuple[_Outcome, list[str]]]]:
    """The CFB-only baseline, then one NFL-bootstrapped run per failure kind,
    each on its own copy of the pristine vault."""
    fakes = _NflFakes(calls=[])
    _install_fakes(monkeypatch, fakes)

    base_paths = _clone_vault(pristine, tmp_path / "runs" / "baseline")
    baseline = _run_update(base_paths, tmp_path / "runs" / "baseline", handle_factory, fake_clock)
    assert fakes.calls == []  # the baseline vault has no NFL schedules file

    runs: dict[str, tuple[_Outcome, list[str]]] = {}
    for kind in _KINDS:
        root = tmp_path / "runs" / kind
        paths = _clone_vault(pristine, root)
        _bootstrap_nfl(paths, season=2025, frozen_through=2024)
        fakes.calls = []
        fakes.fail = (step, kind)
        fail_commits: set[str] = set()
        if not _raises_from_function(step, kind):
            commit_step = _STEP_NAMES[step][1]
            assert commit_step is not None
            fail_commits = {commit_step}
        outcome = _run_update(paths, root, handle_factory, fake_clock, fail_commits=fail_commits)
        runs[kind] = (outcome, list(fakes.calls))
    fakes.fail = None
    return baseline, runs


def _assert_cfb_unchanged(baseline: _Outcome, outcome: _Outcome) -> None:
    assert outcome.cfb_items == baseline.cfb_items
    assert outcome.cfb_counts == baseline.cfb_counts
    assert outcome.cfb_commits == baseline.cfb_commits
    assert outcome.deploy_ready == baseline.deploy_ready
    assert outcome.site_built == baseline.site_built
    assert outcome.key_leak_items == 0
    assert outcome.last_success_at == baseline.last_success_at
    assert outcome.last_attempt_at == baseline.last_attempt_at
    assert outcome.retry_pending == baseline.retry_pending
    assert outcome.last_build_at == baseline.last_build_at
    # CR-02: the CFB state is saved before the NFL block, so its attention count
    # is the CFB one; the NFL items are counted in the NFL block's own report.
    assert outcome.state_attention == baseline.state_attention
    assert baseline.nfl_report_attention is None
    assert outcome.nfl_report_attention == len(outcome.nfl_items)


def _assert_nfl_failure_only(step: str, kind: str, outcome: _Outcome, calls: list[str]) -> None:
    assert outcome.nfl_items == [_expected_item(step, kind)]
    # Every NFL step ran, the failing one and every later one included.
    assert calls == list(_STEPS)
    # No exception message, URL or team name reaches an attention line.
    assert all("key=" not in i.line and "Team" not in i.line for i in outcome.all_items)
    build_attention_body(outcome.all_items, generated_at=UPDATE_NOW)


def _clean_cfb(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the CFB side of an update run attention-free: no 506 gaps, no unsaved
    ESPN PR week, no review counts."""
    monkeypatch.setattr(
        f"{RUNNER}.find_506_gaps",
        lambda paths, season, games, now: Gaps506(season, [], [], 0),
    )
    monkeypatch.setattr(f"{RUNNER}.find_espnpr_gap", lambda paths, season, games, now: None)
    real = __import__(RUNNER, fromlist=["run_build"]).run_build

    def run_build(*args: Any, **kwargs: Any) -> BuildOutcome:
        outcome = real(*args, **kwargs)
        counts = {**outcome.counts, "review_people_new": 0, "review_unresolved_teams": 0}
        return BuildOutcome(
            blocked=outcome.blocked,
            accepted=outcome.accepted,
            reasons=outcome.reasons,
            counts=counts,
            written=outcome.written,
            committed=outcome.committed,
        )

    monkeypatch.setattr(f"{RUNNER}.run_build", run_build)


# -- D-08 isolation (a): clean CFB + a failing NFL step ------------------------------------------


@pytest.mark.parametrize("step", _STEPS)
def test_isolation_clean_cfb_with_failing_nfl_step_is_exit_4_and_cfb_untouched(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch, step
) -> None:
    _clean_cfb(monkeypatch)
    baseline, runs = _isolation_runs(
        update_vault, tmp_path, mock_transport_factory, fake_clock, monkeypatch, step
    )

    assert baseline.exit_code == 0
    assert baseline.last_status == "ok"
    assert baseline.deploy_ready is True
    assert baseline.site_built is True
    assert baseline.last_success_at == UPDATE_NOW
    assert any(c.subject.startswith("build: all ") for c in baseline.cfb_commits)

    for kind, (outcome, calls) in runs.items():
        _assert_nfl_failure_only(step, kind, outcome, calls)
        _assert_cfb_unchanged(baseline, outcome)
        # The added attention item makes the run exit 4: never 3, never 0. The
        # saved CFB state stays "ok" (CR-02: it is saved before the NFL block).
        assert outcome.exit_code == 4, kind
        assert outcome.last_status == baseline.last_status == "ok", kind
        assert outcome.last_success_at == UPDATE_NOW
        assert outcome.retry_pending is False
        assert outcome.deploy_ready is True


# -- D-08 isolation (b): CFB attention baseline + a failing NFL step ------------------------------


@pytest.mark.parametrize("step", _STEPS)
def test_isolation_cfb_attention_with_failing_nfl_step_matches_cfb_baseline(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch, step
) -> None:
    baseline, runs = _isolation_runs(
        update_vault, tmp_path, mock_transport_factory, fake_clock, monkeypatch, step
    )

    assert baseline.exit_code == 4
    assert "sports506_missing" in {i.kind for i in baseline.cfb_items}
    assert baseline.last_status == "attention"

    for kind, (outcome, calls) in runs.items():
        _assert_nfl_failure_only(step, kind, outcome, calls)
        _assert_cfb_unchanged(baseline, outcome)
        assert outcome.exit_code == baseline.exit_code == 4, kind
        assert outcome.last_status == baseline.last_status


# -- D-08 isolation (c): CFB failure baseline + a failing NFL step --------------------------------


@pytest.mark.parametrize("step", _STEPS)
def test_isolation_cfb_failure_with_failing_nfl_step_matches_cfb_baseline(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch, step
) -> None:
    def _boom(*args: Any, **kwargs: Any) -> Gaps506:
        raise ValueError(_SECRET)

    monkeypatch.setattr(f"{RUNNER}.find_506_gaps", _boom)
    prior = load_state(update_vault.job_state)
    baseline, runs = _isolation_runs(
        update_vault, tmp_path, mock_transport_factory, fake_clock, monkeypatch, step
    )

    assert "sports506_step_failed" in {i.kind for i in baseline.cfb_items}
    assert baseline.last_status == "failed"
    assert baseline.last_success_at == prior.last_success_at

    for kind, (outcome, calls) in runs.items():
        _assert_nfl_failure_only(step, kind, outcome, calls)
        _assert_cfb_unchanged(baseline, outcome)
        assert outcome.exit_code == baseline.exit_code, kind
        assert outcome.last_status == "failed"


# -- D-08 isolation (d): exit 3 stays a CFB-only outcome -----------------------------------------


def test_isolation_cfb_commit_error_still_exits_3_before_any_nfl_step(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    fakes = _NflFakes(calls=[])
    _install_fakes(monkeypatch, fakes)
    paths = _clone_vault(update_vault, tmp_path / "runs" / "cfb3")
    _bootstrap_nfl(paths, season=2025, frozen_through=2024)
    handle = mock_transport_factory(_update_cfbd_responses())
    runtime = _runtime(paths, handle, now=lambda: UPDATE_NOW, fake_clock=fake_clock)
    _fail_nfl_commits(runtime, {"cfbd"})
    before = load_state(paths.job_state)

    result = ScheduledJob(
        runtime,
        token="test-token",
        now=lambda: UPDATE_NOW,
        trigger="manual",
        update=True,
        site_out=tmp_path / "site-out",
    ).run()

    assert result.exit_code == 3
    assert push_failed("cfbd") in result.items
    assert fakes.calls == []
    assert load_state(paths.job_state) == before  # no state save on exit 3


def test_isolation_every_nfl_commit_failing_never_reaches_exit_3(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    fakes = _NflFakes(calls=[], fail=("build", "commit"))
    _install_fakes(monkeypatch, fakes)
    root = tmp_path / "runs" / "all"
    paths = _clone_vault(update_vault, root)
    _bootstrap_nfl(paths, season=2025, frozen_through=2024)

    outcome = _run_update(
        paths,
        root,
        mock_transport_factory,
        fake_clock,
        fail_commits={"nfl_schedules", "nfl_pbp", "nfl_rr", "nfl_wikipedia"},
    )

    assert outcome.exit_code == 4
    assert outcome.nfl_items == [
        push_failed("nfl_schedules"),
        push_failed("nfl_pbp"),
        push_failed("nfl_rr"),
        push_failed("nfl_wikipedia"),
        push_failed("nfl_build"),
    ]
    assert outcome.last_status == "attention"
    assert outcome.last_attempt_at == UPDATE_NOW
    assert outcome.deploy_ready is True
    assert fakes.calls == list(_STEPS)


def test_an_error_escaping_the_nfl_block_is_one_attention_item(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    fakes = _NflFakes(calls=[])
    _install_fakes(monkeypatch, fakes)

    def _boom(today: date) -> int:
        raise VaultCommitError("git subcommand push exited 1")

    monkeypatch.setattr(f"{RUNNER}.nfl_collectable_season", _boom)
    root = tmp_path / "runs" / "outer"
    paths = _clone_vault(update_vault, root)
    _bootstrap_nfl(paths, season=2025, frozen_through=2024)

    outcome = _run_update(paths, root, mock_transport_factory, fake_clock)

    assert outcome.nfl_items == [step_failed("nfl", "VaultCommitError")]
    assert outcome.exit_code == 4
    assert outcome.last_status == "attention"
    assert fakes.calls == []
    assert outcome.nfl_report_attention == 1


# -- CR-02: the CFB state is saved and pushed before any NFL step ---------------------------------


def _remote_file(paths: DataPaths, rel: str) -> str:
    remote = _git(paths, "remote", "get-url", "origin").strip()
    return subprocess.run(
        ["git", "--git-dir", remote, "show", f"main:{rel}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _push_conflicting_schedules(paths: DataPaths, other: Path) -> None:
    """Push different bytes for the NFL schedules file from a second clone, as a
    local `collect nflverse` would during the job run."""
    remote = _git(paths, "remote", "get-url", "origin").strip()
    subprocess.run(["git", "clone", "-q", remote, str(other)], check=True, capture_output=True)
    target = other / "raw" / NFLVERSE_SCHEDULES_PATH
    target.write_bytes(target.read_bytes() + b"remote,edit\n")
    ident = ("-c", "user.name=Other", "-c", "user.email=other@example.com")
    for args in (("add", "-A"), ("commit", "-q", "-m", "other: schedules"), ("push", "-q")):
        subprocess.run(["git", *ident, "-C", str(other), *args], check=True, capture_output=True)


def test_nfl_push_conflict_leaves_the_cfb_state_pushed_and_exits_4(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    fakes = _NflFakes(calls=[])
    _install_fakes(monkeypatch, fakes)
    root = tmp_path / "runs" / "conflict"
    paths = _clone_vault(update_vault, root)
    _bootstrap_nfl(paths, season=2025, frozen_through=2024)
    seen: dict[str, str] = {}

    def run_schedules(self: Any, *, refresh: bool, dry_run: bool) -> BatchSummary:
        fakes.hit("schedules")
        seen["remote_state"] = _remote_file(paths, "ledger/job_state.json")
        _push_conflicting_schedules(paths, root / "other")
        local = paths.raw / NFLVERSE_SCHEDULES_PATH
        local.write_bytes(local.read_bytes() + b"local,edit\n")
        return _batch("nfl_nflverse")

    monkeypatch.setattr(NflverseCollector, "run_schedules", run_schedules)

    outcome = _run_update(paths, root, mock_transport_factory, fake_clock)

    # The real pull --rebase conflict fails the NFL push and keeps the NFL
    # commit locally; the NFL report commit then fails to push the same way.
    assert outcome.nfl_items == [push_failed("nfl_schedules"), push_failed("nfl_state")]
    assert outcome.exit_code == 4
    assert fakes.calls == list(_STEPS)
    # The CFB state was already on the remote when the first NFL step began,
    # and it is this run's state.
    local_state = paths.job_state.read_text(encoding="utf-8")
    assert seen["remote_state"] == local_state
    assert json.loads(local_state)["last_attempt_at"].startswith("2025")
    assert _remote_file(paths, "ledger/run_reports.jsonl") == (
        paths.ledger / "run_reports.jsonl"
    ).read_text(encoding="utf-8")
    assert outcome.deploy_ready is True
    assert outcome.last_attempt_at == UPDATE_NOW


@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit, RuntimeError])
def test_an_nfl_step_that_dies_after_the_cfb_save_cannot_lose_the_cfb_state(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch, error
) -> None:
    """A hung NFL step is killed from outside (the Actions timeout); a
    BaseException stands in for that kill, a RuntimeError for a plain raise."""
    fakes = _NflFakes(calls=[])
    _install_fakes(monkeypatch, fakes)
    root = tmp_path / "runs" / "dies"
    paths = _clone_vault(update_vault, root)
    _bootstrap_nfl(paths, season=2025, frozen_through=2024)
    before = load_state(paths.job_state)

    def run_pbp(self: Any, seasons: Any, *, dry_run: bool) -> NflverseSummary:
        fakes.hit("pbp")
        raise error()

    monkeypatch.setattr(NflverseCollector, "run_pbp", run_pbp)
    handle = mock_transport_factory(_update_cfbd_responses())
    runtime = _runtime(paths, handle, now=lambda: UPDATE_NOW, fake_clock=fake_clock)
    job = ScheduledJob(
        runtime,
        token="test-token",
        now=lambda: UPDATE_NOW,
        trigger="manual",
        update=True,
        site_out=root / "site-out",
    )

    if issubclass(error, Exception):
        result = job.run()
        assert result.exit_code == 4
        assert step_failed("nflverse", "RuntimeError") in result.items
        assert result.deploy_ready is True
    else:
        with pytest.raises(error):
            job.run()

    assert fakes.calls[:2] == ["schedules", "pbp"]
    remote_state = json.loads(_remote_file(paths, "ledger/job_state.json"))
    assert remote_state == json.loads(paths.job_state.read_text(encoding="utf-8"))
    state = load_state(paths.job_state)
    assert state != before
    assert state.last_attempt_at == UPDATE_NOW
    assert state.last_build_at == UPDATE_NOW


# -- CR-02 residual: the CLI's result files carry the CFB outcome before any NFL step -----------


class _FixedNow(datetime):
    """cli.datetime stand-in: every `now()` (the job clock and the attention
    body's timestamp) is UPDATE_NOW, so two runs write byte-equal files."""

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        return UPDATE_NOW


def _cli_update_run(
    paths: DataPaths,
    root: Path,
    handle_factory: Any,
    fake_clock: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, Path]:
    """`booth-review job run --update` through main(), with --result-out and
    --attention-out under root/out; returns (exit code, out dir). A BaseException
    raised inside the run propagates to the caller."""
    handle = handle_factory(_update_cfbd_responses())
    runtime = _runtime(paths, handle, now=lambda: UPDATE_NOW, fake_clock=fake_clock)
    monkeypatch.setattr(cli, "build_runtime", lambda **kwargs: runtime)
    monkeypatch.setattr(cli, "datetime", _FixedNow)
    out = root / "out"
    code = main(
        [
            "job",
            "run",
            "--trigger",
            "manual",
            "--update",
            "--site-out",
            str(root / "site-out"),
            "--result-out",
            str(out / "result.txt"),
            "--attention-out",
            str(out / "attention.md"),
        ]
    )
    return code, out


def _outputs(out: Path) -> dict[str, bytes]:
    return {name: (out / name).read_bytes() for name in ("result.txt", "attention.md")}


def _cfb_only_outputs(
    pristine: DataPaths,
    tmp_path: Path,
    handle_factory: Any,
    fake_clock: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, bytes]:
    """The files a run with the same CFB outcome and no NFL block writes."""
    root = tmp_path / "runs" / "cli-baseline"
    paths = _clone_vault(pristine, root)
    code, out = _cli_update_run(paths, root, handle_factory, fake_clock, monkeypatch)
    assert code == 4  # update_vault's CFB side has attention (506 weeks to save)
    files = _outputs(out)
    assert files["result.txt"] == b"deploy_ready=true\nstale_only=false\n"
    assert b"nfl" not in files["attention.md"]
    return files


def _no_temp_files(out: Path) -> bool:
    return sorted(p.name for p in out.iterdir()) == ["attention.md", "result.txt"]


@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit])
def test_cli_result_files_keep_the_cfb_outcome_when_the_nfl_block_is_killed(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch, error
) -> None:
    """A BaseException from an NFL step stands in for the workflow's step
    timeout killing a hung NFL step: the deploy step must still find the CFB
    outcome in --result-out and --attention-out."""
    fakes = _NflFakes(calls=[])
    _install_fakes(monkeypatch, fakes)
    baseline = _cfb_only_outputs(
        update_vault, tmp_path, mock_transport_factory, fake_clock, monkeypatch
    )

    def run_pbp(self: Any, seasons: Any, *, dry_run: bool) -> NflverseSummary:
        fakes.hit("pbp")
        raise error()

    monkeypatch.setattr(NflverseCollector, "run_pbp", run_pbp)
    root = tmp_path / "runs" / "killed"
    paths = _clone_vault(update_vault, root)
    _bootstrap_nfl(paths, season=2025, frozen_through=2024)

    with pytest.raises(error):
        _cli_update_run(paths, root, mock_transport_factory, fake_clock, monkeypatch)

    assert fakes.calls == ["schedules", "pbp"]
    out = root / "out"
    assert _outputs(out) == baseline
    assert _no_temp_files(out)


def test_cli_result_files_are_written_before_the_nfl_block_and_rewritten_after_it(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    fakes = _NflFakes(calls=[])
    _install_fakes(monkeypatch, fakes)
    baseline = _cfb_only_outputs(
        update_vault, tmp_path, mock_transport_factory, fake_clock, monkeypatch
    )
    root = tmp_path / "runs" / "normal"
    out = root / "out"
    seen: dict[str, dict[str, bytes]] = {}

    def run_schedules(self: Any, *, refresh: bool, dry_run: bool) -> BatchSummary:
        fakes.hit("schedules")
        seen["first_nfl_step"] = _outputs(out)
        return _batch("nfl_nflverse")

    def run_pbp(self: Any, seasons: Any, *, dry_run: bool) -> NflverseSummary:
        fakes.hit("pbp")
        raise RuntimeError(_SECRET)

    monkeypatch.setattr(NflverseCollector, "run_schedules", run_schedules)
    monkeypatch.setattr(NflverseCollector, "run_pbp", run_pbp)
    paths = _clone_vault(update_vault, root)
    _bootstrap_nfl(paths, season=2025, frozen_through=2024)

    code, _ = _cli_update_run(paths, root, mock_transport_factory, fake_clock, monkeypatch)

    # The CFB-only files were already in place when the first NFL step ran.
    assert seen["first_nfl_step"] == baseline
    # The final rewrite adds the NFL items after the CFB ones; NFL makes it 4 at most.
    assert code == 4
    assert fakes.calls == list(_STEPS)
    final = _outputs(out)
    assert final["result.txt"] == b"deploy_ready=true\nstale_only=false\n"
    nfl_line = b"- nflverse step failed: RuntimeError"
    assert final["attention.md"].split(b"\n") == [*baseline["attention.md"].split(b"\n"), nfl_line]
    assert _no_temp_files(out)


def test_an_interrupted_final_rewrite_leaves_the_complete_cfb_only_files(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    """The final rewrite goes through a temp file and a rename: a kill just
    before the rename leaves the early CFB-only files whole, with no temp file.
    The pbp failure gives the final outcome an NFL item, so it differs."""
    fakes = _NflFakes(calls=[], fail=("pbp", "runtime"))
    _install_fakes(monkeypatch, fakes)
    baseline = _cfb_only_outputs(
        update_vault, tmp_path, mock_transport_factory, fake_clock, monkeypatch
    )
    root = tmp_path / "runs" / "rename"
    out = root / "out"
    armed: list[bool] = []
    real_replace = Path.replace

    def replace(self: Path, target: Any) -> Path:
        if armed and Path(target).parent == out:
            raise KeyboardInterrupt
        return real_replace(self, target)

    def run_schedules(self: Any, *, refresh: bool, dry_run: bool) -> BatchSummary:
        fakes.hit("schedules")
        armed.append(True)  # the early write is done; kill the next one
        return _batch("nfl_nflverse")

    monkeypatch.setattr(Path, "replace", replace)
    monkeypatch.setattr(NflverseCollector, "run_schedules", run_schedules)
    paths = _clone_vault(update_vault, root)
    _bootstrap_nfl(paths, season=2025, frozen_through=2024)

    with pytest.raises(KeyboardInterrupt):
        _cli_update_run(paths, root, mock_transport_factory, fake_clock, monkeypatch)

    assert fakes.calls == list(_STEPS)
    assert _outputs(out) == baseline
    assert _no_temp_files(out)


def test_on_cfb_result_gets_the_cfb_only_outcome_before_the_first_nfl_step(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    fakes = _NflFakes(calls=[], fail=("pbp", "runtime"))
    _install_fakes(monkeypatch, fakes)
    root = tmp_path / "runs" / "callback"
    paths = _clone_vault(update_vault, root)
    _bootstrap_nfl(paths, season=2025, frozen_through=2024)
    got: list[tuple[list[str], JobRunResult]] = []

    handle = mock_transport_factory(_update_cfbd_responses())
    runtime = _runtime(paths, handle, now=lambda: UPDATE_NOW, fake_clock=fake_clock)
    result = ScheduledJob(
        runtime,
        token="test-token",
        now=lambda: UPDATE_NOW,
        trigger="manual",
        update=True,
        site_out=root / "site-out",
        on_cfb_result=lambda cfb: got.append((list(fakes.calls), cfb)),
    ).run()

    assert len(got) == 1
    calls_then, cfb = got[0]
    assert calls_then == []
    assert cfb.deploy_ready is True
    assert cfb.exit_code == 4
    assert not any(_is_nfl_item(i) for i in cfb.items)
    assert _nfl_counts(cfb.counts) == {}
    # The final outcome adds the NFL item; the CFB-only result kept its own list.
    assert result.items == [*cfb.items, step_failed("nflverse", "RuntimeError")]
    assert result.deploy_ready is True
    assert result.exit_code == 4


def test_a_failing_on_cfb_result_is_one_attention_item_and_the_nfl_block_still_runs(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    fakes = _NflFakes(calls=[])
    _install_fakes(monkeypatch, fakes)
    root = tmp_path / "runs" / "callback-fails"
    paths = _clone_vault(update_vault, root)
    _bootstrap_nfl(paths, season=2025, frozen_through=2024)

    def _unwritable(cfb: JobRunResult) -> None:
        raise PermissionError(_SECRET)

    handle = mock_transport_factory(_update_cfbd_responses())
    runtime = _runtime(paths, handle, now=lambda: UPDATE_NOW, fake_clock=fake_clock)
    result = ScheduledJob(
        runtime,
        token="test-token",
        now=lambda: UPDATE_NOW,
        trigger="manual",
        update=True,
        site_out=root / "site-out",
        on_cfb_result=_unwritable,
    ).run()

    assert step_failed("result_out", "PermissionError") in result.items
    assert fakes.calls == list(_STEPS)
    assert result.exit_code == 4
    assert result.deploy_ready is True
    build_attention_body(result.items, generated_at=UPDATE_NOW)


# -- NFL step results become NFL attention items ------------------------------------------------


def _nfl_update_run(
    update_vault: DataPaths,
    tmp_path: Path,
    handle_factory: Any,
    fake_clock: Any,
    *,
    frozen_through: int = 2024,
    name: str = "nfl",
    **job_kwargs: Any,
) -> tuple[Any, DataPaths]:
    root = tmp_path / "runs" / name
    paths = _clone_vault(update_vault, root)
    _bootstrap_nfl(paths, season=2025, frozen_through=frozen_through)
    handle = handle_factory(_update_cfbd_responses())
    runtime = _runtime(paths, handle, now=lambda: UPDATE_NOW, fake_clock=fake_clock)
    job_kwargs.setdefault("update", True)
    if job_kwargs["update"]:
        job_kwargs.setdefault("site_out", root / "site-out")
    result = ScheduledJob(
        runtime, token="test-token", now=lambda: UPDATE_NOW, trigger="manual", **job_kwargs
    ).run()
    return result, paths


def test_nfl_rr_uses_its_own_cap_and_reports_backlog(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    caps: list[int] = []
    fakes = _NflFakes(calls=[], rr_backlog=3, rr_caps=caps)
    _install_fakes(monkeypatch, fakes)

    result, _ = _nfl_update_run(
        update_vault, tmp_path, mock_transport_factory, fake_clock, nfl_rr_cap=7, rr_cap=55
    )

    assert caps == [7]
    assert nfl_rr_backlog(3, 7) in result.items
    assert result.counts["nfl_rr_backlog"] == 3
    assert "rr_backlog" not in {i.kind for i in result.items}


def test_nfl_rr_cap_defaults_to_40(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    caps: list[int] = []
    _install_fakes(monkeypatch, _NflFakes(calls=[], rr_caps=caps))
    _nfl_update_run(update_vault, tmp_path, mock_transport_factory, fake_clock)
    assert caps == [NFL_REFRESH_CAP_DEFAULT] == [40]


def test_nfl_gaps_drift_and_past_freeze_become_attention_items(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    fakes = _NflFakes(calls=[], gaps=NflGaps(2025, ["3"], ["2"], 3, 0), drift=(2019, 2020))
    _install_fakes(monkeypatch, fakes)

    result, _ = _nfl_update_run(
        update_vault, tmp_path, mock_transport_factory, fake_clock, frozen_through=2023
    )

    nfl_items = [i for i in result.items if _is_nfl_item(i)]
    assert nfl_items == [
        nfl_506_missing(2025, ["3"]),
        nfl_506_stale(2025, ["2"]),
        nfl_schedule_drift(2),
        nfl_season_past_freeze(2024, date(2025, 3, 1)),
    ]
    assert result.counts["nfl_506_missing"] == 1
    assert result.counts["nfl_506_stale"] == 1
    assert result.counts["nfl_schedule_drift"] == 2
    assert result.counts["nfl_past_freeze"] == 1
    assert result.exit_code == 4
    assert result.deploy_ready is True


def test_nfl_build_runs_in_update_mode_with_the_season_range_and_reports_review(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    kwargs: list[dict[str, Any]] = []
    fakes = _NflFakes(
        calls=[],
        build_kwargs=kwargs,
        build_blocked=True,
        build_counts={
            "games": 12,
            "standalone": 3,
            "override_errors": 2,
            "unresolved_crew_names": 4,
        },
    )
    _install_fakes(monkeypatch, fakes)

    result, _ = _nfl_update_run(update_vault, tmp_path, mock_transport_factory, fake_clock)

    assert len(kwargs) == 1
    call = kwargs[0]
    assert list(call["seasons"]) == list(range(2014, 2026))
    assert call["include_playoffs"] is False
    assert call["check_acceptance"] is False
    assert call["commit"] is True
    assert call["now"] == UPDATE_NOW
    assert nfl_build_blocked(2) in result.items
    assert nfl_review_due(4) in result.items
    assert result.counts["nfl_build_games"] == 12
    # A blocked NFL build never holds the CFB deploy.
    assert result.deploy_ready is True
    assert result.exit_code == 4


def test_nfl_build_is_skipped_outside_update_mode_and_in_dry_run(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    fakes = _NflFakes(calls=[])
    _install_fakes(monkeypatch, fakes)

    _nfl_update_run(update_vault, tmp_path, mock_transport_factory, fake_clock, update=False)
    assert fakes.calls == ["schedules", "pbp", "rr", "wikipedia", "gaps", "checks"]

    fakes.calls = []
    _nfl_update_run(
        update_vault, tmp_path, mock_transport_factory, fake_clock, name="dry", dry_run=True
    )
    assert fakes.calls == ["schedules", "pbp", "rr", "wikipedia", "gaps", "checks"]


def test_nfl_build_no_commit_passes_commit_false(
    update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch
) -> None:
    kwargs: list[dict[str, Any]] = []
    _install_fakes(monkeypatch, _NflFakes(calls=[], build_kwargs=kwargs))
    _nfl_update_run(update_vault, tmp_path, mock_transport_factory, fake_clock, commit=False)
    assert [c["commit"] for c in kwargs] == [False]
