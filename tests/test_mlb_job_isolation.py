"""D-16: the scheduled job never builds, collects or freezes MLB data."""

from __future__ import annotations

from pathlib import Path

import booth_review.job.runner as runner


def test_job_runner_has_no_mlb_step() -> None:
    text = Path(runner.__file__).read_text(encoding="utf-8").lower()
    for word in ("mlb", "retrosheet", "statsapi"):
        assert word not in text, word
