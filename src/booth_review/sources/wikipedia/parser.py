"""Scheduling-changes parser for Wikipedia NFL season articles (D-17).

Finds the "scheduling changes" subsection of "Regular season", walks its
list items (including nested bullets, which inherit the current week), and
extracts raw facts only: week, the two team names as written, the original
time/day/network, and the new network/slot wording. Matching a change to a game
happens later against the team crosswalk. Anything that cannot be read cleanly
goes to ``unparsed`` instead of being guessed at; venue relocations are counted
and dropped. Only text is extracted, never markup (article text is CC BY-SA 4.0).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from booth_review.errors import ParseError

_NETWORKS = (
    "NFL Network",
    "Prime Video",
    "ESPN+",
    "Amazon",
    "Netflix",
    "YouTube",
    "Peacock",
    "ESPN",
    "CBS",
    "FOX",
    "Fox",
    "NBC",
    "ABC",
)
_NETWORK_ALT = "|".join(re.escape(n) for n in _NETWORKS)
NETWORK_RE = re.compile(rf"(?<![\w+])(?P<net>{_NETWORK_ALT})(?![\w+])")
ON_NETWORK_RE = re.compile(rf"\bon\s+(?P<net>{_NETWORK_ALT})(?![\w+])")
_DAYS = "Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday"
_TIME = r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>[apAP])\.?[mM]\.?\s*E[SD]?T"
ORIGINAL_TIME_RE = re.compile(
    rf"(?:originally scheduled (?:for|at)|moved from)\s+"
    rf"(?:(?P<day>{_DAYS})(?:,)?\s+(?:at\s+)?)?{_TIME}"
)
ANY_TIME_RE = re.compile(_TIME)
MATCHUP_RE = re.compile(r"(?P<a>[A-Z][\w.' ]+?)\s*[\u2013\u2014-]\s*(?P<b>[A-Z][\w.' ]+?)\s+game")
WEEK_LABEL_RE = re.compile(r"(?i)^\s*week\s+(\d{1,2})\s*[:\u2013\u2014-]?\s*(?P<rest>.*)$")
WEEK_BOLD_RE = re.compile(r"(?i)week\s+(\d{1,2})")
SECTION_RE = re.compile(r"(?i)scheduling changes")
RELOCATION_RE = re.compile(
    r"(?i)\bmoved to\b.*\b(stadium|field|dome|arena|park|city|venue|relocat\w*)\b"
)
SLOT_HINTS: tuple[tuple[str, str], ...] = (
    ("Sunday Night Football", "SNF"),
    ("Monday Night Football", "MNF"),
    ("Thursday Night Football", "TNF"),
    ("Saturday", "Saturday"),
)


@dataclass(frozen=True)
class ScheduleChange:
    season: int
    week: int
    team_a_raw: str
    team_b_raw: str
    original_day: str | None
    original_time_et: str | None
    original_network_raw: str | None
    new_network_raw: str | None
    new_slot_hint: str | None
    raw_text_hash: str
    new_time_et: str | None = None


@dataclass(frozen=True)
class UnparsedChange:
    season: int
    week: int | None
    raw_text_hash: str
    text: str


@dataclass(frozen=True)
class ChangesResult:
    changes: tuple[ScheduleChange, ...]
    unparsed: tuple[UnparsedChange, ...]
    relocations_ignored: int
    section_found: bool


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _to_24h(hour: str, minute: str | None, ap: str) -> str:
    h = int(hour) % 12
    if ap.lower() == "p":
        h += 12
    return f"{h:02d}:{minute or '00'}"


def _clean_team(name: str) -> str:
    name = _collapse(name)
    return name[4:] if name.lower().startswith("the ") else name


def _own_text(li: Tag) -> str:
    """The list item's text without nested lists."""
    parts: list[str] = []
    for child in li.children:
        if isinstance(child, Tag):
            if child.name in ("ul", "ol"):
                continue
            parts.append(child.get_text(" ", strip=True))
        else:
            parts.append(str(child))
    return _collapse(" ".join(parts))


class _Walker:
    def __init__(self, season: int) -> None:
        self.season = season
        self.week: int | None = None
        self.changes: list[ScheduleChange] = []
        self.unparsed: list[UnparsedChange] = []
        self.relocations = 0

    def walk_list(self, lst: Tag) -> None:
        for li in lst.find_all("li", recursive=False):
            self.item(li)
            for nested in li.find_all(["ul", "ol"], recursive=False):
                self.walk_list(nested)

    def item(self, li: Tag) -> None:
        text = _own_text(li)
        label = WEEK_LABEL_RE.match(text)
        if label:
            self.week = int(label.group(1))
            text = label.group("rest").strip()
        if not text:
            return
        self.candidate(text)

    def candidate(self, text: str) -> None:
        digest = _hash(text)
        original = ORIGINAL_TIME_RE.search(text)
        has_network = NETWORK_RE.search(text) is not None
        if not original and not has_network and RELOCATION_RE.search(text):
            self.relocations += 1
            return
        matchup = MATCHUP_RE.search(text)
        orig_net: str | None = None
        remainder = text
        if original:
            after = text[original.end() :]
            net = ON_NETWORK_RE.match(after.lstrip(", ")) or ON_NETWORK_RE.search(after[:20])
            if net:
                orig_net = net.group("net")
                remainder = after[after.find(orig_net) + len(orig_net) :]
            else:
                remainder = after
        if matchup is None or self.week is None or not original or orig_net is None:
            self.unparsed.append(UnparsedChange(self.season, self.week, digest, text))
            return
        new_time = ANY_TIME_RE.search(remainder)
        new_net = NETWORK_RE.search(remainder)
        hint = next((tag for phrase, tag in SLOT_HINTS if phrase in remainder), None)
        self.changes.append(
            ScheduleChange(
                season=self.season,
                week=self.week,
                team_a_raw=_clean_team(matchup.group("a")),
                team_b_raw=_clean_team(matchup.group("b")),
                original_day=original.group("day"),
                original_time_et=_to_24h(
                    original.group("h"), original.group("m"), original.group("ap")
                ),
                original_network_raw=orig_net,
                new_network_raw=new_net.group("net") if new_net else None,
                new_slot_hint=hint,
                raw_text_hash=digest,
                new_time_et=(
                    _to_24h(new_time.group("h"), new_time.group("m"), new_time.group("ap"))
                    if new_time
                    else None
                ),
            )
        )


def _is_heading_wrapper(tag: Tag) -> bool:
    return tag.name == "div" and "mw-heading" in (tag.get("class") or [])


def _find_section_heading(soup: BeautifulSoup) -> Tag | None:
    regular = next(
        (
            h
            for h in soup.find_all("h2")
            if _collapse(h.get_text(" ", strip=True)).lower().startswith("regular season")
        ),
        None,
    )
    if regular is None:
        return None
    for heading in regular.find_all_next(["h2", "h3"]):
        if heading.name == "h2":
            return None
        if SECTION_RE.search(heading.get_text(" ", strip=True)):
            return heading
    return None


def _section_siblings(heading: Tag):  # type: ignore[no-untyped-def]
    anchor = (
        heading.parent
        if isinstance(heading.parent, Tag) and _is_heading_wrapper(heading.parent)
        else heading
    )
    for sib in anchor.next_siblings:
        if not isinstance(sib, Tag):
            continue
        if sib.name in ("h2", "h3"):
            return
        if _is_heading_wrapper(sib) and sib.find(["h2", "h3"]):
            return
        yield sib


def parse_scheduling_changes(html: bytes, *, season: int) -> ChangesResult:
    """Extract scheduling-change facts from a season article's cached HTML."""
    try:
        text = html.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError(f"season {season}: Wikipedia article is not valid UTF-8") from exc
    soup = BeautifulSoup(text, "lxml")
    heading = _find_section_heading(soup)
    if heading is None:
        return ChangesResult((), (), 0, False)
    walker = _Walker(season)
    for sib in _section_siblings(heading):
        if sib.name in ("ul", "ol"):
            walker.walk_list(sib)
            continue
        for bold in sib.find_all(["b", "strong"]):
            m = WEEK_BOLD_RE.search(bold.get_text(" ", strip=True))
            if m:
                walker.week = int(m.group(1))
        for lst in sib.find_all(["ul", "ol"]):
            if lst.find_parent(["ul", "ol"]) is None:
                walker.walk_list(lst)
    return ChangesResult(tuple(walker.changes), tuple(walker.unparsed), walker.relocations, True)
