"""Digest and normalization checks for the vendored Plotly.js full bundle (D-14).

The bundle at site/vendor/plotly-4.1.1.min.js is downloaded once and pinned by
its SHA-256 digest. These tests prove the committed bytes still match that pinned
digest, the recorded .sha256 file agrees, and git never text-normalizes the bundle
(which would silently change its bytes and invalidate the pinned digest).
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

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
