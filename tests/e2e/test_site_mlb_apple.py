"""09-19: the MLB Apple crews view on the synthetic MLB fixture.

Fixture booths: 0 Ada Quill / Ben Marlow (Lead, 2 games, 1 from the relay), 1 Cy Fable /
Dee Hart (#2, 2 games, 1 relay), 2 Eli Stroud / Fay Lorn (#3, 1 game). Every
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


ROW = "#mlb-view-apple tr.crews-row"


def test_rows_rank_labels_and_names(mlb: Page) -> None:
    rows = mlb.locator(ROW)
    assert rows.count() == 3
    pills = mlb.eval_on_selector_all(
        f"{ROW} td.crews-col-position, {ROW} td:nth-child(2)", "els => els.map(e => e.textContent)"
    )
    assert pills == ["Lead", "#2", "#3"]
    first = rows.nth(0).inner_text()
    assert "Ada Quill" in first
    assert "Ben Marlow" in first
    assert "with" in first
    assert mlb.locator("#mlb-view-apple .crews-table.is-mlb .role-pill").count() == 0
    heads = mlb.eval_on_selector_all(
        "#mlb-view-apple thead th button .crews-sort-label", "els => els.map(e => e.textContent)"
    )
    assert heads == [
        "Booth position",
        "Booth",
        "Network",
        "Games",
        "Crew listed",
        "Stakes",
        "Excitement",
        "2025 win % of both clubs",
    ]
    sorts = mlb.eval_on_selector_all(
        "#mlb-view-apple thead th[aria-sort]", "els => els.map(e => e.getAttribute('aria-sort'))"
    )
    assert sorts == ["ascending"] + ["none"] * 7
    assert mlb.locator("#mlb-tab-apple[aria-selected='true']").count() == 1


def test_rank_pills_are_gold_and_silver(mlb: Page) -> None:
    css = mlb.evaluate(
        """() => {
          const root = getComputedStyle(document.documentElement);
          const pill = (r) =>
            document.querySelector(`#mlb-view-apple .rank-pill[data-rank="${r}"]`);
          return {
            lead: pill('lead')?.textContent, two: pill('2')?.textContent,
            leadBg: getComputedStyle(pill('lead')).backgroundColor,
            twoBg: getComputedStyle(pill('2')).backgroundColor,
            gold: root.getPropertyValue('--pill-gold-fill').trim(),
            silver: root.getPropertyValue('--pill-silver-fill').trim(),
            pills: document.querySelectorAll('#mlb-view-apple .rank-pill').length,
          };
        }"""
    )
    assert css["lead"] == "Lead"
    assert css["two"] == "#2"
    assert css["pills"] == 2  # #3 is plain text
    assert css["leadBg"] == "rgb(242, 223, 160)"
    assert css["twoBg"] == "rgb(217, 219, 223)"


def test_network_column_shows_the_apple_logo(mlb: Page) -> None:
    assert mlb.locator(f'{ROW} td.crews-network img[alt="Apple TV"]').count() == 3


def test_coverage_line_comes_from_data(mlb: Page) -> None:
    text = mlb.inner_text("#mlb-view-apple .nfl-coverage")
    assert text == "Crew listed for 5 of 6 Apple games. 2 from the relay."
    assert "1 from relay" in mlb.locator(ROW).nth(0).inner_text()


def test_pending_cells_and_lead_lines(mlb: Page) -> None:
    cells = mlb.locator("#mlb-view-apple td.mlb-pending")
    assert cells.count() == 6
    assert set(cells.all_inner_texts()) == {"pending Retrosheet 2026"}
    lines = mlb.locator("#mlb-view-apple .mlb-lead-line")
    assert lines.count() == 2
    assert lines.nth(0).get_attribute("data-measure") == "stakes"
    assert "pending Retrosheet 2026" in lines.nth(0).inner_text()
    assert "late in 2026" in mlb.inner_text("#mlb-view-apple .mlb-pending-note")


def test_low_n_is_flagged_per_cell_and_rows_stay_full(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page

    def handler(route: Route) -> None:
        resp = route.fetch()
        data = json.loads(resp.text())
        b = data["apple_booths"]
        b["quality_status"] = ["ready", "ready", "pending"]
        b["raw_stakes"] = [1.1, 0.9, None]
        b["raw_stakes_n"] = [3, 8, 0]
        b["raw_excitement"] = [1.5, 1.2, None]
        g = data["games"]
        g["wp_excitement"] = [1.0] * len(g["date"])
        route.fulfill(response=resp, body=json.dumps(data))

    page.route("**/mlb-data.json", handler)
    open_mlb_app(page)
    assert page.locator("#mlb-view-apple tr[data-low-n]").count() == 0
    for tr in page.locator(ROW).all():
        assert tr.evaluate("e => getComputedStyle(e).opacity") == "1"
    cells = page.locator(ROW).nth(0).locator("td")
    stakes = cells.nth(6)
    assert "is-low-n" in (stakes.get_attribute("class") or "")
    assert stakes.locator(".crews-tag").inner_text() == "n < 8"
    assert (
        stakes.locator(".crews-tag").get_attribute("title") == "Fewer than 8 games have this figure"
    )
    # Excitement n is 2 games (the booth's two), also under 8.
    assert cells.nth(7).locator(".crews-tag").inner_text() == "n < 8"
    # Booth 1: stakes n is exactly 8, not flagged.
    assert page.locator(ROW).nth(1).locator("td").nth(6).locator(".crews-tag").count() == 0
    # Booth 2 is pending: text, no tag.
    pend = page.locator(ROW).nth(2).locator("td.mlb-pending")
    assert pend.count() == 2
    assert set(pend.all_inner_texts()) == {"pending Retrosheet 2026"}
    assert page.locator(ROW).nth(2).locator(".crews-tag").count() == 0
    caps = page.inner_text("#mlb-view-apple .nfl-captions")
    assert "Cells marked n < 8 rest on fewer than 8 games." in caps
    assert "Faded rows" not in caps


def test_notes_follow_the_table_in_order(mlb: Page) -> None:
    order = mlb.evaluate(
        """() => {
          const v = document.querySelector('#mlb-view-apple');
          const at = (sel) => v.querySelector(sel);
          const pos = (n) => [...v.querySelectorAll('*')].indexOf(n);
          return [at('.crews-table-wrap'), at('.nfl-coverage'), at('.mlb-lead-lines'),
            at('.mlb-rr-note'), at('.nfl-captions')].map(pos);
        }"""
    )
    assert order == sorted(order)
    assert min(order) >= 0


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
    # Cells: chevron, position, booth, network, games, listed, stakes, excitement, prior.
    cells = page.locator(ROW).nth(0).locator("td")
    assert cells.nth(4).inner_text() == "2"
    assert cells.nth(6).inner_text().split()[0] == "1.10"
    assert cells.nth(7).inner_text().split()[0] == "1.50"
    assert cells.nth(8).inner_text() == "55.3%"
    page.click("#mlb-view-apple .segmented button[data-value='adjusted']")
    cells = page.locator(ROW).nth(0).locator("td")
    assert cells.nth(6).inner_text().replace("\n", " ").startswith("+0.20 ±0.10")
    assert page.locator(ROW).nth(1).locator("td").nth(6).inner_text().startswith("\u22120.10")
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
    mlb.click(f"{ROW} td.crews-name >> nth=1")
    assert mlb.evaluate(f"{HOOKS}.getTableIndexes()") == [3, 2]
    assert mlb.locator("#mlb-view-apple tr.is-picked").count() == 1
    assert mlb.locator(ROW).nth(1).get_attribute("aria-pressed") == "true"
    assert "booth=p2" in mlb.url
    # Exactly one inset inline-start marker, 2px, in the picked row.
    marks = mlb.evaluate(
        """() => [...document.querySelectorAll('#mlb-view-apple tr.is-picked > *')]
          .map((c) => getComputedStyle(c).boxShadow).filter((b) => b !== 'none')"""
    )
    assert len(marks) == 1
    assert "inset" in marks[0]
    assert "2px" in marks[0]
    mlb.click(f"{ROW} td.crews-name >> nth=1")
    assert mlb.evaluate(f"{HOOKS}.getTableIndexes()") == []
    assert "booth=" not in mlb.url


def test_every_head_sorts_and_third_click_returns_to_position(mlb: Page) -> None:
    head = "#mlb-view-apple thead th.crews-col-games button"
    names = lambda: mlb.eval_on_selector_all(  # noqa: E731
        f"{ROW} td.crews-col-position, {ROW} td:nth-child(2)", "els => els.map(e => e.textContent)"
    )
    mlb.click(head)
    assert (
        mlb.get_attribute("#mlb-view-apple thead th.crews-col-games", "aria-sort") == "descending"
    )
    mlb.click(head)
    assert mlb.get_attribute("#mlb-view-apple thead th.crews-col-games", "aria-sort") == "ascending"
    assert names()[0] == "#3"  # 1 game first
    mlb.click(head)
    assert (
        mlb.get_attribute("#mlb-view-apple thead th.crews-col-position", "aria-sort") == "ascending"
    )
    assert names() == ["Lead", "#2", "#3"]


def test_row_keys_pick_and_expand(mlb: Page) -> None:
    mlb.locator(ROW).first.focus()
    mlb.keyboard.press("ArrowDown")
    assert mlb.evaluate("document.activeElement.dataset.rowKey") == "1"
    mlb.keyboard.press("End")
    assert mlb.evaluate("document.activeElement.dataset.rowKey") == "2"
    mlb.keyboard.press("Home")
    mlb.keyboard.press("ArrowRight")
    assert mlb.locator(ROW).first.get_attribute("aria-expanded") == "true"
    mlb.keyboard.press("Escape")
    assert mlb.locator(ROW).first.get_attribute("aria-expanded") == "false"
    mlb.keyboard.press("Enter")
    assert "booth=p0" in mlb.url or "booth=" in mlb.url


def test_some_booths_pending_withholds_the_lead_lines_as_pending(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    def handler(route: Route) -> None:
        resp = route.fetch()
        data = json.loads(resp.text())
        b = data["apple_booths"]
        # Booth 0 is ready, the others stay pending: the builder nulls the differences.
        b["quality_status"][0] = "ready"
        b["raw_stakes"][0] = 1.1
        b["adj_stakes"][0] = 0.2
        b["adj_stakes_se"][0] = 0.05
        route.fulfill(response=resp, body=json.dumps(data))

    mlb_guarded_page.route("**/mlb-data.json", handler)
    open_mlb_app(mlb_guarded_page)
    lead = mlb_guarded_page.eval_on_selector_all(
        "#mlb-view-apple .mlb-lead-line", "els => els.map(e => e.textContent)"
    )
    assert lead and all("pending Retrosheet 2026" in t for t in lead)
    assert not any("too few games" in t for t in lead)
