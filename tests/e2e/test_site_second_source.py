"""04.19-09 e2e: second-source (non-Ratings Reference) figure credit on the synthetic fixture.

Fixture telecast 3 is a Sports Media Watch figure (empty rr_urls, SMW season-page
source_url, 2021 game between Stonebridge and Maplecrest); telecast 0 is an RR row.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

SMW_INDEX = 3
SMW_URL_PREFIX = "https://www.sportsmediawatch.com/"


def _smw_row(page: Page) -> Any:
    return (
        page.locator("#games-table tbody tr")
        .filter(has_text="Stonebridge")
        .filter(has_not_text="No figure to cite")
        .first
    )


def test_smw_table_cell_is_publisher_link_only(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?school=stonebridge")
    cell = _smw_row(guarded_page).locator("td").last
    links = cell.locator("a")
    expect(links).to_have_count(1)
    expect(links.first).to_have_text("Sports Media Watch")
    href = links.first.get_attribute("href") or ""
    assert href.startswith(SMW_URL_PREFIX)
    assert links.first.get_attribute("target") == "_blank"
    assert links.first.get_attribute("rel") == "noopener noreferrer"
    text = cell.inner_text()
    assert "·" not in text
    assert "Ratings Reference" not in text


def test_rr_table_cell_keeps_separator_and_rr_link(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?school=northfield")
    cell = (
        guarded_page.locator("#games-table tbody tr")
        .filter(has=guarded_page.locator("a:text-is('Ratings Reference')"))
        .first.locator("td")
        .last
    )
    assert "·" in cell.inner_text()
    expect(cell.locator("a:text-is('Ratings Reference')")).to_have_count(1)


def test_smw_panel_credit_lines(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    open_app(guarded_page, "")
    guarded_page.evaluate(f"window.__testHooks.openPanel({SMW_INDEX})")
    body = guarded_page.locator("#panel-body")
    expect(body.locator("a:has-text('View original source (Sports Media Watch) ↗')")).to_have_count(
        1
    )
    expect(body.locator("a:has-text('View record')")).to_have_count(0)
    season = fixture_raw["telecasts"]["season"][SMW_INDEX]
    expected = (
        f"Figure read from Sports Media Watch's {season} ratings chart; "
        "not listed on Ratings Reference."
    )
    paragraphs = body.locator("p").all_inner_texts()
    assert expected in paragraphs


def test_rr_panel_has_no_not_via_rr_line(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    assert "not listed on Ratings Reference" not in guarded_page.inner_text("#panel-body")
    expect(guarded_page.locator("#panel-body a:has-text('View record')")).to_have_count(1)


def test_smw_unsafe_source_url_degrades_to_plain_text(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    raw = copy.deepcopy(fixture_raw)
    raw["telecasts"]["source_url"][SMW_INDEX] = "javascript:alert(1)"
    guarded_page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    open_app(guarded_page, "?school=stonebridge")
    cell = _smw_row(guarded_page).locator("td").last
    expect(cell.locator("a")).to_have_count(0)
    assert cell.inner_text().strip() == "Original source not recorded"
