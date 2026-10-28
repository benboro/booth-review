"""Digest, attribute and inventory checks for the vendored fonts and their OFL texts."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = REPO_ROOT / "site" / "fonts"

FONT_SHA256 = {
    "lm-roman-demi-latin-600-normal.woff2": (
        "667737468c8b2a50e4b0b2c07ed5a426f88e27655205fe17bc8e4cb3996da2c1"
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
    "OFL-roboto.txt": "Copyright 2011 The Roboto Project Authors",
    "OFL-roboto-condensed.txt": "Copyright 2011 Google Inc.",
}

GUST_LICENCE = {
    "GUST-FONT-LICENSE.txt": "This is version 1.0, dated 22 June 2009, of the GUST Font License",
}
GUST_LICENCE_SHA256 = "5eb61bb836bb1845ef668717cb15b382e997748ce2629e4388cc5e4c3fa4e433"
LM_SUBSET_MAX_BYTES = 30720


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
    assert found == set(FONT_SHA256) | set(OFL_COPYRIGHT) | set(GUST_LICENCE)


@pytest.mark.parametrize("name", sorted(GUST_LICENCE))
def test_gust_licence_present_and_pinned(name: str) -> None:
    raw = (FONT_DIR / name).read_bytes()
    assert GUST_LICENCE[name] in raw.decode("utf-8")
    assert hashlib.sha256(raw).hexdigest() == GUST_LICENCE_SHA256


def test_lm_subset_size_ceiling() -> None:
    size = (FONT_DIR / "lm-roman-demi-latin-600-normal.woff2").stat().st_size
    assert size <= LM_SUBSET_MAX_BYTES


def test_no_crimson_left() -> None:
    """The type swap is complete: no reference to the old serif remains (Plotly's bundle excluded,
    since it carries the CSS colour name)."""
    needle = "crim" + "son"  # split so this file does not match itself
    offenders: list[str] = []
    for top in ("site", "src", "tests", "docs"):
        for path in (REPO_ROOT / top).rglob("*"):
            if (
                path == Path(__file__)
                or not path.is_file()
                or "__pycache__" in path.parts
                or "vendor" in path.parts
            ):
                continue
            if path.suffix in {".woff2", ".png", ".pyc", ".svg", ".jpg"}:
                continue
            if (
                needle in path.name.lower()
                or needle in path.read_text(encoding="utf-8", errors="ignore").lower()
            ):
                offenders.append(path.relative_to(REPO_ROOT).as_posix())
    assert not offenders, offenders
