"""A wrapping matchup breaks before its joiner (user decisions 2026-11-03).

On every surface that lets a matchup wrap (the ESPN+ and regional table, Matched games, the This
weekend phone rows, the map game card and the CFB modal title), line 2 starts with "at", "@" or
"vs." and holds the home side, and an inline badge sits on the last line. The away side never
ends a line with the joiner, and the home side stays on one line when it fits there. Synthetic
games and an in-memory copy of the contract fixture only.
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
  const part = el.querySelector(':scope > .mu-part');
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
    _assert_breaks_before_joiner(
        got, joiner=joiner, text=f"#20 {away} {joiner} #5 {home}{suffix}", inline_badge=True
    )
    _assert_one_line(_lines(compact_page, '#wk-host .wk-crow[data-wk-id="g:s"] td.wk-c-game'))


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
    got = _lines(guarded_page, _RANKED_CELL)
    _assert_breaks_before_joiner(
        got, joiner="at", text=f"#5 {away} 20 at #3 {home} 27", inline_badge=True
    )


def test_matched_games_one_line_is_unchanged_at_1440(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    guarded_page.set_viewport_size({"width": 1440, "height": 900})
    _serve_names(guarded_page, fixture_raw, Lakeview="Lakeview Polytechnic Institute")
    open_app(guarded_page, _QUERY)
    guarded_page.wait_for_selector(_RANKED_CELL)
    _assert_one_line(_lines(guarded_page, _RANKED_CELL))


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
    # The phone row's badge sits at the top right, outside the text, so it is not inline.
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
    # The title writes ranks as superscripts with no "#".
    _assert_breaks_before_joiner(
        got,
        joiner="at",
        text=f"5{away} 20 at 3{home} 27",
        inline_badge=True,
        away_wraps=away == HOSTILE,
    )
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
