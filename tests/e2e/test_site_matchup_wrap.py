"""A wrapping matchup breaks before its joiner (user decisions 2026-11-03).

On every surface that lets a matchup wrap (the ESPN+ and regional table, Matched games, the This
weekend phone rows, the map game card and the CFB modal title), line 2 starts with "at", "@" or
"vs." and holds the home side. The away side never ends a line with the joiner, and the home side
stays on one line when it fits there. In the two tables a one-line ranked matchup ends with the
badge inline; a wrapped one centres the badge on the lines, 6px after the longest line (user
decisions 2026-11-03). Synthetic games and an in-memory copy of the contract fixture only.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page
from test_site_weekend_render import (
    _known,
    _mount,
    _mount_phone,
    _plus,
)

pytestmark = pytest.mark.e2e

OpenApp = Callable[[Page, str], None]

HOSTILE = '<img src=x onerror="window.__xssMu=1">'

# Splits the element's visible characters into lines (a new line starts where a character's
# middle drops more than half a line below the current line's), and reports where the away
# side ends, where the home part (`.mu-part`, which starts with the joiner) starts and ends,
# and where an inline badge sits. `text` is the element's text without the badge's own title.
_LINES_JS = """(sel) => {
  const el = document.querySelector(sel);
  const part = el.querySelector(':scope > .mu-part, :scope > .mu-lines > .mu-part');
  const lh = parseFloat(getComputedStyle(el).lineHeight)
    || parseFloat(getComputedStyle(el).fontSize) * 1.2;
  const chars = [];
  const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    if (n.parentElement.closest('.rk-badge')) continue;
    const home = part ? part.contains(n) : false;
    for (let k = 0; k < n.length; k += 1) {
      if (/\\s/.test(n.data[k])) continue;
      const r = document.createRange();
      r.setStart(n, k);
      r.setEnd(n, k + 1);
      const b = r.getBoundingClientRect();
      if (b.width === 0 && b.height === 0) continue;  // clamped away
      chars.push({ ch: n.data[k], home, mid: (b.top + b.bottom) / 2 });
    }
  }
  let line = 0;
  let cur = chars.length ? chars[0].mid : 0;
  const mids = [cur];
  for (const c of chars) {
    if (c.mid > cur + lh / 2) { line += 1; cur = c.mid; mids.push(cur); }
    c.line = line;
  }
  const away = chars.filter((c) => !c.home);
  const home = chars.filter((c) => c.home);
  const texts = [];
  for (const c of chars) texts[c.line] = (texts[c.line] ?? '') + c.ch;
  let text = '';
  const all = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  for (let n = all.nextNode(); n; n = all.nextNode()) {
    if (!n.parentElement.closest('.rk-badge')) text += n.data;
  }
  const badge = el.querySelector('.rk-badge');
  const bb = badge ? badge.getBoundingClientRect() : null;
  return {
    text,
    hasPart: part !== null,
    lines: line + 1,
    texts,
    awayEnd: away.length ? away[away.length - 1].line : null,
    homeStart: home.length ? home[0].line : null,
    homeLines: [...new Set(home.map((c) => c.line))],
    lastMid: mids[mids.length - 1],
    lh,
    badgeMid: bb ? (bb.top + bb.bottom) / 2 : null,
    imgs: el.querySelectorAll('img').length,
    xss: window.__xssMu ?? null,
  };
}"""


def _lines(page: Page, selector: str) -> dict[str, Any]:
    got: dict[str, Any] = page.evaluate(_LINES_JS, selector)
    return got


def _assert_breaks_before_joiner(
    got: dict[str, Any], *, joiner: str, text: str, inline_badge: bool, away_wraps: bool = False
) -> None:
    assert got["text"] == text
    assert got["hasPart"]
    assert got["lines"] >= 2, got
    if away_wraps:
        # An away side longer than a whole line wraps inside itself; the joiner and the home
        # side then follow its last word, or start the next line when they do not fit there.
        assert got["awayEnd"] >= 1, got
        assert got["homeStart"] in (got["awayEnd"], got["awayEnd"] + 1), got
    else:
        # The away side fills line 1 and line 2 starts with the joiner.
        assert (got["awayEnd"], got["homeStart"]) == (0, 1), got
        assert got["texts"][1].startswith(joiner), got
    # The joiner, the home side (and an inline badge) all sit on the last line.
    assert got["homeLines"] == [got["lines"] - 1], got
    assert got["imgs"] == 0 and got["xss"] is None
    if inline_badge:
        assert got["badgeMid"] is not None
        assert abs(got["badgeMid"] - got["lastMid"]) < got["lh"] / 2, got


def _assert_one_line(got: dict[str, Any]) -> None:
    assert got["lines"] == 1, got


# The ranked badge's place in a table matchup cell, against the matchup's text: each visible
# character's rect (the badge's own title skipped), the first line's top, the last line's
# bottom, the right edge of the last line's text and of the longest line's, the badge's and the
# cell's rects, the row's height and whether the cell's lines carry `rk-wrapped`.
_BADGE_JS = """(sel) => {
  const td = document.querySelector(sel);
  const box = td.querySelector('.mu-lines') ?? td;
  const lh = parseFloat(getComputedStyle(box).lineHeight)
    || parseFloat(getComputedStyle(box).fontSize) * 1.2;
  const chars = [];
  const walk = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    if (n.parentElement.closest('.rk-badge')) continue;
    for (let k = 0; k < n.length; k += 1) {
      if (/\\s/.test(n.data[k])) continue;
      const r = document.createRange();
      r.setStart(n, k);
      r.setEnd(n, k + 1);
      const b = r.getBoundingClientRect();
      if (b.width === 0 && b.height === 0) continue;
      chars.push({ top: b.top, bottom: b.bottom, left: b.left, right: b.right,
        mid: (b.top + b.bottom) / 2 });
    }
  }
  let line = 0;
  let cur = chars[0].mid;
  for (const c of chars) {
    if (c.mid > cur + lh / 2) { line += 1; cur = c.mid; }
    c.line = line;
  }
  const ends = [];
  for (const c of chars) ends[c.line] = Math.max(ends[c.line] ?? -Infinity, c.right);
  const first = chars.filter((c) => c.line === 0);
  const last = chars.filter((c) => c.line === line);
  const rect = (e) => { const r = e.getBoundingClientRect();
    return { top: r.top, bottom: r.bottom, left: r.left, right: r.right }; };
  const b = rect(td.querySelector('.rk-badge'));
  const overlap = chars.filter((c) => c.left < b.right && c.right > b.left
    && c.top < b.bottom && c.bottom > b.top).length;
  return {
    lines: line + 1,
    wrapped: box.classList.contains('rk-wrapped'),
    firstTop: Math.min(...first.map((c) => c.top)),
    lastBottom: Math.max(...last.map((c) => c.bottom)),
    lastRight: Math.max(...last.map((c) => c.right)),
    longestRight: Math.max(...ends),
    textLeft: Math.min(...chars.map((c) => c.left)),
    badge: b,
    cell: rect(td),
    rowHeight: td.parentElement.getBoundingClientRect().height,
    overlap,
  };
}"""


def _badge(page: Page, selector: str) -> dict[str, Any]:
    # The badge's placement follows a ResizeObserver, which reports after layout, before paint:
    # two frames let every report land.
    page.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
    got: dict[str, Any] = page.evaluate(_BADGE_JS, selector)
    return got


def _assert_badge_centred(got: dict[str, Any]) -> None:
    """A wrapped cell: the badge centred on the lines, 6px after the longest line (the one-line
    gap, user feedback 2026-11-03), clear of the text and inside the cell."""
    assert got["lines"] >= 2 and got["wrapped"], got
    b, cell = got["badge"], got["cell"]
    assert abs(b["left"] - got["longestRight"] - 6) <= 0.5, got
    lines_mid = (got["firstTop"] + got["lastBottom"]) / 2
    assert abs((b["top"] + b["bottom"]) / 2 - lines_mid) <= 1, got
    assert b["top"] >= got["firstTop"], got
    assert got["overlap"] == 0, got
    assert cell["left"] <= b["left"] and b["right"] <= cell["right"], got
    assert cell["top"] <= b["top"] and b["bottom"] <= cell["bottom"], got


def _assert_badge_inline(got: dict[str, Any]) -> None:
    """A one-line cell: the badge inline, 6px after the last word, inside the cell."""
    assert got["lines"] == 1 and not got["wrapped"], got
    b, cell = got["badge"], got["cell"]
    assert abs(b["left"] - got["lastRight"] - 6) <= 1, got
    assert got["overlap"] == 0, got
    assert cell["left"] <= b["left"] and b["right"] <= cell["right"], got


# ------------------------------------------------------------------ ESPN+ and regional table

COMPACT_WIDTH = 768


@pytest.fixture
def compact_page(guarded_page: Page, open_app: OpenApp) -> Page:
    guarded_page.set_viewport_size({"width": COMPACT_WIDTH, "height": 900})
    open_app(guarded_page, "")
    return guarded_page


@pytest.mark.parametrize(
    ("away", "home", "neutral"),
    [
        ("Southern Mississippi Golden Eagles", "Louisiana-Monroe", False),
        (HOSTILE, "Kansas State Wildcats", True),
    ],
)
def test_compact_table_breaks_before_the_joiner(
    compact_page: Page, away: str, home: str, neutral: bool
) -> None:
    venue = {"city": "Arlington", "state": "TX"} if neutral else None
    games = [
        _known(key="a"),
        _plus(
            key="r",
            away=away,
            home=home,
            awayRank=20,
            homeRank=5,
            neutral=neutral,
            venue=venue,
            pbp="Ann Caller Longname",
            analyst="Bob Color Longername",
            crewKnown=True,
        ),
        _plus(key="s", away="Away", home="Home", awayRank=20, homeRank=5),
    ]
    _mount(compact_page, games, width=COMPACT_WIDTH)
    joiner = "vs." if neutral else "@"
    suffix = " (Arlington, TX)" if neutral else ""
    got = _lines(compact_page, '#wk-host .wk-crow[data-wk-id="g:r"] td.wk-c-game')
    # A wrapped cell's badge sits at the right, centred on the lines, so it is not inline.
    _assert_breaks_before_joiner(
        got, joiner=joiner, text=f"#20 {away} {joiner} #5 {home}{suffix}", inline_badge=False
    )
    _assert_one_line(_lines(compact_page, '#wk-host .wk-crow[data-wk-id="g:s"] td.wk-c-game'))


def _compact_badge_games() -> list[dict[str, Any]]:
    return [
        _known(key="a"),
        # Wraps at 768: the away side fills line 1 and the home side takes line 2.
        _plus(
            key="w",
            away="Southern Mississippi Golden Eagles",
            home="Louisiana-Monroe",
            awayRank=20,
            homeRank=5,
            pbp="Ann Caller Longname",
            analyst="Bob Color Longername",
            crewKnown=True,
        ),
        # One line, ranked and its unranked twin (same text, no badge).
        _plus(key="o", away="Away", home="Home", awayRank=20, homeRank=5),
        _plus(key="u", away="#20 Away", home="#5 Home"),
    ]


def _crow(key: str) -> str:
    return f'#wk-host .wk-crow[data-wk-id="g:{key}"] td.wk-c-game'


def test_compact_table_centres_a_wrapped_badge_on_the_lines(compact_page: Page) -> None:
    """User decision 2026-11-03: a wrapped ranked cell's badge centres on the matchup lines, 6px
    after the longest line as on one line (not at the cell's right edge, user feedback
    2026-11-03); a one-line cell keeps it inline after the last word."""
    _mount(compact_page, _compact_badge_games(), width=COMPACT_WIDTH)
    wrapped = _badge(compact_page, _crow("w"))
    _assert_badge_centred(wrapped)
    # The badge's room (24px at the end of the lines) does not push the cell to a third line.
    assert wrapped["lines"] == 2, wrapped
    one = _badge(compact_page, _crow("o"))
    _assert_badge_inline(one)
    # One line is unchanged: the same row height and text start as the unranked twin's row.
    twin = compact_page.evaluate(
        """(sel) => { const td = document.querySelector(sel);
          const r = document.createRange(); r.selectNodeContents(td);
          const t = r.getClientRects()[0], c = td.getBoundingClientRect();
          return { rowHeight: td.parentElement.getBoundingClientRect().height,
            dx: t.left - c.left }; }""",
        _crow("u"),
    )
    assert one["rowHeight"] == twin["rowHeight"], (one, twin)
    assert abs((one["textLeft"] - one["cell"]["left"]) - twin["dx"]) <= 0.5, (one, twin)
    # Unwrapped cells reserve nothing: no end padding on the ranked one-line cell's lines.
    pad = compact_page.evaluate(
        "(sel) => getComputedStyle(document.querySelector(sel + ' .mu-lines')).paddingRight",
        _crow("o"),
    )
    assert pad == "0px"


def test_compact_table_badge_follows_a_resize(compact_page: Page) -> None:
    """The cell is re-measured on resize: widening to one line puts the badge back inline, and
    narrowing again centres it on the lines. (Narrowing the cell itself by style rewrapped
    locally but not on the CI runner, so that check was dropped; Matched games covers a
    narrowed column.)"""
    _mount(compact_page, _compact_badge_games(), width=COMPACT_WIDTH)
    first = _badge(compact_page, _crow("w"))
    _assert_badge_centred(first)
    compact_page.set_viewport_size({"width": 1440, "height": 900})
    _wait_wrapped(compact_page, _crow("w"), wrapped=False)
    _assert_badge_inline(_badge(compact_page, _crow("w")))
    compact_page.set_viewport_size({"width": COMPACT_WIDTH, "height": 900})
    _wait_wrapped(compact_page, _crow("w"), wrapped=True)
    _assert_badge_centred(_badge(compact_page, _crow("w")))


def _wait_wrapped(page: Page, selector: str, *, wrapped: bool) -> None:
    # The ResizeObserver re-syncs after the next layout, not within set_viewport_size; poll on
    # a timer (not animation frames) until the cell's wrapped state settles. This raced in CI.
    page.wait_for_function(
        "([sel, want]) => document.querySelector(sel + ' .mu-lines')"
        ".classList.contains('rk-wrapped') === want",
        arg=[selector, wrapped],
        polling=100,
    )


# ------------------------------------------------------------------ Matched games

_QUERY = "?school=northfield"  # telecasts 0, 4 and 8; telecast 4 is #5 Northfield at #3 Lakeview


def _serve_names(page: Page, fixture_raw: dict[str, Any], **names: str) -> None:
    raw = copy.deepcopy(fixture_raw)
    teams = raw["lookups"]["teams"]
    for old, new in names.items():
        next(t for t in teams if t["name"] == old.replace("_", " "))["name"] = new
    page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))


_RANKED_CELL = "#games-table tbody td.matchup:has(.rk-badge)"

# The shipped Matched games table never wraps its matchup: on desktop the cell is nowrap, and on
# a phone the table takes its max-content width and scrolls. To prove the cell's own markup and
# styles break before the joiner, this narrows the matchup column in a fixed-layout table.
_NARROW_JS = """(px) => {
  const table = document.querySelector('#games-table');
  const ths = table.querySelectorAll('thead th');
  const tds = table.querySelectorAll('tbody tr:first-child td');
  table.style.tableLayout = 'fixed';
  table.style.width = '1600px';
  [...ths].forEach((th, k) => {
    th.style.width = tds[k]?.classList.contains('matchup') ? px + 'px' : '';
  });
  return true;
}"""


@pytest.mark.parametrize(
    ("away", "home", "column"),
    [("Northfield", "Lakeview State", 260), ("Northfield", HOSTILE, 460)],
)
def test_matched_games_breaks_before_the_joiner_at_390(
    guarded_page: Page,
    open_app: OpenApp,
    fixture_raw: dict[str, Any],
    away: str,
    home: str,
    column: int,
) -> None:
    guarded_page.set_viewport_size({"width": 390, "height": 844})
    _serve_names(guarded_page, fixture_raw, Lakeview=home)
    open_app(guarded_page, _QUERY)
    guarded_page.wait_for_selector(_RANKED_CELL)
    # As shipped, the phone table scrolls at max-content, so the cell stays on one line.
    _assert_one_line(_lines(guarded_page, _RANKED_CELL))
    guarded_page.evaluate(_NARROW_JS, column)
    _badge(guarded_page, _RANKED_CELL)  # lets the narrowed cell's badge move first
    got = _lines(guarded_page, _RANKED_CELL)
    _assert_breaks_before_joiner(
        got, joiner="at", text=f"#5 {away} 20 at #3 {home} 27", inline_badge=False
    )


def test_matched_games_one_line_is_unchanged_at_1440(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    guarded_page.set_viewport_size({"width": 1440, "height": 900})
    _serve_names(guarded_page, fixture_raw, Lakeview="Lakeview Polytechnic Institute")
    open_app(guarded_page, _QUERY)
    guarded_page.wait_for_selector(_RANKED_CELL)
    _assert_one_line(_lines(guarded_page, _RANKED_CELL))


def test_matched_games_centres_a_wrapped_badge_on_the_lines(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """The rule holds in Matched games if its layout ever lets the matchup wrap: one line keeps
    the badge inline, a narrowed column centres it on the lines, and widening again puts it back
    exactly where it was. At 390, since the desktop cell is nowrap."""
    guarded_page.set_viewport_size({"width": 390, "height": 844})
    _serve_names(guarded_page, fixture_raw, Lakeview="Lakeview State")
    open_app(guarded_page, _QUERY)
    guarded_page.wait_for_selector(_RANKED_CELL)
    before = _badge(guarded_page, _RANKED_CELL)
    _assert_badge_inline(before)
    guarded_page.evaluate(_NARROW_JS, 260)
    _assert_badge_centred(_badge(guarded_page, _RANKED_CELL))
    # A narrower column rewraps the lines and the badge follows the longest one.
    guarded_page.evaluate(_NARROW_JS, 200)
    _assert_badge_centred(_badge(guarded_page, _RANKED_CELL))
    guarded_page.evaluate(
        """() => { const t = document.querySelector('#games-table');
          t.style.tableLayout = ''; t.style.width = '';
          t.querySelectorAll('thead th').forEach((th) => { th.style.width = ''; }); }"""
    )
    after = _badge(guarded_page, _RANKED_CELL)
    _assert_badge_inline(after)
    assert after == before


# ------------------------------------------------------------------ phone rows


@pytest.mark.parametrize(
    ("away", "home"),
    [
        ("Southern Mississippi", "Louisiana-Monroe"),
        (HOSTILE, "Kansas State"),
    ],
)
def test_phone_row_breaks_before_the_joiner(
    guarded_page: Page, open_app: OpenApp, away: str, home: str
) -> None:
    guarded_page.set_viewport_size({"width": 390, "height": 844})
    open_app(guarded_page, "")
    games = [
        _known(key="r", away=away, home=home, awayRank=20, homeRank=5),
        _known(key="s", away="Away", home="Home", awayRank=20, homeRank=5),
    ]
    _mount_phone(guarded_page, games)
    got = _lines(guarded_page, '#wk-host .wk-item[data-wk-id="g:r"] .wk-item-l1')
    # The phone row's badge sits at the right, centred on the matchup lines, so not inline.
    _assert_breaks_before_joiner(
        got,
        joiner="@",
        text=f"#20 {away} @ #5 {home}",
        inline_badge=False,
        away_wraps=away == HOSTILE,
    )
    _assert_one_line(_lines(guarded_page, '#wk-host .wk-item[data-wk-id="g:s"] .wk-item-l1'))


# ------------------------------------------------------------------ map game card

_CARD_JS = """async ([sides, ranked]) => {
  const t = await import('./modules/tooltip.js');
  const matchup = `${sides.away} ${sides.joiner} ${sides.home}`;
  t.showGameTooltip({ matchup, matchupSides: sides,
    booth: { star: false, text: 'Pat Rowan · Sam Delgado', weight: 600 },
    kickoff: '7:30 pm ET, Alpha Sports', venue: 'Stonebridge Stadium, Pasadena, CA',
    family: 'disney', ranked, rankSlot: true, conf: null },
    { theme: 'light', clientX: 200, clientY: 200 });
  return true;
}"""


@pytest.mark.parametrize(
    ("away", "home"),
    [
        ("#20 Ironpeak Polytechnic Institute", "#5 Stonebridge State"),
        (f"#20 {HOSTILE}", "#5 Stonebridge"),
    ],
)
def test_map_card_breaks_before_the_joiner(
    guarded_page: Page, open_app: OpenApp, away: str, home: str
) -> None:
    guarded_page.set_viewport_size({"width": 1440, "height": 900})
    open_app(guarded_page, "")
    guarded_page.evaluate(_CARD_JS, [{"away": away, "joiner": "@", "home": home}, True])
    got = _lines(guarded_page, "#chart-tooltip .tooltip-game-matchup")
    # The card's badge sits at the top right, in reserved padding, so it is not inline.
    _assert_breaks_before_joiner(
        got,
        joiner="@",
        text=f"{away} @ {home}",
        inline_badge=False,
        away_wraps=HOSTILE in away,
    )
    guarded_page.evaluate(
        _CARD_JS, [{"away": "#20 Ironpeak", "joiner": "@", "home": "#5 Stonebridge"}, True]
    )
    _assert_one_line(_lines(guarded_page, "#chart-tooltip .tooltip-game-matchup"))


# ------------------------------------------------------------------ modal title


@pytest.mark.parametrize(
    ("away", "home"),
    [("Northfield", "Lakeview State"), (HOSTILE, "Lakeview")],
)
def test_modal_title_breaks_before_the_joiner_at_390(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any], away: str, home: str
) -> None:
    """The hostile away name is longer than a line, so it also covers the away-wraps case."""
    guarded_page.set_viewport_size({"width": 390, "height": 844})
    _serve_names(guarded_page, fixture_raw, Northfield=away, Lakeview=home)
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.openPanel(4)")
    guarded_page.wait_for_selector("#detail-panel[open]")
    got = _lines(guarded_page, "#panel-title")
    # The title writes ranks as superscripts with no "#". A wrapped title's badge leaves the
    # last line for the reserved space at the right, centred on the title's lines (user
    # feedback 2026-11-03), so it is not inline here.
    _assert_breaks_before_joiner(
        got,
        joiner="at",
        text=f"5{away} 20 at 3{home} 27",
        inline_badge=False,
        away_wraps=away == HOSTILE,
    )
    # Measured together in one call: the dialog may still be easing into place.
    off = guarded_page.evaluate(
        "(() => { const r = document.querySelector('#panel-title').getBoundingClientRect();"
        " const b = document.querySelector('#panel-title .rk-badge').getBoundingClientRect();"
        " return (b.top + b.bottom) / 2 - (r.top + r.bottom) / 2; })()"
    )
    assert abs(off) <= 1, got
    label = guarded_page.get_attribute("#panel-title", "aria-label")
    assert label == f"#5 {away} 20 at #3 {home} 27. Both teams ranked."


def test_modal_title_one_line_is_unchanged_at_1440(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    guarded_page.set_viewport_size({"width": 1440, "height": 900})
    _serve_names(guarded_page, fixture_raw)
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.openPanel(4)")
    guarded_page.wait_for_selector("#detail-panel[open]")
    _assert_one_line(_lines(guarded_page, "#panel-title"))
