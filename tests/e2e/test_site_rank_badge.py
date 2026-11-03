"""Phase 28 ranked-matchup badge: module behaviour, then its presence, accessible name, zero
layout shift and CFB-only scope on the This weekend list surfaces (D-01..D-07). Synthetic games
only, mounted with the helpers of the weekend render tests."""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page
from test_site_weekend_render import (
    _cell,
    _known,
    _mount,
    _mount_phone,
    _plus,
    phone_page,  # noqa: F401  (fixture)
    wk_page,  # noqa: F401  (fixture)
)

pytestmark = pytest.mark.e2e

LABEL = "Both teams ranked"

_MODULE_JS = """
async () => {
  const m = await import('./modules/rank-badge.js');
  const full = m.rankBadge();
  const hid = m.rankBadge({ hidden: true });
  document.body.append(full, hid);
  const svg = full.querySelector('svg');
  const hsvg = hid.querySelector('svg');
  const mask = svg.querySelector('mask');
  const rect = svg.querySelector('rect[fill=currentColor]');
  const box = hid.getBoundingClientRect();
  hid.style.height = '18px';
  const sized = hid.getBoundingClientRect();
  const out = {
    both: [m.bothRanked(20, 5), m.bothRanked(null, 5), m.bothRanked(20, undefined),
      m.bothRanked(null, null), m.bothRanked(0, 1)],
    ranked: [
      m.isRankedMatchup({ sport: 'cfb', awayRank: 20, homeRank: 5 }),
      m.isRankedMatchup({ sport: 'nfl', awayRank: 20, homeRank: 5 }),
      m.isRankedMatchup({ sport: 'cfb', awayRank: 20 }),
      m.isRankedMatchup({}),
      m.isRankedMatchup(undefined),
    ],
    spanTitle: full.title,
    hiddenTitle: hid.title,
    viewBox: svg.getAttribute('viewBox'),
    role: svg.getAttribute('role'),
    aria: svg.getAttribute('aria-label'),
    titleEl: svg.querySelector('title').textContent,
    maskRef: rect.getAttribute('mask') === `url(#${mask.id})`,
    maskInDoc: document.getElementById(mask.id) === mask,
    starPoints: svg.querySelector('polygon').getAttribute('points').split(' ').length,
    paths: svg.querySelectorAll('path').length,
    hidden: {
      ariaHidden: hsvg.getAttribute('aria-hidden'),
      spanAriaHidden: hid.getAttribute('aria-hidden'),
      fullSpanAriaHidden: full.getAttribute('aria-hidden'),
      focusable: hsvg.getAttribute('focusable'),
      role: hsvg.getAttribute('role'),
      label: hsvg.getAttribute('aria-label'),
    },
    ids: [svg.querySelector('mask').id, hsvg.querySelector('mask').id],
    h: sized.height,
    w: sized.width,
    wasZero: box.height,
  };
  full.remove();
  hid.remove();
  return out;
}
"""


def test_module_contract(wk_page: Page) -> None:  # noqa: F811
    r = wk_page.evaluate(_MODULE_JS)
    assert r["both"] == [True, False, False, False, True]
    assert r["ranked"] == [True, False, False, False, False]
    assert r["spanTitle"] == LABEL and r["hiddenTitle"] == LABEL
    assert r["viewBox"] == "0 0 100 100"
    assert (r["role"], r["aria"], r["titleEl"]) == ("img", LABEL, LABEL)
    assert r["maskRef"] and r["maskInDoc"]
    assert r["starPoints"] == 10 and r["paths"] == 1
    assert r["hidden"] == {
        "ariaHidden": "true",
        # IN-02: the span is hidden too, so its title is not read as a description.
        "spanAriaHidden": "true",
        "fullSpanAriaHidden": None,
        "focusable": "false",
        "role": None,
        "label": None,
    }
    assert r["ids"][0] != r["ids"][1]
    assert r["h"] == 18 and r["w"] > 0


def _badge_box(page: Page, selector: str) -> dict[str, float]:
    box = page.locator(f"{selector} .rk-badge").bounding_box()
    assert box is not None
    return box


def test_cell_aria_sentence_and_hidden_badge(wk_page: Page) -> None:  # noqa: F811
    _mount(wk_page, [_known(key="r", awayRank=20, homeRank=5), _known(key="o", awayRank=20)])
    label = wk_page.locator(_cell("r")).get_attribute("aria-label") or ""
    assert label.endswith(" Both teams ranked.")
    assert wk_page.locator(f"{_cell('r')} .rk-badge svg").get_attribute("aria-hidden") == "true"
    assert wk_page.locator(f"{_cell('r')} .rk-badge").count() == 1
    assert "rk-has" in (wk_page.locator(_cell("r")).get_attribute("class") or "")
    other = wk_page.locator(_cell("o"))
    assert "Both teams ranked" not in (other.get_attribute("aria-label") or "")
    assert other.locator(".rk-badge").count() == 0
    assert "rk-has" not in (other.get_attribute("class") or "")
    assert wk_page.locator(f"{_cell('r')} .rk-badge").get_attribute("title") == LABEL


def test_cell_equal_height_and_badge_geometry(wk_page: Page) -> None:  # noqa: F811
    _mount(wk_page, [_known(key="r", awayRank=20, homeRank=5)])
    ranked = wk_page.locator(_cell("r")).bounding_box()
    _mount(wk_page, [_known(key="r", awayRank=20, homeRank=None)])
    plain = wk_page.locator(_cell("r")).bounding_box()
    assert ranked is not None and plain is not None
    assert ranked["height"] == plain["height"]
    assert ranked["width"] == plain["width"]
    _mount(wk_page, [_known(key="r", awayRank=20, homeRank=5)])
    cell = wk_page.locator(_cell("r")).bounding_box()
    badge = _badge_box(wk_page, _cell("r"))
    assert cell is not None
    assert abs((cell["x"] + cell["width"] - 6) - (badge["x"] + badge["width"])) <= 1
    assert abs(badge["y"] - cell["y"] - 4) <= 1
    assert badge["height"] == 18


def test_long_matchup_ellipsis_ends_before_badge(wk_page: Page) -> None:  # noqa: F811
    games = [
        _known(
            key="r",
            awayRank=20,
            homeRank=5,
            away="Southern Mississippi Golden Eagles",
            home="Louisiana-Monroe Warhawks",
        )
    ]
    _mount(wk_page, games)
    m = wk_page.locator(f"{_cell('r')} .wk-match")
    over = m.evaluate("e => e.scrollWidth > e.clientWidth")
    assert over
    mbox = m.bounding_box()
    badge = _badge_box(wk_page, _cell("r"))
    assert mbox is not None
    assert mbox["x"] + mbox["width"] <= badge["x"]


_CELL_SWEEP_JS = """([rankedSel, plainSel]) => {
  // Gives a ranked and an unranked timeline cell of the same width the same matchup and booth
  // text, one character longer each step, and compares where each line truncates: the text box
  // widths and whether the ellipsis shows.
  const cells = [document.querySelector(rankedSel), document.querySelector(plainSel)];
  const full = '#20 Southern Mississippi Golden Eagles at #5 Louisiana-Monroe Warhawks';
  const booth = 'Joe Fowler, Pat Herbstreit, Sam Sideline and Lee Reporter of the Lakeview Network';
  const out = [];
  for (let n = 1; n <= full.length; n += 1) {
    const got = cells.map((cell) => {
      const m = cell.querySelector('.wk-match');
      const b = cell.querySelector('.wk-booth');
      m.textContent = full.slice(0, n);
      b.textContent = booth.slice(0, n + 10);
      return { h: cell.getBoundingClientRect().height,
               match: m.clientWidth, matchCut: m.scrollWidth > m.clientWidth,
               booth: b.clientWidth, boothCut: b.scrollWidth > b.clientWidth };
    });
    out.push({ n, ranked: got[0], plain: got[1] });
  }
  return { width: cells.map((c) => c.getBoundingClientRect().width), out };
}"""


def test_cells_truncate_the_same_with_or_without_the_badge(wk_page: Page) -> None:  # noqa: F811
    """User decision 2026-11-03 ("reserve badge space everywhere"): every CFB timeline cell keeps
    the badge's 28px, so identical text truncates at the same place, ranked or not."""
    _mount(
        wk_page,
        [
            _known(key="r", awayRank=20, homeRank=5),
            _known(key="o", awayRank=20, networkId="cbs", networkName="CBS", family="cbs"),
        ],
    )
    pads = [
        wk_page.locator(_cell(k)).evaluate("e => getComputedStyle(e).paddingRight")
        for k in ("r", "o")
    ]
    assert pads == ["28px", "28px"]
    got = wk_page.evaluate(_CELL_SWEEP_JS, [_cell("r"), _cell("o")])
    assert got["width"][0] == got["width"][1]
    differ = [r for r in got["out"] if r["ranked"] != r["plain"]]
    assert differ == []
    # The sweep reached lengths that cut both lines, so it crossed the truncation points.
    assert any(r["plain"]["matchCut"] for r in got["out"])
    assert any(r["plain"]["boothCut"] for r in got["out"])
    assert not got["out"][0]["plain"]["matchCut"]


def test_nfl_cells_keep_their_normal_padding(wk_page: Page) -> None:  # noqa: F811
    _mount(wk_page, [_known(key="n", sport="nfl")], model={"sport": "nfl"})
    pad = wk_page.locator(_cell("n")).evaluate("e => getComputedStyle(e).paddingRight")
    assert pad == "8px"


def test_lead_star_and_badge_boxes_are_disjoint(wk_page: Page) -> None:  # noqa: F811
    _mount(wk_page, [_known(key="r", awayRank=20, homeRank=5, lead=True, boothRank=1)])
    star = wk_page.locator(f"{_cell('r')} .wk-star").bounding_box()
    badge = _badge_box(wk_page, _cell("r"))
    assert star is not None
    apart = (
        star["x"] + star["width"] <= badge["x"]
        or badge["x"] + badge["width"] <= star["x"]
        or star["y"] + star["height"] <= badge["y"]
        or badge["y"] + badge["height"] <= star["y"]
    )
    assert apart


def test_phone_row_badge_aria_and_equal_height(phone_page: Page) -> None:  # noqa: F811
    _mount_phone(
        phone_page,
        [
            _known(key="r", awayRank=20, homeRank=5, home="R"),
            _known(key="o", awayRank=20, homeRank=None, home="R"),
        ],
    )
    sel = '#wk-host .wk-item[data-wk-id="g:%s"]'
    ranked = phone_page.locator(sel % "r")
    plain = phone_page.locator(sel % "o")
    assert ranked.locator(".rk-badge").count() == 1
    assert plain.locator(".rk-badge").count() == 0
    assert ranked.locator(".rk-badge svg").get_attribute("aria-hidden") == "true"
    assert (ranked.get_attribute("aria-label") or "").endswith(" Both teams ranked.")
    rb, pb = ranked.bounding_box(), plain.bounding_box()
    assert rb is not None and pb is not None
    assert rb["height"] == pb["height"]


_ROW_SWEEP_JS = """([rankedSel, plainSel]) => {
  // Gives a ranked and an unranked phone row the same matchup (line 1) and booth (line 2)
  // text, one character longer each step, and compares each row's height and each line's
  // unclamped height, so a line that wraps or clamps at a different place shows up.
  const rows = [document.querySelector(rankedSel), document.querySelector(plainSel)];
  const full = '#20 Southern Mississippi Golden Eagles at #5 Louisiana-Monroe Warhawks';
  const booth = 'Joe Fowler, Pat Herbstreit and Sam Sideline of the Lakeview Network';
  const out = [];
  for (let n = 1; n <= full.length; n += 1) {
    const got = rows.map((row) => {
      row.querySelector('.wk-item-l1').textContent = full.slice(0, n);
      row.querySelector('.wk-booth').textContent = booth.slice(0, n);
      return {
        h: row.getBoundingClientRect().height,
        l1: row.querySelector('.wk-item-l1').scrollHeight,
        l2: row.querySelector('.wk-item-l2').scrollHeight,
      };
    });
    out.push({ n, ranked: got[0], plain: got[1] });
  }
  return out;
}"""


def test_phone_rows_wrap_the_same_with_or_without_the_badge(phone_page: Page) -> None:  # noqa: F811
    """User decision 2026-11-03 ("reserve badge space everywhere"): every CFB phone row keeps
    the badge's 28px, so identical text wraps and clamps identically, ranked or not, at 390px."""
    _mount_phone(
        phone_page,
        [
            _known(key="r", awayRank=20, homeRank=5, home="R"),
            _known(key="o", awayRank=20, homeRank=None, home="R"),
        ],
    )
    sel = '#wk-host .wk-item[data-wk-id="g:%s"]'
    pads = [
        phone_page.locator(sel % k).evaluate("e => getComputedStyle(e).paddingRight")
        for k in ("r", "o")
    ]
    assert pads == ["28px", "28px"]
    rows = phone_page.evaluate(_ROW_SWEEP_JS, [sel % "r", sel % "o"])
    differ = [r for r in rows if r["ranked"] != r["plain"]]
    assert differ == []
    # The sweep crossed a wrap point, so it tested the lengths that end a line near the edge.
    assert len({r["plain"]["l1"] for r in rows}) >= 2


def test_nfl_phone_rows_keep_their_normal_padding(phone_page: Page) -> None:  # noqa: F811
    _mount_phone(phone_page, [_known(key="n", sport="nfl")], model={"sport": "nfl"})
    pad = phone_page.locator('#wk-host .wk-item[data-wk-id="g:n"]').evaluate(
        "e => getComputedStyle(e).paddingRight"
    )
    assert pad == "16px"


def test_compact_table_badge_aria_and_equal_row_height(wk_page: Page) -> None:  # noqa: F811
    _mount(
        wk_page,
        [
            _known(key="a"),
            _plus(key="r", home="Ranked", awayRank=20, homeRank=5),
            _plus(key="o", home="Plain", awayRank=20),
        ],
    )
    sel = '#wk-host .wk-crow[data-wk-id="g:%s"]'
    ranked = wk_page.locator(sel % "r")
    plain = wk_page.locator(sel % "o")
    assert ranked.locator("td.wk-c-game .rk-badge").count() == 1
    assert plain.locator(".rk-badge").count() == 0
    assert ranked.locator(".rk-badge svg").get_attribute("aria-hidden") == "true"
    assert (ranked.get_attribute("aria-label") or "").endswith(" Both teams ranked.")
    rb, pb = ranked.bounding_box(), plain.bounding_box()
    assert rb is not None and pb is not None
    assert rb["height"] == pb["height"]


def test_nfl_weekend_never_shows_the_badge(wk_page: Page) -> None:  # noqa: F811
    games: list[dict[str, Any]] = [
        _known(key="n", sport="nfl", awayRank=20, homeRank=5),
        _plus(key="m", sport="nfl", awayRank=3, homeRank=4),
    ]
    _mount(wk_page, games, model={"sport": "nfl"})
    assert wk_page.locator("#wk-host .rk-badge").count() == 0
    label = wk_page.locator(_cell("n")).get_attribute("aria-label") or ""
    assert "Both teams ranked" not in label


_PHONE_CENTRE_JS = """(sel) => {
  // The ranked badge against the matchup lines it centres on: the matchup line's box is
  // exactly the lines the 2-line clamp shows, and its top is the first line's top.
  const row = document.querySelector(sel);
  const l1 = row.querySelector('.wk-item-l1');
  const badge = row.querySelector('.rk-badge');
  const lines = l1.getBoundingClientRect();
  const b = badge.getBoundingClientRect();
  const r = row.getBoundingClientRect();
  const h = r.height;
  badge.style.display = 'none';
  const bare = row.getBoundingClientRect().height;
  badge.style.display = '';
  const lh = parseFloat(getComputedStyle(l1).lineHeight);
  return {
    linesTop: lines.top, linesMid: (lines.top + lines.bottom) / 2,
    lineCount: Math.round(lines.height / lh), clipped: l1.scrollHeight > l1.clientHeight + 1,
    badgeTop: b.top, badgeMid: (b.top + b.bottom) / 2, badgeLeft: b.left, badgeRight: b.right,
    badgeH: b.height, rowRight: r.right, h, bare,
  };
}"""


@pytest.mark.parametrize(
    ("away", "home", "lines", "clipped"),
    [
        ("Away", "Home", 1, False),
        ("Southern Mississippi", "Louisiana-Monroe", 2, False),
        # Long enough for three lines, so the 2-line clamp cuts it: the badge centres on the
        # two lines that show.
        (
            "Southern Mississippi Golden Eagles of Hattiesburg",
            "Louisiana-Monroe Warhawks of Monroe",
            2,
            True,
        ),
    ],
)
def test_phone_row_badge_centres_on_the_matchup_lines(
    phone_page: Page,  # noqa: F811
    away: str,
    home: str,
    lines: int,
    clipped: bool,
) -> None:
    """User feedback 2026-11-03: at 390px the phone row's badge centres vertically on the
    matchup's visible lines (line 1, or lines 1-2 when it wraps), never on the booth line or
    the whole row, and never rides above the first line. It stays in the reserved 28px, and no
    row changes height."""
    _mount_phone(
        phone_page,
        [
            _known(key="r", away=away, home=home, awayRank=20, homeRank=5),
            _known(key="o", away=away, home=home, awayRank=20, homeRank=None),
        ],
    )
    sel = '#wk-host .wk-item[data-wk-id="g:%s"]'
    got = phone_page.evaluate(_PHONE_CENTRE_JS, sel % "r")
    assert (got["lineCount"], got["clipped"]) == (lines, clipped), got
    assert got["badgeH"] == pytest.approx(18, abs=0.01)
    assert abs(got["badgeMid"] - got["linesMid"]) <= 1, got
    assert got["badgeTop"] >= got["linesTop"] - 0.01, got
    assert got["badgeRight"] == pytest.approx(got["rowRight"] - 6, abs=0.5)
    assert got["badgeLeft"] >= got["rowRight"] - 28 - 0.01
    assert got["h"] == pytest.approx(got["bare"], abs=0.01)
    plain = phone_page.locator(sel % "o").bounding_box()
    assert plain is not None
    assert got["h"] == pytest.approx(plain["height"], abs=0.01)


def test_cell_badge_never_rides_above_the_matchup_line(wk_page: Page) -> None:  # noqa: F811
    """User feedback 2026-11-03: the timeline cell's matchup is one line, so its badge (top
    4px) must start no higher than that line's box and centre on it."""
    _mount(wk_page, [_known(key="r", awayRank=20, homeRank=5)])
    got = wk_page.evaluate(
        """(sel) => {
          const cell = document.querySelector(sel);
          const line = cell.querySelector('.wk-line1').getBoundingClientRect();
          const b = cell.querySelector('.rk-badge').getBoundingClientRect();
          return { lineTop: line.top, lineMid: (line.top + line.bottom) / 2,
                   badgeTop: b.top, badgeMid: (b.top + b.bottom) / 2 };
        }""",
        _cell("r"),
    )
    assert got["badgeTop"] >= got["lineTop"] - 0.01, got
    assert abs(got["badgeMid"] - got["lineMid"]) <= 1, got
