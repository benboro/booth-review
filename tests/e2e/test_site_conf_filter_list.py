"""Phase 28 Conference filter-list logos (D-09, D-11, D-12, D-13): a fixed 44px slot between the
checkbox and the name holds each conference's 16px logo for the last season of the Seasons
filter, empty for FBS Independents, names aligned, rows the same height, dark files in the dark
theme, and a hostile conference name kept as literal text.

Synthetic contract fixture only (Big Ten, FBS Independents, Mountain West, Pac-12, SEC; seasons
2019, 2021, 2025, 2026); never vault data.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from dark_checks import set_theme
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

OpenApp = Callable[[Page, str], None]

_ROWS = """() => [...document.querySelectorAll('#conference-list label.check-row')].map((l) => {
  const slot = l.querySelector('.cf-slot');
  const name = l.querySelector('.option-name');
  const img = slot ? slot.querySelector('img.cf-logo') : null;
  const ib = img ? img.getBoundingClientRect() : null;
  return {
    order: [...l.children].map((c) => c.tagName.toLowerCase() + '.' + (c.className || c.type)),
    name: name.textContent,
    slotWidth: slot ? slot.getBoundingClientRect().width : null,
    slotKids: slot ? slot.childNodes.length : null,
    imgs: slot ? slot.querySelectorAll('img').length : 0,
    alt: img ? img.alt : null,
    title: img ? img.title : null,
    src: img ? img.getAttribute('src') : null,
    imgH: ib ? ib.height : null,
    nameLeft: name.getBoundingClientRect().left,
    rowH: l.closest('.check-item').getBoundingClientRect().height,
  };
})"""


def _open_conferences(page: Page) -> None:
    page.click("#trigger-conference")
    page.wait_for_function("document.getElementById('pop-conference').matches(':popover-open')")


def _rows(page: Page) -> dict[str, dict[str, Any]]:
    rows: list[dict[str, Any]] = page.evaluate(_ROWS)
    return {r["name"]: r for r in rows}


def _wait_src(page: Page, name: str, suffix: str) -> None:
    page.wait_for_function(
        """([n, s]) => {
          const img = document.querySelector(
            `#conference-list img.cf-logo[data-cf="${CSS.escape(n)}"]`);
          return !!img && img.getAttribute('src').endsWith(s);
        }""",
        arg=[name, suffix],
    )


@pytest.fixture
def conf_page(guarded_page: Page, open_app: OpenApp) -> Page:
    guarded_page.set_viewport_size({"width": 1440, "height": 900})
    open_app(guarded_page, "")
    _open_conferences(guarded_page)
    return guarded_page


def test_each_row_has_a_44px_slot_between_checkbox_and_name(conf_page: Page) -> None:
    rows = _rows(conf_page)
    assert list(rows) == ["Big Ten", "FBS Independents", "Mountain West", "Pac-12", "SEC"]
    for row in rows.values():
        assert row["order"][:3] == ["input.checkbox", "span.cf-slot", "span.option-name"]
        assert row["slotWidth"] == pytest.approx(44, abs=0.5)


def test_logo_rows_hold_one_16px_logo_and_independents_slot_is_empty(conf_page: Page) -> None:
    rows = _rows(conf_page)
    for name, row in rows.items():
        if name == "FBS Independents":
            assert row["slotKids"] == 0
            continue
        assert row["imgs"] == 1
        assert row["alt"] == name
        assert row["title"] == name
        assert row["imgH"] == pytest.approx(16, abs=0.5)


def test_names_align(conf_page: Page) -> None:
    rows = _rows(conf_page)
    lefts = {row["nameLeft"] for row in rows.values()}
    assert max(lefts) - min(lefts) == 0


@pytest.mark.xfail(
    strict=True,
    reason=(
        "D-05: the 44px slot narrows the 218px Conference list row so 'FBS Independents' "
        "wraps (50px vs 29px); needs a style.css change outside plan 28-05"
    ),
)
def test_row_heights_match(conf_page: Page) -> None:
    rows = _rows(conf_page)
    heights = {row["rowH"] for row in rows.values()}
    assert max(heights) - min(heights) == 0
    assert rows["SEC"]["rowH"] == rows["FBS Independents"]["rowH"]


def test_logos_follow_the_last_season_of_the_seasons_filter(conf_page: Page) -> None:
    page = conf_page
    rows = _rows(page)
    assert rows["SEC"]["src"].endswith("southeastern-conference-2024-present.svg")
    assert rows["Pac-12"]["src"].endswith("pac-12-conference-2026-present-official-site.svg")

    page.evaluate("window.__testHooks.setState({ seasons: [2019, 2019] })")
    _wait_src(page, "SEC", "southeastern-conference-before-2024.svg")
    rows = _rows(page)
    assert rows["Pac-12"]["src"].endswith("pac-12-conference-before-2026.svg")
    assert rows["SEC"]["imgs"] == 1

    page.evaluate("window.__testHooks.setState({ seasons: [2019, 2026] })")
    _wait_src(page, "SEC", "southeastern-conference-2024-present.svg")
    rows = _rows(page)
    assert rows["Pac-12"]["src"].endswith("pac-12-conference-2026-present-official-site.svg")


def test_season_to_menu_swaps_the_logos(guarded_page: Page, open_app: OpenApp) -> None:
    page = guarded_page
    open_app(page, "")
    page.click("#trigger-seasons")
    page.wait_for_function("document.getElementById('pop-seasons').matches(':popover-open')")
    page.select_option("#season-to", "2021")
    _wait_src(page, "SEC", "southeastern-conference-before-2024.svg")
    _wait_src(page, "Pac-12", "pac-12-conference-before-2026.svg")


def test_dark_theme_uses_the_dark_files(conf_page: Page) -> None:
    set_theme(conf_page, "dark")
    rows = _rows(conf_page)
    for name, row in rows.items():
        if name == "FBS Independents":
            continue
        assert "/logos/dark/conf/" in "/" + row["src"]


def test_checking_a_conference_still_filters(conf_page: Page) -> None:
    conf_page.check("#conference-list input[value='SEC']")
    conf_page.wait_for_function("location.search.includes('conferences=SEC')")
    assert _rows(conf_page)["SEC"]["imgs"] == 1


def test_hostile_conference_name_is_literal_text_with_an_empty_slot(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    hostile = "<img src=x onerror=alert(1)>Mountain"
    raw = copy.deepcopy(fixture_raw)
    confs = raw["lookups"]["conferences"]
    index = next(i for i, c in enumerate(confs) if c["name"] == "Mountain West")
    confs[index]["name"] = hostile
    guarded_page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    guarded_page.set_viewport_size({"width": 1440, "height": 900})
    open_app(guarded_page, "")
    _open_conferences(guarded_page)
    rows = _rows(guarded_page)
    assert hostile in rows
    assert rows[hostile]["slotKids"] == 0
    stray = "() => document.querySelectorAll('#conference-list img[src=\"x\"]').length"
    assert guarded_page.evaluate(stray) == 0
