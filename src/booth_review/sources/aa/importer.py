"""AaImporter: hand-saved Awful Announcing weekly announcing-schedule posts.

`booth-review import aa` brings the college football and NFL weekly schedule
posts the user saved in a browser into the vault, at the cache path the build
reads. It takes no HTTP client and builds none; the only AA requests are still
`booth-review collect aa`'s.

Pages are identified by content, never by file name:

- the canonical link must be an on-host AA post under ``/college-football/``
  (league ``cfb``) or ``/nfl/`` (league ``nfl``) whose slug or title says
  "announcing schedule";
- the week number comes from the title (else the slug) and the season from the
  4-digit year there (else the published date); only 2026 is imported, as for
  the scripted crews fetch;
- the post must parse with ``parse_crews``, and most of its dated game lines
  must fall in that week of the vault's schedule (CFBD for college football,
  nflverse for the NFL), so a mislabelled or wrong-season save is refused;
- for college football, a post the feed watch recorded for a different link
  that week is refused.

College football posts go to ``raw/aa/crews/<season>/wk-NN.html`` (the scripted
fetch's path, so the CFB build reads them as is) and NFL posts to
``raw/nfl/aa/crews/<season>/wk-NN.html``
(the NFL build reads only ``raw/nfl/``). The manifest line is marked
``origin: manual`` with the browser save time. A hand-saved copy has no ETag or
Last-Modified of its own: one that replaces a fetched copy keeps that copy's
validators, and the Tuesday job fetches its own copy of a college football week
over a hand import (``fetch_week_crews``), so the Friday and Saturday conditional
re-checks still work.

A vault copy that differs is kept unless --force, and is left alone without a
complaint when it is at least as new as the save (the job's fetch usually is).
Two different saves of one week are both rejected, unless --force keeps the
newest. Messages carry counts and reasons only, never page text.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Final, Literal
from urllib.parse import urlsplit

from booth_review.config import DataPaths
from booth_review.errors import ParseError
from booth_review.sources.aa.crews import (
    CREWS_SEASON,
    MANUAL_ORIGIN,
    AaCrewsParseError,
    ParsedCrews,
    crews_cache_path,
    parse_crews,
)
from booth_review.sources.aa.feed import load_feed_state, week_key
from booth_review.sources.aa.index import on_host
from booth_review.sources.aa.parser import post_url_from_html
from booth_review.transport.cache import FreezeGuard, Manifest, ManifestEntry, atomic_write_bytes

DEFAULT_INCOMING_DIR: Final = Path("data/incoming/aa")
SOURCE: Final = "aa"

League = Literal["cfb", "nfl"]
_LEAGUE_PATHS: Final[dict[str, League]] = {"college-football": "cfb", "nfl": "nfl"}

_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_HTML_SUFFIXES = frozenset({".htm", ".html"})
_WEEK_RE = re.compile(r"\bweek[\s-]+(\d{1,2})\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_CHALLENGE_MARKERS = ("just a moment", "cf-chl", "attention required", "access denied")
# Most of a post's dated game lines must fall in its titled week.
_WEEK_SHARE = 0.5
_WEEK_SPAN = timedelta(days=7)


def nfl_crews_cache_path(season: int, label: str) -> str:
    """Vault-relative cache path of an NFL week's crews post (week zero-padded)."""
    if not label.isdigit():
        raise ValueError("crews week label must be numeric")
    from booth_review.nfl.layout import nfl_aa_crews_path

    return nfl_aa_crews_path(season, int(label))


def cache_path_for(league: League, season: int, label: str) -> str:
    if league == "cfb":
        return crews_cache_path(season, label)
    return nfl_crews_cache_path(season, label)


# -- identification -------------------------------------------------------------------


@dataclass(frozen=True)
class AaPostPage:
    """One identified weekly schedule post."""

    league: League
    season: int
    week: str
    canonical_url: str
    modified: datetime | None
    parsed: ParsedCrews

    @property
    def cache_path(self) -> str:
        return cache_path_for(self.league, self.season, self.week)


ExamineStatus = Literal["page", "invalid", "unrecognized"]


@dataclass(frozen=True)
class Examined:
    status: ExamineStatus
    page: AaPostPage | None = None
    reason: str | None = None
    league: League | None = None


class _TitleScan(HTMLParser):
    """The first <title> text (inline SVG icons carry later <title> tags)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self._in_title = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title" and self.title is None:
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._in_title:
            self._in_title = False
            self.title = " ".join("".join(self._parts).split())

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._parts.append(data)


def _title(text: str) -> str:
    scan = _TitleScan()
    scan.feed(text)
    scan.close()
    return scan.title or ""


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t}


def _is_schedule_post(slug: str, title: str) -> bool:
    tokens = _tokens(slug) | _tokens(title)
    return "announcing" in tokens and bool(tokens & {"schedule", "schedules"})


def _week(title: str, slug: str) -> str | None:
    for text in (title, slug):
        match = _WEEK_RE.search(text)
        if match:
            return str(int(match.group(1)))
    return None


def _season(league: League, title: str, slug: str, published: datetime | None) -> int | None:
    for text in (title, slug):
        match = _YEAR_RE.search(text)
        if match:
            return int(match.group(1))
    if published is None:
        return None
    # Bowls and the CFP final run to January; NFL weeks 17-18 and the playoffs too.
    last_month = 5 if league == "cfb" else 2
    return published.year - 1 if published.month <= last_month else published.year


def examine(content: bytes) -> Examined:
    """Classify one saved file by its content alone (schedule checks come later)."""
    if not content.strip():
        return Examined("invalid", reason="empty file")
    text = content.decode("utf-8", errors="replace")
    lowered = text.lower()
    if any(marker in lowered for marker in _CHALLENGE_MARKERS):
        return Examined("invalid", reason="looks like a challenge or error page")
    if "<html" not in lowered and "<!doctype html" not in lowered:
        return Examined("invalid", reason="does not look like HTML")
    canonical = post_url_from_html(text)
    if canonical is None:
        return Examined("unrecognized")
    url = on_host(canonical)
    if url is None:
        return Examined("unrecognized")
    parts = [p for p in urlsplit(url).path.split("/") if p]
    league = _LEAGUE_PATHS.get(parts[0]) if len(parts) > 1 else None
    slug = parts[-1].removesuffix(".html") if parts else ""
    title = _title(text)
    if league is None or not _is_schedule_post(slug, title):
        return Examined("unrecognized")
    week = _week(title, slug)
    if week is None:
        return Examined("invalid", reason="post names no week number", league=league)
    # A season is needed before parsing (January and later dates roll to the next year).
    published = _published_hint(text)
    season = _season(league, title, slug, published)
    if season is None:
        return Examined("invalid", reason="post names no season", league=league)
    if season != CREWS_SEASON:
        reason = f"only the {CREWS_SEASON} season is imported"
        return Examined("invalid", reason=reason, league=league)
    try:
        parsed = parse_crews(text, season=season)
    except AaCrewsParseError:
        return Examined("invalid", reason="post does not parse as a crews schedule", league=league)
    page = AaPostPage(
        league=league,
        season=season,
        week=week,
        canonical_url=parsed.url,
        modified=parsed.modified,
        parsed=parsed,
    )
    return Examined("page", page=page, league=league)


_PUBLISHED_RE = re.compile(
    r'<meta[^>]+property="article:published_time"[^>]+content="([^"]+)"', re.IGNORECASE
)


def _published_hint(text: str) -> datetime | None:
    match = _PUBLISHED_RE.search(text)
    if match is None:
        return None
    try:
        moment = datetime.fromisoformat(match.group(1).strip())
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


# -- schedule checks ------------------------------------------------------------------


def _cfb_week_days(paths: DataPaths, season: int) -> dict[str, tuple[date, date]] | None:
    """Each numbered CFB week's Monday-to-Sunday ET span, from the vault's CFBD games."""
    from booth_review.job.gaps_espnpr import week_spans
    from booth_review.sources.cfbd.parser import parse_games

    games_path = paths.raw / "cfbd" / "games" / f"{season}.json"
    if not games_path.is_file():
        return None
    try:
        games = parse_games(games_path.read_bytes())
    except ParseError:
        return None
    return {
        label: (monday.date(), (monday + _WEEK_SPAN).date())
        for label, monday in week_spans(games, season).items()
    }


def _nfl_week_days(paths: DataPaths, season: int) -> dict[str, set[date]] | None:
    """Each NFL regular-season week's game dates, from the vault's nflverse schedule."""
    from booth_review.nfl.layout import NFLVERSE_SCHEDULES_PATH
    from booth_review.nfl.schedule import parse_upcoming

    schedule = paths.raw / NFLVERSE_SCHEDULES_PATH
    if not schedule.is_file():
        return None
    try:
        games, _unplaced = parse_upcoming(schedule.read_bytes(), seasons=[season])
    except ParseError:
        return None
    days: dict[str, set[date]] = {}
    for game in games:
        day = game.kickoff_et.date() if game.kickoff_et is not None else game.gameday
        if day is not None:
            days.setdefault(str(game.week), set()).add(day)
    return days


class _Schedules:
    """Lazily loaded week calendars, one per league and season."""

    def __init__(self, paths: DataPaths) -> None:
        self._paths = paths
        self._cfb: dict[int, dict[str, tuple[date, date]] | None] = {}
        self._nfl: dict[int, dict[str, set[date]] | None] = {}

    def problem(self, page: AaPostPage) -> str | None:
        """Why `page`'s game dates don't fit its titled week, or None when they do."""
        days = [t.date_et for t in page.parsed.times]
        if not days:
            return "post has no dated game lines"
        if page.league == "cfb":
            if page.season not in self._cfb:
                self._cfb[page.season] = _cfb_week_days(self._paths, page.season)
            spans = self._cfb[page.season]
            if spans is None:
                return "no CFBD schedule for the season in the vault"
            span = spans.get(page.week)
            inside = 0 if span is None else sum(span[0] <= d < span[1] for d in days)
        else:
            if page.season not in self._nfl:
                self._nfl[page.season] = _nfl_week_days(self._paths, page.season)
            weeks = self._nfl[page.season]
            if weeks is None:
                return "no nflverse schedule for the season in the vault"
            week_days = weeks.get(page.week, set())
            inside = sum(d in week_days for d in days)
        if inside <= len(days) * _WEEK_SHARE:
            return "game dates do not match the week in the title"
        return None


# -- import ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WeekRef:
    league: League
    season: int
    week: str

    @property
    def cache_path(self) -> str:
        return cache_path_for(self.league, self.season, self.week)


@dataclass(frozen=True)
class SkippedFile:
    reason: str
    league: League | None = None


@dataclass
class AaImportResult:
    """The outcome of one import run (counts only)."""

    imported: list[WeekRef] = field(default_factory=list)
    skipped_existing: list[WeekRef] = field(default_factory=list)
    vault_newer: list[WeekRef] = field(default_factory=list)
    """A different vault copy at least as new as the save (left alone, no complaint)."""
    changed_without_force: list[WeekRef] = field(default_factory=list)
    skipped_invalid: list[SkippedFile] = field(default_factory=list)
    superseded: int = 0
    unrecognized: int = 0
    problems: list[str] = field(default_factory=list)

    def groups(self) -> list[tuple[League, int]]:
        """Every (league, season) that has a counted week, sorted."""
        refs: Iterable[WeekRef] = (
            *self.imported,
            *self.skipped_existing,
            *self.vault_newer,
            *self.changed_without_force,
        )
        return sorted({(ref.league, ref.season) for ref in refs})

    def counts(self, league: League, season: int) -> dict[str, int]:
        """Counts for vault.batch_message, count-only."""

        def n(refs: list[WeekRef]) -> int:
            return sum(ref.league == league and ref.season == season for ref in refs)

        return {
            "imported": n(self.imported),
            "skipped": (
                n(self.skipped_existing) + n(self.vault_newer) + n(self.changed_without_force)
            ),
        }

    @property
    def has_problems(self) -> bool:
        return bool(self.skipped_invalid or self.changed_without_force or self.problems)


@dataclass(frozen=True)
class _Candidate:
    page: AaPostPage
    content: bytes
    mtime: float

    @property
    def ref(self) -> WeekRef:
        return WeekRef(self.page.league, self.page.season, self.page.week)

    @property
    def time(self) -> datetime:
        """The post's modified time, else the browser save time."""
        if self.page.modified is not None:
            return self.page.modified.astimezone(UTC)
        return datetime.fromtimestamp(self.mtime, UTC)


def _manifest_time(stamp: object) -> datetime | None:
    if not isinstance(stamp, str):
        return None
    try:
        return datetime.strptime(stamp, _TIME_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


class AaImporter:
    """Imports hand-saved AA schedule posts from an incoming folder into the vault.

    Takes no client: nothing here can send a request.
    """

    def __init__(self, paths: DataPaths) -> None:
        self._paths = paths
        self._manifest = Manifest(paths.manifest)

    def run(self, *, incoming_dir: Path | None = None, force: bool = False) -> AaImportResult:
        result = AaImportResult()
        folder = incoming_dir if incoming_dir is not None else DEFAULT_INCOMING_DIR
        if not folder.is_dir():
            result.problems.append("incoming folder not found")
            return result

        freeze = FreezeGuard.load(self._paths.frozen)
        recorded = self._recorded_cfb_links(result)
        for candidate in self._choose(self._scan(folder, result), force, result):
            page, ref = candidate.page, candidate.ref
            if freeze.is_frozen(SOURCE, page.season):
                result.skipped_invalid.append(SkippedFile("season is frozen", page.league))
                continue
            if page.league == "cfb":
                link = recorded.get(week_key(page.season, page.week))
                if link is not None and link != page.canonical_url:
                    result.skipped_invalid.append(
                        SkippedFile("the feed watch recorded a different post for this week", "cfb")
                    )
                    continue
            dest = self._paths.raw / page.cache_path
            if dest.is_file():
                existing = dest.read_bytes()
                if existing == candidate.content:
                    result.skipped_existing.append(ref)
                    continue
                if not force:
                    vault_time = self._vault_time(existing, page)
                    if vault_time is not None and vault_time >= candidate.time:
                        result.vault_newer.append(ref)
                    else:
                        result.changed_without_force.append(ref)
                    continue
            self._write(dest, candidate)
            result.imported.append(ref)
        return result

    def _recorded_cfb_links(self, result: AaImportResult) -> dict[str, str]:
        if not (self._paths.ledger / "aa_feed_watch.json").is_file():
            return {}
        try:
            return dict(load_feed_state(self._paths).weeks)
        except Exception as exc:  # an unreadable state never blocks a hand import
            result.problems.append(f"feed watch state unreadable ({type(exc).__name__})")
            return {}

    def _scan(self, folder: Path, result: AaImportResult) -> list[_Candidate]:
        schedules = _Schedules(self._paths)
        candidates: list[_Candidate] = []
        saves = (p for p in folder.iterdir() if p.suffix.lower() in _HTML_SUFFIXES)
        for path in sorted(saves):
            if not path.is_file():
                continue
            content = path.read_bytes()
            examined = examine(content)
            if examined.status == "unrecognized":
                result.unrecognized += 1
                continue
            if examined.status == "invalid" or examined.page is None:
                result.skipped_invalid.append(
                    SkippedFile(examined.reason or "invalid", examined.league)
                )
                continue
            problem = schedules.problem(examined.page)
            if problem is not None:
                result.skipped_invalid.append(SkippedFile(problem, examined.page.league))
                continue
            candidates.append(_Candidate(examined.page, content, path.stat().st_mtime))
        return candidates

    @staticmethod
    def _choose(
        candidates: list[_Candidate], force: bool, result: AaImportResult
    ) -> list[_Candidate]:
        """One candidate per week. Identical copies collapse; different saves of one
        week are all rejected, unless --force keeps the newest save."""
        groups: dict[WeekRef, list[_Candidate]] = {}
        for candidate in candidates:
            groups.setdefault(candidate.ref, []).append(candidate)
        chosen: list[_Candidate] = []
        for ref, group in sorted(
            groups.items(), key=lambda item: (item[0].league, item[0].season, int(item[0].week))
        ):
            distinct: dict[bytes, _Candidate] = {}
            for candidate in group:
                kept = distinct.get(candidate.content)
                if kept is None or candidate.mtime > kept.mtime:
                    distinct[candidate.content] = candidate
            if len(distinct) == 1:
                chosen.extend(distinct.values())
                continue
            if force:
                ordered = sorted(distinct.values(), key=lambda c: (c.time, c.mtime))
                chosen.append(ordered[-1])
                result.superseded += len(ordered) - 1
                continue
            for _ in distinct:
                result.skipped_invalid.append(
                    SkippedFile("two different files claim this week", ref.league)
                )
        return chosen

    def _vault_time(self, existing: bytes, page: AaPostPage) -> datetime | None:
        """The vault copy's modified time, else its manifest save or fetch time."""
        try:
            parsed = parse_crews(existing.decode("utf-8", errors="replace"), season=page.season)
        except AaCrewsParseError:
            parsed = None
        if parsed is not None and parsed.modified is not None:
            return parsed.modified.astimezone(UTC)
        latest: datetime | None = None
        for entry in self._manifest.entries():
            if entry.get("path") != page.cache_path or entry.get("status") != 200:
                continue
            latest = _manifest_time(entry.get("saved_at")) or _manifest_time(
                entry.get("fetched_at")
            )
        return latest

    def _write(self, dest: Path, candidate: _Candidate) -> None:
        page = candidate.page
        # A copy the job fetched carries an ETag / Last-Modified; keep them on the hand
        # import's line so the Friday/Saturday conditional re-checks still have them
        # (a 304 means AA has not changed the post since that fetch).
        kept = self._manifest.latest_validators(page.canonical_url)
        atomic_write_bytes(dest, candidate.content)
        self._manifest.append(
            ManifestEntry(
                url=page.canonical_url,
                source=SOURCE,
                season=page.season,
                kind="page",
                fetched_at=datetime.now(UTC).strftime(_TIME_FORMAT),
                status=200,
                etag=kept.etag if kept is not None else None,
                last_modified=kept.last_modified if kept is not None else None,
                sha256=hashlib.sha256(candidate.content).hexdigest(),
                path=page.cache_path,
                bytes=len(candidate.content),
                final_url=page.canonical_url,
                origin=MANUAL_ORIGIN,
                # The file's own modified time is when the browser saved the page.
                saved_at=datetime.fromtimestamp(candidate.mtime, UTC).strftime(_TIME_FORMAT),
            )
        )
