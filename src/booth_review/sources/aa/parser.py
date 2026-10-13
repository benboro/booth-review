"""Awful Announcing ratings post parser (04.19 D-10, D-17, D-21).

AA posts are prose: the ``entry-content`` body holds paragraphs (plus the odd
heading, list or embedded post in a ``blockquote``), and the page's
``application/ld+json`` block carries ``headline`` and ``datePublished``.
Figures appear inside sentences as ``N.N million`` (1-3 decimals), ``N.NM``
or comma integers, next to peaks, streaming numbers, comparisons with other
seasons and other games. This parser loads a figure only when one sentence
ties it to exactly one named game, and never guesses:

- Every figure mention outside an embedded post gets a line number: its
  1-based position among the post body's figure mentions, in document order.
  The pointer is ``<post-slug>:<line>`` (slug as the collector caches it).
- A mention that is a peak (a "peak" word just before or after it) or a
  streaming-only number ("stream", "unique", "online", "digital" next to it)
  is ignored and counted. Mentions inside a ``blockquote`` are ignored too.
- A sentence yields a ``figure`` row only when it has exactly one remaining
  mention and reads as one of these forms (the "game" is "<A>'s ... win over
  <B>", "<A>-<B> game", "<A> vs./v./at <B>", or "the game/contest/matchup"
  when the headline names exactly one game):
    ``<game> averaged|drew [up to 4 words] <figure> viewers [on <network>]...``
    ``<network> averaged|drew [...] <figure> viewers for [the] <game>...``
    ``<A>-<B> (<network>): <figure>`` (a roundup line)
  and its subject names no other season ("last year", a year other than the
  season's) and no multi-game total ("combined", "doubleheader", "window").
  The network is the first ``on|across <Network>`` before the clause ends
  (several networks join with " & ", which the shared rules call a simulcast);
  a sentence that names none leaves it blank, which the matcher sends to review.
- Every other remaining mention becomes a ``needs_review`` row (no figure).

Date rule: the post date is ``datePublished`` in ET. A figure sentence that
names a weekday dates the game to the latest such weekday before the post
date ("last night" is the day before); otherwise the game is dated to the
latest Saturday before the post date. The matcher then allows +/-1 day.
Rank is the post date's ordinal, so a later post wins a duplicate.
Errors are count-only; nothing here fetches or executes anything.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from booth_review.sources.gapcollect import safe_slug
from booth_review.sources.second_rows import (
    ParsedPost,
    RowKind,
    SecondSourceRow,
    host_matches,
)
from booth_review.sources.smw.rows import classify_row

_ET = ZoneInfo("America/New_York")

_FIG = r"\d{1,3}(?:\.\d{1,3})?\s*(?:million\b|M\b)|\d{1,3}(?:,\d{3})+(?![\d,])"
_FIG_RE = re.compile(rf"(?<![\w.,$])(?:{_FIG})")
_MILLION_RE = re.compile(r"^(\d{1,3}(?:\.\d{1,3})?)\s*(?:million|M)$")
_COMMA_INT_RE = re.compile(r"^\d{1,3}(?:,\d{3})+$")

# A capitalized word of a team or network name ("A&M", "(OH)", "St.", "Notre").
_CAP = r"[A-Z(][\w.&'\u2019()]*"
_CAP_H = r"[A-Z(][\w.&'\u2019()-]*"  # the same, hyphens allowed (no pair split needed)
_RANK = r"(?:(?:No\.\s*|#)\d{1,2}\s+)?"
_TEAM = rf"{_RANK}{_CAP}(?:\s+(?:{_CAP}|&)){{0,4}}"
_TEAM_H = rf"{_RANK}{_CAP_H}(?:\s+(?:{_CAP_H}|&)){{0,4}}"
_PLACE = rf"(?:\s+in\s+{_CAP}(?:\s+{_CAP}){{0,2}})?"
_NOUN = r"(?:win|victory|upset|rout|loss|defeat|triumph|blowout|shutout|comeback)"
_GAME_WORD = r"(?:game|matchup|contest|showdown|clash|battle)"
_POSS = (
    rf"(?P<pa>{_TEAM_H})[\u2019']s\s+(?:[\w-]+\s+){{0,3}}?{_NOUN}\s+(?:(?:win|victory)\s+)?"
    rf"(?:over|against|to)\s+(?:the\s+)?(?P<pb>{_TEAM_H}){_PLACE}"
)
_PAIR = rf"(?P<pair>{_TEAM}\s*[-\u2013]\s*{_TEAM})(?:\s+{_GAME_WORD})?{_PLACE}"
_VS = rf"(?P<va>{_TEAM_H})\s+(?:vs\.?|v\.?|at)\s+(?P<vb>{_TEAM_H})(?:\s+{_GAME_WORD})?{_PLACE}"
_GENERIC = rf"(?P<generic>{_GAME_WORD}|telecast|broadcast)"
_DAY = r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
_PREFIX = (
    rf"(?:(?:The|This|Last)\s+)?(?:(?:{_DAY}(?:\s+night)?|Week\s+\d+|Last\s+night)[\u2019']s\s+)?"
    r"(?:(?:the|The)\s+)?"
)
_VERB = rf"\s+(?:averaged|drew)\s+(?:[a-z]+\s+){{0,4}}?(?P<fig>{_FIG})\s+(?:total\s+)?viewers\b"
_GAME_SUBJECT_RE = re.compile(
    rf"^{_PREFIX}(?:{_POSS}|{_PAIR}|{_VS}|{_GENERIC}){_VERB}(?P<tail>.*)$", re.DOTALL
)
_NET = r"[A-Z][A-Za-z0-9+]*(?:\s+[A-Z0-9][A-Za-z0-9+]*){0,2}"
_NETWORK_SUBJECT_RE = re.compile(
    rf"^(?P<net>{_NET})\s+(?:averaged|drew)\s+(?:[a-z]+\s+){{0,4}}?(?P<fig>{_FIG})\s+viewers"
    rf"\s+for\s+(?:the\s+)?(?:{_PAIR}|{_VS}|{_GENERIC})(?P<tail>.*)$",
    re.DOTALL,
)
_ROUNDUP_RE = re.compile(
    rf"^(?:{_PAIR}|{_VS})\s*\((?P<net>[^()]{{1,40}})\):?\s*(?P<fig>{_FIG})(?:\s+viewers)?\.?$"
)
_HEADLINE_GAME_RE = re.compile(rf"(?:{_POSS}|{_PAIR}|{_VS})")
_TAIL_NETWORK_RE = re.compile(
    rf"\b(?:on|across)\s+(?P<nets>{_NET}(?:\s*(?:,|\band\b|&|/|\s\+\s)\s*{_NET})*)"
)
_NETWORK_JOIN_RE = re.compile(r"\s*,\s*|\s+and\s+|\s*/\s*|\s+\+\s+|\s*&\s*")
_CLAUSE_END_RE = re.compile(r"[,;:(\u2014\u2013]|\s-\s|\bwhich\b|\bwhile\b|\bmarking\b|\bmaking\b")
_NOT_NETWORK_RE = re.compile(
    rf"^(?:{_DAY}|January|February|March|April|May|June|July|August|September|October"
    r"|November|December|Labor|Black|Thanksgiving|Christmas|New|Week|Championship)\b"
)
_HYPHEN_RE = re.compile(r"\s*[-\u2013]\s*")
_PEAK_RE = re.compile(r"\bpeak", re.IGNORECASE)
_STREAM_WORDS_RE = re.compile(r"stream|\bunique\b|\bonline\b|\bdigital\b", re.IGNORECASE)
_WINDOW_RE = re.compile(
    r"\b(?:combined|doubleheader|tripleheader|window|slate|both\s+games|all\s+games)\b",
    re.IGNORECASE,
)
_OTHER_SEASON_RE = re.compile(
    r"\b(?:last|previous|prior)\s+(?:year|season)\b|\ba\s+year\s+ago\b", re.IGNORECASE
)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_WEEKDAY_RE = re.compile(rf"\b({'|'.join(_WEEKDAYS)})\b", re.IGNORECASE)
_LAST_NIGHT_RE = re.compile(r"\blast\s+night\b", re.IGNORECASE)
_ABBREVIATIONS = frozenset({"no.", "vs.", "v.", "st.", "jr.", "sr.", "mr.", "dr.", "ft.", "mt."})
_SINGLE_LETTER_ABBR_RE = re.compile(r"^(?:[A-Za-z]\.)+$")
_SENTENCE_END_RE = re.compile(r"[.!?][\"\u201d\u2019)]*\s+(?=[A-Z0-9\"\u201c\u2018(])")
_LEADING_THE_RE = re.compile(r"^(?:the|The)\s+")
_BLOCK_TAGS = frozenset({"p", "li", "h2", "h3", "h4"})
_SKIP_TAGS = frozenset({"script", "style", "noscript"})


class AaParseError(ValueError):
    """A post that can't be parsed safely; the message is count-only."""


def parse_aa_viewers(printed: str) -> int | None:
    """AA's unit rule: "5.2 million" / "5.2M" -> 5,200,000; "922,000" -> 922,000."""
    text = " ".join(printed.split())
    match = _MILLION_RE.match(text)
    if match is not None:
        return round(float(match.group(1)) * 1_000_000)
    if _COMMA_INT_RE.match(text):
        return int(text.replace(",", ""))
    return None


def post_slug(url: str) -> str:
    """The URL's last path segment without ``.html``, as the collector caches it."""
    leaf = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".html")
    return safe_slug(leaf)


def _classes(attrs: dict[str, str | None]) -> set[str]:
    return set((attrs.get("class") or "").split())


@dataclass
class _Block:
    text: str
    quoted: bool


class _PostParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonical: str | None = None
        self.og_url: str | None = None
        self.ld_blobs: list[str] = []
        self.blocks: list[_Block] = []
        self._ld: list[str] | None = None
        self._skip = 0
        self._body_depth = 0
        self._body_done = False
        self._quote = 0
        self._block: list[str] | None = None
        self._block_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "link" and (attr.get("rel") or "").lower() == "canonical":
            self.canonical = self.canonical or attr.get("href")
        elif tag == "meta" and attr.get("property") == "og:url":
            self.og_url = self.og_url or attr.get("content")
        if tag == "script" and (attr.get("type") or "").lower() == "application/ld+json":
            self._ld = []
            return
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if tag == "div":
            if self._body_depth:
                self._body_depth += 1
            elif not self._body_done and "entry-content" in _classes(attr):
                self._body_depth = 1
            return
        if not self._body_depth:
            return
        if tag == "blockquote":
            self._quote += 1
        elif tag in _BLOCK_TAGS and self._block is None:
            self._block, self._block_tag = [], tag
        elif tag == "br" and self._block is not None:
            self._block.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._ld is not None:
            self.ld_blobs.append("".join(self._ld))
            self._ld = None
            return
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if tag == "div" and self._body_depth:
            self._body_depth -= 1
            if not self._body_depth:
                self._body_done = True
            return
        if not self._body_depth:
            return
        if tag == "blockquote":
            self._quote = max(0, self._quote - 1)
        elif tag == self._block_tag and self._block is not None:
            text = " ".join("".join(self._block).split())
            if text:
                self.blocks.append(_Block(text=text, quoted=self._quote > 0))
            self._block = self._block_tag = None

    def handle_data(self, data: str) -> None:
        if self._ld is not None:
            self._ld.append(data)
        elif self._skip:
            return
        elif self._block is not None:
            self._block.append(data)


def post_url_from_html(html: str) -> str | None:
    """The post's canonical URL (``link rel=canonical``, else ``og:url``)."""
    parser = _PostParser()
    parser.feed(html)
    parser.close()
    return parser.canonical or parser.og_url


def _walk(node: Any) -> list[dict[str, Any]]:
    if isinstance(node, dict):
        found = [node]
        for value in node.values():
            found.extend(_walk(value))
        return found
    if isinstance(node, list):
        return [item for value in node for item in _walk(value)]
    return []


def _ld_fields(blobs: list[str]) -> tuple[str, date | None]:
    """(headline, post date in ET) from the ld+json blocks; an Article wins."""
    objects: list[dict[str, Any]] = []
    for blob in blobs:
        try:
            objects.extend(_walk(json.loads(blob)))
        except ValueError:
            continue
    objects.sort(key=lambda obj: 0 if "Article" in str(obj.get("@type", "")) else 1)
    headline = next(
        (obj["headline"] for obj in objects if isinstance(obj.get("headline"), str)), ""
    )
    posted: date | None = None
    for obj in objects:
        stamp = obj.get("datePublished")
        if not isinstance(stamp, str):
            continue
        try:
            moment = datetime.fromisoformat(stamp.strip())
        except ValueError:
            continue
        if moment.tzinfo is None:
            continue
        posted = moment.astimezone(_ET).date()
        break
    return " ".join(html_lib.unescape(headline).split()), posted


def _sentences(text: str) -> list[str]:
    out: list[str] = []
    start = 0
    for match in _SENTENCE_END_RE.finditer(text):
        head = text[start : match.start() + 1]
        last = head.rsplit(None, 1)[-1] if head.strip() else ""
        if last.lower() in _ABBREVIATIONS or _SINGLE_LETTER_ABBR_RE.match(last):
            continue
        out.append(text[start : match.end()].strip())
        start = match.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def _ignored_mention(sentence: str, start: int, end: int) -> bool:
    """A peak or a streaming-only number next to the mention."""
    before = " ".join(sentence[:start].split()[-6:])
    after = " ".join(sentence[end:].split()[:5])
    if _PEAK_RE.search(before) or _PEAK_RE.search(" ".join(after.split()[:3])):
        return True
    return bool(_STREAM_WORDS_RE.search(before) or _STREAM_WORDS_RE.search(after))


def _clean_team(text: str) -> str:
    return _LEADING_THE_RE.sub("", " ".join(text.split())).strip()


def _split_pair(pair: str) -> tuple[str, str] | None:
    parts = _HYPHEN_RE.split(pair)
    if len(parts) != 2:
        return None
    return _clean_team(parts[0]), _clean_team(parts[1])


def _teams(match: re.Match[str]) -> tuple[str, str] | None:
    groups = match.groupdict()
    if groups.get("pa") and groups.get("pb"):
        return _clean_team(groups["pa"]), _clean_team(groups["pb"])
    if groups.get("va") and groups.get("vb"):
        return _clean_team(groups["va"]), _clean_team(groups["vb"])
    if groups.get("pair"):
        return _split_pair(groups["pair"])
    return None


def _headline_game(headline: str) -> tuple[str, str] | None:
    matches = list(_HEADLINE_GAME_RE.finditer(headline))
    if len(matches) != 1:
        return None
    return _teams(matches[0])


def _trim_network(text: str) -> str:
    """Drop a trailing day, month or time word the name capture ran into
    ("NBC Friday" -> "NBC")."""
    words = text.split()
    for index, word in enumerate(words):
        if _NOT_NETWORK_RE.match(word) or word in ("ET", "PM", "AM"):
            words = words[:index]
            break
    return " ".join(words)


def _network_from(tail: str) -> str:
    clause = _CLAUSE_END_RE.split(tail, maxsplit=1)[0]
    for match in _TAIL_NETWORK_RE.finditer(clause):
        nets = match.group("nets")
        if _NOT_NETWORK_RE.match(nets):
            continue
        parts = [_trim_network(part) for part in _NETWORK_JOIN_RE.split(nets) if part]
        if not all(parts):
            return ""
        return " & ".join(parts)
    return ""


@dataclass(frozen=True)
class _Reading:
    away: str
    home: str
    network: str
    figure: str


def _read_sentence(
    sentence: str, headline_game: tuple[str, str] | None, season: int
) -> _Reading | None:
    """The one game figure a sentence states, or None when it isn't unambiguous.

    The other-season and multi-game checks read the subject and the figure's own
    clause only, so a trailing comparison ("..., the best window since 2015")
    doesn't disqualify a figure the subject already pins to one game."""
    text = sentence.strip().strip('"\u201c\u201d')
    for pattern, network_group in (
        (_GAME_SUBJECT_RE, None),
        (_NETWORK_SUBJECT_RE, "net"),
        (_ROUNDUP_RE, "net"),
    ):
        match = pattern.match(text)
        if match is None:
            continue
        tail = match.groupdict().get("tail") or ""
        clause = _CLAUSE_END_RE.split(tail, maxsplit=1)[0]
        head = f"{text[: match.end('fig')]} {clause}"
        if _WINDOW_RE.search(head) or _OTHER_SEASON_RE.search(head):
            return None
        if any(int(y) not in (season, season + 1) for y in _YEAR_RE.findall(head)):
            return None
        teams = _teams(match)
        if teams is None and match.groupdict().get("generic"):
            teams = headline_game
        if teams is None or not all(teams):
            return None
        if network_group is not None:
            network = " ".join(match.group(network_group).split())
        else:
            network = _network_from(tail)
        return _Reading(away=teams[0], home=teams[1], network=network, figure=match.group("fig"))
    return None


def _game_date(sentence: str, posted: date | None) -> date | None:
    if posted is None:
        return None
    if _LAST_NIGHT_RE.search(sentence):
        return posted - timedelta(days=1)
    match = _WEEKDAY_RE.search(sentence)
    weekday = _WEEKDAYS.index(match.group(1).lower()) if match else 5  # Saturday
    back = (posted.weekday() - weekday) % 7 or 7
    return posted - timedelta(days=back)


def parse_post(html: str, *, url: str, season: int) -> ParsedPost:
    """Every figure mention of one cached AA post (see module docstring)."""
    if not host_matches("aa", url):
        raise AaParseError("aa post URL is not https on the source's host")
    slug = post_slug(url)
    parser = _PostParser()
    parser.feed(html)
    parser.close()
    headline, posted = _ld_fields(parser.ld_blobs)
    headline_game = _headline_game(headline)
    rank = posted.toordinal() if posted is not None else 0

    rows: list[SecondSourceRow] = []
    ignored = 0
    line = 0
    for block in parser.blocks:
        if block.quoted:
            ignored += len(_FIG_RE.findall(block.text))
            continue
        for sentence in _sentences(block.text):
            mentions = list(_FIG_RE.finditer(sentence))
            if not mentions:
                continue
            kept: list[tuple[int, re.Match[str]]] = []
            for mention in mentions:
                line += 1
                if _ignored_mention(sentence, mention.start(), mention.end()):
                    ignored += 1
                else:
                    kept.append((line, mention))
            if not kept:
                continue
            reading = _read_sentence(sentence, headline_game, season) if len(kept) == 1 else None
            day = _game_date(sentence, posted)
            for mention_line, _mention in kept:
                kind: RowKind
                if reading is None:
                    kind, away, home, network, viewers = "needs_review", "", "", "", None
                else:
                    away, home, network = reading.away, reading.home, reading.network
                    kind = classify_row(
                        {
                            "network": network,
                            "away": away,
                            "home": home,
                            "viewers": reading.figure,
                        },
                        parse=parse_aa_viewers,
                    )
                    viewers = parse_aa_viewers(reading.figure) if kind == "figure" else None
                rows.append(
                    SecondSourceRow(
                        source="aa",
                        season=season,
                        pointer=f"{slug}:{mention_line}",
                        date_et=day,
                        away_raw=away,
                        home_raw=home,
                        network_raw=network,
                        viewers=viewers,
                        kind=kind,
                        chart_kind="post",
                        rank=rank,
                        source_url=url,
                        superseded=False,
                    )
                )
    return ParsedPost(rows=rows, ignored=ignored)
