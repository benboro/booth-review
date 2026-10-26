"""ESPN Press Room backup crews (04.19 D-13..D-15, carrying 04.5 D-07..D-14).

The 04.5 backup-crew rules, with the collector swapped for hand-save import
(`booth-review import espnpr`; nothing here fetches anything):

- Precedence is override, then 506, then the backup (04.5 D-11). A booth from
  a saved commentators page or weekly release fills a plotted main-feed
  telecast in the ESPN family (networks.csv family `disney`) only when 506
  listed no main crew for it and no crew override covers it. A partial 506
  crew still beats a full backup booth.
- The whole booth comes from one page, never merged person by person with
  another source (04.3 D-08). When two pages give a booth for one telecast,
  the later saved page wins (the manifest's `saved_at`, else the page's
  published time); differing booths are counted.
- A hand-confirmed override always wins (04.3 D-09), and a later 506 crew
  replaces a backup crew on its own, since this pass only fills telecasts
  506 left crew-less (04.5 D-12). Where 506 lists a crew and the backup page
  names another set of people, a vault review row is written and counted;
  the build never fails over it.
- The booth's network must be the telecast's: a booth whose network resolves
  to another of the game's networks is skipped and counted, never moved.
- Backup rows reach telecast_people with the 506 row shape (source
  `crew_backup`, feed main, crew_position, no 506 pointer). The page prints
  names without roles: the first is play-by-play, the rest take their
  people.csv role (default analyst). On a line of three or more names, the
  trailing names with no play-by-play or analyst role in people.csv are the
  sideline reporters by ESPN's order and are dropped (counted once per booth),
  down to two names. An unknown name becomes
  a provisional person, the same flow as 506 names (review_people_new).
- Credit uses the 04.3 D-11 fields: crew_source_label "ESPN Press Room" and
  crew_source_url the saved page's canonical URL, checked by
  crew_source_url_problem and host_matches("espnpr"). `crew_backup` marks the
  telecast so the 506 freshness stamp can leave it out (D-14).

Phase 18 (18-13 F7): in the current season the pass also fills an unplotted
telecast (an upcoming game 506 listed without a crew), and gives a booth to a
game with no telecast row yet when its CFBD network (the This weekend
schedule's) is the booth's. Those `scheduled_crews` ship only in
telecasts_scheduled; a later 506 listing turns the game into a telecast and the
precedence above takes over.

D-15: `backfill_gap_rows` lists the ESPN-family main-crew gaps left after the
overrides and this pass, for 2014-2025, by CFBD week with ESPN's week label,
so the user can look up and hand-save the weekly releases that cover them.

Review rows go to the vault's interim/ folder through the caller; counts are
the only thing printed, and every error message is count-only.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Final

import polars as pl

from booth_review.build.crew_overrides import CREW_OVERRIDE_SOURCE
from booth_review.build.second_sources import match_row_to_game
from booth_review.config import DataPaths
from booth_review.contract.models import crew_source_url_problem
from booth_review.job.gaps506 import week_windows
from booth_review.job.gaps_espnpr import espn_week_label
from booth_review.people.normalize import fold_person, is_placeholder
from booth_review.people.registry import PeopleRegistry, Person, register_names
from booth_review.people.roles import Role
from booth_review.resolve.diagnose import UnmatchedRow, UnresolvedTeamRow
from booth_review.resolve.games import GameIndex
from booth_review.resolve.networks import NetworkTable, primary_network, split_outlets
from booth_review.resolve.overrides import GameOverride
from booth_review.resolve.teams import TeamResolver
from booth_review.sources.cfbd.parser import CfbdGame
from booth_review.sources.espnpr.importer import identify_page
from booth_review.sources.espnpr.parser import EspnPrBooth, EspnPrParseError, parse_booths
from booth_review.sources.second_rows import RejectedPage, host_matches
from booth_review.transport.cache import Manifest

CREW_BACKUP_LABEL = "ESPN Press Room"
# The telecast_people.source value for backup rows.
CREW_BACKUP_SOURCE = "crew_backup"
# networks.csv family of the ESPN networks (ABC, ESPN, ESPN2, ESPNU, SEC Network, ...).
ESPN_FAMILY = "disney"
# raw/espnpr/<season>/<folder>/*.html folders that carry booths (Plan 38 layout);
# ratings/ is viewership, read by build.second_sources.
BOOTH_FOLDERS = ("commentators", "releases")
_SOURCE: Final = "espnpr"
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_BOOTH_ROLES: frozenset[str] = frozenset({"pbp", "analyst"})
_SIDELINE_MIN_NAMES = 3

# D-15: the past seasons whose gaps the user backfills from weekly releases.
# 2026 on is the current-week commentators page (D-14, the job's hand-save list).
BACKFILL_SEASONS = range(2014, 2026)

REVIEW_CREW_BACKUP_DISAGREEMENTS = "review_crew_backup_disagreements"
REVIEW_CREW_BACKUP_DISAGREEMENT_COLUMNS = (
    "telecast_id",
    "cfbd_game_id",
    "network_id",
    "season",
    "date_et",
    "pointer",
    "source_url",
    "s506_person_ids",
    "backup_names",
    "backup_person_ids",
)
ESPNPR_BACKFILL_GAPS = "espnpr_backfill_gaps"
ESPNPR_BACKFILL_GAP_COLUMNS = (
    "season",
    "cfbd_week",
    "espn_week_label",
    "telecasts",
    "first_date",
    "last_date",
    "networks",
)

_COUNT_KEYS: tuple[str, ...] = (
    "booths",
    "matched",
    "unmatched",
    "unresolved_team",
    "ambiguous",
    "no_game",
    "excluded_override",
    "unmapped_network",
    "network_mismatch",
    "no_telecast",
    "not_plotted",
    "not_espn_family",
    "page_conflicts",
    "no_names",
    "bad_url",
    "filled",
    "scheduled_filled",
    "kept_override",
    "kept_506",
    "agreements",
    "disagreements",
    "sideline_dropped",
    "rows",
    "provisional_persons",
)


@dataclass(frozen=True)
class SavedBooth:
    """One parsed booth and when its page was saved (UTC `%Y-%m-%dT%H:%M:%SZ`;
    the manifest's `saved_at`, else the page's published time, else empty)."""

    booth: EspnPrBooth
    saved_at: str


@dataclass(frozen=True)
class LoadedBooths:
    """Every booth the saved pages give, plus the pages skipped as unreadable
    (no canonical URL, or the parser refuses them)."""

    booths: list[SavedBooth]
    rejected: tuple[RejectedPage, ...] = ()
    # Schedule rows that gave no TV booth (radio crews included), the radio
    # crews among them, and readable pages that gave no booth at all (a
    # template change shows up here instead of as a silent "filled 0").
    rows_skipped: int = 0
    radio_dropped: int = 0
    pages_without_booths: int = 0

    def counts(self) -> dict[str, int]:
        return {
            "rejected_pages": len(self.rejected),
            "rows_skipped": self.rows_skipped,
            "radio_dropped": self.radio_dropped,
            "pages_without_booths": self.pages_without_booths,
        }


@dataclass(frozen=True)
class ScheduledCrew:
    """One scheduled game's backup booth: (person_id, role) in booth order and its page."""

    entries: tuple[tuple[str, Role], ...]
    source_url: str


@dataclass(frozen=True)
class CrewBackupResult:
    telecasts: pl.DataFrame
    telecast_people: pl.DataFrame
    people: pl.DataFrame
    season_counts: dict[int, dict[str, int]]
    statuses: dict[str, str]  # telecast_id -> filled | override | agrees | differs
    review_rows: list[dict[str, object]]  # review_crew_backup_disagreements
    new_name_rows: list[dict[str, object]]  # merged into review_people_new
    counts: dict[str, int]
    unmatched_rows: list[UnmatchedRow] = field(default_factory=list)
    unresolved_rows: list[UnresolvedTeamRow] = field(default_factory=list)
    # CFBD game id -> backup booth, for current-season games with no telecast (18-13 F7).
    scheduled_crews: dict[int, ScheduledCrew] = field(default_factory=dict)

    @property
    def filled_ids(self) -> frozenset[str]:
        return frozenset(tid for tid, status in self.statuses.items() if status == "filled")


# -- Loading ---------------------------------------------------------------------------------


def _season_folder(name: str) -> int | None:
    return int(name) if name.isascii() and name.isdecimal() else None


def load_espnpr_booths(paths: DataPaths, seasons: Sequence[int] | None = None) -> LoadedBooths:
    """Every booth in the vault's saved commentators pages and weekly releases
    (raw/espnpr/<season>/{commentators,releases}/*.html), any season.

    The source URL is the manifest's `url` (the canonical link the importer
    recorded), else the page's own canonical link. A page with neither, or one
    the parser refuses, is skipped and returned in `rejected` (vault path and
    reason), like the viewership loader, so one bad page never stops the build.
    """
    root = paths.raw / _SOURCE
    if not root.is_dir():
        return LoadedBooths(booths=[])
    pages: list[tuple[int, str]] = []  # (season, vault path under raw/)
    for folder in sorted(root.iterdir()):
        season = _season_folder(folder.name)
        if season is None or (seasons is not None and season not in seasons):
            continue
        for sub in BOOTH_FOLDERS:
            directory = folder / sub
            if directory.is_dir():
                pages.extend(
                    (season, f"{_SOURCE}/{season}/{sub}/{page.name}")
                    for page in sorted(directory.glob("*.html"))
                )
    if not pages:
        return LoadedBooths(booths=[])

    # The newest manifest line per path (a --force re-save appends a new one).
    latest: dict[str, dict[str, Any]] = {}
    for entry in Manifest(paths.manifest).entries():
        path = entry.get("path")
        if entry.get("source") == _SOURCE and isinstance(path, str):
            latest[path] = entry

    saved: list[SavedBooth] = []
    rejected: list[RejectedPage] = []
    rows_skipped = radio_dropped = pages_without_booths = 0
    for season, rel in pages:
        html = (paths.raw / rel).read_text(encoding="utf-8", errors="replace")
        entry = latest.get(rel, {})
        page = identify_page(html)
        url = entry.get("url")
        if not isinstance(url, str):
            url = page.canonical_url if page is not None else None
        if url is None:
            rejected.append(RejectedPage(_SOURCE, season, rel, "no_canonical_url"))
            continue
        try:
            parsed = parse_booths(html, url=url, season=season)
        except EspnPrParseError:
            rejected.append(RejectedPage(_SOURCE, season, rel, "parse_error"))
            continue
        rows_skipped += parsed.skipped
        radio_dropped += parsed.radio_dropped
        pages_without_booths += int(not parsed.booths)
        stamp = entry.get("saved_at")
        if not isinstance(stamp, str):
            published = page.published if page is not None else None
            stamp = published.astimezone(UTC).strftime(_TIME_FORMAT) if published else ""
        saved.extend(SavedBooth(booth=booth, saved_at=stamp) for booth in parsed.booths)
    return LoadedBooths(
        booths=saved,
        rejected=tuple(rejected),
        rows_skipped=rows_skipped,
        radio_dropped=radio_dropped,
        pages_without_booths=pages_without_booths,
    )


# -- People ----------------------------------------------------------------------------------


def _working_registry(registry: PeopleRegistry, people: pl.DataFrame) -> PeopleRegistry:
    """people.csv plus every person the 506 pass already added (provisional
    persons included), so a backup name reuses the same person_id."""
    persons: dict[str, Person] = dict(registry.persons)
    for row in people.iter_rows(named=True):
        person_id = row["person_id"]
        if person_id in persons:
            continue
        role: Role = "pbp" if row["usual_role"] == "pbp" else "unknown"
        if row["usual_role"] == "analyst":
            role = "analyst"
        persons[person_id] = Person(
            person_id=person_id,
            canonical_name=row["canonical_name"],
            variants=tuple(row["variants"] or (row["canonical_name"],)),
            usual_role=role,
            role_override=None,
        )
    return PeopleRegistry(persons)


def _booth_role(name: str, registry: PeopleRegistry) -> Role | None:
    """The name's people.csv booth role (role_override, else usual_role) when
    it is pbp or analyst, else None (unregistered, unknown or sideline)."""
    person_id = registry.lookup(name)
    if person_id is None:
        return None
    person = registry.persons[person_id]
    role = person.role_override or person.usual_role
    return role if role in _BOOTH_ROLES else None


def _booth_names(names: Sequence[str], registry: PeopleRegistry) -> tuple[tuple[str, ...], bool]:
    """(booth names, sideline dropped): placeholders removed, then on a line of
    three or more names every trailing name with no booth role in people.csv
    dropped (primetime lines can print two sideline names), keeping at least
    two names."""
    kept = tuple(name for name in names if not is_placeholder(name))
    dropped = False
    while len(kept) >= _SIDELINE_MIN_NAMES and _booth_role(kept[-1], registry) is None:
        kept, dropped = kept[:-1], True
    return kept, dropped


def _roles(names: Sequence[str], registry: PeopleRegistry) -> list[Role]:
    """First name pbp; the rest their people.csv booth role, default analyst."""
    return [
        "pbp" if position == 0 else (_booth_role(name, registry) or "analyst")
        for position, name in enumerate(names)
    ]


# -- The pass --------------------------------------------------------------------------------


def _settle(candidates: Sequence[SavedBooth]) -> tuple[SavedBooth, bool]:
    """(winner, conflict): the later saved page wins; ties break on pointer.
    `conflict` is True when another page names a different set of people."""
    winner = max(candidates, key=lambda c: (c.saved_at, c.booth.pointer))
    folded = {fold_person(n) for n in winner.booth.tv_names}
    conflict = any({fold_person(n) for n in c.booth.tv_names} != folded for c in candidates)
    return winner, conflict


def _unmatched(booth: EspnPrBooth, confidence: str, reason: str) -> UnmatchedRow:
    return UnmatchedRow(
        source=_SOURCE,
        season=booth.season,
        pointer=booth.pointer,
        date_et=booth.date_et.isoformat(),
        away_raw=booth.away_raw,
        home_raw=booth.home_raw,
        network_raw=booth.network_raw,
        confidence=confidence,
        reason=reason,
    )


def _family(network_id: str | None, networks: NetworkTable) -> str | None:
    if network_id is None:
        return None
    row = networks.networks().get(network_id)
    return row[1] if row is not None else None


def apply_crew_backup(
    telecasts: pl.DataFrame,
    telecast_people: pl.DataFrame,
    people: pl.DataFrame,
    booths: Sequence[SavedBooth],
    *,
    resolver: TeamResolver,
    index: GameIndex,
    overrides: Mapping[tuple[str, int, str], GameOverride],
    networks: NetworkTable,
    registry: PeopleRegistry,
    season_counts: Mapping[int, Mapping[str, int]],
    current_season: int | None = None,
    scheduled_networks: Mapping[int, str | None] | None = None,
) -> CrewBackupResult:
    """Fill ESPN-family telecasts 506 and the overrides left crew-less with a
    saved ESPN Press Room booth (see module docstring). Run after
    apply_crew_overrides. `registry` is people.csv (roles); `people` is the
    people table the 506 pass built (it holds 506's provisional persons).
    `current_season` lets unplotted telecasts of that season be filled, and
    `scheduled_networks` (CFBD game id -> the schedule's network) names the
    games with no telecast that may take a booth (18-13 F7).
    Inputs are not mutated; failures are count-only.
    """
    counts: dict[str, int] = dict.fromkeys(_COUNT_KEYS, 0)
    new_counts = {season: dict(values) for season, values in season_counts.items()}
    if not booths:
        return CrewBackupResult(telecasts, telecast_people, people, new_counts, {}, [], [], counts)

    mains_by_game: dict[int, list[tuple[str, str | None]]] = {}
    info: dict[str, dict[str, Any]] = {}
    for row in telecasts.filter(pl.col("feed_type") == "main").iter_rows(named=True):
        mains_by_game.setdefault(row["game_id"], []).append((row["telecast_id"], row["network_id"]))
        info[row["telecast_id"]] = row
    override_ids = set(
        telecasts.filter(pl.col("crew_patched").fill_null(False))["telecast_id"].to_list()
    ) | set(
        telecast_people.filter(
            (pl.col("feed_type") == "main") & (pl.col("source") == CREW_OVERRIDE_SOURCE)
        )["telecast_id"].to_list()
    )
    existing_main: dict[str, set[str]] = {}
    for row in telecast_people.filter(pl.col("feed_type") == "main").iter_rows(named=True):
        existing_main.setdefault(row["telecast_id"], set()).add(row["person_id"])

    unmatched_rows: list[UnmatchedRow] = []
    unresolved: dict[str, list[int]] = {}
    targets: dict[str, list[SavedBooth]] = {}
    scheduled_targets: dict[int, list[SavedBooth]] = {}
    for saved in booths:
        booth = saved.booth
        counts["booths"] += 1
        game, reason = match_row_to_game(
            _SOURCE,
            booth.season,
            booth.date_et,
            booth.away_raw,
            booth.home_raw,
            resolver=resolver,
            index=index,
            overrides=overrides,
            pointer=booth.pointer,
        )
        if game is None:
            if reason == "excluded_override":
                counts["excluded_override"] += 1
                continue
            counts["unmatched"] += 1
            counts["no_game" if reason == "none" else reason] += 1
            if reason == "unresolved_team":
                for raw in (booth.away_raw, booth.home_raw):
                    if not resolver.resolve_candidates(_SOURCE, raw, booth.season):
                        unresolved.setdefault(raw, []).append(booth.season)
                unmatched_rows.append(_unmatched(booth, "", reason))
            else:
                unmatched_rows.append(_unmatched(booth, reason, reason))
            continue
        counts["matched"] += 1
        chart = primary_network(split_outlets(booth.network_raw), booth.season, networks)
        if chart.network_id is None:
            counts["unmapped_network"] += 1
            unmatched_rows.append(_unmatched(booth, "", "unmapped_network"))
            continue
        game_mains = mains_by_game.get(game.id, [])
        if not game_mains:
            if (
                scheduled_networks is None
                or game.season != current_season
                or game.id not in scheduled_networks
            ):
                counts["no_telecast"] += 1
                continue
            if scheduled_networks[game.id] != chart.network_id:
                counts["network_mismatch"] += 1
                unmatched_rows.append(_unmatched(booth, "", "network_mismatch"))
                continue
            if _family(chart.network_id, networks) != ESPN_FAMILY:
                counts["not_espn_family"] += 1
                continue
            scheduled_targets.setdefault(game.id, []).append(saved)
            continue
        target = next((tid for tid, nid in game_mains if nid == chart.network_id), None)
        if target is None:
            counts["network_mismatch"] += 1
            unmatched_rows.append(_unmatched(booth, "", "network_mismatch"))
            continue
        if not info[target]["plotted"] and info[target]["season"] != current_season:
            counts["not_plotted"] += 1
            continue
        if _family(info[target]["network_id"], networks) != ESPN_FAMILY:
            counts["not_espn_family"] += 1
            continue
        targets.setdefault(target, []).append(saved)

    working = _working_registry(registry, people)
    statuses: dict[str, str] = {}
    review_rows: list[dict[str, object]] = []
    fills: dict[str, tuple[tuple[str, ...], SavedBooth]] = {}
    for telecast_id in sorted(targets):
        winner, conflict = _settle(targets[telecast_id])
        counts["page_conflicts"] += int(conflict)
        tel = info[telecast_id]
        if telecast_id in override_ids:
            statuses[telecast_id] = "override"
            counts["kept_override"] += 1
            continue
        names, dropped = _booth_names(winner.booth.tv_names, registry)
        if not names:
            counts["no_names"] += 1
            continue
        if tel["crew_matched"]:
            counts["kept_506"] += 1
            backup_ids = [working.lookup(name) for name in names]
            current = existing_main.get(telecast_id, set())
            if None not in backup_ids and set(backup_ids) == current:
                statuses[telecast_id] = "agrees"
                counts["agreements"] += 1
                continue
            statuses[telecast_id] = "differs"
            counts["disagreements"] += 1
            review_rows.append(
                {
                    "telecast_id": telecast_id,
                    "cfbd_game_id": tel["game_id"],
                    "network_id": tel["network_id"],
                    "season": tel["season"],
                    "date_et": tel["date_et"],
                    "pointer": winner.booth.pointer,
                    "source_url": winner.booth.source_url,
                    "s506_person_ids": "|".join(sorted(current)),
                    "backup_names": "|".join(names),
                    "backup_person_ids": "|".join(pid or "" for pid in backup_ids),
                }
            )
            continue
        url = winner.booth.source_url
        if crew_source_url_problem(url) is not None or not host_matches(_SOURCE, url):
            counts["bad_url"] += 1
            continue
        counts["sideline_dropped"] += int(dropped)
        fills[telecast_id] = (names, winner)

    scheduled_fills: dict[int, tuple[tuple[str, ...], SavedBooth]] = {}
    for game_id in sorted(scheduled_targets):
        winner, conflict = _settle(scheduled_targets[game_id])
        counts["page_conflicts"] += int(conflict)
        names, dropped = _booth_names(winner.booth.tv_names, registry)
        if not names:
            counts["no_names"] += 1
            continue
        url = winner.booth.source_url
        if crew_source_url_problem(url) is not None or not host_matches(_SOURCE, url):
            counts["bad_url"] += 1
            continue
        counts["sideline_dropped"] += int(dropped)
        scheduled_fills[game_id] = (names, winner)

    # Unknown names in the filled booths become provisional persons (Phase 3
    # D-01/D-02), the same fold-grouped flow 506 names take.
    name_counts: Counter[str] = Counter()
    name_seasons: dict[str, tuple[int, int]] = {}
    filled_names = [(int(info[tid]["season"]), names) for tid, (names, _) in fills.items()]
    filled_names += [(w.booth.season, names) for names, w in scheduled_fills.values()]
    for season, names in filled_names:
        for name in names:
            if working.lookup(name) is None:
                name_counts[name] += 1
                lo, hi = name_seasons.get(name, (season, season))
                name_seasons[name] = (min(lo, season), max(hi, season))
    ids_before = set(working.persons)
    if name_counts:
        working = register_names(working, dict(name_counts))
    new_ids = sorted(set(working.persons) - ids_before)

    def _booth_people(names: Sequence[str]) -> list[tuple[str, Role]]:
        person_ids: list[str] = []
        kept_names: list[str] = []
        for name in names:
            person_id = working.lookup(name)
            if person_id is None or person_id in person_ids:  # pragma: no cover - defensive
                continue
            person_ids.append(person_id)
            kept_names.append(name)
        return list(zip(person_ids, _roles(kept_names, registry), strict=True))

    new_rows: list[dict[str, object]] = []
    for telecast_id, (names, _winner) in sorted(fills.items()):
        for position, (person_id, role) in enumerate(_booth_people(names)):
            new_rows.append(
                {
                    "telecast_id": telecast_id,
                    "person_id": person_id,
                    "role": role,
                    "feed_type": "main",
                    "crew_position": position,
                    "s506_pointer": None,
                    "source": CREW_BACKUP_SOURCE,
                }
            )
        statuses[telecast_id] = "filled"
        tel = info[telecast_id]
        if tel["rated"]:
            bucket = new_counts.setdefault(int(tel["season"]), {})
            bucket["rated_with_crew"] = bucket.get("rated_with_crew", 0) + 1
            bucket["records_with_crew"] = bucket.get("records_with_crew", 0) + len(
                tel["rr_telecast_ids"] or []
            )

    scheduled_crews: dict[int, ScheduledCrew] = {}
    for game_id, (names, winner) in sorted(scheduled_fills.items()):
        entries = tuple(_booth_people(names))
        if entries:
            scheduled_crews[game_id] = ScheduledCrew(entries, winner.booth.source_url)
    counts["scheduled_filled"] = len(scheduled_crews)

    filled = sorted(fills)
    counts["filled"] = len(filled)
    counts["rows"] = len(new_rows)
    counts["provisional_persons"] = len(new_ids)

    # 506 listed no main crew for a filled telecast; any main rows it has
    # (none expected) give way to the one-page booth (04.3 D-08).
    kept = telecast_people.filter(
        ~(pl.col("telecast_id").is_in(filled) & (pl.col("feed_type") == "main"))
    )
    people_out_tp = pl.concat([kept, pl.DataFrame(new_rows, schema=telecast_people.schema)])
    if people_out_tp.height:
        people_out_tp = people_out_tp.sort(["telecast_id", "person_id", "feed_type"])

    url_by_id = {tid: winner.booth.source_url for tid, (_, winner) in fills.items()}
    is_filled = pl.col("telecast_id").is_in(filled)
    telecasts_out = telecasts.with_columns(
        pl.when(is_filled).then(True).otherwise(pl.col("crew_matched")).alias("crew_matched"),
        pl.when(is_filled)
        .then(True)
        .otherwise(pl.col("crew_backup").fill_null(False))
        .alias("crew_backup"),
        pl.when(is_filled)
        .then(pl.col("telecast_id").replace_strict(url_by_id, default=None, return_dtype=pl.Utf8))
        .otherwise(pl.col("crew_source_url"))
        .alias("crew_source_url"),
        pl.when(is_filled)
        .then(pl.lit(CREW_BACKUP_LABEL, dtype=pl.Utf8))
        .otherwise(pl.col("crew_source_label"))
        .alias("crew_source_label"),
    )

    new_name_rows: list[dict[str, object]] = []
    people_rows: list[dict[str, object]] = []
    for person_id in new_ids:
        person = working.persons[person_id]
        seasons = [name_seasons[v] for v in person.variants if v in name_seasons]
        new_name_rows.append(
            {
                "name": person.canonical_name,
                "occurrences": sum(name_counts[v] for v in person.variants if v in name_counts),
                "season_first": min(lo for lo, _ in seasons) if seasons else None,
                "season_last": max(hi for _, hi in seasons) if seasons else None,
                "provisional_id": person_id,
            }
        )
        people_rows.append(
            {
                "person_id": person_id,
                "canonical_name": person.canonical_name,
                "variants": sorted(person.variants),
                "usual_role": person.usual_role,
                "registered": False,
            }
        )
    people_out = people
    if people_rows:
        people_out = pl.concat([people, pl.DataFrame(people_rows, schema=people.schema)]).sort(
            "person_id"
        )

    unresolved_rows = [
        UnresolvedTeamRow(
            source=_SOURCE,
            season_first=min(seasons),
            season_last=max(seasons),
            raw_name=raw,
            occurrences=len(seasons),
            suggested_canonical="",
            suggested_cfbd_team_id="",
        )
        for raw, seasons in sorted(unresolved.items())
    ]
    review_rows.sort(key=lambda r: (r["season"], str(r["date_et"]), str(r["telecast_id"])))
    return CrewBackupResult(
        telecasts=telecasts_out,
        telecast_people=people_out_tp,
        people=people_out,
        season_counts=new_counts,
        statuses=statuses,
        review_rows=review_rows,
        new_name_rows=sorted(new_name_rows, key=lambda r: str(r["name"])),
        counts=counts,
        unmatched_rows=unmatched_rows,
        unresolved_rows=unresolved_rows,
        scheduled_crews=scheduled_crews,
    )


# -- D-15 gap list ---------------------------------------------------------------------------


def backfill_gap_rows(
    gap_rows: Sequence[Mapping[str, object]],
    games: Sequence[CfbdGame],
    networks: NetworkTable,
) -> list[dict[str, object]]:
    """The ESPN-family main-crew gaps still `missing` after the overrides and
    the backup pass (crew_gap_rows output), for BACKFILL_SEASONS, one row per
    (season, CFBD week, ESPN week label) with its telecast count, date range
    and networks (D-15). ESPN's labels are 506's: CFBD regular week 1 holds
    ESPN Week 0 and Week 1, split by date; week N >= 2 is ESPN Week N; the
    postseason is "bowls". Vault-only (interim/); never logged or published.
    """
    by_id = {game.id: game for game in games}
    windows: dict[int, dict[str, tuple[datetime, datetime]]] = {}
    # (season, postseason flag, CFBD week, ESPN label) -> [(date, network_id)]
    groups: dict[tuple[int, int, int, str], list[tuple[date, str]]] = {}
    for row in gap_rows:
        if row["override_status"] != "missing":
            continue
        season = row["season"]
        network_id = row["network_id"]
        if not isinstance(season, int) or season not in BACKFILL_SEASONS:
            continue
        if not isinstance(network_id, str) or _family(network_id, networks) != ESPN_FAMILY:
            continue
        game = by_id.get(int(str(row["cfbd_game_id"])))
        day = row["date_et"]
        if game is None or not isinstance(day, date):
            continue
        if game.season_type == "postseason":
            key = (season, 1, game.week, "bowls")
        elif game.season_type == "regular":
            if season not in windows:
                windows[season] = week_windows(games, season)
            key = (season, 0, game.week, f"Week {espn_week_label(game, windows[season])}")
        else:
            continue
        groups.setdefault(key, []).append((day, network_id))

    # The postseason is one row per season, whatever CFBD week its games carry.
    merged: dict[tuple[int, int, int, str], list[tuple[date, str]]] = {}
    for (season, post, week, label), items in groups.items():
        merged.setdefault((season, post, 0 if post else week, label), []).extend(items)

    out: list[dict[str, object]] = []
    for (season, post, week, label), items in sorted(merged.items()):
        days = [day for day, _ in items]
        out.append(
            {
                "season": season,
                "cfbd_week": "postseason" if post else week,
                "espn_week_label": label,
                "telecasts": len(items),
                "first_date": min(days),
                "last_date": max(days),
                "networks": "|".join(sorted({nid for _, nid in items})),
            }
        )
    return out
