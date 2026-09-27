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

import pytest

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
