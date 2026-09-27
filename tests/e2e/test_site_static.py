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
    assert response.json()["schema_version"] == "1.0.0"
