"""CLI-level tests for `booth-review site` (D-14, SITE-19): the fixture and
vault source paths, contract/digest/key-leak failures, cache-busting, and
the out-dir overwrite safety guard.

Prefers the `--fixture` path (no git vault needed at all) for most tests,
per this repo's own test-fixture conventions (tests/conftest.py,
tests/test_contract.py). `monkeypatch.chdir(tmp_path)` on every test avoids
ever reading this developer's own real `.env`, matching `git_vault`'s own
pattern. `CFBD_API_KEY` is always a synthetic placeholder, never a real key.
Never reads data/vault.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from booth_review.cli import main
from booth_review.contract.models import SITE_DATA_FIELDS, validate_site_data

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_SRC = REPO_ROOT / "site"
DOCS_DIR = REPO_ROOT / "docs"
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "contract" / "site-data.fixture.json"

_SYNTHETIC_KEY = "synthetic-test-key-0000"


@pytest.fixture
def site_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """chdir into a throwaway tmp_path (no real .env visible) with the
    real committed site/ and docs/ wired in by absolute path, and the
    synthetic contract fixture as the default --fixture source.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOOTH_REVIEW_SITE_SRC", str(SITE_SRC))
    monkeypatch.setenv("BOOTH_REVIEW_DOCS", str(DOCS_DIR))
    monkeypatch.setenv("BOOTH_REVIEW_SITE_FIXTURE", str(FIXTURE_PATH))
    monkeypatch.delenv("CFBD_API_KEY", raising=False)
    monkeypatch.delenv("BOOTH_REVIEW_VAULT", raising=False)
    return tmp_path


def test_site_help_exits_0() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["site", "--help"])
    assert exc.value.code == 0


def test_fixture_build_copies_every_site_source_file(site_env: Path) -> None:
    out = site_env / "out"

    exit_code = main(["site", "--fixture", "--out", str(out)])

    assert exit_code == 0
    for path in SITE_SRC.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(SITE_SRC)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if path.suffix not in {".html", ".js", ".css"}:
            continue
        assert (out / rel).is_file(), rel

    assert (out / "site-data.json").is_file()
    assert (out / "methodology.html").is_file()
    assert (out / "coverage.html").is_file()
    assert (out / ".booth-review-site").is_file()


def test_fixture_build_site_data_json_validates(site_env: Path) -> None:
    out = site_env / "out"
    assert main(["site", "--fixture", "--out", str(out)]) == 0

    payload = json.loads((out / "site-data.json").read_text(encoding="utf-8"))
    validate_site_data(payload)
    assert set(payload["telecasts"].keys()) == set(SITE_DATA_FIELDS)


def test_fixture_build_index_html_tokens_replaced_and_cache_busted(site_env: Path) -> None:
    out = site_env / "out"
    assert main(["site", "--fixture", "--out", str(out)]) == 0

    index_text = (out / "index.html").read_text(encoding="utf-8")
    assert "__SITE_DATA_VERSION__" not in index_text
    assert "<!-- booth-review:footer -->" not in index_text
    assert "RatingsReference.com" in index_text
    assert "CollegeFootballData.com" in index_text

    body = (out / "site-data.json").read_bytes()
    expected_version = hashlib.sha256(body).hexdigest()[:10]
    match = re.search(r'name="site-data-version" content="([0-9a-f]{10})"', index_text)
    assert match is not None
    assert match.group(1) == expected_version


def test_fixture_build_file_suffixes_and_one_json_file(site_env: Path) -> None:
    out = site_env / "out"
    assert main(["site", "--fixture", "--out", str(out)]) == 0

    json_files = []
    for path in out.rglob("*"):
        if not path.is_file():
            continue
        if path.name == ".booth-review-site":
            continue
        assert path.suffix in {".html", ".js", ".css", ".json"}, path
        if path.suffix == ".json":
            json_files.append(path)
    assert len(json_files) == 1


def test_key_check_passed_when_key_set(
    site_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CFBD_API_KEY", _SYNTHETIC_KEY)
    out = site_env / "out"

    exit_code = main(["site", "--fixture", "--out", str(out)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "cfbd key check: passed" in output
    assert output.splitlines()[0].startswith("site (fixture): 12 telecasts, 10 people,")


def test_key_check_skipped_when_no_key(site_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = site_env / "out"

    exit_code = main(["site", "--fixture", "--out", str(out)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "cfbd key check: skipped (no key configured)" in output


def test_key_leak_detected_removes_output_and_never_prints_key(
    site_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CFBD_API_KEY", _SYNTHETIC_KEY)

    tainted_src = site_env / "site_src_tainted"
    shutil.copytree(SITE_SRC, tainted_src)
    (tainted_src / "modules" / "leak.js").write_text(f"// {_SYNTHETIC_KEY}\n", encoding="utf-8")
    monkeypatch.setenv("BOOTH_REVIEW_SITE_SRC", str(tainted_src))

    out = site_env / "out"
    exit_code = main(["site", "--fixture", "--out", str(out)])

    assert exit_code == 3
    assert not out.exists()
    captured = capsys.readouterr()
    assert _SYNTHETIC_KEY not in captured.out
    assert _SYNTHETIC_KEY not in captured.err


def test_contract_failure_exits_3_and_names_contract(
    site_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["telecasts"]["venue"] = ["Example Field"] * len(payload["telecasts"]["season"])
    bad_fixture = site_env / "bad-fixture.json"
    bad_fixture.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("BOOTH_REVIEW_SITE_FIXTURE", str(bad_fixture))

    out = site_env / "out"
    exit_code = main(["site", "--fixture", "--out", str(out)])

    assert exit_code == 3
    assert "contract" in capsys.readouterr().err


def test_bundle_digest_mismatch_exits_3_and_names_digest(
    site_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tainted_src = site_env / "site_src_bad_bundle"
    shutil.copytree(SITE_SRC, tainted_src)
    bundle_path = tainted_src / "vendor" / "plotly-gl2d-4.1.1.min.js"
    corrupted = bytearray(bundle_path.read_bytes())
    corrupted[0] ^= 0xFF
    bundle_path.write_bytes(bytes(corrupted))
    monkeypatch.setenv("BOOTH_REVIEW_SITE_SRC", str(tainted_src))

    out = site_env / "out"
    exit_code = main(["site", "--fixture", "--out", str(out)])

    assert exit_code == 3
    assert "digest" in capsys.readouterr().err


def test_vault_source_build_succeeds_and_vault_unchanged(
    site_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = site_env / "vault"
    processed = vault_root / "processed"
    processed.mkdir(parents=True)
    site_data_path = processed / "site-data.json"
    site_data_path.write_bytes(FIXTURE_PATH.read_bytes())
    monkeypatch.setenv("BOOTH_REVIEW_VAULT", str(vault_root))
    before_bytes = site_data_path.read_bytes()

    out = site_env / "out"
    exit_code = main(["site", "--out", str(out)])

    assert exit_code == 0
    assert site_data_path.read_bytes() == before_bytes
    assert (out / "site-data.json").is_file()


def test_vault_source_missing_file_exits_3_and_names_build(
    site_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault_root = site_env / "vault-empty"
    (vault_root / "processed").mkdir(parents=True)
    monkeypatch.setenv("BOOTH_REVIEW_VAULT", str(vault_root))

    out = site_env / "out"
    exit_code = main(["site", "--out", str(out)])

    assert exit_code == 3
    assert "booth-review build" in capsys.readouterr().err


def test_out_dir_without_marker_refuses_overwrite(
    site_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = site_env / "out"
    out.mkdir()
    sentinel = out / "not-ours.txt"
    sentinel.write_text("keep me\n", encoding="utf-8")

    exit_code = main(["site", "--fixture", "--out", str(out)])

    assert exit_code == 3
    assert sentinel.is_file()
    assert sentinel.read_text(encoding="utf-8") == "keep me\n"


def test_rerun_into_previous_build_dir_succeeds(site_env: Path) -> None:
    out = site_env / "out"
    assert main(["site", "--fixture", "--out", str(out)]) == 0

    exit_code = main(["site", "--fixture", "--out", str(out)])

    assert exit_code == 0
    assert (out / ".booth-review-site").is_file()


def _siblings(out: Path) -> list[str]:
    """Hidden staging/retired dirs `assemble_site` may leave next to `out`."""
    return sorted(p.name for p in out.parent.iterdir() if p.name.startswith(f".{out.name}."))


def test_failed_build_leaves_no_output_and_rerun_succeeds(
    site_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WR-01: a build that fails after the out dir would have been created
    (here: docs/ is missing its pages) leaves nothing behind -- no partly
    built, unmarked out dir the next run would refuse to overwrite, and no
    staging dir -- so a normal rerun succeeds."""
    empty_docs = site_env / "empty-docs"
    empty_docs.mkdir()
    monkeypatch.setenv("BOOTH_REVIEW_DOCS", str(empty_docs))
    out = site_env / "out"

    assert main(["site", "--fixture", "--out", str(out)]) == 3
    assert not out.exists()
    assert _siblings(out) == []

    monkeypatch.setenv("BOOTH_REVIEW_DOCS", str(DOCS_DIR))
    assert main(["site", "--fixture", "--out", str(out)]) == 0
    assert (out / ".booth-review-site").is_file()
    assert _siblings(out) == []


def test_failed_build_keeps_the_previous_build_intact(
    site_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WR-01: a failed rebuild over a previous build never deletes or
    half-overwrites it -- the old site stays byte-for-byte in place."""
    out = site_env / "out"
    assert main(["site", "--fixture", "--out", str(out)]) == 0
    before = {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file()}

    empty_docs = site_env / "empty-docs"
    empty_docs.mkdir()
    monkeypatch.setenv("BOOTH_REVIEW_DOCS", str(empty_docs))
    assert main(["site", "--fixture", "--out", str(out)]) == 3

    after = {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file()}
    assert after == before
    assert _siblings(out) == []


def test_key_leak_keeps_the_previous_build_and_removes_the_leaky_one(
    site_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WR-01/T-04-13: a leak caught by the guard never reaches the out dir;
    a previous clean build there is left as it was."""
    out = site_env / "out"
    assert main(["site", "--fixture", "--out", str(out)]) == 0

    monkeypatch.setenv("CFBD_API_KEY", _SYNTHETIC_KEY)
    tainted_src = site_env / "site_src_tainted"
    shutil.copytree(SITE_SRC, tainted_src)
    (tainted_src / "modules" / "leak.js").write_text(f"// {_SYNTHETIC_KEY}\n", encoding="utf-8")
    monkeypatch.setenv("BOOTH_REVIEW_SITE_SRC", str(tainted_src))

    assert main(["site", "--fixture", "--out", str(out)]) == 3
    assert (out / ".booth-review-site").is_file()
    assert not (out / "modules" / "leak.js").exists()
    assert _siblings(out) == []


def _ci_key_guard_step() -> dict[str, Any]:
    ci = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    steps = [
        step for step in ci["jobs"]["check"]["steps"] if "CFBD_API_KEY" in (step.get("env") or {})
    ]
    assert len(steps) == 1, "ci.yml must set CFBD_API_KEY on exactly one step"
    return steps[0]  # type: ignore[no-any-return]


def test_ci_runs_the_key_leak_guard_with_a_synthetic_canary_not_a_secret() -> None:
    """WR-02: CI sets a synthetic canary key (never a `secrets.` reference) on
    a `booth-review site` step that fails unless the guard reports `passed`,
    so the key-leak grep can't silently skip in CI."""
    step = _ci_key_guard_step()
    canary = step["env"]["CFBD_API_KEY"]
    assert canary.startswith("ci-canary-")
    assert "${{" not in canary
    assert "booth-review site --fixture" in step["run"]
    assert "grep -qx 'cfbd key check: passed'" in step["run"]


def test_ci_canary_key_makes_the_guard_run_and_catches_an_embedded_key(
    site_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """WR-02: with CI's own canary configured, a clean build reports the
    exact line the CI step greps for, and a build that embeds the configured
    key is refused."""
    canary = _ci_key_guard_step()["env"]["CFBD_API_KEY"]
    monkeypatch.setenv("CFBD_API_KEY", canary)

    assert main(["site", "--fixture", "--out", str(site_env / "out")]) == 0
    assert "cfbd key check: passed" in capsys.readouterr().out.splitlines()

    tainted_src = site_env / "site_src_tainted"
    shutil.copytree(SITE_SRC, tainted_src)
    (tainted_src / "modules" / "config.js").write_text(
        f"export const KEY = '{canary}';\n", encoding="utf-8"
    )
    monkeypatch.setenv("BOOTH_REVIEW_SITE_SRC", str(tainted_src))
    assert main(["site", "--fixture", "--out", str(site_env / "out2")]) == 3
    assert not (site_env / "out2").exists()
