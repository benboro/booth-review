"""Digest and normalization checks for the vendored Plotly.js full bundle (D-14).

The bundle at site/vendor/plotly-4.1.1.min.js is downloaded once and pinned by
its SHA-256 digest. These tests prove the committed bytes still match that pinned
digest, the recorded .sha256 file agrees, and git never text-normalizes the bundle
(which would silently change its bytes and invalidate the pinned digest).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from booth_review.build import site_assembly
from booth_review.errors import SiteBuildError

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = REPO_ROOT / "site" / "vendor" / "plotly-4.1.1.min.js"
DIGEST_PATH = REPO_ROOT / "site" / "vendor" / "plotly-4.1.1.min.js.sha256"

EXPECTED_SHA256 = "3b6e15d45dbb7fca5bd2094291e961ddc5472cd887009e6009a56dab668d721f"


def test_bundle_matches_pinned_digest() -> None:
    digest = hashlib.sha256(BUNDLE_PATH.read_bytes()).hexdigest()
    assert digest == EXPECTED_SHA256


def test_recorded_digest_file_matches() -> None:
    tokens = DIGEST_PATH.read_text(encoding="utf-8").split()
    assert tokens[0] == EXPECTED_SHA256
    assert tokens[1] == "plotly-4.1.1.min.js"


def test_bundle_is_not_text_normalized() -> None:
    result = subprocess.run(
        ["git", "check-attr", "text", "--", "site/vendor/plotly-4.1.1.min.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "text: unset" in result.stdout


GEOMETRY_PATH = REPO_ROOT / "site" / "vendor" / "us-states-albers.js"
GEOMETRY_DIGEST_PATH = REPO_ROOT / "site" / "vendor" / "us-states-albers.js.sha256"
GEOMETRY_SHA256 = "ff1e0a82d121f389782ef3ff466fc2910a08b7594af9e92598ac4032a9e2d3dc"


def test_geometry_matches_pinned_digest() -> None:
    assert hashlib.sha256(GEOMETRY_PATH.read_bytes()).hexdigest() == GEOMETRY_SHA256


def test_geometry_recorded_digest_file_matches() -> None:
    tokens = GEOMETRY_DIGEST_PATH.read_text(encoding="utf-8").split()
    assert tokens[0] == GEOMETRY_SHA256
    assert tokens[1] == "us-states-albers.js"


def test_geometry_is_not_text_normalized() -> None:
    result = subprocess.run(
        ["git", "check-attr", "text", "--", "site/vendor/us-states-albers.js"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "text: unset" in result.stdout


def test_build_check_pins_same_geometry_digest() -> None:
    assert site_assembly.MAP_GEOMETRY_SHA256 == GEOMETRY_SHA256


def test_geometry_structure() -> None:
    text = GEOMETRY_PATH.read_text(encoding="utf-8")
    body = text[text.index("export const US_STATES") :]
    ids = re.findall(r"id: '(\d\d)'", body)
    assert len(ids) == 50
    assert len(set(ids)) == 50
    assert "02" not in ids
    assert "15" in ids
    hawaii = next(line for line in body.splitlines() if "id: '15'" in line)
    for line in body.splitlines():
        if "id: '" not in line:
            continue
        numbers = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", line.split("rings:")[1])]
        assert len(numbers) % 2 == 0
        xs, ys = numbers[0::2], numbers[1::2]
        assert all(0 <= x <= 975 for x in xs)
        assert all(0 <= y <= 610 for y in ys)
        if line is hawaii:
            assert all(200 <= x <= 345 for x in xs)
            assert all(520 <= y <= 610 for y in ys)


def test_tampered_geometry_is_refused(tmp_path: Path) -> None:
    site_copy = tmp_path / "site"
    shutil.copytree(REPO_ROOT / "site", site_copy)
    with (site_copy / "vendor" / "us-states-albers.js").open("ab") as handle:
        handle.write(b"\n")
    with pytest.raises(SiteBuildError, match="map geometry digest mismatch"):
        site_assembly._verify_bundle(site_copy)
