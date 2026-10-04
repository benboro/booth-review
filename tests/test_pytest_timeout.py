"""The per-test timeout guard: a hung test must fail, not block the run.

A Playwright chart test once hung for hours on a Plotly redraw loop because
nothing bounded a single test. These tests prove the limit is configured and
that pytest-timeout actually stops a stuck test.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_sets_a_per_test_timeout() -> None:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    timeout = config["tool"]["pytest"]["ini_options"]["timeout"]
    assert isinstance(timeout, int)
    assert 0 < timeout <= 600


def test_a_hung_test_fails_at_the_timeout(tmp_path: Path) -> None:
    (tmp_path / "test_hang.py").write_text(
        "import time\n\ndef test_hang():\n    time.sleep(60)\n", encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--timeout=1"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1
    assert "Timeout" in result.stdout
