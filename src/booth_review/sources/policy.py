"""Robots.txt and terms re-check for the scripted second sources (04.19 D-10).

`booth-review collect tvrg|aa --policy-check` fetches each site's policy
page(s) and one index sample through the standard client (user agent,
robots.txt, pacing, cache), reads the robots.txt the client fetched, and
appends one line to ``ledger/policy_checks.jsonl``. A data pass for a source
runs only while `policy_fresh` is true: the newest line for that source is at
most 30 days old and has both ``robots_ok`` and ``terms_ok`` true. ``terms_ok``
is set only by ``--confirm-terms``, after the user has read a summary of the
site's current terms.

The client never reads ``Crawl-delay``; this module does, and a delay longer
than the host's ``min_interval_s`` fails the check rather than slowing down.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Final, Literal
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

from booth_review.config import HOST_POLICIES, USER_AGENT, DataPaths
from booth_review.errors import (
    BoothReviewError,
    RobotsDisallowedError,
    UnknownHostError,
    VaultStateError,
)
from booth_review.sources.base import BatchSummary, run_requests
from booth_review.transport.cache import Manifest, RawCache
from booth_review.transport.client import PoliteClient
from booth_review.transport.robots import RobotsRules
from booth_review.transport.types import FetchRequest, FetchResponse

POLICY_LEDGER: Final = "ledger/policy_checks.jsonl"
POLICY_MAX_AGE_DAYS: Final = 30

PolicySource = Literal["tvrg", "aa"]
POLICY_SOURCES: Final[tuple[PolicySource, ...]] = ("tvrg", "aa")

TVRG_HOST: Final = "www.thetvratingsguide.com"
AA_HOST: Final = "awfulannouncing.com"


class PolicyRobotsError(BoothReviewError):
    """robots.txt now disallows a planned path or asks for a longer Crawl-delay."""

    def __init__(self, verdict: RobotsVerdict) -> None:
        super().__init__(
            f"robots.txt check failed: disallowed {verdict.disallowed}, "
            f"crawl_delay {verdict.crawl_delay}"
        )
        self.verdict = verdict


# -- ledger ------------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyCheck:
    """One ledger line. ``checked_at`` is when robots.txt was actually read, so
    a later ``--confirm-terms`` line never extends a check's freshness."""

    source: str
    checked_at: datetime
    robots_ok: bool
    crawl_delay: float | None
    terms_ok: bool | None

    def to_json(self) -> str:
        return json.dumps(
            {
                "source": self.source,
                "checked_at": self.checked_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "robots_ok": self.robots_ok,
                "crawl_delay": self.crawl_delay,
                "terms_ok": self.terms_ok,
            },
            sort_keys=False,
        )

    @classmethod
    def from_dict(cls, row: dict[str, object]) -> PolicyCheck:
        checked = datetime.strptime(str(row["checked_at"]), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
        delay = row.get("crawl_delay")
        terms = row.get("terms_ok")
        return cls(
            source=str(row["source"]),
            checked_at=checked,
            robots_ok=row.get("robots_ok") is True,
            crawl_delay=float(delay) if isinstance(delay, int | float) else None,
            terms_ok=terms if isinstance(terms, bool) else None,
        )


def _ledger_path(paths: DataPaths) -> Path:
    return paths.vault / POLICY_LEDGER


def append_policy_check(paths: DataPaths, check: PolicyCheck) -> None:
    """Append one line in a single write (concurrent appenders never interleave)."""
    path = _ledger_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(check.to_json() + "\n")


def latest_policy_check(paths: DataPaths, source: str) -> PolicyCheck | None:
    """The last line written for `source` (file order), or None.

    An unreadable line (not JSON, or missing or malformed fields) stops with a
    count-only VaultStateError rather than a traceback. It is never skipped:
    skipping could make an older approval the newest line (fail closed).
    """
    path = _ledger_path(paths)
    if not path.is_file():
        return None
    latest: PolicyCheck | None = None
    unreadable: list[int] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
                if not isinstance(row, dict):
                    raise TypeError("not an object")
                check = PolicyCheck.from_dict(row)
            except (ValueError, KeyError, TypeError):
                unreadable.append(line_no)
                continue
            if check.source == source:
                latest = check
    if unreadable:
        raise VaultStateError(
            f"{POLICY_LEDGER}: {len(unreadable)} unreadable line(s), first at line "
            f"{unreadable[0]}; fix or remove it, then run --policy-check"
        )
    return latest


def _within(check: PolicyCheck, now: datetime, max_age_days: int) -> bool:
    age = now - check.checked_at
    return timedelta(0) <= age <= timedelta(days=max_age_days) or (
        # A clock a few seconds behind the ledger is still "now".
        timedelta(minutes=-5) <= age < timedelta(0)
    )


def robots_fresh(
    paths: DataPaths, source: str, now: datetime, max_age_days: int = POLICY_MAX_AGE_DAYS
) -> PolicyCheck | None:
    """The newest line when it is robots-ok and within `max_age_days`, else None."""
    check = latest_policy_check(paths, source)
    if check is None or not check.robots_ok or not _within(check, now, max_age_days):
        return None
    return check


def policy_fresh(
    paths: DataPaths, source: str, now: datetime, max_age_days: int = POLICY_MAX_AGE_DAYS
) -> bool:
    """True only when the newest line for `source` is within `max_age_days`
    and has both robots_ok and terms_ok true."""
    check = robots_fresh(paths, source, now, max_age_days)
    return check is not None and check.terms_ok is True


# -- robots.txt --------------------------------------------------------------------------


def _ua_token(user_agent: str) -> str:
    parts = user_agent.split()
    return parts[0].split("/", 1)[0].lower() if parts else ""


def _groups(robots_text: str) -> list[tuple[list[str], list[tuple[str, str]]]]:
    """(agents, [(field, value), ...]) per group, comments stripped."""
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    fields: list[tuple[str, str]] = []
    in_body = False
    for raw in robots_text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        name = name.strip().lower()
        value = value.strip()
        if name == "user-agent":
            if in_body:
                groups.append((agents, fields))
                agents, fields, in_body = [], [], False
            agents.append(value.lower())
        elif name == "sitemap":
            continue  # not part of any group
        else:
            in_body = True
            fields.append((name, value))
    if agents:
        groups.append((agents, fields))
    return groups


def crawl_delay_for(robots_text: str, user_agent: str = USER_AGENT) -> float | None:
    """The Crawl-delay of the group naming our token ("booth-review"), else
    of the "*" group; None when that group sets none (or an unreadable one)."""
    token = _ua_token(user_agent)
    specific: list[tuple[str, str]] = []
    wildcard: list[tuple[str, str]] = []
    found = False
    for agents, fields in _groups(robots_text):
        if token and token in agents:
            found = True
            specific.extend(fields)
        if "*" in agents:
            wildcard.extend(fields)
    delays: list[float] = []
    for name, value in specific if found else wildcard:
        if name == "crawl-delay":
            try:
                delays.append(float(value))
            except ValueError:
                continue
    return max(delays) if delays else None


def sitemap_urls(robots_text: str) -> list[str]:
    """Every ``Sitemap:`` URL in file order."""
    urls: list[str] = []
    for raw in robots_text.splitlines():
        line = raw.split("#", 1)[0].strip()
        name, sep, value = line.partition(":")
        if sep and name.strip().lower() == "sitemap" and value.strip():
            urls.append(value.strip())
    return urls


@dataclass(frozen=True)
class RobotsVerdict:
    status: int
    crawl_delay: float | None
    min_interval_s: float
    disallowed: int
    sitemaps: tuple[str, ...] = ()

    @property
    def delay_ok(self) -> bool:
        return self.crawl_delay is None or self.crawl_delay <= self.min_interval_s

    @property
    def ok(self) -> bool:
        return self.disallowed == 0 and self.delay_ok


def evaluate_robots(
    status: int, content: bytes, *, host: str, planned_urls: Sequence[str]
) -> RobotsVerdict:
    """Judge robots.txt the way PoliteClient does (401/403 block everything,
    other 4xx allow everything), plus the Crawl-delay the client ignores."""
    min_interval = HOST_POLICIES[host].min_interval_s
    if status in (401, 403):
        return RobotsVerdict(status, None, min_interval, disallowed=len(planned_urls))
    if status != 200:
        return RobotsVerdict(status, None, min_interval, disallowed=0)
    text = content.decode("utf-8", errors="replace")
    lines = text.splitlines()
    parser = robotparser.RobotFileParser()
    parser.parse(lines)
    rules = RobotsRules.parse(lines, agent=USER_AGENT)
    disallowed = sum(
        1 for url in planned_urls if not parser.can_fetch(USER_AGENT, url) or rules.disallows(url)
    )
    return RobotsVerdict(
        status,
        crawl_delay_for(text),
        min_interval,
        disallowed=disallowed,
        sitemaps=tuple(sitemap_urls(text)),
    )


def cached_robots(paths: DataPaths, host: str) -> tuple[int, bytes, datetime] | None:
    """(status, body, fetched_at) of the newest robots.txt the cache stored for
    `host`, from the request manifest; None when it was never fetched."""
    url = f"https://{host}/robots.txt"
    latest: dict[str, object] | None = None
    for entry in Manifest(paths.manifest).entries():
        if entry.get("url") == url and entry.get("kind") == "robots" and entry.get("path"):
            latest = entry
    if latest is None:
        return None
    body_path = paths.raw / str(latest["path"])
    if not body_path.is_file():
        return None
    fetched = datetime.strptime(str(latest["fetched_at"]), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    status = latest.get("status")
    return (status if isinstance(status, int) else 200), body_path.read_bytes(), fetched


# -- policy pages ------------------------------------------------------------------------


class _LinkFinder(HTMLParser):
    """Collects (href, text) for every anchor."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None


def legal_link(html: bytes, base_url: str) -> str | None:
    """The absolute URL of the first anchor whose text is "Legal Information"."""
    finder = _LinkFinder()
    finder.feed(html.decode("utf-8", errors="replace"))
    for href, text in finder.links:
        if text.lower() == "legal information" and href:
            return urljoin(base_url, href)
    return None


@dataclass(frozen=True)
class PolicyTarget:
    source: PolicySource
    host: str
    pages: tuple[tuple[str, str], ...]
    """(cache name, URL) of the policy page(s) always fetched."""
    planned_samples: tuple[str, ...]
    """URL shapes the later data pass will request; checked against robots.txt only."""


TARGETS: Final[dict[PolicySource, PolicyTarget]] = {
    "tvrg": PolicyTarget(
        source="tvrg",
        host=TVRG_HOST,
        # Blogspot: no terms page, so the home page (footer) is the policy page.
        pages=(("home", f"https://{TVRG_HOST}/"),),
        planned_samples=(
            f"https://{TVRG_HOST}/2021/09/",
            f"https://{TVRG_HOST}/2021/09/sample-post.html",
        ),
    ),
    "aa": PolicyTarget(
        source="aa",
        host=AA_HOST,
        pages=(("disclaimer", f"https://{AA_HOST}/disclaimer"),),
        planned_samples=(
            f"https://{AA_HOST}/college-football/2023-college-football-week-1-viewership-sample.html",
            f"https://{AA_HOST}/schedules/feed/",
            f"https://{AA_HOST}/feed/",
        ),
    ),
}


def robots_guard(source: PolicySource) -> Callable[[str, FetchResponse], None]:
    """Stop a data pass when the robots.txt the client reads now disallows
    everything or asks for a longer Crawl-delay than our pacing (D-10).

    Shared by the CLI and the scheduled job's feed poll.
    """
    host = TARGETS[source].host

    def _check(seen_host: str, resp: FetchResponse) -> None:
        if seen_host != host:
            return
        verdict = evaluate_robots(
            resp.status_code, resp.content, host=host, planned_urls=TARGETS[source].planned_samples
        )
        if not verdict.ok:
            raise PolicyRobotsError(verdict)

    return _check


def tvrg_archive_url(year: int, month: int) -> str:
    return f"https://{TVRG_HOST}/{year:04d}/{month:02d}/"


@dataclass
class PolicyOutcome:
    """What one policy check found; printed and ledgered count-only."""

    source: PolicySource
    summary: BatchSummary
    verdict: RobotsVerdict | None
    robots_checked_at: datetime | None
    legal_page: str = "n/a"
    index_sample: str = "none"
    notes: list[str] = field(default_factory=list)

    @property
    def robots_ok(self) -> bool:
        return self.verdict is not None and self.verdict.ok


def _merge(a: BatchSummary, b: BatchSummary) -> BatchSummary:
    return BatchSummary(
        source=a.source,
        season_label=a.season_label,
        planned=a.planned + b.planned,
        cached=a.cached + b.cached,
        fetched=a.fetched + b.fetched,
        not_modified=a.not_modified + b.not_modified,
        failed=a.failed + b.failed,
        frozen_miss=a.frozen_miss + b.frozen_miss,
        new_urls=[*a.new_urls, *b.new_urls],
        failed_urls=[*a.failed_urls, *b.failed_urls],
    )


class PolicyChecker:
    """Runs one source's policy check through the standard cache and client.

    robots.txt is judged the moment the client fetches it (a listener), so a
    disallowed planned path or a long Crawl-delay stops the run before any
    policy page is requested. When every page is already cached (a same-day
    re-run), the newest cached robots.txt from the request manifest is judged.
    """

    def __init__(
        self,
        cache: RawCache,
        client: PoliteClient,
        paths: DataPaths,
        source: PolicySource,
        *,
        today: date,
        index_month: tuple[int, int] | None = None,
    ) -> None:
        self._cache = cache
        self._client = client
        self._paths = paths
        self._target = TARGETS[source]
        self._today = today
        self._index_month = index_month
        self._live: tuple[RobotsVerdict, datetime] | None = None
        client.add_robots_listener(self._on_robots)

    @property
    def target(self) -> PolicyTarget:
        return self._target

    def _on_robots(self, host: str, resp: FetchResponse) -> None:
        if host != self._target.host:
            return
        verdict = evaluate_robots(
            resp.status_code,
            resp.content,
            host=host,
            planned_urls=self._target.planned_samples,
        )
        self._live = (verdict, resp.fetched_at)
        if not verdict.ok:
            raise PolicyRobotsError(verdict)

    def _policy_request(self, name: str, url: str) -> FetchRequest:
        return FetchRequest(
            source=self._target.source,
            season=None,
            url=url,
            cache_path=f"{self._target.source}/_policy/{self._today.isoformat()}/{name}.html",
        )

    def _run(self, requests: Sequence[FetchRequest]) -> BatchSummary:
        return run_requests(
            self._cache,
            requests,
            source=self._target.source,
            season_label="policy",
            dry_run=False,
        )

    def _optional(self, req: FetchRequest) -> tuple[BatchSummary, str]:
        """Fetch an optional page; a redirect off the allow-list is a note, not a failure."""
        try:
            summary = self._run([req])
        except UnknownHostError:
            empty = BatchSummary(self._target.source, "policy", 1, 0, 0, 0, 0, 0)
            return empty, "redirected off the allow-list, not followed"
        except RobotsDisallowedError:
            empty = BatchSummary(self._target.source, "policy", 1, 0, 0, 0, 0, 0)
            return empty, "robots-disallowed, not fetched"
        if summary.failed:
            return summary, "failed"
        return summary, "fetched" if summary.fetched else "cached"

    def _verdict(self) -> tuple[RobotsVerdict, datetime] | None:
        if self._live is not None:
            return self._live
        stored = cached_robots(self._paths, self._target.host)
        if stored is None:
            return None
        status, body, fetched_at = stored
        verdict = evaluate_robots(
            status, body, host=self._target.host, planned_urls=self._target.planned_samples
        )
        return verdict, fetched_at

    def run(self) -> PolicyOutcome:
        """Fetch the policy page(s), then the index sample. Raises
        PolicyRobotsError, RobotsDisallowedError or UnknownHostError on a
        robots or allow-list failure (the caller ledgers robots_ok false)."""
        target = self._target
        pages = [self._policy_request(name, url) for name, url in target.pages]
        summary = self._run(pages)
        judged = self._verdict()
        verdict, checked_at = judged if judged is not None else (None, None)
        if verdict is not None and not verdict.ok:
            raise PolicyRobotsError(verdict)
        outcome = PolicyOutcome(
            source=target.source, summary=summary, verdict=verdict, robots_checked_at=checked_at
        )
        if target.source == "tvrg":
            self._tvrg_extras(outcome)
        else:
            self._aa_extras(outcome, pages[0])
        return outcome

    def _tvrg_extras(self, outcome: PolicyOutcome) -> None:
        if self._index_month is None:
            outcome.index_sample = "none (no gap month)"
            return
        year, month = self._index_month
        req = FetchRequest(
            source="tvrg",
            season=None,
            url=tvrg_archive_url(year, month),
            cache_path=f"tvrg/index/{year:04d}-{month:02d}.html",
        )
        # The archive is a planned data path: a robots ban here must stop the
        # check, so it is not wrapped like the optional AA pages.
        index_summary = self._run([req])
        outcome.summary = _merge(outcome.summary, index_summary)
        outcome.index_sample = (
            "failed" if index_summary.failed else ("fetched" if index_summary.fetched else "cached")
        )

    def _aa_extras(self, outcome: PolicyOutcome, disclaimer: FetchRequest) -> None:
        body = self._cache.read_cached(disclaimer)
        link = legal_link(body, disclaimer.url) if body else None
        if link is None:
            outcome.legal_page = "no link found"
        elif urlsplit(link).hostname != AA_HOST:
            outcome.legal_page = "external legal page not fetched"
        else:
            legal_req = self._policy_request("legal", link)
            legal_summary, status = self._optional(legal_req)
            outcome.summary = _merge(outcome.summary, legal_summary)
            outcome.legal_page = status

        sitemaps = outcome.verdict.sitemaps if outcome.verdict is not None else ()
        if not sitemaps:
            outcome.index_sample = "none (no Sitemap line)"
            return
        first = sitemaps[0]
        if urlsplit(first).hostname != AA_HOST:
            outcome.index_sample = "external sitemap not fetched"
            return
        index_req = FetchRequest(
            source="aa", season=None, url=first, cache_path="aa/index/sitemap-1.xml"
        )
        index_summary, status = self._optional(index_req)
        outcome.summary = _merge(outcome.summary, index_summary)
        outcome.index_sample = status
