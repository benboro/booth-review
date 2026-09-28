"""Static-page tests: D-16 credits, freshness stamps, nav, methodology
anchors, the coverage table, and the site-data.json payload -- proven in a
real browser against the fixture build served by `guarded_page`/`site_url`.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_PAGES = ("index.html", "methodology.html", "coverage.html")

_CREDIT_LINE = (
    "Viewership: RatingsReference.com (CC BY 4.0), modified: filtered and "
    "joined with crew and game data · Crews: 506 Sports · "
    "Data provided by CollegeFootballData.com"
)

_CREDIT_LINKS = (
    ("RatingsReference.com", "https://ratingsreference.com"),
    ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"),
    ("506 Sports", "https://506sports.com"),
    ("CollegeFootballData.com", "https://collegefootballdata.com"),
)


@pytest.mark.parametrize("page_name", _PAGES)
def test_footer_credits_freshness_and_nav(
    guarded_page: Page, site_url: str, page_name: str
) -> None:
    """Every page carries the D-16 credit line (with its four links), both
    freshness stamps, and the Chart/Methodology/Coverage nav."""
    guarded_page.goto(f"{site_url}/{page_name}")

    footer_text = re.sub(r"\s+", " ", guarded_page.inner_text("footer")).strip()
    assert _CREDIT_LINE in footer_text
    assert "Crews and scores through Week 5" in footer_text
    assert "Viewership through Week 4" in footer_text

    for label, href in _CREDIT_LINKS:
        link = guarded_page.locator(f"footer a:text-is('{label}')")
        assert link.count() == 1
        assert link.get_attribute("href") == href

    for nav_label in ("Chart", "Methodology", "Coverage"):
        assert guarded_page.locator(f"nav a:text-is('{nav_label}')").count() == 1


def test_methodology_page_has_expected_heading_anchors(guarded_page: Page, site_url: str) -> None:
    guarded_page.goto(f"{site_url}/methodology.html")
    for heading_id in (
        "the-2025-excitement-break",
        "measurement-eras",
        "known-gaps",
        "sources-and-credits",
    ):
        assert guarded_page.locator(f"#{heading_id}").count() == 1


def test_coverage_page_has_a_total_row(guarded_page: Page, site_url: str) -> None:
    guarded_page.goto(f"{site_url}/coverage.html")
    table = guarded_page.locator("table.coverage-table")
    assert table.count() == 1
    assert "Total" in table.inner_text()


def test_site_data_json_is_reachable_and_matches_the_contract_version(
    guarded_page: Page, site_url: str
) -> None:
    guarded_page.goto(f"{site_url}/index.html")
    response = guarded_page.request.get(f"{site_url}/site-data.json")
    assert response.status == 200
    assert response.json()["schema_version"] == "1.1.0"


_BOX_JS = """
(selector) => {
  const r = document.querySelector(selector).getBoundingClientRect();
  return {x: r.x, width: r.width, height: r.height};
}
"""


@pytest.mark.parametrize("page_name", ("methodology.html", "coverage.html"))
def test_secondary_pages_do_not_inherit_the_chart_grid(
    guarded_page: Page, site_url: str, page_name: str
) -> None:
    """WR-05: the chart page's 280px-rail grid is scoped to index.html, so on
    the methodology/coverage pages the header and footer (with the D-16
    credit line) span the page instead of being squeezed into the rail
    column, and the content column is centered."""
    guarded_page.set_viewport_size({"width": 1400, "height": 900})
    guarded_page.goto(f"{site_url}/{page_name}")

    assert guarded_page.evaluate("getComputedStyle(document.body).display") == "block"
    viewport = guarded_page.evaluate("document.documentElement.clientWidth")

    footer = guarded_page.evaluate(_BOX_JS, "footer")
    assert footer["x"] == 0
    assert footer["width"] == viewport

    header = guarded_page.evaluate(_BOX_JS, "header")
    assert header["width"] == viewport
    assert header["height"] < 100

    main = guarded_page.evaluate(_BOX_JS, "main.page")
    assert abs((main["x"] + main["width"] / 2) - viewport / 2) <= 1


def test_chart_page_keeps_its_grid(guarded_page: Page, site_url: str) -> None:
    """WR-05: scoping the grid to `body.app` leaves the chart page's own
    rail + chart layout in place."""
    guarded_page.set_viewport_size({"width": 1400, "height": 900})
    guarded_page.goto(f"{site_url}/index.html")
    assert guarded_page.evaluate("getComputedStyle(document.body).display") == "grid"
    rail = guarded_page.evaluate(_BOX_JS, "#rail")
    assert rail["x"] == 0
    assert rail["width"] == 280
