"""04.19-09 e2e: second-source (non-Ratings Reference) figure credit on the synthetic fixture.

Fixture telecast 3 is a Sports Media Watch figure (empty rr_urls, SMW season-page
source_url, 2021 game between Stonebridge and Maplecrest); telecast 0 is an RR row.
Telecast 8 (Plan 49) is an ESPN Press Room backup crew: its crew credit reads
"Crew source: ESPN Press Room" and links the release, in place of the 506 listing.
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
BACKUP_INDEX = 8
ESPNPR_URL_PREFIX = "https://espnpressroom.com/"


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
    assert "; " in cell.inner_text()
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


def test_backup_crew_panel_credits_espn_press_room(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    """04.19 D-13 (04.3 D-11): a backup crew credits its ESPN Press Room page, last in
    Links, through the same crew-source link a hand-confirmed crew uses; no 506 link."""
    assert fixture_raw["telecasts"]["crew_source_label"][BACKUP_INDEX] == "ESPN Press Room"
    assert fixture_raw["telecasts"]["s506_url"][BACKUP_INDEX] is not None
    open_app(guarded_page, "")
    guarded_page.evaluate(f"window.__testHooks.openPanel({BACKUP_INDEX})")
    body = guarded_page.locator("#panel-body")
    link = body.locator("a:has-text('Crew source: ESPN Press Room ↗')")
    expect(link).to_have_count(1)
    href = link.get_attribute("href") or ""
    assert href.startswith(ESPNPR_URL_PREFIX)
    assert href == fixture_raw["telecasts"]["crew_source_url"][BACKUP_INDEX]
    expect(link).to_have_attribute("target", "_blank")
    expect(link).to_have_attribute("rel", "noopener noreferrer")
    expect(body.locator("a:has-text('View 506 Sports listing')")).to_have_count(0)
    expect(body.locator(".panel-links li").last).to_contain_text("Crew source: ESPN Press Room")


def test_backup_crew_unsafe_url_degrades_to_plain_text(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    """T-04.19-41-01: an unsafe backup-crew URL renders plain text, no link, no arrow."""
    raw = copy.deepcopy(fixture_raw)
    raw["telecasts"]["crew_source_url"][BACKUP_INDEX] = "javascript:alert(1)"
    guarded_page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    open_app(guarded_page, "")
    guarded_page.evaluate(f"window.__testHooks.openPanel({BACKUP_INDEX})")
    body = guarded_page.locator("#panel-body")
    expect(body.locator("a:has-text('Crew source')")).to_have_count(0)
    links = body.locator(".panel-links").inner_text()
    assert "Crew source: ESPN Press Room" in links
    assert "Crew source: ESPN Press Room ↗" not in links
    expect(body.locator("a:has-text('View 506 Sports listing')")).to_have_count(0)


# -- RT-08 / RT-09: The TV Ratings Guide, Awful Announcing and ESPN Press Room figures ----------
# The contract fixture carries no TVRG, AA or ESPN Press Room figure row, so the telecast-3 row
# (an SMW row with no Ratings Reference records) is re-served with another figure source, its
# publisher name and a same-publisher source URL. The fixture file's contract shape is unchanged.

_NOT_VIA_RR = "not listed on Ratings Reference."
_SECOND_SOURCES = [
    (
        "tvrg",
        "The TV Ratings Guide",
        "https://tvratingsguide.com/2021/10/example-ratings-post/",
        f"Figure read from The TV Ratings Guide's ratings post; {_NOT_VIA_RR}",
    ),
    (
        "aa",
        "Awful Announcing",
        "https://awfulannouncing.com/2021/example-ratings-post.html",
        f"Figure read from Awful Announcing's ratings post; {_NOT_VIA_RR}",
    ),
    (
        "espnpr",
        "ESPN Press Room",
        "https://espnpressroom.com/us/press-releases/2021/10/example-release/",
        f"Figure read from an ESPN Press Room release; {_NOT_VIA_RR}",
    ),
]


def _serve_second_source(
    page: Page, fixture_raw: dict[str, Any], source: str, publisher: str, url: str
) -> None:
    raw = copy.deepcopy(fixture_raw)
    raw["lookups"]["publishers"][raw["telecasts"]["publisher"][SMW_INDEX]] = publisher
    raw["telecasts"]["figure_source"][SMW_INDEX] = source
    raw["telecasts"]["source_url"][SMW_INDEX] = url
    assert raw["telecasts"]["rr_urls"][SMW_INDEX] == []
    page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))


@pytest.mark.parametrize(("source", "publisher", "url", "line"), _SECOND_SOURCES)
def test_second_source_panel_line_and_publisher_link(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
    source: str,
    publisher: str,
    url: str,
    line: str,
) -> None:
    """RT-08 exact panel line and RT-09 panel link for each non-SMW second source."""
    _serve_second_source(guarded_page, fixture_raw, source, publisher, url)
    open_app(guarded_page, "")
    guarded_page.evaluate(f"window.__testHooks.openPanel({SMW_INDEX})")
    body = guarded_page.locator("#panel-body")
    assert line in body.locator("p").all_inner_texts()
    link = body.locator(f"a:text-is('View original source ({publisher}) ↗')")
    expect(link).to_have_count(1)
    expect(link).to_have_attribute("href", url)
    expect(link).to_have_attribute("target", "_blank")
    expect(link).to_have_attribute("rel", "noopener noreferrer")
    expect(body.locator("a:has-text('View record')")).to_have_count(0)


@pytest.mark.parametrize(("source", "publisher", "url", "line"), _SECOND_SOURCES)
def test_second_source_table_cell_is_publisher_link_only(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
    source: str,
    publisher: str,
    url: str,
    line: str,
) -> None:
    """RT-09 table cell: the publisher name linked to the figure's page, no Ratings Reference."""
    _serve_second_source(guarded_page, fixture_raw, source, publisher, url)
    open_app(guarded_page, "?school=stonebridge")
    cell = _smw_row(guarded_page).locator("td").last
    links = cell.locator("a")
    expect(links).to_have_count(1)
    expect(links.first).to_have_text(publisher)
    expect(links.first).to_have_attribute("href", url)
    expect(links.first).to_have_attribute("target", "_blank")
    expect(links.first).to_have_attribute("rel", "noopener noreferrer")
    text = cell.inner_text()
    assert "·" not in text
    assert "Ratings Reference" not in text
