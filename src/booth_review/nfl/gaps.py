"""The NFL 506 gap report: which week pages need a hand-save (D-10).

Judged against the nflverse schedule (never the 506 site menu) and each page's browser
save time (`saved_at`, with the import time `fetched_at` as a counted
fallback). Sends no requests and reads only the vault's cached pages, manifest
and schedule file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from booth_review.config import DataPaths
from booth_review.job.gaps506 import GAME_LENGTH
from booth_review.nfl.layout import NFLVERSE_SCHEDULES_PATH, nfl_506_path
from booth_review.nfl.schedule import parse_schedules
from booth_review.sources.sports506.importer import NFL_PROFILE
from booth_review.transport.cache import Manifest

_TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"
_SOURCE = "nfl_sports506"


@dataclass(frozen=True)
class NflGaps:
    """Which of `season`'s already-played NFL week pages need attention."""

    season: int
    missing: list[str]
    stale: list[str]
    judged: int
    saved_at_fallbacks: int
    """Judged pages whose staleness used the import time because no saved_at exists."""


def find_nfl_506_gaps(paths: DataPaths, season: int, now: datetime) -> NflGaps | None:
    """Name the played regular-season weeks whose page is missing or saved too early.

    Returns None when the schedule file is absent (nothing to judge against).
    """
    schedule = paths.raw / NFLVERSE_SCHEDULES_PATH
    if not schedule.is_file():
        return None
    games = [
        g for g in parse_schedules(schedule.read_bytes(), seasons=[season]) if g.game_type == "REG"
    ]
    last_kickoff: dict[str, datetime] = {}
    for game in games:
        label = str(game.week)
        kickoff = game.kickoff_et.astimezone(UTC)
        if label not in last_kickoff or kickoff > last_kickoff[label]:
            last_kickoff[label] = kickoff

    latest: dict[str, dict[str, object]] = {}
    for entry in Manifest(paths.manifest).entries():
        path = entry.get("path")
        fetched = entry.get("fetched_at")
        if entry.get("source") != _SOURCE or not isinstance(path, str):
            continue
        if not isinstance(fetched, str):
            continue
        current = latest.get(path)
        if current is None or fetched > str(current["fetched_at"]):
            latest[path] = entry

    missing: list[str] = []
    stale: list[str] = []
    judged = 0
    fallbacks = 0
    for label in NFL_PROFILE.labels(season):
        if label not in last_kickoff:
            continue
        played_at = last_kickoff[label] + GAME_LENGTH
        if now <= played_at:
            continue
        judged += 1
        rel = nfl_506_path(season, int(label))
        if not (paths.raw / rel).is_file():
            missing.append(label)
            continue
        found = latest.get(rel)
        if found is None:
            continue  # cached with no manifest entry: not reported stale
        saved = found.get("saved_at")
        if isinstance(saved, str):
            stamp = saved
        else:
            stamp = str(found["fetched_at"])
            fallbacks += 1
        if datetime.strptime(stamp, _TIME_FMT).replace(tzinfo=UTC) < played_at:
            stale.append(label)

    return NflGaps(
        season=season,
        missing=missing,
        stale=stale,
        judged=judged,
        saved_at_fallbacks=fallbacks,
    )
