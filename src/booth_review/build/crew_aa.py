"""Awful Announcing crews as a second crew source (Phase 27, AAC-03).

AA's weekly college football announcing-schedule post (cached by
`booth-review collect aa --crews`) gives whole role-tagged booths. This pass
coalesces them with 506's crews:

- A hand-confirmed override always wins (04.3 D-09), untouched, whatever its
  status (a `redundant` override leaves no marker on the frame, so the caller
  passes every override's telecast id).
- A main telecast 506 listed no crew for (plotted, unrated or not yet plotted)
  takes AA's whole booth, credited "Awful Announcing" with the post's canonical
  URL. `crew_aa` marks it; `crew_patched` is never set, so the 506 match-rate
  separation holds.
- A 506 crew with the same people is kept and counted as an agreement. So is
  one that lists every AA person plus others (AA's parse drops reporters 506
  may list): a subset is no evidence against 506.
- D-04: when AA's booth is a strict superset of 506's people, AA's whole booth
  wins whatever the page times say, and a review row is written.
- D-02: otherwise the newer page wins, AA's `article:modified_time` (else the
  fetched_at of the last HTTP 200 manifest line) against 506's saved_at (else
  fetched_at). A tie or a missing 506 time keeps 506. A review row is written.
- Booths stay whole (04.3 D-08): a telecast's main rows come from one page.
- D-03: only 2026 is read. Names unknown to people.csv become provisional persons.

Page content is private vault data: every error and count is count-only, review
rows go to the vault's interim/ folder through the caller, and tests use
invented names.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

import polars as pl

from booth_review.build.crew_backup import ScheduledCrew
from booth_review.build.crew_overrides import CREW_OVERRIDE_SOURCE
from booth_review.build.crew_people import register_provisional, working_registry
from booth_review.build.second_sources import match_row_to_game
from booth_review.config import DataPaths
from booth_review.contract.models import crew_source_url_problem
from booth_review.job.gaps506 import _entry_time
from booth_review.people.normalize import fold_person
from booth_review.people.registry import PeopleRegistry
from booth_review.people.roles import Role
from booth_review.resolve.diagnose import UnmatchedRow, UnresolvedTeamRow
from booth_review.resolve.games import GameIndex
from booth_review.resolve.networks import NetworkTable, primary_network, split_outlets
from booth_review.resolve.overrides import GameOverride
from booth_review.resolve.teams import TeamResolver
from booth_review.sources.aa.crews import (
    CREWS_SEASON,
    AaBooth,
    AaCrewsParseError,
    ParsedCrews,
    parse_crews,
)
from booth_review.sources.aa.index import on_host
from booth_review.sources.aa.parser import post_url_from_html
from booth_review.sources.second_rows import RejectedPage, host_matches
from booth_review.transport.cache import Manifest

CREW_AA_LABEL = "Awful Announcing"
# The telecast_people.source value for AA rows.
CREW_AA_SOURCE = "crew_aa"
REVIEW_CREW_AA_DISAGREEMENTS = "review_crew_aa_disagreements"
REVIEW_CREW_AA_DISAGREEMENT_COLUMNS = (
    "telecast_id",
    "cfbd_game_id",
    "network_id",
    "season",
    "date_et",
    "pointer",
    "source_url",
    "s506_person_ids",
    "aa_names",
    "aa_person_ids",
    "winner",
    "relation",
    "aa_time",
    "s506_time",
    "aa_time_source",
)
_SOURCE: Final = "aa"
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

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
    "page_conflicts",
    "bad_url",
    "filled",
    "scheduled_filled",
    "kept_override",
    "agreements",
    "disagreements",
    "superset",
    "aa_won",
    "s506_won",
    "unparsed_lines",
    "tbd",
    "no_pbp",
    "undated_pages",
    "rejected_pages",
    "rows",
    "provisional_persons",
)


@dataclass(frozen=True)
class AaPage:
    """One cached crews post: its parse and the time the pass compares (D-02)."""

    path: str
    parsed: ParsedCrews
    aa_time: datetime | None
    aa_time_source: str  # modified | fetched | none


@dataclass(frozen=True)
class LoadedAaPages:
    pages: list[AaPage]
    rejected: list[RejectedPage] = field(default_factory=list)


@dataclass(frozen=True)
class CrewAaResult:
    telecasts: pl.DataFrame
    telecast_people: pl.DataFrame
    people: pl.DataFrame
    season_counts: dict[int, dict[str, int]]
    statuses: dict[str, str]  # filled | override | agrees | aa_won | superset | s506_won
    review_rows: list[dict[str, object]]
    new_name_rows: list[dict[str, object]]
    counts: dict[str, int]
    unmatched_rows: list[UnmatchedRow] = field(default_factory=list)
    unresolved_rows: list[UnresolvedTeamRow] = field(default_factory=list)
    scheduled_crews: dict[int, ScheduledCrew] = field(default_factory=dict)

    @property
    def filled_ids(self) -> frozenset[str]:
        return frozenset(tid for tid, status in self.statuses.items() if status == "filled")

    @property
    def won_ids(self) -> frozenset[str]:
        return frozenset(
            tid for tid, status in self.statuses.items() if status in ("aa_won", "superset")
        )


# -- Loading ---------------------------------------------------------------------------------


def _manifest_time(stamp: object) -> datetime | None:
    if not isinstance(stamp, str):
        return None
    try:
        return datetime.strptime(stamp, _TIME_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


def load_aa_pages(paths: DataPaths, seasons: Sequence[int] | None = None) -> LoadedAaPages:
    """Every cached crews post (raw/aa/crews/<season>/wk-*.html), 2026 only (D-03).

    The time compared against 506 is the post's `article:modified_time`, else the
    fetched_at of the page's latest HTTP 200 manifest line (a 304 line is not a
    fetch of new content). A page with no on-host canonical link, or one the
    parser refuses, is returned in `rejected`; it never stops the build.
    """
    wanted = [CREWS_SEASON] if seasons is None else [s for s in seasons if s == CREWS_SEASON]
    found: list[tuple[int, str]] = []
    for season in wanted:
        directory = paths.raw / _SOURCE / "crews" / str(season)
        if directory.is_dir():
            found.extend(
                (season, f"{_SOURCE}/crews/{season}/{page.name}")
                for page in sorted(directory.glob("wk-*.html"))
            )
    if not found:
        return LoadedAaPages(pages=[])

    fetched: dict[str, datetime] = {}
    for entry in Manifest(paths.manifest).entries():
        path = entry.get("path")
        if entry.get("source") != _SOURCE or not isinstance(path, str):
            continue
        if entry.get("status") != 200:
            continue
        moment = _manifest_time(entry.get("fetched_at"))
        if moment is not None:
            fetched[path] = moment

    pages: list[AaPage] = []
    rejected: list[RejectedPage] = []
    for season, rel in found:
        html = (paths.raw / rel).read_text(encoding="utf-8", errors="replace")
        canonical = post_url_from_html(html)
        if canonical is None:
            rejected.append(RejectedPage(_SOURCE, season, rel, "no_canonical_url"))
            continue
        if on_host(canonical) is None:
            rejected.append(RejectedPage(_SOURCE, season, rel, "off_host_url"))
            continue
        try:
            parsed = parse_crews(html, season=season)
        except AaCrewsParseError:
            rejected.append(RejectedPage(_SOURCE, season, rel, "parse_error"))
            continue
        if parsed.modified is not None:
            aa_time: datetime | None = parsed.modified.astimezone(UTC)
            source = "modified"
        elif rel in fetched:
            aa_time, source = fetched[rel], "fetched"
        else:
            aa_time, source = None, "none"
        pages.append(AaPage(path=rel, parsed=parsed, aa_time=aa_time, aa_time_source=source))
    return LoadedAaPages(pages=pages, rejected=rejected)


def load_506_times(paths: DataPaths) -> dict[tuple[int, str], datetime]:
    """(season, 506 week label) -> when that week page was saved (saved_at, else
    fetched_at of its latest manifest line), as aware UTC datetimes."""
    latest: dict[str, dict[str, Any]] = {}
    for entry in Manifest(paths.manifest).entries():
        path = entry.get("path")
        if entry.get("source") == "sports506" and isinstance(path, str):
            latest[path] = entry
    out: dict[tuple[int, str], datetime] = {}
    for path, entry in latest.items():
        parts = path.split("/")
        if len(parts) != 3 or parts[0] != "sports506":
            continue
        name = parts[2]
        if not (name.startswith("wk-") and name.endswith(".html")):
            continue
        label = name[3:-5]
        if label != "B":
            label = label.lstrip("0") or "0"
        moment = _manifest_time(_entry_time(entry))
        if parts[1].isdecimal() and moment is not None:
            out[(int(parts[1]), label)] = moment
    return out


# -- The pass --------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Cand:
    """One booth with the page it came from."""

    booth: AaBooth
    page: AaPage

    @property
    def key(self) -> tuple[str, str]:
        stamp = self.page.aa_time.strftime(_TIME_FORMAT) if self.page.aa_time else ""
        return (stamp, self.booth.pointer)


def _unmatched(booth: AaBooth, confidence: str, reason: str) -> UnmatchedRow:
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


def _settle(candidates: Sequence[_Cand]) -> tuple[_Cand, bool]:
    """(winner, conflict): the later page wins; ties break on pointer. `conflict`
    is True when another candidate names different people."""
    winner = max(candidates, key=lambda c: c.key)
    folded = {fold_person(n) for n, _ in winner.booth.people}
    conflict = any({fold_person(n) for n, _ in c.booth.people} != folded for c in candidates)
    return winner, conflict


def _stamp(moment: datetime | None) -> str:
    return moment.astimezone(UTC).strftime(_TIME_FORMAT) if moment is not None else ""


def _url_ok(url: str) -> bool:
    return crew_source_url_problem(url) is None and host_matches(_SOURCE, url)


def apply_crew_aa(
    telecasts: pl.DataFrame,
    telecast_people: pl.DataFrame,
    people: pl.DataFrame,
    pages: LoadedAaPages | Sequence[AaPage],
    *,
    resolver: TeamResolver,
    index: GameIndex,
    overrides: Mapping[tuple[str, int, str], GameOverride],
    networks: NetworkTable,
    registry: PeopleRegistry,
    season_counts: Mapping[int, Mapping[str, int]],
    s506_times: Mapping[tuple[int, str], datetime],
    current_season: int | None = None,
    scheduled_networks: Mapping[int, str | None] | None = None,
    override_telecast_ids: Collection[str] = frozenset(),
) -> CrewAaResult:
    """Coalesce 506 and Awful Announcing main crews (see module docstring).
    Run after apply_crew_overrides, passing every telecast id it gave a status
    (including `redundant`) as `override_telecast_ids`. Inputs are not mutated;
    failures are count-only.
    """
    counts: dict[str, int] = dict.fromkeys(_COUNT_KEYS, 0)
    new_counts = {season: dict(values) for season, values in season_counts.items()}
    if isinstance(pages, LoadedAaPages):
        page_list = list(pages.pages)
        counts["rejected_pages"] = len(pages.rejected)
    else:
        page_list = list(pages)
    counts["unparsed_lines"] = sum(p.parsed.unparsed for p in page_list)
    counts["tbd"] = sum(p.parsed.tbd for p in page_list)
    counts["no_pbp"] = sum(p.parsed.no_pbp for p in page_list)
    counts["undated_pages"] = sum(p.aa_time_source != "modified" for p in page_list)
    if not page_list:
        return CrewAaResult(telecasts, telecast_people, people, new_counts, {}, [], [], counts)

    mains_by_game: dict[int, list[tuple[str, str | None]]] = {}
    info: dict[str, dict[str, Any]] = {}
    for row in telecasts.filter(pl.col("feed_type") == "main").iter_rows(named=True):
        mains_by_game.setdefault(row["game_id"], []).append((row["telecast_id"], row["network_id"]))
        info[row["telecast_id"]] = row
    override_ids = (
        set(override_telecast_ids)
        | set(telecasts.filter(pl.col("crew_patched").fill_null(False))["telecast_id"].to_list())
        | set(
            telecast_people.filter(
                (pl.col("feed_type") == "main") & (pl.col("source") == CREW_OVERRIDE_SOURCE)
            )["telecast_id"].to_list()
        )
    )
    existing_main: dict[str, set[str]] = {}
    for row in telecast_people.filter(pl.col("feed_type") == "main").iter_rows(named=True):
        existing_main.setdefault(row["telecast_id"], set()).add(row["person_id"])

    unmatched_rows: list[UnmatchedRow] = []
    unresolved: dict[str, list[int]] = {}
    targets: dict[str, list[_Cand]] = {}
    scheduled_targets: dict[int, list[_Cand]] = {}
    for page in page_list:
        for booth in page.parsed.booths:
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
            cand = _Cand(booth, page)
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
                scheduled_targets.setdefault(game.id, []).append(cand)
                continue
            target = next((tid for tid, nid in game_mains if nid == chart.network_id), None)
            if target is None:
                counts["network_mismatch"] += 1
                unmatched_rows.append(_unmatched(booth, "", "network_mismatch"))
                continue
            targets.setdefault(target, []).append(cand)

    working = working_registry(registry, people)
    statuses: dict[str, str] = {}
    review_rows: list[dict[str, object]] = []
    # telecast_id -> (names, role by name, winning candidate, is a fill of a crewless telecast)
    wins: dict[str, tuple[_Cand, bool]] = {}
    for telecast_id in sorted(targets):
        winner, conflict = _settle(targets[telecast_id])
        counts["page_conflicts"] += int(conflict)
        tel = info[telecast_id]
        if telecast_id in override_ids:
            statuses[telecast_id] = "override"
            counts["kept_override"] += 1
            continue
        names = [name for name, _ in winner.booth.people]
        aa_ids = [working.lookup(name) for name in names]
        known = {pid for pid in aa_ids if pid is not None}
        current = existing_main.get(telecast_id, set())
        if not tel["crew_matched"]:
            if not _url_ok(winner.booth.source_url):
                counts["bad_url"] += 1
                continue
            wins[telecast_id] = (winner, True)
            continue
        # Every AA person is in 506's crew (equal, or 506 also lists a reporter
        # AA's parse dropped): an agreement; 506's crew and credit stay.
        if None not in aa_ids and known and known <= current:
            statuses[telecast_id] = "agrees"
            counts["agreements"] += 1
            continue
        superset = bool(current) and current <= known and (None in aa_ids or known != current)
        aa_time = winner.page.aa_time
        s506_time = s506_times.get((int(tel["season"]), str(tel["s506_week"])))
        aa_newer = aa_time is not None and s506_time is not None and aa_time > s506_time
        aa_wins = superset or aa_newer
        if aa_wins and not _url_ok(winner.booth.source_url):
            counts["bad_url"] += 1
            continue
        if superset:
            status = "superset"
        elif aa_newer:
            status = "aa_won"
        else:
            status = "s506_won"
        statuses[telecast_id] = status
        counts["disagreements"] += 1
        counts[status] += 1
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
                "aa_names": "|".join(names),
                "aa_person_ids": "|".join(pid or "" for pid in aa_ids),
                "winner": "aa" if aa_wins else "506",
                "relation": "superset" if superset else "differs",
                "aa_time": _stamp(aa_time),
                "s506_time": _stamp(s506_time),
                "aa_time_source": winner.page.aa_time_source,
            }
        )
        if aa_wins:
            wins[telecast_id] = (winner, False)

    scheduled_wins: dict[int, _Cand] = {}
    for game_id in sorted(scheduled_targets):
        winner, conflict = _settle(scheduled_targets[game_id])
        counts["page_conflicts"] += int(conflict)
        if not _url_ok(winner.booth.source_url):
            counts["bad_url"] += 1
            continue
        scheduled_wins[game_id] = winner

    # Unknown names in the winning booths become provisional persons.
    name_counts: Counter[str] = Counter()
    name_seasons: dict[str, tuple[int, int]] = {}
    winning = [(int(info[tid]["season"]), cand) for tid, (cand, _) in wins.items()]
    winning += [(cand.booth.season, cand) for cand in scheduled_wins.values()]
    for season, cand in winning:
        for name, _role in cand.booth.people:
            if working.lookup(name) is None:
                name_counts[name] += 1
                lo, hi = name_seasons.get(name, (season, season))
                name_seasons[name] = (min(lo, season), max(hi, season))
    working, new_ids, new_name_rows, people_rows = register_provisional(
        working, name_counts, name_seasons
    )

    def _booth_people(cand: _Cand) -> list[tuple[str, Role]]:
        seen: list[str] = []
        out: list[tuple[str, Role]] = []
        for name, role in cand.booth.people:
            person_id = working.lookup(name)
            if person_id is None or person_id in seen:  # pragma: no cover - defensive
                continue
            seen.append(person_id)
            out.append((person_id, role))
        return out

    new_rows: list[dict[str, object]] = []
    for telecast_id, (cand, is_fill) in sorted(wins.items()):
        for position, (person_id, role) in enumerate(_booth_people(cand)):
            new_rows.append(
                {
                    "telecast_id": telecast_id,
                    "person_id": person_id,
                    "role": role,
                    "feed_type": "main",
                    "crew_position": position,
                    "s506_pointer": None,
                    "source": CREW_AA_SOURCE,
                }
            )
        tel = info[telecast_id]
        if is_fill:
            statuses[telecast_id] = "filled"
            if tel["rated"]:
                bucket = new_counts.setdefault(int(tel["season"]), {})
                bucket["rated_with_crew"] = bucket.get("rated_with_crew", 0) + 1
                bucket["records_with_crew"] = bucket.get("records_with_crew", 0) + len(
                    tel["rr_telecast_ids"] or []
                )

    scheduled_crews: dict[int, ScheduledCrew] = {}
    for game_id, cand in sorted(scheduled_wins.items()):
        entries = tuple(_booth_people(cand))
        if entries:
            scheduled_crews[game_id] = ScheduledCrew(
                entries, cand.booth.source_url, label=CREW_AA_LABEL
            )
    counts["scheduled_filled"] = len(scheduled_crews)

    won = sorted(wins)
    filled = sorted(tid for tid, (_, is_fill) in wins.items() if is_fill)
    counts["filled"] = len(filled)
    counts["rows"] = len(new_rows)
    counts["provisional_persons"] = len(new_ids)

    # An AA booth replaces every main row of the telecast it wins (04.3 D-08).
    kept = telecast_people.filter(
        ~(pl.col("telecast_id").is_in(won) & (pl.col("feed_type") == "main"))
    )
    people_out_tp = pl.concat([kept, pl.DataFrame(new_rows, schema=telecast_people.schema)])
    if people_out_tp.height:
        people_out_tp = people_out_tp.sort(["telecast_id", "person_id", "feed_type"])

    url_by_id = {tid: cand.booth.source_url for tid, (cand, _) in wins.items()}
    is_won = pl.col("telecast_id").is_in(won)
    is_filled = pl.col("telecast_id").is_in(filled)
    telecasts_out = telecasts.with_columns(
        pl.when(is_filled).then(True).otherwise(pl.col("crew_matched")).alias("crew_matched"),
        pl.when(is_won).then(True).otherwise(pl.col("crew_aa").fill_null(False)).alias("crew_aa"),
        pl.when(is_won)
        .then(pl.col("telecast_id").replace_strict(url_by_id, default=None, return_dtype=pl.Utf8))
        .otherwise(pl.col("crew_source_url"))
        .alias("crew_source_url"),
        pl.when(is_won)
        .then(pl.lit(CREW_AA_LABEL, dtype=pl.Utf8))
        .otherwise(pl.col("crew_source_label"))
        .alias("crew_source_label"),
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
    return CrewAaResult(
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
