"""This weekend marks (user picks 2026-11-11): the rivalry swords on CFB timeline cells and phone
rows in the badge corner (B2), their accessible name, and the centred network logos in the
timeline's row-label column and the phone rows' logo slot. Synthetic games only."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page
from test_site_weekend_cfb import (
    serve_weekend,  # noqa: F401  (fixture)
    wk,  # noqa: F401  (fixture)
)
from test_site_weekend_render import (
    _cell,
    _known,
    _mount,
    _mount_phone,
    phone_page,  # noqa: F401  (fixture)
    wk_page,  # noqa: F401  (fixture)
)

pytestmark = pytest.mark.e2e

RIVALRY = "Lakeshore Rivalry"


def _box(page: Page, selector: str) -> dict[str, float]:
    box = page.locator(selector).bounding_box()
    assert box is not None
    return box


def _centre(box: dict[str, float]) -> tuple[float, float]:
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def test_cell_rivalry_mark_name_and_colour(wk_page: Page) -> None:  # noqa: F811
    _mount(
        wk_page,
        [
            _known(key="v", rivalry=RIVALRY),
            _known(
                key="b",
                awayRank=20,
                homeRank=5,
                rivalry=RIVALRY,
                networkId="cbs",
                networkName="CBS",
                family="cbs",
            ),
            _known(key="o", networkId="abc", networkName="ABC", family="disney"),
        ],
    )
    v = wk_page.locator(_cell("v"))
    assert (v.get_attribute("aria-label") or "").endswith(f" Rivalry: {RIVALRY}.")
    both = wk_page.locator(_cell("b")).get_attribute("aria-label") or ""
    assert both.endswith(f" Both teams ranked. Rivalry: {RIVALRY}.")
    mark = v.locator(".rv-mark")
    assert mark.count() == 1
    assert mark.get_attribute("aria-hidden") == "true"
    assert mark.get_attribute("title") == f"Rivalry: {RIVALRY}"
    assert "rv-has" in (v.get_attribute("class") or "")
    # The swords draw in the cell's own text colour, never the rivalry red.
    colours = v.evaluate(
        "e => [getComputedStyle(e).color, getComputedStyle(e.querySelector('.rv-mark svg')).color]"
    )
    assert colours[0] == colours[1]
    plain = wk_page.locator(_cell("o"))
    assert plain.locator(".rv-mark").count() == 0
    assert "Rivalry" not in (plain.get_attribute("aria-label") or "")


def test_cell_rivalry_mark_takes_the_badge_corner(wk_page: Page) -> None:  # noqa: F811
    """B2: alone, the swords sit in the badge's slot (top right, 6px in); with the badge, they
    sit under it on the booth line, in the same column. The cell never grows."""
    _mount(
        wk_page,
        [
            _known(key="r", awayRank=20, homeRank=5),
            _known(key="v", rivalry=RIVALRY, networkId="cbs", networkName="CBS", family="cbs"),
            _known(
                key="b",
                awayRank=20,
                homeRank=5,
                rivalry=RIVALRY,
                networkId="abc",
                networkName="ABC",
                family="disney",
            ),
        ],
    )
    badge_x, badge_y = _centre(_box(wk_page, f"{_cell('r')} .rk-badge"))
    cell_r = _box(wk_page, _cell("r"))
    assert abs((cell_r["x"] + cell_r["width"] - badge_x) - 15) < 0.6
    lone = _box(wk_page, f"{_cell('v')} .rv-mark")
    lx, ly = _centre(lone)
    cell_v = _box(wk_page, _cell("v"))
    assert abs((cell_v["x"] + cell_v["width"] - lx) - 15) < 0.6
    assert abs((ly - cell_v["y"]) - (badge_y - cell_r["y"])) < 0.6
    assert lone["width"] == pytest.approx(16, abs=0.1)
    cell_b = _box(wk_page, _cell("b"))
    badge_b = _box(wk_page, f"{_cell('b')} .rk-badge")
    swords_b = _box(wk_page, f"{_cell('b')} .rv-mark")
    sx, sy = _centre(swords_b)
    bx, _ = _centre(badge_b)
    _, booth_y = _centre(_box(wk_page, f"{_cell('b')} .wk-line2"))
    assert abs(sx - bx) < 0.6
    assert abs(sy - booth_y) < 1
    assert swords_b["y"] >= badge_b["y"] + badge_b["height"] - 0.5
    assert swords_b["y"] + swords_b["height"] <= cell_b["y"] + cell_b["height"]
    assert cell_b["height"] == cell_r["height"] == cell_v["height"]


def test_phone_row_rivalry_mark_name(phone_page: Page) -> None:  # noqa: F811
    _mount_phone(phone_page, [_known(key="v", home="V", rivalry=RIVALRY)])
    row = phone_page.locator('#wk-host .wk-item[data-wk-id="g:v"]')
    assert (row.get_attribute("aria-label") or "").endswith(f" Rivalry: {RIVALRY}.")
    assert row.locator(".wk-item-mu .rv-mark").get_attribute("aria-hidden") == "true"


def test_nfl_cells_never_show_the_rivalry_mark(wk_page: Page) -> None:  # noqa: F811
    _mount(wk_page, [_known(key="n", sport="nfl")], model={"sport": "nfl"})
    assert wk_page.locator(f"{_cell('n')} .rv-mark").count() == 0


def test_scheduled_rivalry_game_shows_the_mark(wk: Callable[..., Page]) -> None:  # noqa: F811
    """Contract 2.9.0: a scheduled game (no telecast row yet) carries its rivalry, and This
    weekend marks it like any other."""

    def tweak(raw: dict[str, Any]) -> None:
        sched = raw["telecasts_scheduled"]
        # Row 0 becomes Northfield (0) at Lakeview (1), the fixture's Lakeshore Rivalry (1).
        sched["home_team"][0] = 1
        sched["rivalry"][0] = 1

    page = wk("?view=weekend&week=5&day=sat", tweak=tweak)
    page.wait_for_selector("#weekend-panel .wk-cell", timeout=10000)
    cell = page.locator("#weekend-panel .wk-cell", has_text="Northfield @ Lakeview")
    assert cell.count() == 1
    assert cell.locator(".rv-mark").count() == 1
    assert (cell.get_attribute("aria-label") or "").endswith(f" Rivalry: {RIVALRY}.")
    # An untagged scheduled game shows no mark.
    other = page.locator("#weekend-panel .wk-cell", has_text="Boulder Pass @ Maplecrest")
    assert other.count() == 1
    assert other.locator(".rv-mark").count() == 0


_LOGO_CENTRES_JS = """(sel) => [...document.querySelectorAll(sel)].map((slot) => {
  const s = slot.getBoundingClientRect();
  const cs = getComputedStyle(slot);
  const left = s.left + parseFloat(cs.paddingLeft) + parseFloat(cs.borderLeftWidth);
  const right = s.right - parseFloat(cs.paddingRight) - parseFloat(cs.borderRightWidth);
  const img = slot.querySelector('img.net-logo');
  if (!img) return null;
  // object-fit: contain draws the image at its natural aspect ratio inside the box.
  const r = img.getBoundingClientRect();
  const ratio = img.naturalWidth / img.naturalHeight;
  const drawn = Math.min(r.width, r.height * ratio);
  const pos = getComputedStyle(img).objectPosition.split(' ')[0];
  const offset = pos.endsWith('%') ? (r.width - drawn) * parseFloat(pos) / 100 : parseFloat(pos);
  const centre = r.left + offset + drawn / 2;
  return { slot: (left + right) / 2, logo: centre };
}).filter(Boolean)"""


def test_row_label_logos_are_centred(wk_page: Page) -> None:  # noqa: F811
    _mount(
        wk_page,
        [
            _known(key="f"),
            _known(key="a", networkId="abc", networkName="ABC", family="disney"),
            _known(key="c", networkId="cbs", networkName="CBS", family="cbs"),
        ],
    )
    wk_page.wait_for_function(
        "() => [...document.querySelectorAll('#wk-host .wk-rowhead img')]"
        ".every((i) => i.complete && i.naturalWidth > 0)"
    )
    got = wk_page.evaluate(_LOGO_CENTRES_JS, "#wk-host .wk-rowhead")
    assert len(got) == 3
    for row in got:
        assert abs(row["logo"] - row["slot"]) < 0.6


def test_phone_logo_slot_is_centred(phone_page: Page) -> None:  # noqa: F811
    _mount_phone(
        phone_page,
        [
            _known(key="f", home="F"),
            _known(key="a", home="A", networkId="abc", networkName="ABC", family="disney"),
        ],
    )
    phone_page.wait_for_function(
        "() => [...document.querySelectorAll('#wk-host .wk-item-mark img')]"
        ".every((i) => i.complete && i.naturalWidth > 0)"
    )
    got = phone_page.evaluate(_LOGO_CENTRES_JS, "#wk-host .wk-item-mark")
    assert len(got) == 2
    for row in got:
        assert abs(row["logo"] - row["slot"]) < 0.6
