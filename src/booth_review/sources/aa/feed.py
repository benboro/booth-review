"""Awful Announcing feed watch (Phase 25): find this week's CFB schedule post.

A feed-only check. The response body is held in memory only. Only the title,
link, pubDate and categories of each item are read; the title is used for
matching in memory and is never stored or logged. The feed is never cached
under ``raw/`` (D-12). The only things persisted are the ETag and
Last-Modified validators, the verified feed URL, the week-to-link map and the
weeks whose plain reminder already went out, in ``ledger/aa_feed_watch.json``,
plus a path-less audit row per request in ``ledger/requests.jsonl``.

Untrusted XML: a DOCTYPE or ENTITY declaration is refused, and the parser
never resolves entities or touches the network.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from lxml import etree

from booth_review.config import DataPaths
from booth_review.errors import ParseError, VaultStateError
from booth_review.sources.aa.collector import _OTHER_LEAGUES
from booth_review.sources.aa.index import on_host
from booth_review.transport.cache import Manifest, ManifestEntry, atomic_write_json
from booth_review.transport.client import PoliteClient
from booth_review.transport.types import FetchResponse, Validators

AA_FEED_CANDIDATES: Final = {
    "schedules": "https://awfulannouncing.com/schedules/feed/",
    "site": "https://awfulannouncing.com/feed/",
}
"""Both UNVERIFIED until the one real `booth-review collect` request (D-10)."""

FEED_MAX_BYTES: Final = 1_500_000
FEED_STATE_NAME: Final = "aa_feed_watch.json"
EASTERN: Final = ZoneInfo("America/New_York")

_FORBIDDEN_DECL = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
_LINE_RE = re.compile(r"^[A-Za-z0-9 ,()_./:#-]+$")
_WEEK_KEY_RE = re.compile(r"^[0-9]{4}-[A-Za-z0-9]+$")
# A Friday/Saturday crews re-check slot: its ET date and slot hour (Phase 27 review WR-02).
_SLOT_KEY_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}$")
_URL_PATH_RE = re.compile(r"^/[a-z0-9/._-]+$")
_COLLEGE_WORDS: Final = frozenset({"college", "cfb", "ncaa"})
_TS_FORMAT: Final = "%Y-%m-%dT%H:%M:%SZ"


class FeedNotVerifiedError(Exception):
    """No feed has been verified yet (run the verify step first)."""


class FeedStatusError(Exception):
    """The feed answered with an unexpected HTTP status."""

    def __init__(self, status: int) -> None:
        super().__init__(f"aa feed: unexpected status {status}")
        self.status = status


@dataclass(frozen=True)
class FeedEntry:
    link: str
    pub_date: datetime | None
    categories: tuple[str, ...]
    title: str


@dataclass(frozen=True)
class FeedWatchState:
    verified_feed_url: str | None
    verified_at: str | None
    etag: str | None
    last_modified: str | None
    checked_at: str | None
    weeks: dict[str, str]
    blind_weeks: list[str]
    """Week keys whose plain (blind) reminder line already went out (D-11)."""
    crews_rechecked: list[str] = field(default_factory=list)
    """Friday/Saturday crews re-check slots (ET `YYYY-MM-DDTHH`) that already sent
    their one request, so a backup or manual run in the same slot sends none."""
    crews_failed: list[str] = field(default_factory=list)
    """Week keys whose Tuesday crews post request failed; the job never sends it
    again (a failed request is never retried, adversarial panel F8)."""


@dataclass(frozen=True)
class WeekCheck:
    url: str | None
    requested: bool
    status: int | None


@dataclass(frozen=True)
class VerifyResult:
    feed_url: str
    status: int
    entries: int
    cfb_links: tuple[str, ...]
    other_schedule_links: tuple[str, ...]
    verified: bool


# -- parse ---------------------------------------------------------------------------------


def _local(tag: object) -> str | None:
    if not isinstance(tag, str):
        return None
    return tag.rsplit("}", 1)[-1]


def _pub_date(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        value = parsedate_to_datetime(text.strip())
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def parse_feed(xml: bytes) -> list[FeedEntry]:
    """Parse an RSS 2.0 feed into entries. Raises ParseError on a DOCTYPE/ENTITY
    declaration or invalid XML."""
    if _FORBIDDEN_DECL.search(xml):
        raise ParseError("aa feed: DOCTYPE/ENTITY declarations are forbidden")
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, huge_tree=False, load_dtd=False
    )
    try:
        root = etree.fromstring(xml, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise ParseError(f"aa feed: invalid XML: {exc}") from exc
    if root.getroottree().docinfo.doctype:
        raise ParseError("aa feed: DOCTYPE/ENTITY declarations are forbidden")

    entries: list[FeedEntry] = []
    for channel in root:
        if _local(channel.tag) != "channel":
            continue
        for item in channel:
            if _local(item.tag) != "item":
                continue
            link = ""
            title = ""
            pub: datetime | None = None
            cats: list[str] = []
            for child in item:
                name = _local(child.tag)
                if name == "link":
                    link = (child.text or "").strip()
                elif name == "title":
                    title = (child.text or "").strip()
                elif name == "pubDate":
                    pub = _pub_date(child.text)
                elif name == "category":
                    cats.append((child.text or "").strip())
            if link:
                entries.append(FeedEntry(link, pub, tuple(cats), title))
    return entries


# -- match ---------------------------------------------------------------------------------


def _path_parts(link: str) -> list[str]:
    return [p for p in urlsplit(link).path.split("/") if p]


def _tokens(entry: FeedEntry) -> set[str]:
    parts = _path_parts(entry.link)
    slug = parts[-1].removesuffix(".html").lower() if parts else ""
    tokens = set(slug.split("-"))
    tokens |= set(re.split(r"[^a-z0-9]+", entry.title.lower()))
    tokens.discard("")
    return tokens


def is_cfb_schedule_post(entry: FeedEntry) -> bool:
    """True for an on-host CFB announcing-schedule post (D-10).

    Never uses a week number: the week is decided by the post's date.
    """
    if on_host(entry.link) is None or urlsplit(entry.link).query:
        return False
    parts = _path_parts(entry.link)
    cats = {c.strip().lower().replace(" ", "-") for c in entry.categories}
    in_schedules = "schedules" in cats or (len(parts) > 1 and parts[0] == "schedules")
    in_college = "college-football" in cats or (len(parts) > 1 and parts[0] == "college-football")
    if not (in_schedules or in_college):
        return False
    tokens = _tokens(entry)
    if not tokens & _COLLEGE_WORDS:
        return False
    if not (
        ("announcing" in tokens and tokens & {"schedule", "schedules"}) or "announcers" in tokens
    ):
        return False
    return not tokens & _OTHER_LEAGUES


def week_start_et(now: datetime) -> datetime:
    """Monday 00:00 America/New_York of the ET week containing `now`."""
    if now.tzinfo is None:
        raise ValueError("week_start_et needs a timezone-aware datetime")
    local = now.astimezone(EASTERN)
    monday = local.date() - timedelta(days=local.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=EASTERN)


def match_week_post(entries: list[FeedEntry], now: datetime) -> str | None:
    start = week_start_et(now)
    best: tuple[datetime, str] | None = None
    for entry in entries:
        if entry.pub_date is None or not is_cfb_schedule_post(entry):
            continue
        if entry.pub_date < start:
            continue
        url = on_host(entry.link)
        if url is not None and (best is None or entry.pub_date > best[0]):
            best = (entry.pub_date, url)
    return best[1] if best else None


# -- state ---------------------------------------------------------------------------------


def week_key(season: int, label: str) -> str:
    return f"{season}-{label}"


def _empty_state() -> FeedWatchState:
    return FeedWatchState(None, None, None, None, None, {}, [])


def _state_path(paths: DataPaths) -> Path:
    return paths.ledger / FEED_STATE_NAME


def _opt_str(raw: dict[str, object], key: str) -> str | None:
    value = raw.get(key)
    if value is not None and not isinstance(value, str):
        raise VaultStateError(f"{FEED_STATE_NAME}: {key} must be a string or null")
    return value


def load_feed_state(paths: DataPaths) -> FeedWatchState:
    path = _state_path(paths)
    if not path.is_file():
        return _empty_state()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VaultStateError(f"{FEED_STATE_NAME}: unreadable ({type(exc).__name__})") from exc
    if not isinstance(raw, dict):
        raise VaultStateError(f"{FEED_STATE_NAME}: top level must be an object")
    weeks = raw.get("weeks", {})
    blind = raw.get("blind_weeks", [])
    if not isinstance(weeks, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in weeks.items()
    ):
        raise VaultStateError(f"{FEED_STATE_NAME}: weeks must map strings to strings")
    if not isinstance(blind, list) or not all(isinstance(k, str) for k in blind):
        raise VaultStateError(f"{FEED_STATE_NAME}: blind_weeks must be a list of strings")
    rechecked = raw.get("crews_rechecked", [])
    if not isinstance(rechecked, list) or not all(isinstance(k, str) for k in rechecked):
        raise VaultStateError(f"{FEED_STATE_NAME}: crews_rechecked must be a list of strings")
    failed = raw.get("crews_failed", [])
    if not isinstance(failed, list) or not all(isinstance(k, str) for k in failed):
        raise VaultStateError(f"{FEED_STATE_NAME}: crews_failed must be a list of strings")
    return FeedWatchState(
        verified_feed_url=_opt_str(raw, "verified_feed_url"),
        verified_at=_opt_str(raw, "verified_at"),
        etag=_opt_str(raw, "etag"),
        last_modified=_opt_str(raw, "last_modified"),
        checked_at=_opt_str(raw, "checked_at"),
        weeks=dict(weeks),
        blind_weeks=list(blind),
        crews_rechecked=list(rechecked),
        crews_failed=list(failed),
    )


def _check_url(url: str) -> None:
    if (
        on_host(url) is None
        or _LINE_RE.fullmatch(url) is None
        or _URL_PATH_RE.fullmatch(urlsplit(url).path) is None
    ):
        raise ValueError("feed state: refusing a URL that is off-host or off the whitelist")


def save_feed_state(paths: DataPaths, state: FeedWatchState) -> None:
    if state.verified_feed_url is not None:
        _check_url(state.verified_feed_url)
    for key, url in state.weeks.items():
        if _WEEK_KEY_RE.fullmatch(key) is None:
            raise ValueError("feed state: bad week key")
        _check_url(url)
    for key in state.blind_weeks:
        if _WEEK_KEY_RE.fullmatch(key) is None:
            raise ValueError("feed state: bad blind week key")
    for key in state.crews_rechecked:
        if _SLOT_KEY_RE.fullmatch(key) is None:
            raise ValueError("feed state: bad crews re-check slot key")
    for key in state.crews_failed:
        if _WEEK_KEY_RE.fullmatch(key) is None:
            raise ValueError("feed state: bad crews failed week key")
    payload: dict[str, object] = {
        "verified_feed_url": state.verified_feed_url,
        "verified_at": state.verified_at,
        "etag": state.etag,
        "last_modified": state.last_modified,
        "checked_at": state.checked_at,
        "weeks": dict(sorted(state.weeks.items())),
        "blind_weeks": sorted(set(state.blind_weeks)),
    }
    if state.crews_rechecked:  # absent until the first re-check, so older files stay as they were
        payload["crews_rechecked"] = sorted(set(state.crews_rechecked))
    if state.crews_failed:  # absent until a post request fails, likewise
        payload["crews_failed"] = sorted(set(state.crews_failed))
    atomic_write_json(_state_path(paths), payload)


def record_blind_week(paths: DataPaths, *, season: int, label: str) -> bool:
    """Mark a week's plain reminder as sent. True when newly added."""
    state = load_feed_state(paths)
    key = week_key(season, label)
    if key in state.blind_weeks:
        return False
    save_feed_state(paths, replace(state, blind_weeks=[*state.blind_weeks, key]))
    return True


def record_crews_recheck(paths: DataPaths, slot: str) -> bool:
    """Mark a Friday/Saturday crews re-check slot as used. True when newly added."""
    if _SLOT_KEY_RE.fullmatch(slot) is None:
        raise ValueError("feed state: bad crews re-check slot key")
    state = load_feed_state(paths)
    if slot in state.crews_rechecked:
        return False
    save_feed_state(paths, replace(state, crews_rechecked=[*state.crews_rechecked, slot]))
    return True


def record_crews_failed(paths: DataPaths, *, season: int, label: str) -> bool:
    """Mark a week whose Tuesday crews post request failed. True when newly added."""
    state = load_feed_state(paths)
    key = week_key(season, label)
    if key in state.crews_failed:
        return False
    save_feed_state(paths, replace(state, crews_failed=[*state.crews_failed, key]))
    return True


def crews_rechecked(paths: DataPaths, slot: str) -> bool:
    """True when the slot's one re-check request already went out."""
    return slot in load_feed_state(paths).crews_rechecked


# -- poll ----------------------------------------------------------------------------------


def _now_ts(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(_TS_FORMAT)


def _audit(paths: DataPaths, url: str, response: FetchResponse) -> None:
    Manifest(paths.manifest).append(
        ManifestEntry(
            url=url,
            source="aa",
            season=None,
            kind="page",
            fetched_at=_now_ts(response.fetched_at),
            status=response.status_code,
            etag=response.etag,
            last_modified=response.last_modified,
            sha256=None,
            path=None,
            bytes=None,
            final_url=response.final_url,
        )
    )


def check_week(
    client: PoliteClient, paths: DataPaths, *, season: int, label: str, now: datetime
) -> WeekCheck:
    """At most one conditional request for this week's post link (D-05, D-06, D-11)."""
    state = load_feed_state(paths)
    key = week_key(season, label)
    if key in state.weeks:
        return WeekCheck(state.weeks[key], False, None)
    if key in state.blind_weeks:
        return WeekCheck(None, False, None)
    if state.verified_feed_url is None:
        raise FeedNotVerifiedError("no verified AA feed; run the verify step first")

    validators = (
        Validators(state.etag, state.last_modified) if state.etag or state.last_modified else None
    )
    response = client.fetch(
        state.verified_feed_url, validators=validators, max_bytes=FEED_MAX_BYTES
    )
    _audit(paths, state.verified_feed_url, response)
    checked_at = _now_ts(response.fetched_at)
    if response.status_code == 304:
        save_feed_state(paths, replace(state, checked_at=checked_at))
        return WeekCheck(None, True, 304)
    if response.status_code != 200:
        raise FeedStatusError(response.status_code)

    entries = parse_feed(response.content)
    url = match_week_post(entries, now)
    weeks = dict(state.weeks)
    if url is not None:
        weeks.setdefault(key, url)
    new_state = replace(
        state,
        etag=response.etag,
        last_modified=response.last_modified,
        checked_at=checked_at,
        weeks=weeks,
    )
    del response, entries
    save_feed_state(paths, new_state)
    return WeekCheck(weeks.get(key), True, 200)


def verify_feed(
    client: PoliteClient, paths: DataPaths, candidate: str, now: datetime
) -> VerifyResult:
    """One unconditional request; record the feed as verified only when it carries
    at least one CFB schedule post (D-03, D-10)."""
    if candidate not in AA_FEED_CANDIDATES:
        raise ValueError(f"unknown feed candidate {candidate!r}")
    url = AA_FEED_CANDIDATES[candidate]
    response = client.fetch(url, validators=None, max_bytes=FEED_MAX_BYTES)
    _audit(paths, url, response)
    if response.status_code != 200:
        return VerifyResult(url, response.status_code, 0, (), (), False)
    entries = parse_feed(response.content)
    cfb: list[str] = []
    other: list[str] = []
    for entry in entries:
        link = on_host(entry.link)
        if link is None:
            continue
        if is_cfb_schedule_post(entry):
            cfb.append(link)
        else:
            parts = _path_parts(link)
            if parts and parts[0] == "schedules":
                other.append(link)
    verified = bool(cfb)
    if verified:
        state = load_feed_state(paths)
        save_feed_state(
            paths,
            replace(
                state,
                verified_feed_url=url,
                verified_at=_now_ts(now),
                etag=None,
                last_modified=None,
            ),
        )
    return VerifyResult(url, 200, len(entries), tuple(cfb), tuple(other), verified)
