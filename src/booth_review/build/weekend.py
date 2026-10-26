"""The This weekend inputs for the CFB build (Phase 18 Plan 06).

Picks the current weekend, lists the season's week labels, resolves a network
for each unplayed game from CFBD's media rows, and reads the freshness stamps
from the request manifest. It reads only what the vault already holds: no
request, no wall clock. The week logic itself is `job.gaps506.week_windows`
and `job.gaps_espnpr.week_spans`; nothing here re-implements it.

The current weekend is the first numbered week whose last FBS-involving
kickoff plus GAME_LENGTH is after the build time. CFBD's `completed` flag is
never read: it lags the real result by hours (RESEARCH Pitfall 2).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from booth_review.build.crew_backup import ScheduledCrew
from booth_review.config import DataPaths
from booth_review.job.gaps506 import GAME_LENGTH, _entry_time, week_windows
from booth_review.job.gaps_espnpr import espn_week_label, week_spans
from booth_review.resolve.games import is_fbs_game
from booth_review.resolve.networks import NetworkTable, primary_network
from booth_review.sources.cfbd.parser import CfbdGame, CfbdMedia
from booth_review.sources.sports506.weeks import label_from_cache_name
from booth_review.transport.cache import Manifest

# Only these CFBD media types name a TV network; radio and mobile never do.
_NETWORK_MEDIA_TYPES = frozenset({"tv", "web"})
_TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"
_SUNDAY_OFFSET = timedelta(days=6)

WeekendStamps = dict[str, str | None]


@dataclass(frozen=True)
class ScheduleInputs:
    """Everything the builder needs to ship telecasts_scheduled and the weekend stamp."""

    season: int = 0
    games: tuple[CfbdGame, ...] = ()
    weeks: tuple[dict[str, object], ...] = ()
    # CFBD game id -> 506/ESPN week label of that regular-season game.
    labels: dict[int, str] = field(default_factory=dict)
    # CFBD game id -> (network id or None, mapped tv/web outlet ids).
    networks: dict[int, tuple[str | None, list[str]]] = field(default_factory=dict)
    network_unmapped: int = 0
    stamps: dict[str, WeekendStamps] = field(default_factory=dict)
    # CFBD game id -> ESPN Press Room booth for a game with no telecast (18-13 F7).
    crews: dict[int, ScheduledCrew] = field(default_factory=dict)


def _fbs_regular(games: Iterable[CfbdGame], season: int) -> list[CfbdGame]:
    return [g for g in games if g.season == season and is_fbs_game(g)]


def _numbered(windows: dict[str, tuple[datetime, datetime]]) -> list[str]:
    return sorted((label for label in windows if label.isdigit()), key=int)


def current_label(games: Sequence[CfbdGame], season: int, now: datetime) -> str | None:
    """The numbered week the This weekend view opens on at `now` (aware).

    The first week whose last kickoff plus GAME_LENGTH is after `now`; after
    the last numbered week it stays on that week (bowls deferred). None when
    the season has no numbered week.
    """
    if now.tzinfo is None:
        raise ValueError("current_label needs an aware datetime")
    windows = week_windows(_fbs_regular(games, season), season)
    labels = _numbered(windows)
    if not labels:
        return None
    for label in labels:
        if now <= windows[label][1] + GAME_LENGTH:
            return label
    return labels[-1]


def week_labels(games: Sequence[CfbdGame], season: int) -> dict[int, str]:
    """CFBD game id -> week label for every FBS-involving regular-season game."""
    fbs = _fbs_regular(games, season)
    windows = week_windows(fbs, season)
    return {g.id: espn_week_label(g, windows) for g in fbs if g.season_type in (None, "regular")}


def week_refs(games: Sequence[CfbdGame], season: int) -> list[dict[str, object]]:
    """Each numbered week's label, number and Monday-to-Sunday ET dates, by number."""
    spans = week_spans(_fbs_regular(games, season), season)
    refs: list[dict[str, object]] = []
    for label in sorted(spans, key=int):
        monday = spans[label]
        refs.append(
            {
                "label": label,
                "number": int(label),
                "start": monday.date().isoformat(),
                "end": (monday + _SUNDAY_OFFSET).date().isoformat(),
            }
        )
    return refs


def schedule_networks(
    media_rows: Iterable[CfbdMedia],
    season: int,
    table: NetworkTable,
    counted: Collection[int] | None = None,
    primary_overrides: Mapping[int, str] | None = None,
) -> tuple[dict[int, tuple[str | None, list[str]]], int]:
    """Resolve each game's network from its tv (then web) CFBD media rows.

    Radio and mobile rows are ignored. An outlet the crosswalk does not map
    leaves the network null; a game whose tv/web outlets all failed to map is
    counted in the second return value, among the `counted` game ids when
    given (the schedule's FBS regular-season games, 18-13 F10). A
    primary_network_overrides.csv row replaces the network by CFBD game id, as
    the telecast build does (18-13 F20).
    """
    tv: dict[int, list[str]] = {}
    web: dict[int, list[str]] = {}
    for media in media_rows:
        if media.season != season or not media.outlet:
            continue
        if media.media_type not in _NETWORK_MEDIA_TYPES:
            continue
        bucket = tv if media.media_type == "tv" else web
        bucket.setdefault(media.id, []).append(media.outlet)

    overrides = primary_overrides or {}
    override_only = {g for g in overrides if counted is None or g in counted}
    result: dict[int, tuple[str | None, list[str]]] = {}
    unmapped = 0
    for game_id in sorted(set(tv) | set(web) | override_only):
        outlet_ids: dict[str, None] = {}
        network: str | None = None
        any_unmapped = False
        for texts in (tv.get(game_id, []), web.get(game_id, [])):
            if not texts:
                continue
            picked = primary_network(texts, season, table)
            any_unmapped = any_unmapped or bool(picked.unmapped)
            for outlet_id in picked.outlets:
                outlet_ids.setdefault(outlet_id, None)
            if network is None:
                network = picked.network_id
        if game_id in overrides:
            network = overrides[game_id]
            outlet_ids.setdefault(network, None)
        if network is None and any_unmapped and (counted is None or game_id in counted):
            unmapped += 1
        result[game_id] = (network, list(outlet_ids))
    return result, unmapped


def _fmt(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(_TIME_FMT)


def weekend_stamps(
    paths: DataPaths,
    season: int,
    labels: Sequence[str],
    *,
    entries: list[dict[str, object]] | None = None,
) -> dict[str, WeekendStamps]:
    """Per week label: the schedule, 506 and ESPN Press Room stamps from manifest lines.

    schedule_updated_at is the newest change (a new sha256 for the path) to the
    CFBD games or media cache for `season`; crews_506_saved_at is the latest
    506 page line for the label (saved time, else import time);
    crews_espnpr_saved_at and espnpr_week come from that week's commentators
    page. A stamp is None when its source never landed.
    """
    manifest_entries = entries if entries is not None else list(Manifest(paths.manifest).entries())
    schedule_paths = {f"cfbd/games/{season}.json", f"cfbd/media/{season}.json"}
    last_sha: dict[str, object] = {}
    schedule_newest: datetime | None = None
    s506: dict[str, tuple[str, str]] = {}
    espn: dict[str, tuple[str, str]] = {}
    for entry in manifest_entries:
        path = entry.get("path")
        if not isinstance(path, str):
            continue
        fetched_at = entry.get("fetched_at")
        if path in schedule_paths:
            sha = entry.get("sha256")
            if sha is None or not isinstance(fetched_at, str):
                continue
            previous = last_sha.get(path)
            last_sha[path] = sha
            if previous == sha:
                continue
            stamp = datetime.strptime(fetched_at, _TIME_FMT).replace(tzinfo=UTC)
            schedule_newest = stamp if schedule_newest is None else max(schedule_newest, stamp)
            continue
        if not isinstance(fetched_at, str):
            continue
        when = _entry_time(entry)
        if when is None:
            continue
        if path.startswith(f"sports506/{season}/"):
            label = label_from_cache_name(path.rsplit("/", 1)[-1])
            if label is not None and fetched_at >= s506.get(label, ("", ""))[0]:
                s506[label] = (fetched_at, when)
        elif path.startswith(f"espnpr/{season}/commentators/wk-") and path.endswith(".html"):
            label = path.rsplit("/", 1)[-1][len("wk-") : -len(".html")]
            if fetched_at >= espn.get(label, ("", ""))[0]:
                espn[label] = (fetched_at, when)

    schedule_text = _fmt(schedule_newest) if schedule_newest is not None else None
    stamps: dict[str, WeekendStamps] = {}
    for label in labels:
        espn_entry = espn.get(label)
        stamps[label] = {
            "schedule_updated_at": schedule_text,
            "crews_506_saved_at": s506[label][1] if label in s506 else None,
            "crews_espnpr_saved_at": espn_entry[1] if espn_entry else None,
            "espnpr_week": label if espn_entry else None,
        }
    return stamps


def build_schedule_inputs(
    paths: DataPaths,
    season: int,
    games: Sequence[CfbdGame],
    media_rows: Iterable[CfbdMedia],
    table: NetworkTable,
    primary_overrides: Mapping[int, str] | None = None,
) -> ScheduleInputs:
    """Gather the current season's ScheduleInputs from already-loaded sources."""
    season_games = tuple(g for g in games if g.season == season)
    refs = week_refs(season_games, season)
    game_labels = week_labels(season_games, season)
    networks, unmapped = schedule_networks(
        media_rows, season, table, counted=game_labels, primary_overrides=primary_overrides
    )
    labels = [str(ref["label"]) for ref in refs]
    return ScheduleInputs(
        season=season,
        games=season_games,
        weeks=tuple(refs),
        labels=game_labels,
        networks=networks,
        network_unmapped=unmapped,
        stamps=weekend_stamps(paths, season, labels),
    )
