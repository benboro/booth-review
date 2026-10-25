"""09-29: the MLB methodology and known-gaps blocks render only on an MLB-enabled site."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_RETROSHEET = (
    "The information used here was obtained free of charge from and is copyrighted by "
    "Retrosheet. Interested parties may contact Retrosheet at www.retrosheet.org."
)


def test_methodology_shows_the_mlb_block_when_mlb_is_on(
    mlb_guarded_page: Page, mlb_site_url: str
) -> None:
    mlb_guarded_page.goto(f"{mlb_site_url}/methodology.html")
    text = " ".join(mlb_guarded_page.inner_text("body").split())
    assert "MLB: Stakes" in text
    assert "pending Retrosheet 2026" in text
    assert _RETROSHEET in text
    assert "<!--" not in mlb_guarded_page.content().replace("<!---->", "")


def test_known_gaps_shows_the_mlb_block_when_mlb_is_on(
    mlb_guarded_page: Page, mlb_site_url: str
) -> None:
    mlb_guarded_page.goto(f"{mlb_site_url}/methodology.html")
    text = mlb_guarded_page.inner_text("body")
    assert "Division Series" in text
    assert "2020 Wild Card network map is left open" in text


def test_methodology_has_no_mlb_text_when_mlb_is_off(guarded_page: Page, site_url: str) -> None:
    guarded_page.goto(f"{site_url}/methodology.html")
    text = guarded_page.inner_text("body")
    assert "MLB: Stakes" not in text
    assert "Retrosheet" not in text
    assert "Division Series" not in text


def test_methodology_explains_cell_flags_and_scatter_strips(
    mlb_guarded_page: Page, mlb_site_url: str
) -> None:
    mlb_guarded_page.goto(f"{mlb_site_url}/methodology.html")
    text = " ".join(mlb_guarded_page.inner_text("body").split())
    assert (
        "In the Apple crews table, a Stakes or Excitement figure resting on fewer than that "
        "many games is marked n < 10 in its own cell; the row is not faded." in text
    )
    assert (
        "The Scatter plots one dot per game, viewers against excitement. Games with no public "
        "rating sit in a strip along the bottom and games with no excitement figure in a strip "
        "on the left, so no game is left out." in text
    )


def test_methodology_flag_off_has_no_scatter_strip_text(guarded_page: Page, site_url: str) -> None:
    guarded_page.goto(f"{site_url}/methodology.html")
    text = " ".join(guarded_page.inner_text("body").split())
    assert "so no game is left out" not in text
    assert "the row is not faded" not in text
