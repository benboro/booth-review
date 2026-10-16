"""09-19: the MLB Apple crews view on the synthetic MLB fixture.

Fixture booths: 0 Ada Quill / Ben Marlow (Lead, 2 games, 1 from the relay), 1 Cy Fable /
Dee Hart (#2, 2 games, 1 relay), 2 Eli Stroud / Fay Lorn (#3, 1 game, low n). Every
booth is quality-pending in the fixture; tests that need ready data rewrite the response.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from playwright.sync_api import Page, Route

pytestmark = pytest.mark.e2e

HOOKS = "window.__mlbTestHooks"


@pytest.fixture
def mlb(mlb_guarded_page: Page, open_mlb_app: Callable[..., None]) -> Page:
    open_mlb_app(mlb_guarded_page)
    return mlb_guarded_page


def _ready_open(
    page: Page, open_mlb_app: Callable[..., None], **summary: float | int | None
) -> None:
    """Open the app with the booths marked ready and the given apple_summary overrides."""

    def handler(route: Route) -> None:
        resp = route.fetch()
        data = json.loads(resp.text())
        b = data["apple_booths"]
        b["quality_status"] = ["ready"] * len(b["quality_status"])
        b["raw_stakes"] = [1.10, 0.95, 1.30]
        b["adj_stakes"] = [0.20, -0.10, 0.05]
        b["adj_stakes_se"] = [0.05, 0.06, 0.20]
        b["raw_excitement"] = [1.5, 1.2, 1.9]
        b["adj_excitement"] = [0.30, -0.20, 0.10]
        b["adj_excitement_se"] = [0.04, 0.05, 0.30]
        b["strength_prior"] = [0.553, 0.5, 0.48]
        data["apple_summary"].update(summary)
        data["freshness"]["quality_pending"] = False
        route.fulfill(response=resp, body=json.dumps(data))

    page.route("**/mlb-data.json", handler)
    open_mlb_app(page)


def test_rows_rank_labels_and_names(mlb: Page) -> None:
    rows = mlb.locator("#mlb-view-apple tbody tr")
    assert rows.count() == 3
    ranks = mlb.eval_on_selector_all(
        "#mlb-view-apple .booth-rank", "els => els.map(e => e.textContent)"
    )
    assert ranks == ["Lead", "#2", "#3"]
    first = rows.nth(0).inner_text()
    assert "Ada Quill" in first
    assert "Ben Marlow" in first
    assert rows.nth(0).locator(".role-pill").count() == 2
    heads = mlb.eval_on_selector_all(
        "#mlb-view-apple thead th", "els => els.map(e => e.textContent)"
    )
    assert heads == [
        "Booth",
        "Games",
        "Crew listed",
        "Stakes",
        "Excitement",
        "2025 win % of both clubs",
    ]
    assert mlb.locator("#mlb-tab-apple[aria-selected='true']").count() == 1


def test_coverage_line_comes_from_data(mlb: Page) -> None:
    text = mlb.inner_text("#mlb-view-apple .nfl-coverage")
    assert text == "Crew listed for 5 of 6 Apple games. 2 from the relay."
    assert "1 from relay" in mlb.locator("#mlb-view-apple tbody tr").nth(0).inner_text()


def test_pending_cells_and_lead_lines(mlb: Page) -> None:
    cells = mlb.locator("#mlb-view-apple td.mlb-pending")
    assert cells.count() == 6
    assert set(cells.all_inner_texts()) == {"pending Retrosheet 2026"}
    lines = mlb.locator("#mlb-view-apple .mlb-lead-line")
    assert lines.count() == 2
    assert lines.nth(0).get_attribute("data-measure") == "stakes"
    assert "pending Retrosheet 2026" in lines.nth(0).inner_text()
    assert "late in 2026" in mlb.inner_text("#mlb-view-apple .mlb-pending-note")


def test_low_n_booth_is_faded_and_tagged(mlb: Page) -> None:
    low = mlb.locator("#mlb-view-apple tbody tr[data-low-n='true']")
    assert low.count() == 3  # 2, 2 and 1 games are all under the threshold of 8
    assert low.nth(2).locator(".low-n-tag").inner_text() == "low n"
    assert mlb.evaluate(f"{HOOKS}.getViewModel('apple').rows.every(r => r.lowN)")


def test_rr_note_uses_summary_counts(
    mlb: Page, mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    assert (
        mlb.inner_text("#mlb-view-apple .mlb-rr-note")
        == "Ratings Reference has a figure for 1 of Apple's 6 games."
    )
    page = mlb_guarded_page
    page.unroute_all()
    _ready_open(page, open_mlb_app, rr_rated=0, apple_games=40)
    assert (
        page.inner_text("#mlb-view-apple .mlb-rr-note")
        == "Ratings Reference has no figure for any of Apple's 40 games."
    )


def test_ready_values_raw_then_adjusted(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    _ready_open(page, open_mlb_app)
    cells = page.locator("#mlb-view-apple tbody tr").nth(0).locator("td")
    assert cells.nth(0).inner_text() == "2"
    assert cells.nth(2).inner_text() == "1.10"
    assert cells.nth(3).inner_text() == "1.50"
    assert cells.nth(4).inner_text() == "55.3%"
    page.click("#mlb-view-apple .segmented button[data-value='adjusted']")
    cells = page.locator("#mlb-view-apple tbody tr").nth(0).locator("td")
    assert cells.nth(2).inner_text().replace("\n", " ") == "+0.20 ±0.10"
    assert (
        page.locator("#mlb-view-apple tbody tr")
        .nth(1)
        .locator("td")
        .nth(2)
        .inner_text()
        .startswith("\u22120.10")
    )
    assert "tendency, not proof" in page.inner_text("#mlb-view-apple .nfl-captions")
    assert "pending" not in page.inner_text("#mlb-view-apple tbody").lower()


def test_difference_line_and_spanning_zero(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    _ready_open(
        page,
        open_mlb_app,
        lead_minus_others_stakes=0.30,
        lead_minus_others_stakes_se=0.05,
        lead_minus_others_excitement=0.10,
        lead_minus_others_excitement_se=0.20,
        n_lead=12,
        n_others=30,
    )
    stakes = page.inner_text("#mlb-view-apple .mlb-lead-line[data-measure='stakes']")
    assert "+0.30 ±0.10" in stakes
    assert "12 games for the lead booth, 30 for the others" in stakes
    excitement = page.inner_text("#mlb-view-apple .mlb-lead-line[data-measure='excitement']")
    assert "too few games to call a difference" in excitement
    assert "p =" not in stakes
    assert "win" not in (stakes + excitement).lower()


def test_row_click_lists_booth_games_and_toggles(mlb: Page) -> None:
    mlb.click("#mlb-view-apple .booth-row-btn >> nth=1")
    assert mlb.evaluate(f"{HOOKS}.getTableIndexes()") == [3, 2]
    assert mlb.locator("#mlb-view-apple .booth-row-btn[aria-pressed='true']").count() == 1
    assert "booth=1" in mlb.url
    mlb.click("#mlb-view-apple .booth-row-btn >> nth=1")
    assert mlb.evaluate(f"{HOOKS}.getTableIndexes()") == []
    assert "booth=" not in mlb.url
