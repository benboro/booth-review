"""ESPN Press Room page parser: booths (04.19 D-13) and viewership (D-12).

Pages come only from `booth-review import espnpr` (hand-saved; nothing here
fetches, renders or executes anything). The structure was recorded from saved
pages in 04.19-37. Text is read from the post body (``div.brxe-post-content``)
and, after it, any ``div.release__table-container`` section (the 2026 release
template moved the schedule table there; the 2024 pages leave it empty) with
the stdlib HTML parser; entities are unescaped, U+00A0 is a space and
whitespace is collapsed.

**Booths** (commentators page and weekly release): only the schedule table is
read (first row ``Date | Time (ET) | Game/Commentators | Where to Watch`` or
``... | Platform``), never the prose or bullet lists that repeat the crews.

- The date (``Ddd, Mon D``) is printed on a day's first game only and carried
  down; the year is the season's (January to June belong to season + 1).
- The matchup is the text before the first ``<br>`` of the Game/Commentators
  cell: ``<away> at <home>`` (``vs.`` at a neutral site), each side with an
  optional ``No. N`` / ``T-No. N`` / ``#N`` rank prefix, and a trailing ``*``
  footnote mark. A leading event name ending in ``:`` or a spaced dash is
  dropped, so it never reaches the team fields. These are structural rules for
  this source, never a per-team fix.
- Each later ``<br>`` line is a crew: names separated by ``, ``, printed order
  kept (no role labels on the page). ``TV:`` lines are the TV crew; ``Radio:``
  and any other labeled line are dropped. A row whose networks are all radio
  (``ESPN Radio`` alone) carries a radio crew and never becomes a TV booth.
- Networks may be ``/``-joined and wrap with a trailing ``/`` before a
  ``<br>``; the lines are joined before anything splits them.
- A row with no crew, more than one unlabeled crew line, a crew that isn't 2-4
  names, or no date is skipped and counted.

Pointers are ``<page-key>:<line>``: ``wk-<N>`` for the commentators page (its
``WEEK N`` heading) or the release slug, and the row's 1-based position below
the table's header row.

**Viewership** (ratings release) -> `SecondSourceRow` (source espnpr, chart
kind post). Every figure the page prints gets a line number in document
order: each data row of a viewers table, each bullet item and each prose
figure mention. The pointer is ``<slug>:<line>``.

- Viewers table (``Rank | Window | Matchup | P2+ Viewers``): the matchup is
  ``Mon. D: <team> at|vs. <team>`` and the figure ``N.N Million``. The table has
  no network column; the network is the one network the paragraph above it
  names. A paragraph that names none, several, or a family ("ESPN networks")
  leaves it blank, which the matcher sends to review.
- Bullet items ``<team> vs.|at <team>: N.N million`` take their network from
  the lead-in paragraph only when it names exactly one network and no scope
  ("cable networks", "across", "platforms"); otherwise blank, to review.
- Prose is read sentence by sentence with Awful Announcing's rules (one figure
  tied to one named game, never a window average, a peak or a stream count);
  everything else is ``needs_review`` and never loads. A sentence that names a
  MegaCast is ``multi_feed``; several networks ("across ABC and ESPN2") make a
  ``simulcast``; both are excluded like SMW's. A prose or bullet figure in
  whole millions ("5 million") is too coarse for the 3% gate (D-12 relies on
  0.1M rounding) and goes to ``needs_review``.
- Units: ``N.N million`` / ``N.NM`` -> N.N * 1e6, ``NK`` / ``N thousand`` ->
  N * 1e3, comma integers as printed; any other text after a number is
  ``unknown_suffix`` (review), and a cell with no digit is ``no_figure``.
- Dates: table rows carry their own; bullets and prose take the weekday a
  sentence names (else Saturday) before the published date, like AA, and the
  matcher allows a day either way. Rank is the published date's ordinal times
  ten plus a tier (table 2, bullet 1, prose 0), so a later release wins a
  duplicate and, within one release, the table wins over the same game's
  bullet or prose figure.

Errors are count-only (`EspnPrParseError`); messages never carry page text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from booth_review.sources.aa.parser import (
    _FIG_RE,
    _game_date,
    _ignored_mention,
    _read_sentence,
    _sentences,
)
from booth_review.sources.espnpr.importer import EspnPrPage, identify_page
from booth_review.sources.second_rows import (
    ParsedPost,
    RowKind,
    SecondSourceRow,
    host_matches,
)
from booth_review.sources.smw.rows import classify_row

_ET = ZoneInfo("America/New_York")

# A season's games from January to June belong to the season that began the
# previous August (bowls and the CFP final).
_SEASON_START_MONTH = 7
_MONTHS = {
    name: number
    for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}

_BLOCK_TAGS = frozenset({"p", "li", "h1", "h2", "h3", "h4", "h5", "h6"})
_LIST_TAGS = frozenset({"ul", "ol"})
_SKIP_TAGS = frozenset({"script", "style", "noscript", "template"})
_BOLD_TAGS = frozenset({"strong", "b"})
_CONTENT_CLASS = "brxe-post-content"
# The 2026 release template's own section for the schedule table, after the post body.
_TABLE_CONTAINER_CLASS = "release__table-container"

# -- matchups and crews --
_ROW_DATE_RE = re.compile(
    r"^(?:[A-Za-z]{3,9}\.?,?\s+)?(?P<mon>[A-Za-z]{3,9})\.?\s+(?P<day>\d{1,2})\b"
)
_RANK_PREFIX_RE = re.compile(r"^(?:(?:T-)?No\.\s*\d{1,2}|#\d{1,2})\s+", re.IGNORECASE)
# A neutral-site location printed after the matchup, "(City, Region)". A school's
# own parenthetical ("Miami (Ohio)", "(Pa.)") has no comma, so it never matches.
_LOCATION_RE = re.compile(r"\s*\([^()]*,[^()]*\)$")
_EVENT_PREFIX_RE = re.compile(r"^[^:]{1,80}?(?::|\s[\u2013\u2014-])\s+(?=\S)")
_AT_RE = re.compile(r"\s+at\s+")
_VS_RE = re.compile(r"\s+vs\.?\s+", re.IGNORECASE)
_LABEL_RE = re.compile(r"^(?P<label>[A-Za-z][A-Za-z0-9 +&.'-]{0,30}?)\s*:\s*(?P<rest>.*)$")
_NAME_RE = re.compile(r"^[^\W\d_][^\d,:;()/]*$")
_MIN_CREW, _MAX_CREW = 2, 4

# -- viewership --
_TABLE_MATCHUP_RE = re.compile(r"^(?P<mon>[A-Za-z]{3,5})\.?\s+(?P<day>\d{1,2})\s*:\s*(?P<game>.+)$")
_TABLE_GAME_SEP_RE = re.compile(r"\s+(?:at|vs\.?)\s+", re.IGNORECASE)
_BULLET_FIG = r"\d{1,3}(?:\.\d{1,3})?\s*(?:million\b|M\b)|\d{1,3}(?:,\d{3})+(?![\d,])"
_BULLET_RE = re.compile(
    rf"^(?P<a>[^:]{{1,60}}?)\s+(?:vs\.?|at)\s+(?P<b>[^:]{{1,60}}?)\s*:\s*(?P<fig>{_BULLET_FIG})\.?$",
    re.IGNORECASE,
)
_VIEWERS_RE = re.compile(
    r"^(?P<n>\d{1,3}(?:\.\d{1,3})?)\s*(?P<unit>million|m|thousand|k)$", re.IGNORECASE
)
_COMMA_INT_RE = re.compile(r"^\d{1,3}(?:,\d{3})+$")
_WHOLE_MILLION_RE = re.compile(r"^\d{1,3}\s*(?:million|m)$", re.IGNORECASE)
_MEGACAST_RE = re.compile(r"mega\s*cast", re.IGNORECASE)
_NETWORK_NAME = (
    r"SEC\s+Network\+?|ACC\s+Network(?:\s+Extra)?|Longhorn\s+Network|ESPN\s+Deportes"
    r"|ESPNews|ESPNU|ESPN2|ESPN\+|ESPN|ABC"
)
_NETWORK_RE = re.compile(rf"(?<![\w+])(?:{_NETWORK_NAME})(?![\w+])")
# "ESPN networks", "ESPN platforms": a family of networks, never one.
_FAMILY_RE = re.compile(
    rf"(?:{_NETWORK_NAME})(?:[\u2019']s)?\s+(?:networks|platforms|family)\b", re.IGNORECASE
)
_SHARED_RE = re.compile(r"\b(?:combined|simulcast\w*|megacast\w*)\b", re.IGNORECASE)
_SCOPE_RE = re.compile(r"\b(?:networks|cable|platforms|across)\b", re.IGNORECASE)

_TIER_TABLE, _TIER_BULLET, _TIER_PROSE = 2, 1, 0


class EspnPrParseError(ValueError):
    """A page that can't be parsed safely; the message is count-only."""


@dataclass(frozen=True)
class EspnPrBooth:
    """One TV booth from a schedule table row (names in printed order)."""

    season: int
    date_et: date
    kickoff: str | None
    away_raw: str
    home_raw: str
    network_raw: str
    tv_names: tuple[str, ...]
    source_url: str
    pointer: str


@dataclass(frozen=True)
class ParsedBooths:
    """A page's booths; `skipped` counts schedule rows that gave no TV booth
    (radio crews included), `radio_dropped` the radio crews among them."""

    booths: list[EspnPrBooth]
    skipped: int
    radio_dropped: int = 0


# A ratings release parses to the same shape as a TVRG or AA post.
ParsedViewership = ParsedPost


# -- HTML walk ---------------------------------------------------------------------------


@dataclass
class _Text:
    tag: str
    text: str
    bold: bool


@dataclass
class _Table:
    # row -> cell -> the cell's lines (split at <br>, each cleaned)
    rows: list[list[list[str]]] = field(default_factory=list)


def _clean(text: str) -> str:
    return " ".join(text.replace("\u00a0", " ").split())


class _ContentParser(HTMLParser):
    """The first post body's text blocks and tables, then any release table
    container's, in document order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[_Text | _Table] = []
        self._depth = 0
        self._done = False
        self._skip = 0
        self._bold = 0
        self._block: list[str] | None = None
        self._block_tag = ""
        self._bold_chars = 0
        self._plain_chars = 0
        self._table: _Table | None = None
        self._row: list[list[str]] | None = None
        self._cell: list[str] | None = None

    # block helpers
    def _flush(self) -> None:
        if self._block is None:
            return
        text = _clean("".join(self._block))
        if text:
            bold = self._bold_chars > 0 and self._plain_chars == 0
            self.blocks.append(_Text(tag=self._block_tag, text=text, bold=bold))
        self._block = None
        self._block_tag = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if tag == "div":
            if self._depth:
                self._depth += 1
            else:
                classes = (dict(attrs).get("class") or "").split()
                if (_CONTENT_CLASS in classes and not self._done) or (
                    _TABLE_CONTAINER_CLASS in classes
                ):
                    self._depth = 1
            return
        if not self._depth:
            return
        if tag in _BOLD_TAGS:
            self._bold += 1
        elif tag == "table":
            self._flush()
            self._table = _Table()
        elif self._table is not None:
            if tag == "tr":
                self._row = []
            elif tag in ("td", "th") and self._row is not None:
                self._cell = []
            elif tag == "br" and self._cell is not None:
                self._cell.append("\n")
        elif tag in _BLOCK_TAGS:
            self._flush()
            self._block, self._block_tag = [], tag
            self._bold_chars = self._plain_chars = 0
        elif tag in _LIST_TAGS:
            self._flush()
        elif tag == "br" and self._block is not None:
            self._block.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if tag == "div" and self._depth:
            self._depth -= 1
            if not self._depth:
                self._flush()
                self._done = True
            return
        if not self._depth:
            return
        if tag in _BOLD_TAGS:
            self._bold = max(0, self._bold - 1)
        elif self._table is not None:
            if tag in ("td", "th") and self._cell is not None and self._row is not None:
                self._row.append([_clean(line) for line in "".join(self._cell).split("\n")])
                self._cell = None
            elif tag == "tr" and self._row is not None:
                self._table.rows.append(self._row)
                self._row = None
            elif tag == "table":
                self.blocks.append(self._table)
                self._table = None
        elif tag in _BLOCK_TAGS and tag == self._block_tag:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip or not self._depth:
            return
        if self._cell is not None:
            self._cell.append(data)
        elif self._block is not None:
            self._block.append(data)
            visible = len("".join(data.replace("\u00a0", " ").split()))
            if self._bold:
                self._bold_chars += visible
            else:
                self._plain_chars += visible


def _content_blocks(html: str) -> list[_Text | _Table]:
    parser = _ContentParser()
    parser.feed(html)
    parser.close()
    parser._flush()
    return parser.blocks


def _cell_text(cell: list[str]) -> str:
    return _clean(" ".join(cell))


def _page(html: str, url: str) -> EspnPrPage:
    if not host_matches("espnpr", url):
        raise EspnPrParseError("espnpr page URL is not https on the source's host")
    page = identify_page(html)
    if page is None:
        raise EspnPrParseError("espnpr page is not an identifiable data page")
    return page


# -- shared text rules ---------------------------------------------------------------------


def _season_date(month_text: str, day_text: str, season: int) -> date | None:
    month = _MONTHS.get(month_text[:3].lower())
    if month is None:
        return None
    year = season + 1 if month < _SEASON_START_MONTH else season
    try:
        return date(year, month, int(day_text))
    except ValueError:
        return None


def _team(text: str) -> str:
    team = _RANK_PREFIX_RE.sub("", text.strip())
    return team.rstrip("*\u2020 ").strip()


def _split_game(text: str) -> tuple[str, str] | None:
    """(away, home) from ``<away> at <home>`` (or ``vs.``), event prefix, a
    trailing ``(City, Region)`` location and rank marks stripped; None when the
    text doesn't split into exactly two teams."""
    game = text.strip().rstrip("*\u2020 ").strip()
    game = _LOCATION_RE.sub("", game).rstrip("*\u2020 ").strip()
    for candidate in (_EVENT_PREFIX_RE.sub("", game, count=1), game):
        for separator in (_AT_RE, _VS_RE):
            parts = separator.split(candidate)
            if len(parts) == 2:
                away, home = _team(parts[0]), _team(parts[1])
                if away and home:
                    return away, home
    return None


def parse_espnpr_viewers(printed: str) -> int | None:
    """ESPN PR's unit rule: "5.2 million" / "5.2M" -> 5,200,000; "904K" ->
    904,000; "5,200,000" as printed; anything else -> None."""
    text = _clean(printed).rstrip(".")
    match = _VIEWERS_RE.match(text)
    if match is not None:
        unit = match.group("unit").lower()
        scale = 1_000_000 if unit in ("million", "m") else 1_000
        return round(float(match.group("n")) * scale)
    if _COMMA_INT_RE.match(text):
        return int(text.replace(",", ""))
    return None


def _context_network(text: str | None, *, ranking_scope_ok: bool) -> str:
    """The one network a heading or lead-in names, or "" when it names none,
    several, a family ("ESPN networks") or a shared total. With
    `ranking_scope_ok` a ranking scope ("across all networks") is allowed."""
    if not text:
        return ""
    names = {" ".join(m.group(0).split()) for m in _NETWORK_RE.finditer(text)}
    if len(names) != 1 or _FAMILY_RE.search(text) or _SHARED_RE.search(text):
        return ""
    if not ranking_scope_ok and _SCOPE_RE.search(text):
        return ""
    return names.pop()


# -- booths ----------------------------------------------------------------------------------


def _is_schedule_header(row: list[list[str]]) -> bool:
    cells = [_cell_text(cell).lower() for cell in row]
    return len(cells) >= 4 and cells[0] == "date" and cells[1].startswith("time")


def _join_networks(lines: list[str]) -> str:
    joined = ""
    for line in lines:
        if not line:
            continue
        if not joined:
            joined = line
        elif joined.endswith("/") or line.startswith("/"):
            joined += line
        else:
            joined += "/" + line
    return joined.strip(" /")


def _matchup(lines: list[str]) -> tuple[tuple[str, str] | None, list[str]]:
    """((away, home), the crew lines after it). The matchup is the first line;
    a neutral-site event row wraps it over two (an event heading, or a break
    mid-game), so when the first line alone isn't a game the first two joined
    are tried."""
    if not lines:
        return None, []
    teams = _split_game(lines[0])
    if teams is None and len(lines) > 1:
        joined = _split_game(f"{lines[0]} {lines[1]}")
        if joined is not None:
            return joined, lines[2:]
    return teams, lines[1:]


def _tv_crew(lines: list[str]) -> tuple[str | None, int]:
    """(the one TV crew line, radio lines dropped). A ``TV:`` line wins;
    otherwise the one unlabeled line. Labeled non-TV lines are dropped."""
    tv: list[str] = []
    plain: list[str] = []
    radio = 0
    for line in lines:
        match = _LABEL_RE.match(line)
        if match is None:
            plain.append(line)
            continue
        label = match.group("label").strip().lower()
        if label == "tv":
            tv.append(match.group("rest").strip())
        elif "radio" in label:
            radio += 1
    candidates = tv or plain
    return (candidates[0] if len(candidates) == 1 else None), radio


def _names(line: str) -> tuple[str, ...] | None:
    names = tuple(_clean(name) for name in line.split(",") if _clean(name))
    if not _MIN_CREW <= len(names) <= _MAX_CREW:
        return None
    if not all(_NAME_RE.match(name) for name in names):
        return None
    return names


def parse_booths(html: str, *, url: str, season: int) -> ParsedBooths:
    """Every TV booth in a commentators page's or weekly release's schedule
    table (see module docstring)."""
    page = _page(html, url)
    if page.kind == "commentators":
        key = f"wk-{page.key}"
    elif page.kind == "release":
        key = page.key
    else:
        raise EspnPrParseError("espnpr page has no schedule table")
    table = next(
        (
            block
            for block in _content_blocks(html)
            if isinstance(block, _Table) and block.rows and _is_schedule_header(block.rows[0])
        ),
        None,
    )
    if table is None:
        return ParsedBooths(booths=[], skipped=0)

    booths: list[EspnPrBooth] = []
    skipped = radio_dropped = 0
    current: date | None = None
    for line, cells in enumerate(table.rows[1:], start=1):
        if len(cells) < 4:
            skipped += 1
            continue
        date_text = _cell_text(cells[0])
        if date_text:
            match = _ROW_DATE_RE.match(date_text)
            current = (
                _season_date(match.group("mon"), match.group("day"), season) if match else None
            )
        game_lines = [text for text in cells[2] if text]
        network = _join_networks(cells[3])
        outlets = [part.strip() for part in network.split("/") if part.strip()]
        if outlets and all("radio" in part.lower() for part in outlets):
            # A radio-only row carries the radio crew; the TV booth is elsewhere.
            skipped += 1
            radio_dropped += 1 if len(game_lines) > 1 else 0
            continue
        teams, crew_lines = _matchup(game_lines)
        crew_line, radio = _tv_crew(crew_lines)
        radio_dropped += radio
        names = _names(crew_line) if crew_line is not None else None
        if current is None or teams is None or names is None:
            skipped += 1
            continue
        kickoff = _cell_text(cells[1]) or None
        booths.append(
            EspnPrBooth(
                season=season,
                date_et=current,
                kickoff=kickoff,
                away_raw=teams[0],
                home_raw=teams[1],
                network_raw=network,
                tv_names=names,
                source_url=url,
                pointer=f"{key}:{line}",
            )
        )
    return ParsedBooths(booths=booths, skipped=skipped, radio_dropped=radio_dropped)


# -- viewership ------------------------------------------------------------------------------


def viewership_url_from_html(html: str) -> str | None:
    """A ratings release's canonical URL, or None for any other page."""
    page = identify_page(html)
    if page is None or page.kind != "ratings":
        return None
    return page.canonical_url


def _viewer_columns(header: list[list[str]]) -> tuple[int, int] | None:
    cells = [_cell_text(cell).lower() for cell in header]
    matchup = next((i for i, cell in enumerate(cells) if cell == "matchup"), None)
    viewers = next((i for i, cell in enumerate(cells) if cell.endswith("viewers")), None)
    if matchup is None or viewers is None:
        return None
    return matchup, viewers


@dataclass
class _Rows:
    season: int
    slug: str
    url: str
    published: date | None
    rows: list[SecondSourceRow] = field(default_factory=list)
    line: int = 0

    def add(
        self,
        *,
        kind: RowKind,
        tier: int,
        day: date | None,
        away: str = "",
        home: str = "",
        network: str = "",
        viewers: int | None = None,
        line: int | None = None,
    ) -> None:
        base = self.published.toordinal() * 10 if self.published is not None else 0
        self.rows.append(
            SecondSourceRow(
                source="espnpr",
                season=self.season,
                pointer=f"{self.slug}:{self.line if line is None else line}",
                date_et=day,
                away_raw=away,
                home_raw=home,
                network_raw=network,
                viewers=viewers if kind == "figure" else None,
                kind=kind,
                chart_kind="post",
                rank=base + tier,
                source_url=self.url,
                superseded=False,
            )
        )


def _classify(network: str, away: str, home: str, figure: str) -> RowKind:
    return classify_row(
        {"network": network, "away": away, "home": home, "viewers": figure},
        parse=parse_espnpr_viewers,
    )


def _table_rows(table: _Table, heading: str | None, out: _Rows) -> None:
    columns = _viewer_columns(table.rows[0])
    if columns is None:
        return
    matchup_col, viewers_col = columns
    network = _context_network(heading, ranking_scope_ok=True)
    for cells in table.rows[1:]:
        if not any(_cell_text(cell) for cell in cells):
            continue
        out.line += 1
        matchup = _cell_text(cells[matchup_col]) if matchup_col < len(cells) else ""
        figure = _cell_text(cells[viewers_col]) if viewers_col < len(cells) else ""
        match = _TABLE_MATCHUP_RE.match(matchup)
        day = _season_date(match.group("mon"), match.group("day"), out.season) if match else None
        parts = _TABLE_GAME_SEP_RE.split(match.group("game")) if match else []
        if day is None or len(parts) != 2:
            out.add(kind="needs_review", tier=_TIER_TABLE, day=day)
            continue
        away, home = _team(parts[0]), _team(parts[1])
        kind = _classify(network, away, home, figure)
        out.add(
            kind=kind,
            tier=_TIER_TABLE,
            day=day,
            away=away,
            home=home,
            network=network,
            viewers=parse_espnpr_viewers(figure),
        )


def _bullet_row(text: str, lead_in: str | None, out: _Rows) -> bool:
    match = _BULLET_RE.match(text)
    if match is None:
        return False
    out.line += 1
    day = _game_date(text, out.published)
    figure = match.group("fig")
    away, home = _team(match.group("a")), _team(match.group("b"))
    if _WHOLE_MILLION_RE.match(_clean(figure)):
        out.add(kind="needs_review", tier=_TIER_BULLET, day=day)
        return True
    network = _context_network(lead_in, ranking_scope_ok=False)
    kind = _classify(network, away, home, figure)
    out.add(
        kind=kind,
        tier=_TIER_BULLET,
        day=day,
        away=away,
        home=home,
        network=network,
        viewers=parse_espnpr_viewers(figure),
    )
    return True


def _prose_rows(text: str, out: _Rows) -> int:
    """Rows for every figure mention in a prose block; returns mentions ignored."""
    ignored = 0
    for sentence in _sentences(text):
        mentions = list(_FIG_RE.finditer(sentence))
        if not mentions:
            continue
        kept: list[int] = []
        for mention in mentions:
            out.line += 1
            if _ignored_mention(sentence, mention.start(), mention.end()):
                ignored += 1
            else:
                kept.append(out.line)
        if not kept:
            continue
        day = _game_date(sentence, out.published)
        megacast = bool(_MEGACAST_RE.search(sentence))
        reading = _read_sentence(sentence, None, out.season) if len(kept) == 1 else None
        for line in kept:
            if megacast:
                out.add(kind="multi_feed", tier=_TIER_PROSE, day=day, line=line)
            elif reading is None:
                out.add(kind="needs_review", tier=_TIER_PROSE, day=day, line=line)
            else:
                kind = _classify(reading.network, reading.away, reading.home, reading.figure)
                if kind == "figure" and _WHOLE_MILLION_RE.match(_clean(reading.figure)):
                    kind = "needs_review"
                out.add(
                    kind=kind,
                    tier=_TIER_PROSE,
                    day=day,
                    away=reading.away if kind != "needs_review" else "",
                    home=reading.home if kind != "needs_review" else "",
                    network=reading.network if kind != "needs_review" else "",
                    viewers=parse_espnpr_viewers(reading.figure),
                    line=line,
                )
    return ignored


def parse_viewership(html: str, *, url: str, season: int) -> ParsedViewership:
    """Every figure a ratings release prints (see module docstring)."""
    page = _page(html, url)
    if page.kind != "ratings":
        raise EspnPrParseError("espnpr page is not a ratings release")
    published = page.published.astimezone(_ET).date() if page.published is not None else None
    out = _Rows(season=season, slug=page.key, url=url, published=published)
    ignored = 0
    last_paragraph: str | None = None
    for block in _content_blocks(html):
        if isinstance(block, _Table):
            if block.rows:
                _table_rows(block, last_paragraph, out)
            continue
        if block.tag == "li" and _bullet_row(block.text, last_paragraph, out):
            continue
        ignored += _prose_rows(block.text, out)
        if block.tag != "li":
            last_paragraph = block.text
    return ParsedPost(rows=out.rows, ignored=ignored)


__all__ = [
    "EspnPrBooth",
    "EspnPrParseError",
    "ParsedBooths",
    "ParsedViewership",
    "parse_booths",
    "parse_espnpr_viewers",
    "parse_viewership",
    "viewership_url_from_html",
]
