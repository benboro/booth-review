"""docs/LAUNCH.md structure and hygiene (D-15). The file is public: it names no
private data repo, no scratch repo, and no Actions run link.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_LAUNCH = _ROOT / "docs" / "LAUNCH.md"
_CHECKBOX = re.compile(r"^- \[( |x)\] ")
_POINTER = re.compile(r"tests/[A-Za-z0-9_/]+\.py::(test_[A-Za-z0-9_]+)")
_FILE_POINTER = re.compile(r"(tests/[A-Za-z0-9_/]+\.py)::(test_[A-Za-z0-9_]+)")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_SLUG = re.compile(r"benboro/[A-Za-z0-9_.-]+")
_ALLOWED_SLUGS = {"benboro/benboro.github.io", "benboro/booth-review"}


def _lines() -> list[str]:
    return _LAUNCH.read_text(encoding="utf-8").splitlines()


def _checkbox_lines() -> list[str]:
    return [line for line in _lines() if _CHECKBOX.match(line)]


def test_checked_lines_have_a_date_and_evidence() -> None:
    checked = [line for line in _checkbox_lines() if line.startswith("- [x]")]
    assert len(checked) >= 20
    for line in checked:
        assert _DATE.search(line), line
        assert _POINTER.search(line) or "evidence:" in line, line


def test_every_pointer_names_an_existing_test() -> None:
    pointers = _FILE_POINTER.findall(_LAUNCH.read_text(encoding="utf-8"))
    assert pointers
    for relative, name in pointers:
        path = _ROOT / relative
        assert path.is_file(), relative
        assert f"def {name}" in path.read_text(encoding="utf-8"), f"{relative}::{name}"


def test_unchecked_lines_are_pending_except_the_last() -> None:
    boxes = _checkbox_lines()
    for line in boxes[:-1]:
        if line.startswith("- [ ]"):
            assert "pending" in line, line


def test_last_checkbox_is_the_publish_flip_and_unchecked() -> None:
    last = _checkbox_lines()[-1]
    assert last.startswith("- [ ]")
    assert "PUBLISH_ENABLED" in last


def test_no_private_names_or_run_links() -> None:
    text = _LAUNCH.read_text(encoding="utf-8")
    for forbidden in ("booth-review-data", "site-scratch", "actions/runs/"):
        assert forbidden not in text, forbidden


def test_repo_slugs_are_allowlisted() -> None:
    text = _LAUNCH.read_text(encoding="utf-8")
    slugs = set(_SLUG.findall(text))
    assert slugs
    # A trailing sentence period can ride along on a match.
    cleaned = {slug.rstrip(".") for slug in slugs}
    assert cleaned <= _ALLOWED_SLUGS, cleaned - _ALLOWED_SLUGS


def test_local_vault_origin_name_is_absent() -> None:
    vault = _ROOT / "data" / "vault"
    if not vault.is_dir():
        pytest.skip("no local vault")
    result = subprocess.run(
        ["git", "-C", str(vault), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        pytest.skip("vault has no origin")
    name = result.stdout.strip().rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    if not name:
        pytest.skip("vault origin has no parseable name")
    assert name not in _LAUNCH.read_text(encoding="utf-8")
