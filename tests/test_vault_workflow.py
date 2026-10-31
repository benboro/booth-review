"""Tests for the AUTO-01/AUTO-03 workflow/gitattributes templates (ops/vault/)
and version consistency.

`ops/vault/collect.yml` and `ops/vault/gitattributes` are templates: they are
installed into the *private* data repo's own working copy (Plan 07, with the
user's OK), never activated in this (public) repo. Text assertions here read
the files directly (`Path.read_text`); the union-merge proof drives real git
against a local bare remote plus two clones under `tmp_path`, with no network
involved, matching `tests/test_vault.py`'s own fixture style.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
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


def test_version_matches_pyproject_and_lock() -> None:
    # A patch bump per reference-fix batch changes pyproject.toml, uv.lock and
    # the literal below (D-04).
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))
    locked = next(pkg for pkg in lock["package"] if pkg["name"] == "booth-review")
    assert booth_review.__version__ == pyproject["project"]["version"] == locked["version"]
    assert booth_review.__version__ == "0.18.4"


# -- collect.yml: schedule / triggers ----------------------------------------------------------


def test_workflow_has_thirteen_america_new_york_timezone_entries() -> None:
    # 2 main slots (D-11) + 3 backup-slot groups (D-12: Sun afternoon/evening,
    # Wed late, Thu daytime) + the 4 Phase 18 schedule-only entries (Fri/Sat
    # main and backup) + the 4 Phase 24 reminder entries -- every schedule
    # entry uses the same timezone.
    assert WORKFLOW_TEXT.count('timezone: "America/New_York"') == 13


def test_workflow_schedule_has_exactly_thirteen_entries_all_america_new_york() -> None:
    workflow = yaml.safe_load(WORKFLOW_TEXT)
    entries = workflow[True]["schedule"]
    assert len(entries) == 13
    assert all(entry["timezone"] == "America/New_York" for entry in entries)


def test_workflow_has_the_phase_24_reminder_crons() -> None:
    workflow = yaml.safe_load(WORKFLOW_TEXT)
    crons = [entry["cron"] for entry in workflow[True]["schedule"]]
    for cron in ("30 17,18 * * 1", "30 21,22 * * 2", "0 12,13 * * 3", "30 11,12 * * 5"):
        assert crons.count(cron) == 1
    # Thursday 12:00 and 14:00 already fire through the existing entry: no duplicate.
    assert crons.count("0 6-16/2 * * 4") == 1
    assert len(crons) == len(set(crons))


def test_workflow_has_sunday_and_wednesday_main_slot_cron_entries() -> None:
    assert '"0 10 * * 0"' in WORKFLOW_TEXT
    assert '"0 20 * * 3"' in WORKFLOW_TEXT


def test_workflow_has_backup_slot_cron_entries() -> None:
    assert '"0 12-22/2 * * 0"' in WORKFLOW_TEXT  # Sunday backup slots
    assert '"0 22 * * 3"' in WORKFLOW_TEXT  # Wednesday backup slot
    assert '"0 6-16/2 * * 4"' in WORKFLOW_TEXT  # Thursday backup slots


def test_workflow_has_workflow_dispatch() -> None:
    assert "workflow_dispatch" in WORKFLOW_TEXT


def test_workflow_has_friday_saturday_schedule_only_crons() -> None:
    entries = yaml.safe_load(WORKFLOW_TEXT)[True]["schedule"]
    by_cron = {entry["cron"]: entry for entry in entries}
    for cron in ("0 18 * * 5", "0 20,22 * * 5", "0 8 * * 6", "0 9,10 * * 6"):
        assert cron in by_cron
        assert by_cron[cron]["timezone"] == "America/New_York"


def test_workflow_dispatch_mode_input_is_a_three_way_choice() -> None:
    dispatch = yaml.safe_load(WORKFLOW_TEXT)[True]["workflow_dispatch"]
    mode = dispatch["inputs"]["mode"]
    assert mode["type"] == "choice"
    assert mode["options"] == ["full", "schedule", "rebuild"]
    assert mode["default"] == "full"


def test_workflow_passes_mode_through_env_never_inline() -> None:
    assert "DISPATCH_MODE: ${{ inputs.mode }}" in WORKFLOW_TEXT
    assert '--mode "$mode"' in WORKFLOW_TEXT
    uses = [line for line in _non_comment_lines(WORKFLOW_TEXT) if "inputs.mode" in line]
    assert uses == ["          DISPATCH_MODE: ${{ inputs.mode }}"]


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
    pattern = (
        r"uses:\s*actions/checkout@[0-9a-f]{40} # v7\.\d+\.\d+\s*\n\s*with:\s*\n\s*path:\s*vault"
    )
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


# IN-01: every action is pinned to a full commit SHA, with its release tag in a
# trailing comment, so a moved or compromised tag can't run in a job that
# holds the CFBD key and a vault write token.
_PINNED_USES_RE = re.compile(r"uses:\s*([\w.-]+/[\w.-]+)@([0-9a-f]{40}) # (v\d+\.\d+\.\d+)\s*$")


def _uses_lines(text: str) -> list[str]:
    return [line for line in _non_comment_lines(text) if "uses:" in line]


def _pins(text: str) -> set[tuple[str, str, str]]:
    pins = set()
    for line in _uses_lines(text):
        match = _PINNED_USES_RE.search(line)
        assert match is not None, f"action not pinned to a commit SHA with a # vX.Y.Z tag: {line}"
        pins.add((match.group(1), match.group(2), match.group(3)))
    return pins


@pytest.mark.parametrize("text", [WORKFLOW_TEXT, CI_TEXT], ids=["collect.yml", "ci.yml"])
def test_every_action_is_pinned_to_a_full_commit_sha_with_a_version_comment(text: str) -> None:
    assert _uses_lines(text)
    _pins(text)  # asserts each line


def test_workflow_setup_uv_pin_matches_ci_yml() -> None:
    workflow_pins = {pin for pin in _pins(WORKFLOW_TEXT) if pin[0] == "astral-sh/setup-uv"}
    ci_pins = {pin for pin in _pins(CI_TEXT) if pin[0] == "astral-sh/setup-uv"}
    assert len(workflow_pins) == 1
    assert workflow_pins == ci_pins


def test_workflow_checkout_pin_matches_ci_yml() -> None:
    workflow_pins = {pin for pin in _pins(WORKFLOW_TEXT) if pin[0] == "actions/checkout"}
    ci_pins = {pin for pin in _pins(CI_TEXT) if pin[0] == "actions/checkout"}
    assert len(workflow_pins) == 1
    assert workflow_pins == ci_pins


def test_ci_playwright_image_matches_locked_playwright() -> None:
    """The e2e container's browsers are built for one Playwright release; a
    mismatched uv.lock would look for browsers the image doesn't have."""
    image = yaml.safe_load(CI_TEXT)["jobs"]["e2e"]["container"]["image"]
    match = re.fullmatch(
        r"mcr\.microsoft\.com/playwright/python:v(\d+\.\d+\.\d+)-noble@sha256:[0-9a-f]{64}", image
    )
    assert match is not None, f"e2e image not a digest-pinned Playwright tag: {image}"
    lock = tomllib.loads(Path("uv.lock").read_text(encoding="utf-8"))
    locked = {pkg["version"] for pkg in lock["package"] if pkg["name"] == "playwright"}
    assert locked == {match.group(1)}


def test_workflow_job_ref_reaches_the_shell_only_through_env() -> None:
    for line in WORKFLOW_TEXT.splitlines():
        if "${{ vars.JOB_REF }}" in line:
            assert line.strip() in ("JOB_REF: ${{ vars.JOB_REF }}", "ref: ${{ vars.JOB_REF }}")


def _steps() -> list[dict[str, object]]:
    workflow = yaml.safe_load(WORKFLOW_TEXT)
    steps: list[dict[str, object]] = workflow["jobs"]["collect"]["steps"]
    return steps


@pytest.mark.parametrize(
    "name", ["vars.DEPLOY_REPO", "vars.PUBLISH_ENABLED", "vars.NFL_SITE_ENABLED"]
)
def test_deploy_vars_never_appear_inside_a_run_block(name: str) -> None:
    for step in _steps():
        assert name not in str(step.get("run", ""))
    # Outside run blocks they may sit only in env: and with: lines. Never in an
    # if: line: Actions expressions compare strings case-insensitively (WR-02).
    for line in _non_comment_lines(WORKFLOW_TEXT):
        if name in line:
            stripped = line.strip()
            assert stripped.startswith(
                (
                    "PUBLISH_ENABLED:",
                    "NFL_SITE_ENABLED:",
                    "DEPLOY_REPO:",
                    "repository:",
                    "ssh-key:",
                )
            ), stripped


def test_job_and_deploy_steps_carry_the_nfl_site_flag_from_vars() -> None:
    carriers = []
    for step in _steps():
        env = step.get("env")
        if isinstance(env, dict) and "NFL_SITE_ENABLED" in env:
            assert env["NFL_SITE_ENABLED"] == "${{ vars.NFL_SITE_ENABLED }}"
            carriers.append(step.get("id"))
    assert sorted(str(c) for c in carriers) == ["deploy", "job"]


_BASH = shutil.which("bash")
_DEPLOY_GATE = (
    "steps.result.outputs.deploy_ready == 'true' && steps.gate.outputs.publish == 'yes'"
    " && steps.job.outputs.code != '3'"
)


def _step(step_id: str) -> dict[str, object]:
    return next(s for s in _steps() if s.get("id") == step_id)


def _run_step(
    step: dict[str, object], env: dict[str, str], tmp_path: Path
) -> tuple[int, dict[str, str]]:
    """Run a step's `run:` block the way Actions does (bash -eo pipefail) and
    return its exit code and the key=value lines it wrote to $GITHUB_OUTPUT."""
    assert _BASH is not None
    script = tmp_path / "step.sh"
    script.write_text(str(step["run"]), encoding="utf-8")
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    full_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "GITHUB_OUTPUT": str(output),
        "RUNNER_TEMP": str(tmp_path),
        **env,
    }
    result = subprocess.run(
        [_BASH, "--noprofile", "--norc", "-eo", "pipefail", str(script)],
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )
    (tmp_path / "step.err").write_text(result.stderr, encoding="utf-8")
    lines = output.read_text(encoding="utf-8").splitlines()
    return result.returncode, dict(line.split("=", 1) for line in lines if "=" in line)


def test_deploy_steps_gated_on_the_shell_computed_publish_output() -> None:
    # CR-02: `!cancelled()` replaces the implicit success() so a job step that
    # hit its timeout still deploys its CFB-only result; the deploy itself also
    # needs the target checkout to have succeeded.
    assert _step("target")["if"] == "${{ !cancelled() && " + _DEPLOY_GATE + " }}"
    assert _step("deploy")["if"] == (
        "${{ !cancelled() && steps.target.outcome == 'success' && " + _DEPLOY_GATE + " }}"
    )
    gated = [s for s in _steps() if _DEPLOY_GATE in str(s.get("if", ""))]
    assert {s.get("id") for s in gated} == {"target", "deploy"}
    assert not any("vars.PUBLISH_ENABLED" in str(s.get("if", "")) for s in _steps())
    deploy = _step("deploy")
    assert "booth-review deploy --site" in str(deploy["run"])
    # The gate runs before the deploy target is ever checked out.
    ids = [s.get("id") for s in _steps()]
    assert ids.index("gate") < ids.index("target") < ids.index("deploy")


@pytest.mark.skipif(_BASH is None, reason="bash not available")
@pytest.mark.parametrize(
    ("value", "publish"),
    [
        ("true", "yes"),
        ("True", "no"),
        ("TRUE", "no"),
        (" true", "no"),
        ("true ", "no"),
        ("1", "no"),
        ("yes", "no"),
        ("false", "no"),
        ("", "no"),
    ],
)
def test_publish_gate_is_exactly_true(value: str, publish: str, tmp_path: Path) -> None:
    # WR-02: only the exact string `true` opens the gate, matching the CLI.
    code, outputs = _run_step(
        _step("gate"),
        {"PUBLISH_ENABLED": value, "DEPLOY_REPO": "owner/site"},
        tmp_path,
    )
    assert code == 0
    assert outputs == {"publish": publish}


@pytest.mark.skipif(_BASH is None, reason="bash not available")
@pytest.mark.parametrize("repo", ["", "owner", "owner/site/extra", "owner/si te"])
def test_publish_gate_fails_on_a_bad_deploy_repo_when_enabled(repo: str, tmp_path: Path) -> None:
    code, outputs = _run_step(
        _step("gate"), {"PUBLISH_ENABLED": "true", "DEPLOY_REPO": repo}, tmp_path
    )
    assert code != 0
    assert "publish" not in outputs


@pytest.mark.skipif(_BASH is None, reason="bash not available")
def test_publish_gate_ignores_deploy_repo_when_disabled(tmp_path: Path) -> None:
    code, outputs = _run_step(
        _step("gate"), {"PUBLISH_ENABLED": "TRUE", "DEPLOY_REPO": ""}, tmp_path
    )
    assert code == 0
    assert outputs == {"publish": "no"}


def test_every_checkout_matches_the_ci_pin() -> None:
    ci_pins = {pin[1] for pin in _pins(CI_TEXT) if pin[0] == "actions/checkout"}
    uses = [str(s["uses"]) for s in _steps() if "uses" in s]
    checkouts = [u for u in uses if u.startswith("actions/checkout@")]
    assert len(checkouts) == 3
    assert {u.split("@")[1] for u in checkouts} == ci_pins


def test_scratch_key_selection_names_only_the_prod_target() -> None:
    step = next(s for s in _steps() if s.get("name") == "Check out the deploy target")
    ssh_key = str(step["with"]["ssh-key"])  # type: ignore[index]
    assert ssh_key == (
        "${{ vars.DEPLOY_REPO == 'benboro/benboro.github.io' && secrets.DEPLOY_KEY_PROD"
        " || secrets.DEPLOY_KEY_SCRATCH }}"
    )
    assert WORKFLOW_TEXT.count("site-scratch") == 0


def test_job_step_passes_update_flags_and_filters_result_lines() -> None:
    job = next(s for s in _steps() if s.get("id") == "job")
    run = str(job["run"])
    for flag in ("--update", "--site-out", "--result-out", "--attention-out"):
        assert flag in run
    assert '>> "$GITHUB_OUTPUT"' in run
    # CR-02: the result file is read by its own step, which also runs after a
    # job-step timeout (the job step then sets no outputs).
    result = str(_step("result")["run"])
    assert "grep -E '^(deploy_ready|stale_only)=(true|false)$'" in result
    assert "grep" not in run


def test_job_step_env_carries_the_github_token_for_the_nflverse_api_route() -> None:
    # 999.4 D-21: GITHUB_TOKEN reaches booth-review only through the job step's
    # env; the collector sends it to api.github.com requests only.
    job = _step("job")
    env = job["env"]
    assert isinstance(env, dict)
    assert env["GITHUB_TOKEN"] == "${{ github.token }}"
    assert WORKFLOW_TEXT.count("GITHUB_TOKEN: ${{ github.token }}") == 1
    for step in _steps():
        if step.get("id") != "job":
            assert "GITHUB_TOKEN" not in dict(step.get("env") or {})  # type: ignore[call-overload]


def test_no_nfl_step_adds_a_deploy() -> None:
    # The NFL steps live inside `booth-review job run`; the workflow gains no
    # step of its own, and the only deploy is still the gated CFB site deploy.
    runs = [(s.get("id"), str(s.get("run", ""))) for s in _steps()]
    assert [sid for sid, run in runs if "uv run booth-review" in run] == ["job", "deploy"]
    assert [sid for sid, run in runs if "uv run booth-review deploy" in run] == ["deploy"]
    for _sid, run in runs:
        assert "nfl" not in run.lower()


# -- collect.yml: secret handling ---------------------------------------------------------------


def test_workflow_secret_references_are_the_exact_expected_set() -> None:
    non_comment = "\n".join(_non_comment_lines(WORKFLOW_TEXT))
    found = re.findall(r"secrets\.(\w+)", non_comment)
    # DEPLOY_KEY_PROD / DEPLOY_KEY_SCRATCH sit in one ssh-key expression.
    assert sorted(found) == [
        "CFBD_API_KEY",
        "CFBD_API_KEY",
        "DEPLOY_KEY_PROD",
        "DEPLOY_KEY_SCRATCH",
    ]
    assert non_comment.count("CFBD_API_KEY: ${{ secrets.CFBD_API_KEY }}") == 2


def test_workflow_never_echoes_a_secret() -> None:
    for line in _non_comment_lines(WORKFLOW_TEXT):
        if "echo" in line:
            assert "secrets." not in line
            assert "CFBD_API_KEY" not in line


# -- collect.yml: attention issue step -----------------------------------------------------------


def test_workflow_attention_step_uses_gh_issue() -> None:
    assert "gh issue list" in WORKFLOW_TEXT
    assert "--label booth-review-job" in WORKFLOW_TEXT
    assert "gh label create booth-review-job" in WORKFLOW_TEXT
    assert "--force" in WORKFLOW_TEXT
    assert WORKFLOW_TEXT.count("--label booth-review-job") >= 2
    assert "gh issue edit" in WORKFLOW_TEXT
    assert "gh issue create" in WORKFLOW_TEXT


def test_workflow_attention_step_runs_always_except_code_5_nothing_due() -> None:
    workflow = yaml.safe_load(WORKFLOW_TEXT)
    steps = workflow["jobs"]["collect"]["steps"]
    step = next(s for s in steps if "attention issue" in s.get("name", ""))
    # Without always() GitHub adds an implicit success(), which would skip the
    # issue update when setup (checkout, uv sync) fails before the job runs.
    assert step["if"] == "always() && steps.job.outputs.code != '5'"


def test_workflow_fails_hard_only_outside_0_4_and_5_or_on_deploy_failure() -> None:
    step = next(s for s in _steps() if "hard failure" in str(s.get("name", "")))
    run = str(step["run"])
    env = step["env"]
    assert "0|4|5) ;;" in run
    assert '"$DEPLOY_CODE" != "0"' in run
    assert set(env) == {"JOB_CODE", "JOB_OUTCOME", "DEPLOY_CODE", "DEPLOY_EXPECTED"}  # type: ignore[arg-type]


# -- WR-03: a due deploy that never ran is a problem, not a clean run ----------------------------


def _attention_step() -> dict[str, object]:
    return next(s for s in _steps() if "attention issue" in str(s.get("name", "")))


def _fail_step() -> dict[str, object]:
    return next(s for s in _steps() if "hard failure" in str(s.get("name", "")))


@pytest.mark.parametrize("step", [_attention_step, _fail_step], ids=["attention", "fail"])
def test_deploy_expected_uses_the_deploy_gate(step: object) -> None:
    env = step()["env"]  # type: ignore[operator]
    assert env["DEPLOY_EXPECTED"] == "${{ " + _DEPLOY_GATE + " }}"


def _fake_gh(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """A stand-in `gh` that logs each call and reports open issue #7 (or
    $FAKE_ISSUE when set), whose body and last comment come from the files
    $FAKE_BODY and $FAKE_COMMENT (the fake skips gh's own --jq step)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "gh.log"
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        'echo "$*" >> "$GH_LOG"\n'
        'case "$1 $2" in\n'
        '  "issue list") echo "${FAKE_ISSUE-7}" ;;\n'
        '  "issue create") echo "https://example.invalid/owner/vault/issues/7" ;;\n'
        '  "issue view")\n'
        '    case "$*" in\n'
        '      *"--json body"*) cat "$FAKE_BODY" 2>/dev/null || true ;;\n'
        '      *"--json comments"*"| last"*)\n'
        '        cat "${FAKE_COMMENT_LAST:-$FAKE_COMMENT}" 2>/dev/null || true ;;\n'
        '      *"--json comments"*) cat "$FAKE_COMMENT" 2>/dev/null || true ;;\n'
        "    esac ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}",
        "GH_LOG": str(log),
        "GH_TOKEN": "x",
        "GITHUB_SERVER_URL": "https://example.invalid",
        "GITHUB_REPOSITORY": "owner/vault",
        "GITHUB_RUN_ID": "1",
    }
    return env, log


@pytest.mark.skipif(_BASH is None, reason="bash not available")
@pytest.mark.parametrize(
    ("expected", "deploy_code", "closes"),
    [
        ("true", "", False),  # target checkout failed: deploy step skipped
        ("true", "0", True),
        ("true", "3", False),
        ("false", "", True),  # publishing off: no deploy was due
    ],
)
def test_attention_step_never_closes_the_issue_when_a_due_deploy_did_not_run(
    expected: str, deploy_code: str, closes: bool, tmp_path: Path
) -> None:
    env, log = _fake_gh(tmp_path)
    env.update(
        {
            "JOB_CODE": "0",
            "DEPLOY_CODE": deploy_code,
            "DEPLOY_EXPECTED": expected,
            "STALE_ONLY": "false",
        }
    )
    code, _outputs = _run_step(_attention_step(), env, tmp_path)
    assert code == 0
    calls = log.read_text(encoding="utf-8").splitlines()
    assert any(c.startswith("issue close 7") for c in calls) is closes
    assert any(c.startswith("issue edit 7 ") and "--body-file" in c for c in calls) is not closes
    if expected == "true" and not deploy_code:
        body = (tmp_path / "attention-body.md").read_text(encoding="utf-8")
        assert "deploy did not run" in body
        assert "the live site was not updated" in body


@pytest.mark.skipif(_BASH is None, reason="bash not available")
@pytest.mark.parametrize(
    ("expected", "deploy_code", "fails"),
    [
        ("true", "", True),
        ("true", "0", False),
        ("true", "3", True),
        ("false", "", False),
    ],
)
def test_fail_step_fails_when_a_due_deploy_did_not_run(
    expected: str, deploy_code: str, fails: bool, tmp_path: Path
) -> None:
    code, _outputs = _run_step(
        _fail_step(),
        {"JOB_CODE": "0", "DEPLOY_CODE": deploy_code, "DEPLOY_EXPECTED": expected},
        tmp_path,
    )
    assert (code != 0) is fails


# -- CR-02: a job step that hits its timeout still deploys its CFB-only result -------------------
#
# GitHub Actions fails (does not cancel) a step that hits its own timeout-minutes;
# the step sets no outputs, and every later step whose `if:` has no status
# function gets an implicit success() and is skipped. `job run` writes the
# CFB-only result file before the NFL block, so the steps after the job step
# must still run, and still deploy only on deploy_ready, never on exit 3.

_STATUS_FUNCTIONS = {"always", "cancelled", "success", "failure"}
_EXPR_TOKEN_RE = re.compile(r"\s*(&&|\|\||==|!=|!|\(|\)|'[^']*'|[A-Za-z_][\w.-]*)")


class _Condition:
    """Evaluates the `if:` expressions this workflow uses, as Actions does:
    `&&`, `||`, `!`, parentheses, case-insensitive `==`/`!=`, 'literals',
    `steps.<id>.outcome`, `steps.<id>.outputs.<name>` (a missing one is
    empty) and the four status functions. An expression with no status
    function gets an implicit `success() &&`."""

    def __init__(self, steps: dict[str, dict[str, object]], *, failed: bool) -> None:
        self._steps = steps
        self._failed = failed
        self._tokens: list[str] = []

    def runs(self, expr: object) -> bool:
        if expr is None:
            return not self._failed
        text = str(expr).strip()
        if text.startswith("${{"):
            assert text.endswith("}}"), text
            text = text[3:-2]
        self._tokens = []
        pos = 0
        while text[pos:].strip():
            match = _EXPR_TOKEN_RE.match(text, pos)
            assert match is not None, f"unsupported expression: {text[pos:]!r}"
            self._tokens.append(match.group(1))
            pos = match.end()
        implicit = not any(
            tok in _STATUS_FUNCTIONS and nxt == "("
            for tok, nxt in zip(self._tokens, [*self._tokens[1:], ""], strict=True)
        )
        value = self._truthy(self._or())
        assert not self._tokens, f"trailing tokens: {self._tokens}"
        return value and not (implicit and self._failed)

    @staticmethod
    def _truthy(value: object) -> bool:
        return bool(value)

    def _take(self, expected: str | None = None) -> str:
        token = self._tokens.pop(0)
        assert expected is None or token == expected, (token, expected)
        return token

    def _or(self) -> object:
        value = self._and()
        while self._tokens[:1] == ["||"]:
            self._take()
            right = self._and()
            value = value if self._truthy(value) else right
        return value

    def _and(self) -> object:
        value = self._unary()
        while self._tokens[:1] == ["&&"]:
            self._take()
            right = self._unary()
            value = right if self._truthy(value) else value
        return value

    def _unary(self) -> object:
        if self._tokens[:1] == ["!"]:
            self._take()
            return not self._truthy(self._unary())
        return self._compare()

    def _compare(self) -> object:
        left = self._primary()
        if self._tokens[:1] in (["=="], ["!="]):
            op = self._take()
            right = self._primary()
            equal = str(left).lower() == str(right).lower()
            return equal if op == "==" else not equal
        return left

    def _primary(self) -> object:
        token = self._take()
        if token == "(":
            value = self._or()
            self._take(")")
            return value
        if token.startswith("'"):
            return token[1:-1]
        if self._tokens[:1] == ["("]:
            self._take("(")
            self._take(")")
            return {
                "always": True,
                "cancelled": False,
                "success": not self._failed,
                "failure": self._failed,
            }[token]
        parts = token.split(".")
        assert parts[0] == "steps", token
        step = self._steps.get(parts[1])
        if step is None:
            return ""
        if parts[2] == "outcome":
            return step["outcome"]
        assert parts[2] == "outputs", token
        outputs = step["outputs"]
        assert isinstance(outputs, dict)
        return outputs.get(parts[3], "")


def _label(step: dict[str, object]) -> str:
    """A step's id, else its name, else the action it uses (without the pin)."""
    return str(step.get("id") or step.get("name") or str(step["uses"]).split("@")[0])


def _simulate(
    tmp_path: Path,
    *,
    job_outcome: str = "success",
    job_code: str | None = "0",
    result_file: str | None = "deploy_ready=true\nstale_only=false\n",
    publish: str = "yes",
    failing_step: str | None = None,
) -> list[str]:
    """Walk the steps as the Actions runner decides them and return the ids
    (or names) of the steps that run. The "result" step's own run block is
    executed against $RUNNER_TEMP/result.txt; every other step is stubbed."""
    assert any(s.get("id") == "result" for s in _steps())
    if result_file is not None:
        (tmp_path / "result.txt").write_text(result_file, encoding="utf-8")
    state: dict[str, dict[str, object]] = {}
    failed = False
    ran: list[str] = []
    for step in _steps():
        sid = _label(step)
        if not _Condition(state, failed=failed).runs(step.get("if")):
            state[sid] = {"outcome": "skipped", "outputs": {}}
            continue
        ran.append(sid)
        outcome, outputs = "success", {}
        if sid == failing_step:
            outcome = "failure"
        elif sid == "gate":
            outputs = {"publish": publish}
        elif sid == "job":
            outcome = job_outcome
            outputs = {} if job_code is None else {"code": job_code}
        elif sid == "result":
            code, outputs = _run_step(step, {}, tmp_path)
            assert code == 0
        elif sid == "deploy":
            outputs = {"code": "0"}
        state[sid] = {"outcome": outcome, "outputs": outputs}
        failed = failed or outcome == "failure"
    return ran


_SETUP = [
    "Require a pinned JOB_REF (D-10: never default to main)",
    "gate",
    "Checkout vault (self)",
    "Checkout public repo at pinned tag",
    "astral-sh/setup-uv",
    "Install booth-review",
    "Configure the vault's git identity",
]
_TAIL = [
    "Update the attention issue (count-only, one tracked issue)",
    "Fail the workflow on a hard failure",
]
_DEPLOYS = ["target", "deploy"]
_READY = "deploy_ready=true\nstale_only=false\n"
_CFB_REPORT = "Counts only.\n- 506 2026 pages to save: week 1"


def test_job_step_has_its_own_timeout_well_under_the_job_timeout() -> None:
    workflow = yaml.safe_load(WORKFLOW_TEXT)
    job_timeout = workflow["jobs"]["collect"]["timeout-minutes"]
    step_timeout = _step("job")["timeout-minutes"]
    assert job_timeout == 60
    assert isinstance(step_timeout, int)
    # Room for setup before the step and the deploy and issue update after it.
    assert 0 < step_timeout <= job_timeout - 10
    timed = [_label(s) for s in _steps() if "timeout-minutes" in s]
    assert timed == ["job"]


@pytest.mark.skipif(_BASH is None, reason="bash not available")
@pytest.mark.parametrize(
    ("scenario", "kwargs", "after_job"),
    [
        # A hung NFL step: the CFB-only result file is there, so it deploys.
        ("timeout-cfb-ready", {"job_outcome": "failure", "job_code": None}, ["result", *_DEPLOYS]),
        # Timed out before the CFB result was written: nothing to deploy.
        (
            "timeout-no-result",
            {"job_outcome": "failure", "job_code": None, "result_file": None},
            ["result"],
        ),
        (
            "timeout-not-ready",
            {
                "job_outcome": "failure",
                "job_code": None,
                "result_file": "deploy_ready=false\nstale_only=false\n",
            },
            ["result"],
        ),
        ("finished-0", {}, ["result", *_DEPLOYS]),
        ("finished-4", {"job_code": "4"}, ["result", *_DEPLOYS]),
        # Exit 3 never deploys, even if a result file said deploy_ready=true.
        ("finished-3", {"job_code": "3"}, ["result"]),
        ("not-ready", {"result_file": "deploy_ready=false\nstale_only=false\n"}, ["result"]),
        (
            "publishing-off",
            {"publish": "no", "job_outcome": "failure", "job_code": None},
            ["result"],
        ),
    ],
    ids=[
        "timeout-cfb-ready",
        "timeout-no-result",
        "timeout-not-ready",
        "finished-0",
        "finished-4",
        "finished-3",
        "not-ready",
        "publishing-off",
    ],
)
def test_steps_after_the_job_step_run_after_its_timeout_and_deploy_only_when_ready(
    scenario: str, kwargs: dict[str, object], after_job: list[str], tmp_path: Path
) -> None:
    ran = _simulate(tmp_path, **kwargs)  # type: ignore[arg-type]
    assert ran == [*_SETUP, "job", *after_job, *_TAIL], scenario


@pytest.mark.skipif(_BASH is None, reason="bash not available")
@pytest.mark.parametrize("failing", ["Install booth-review", "target"])
def test_a_failed_setup_or_target_checkout_still_never_deploys(
    failing: str, tmp_path: Path
) -> None:
    ran = _simulate(tmp_path, failing_step=failing)
    if failing == "target":
        assert ran == [*_SETUP, "job", "result", "target", *_TAIL]
    else:
        # Every later step but the two always() ones is skipped, the job step
        # included, so the result step never reads a file.
        assert ran == [*_SETUP[: _SETUP.index(failing) + 1], *_TAIL]


@pytest.mark.skipif(_BASH is None, reason="bash not available")
@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("deploy_ready=true\nstale_only=false\n", {"deploy_ready": "true", "stale_only": "false"}),
        ("deploy_ready=false\nstale_only=true\n", {"deploy_ready": "false", "stale_only": "true"}),
        (None, {}),
        ("deploy_ready=True\nnoise\n", {}),
    ],
    ids=["ready", "stale-only", "missing", "malformed"],
)
def test_result_step_reads_only_the_two_exact_result_lines(
    content: str | None, expected: dict[str, str], tmp_path: Path
) -> None:
    if content is not None:
        (tmp_path / "result.txt").write_text(content, encoding="utf-8")
    code, outputs = _run_step(_step("result"), {}, tmp_path)
    assert code == 0
    assert outputs == expected


@pytest.mark.skipif(_BASH is None, reason="bash not available")
@pytest.mark.parametrize("cfb_saved", [True, False], ids=["after-cfb-result", "before-cfb-result"])
def test_attention_step_reports_a_job_step_timeout_and_keeps_the_issue_open(
    cfb_saved: bool, tmp_path: Path
) -> None:
    env, log = _fake_gh(tmp_path)
    if cfb_saved:
        (tmp_path / "result.txt").write_text(_READY, encoding="utf-8")
        (tmp_path / "attention.md").write_text(_CFB_REPORT, encoding="utf-8")
    env.update(
        {
            "JOB_CODE": "",
            "JOB_OUTCOME": "failure",
            "DEPLOY_CODE": "0" if cfb_saved else "",
            "DEPLOY_EXPECTED": "true" if cfb_saved else "false",
            "STALE_ONLY": "false" if cfb_saved else "",
        }
    )
    code, _outputs = _run_step(_attention_step(), env, tmp_path)
    assert code == 0
    calls = log.read_text(encoding="utf-8").splitlines()
    assert not any(c.startswith("issue close") for c in calls)
    assert any(c.startswith("issue edit 7 ") and "--body-file" in c for c in calls)
    body = (tmp_path / "attention-body.md").read_text(encoding="utf-8")
    if cfb_saved:
        assert body.startswith(_CFB_REPORT + "\n")
        assert "step timeout after the CFB result was saved" in body
        assert "live site was not updated" not in body
    else:
        assert body.startswith("job run hit its step timeout without an attention report\n")
        assert "step timeout before the CFB result was saved" in body


@pytest.mark.skipif(_BASH is None, reason="bash not available")
def test_fail_step_names_a_job_step_timeout_even_after_a_good_deploy(tmp_path: Path) -> None:
    code, _outputs = _run_step(
        _fail_step(),
        {"JOB_CODE": "", "JOB_OUTCOME": "failure", "DEPLOY_CODE": "0", "DEPLOY_EXPECTED": "true"},
        tmp_path,
    )
    assert code != 0
    assert "job run hit its step timeout" in (tmp_path / "step.err").read_text(encoding="utf-8")


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


# -- WR-07: a stale-only backup run never repeats an identical comment -----------------------------

_STALE_REPORT = (
    "Counts only. Updated 2026-10-08 16:00 UTC\n"
    "- last successful build is 5 days old (limit 4)\n"
    "- newest plotted 2026 telecast trails the newest listed one: 3 listed after it"
)


@pytest.mark.skipif(_BASH is None, reason="bash not available")
@pytest.mark.parametrize(
    ("issue", "body", "comment", "action"),
    [
        # The main run already wrote these items into the body (plus others).
        (
            "7",
            "Counts only. Updated 2026-10-08 00:05 UTC\n"
            "- 506 2026 pages to save: week 6\n"
            "- last successful build is 5 days old (limit 4)\n"
            "- newest plotted 2026 telecast trails the newest listed one: 3 listed after it\n"
            "\nrun: https://example.invalid/r/1",
            "",
            "none",
        ),
        # An earlier backup slot already commented the same items (CRLF too).
        (
            "7",
            "Counts only.\n- something else: 1",
            "Counts only. Updated 2026-10-08 14:00 UTC\r\n"
            "- last successful build is 5 days old (limit 4)\r\n"
            "- newest plotted 2026 telecast trails the newest listed one: 3 listed after it\r\n"
            "\r\nrun: https://example.invalid/r/0",
            "none",
        ),
        # The build-age line moved on since the last post: comment once.
        (
            "7",
            "Counts only.\n- last successful build is 4 days old (limit 4)",
            "",
            "comment",
        ),
        # Only part of the report was posted before.
        (
            "7",
            "Counts only.\n- last successful build is 5 days old (limit 4)",
            "",
            "comment",
        ),
        # No open issue: open one.
        ("", "", "", "create"),
    ],
    ids=["in-body", "in-last-comment", "changed", "partial", "no-issue"],
)
def test_stale_only_run_comments_only_when_the_report_changed(
    issue: str, body: str, comment: str, action: str, tmp_path: Path
) -> None:
    env, log = _fake_gh(tmp_path)
    (tmp_path / "issue-body.md").write_text(body, encoding="utf-8", newline="")
    (tmp_path / "issue-comment.md").write_text(comment, encoding="utf-8", newline="")
    (tmp_path / "attention.md").write_text(_STALE_REPORT, encoding="utf-8")
    env.update(
        {
            "FAKE_ISSUE": issue,
            "FAKE_BODY": str(tmp_path / "issue-body.md"),
            "FAKE_COMMENT": str(tmp_path / "issue-comment.md"),
            "JOB_CODE": "4",
            "DEPLOY_CODE": "",
            "DEPLOY_EXPECTED": "false",
            "STALE_ONLY": "true",
        }
    )
    code, _outputs = _run_step(_attention_step(), env, tmp_path)
    assert code == 0
    calls = log.read_text(encoding="utf-8").splitlines()
    commented = [c for c in calls if c.startswith("issue comment ")]
    created = [c for c in calls if c.startswith("issue create ")]
    assert not any(c.startswith(("issue close", "issue edit 7")) for c in calls)
    assert len(commented) == (1 if action == "comment" else 0)
    assert len(created) == (1 if action == "create" else 0)


_REMINDER_LINE = (
    "- reminder 2026 cfb week 10: save the aa college football schedule post "
    "https://awfulannouncing.com/college-football/"
)


@pytest.mark.skipif(_BASH is None, reason="bash not available")
@pytest.mark.parametrize(
    ("issue", "body", "comment", "report", "action"),
    [
        # A first reminder for the week: comment once.
        ("7", "Counts only.", "", _REMINDER_LINE, "comment"),
        # The backup slot an hour later repeats the same line: no second comment.
        (
            "7",
            "Counts only.",
            "Counts only.\n" + _REMINDER_LINE + "\n\nrun: https://example.invalid/r/2",
            _REMINDER_LINE,
            "none",
        ),
        # Next week's line differs by its week label: comment again.
        (
            "7",
            "Counts only.",
            "Counts only.\n" + _REMINDER_LINE + "\n\nrun: https://example.invalid/r/2",
            _REMINDER_LINE.replace("week 10", "week 11"),
            "comment",
        ),
        # No open issue: open one.
        ("", "", "", _REMINDER_LINE, "create"),
    ],
    ids=["first", "repeat-same-week", "new-week", "no-issue"],
)
def test_reminder_only_run_comments_once_per_week(
    issue: str, body: str, comment: str, report: str, action: str, tmp_path: Path
) -> None:
    env, log = _fake_gh(tmp_path)
    (tmp_path / "issue-body.md").write_text(body, encoding="utf-8", newline="")
    (tmp_path / "issue-comment.md").write_text(comment, encoding="utf-8", newline="")
    (tmp_path / "attention.md").write_text(
        "Counts only. Updated 2026-11-03 21:30 UTC\n" + report, encoding="utf-8"
    )
    env.update(
        {
            "FAKE_ISSUE": issue,
            "FAKE_BODY": str(tmp_path / "issue-body.md"),
            "FAKE_COMMENT": str(tmp_path / "issue-comment.md"),
            "JOB_CODE": "4",
            "DEPLOY_CODE": "",
            "DEPLOY_EXPECTED": "false",
            "STALE_ONLY": "true",
        }
    )
    code, _outputs = _run_step(_attention_step(), env, tmp_path)
    assert code == 0
    calls = log.read_text(encoding="utf-8").splitlines()
    commented = [c for c in calls if c.startswith("issue comment ")]
    created = [c for c in calls if c.startswith("issue create ")]
    assert len(commented) == (1 if action == "comment" else 0)
    assert len(created) == (1 if action == "create" else 0)


# -- collect.yml: Phase 24 reminder comments (separate from the attention body) -------------------

_RLINE = "- reminder 2026 cfb week 7: save the aa college football schedule post https://x/"


def _reminder_env(tmp_path: Path, *, code: str, stale_only: str) -> tuple[dict[str, str], Path]:
    env, log = _fake_gh(tmp_path)
    env.update(
        {
            "JOB_CODE": code,
            "DEPLOY_CODE": "",
            "DEPLOY_EXPECTED": "false",
            "STALE_ONLY": stale_only,
            "FAKE_BODY": str(tmp_path / "fake-body"),
            "FAKE_COMMENT": str(tmp_path / "fake-comment"),
        }
    )
    (tmp_path / "reminders.md").write_text(f"Counts only. Updated now\n{_RLINE}", encoding="utf-8")
    return env, log


def _calls(log: Path) -> list[str]:
    return log.read_text(encoding="utf-8").splitlines()


def test_job_step_writes_reminders_to_their_own_file() -> None:
    run = str(_step("job")["run"])
    assert '--reminders-out "$RUNNER_TEMP/reminders.md"' in run
    assert "reminders.md" in run.split("--reminders-out")[0]  # cleared before the run


@pytest.mark.skipif(_BASH is None, reason="bash not available")
def test_a_clean_full_run_comments_the_reminder_and_leaves_the_issue_open(tmp_path: Path) -> None:
    env, log = _reminder_env(tmp_path, code="0", stale_only="false")
    code, _ = _run_step(_attention_step(), env, tmp_path)
    assert code == 0
    calls = _calls(log)
    assert any(c.startswith("issue comment 7 ") and "reminders.md" in c for c in calls)
    assert not any(c.startswith(("issue close", "issue edit")) for c in calls)
    assert not any("clean run" in c for c in calls)


@pytest.mark.skipif(_BASH is None, reason="bash not available")
def test_a_problem_run_edits_the_body_and_still_comments_the_reminder(tmp_path: Path) -> None:
    env, log = _reminder_env(tmp_path, code="4", stale_only="false")
    (tmp_path / "attention.md").write_text("Counts only.\n- some real item", encoding="utf-8")
    code, _ = _run_step(_attention_step(), env, tmp_path)
    assert code == 0
    calls = _calls(log)
    assert any(c.startswith("issue edit 7 ") for c in calls)
    assert any(c.startswith("issue comment 7 ") and "reminders.md" in c for c in calls)


@pytest.mark.skipif(_BASH is None, reason="bash not available")
def test_a_reminder_only_comment_run_posts_one_comment_and_no_fallback_body(
    tmp_path: Path,
) -> None:
    env, log = _reminder_env(tmp_path, code="4", stale_only="true")
    code, _ = _run_step(_attention_step(), env, tmp_path)
    assert code == 0
    calls = _calls(log)
    comments = [c for c in calls if c.startswith("issue comment")]
    assert len(comments) == 1
    assert "reminders.md" in comments[0]
    assert not any(c.startswith("issue edit") for c in calls)


@pytest.mark.skipif(_BASH is None, reason="bash not available")
def test_a_reminder_already_in_a_recent_comment_is_not_posted_again(tmp_path: Path) -> None:
    env, log = _reminder_env(tmp_path, code="4", stale_only="true")
    (tmp_path / "fake-comment").write_text(f"Counts only.\n{_RLINE}\n", encoding="utf-8")
    code, _ = _run_step(_attention_step(), env, tmp_path)
    assert code == 0
    assert not any(c.startswith("issue comment") for c in _calls(log))


@pytest.mark.skipif(_BASH is None, reason="bash not available")
def test_a_reminder_in_the_issue_body_does_not_swallow_the_comment(tmp_path: Path) -> None:
    env, log = _reminder_env(tmp_path, code="4", stale_only="true")
    (tmp_path / "fake-body").write_text(f"Counts only.\n{_RLINE}\n", encoding="utf-8")
    code, _ = _run_step(_attention_step(), env, tmp_path)
    assert code == 0
    assert any(c.startswith("issue comment 7 ") for c in _calls(log))


@pytest.mark.skipif(_BASH is None, reason="bash not available")
def test_a_reminder_opens_the_issue_when_none_exists(tmp_path: Path) -> None:
    env, log = _reminder_env(tmp_path, code="0", stale_only="false")
    env["FAKE_ISSUE"] = ""
    code, _ = _run_step(_attention_step(), env, tmp_path)
    assert code == 0
    calls = _calls(log)
    created = [c for c in calls if c.startswith("issue create")]
    assert len(created) == 1
    assert "reminders.md" not in created[0]  # the body is neutral, never the reminder
    assert any(c.startswith("issue comment 7 ") and "reminders.md" in c for c in calls)
    assert not any(c.startswith("issue close") for c in calls)


@pytest.mark.skipif(_BASH is None, reason="bash not available")
def test_the_backup_slot_after_an_issue_creating_reminder_posts_nothing(tmp_path: Path) -> None:
    env, log = _reminder_env(tmp_path, code="4", stale_only="true")
    env["FAKE_ISSUE"] = ""
    code, _ = _run_step(_attention_step(), env, tmp_path)
    assert code == 0
    first = _calls(log)
    assert len([c for c in first if c.startswith("issue create")]) == 1
    assert len([c for c in first if c.startswith("issue comment 7 ")]) == 1
    posted = (tmp_path / "reminders.md").read_text(encoding="utf-8")

    # An hour later: the issue now exists, holding a neutral body and the posted comment.
    log.write_text("", encoding="utf-8")
    (tmp_path / "fake-body").write_text("Hand-save reminders follow in the comments.\n")
    (tmp_path / "fake-comment").write_text(posted, encoding="utf-8")
    (tmp_path / "reminders.md").write_text(f"Counts only. Updated now\n{_RLINE}", encoding="utf-8")
    env["FAKE_ISSUE"] = "7"
    code, _ = _run_step(_attention_step(), env, tmp_path)
    assert code == 0
    assert not any(c.startswith(("issue comment", "issue create")) for c in _calls(log))


@pytest.mark.skipif(_BASH is None, reason="bash not available")
def test_a_reminder_comment_does_not_make_the_stale_only_check_repost_staleness(
    tmp_path: Path,
) -> None:
    env, log = _reminder_env(tmp_path, code="4", stale_only="true")
    stale = "- build is stale: last build 2026-10-01"
    (tmp_path / "attention.md").write_text(f"Counts only.\n{stale}\n", encoding="utf-8")
    # The staleness line sits in an earlier comment; the newest comment is another reminder.
    (tmp_path / "fake-comment").write_text(f"Counts only.\n{stale}\n", encoding="utf-8")
    (tmp_path / "last-comment").write_text("some other reminder comment\n", encoding="utf-8")
    env["FAKE_COMMENT_LAST"] = str(tmp_path / "last-comment")
    code, _ = _run_step(_attention_step(), env, tmp_path)
    assert code == 0
    comments = [c for c in _calls(log) if c.startswith("issue comment")]
    assert len(comments) == 1  # the new reminder only
    assert "reminders.md" in comments[0]


@pytest.mark.skipif(_BASH is None, reason="bash not available")
def test_a_failed_push_run_still_comments_the_reminder(tmp_path: Path) -> None:
    env, log = _reminder_env(tmp_path, code="3", stale_only="false")
    (tmp_path / "attention.md").write_text("Counts only.\n- vault push failed", encoding="utf-8")
    code, _ = _run_step(_attention_step(), env, tmp_path)
    assert code == 0
    assert any(c.startswith("issue comment 7 ") and "reminders.md" in c for c in _calls(log))
