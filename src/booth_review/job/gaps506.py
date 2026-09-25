"""The 2026 506 gap finder: which week pages need a hand-save (Claude's Discretion).

The scheduled job never fetches 506sports.com -- it is blocked (403 to a
correctly-identified client), and AGENTS.md says never work around that. This
module only names, by week label, which of the current season's 506 pages
are missing or were saved before their games finished, so the job can list
them in the D-12 attention issue. The user hand-saves and imports those pages
with `booth-review import 506 --season <yr> [--force]`; this module sends no
requests and reads nothing outside the vault (already-cached 506 pages and
the manifest) plus the CFBD games already collected for the season.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from booth_review.config import DataPaths
from booth_review.sources.cfbd.parser import CfbdGame
from booth_review.sources.sports506.collector import WEEK_LABELS
from booth_review.sources.sports506.weeks import discover_season_weeks, label_from_cache_name
from booth_review.transport.cache import Manifest

EASTERN = ZoneInfo("America/New_York")

# A game counts as "played" once this long has passed since its kickoff.
GAME_LENGTH = timedelta(hours=4)

# The largest gap (in ET calendar days) between consecutive CFBD regular
# week-1 kickoffs that splits the week into 506's own "0" (early openers)
# and "1" (the rest); below this, every week-1 game is 506's "1".
WEEK_ONE_SPLIT_GAP_DAYS = 4

_TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class Gaps506:
    """Which of `season`'s already-played 506 week pages need attention."""

    season: int
    missing: list[str]
    stale: list[str]
    judged: int
    """Count of played weeks actually evaluated (missing + stale + fine)."""


def _split_week_one(games: Sequence[CfbdGame]) -> dict[str, list[CfbdGame]]:
    """Split CFBD regular week-1 games into 506's "0" (openers) and "1".

    Sorted by kickoff; the split lands at the largest gap (in ET calendar
    days) between consecutive kickoffs, when that gap is at least
    WEEK_ONE_SPLIT_GAP_DAYS. With no such gap, every game is "1".
    """
    ordered = sorted(games, key=lambda g: g.start_date)
    if len(ordered) < 2:
        return {"1": list(ordered)}

    best_gap = -1
    split_index = 0
    for i in range(1, len(ordered)):
        prev_et = ordered[i - 1].start_date.astimezone(EASTERN).date()
        cur_et = ordered[i].start_date.astimezone(EASTERN).date()
        gap_days = (cur_et - prev_et).days
        if gap_days > best_gap:
            best_gap = gap_days
            split_index = i

    if best_gap >= WEEK_ONE_SPLIT_GAP_DAYS:
        return {"0": ordered[:split_index], "1": ordered[split_index:]}
    return {"1": ordered}


def week_windows(games: Sequence[CfbdGame], season: int) -> dict[str, tuple[datetime, datetime]]:
    """Map each 506 week label to its (first_kickoff, last_kickoff) UTC window.

    Regular week N>=2 maps to label str(N); regular week 1 is split into
    "0"/"1" (see `_split_week_one`); postseason games map to "B". Labels
    outside WEEK_LABELS (e.g. spring games, an unrecognized week number) are
    dropped.
    """
    by_label: dict[str, list[CfbdGame]] = {}
    week_one: list[CfbdGame] = []

    for game in games:
        if game.season != season:
            continue
        if game.season_type == "postseason":
            by_label.setdefault("B", []).append(game)
        elif game.season_type == "regular":
            if game.week == 1:
                week_one.append(game)
            else:
                by_label.setdefault(str(game.week), []).append(game)
        # Other season types (e.g. spring_regular) are out of scope.

    if week_one:
        for label, group in _split_week_one(week_one).items():
            by_label.setdefault(label, []).extend(group)

    windows: dict[str, tuple[datetime, datetime]] = {}
    for label, group in by_label.items():
        if label not in WEEK_LABELS or not group:
            continue
        starts = [g.start_date for g in group]
        windows[label] = (min(starts), max(starts))
    return windows


def find_506_gaps(
    paths: DataPaths, season: int, games: Sequence[CfbdGame], now: datetime
) -> Gaps506:
    """Name the played 506 week pages for `season` that are missing or stale."""
    windows = week_windows(games, season)

    season_dir = paths.raw / "sports506" / str(season)
    cached_by_label: dict[str, str] = {}
    if season_dir.is_dir():
        for cached_path in sorted(season_dir.iterdir()):
            label = label_from_cache_name(cached_path.name)
            if label is not None:
                cached_by_label[label] = cached_path.name

    if cached_by_label:
        discovered: set[str] = set()
        for name in cached_by_label.values():
            html = (season_dir / name).read_bytes()
            discovered.update(discover_season_weeks(html, season).labels)
        labels = [label for label in WEEK_LABELS if label in windows and label in discovered]
    else:
        labels = [label for label in WEEK_LABELS if label in windows]

    manifest_prefix = f"sports506/{season}/"
    latest_fetch_by_label: dict[str, str] = {}
    for manifest_entry in Manifest(paths.manifest).entries():
        entry_path = manifest_entry.get("path")
        if not isinstance(entry_path, str) or not entry_path.startswith(manifest_prefix):
            continue
        label = label_from_cache_name(entry_path.rsplit("/", 1)[-1])
        if label is None:
            continue
        fetched_at = manifest_entry.get("fetched_at")
        if not isinstance(fetched_at, str):
            continue
        current = latest_fetch_by_label.get(label)
        if current is None or fetched_at > current:
            latest_fetch_by_label[label] = fetched_at

    missing: list[str] = []
    stale: list[str] = []
    judged = 0

    for label in labels:
        _first_kickoff, last_kickoff = windows[label]
        played_at = last_kickoff + GAME_LENGTH
        if now <= played_at:
            continue  # not yet played

        judged += 1

        if label not in cached_by_label:
            missing.append(label)
            continue

        latest_fetch = latest_fetch_by_label.get(label)
        if latest_fetch is None:
            continue  # cached with no manifest entry: not reported stale

        fetched_dt = datetime.strptime(latest_fetch, _TIME_FMT).replace(tzinfo=UTC)
        if fetched_dt < played_at:
            stale.append(label)

    return Gaps506(season=season, missing=missing, stale=stale, judged=judged)
