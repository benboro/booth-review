"""Tests for the AUTO-01 workflow/gitattributes templates (ops/vault/) and
the 0.2.1 version bump.

`ops/vault/collect.yml` and `ops/vault/gitattributes` are templates: they are
installed into the *private* data repo's own working copy (Plan 07, with the
user's OK), never activated in this (public) repo. Text assertions here read
the files directly (`Path.read_text`); the union-merge proof drives real git
against a local bare remote plus two clones under `tmp_path`, with no network
involved, matching `tests/test_vault.py`'s own fixture style.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

import booth_review
from booth_review.errors import VaultCommitError
from booth_review.vault import VaultRepo, batch_message

WORKFLOW_PATH = Path("ops/vault/collect.yml")
GITATTRIBUTES_PATH = Path("ops/vault/gitattributes")
CI_PATH = Path(".github/workflows/ci.yml")

WORKFLOW_TEXT = WORKFLOW_PATH.read_text(encoding="utf-8")
GITATTRIBUTES_TEXT = GITATTRIBUTES_PATH.read_text(encoding="utf-8")
CI_TEXT = CI_PATH.read_text(encoding="utf-8")


def _non_comment_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.strip().startswith("#")]


def _run_ok(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True, text=True)


# -- version ---------------------------------------------------------------------------------


def test_workflow_and_ci_parse_as_yaml_with_expected_structure() -> None:
    # GitHub rejects a workflow that isn't valid YAML without running any job,
    # which text assertions alone can't catch (an unquoted ": " in a step name).
    workflow = yaml.safe_load(WORKFLOW_TEXT)
    yaml.safe_load(CI_TEXT)

    # PyYAML reads the bare `on:` key as boolean True (YAML 1.1).
    triggers = workflow[True]
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    steps = workflow["jobs"]["collect"]["steps"]
    assert all(isinstance(step.get("name", ""), str) for step in steps)
    assert any("JOB_REF" in step.get("name", "") for step in steps)


def test_version_is_0_2_1() -> None:
    assert booth_review.__version__ == "0.2.1"


def test_pyproject_declares_0_2_1() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.2.1"' in pyproject


# -- collect.yml: schedule / triggers ----------------------------------------------------------


def test_workflow_has_five_america_new_york_timezone_entries() -> None:
    # 2 main slots (D-11) + 3 backup-slot groups (D-12: Sun afternoon/evening,
    # Wed late, Thu daytime) -- every schedule entry uses the same timezone.
    assert WORKFLOW_TEXT.count('timezone: "America/New_York"') == 5


def test_workflow_schedule_has_exactly_five_entries_all_america_new_york() -> None:
    workflow = yaml.safe_load(WORKFLOW_TEXT)
    entries = workflow[True]["schedule"]
    assert len(entries) == 5
    assert all(entry["timezone"] == "America/New_York" for entry in entries)


def test_workflow_has_sunday_and_wednesday_main_slot_cron_entries() -> None:
    assert '"0 10 * * 0"' in WORKFLOW_TEXT
    assert '"0 20 * * 3"' in WORKFLOW_TEXT


def test_workflow_has_backup_slot_cron_entries() -> None:
    assert '"0 12-22/2 * * 0"' in WORKFLOW_TEXT  # Sunday backup slots
    assert '"0 22 * * 3"' in WORKFLOW_TEXT  # Wednesday backup slot
    assert '"0 6-16/2 * * 4"' in WORKFLOW_TEXT  # Thursday backup slots


def test_workflow_has_workflow_dispatch() -> None:
    assert "workflow_dispatch" in WORKFLOW_TEXT


# -- collect.yml: permissions / concurrency ----------------------------------------------------


def test_workflow_permissions_are_exactly_contents_write_and_issues_write() -> None:
    match = re.search(r"^permissions:\n((?:  .+\n)+)", WORKFLOW_TEXT, re.MULTILINE)
    assert match is not None
    block = match.group(1)
    granted = {line.strip().split(":")[0] for line in block.splitlines() if ":" in line}
    assert granted == {"contents", "issues"}
    assert "contents: write" in block
    assert "issues: write" in block


def test_workflow_concurrency_group_queues_never_cancels() -> None:
    assert "cancel-in-progress: false" in WORKFLOW_TEXT
    assert re.search(r"concurrency:\n\s+group:\s*\S+", WORKFLOW_TEXT) is not None


# -- collect.yml: checkout steps ---------------------------------------------------------------


def test_workflow_checks_out_vault_self_at_path_vault() -> None:
    pattern = r"uses:\s*actions/checkout@v7\s*\n\s*with:\s*\n\s*path:\s*vault"
    assert re.search(pattern, WORKFLOW_TEXT)


def test_workflow_checks_out_public_repo_at_pinned_job_ref() -> None:
    assert "repository: benboro/booth-review" in WORKFLOW_TEXT
    assert "ref: ${{ vars.JOB_REF }}" in WORKFLOW_TEXT
    assert "path: src" in WORKFLOW_TEXT
    assert "persist-credentials: false" in WORKFLOW_TEXT


def test_workflow_never_defaults_job_ref_to_main() -> None:
    assert "ref: main" not in WORKFLOW_TEXT
    assert "vars.JOB_REF" in WORKFLOW_TEXT


def test_workflow_never_names_the_private_repo() -> None:
    assert WORKFLOW_TEXT.count("booth-review-data") == 0


def test_workflow_setup_uv_version_matches_ci_yml() -> None:
    workflow_version = re.search(r"astral-sh/setup-uv@(\S+)", WORKFLOW_TEXT)
    ci_version = re.search(r"astral-sh/setup-uv@(\S+)", CI_TEXT)
    assert workflow_version is not None
    assert ci_version is not None
    assert workflow_version.group(1) == ci_version.group(1)


def test_workflow_checkout_version_matches_ci_yml() -> None:
    workflow_versions = set(re.findall(r"actions/checkout@(\S+)", WORKFLOW_TEXT))
    ci_versions = set(re.findall(r"actions/checkout@(\S+)", CI_TEXT))
    assert workflow_versions == ci_versions


# -- collect.yml: secret handling ---------------------------------------------------------------


def test_workflow_references_cfbd_secret_exactly_once_outside_comments() -> None:
    non_comment = "\n".join(_non_comment_lines(WORKFLOW_TEXT))
    assert non_comment.count("secrets.") == 1
    assert "CFBD_API_KEY: ${{ secrets.CFBD_API_KEY }}" in WORKFLOW_TEXT


def test_workflow_never_echoes_a_secret() -> None:
    for line in _non_comment_lines(WORKFLOW_TEXT):
        if "echo" in line:
            assert "secrets." not in line
            assert "CFBD_API_KEY" not in line


# -- collect.yml: attention issue step -----------------------------------------------------------


def test_workflow_attention_step_uses_gh_issue() -> None:
    assert "gh issue list" in WORKFLOW_TEXT
    assert "gh issue edit" in WORKFLOW_TEXT
    assert "gh issue create" in WORKFLOW_TEXT


def test_workflow_attention_step_runs_always_except_code_5_nothing_due() -> None:
    workflow = yaml.safe_load(WORKFLOW_TEXT)
    steps = workflow["jobs"]["collect"]["steps"]
    step = next(s for s in steps if "attention issue" in s.get("name", ""))
    # Without always() GitHub adds an implicit success(), which would skip the
    # issue update when setup (checkout, uv sync) fails before the job runs.
    assert step["if"] == "always() && steps.job.outputs.code != '5'"


def test_workflow_fails_hard_only_outside_0_4_and_5() -> None:
    workflow = yaml.safe_load(WORKFLOW_TEXT)
    steps = workflow["jobs"]["collect"]["steps"]
    step = next(s for s in steps if "hard failure" in s.get("name", ""))
    condition = step["if"]
    assert "!= '0'" in condition
    assert "!= '4'" in condition
    assert "!= '5'" in condition


# -- gitattributes ---------------------------------------------------------------------------


def test_gitattributes_forces_lf_everywhere() -> None:
    assert "* text=auto eol=lf" in GITATTRIBUTES_TEXT


def test_gitattributes_keeps_raw_bytes_untouched() -> None:
    assert "raw/** -text" in GITATTRIBUTES_TEXT


def test_gitattributes_union_merges_ledger_jsonl() -> None:
    assert "ledger/*.jsonl merge=union" in GITATTRIBUTES_TEXT


def test_gitattributes_template_has_no_leading_dot_in_its_own_filename() -> None:
    # Named "gitattributes", not ".gitattributes", so it never applies inside
    # this (public) repo's own working copy until explicitly installed.
    assert GITATTRIBUTES_PATH.name == "gitattributes"


# -- union-merge proof: two clones appending different JSONL lines --------------------------


def _seed_remote(tmp_path: Path, *, with_attributes: bool) -> Path:
    remote = tmp_path / "remote.git"
    _run_ok(["git", "init", "--bare", "-q", "-b", "main", str(remote)])

    seed = tmp_path / "seed"
    _run_ok(["git", "clone", "-q", str(remote), str(seed)])
    _run_ok(["git", "-C", str(seed), "config", "user.name", "Seed Bot"])
    _run_ok(["git", "-C", str(seed), "config", "user.email", "seed-bot@example.com"])

    if with_attributes:
        (seed / ".gitattributes").write_text(GITATTRIBUTES_TEXT, encoding="utf-8")

    ledger_dir = seed / "ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    (ledger_dir / "requests.jsonl").write_text('{"line": "base"}\n', encoding="utf-8")

    _run_ok(["git", "-C", str(seed), "add", "-A"])
    _run_ok(["git", "-C", str(seed), "commit", "-q", "-m", "init: seed"])
    _run_ok(["git", "-C", str(seed), "push", "-q", "origin", "main"])
    return remote


def _clone(tmp_path: Path, remote: Path, name: str) -> Path:
    clone = tmp_path / name
    _run_ok(["git", "clone", "-q", str(remote), str(clone)])
    _run_ok(["git", "-C", str(clone), "config", "user.name", f"{name} Bot"])
    _run_ok(["git", "-C", str(clone), "config", "user.email", f"{name}-bot@example.com"])
    return clone


def test_union_merge_lets_two_independent_ledger_appends_rebase_and_push_cleanly(
    tmp_path: Path, isolated_git_env: None
) -> None:
    remote = _seed_remote(tmp_path, with_attributes=True)
    vault = _clone(tmp_path, remote, "vault")
    second = _clone(tmp_path, remote, "second")

    (second / "ledger" / "requests.jsonl").write_text(
        '{"line": "base"}\n{"line": "from-second"}\n', encoding="utf-8"
    )
    _run_ok(["git", "-C", str(second), "add", "ledger/requests.jsonl"])
    _run_ok(["git", "-C", str(second), "commit", "-q", "-m", "job: state 2026 (missed 0)"])
    _run_ok(["git", "-C", str(second), "push", "-q"])

    (vault / "ledger" / "requests.jsonl").write_text(
        '{"line": "base"}\n{"line": "from-vault"}\n', encoding="utf-8"
    )
    repo = VaultRepo(vault)
    message = batch_message("job", "cfbd", "2026", {"fetched": 1, "cached": 0})

    result = repo.commit_batch(message, paths=["ledger/requests.jsonl"])

    assert result is True

    check = tmp_path / "check"
    _run_ok(["git", "clone", "-q", str(remote), str(check)])
    merged = (check / "ledger" / "requests.jsonl").read_text(encoding="utf-8")
    assert '"line": "from-second"' in merged
    assert '"line": "from-vault"' in merged


def test_without_attributes_the_same_scenario_raises_and_leaves_no_rebase_in_progress(
    tmp_path: Path, isolated_git_env: None
) -> None:
    remote = _seed_remote(tmp_path, with_attributes=False)
    vault = _clone(tmp_path, remote, "vault")
    second = _clone(tmp_path, remote, "second")

    (second / "ledger" / "requests.jsonl").write_text(
        '{"line": "base"}\n{"line": "from-second"}\n', encoding="utf-8"
    )
    _run_ok(["git", "-C", str(second), "add", "ledger/requests.jsonl"])
    _run_ok(["git", "-C", str(second), "commit", "-q", "-m", "job: state 2026 (missed 0)"])
    _run_ok(["git", "-C", str(second), "push", "-q"])

    (vault / "ledger" / "requests.jsonl").write_text(
        '{"line": "base"}\n{"line": "from-vault"}\n', encoding="utf-8"
    )
    repo = VaultRepo(vault)
    message = batch_message("job", "cfbd", "2026", {"fetched": 1, "cached": 0})

    with pytest.raises(VaultCommitError):
        repo.commit_batch(message, paths=["ledger/requests.jsonl"])

    status = subprocess.run(
        ["git", "-C", str(vault), "status"], capture_output=True, text=True, check=True
    )
    assert "rebase in progress" not in status.stdout
    assert not (vault / ".git" / "rebase-merge").exists()
    assert not (vault / ".git" / "rebase-apply").exists()
