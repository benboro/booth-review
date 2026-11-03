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
    assert r["hidden"] == {"ariaHidden": "true", "focusable": "false", "role": None, "label": None}
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
