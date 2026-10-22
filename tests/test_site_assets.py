"""Digest, attribute and inventory checks for the vendored fonts and their OFL texts."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = REPO_ROOT / "site" / "fonts"

FONT_SHA256 = {
    "crimson-text-latin-600-normal.woff2": (
        "e2ca4f57a77f4db70d61c4d16e748545ce2000e0252be1f67fa1c964040f9b9b"
    ),
    "roboto-latin-400-normal.woff2": (
        "425c0713a8176f92273d378599c7eac57de7fafabd4bd0ed457b70eb8f80d371"
    ),
    "roboto-latin-600-normal.woff2": (
        "3eac5e2f468629b4673394bb25a387aba117e0dfa646b7f371a2cbd2bbf91d87"
    ),
    "roboto-condensed-latin-400-normal.woff2": (
        "543c03fff71d1b39590af102e0852c2dbce46f4dbe4faaebafbef6edc82e78f5"
    ),
}

OFL_COPYRIGHT = {
    "OFL-crimson-text.txt": "Copyright 2010 The Crimson Text Project Authors",
    "OFL-roboto.txt": "Copyright 2011 The Roboto Project Authors",
    "OFL-roboto-condensed.txt": "Copyright 2011 Google Inc.",
}


@pytest.mark.parametrize("name", sorted(FONT_SHA256))
def test_font_matches_pinned_digest(name: str) -> None:
    digest = hashlib.sha256((FONT_DIR / name).read_bytes()).hexdigest()
    assert digest == FONT_SHA256[name]


@pytest.mark.parametrize("name", sorted(FONT_SHA256))
def test_font_is_not_text_normalized(name: str) -> None:
    result = subprocess.run(
        ["git", "check-attr", "text", "--", f"site/fonts/{name}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "text: unset" in result.stdout


@pytest.mark.parametrize("name", sorted(OFL_COPYRIGHT))
def test_ofl_text_present_with_copyright_line(name: str) -> None:
    text = (FONT_DIR / name).read_text(encoding="utf-8")
    assert text.startswith(OFL_COPYRIGHT[name])
    assert "SIL OPEN FONT LICENSE" in text.upper()


def test_font_dir_holds_exactly_the_approved_files() -> None:
    found = {path.name for path in FONT_DIR.iterdir()}
    assert found == set(FONT_SHA256) | set(OFL_COPYRIGHT)
