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
  const full = '#20 Southern Mississippi Golden Eagles of the Gulf Coast at '
    + '#5 Louisiana-Monroe Warhawks of the Delta';
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


def test_cells_reserve_room_only_for_the_marks_they_show(wk_page: Page) -> None:  # noqa: F811
    """User 2026-11-11 (reversing 2026-11-03's "reserve badge space everywhere"): a cell's text
    truncates on what is visible. Every cell keeps its 8px padding; a line gives up 20px more
    only for a mark drawn on it (the badge or swords on the matchup line, the swords on the
    booth line under a badge)."""
    _mount(
        wk_page,
        [
            _known(key="r", awayRank=20, homeRank=5),
            _known(
                key="v",
                rivalry="Lakeshore Rivalry",
                networkId="cbs",
                networkName="CBS",
                family="cbs",
            ),
            _known(
                key="b",
                awayRank=20,
                homeRank=5,
                rivalry="Lakeshore Rivalry",
                networkId="abc",
                networkName="ABC",
                family="disney",
            ),
            _known(key="o", awayRank=20, networkId="nbc", networkName="NBC", family="nbc"),
        ],
    )
    style = (
        "e => [getComputedStyle(e).paddingRight,"
        " getComputedStyle(e.querySelector('.wk-line1')).marginRight,"
        " getComputedStyle(e.querySelector('.wk-line2')).marginRight]"
    )
    got = {k: wk_page.locator(_cell(k)).evaluate(style) for k in ("r", "v", "b", "o")}
    assert got == {
        "r": ["8px", "20px", "0px"],
        "v": ["8px", "20px", "0px"],
        "b": ["8px", "20px", "20px"],
        "o": ["8px", "0px", "0px"],
    }
    sweep = wk_page.evaluate(_CELL_SWEEP_JS, [_cell("r"), _cell("o")])
    assert sweep["width"][0] == sweep["width"][1]
    rows = sweep["out"]
    # The booth line has no mark on a ranked cell, so it truncates exactly as on a plain one.
    assert all(
        (r["ranked"]["booth"], r["ranked"]["boothCut"])
        == (r["plain"]["booth"], r["plain"]["boothCut"])
        for r in rows
    )
    assert all(r["ranked"]["h"] == r["plain"]["h"] for r in rows)
    # Once both matchups truncate, the plain one shows exactly the badge's 20px more.
    last = rows[-1]
    assert last["ranked"]["matchCut"] and last["plain"]["matchCut"]
    assert last["plain"]["match"] - last["ranked"]["match"] == 20
    # Short text fits on both; somewhere only the ranked cell cuts (the plain one uses the room).
    assert not rows[0]["ranked"]["matchCut"] and not rows[0]["plain"]["matchCut"]
    assert any(r["ranked"]["matchCut"] and not r["plain"]["matchCut"] for r in rows)
    assert not any(r["plain"]["matchCut"] and not r["ranked"]["matchCut"] for r in rows)


def test_cell_marks_never_cover_the_text(wk_page: Page) -> None:  # noqa: F811
    _mount(
        wk_page,
        [_known(key="b", awayRank=20, homeRank=5, rivalry="Lakeshore Rivalry")],
    )
    wk_page.evaluate(_CELL_SWEEP_JS, [_cell("b"), _cell("b")])  # leaves both lines cut
    sel = _cell("b")
    match = wk_page.locator(f"{sel} .wk-match").bounding_box()
    booth = wk_page.locator(f"{sel} .wk-booth").bounding_box()
    badge = _badge_box(wk_page, sel)
    swords = wk_page.locator(f"{sel} .rv-mark").bounding_box()
    assert match is not None and booth is not None and swords is not None
    assert match["x"] + match["width"] <= badge["x"] - 3.5
    assert booth["x"] + booth["width"] <= swords["x"] - 3.5


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


def test_phone_rows_reserve_room_only_for_the_marks_they_show(phone_page: Page) -> None:  # noqa: F811
    """User 2026-11-11: a phone row's text wraps on what is visible. Every row keeps its 16px
    padding; the matchup lines give up 12px more only for a mark on them, and the booth line
    only for the swords under a badge."""
    _mount_phone(
        phone_page,
        [
            _known(key="r", awayRank=20, homeRank=5, home="R"),
            _known(key="v", awayRank=20, home="V", rivalry="Lakeshore Rivalry"),
            _known(key="b", awayRank=20, homeRank=5, home="B", rivalry="Lakeshore Rivalry"),
            _known(key="o", awayRank=20, homeRank=None, home="R"),
        ],
    )
    sel = '#wk-host .wk-item[data-wk-id="g:%s"]'
    style = (
        "e => [getComputedStyle(e).paddingRight,"
        " getComputedStyle(e.querySelector('.wk-item-l1')).marginRight,"
        " getComputedStyle(e.querySelector('.wk-item-l2')).marginRight]"
    )
    got = {k: phone_page.locator(sel % k).evaluate(style) for k in ("r", "v", "b", "o")}
    assert got == {
        "r": ["16px", "12px", "0px"],
        "v": ["16px", "12px", "0px"],
        "b": ["16px", "12px", "12px"],
        "o": ["16px", "0px", "0px"],
    }
    rows = phone_page.evaluate(_ROW_SWEEP_JS, [sel % "r", sel % "o"])
    # The booth line has no mark on a ranked row, so it wraps exactly as on a plain one.
    assert all(r["ranked"]["l2"] == r["plain"]["l2"] for r in rows)
    # The plain matchup never needs more lines, and somewhere wraps later (uses the room).
    assert all(r["plain"]["l1"] <= r["ranked"]["l1"] for r in rows)
    assert any(r["plain"]["l1"] < r["ranked"]["l1"] for r in rows)
    assert len({r["plain"]["l1"] for r in rows}) >= 2


def test_phone_row_marks_share_the_badge_slot(phone_page: Page) -> None:  # noqa: F811
    """B2 (user 2026-11-11): the swords alone sit where the badge would; under a badge they
    centre on the booth line, in the same column, 6px in from the row's edge."""
    _mount_phone(
        phone_page,
        [
            _known(key="r", awayRank=20, homeRank=5, home="R"),
            _known(key="v", awayRank=20, home="V", rivalry="Lakeshore Rivalry"),
            _known(key="b", awayRank=20, homeRank=5, home="B", rivalry="Lakeshore Rivalry"),
        ],
    )
    sel = '#wk-host .wk-item[data-wk-id="g:%s"]'

    def centre(selector: str) -> tuple[float, float]:
        box = phone_page.locator(selector).bounding_box()
        assert box is not None
        return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

    row = phone_page.locator(sel % "r").bounding_box()
    assert row is not None
    rx, _ = centre(f"{sel % 'r'} .rk-badge")
    assert abs((row["x"] + row["width"] - rx) - 15) < 0.6  # 18px slot, 6px in
    vx, _ = centre(f"{sel % 'v'} .rv-mark")
    assert abs(vx - rx) < 0.6
    bx, by = centre(f"{sel % 'b'} .rv-mark")
    _, l2y = centre(f"{sel % 'b'} .wk-item-l2")
    badge_box = phone_page.locator(f"{sel % 'b'} .rk-badge").bounding_box()
    swords_box = phone_page.locator(f"{sel % 'b'} .rv-mark").bounding_box()
    assert badge_box is not None and swords_box is not None
    assert abs(bx - rx) < 0.6
    assert abs(by - l2y) < 0.6
    assert swords_box["y"] >= badge_box["y"] + badge_box["height"] - 0.5


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
