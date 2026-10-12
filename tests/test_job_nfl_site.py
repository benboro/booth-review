"""Offline tests for the job's NFL site step (999.5 plan 09, D-18/D-20).

The flag-on job carries the vault's last good nfl-data.json into the site dir,
rebuilds and refreshes it after the NFL build, and reports when the site dir ends
up without it. Every NFL problem is an attention item that joins the final outcome
only; CFB's deploy_ready, result file and commits never change. All data is
synthetic and the vaults are throwaway git repos.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest
import test_job_nfl
from test_job_nfl import (
    RUNNER,
    _bootstrap_nfl,
    _clone_vault,
    _install_fakes,
    _NflFakes,
    update_vault,  # noqa: F401  (fixture re-export)
)
from test_job_runner import UPDATE_NOW, _runtime, _update_cfbd_responses

from booth_review.build.site_assembly import load_nfl_site_payload
from booth_review.config import DataPaths
from booth_review.job.attention import (
    AttentionItem,
    build_attention_body,
    nfl_site_carried_live,
    nfl_site_failed,
    nfl_site_key_check_failed,
    step_failed,
)
from booth_review.job.runner import JobRunResult, ScheduledJob
from booth_review.nfl.pipeline import NflBuildOutcome

FIXTURE = Path(__file__).parent / "fixtures" / "contract" / "nfl-data.fixture.json"
_ = test_job_nfl  # keep the module (and its fixtures) importable by name


def _canonical() -> bytes:
    return load_nfl_site_payload(FIXTURE)[1]


def _variant() -> bytes:
    """Valid nfl-data bytes that differ from the fixture's canonical bytes."""
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["constants"]["low_n_threshold"] = raw["constants"]["low_n_threshold"] + 1
    return json.dumps(raw).encode("utf-8")


class _Run:
    def __init__(self, result: JobRunResult, cfb: list[JobRunResult], site: Path, paths: DataPaths):
        self.result = result
        self.cfb = cfb
        self.site = site
        self.paths = paths

    @property
    def kinds(self) -> list[str]:
        return [item.kind for item in self.result.items]

    @property
    def site_file(self) -> Path:
        return self.site / "nfl-data.json"


def _go(
    update_vault: DataPaths,  # noqa: F811
    tmp_path: Path,
    handle_factory: Any,
    fake_clock: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    nfl_site: bool = True,
    bootstrap: bool = False,
    vault_file: bytes | None = None,
    build: Any = None,
    refresh: Any = None,
    dry_run: bool = False,
    name: str = "run",
    build_kwargs: list[dict[str, Any]] | None = None,
) -> _Run:
    root = tmp_path / "runs" / name
    paths = _clone_vault(update_vault, root)
    if bootstrap:
        _bootstrap_nfl(paths, season=2025, frozen_through=2024)
    if vault_file is not None:
        paths.processed.mkdir(parents=True, exist_ok=True)
        (paths.processed / "nfl-data.json").write_bytes(vault_file)
    fakes = _NflFakes(calls=[], build_kwargs=build_kwargs)
    _install_fakes(monkeypatch, fakes)
    if build is not None:

        def fake_build(p: DataPaths, reference: Path, **kwargs: Any) -> NflBuildOutcome:
            if build_kwargs is not None:
                build_kwargs.append(kwargs)
            counts = build(p)
            return NflBuildOutcome(
                blocked=False, written=(), counts=counts, acceptance=None, committed=False
            )

        monkeypatch.setattr(f"{RUNNER}.run_nfl_build", fake_build)
    if refresh is not None:
        monkeypatch.setattr(f"{RUNNER}.refresh_nfl_data", refresh)
    handle = handle_factory(_update_cfbd_responses())
    runtime = _runtime(paths, handle, now=lambda: UPDATE_NOW, fake_clock=fake_clock)
    site = root / "site-out"
    cfb: list[JobRunResult] = []
    result = ScheduledJob(
        runtime,
        token="test-token",
        now=lambda: UPDATE_NOW,
        trigger="manual",
        update=True,
        dry_run=dry_run,
        site_out=site,
        nfl_site=nfl_site,
        on_cfb_result=cfb.append,
    ).run()
    return _Run(result, cfb, site, paths)


def _write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


@pytest.fixture
def args(update_vault, mock_transport_factory, fake_clock, tmp_path, monkeypatch):  # noqa: F811
    def run(**kwargs: Any) -> _Run:
        return _go(
            update_vault, tmp_path, mock_transport_factory, fake_clock, monkeypatch, **kwargs
        )

    return run


# -- attention constructors ---------------------------------------------------------------


def test_constructors_are_count_free_and_validated() -> None:
    items = [
        nfl_site_failed("missing"),
        nfl_site_failed("invalid"),
        nfl_site_failed("carry_over_invalid"),
        nfl_site_key_check_failed(),
        nfl_site_carried_live(),
    ]
    assert nfl_site_carried_live().line == "NFL data not refreshed: carried live copy"
    assert all(item.severity == "attention" for item in items)
    build_attention_body(items, generated_at=UPDATE_NOW)
    with pytest.raises(ValueError):
        nfl_site_failed("boom")  # type: ignore[arg-type]


# -- flag off ---------------------------------------------------------------------------------


def test_flag_off_has_no_nfl_file_no_items_and_site_data_off(args) -> None:
    kwargs: list[dict[str, Any]] = []
    run = args(
        nfl_site=False,
        bootstrap=True,
        vault_file=_canonical(),
        build=lambda p: {"games": 1},
        build_kwargs=kwargs,
    )
    assert not run.site_file.exists()
    assert not (run.site / "sports").exists()
    assert not any(kind.startswith("nfl_site") for kind in run.kinds)
    assert kwargs[0]["site_data"] is False
    assert run.result.deploy_ready


# -- carry-over -------------------------------------------------------------------------------


def test_flag_on_carries_the_valid_vault_file_when_the_nfl_block_is_skipped(args) -> None:
    run = args(vault_file=_canonical())
    assert run.site_file.read_bytes() == _canonical()
    assert run.result.deploy_ready
    assert not any(kind.startswith("nfl_site") for kind in run.kinds)


def test_invalid_carry_over_is_one_item_and_leaves_cfb_untouched(args) -> None:
    run = args(vault_file=b'{"not": "the contract"}')
    assert not run.site_file.exists()
    assert run.result.deploy_ready
    assert run.kinds.count("nfl_site_failed") == 1
    assert nfl_site_failed("carry_over_invalid") in run.result.items
    assert nfl_site_carried_live() in run.result.items
    # CFB-only outcome handed to the caller carries no NFL item.
    assert not any(i.kind.startswith("nfl") for i in run.cfb[0].items)
    assert run.cfb[0].deploy_ready


def test_unparseable_carry_over_is_the_same_invalid_item(args) -> None:
    run = args(vault_file=b"not json at all")
    assert nfl_site_failed("carry_over_invalid") in run.result.items
    assert run.result.deploy_ready


def _unique_nfl_token() -> str:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    site_raw = (FIXTURE.parent / "site-data.fixture.json").read_text(encoding="utf-8")
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)

    walk(raw)
    candidates = sorted({s for s in found if len(s) >= 5 and s not in site_raw}, key=len)
    assert candidates
    return candidates[-1]


def test_carry_over_with_the_key_is_dropped_and_cfb_still_deploys(
    args, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CFBD_API_KEY", _unique_nfl_token())
    run = args(vault_file=_canonical())
    assert nfl_site_key_check_failed() in run.result.items
    assert nfl_site_carried_live() in run.result.items
    assert not run.site_file.exists()
    assert run.result.deploy_ready
    for path in run.site.rglob("*"):
        if path.is_file():
            assert _unique_nfl_token().encode() not in path.read_bytes()


def test_no_vault_file_in_the_offseason_reports_carried_live(args) -> None:
    run = args()
    assert not run.site_file.exists()
    assert run.kinds.count("nfl_site_carried_live") == 1
    assert run.result.deploy_ready
    assert not any(i.kind.startswith("nfl") for i in run.cfb[0].items)


# -- NFL block --------------------------------------------------------------------------------


def test_build_writes_a_new_file_and_it_replaces_the_carry_over(args) -> None:
    new = _variant()

    def build(paths: DataPaths) -> dict[str, int]:
        _write(paths.processed / "nfl-data.json", new)
        return {"games": 3}

    kwargs: list[dict[str, Any]] = []
    run = args(bootstrap=True, vault_file=_canonical(), build=build, build_kwargs=kwargs)
    assert kwargs[0]["site_data"] is True
    assert run.site_file.read_bytes() == load_nfl_site_payload_bytes(new)
    assert run.site_file.read_bytes() != _canonical()
    assert "nfl_site_carried_live" not in run.kinds
    assert not any(kind.startswith("nfl_site_") for kind in run.kinds)


def test_site_data_failed_count_is_one_item_and_keeps_the_carry_over(args) -> None:
    run = args(
        bootstrap=True,
        vault_file=_canonical(),
        build=lambda p: {"games": 2, "site_data_failed": 1},
    )
    assert nfl_site_failed("invalid") in run.result.items
    assert run.site_file.read_bytes() == _canonical()
    assert "nfl_site_carried_live" not in run.kinds
    assert run.result.counts["nfl_build_games"] == 2


def test_build_without_a_vault_file_reports_missing_and_carried_live(args) -> None:
    run = args(bootstrap=True, build=lambda p: {"games": 1})
    assert nfl_site_failed("missing") in run.result.items
    assert nfl_site_carried_live() in run.result.items
    assert not run.site_file.exists()


def test_injected_step_error_is_one_item_and_cfb_is_unchanged(
    args, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refresh(**kwargs: Any) -> Any:
        raise RuntimeError("boom with private detail")

    run = args(
        bootstrap=True, vault_file=_canonical(), build=lambda p: {"games": 1}, refresh=refresh
    )
    assert step_failed("nfl_site", "RuntimeError") in run.result.items
    assert run.site_file.read_bytes() == _canonical()
    assert run.result.deploy_ready
    assert run.result.exit_code <= 4
    assert run.cfb[0].deploy_ready
    assert run.cfb[0].exit_code <= 4
    assert not any(i.kind.startswith("nfl") for i in run.cfb[0].items)
    assert all("private" not in item.line for item in run.result.items)


def test_new_file_with_the_key_keeps_the_carry_over(args, monkeypatch: pytest.MonkeyPatch) -> None:
    token = _unique_nfl_token()
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    # The carry-over must be clean, so write it first under a different key,
    # then switch the key before the NFL block via the build step.
    monkeypatch.setenv("CFBD_API_KEY", "SENTINEL-UPDATE-KEY-ABC")

    def build(paths: DataPaths) -> dict[str, int]:
        _write(paths.processed / "nfl-data.json", json.dumps(raw).encode())
        monkeypatch.setenv("CFBD_API_KEY", token)
        return {"games": 1}

    run = args(bootstrap=True, vault_file=_variant(), build=build)
    assert nfl_site_key_check_failed() in run.result.items
    assert run.site_file.read_bytes() == load_nfl_site_payload_bytes(_variant())
    assert run.result.deploy_ready


def load_nfl_site_payload_bytes(body: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.json"
        p.write_bytes(body)
        return load_nfl_site_payload(p)[1]


def test_refresh_without_a_configured_key_is_a_key_check_item(
    args, monkeypatch: pytest.MonkeyPatch
) -> None:
    from booth_review.build.site_assembly import NflRefreshResult

    def refresh(**kwargs: Any) -> NflRefreshResult:
        return NflRefreshResult(games=1, key_checked=False, replaced=False)

    run = args(
        bootstrap=True, vault_file=_canonical(), build=lambda p: {"games": 1}, refresh=refresh
    )
    assert nfl_site_key_check_failed() in run.result.items
    assert run.site_file.read_bytes() == _canonical()


def test_dry_run_never_runs_the_site_step_or_reports_carried_live(args) -> None:
    run = args(dry_run=True, bootstrap=True, vault_file=_canonical())
    assert "nfl_site_carried_live" not in run.kinds
    assert not any(kind.startswith("nfl_site") for kind in run.kinds)


def test_items_stay_count_only(args) -> None:
    run = args(vault_file=b"{}")
    body = build_attention_body(run.result.items, generated_at=UPDATE_NOW)
    assert "?" not in body
    assert isinstance(run.result.items[0], AttentionItem)
