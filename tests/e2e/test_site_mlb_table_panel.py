# ruff: noqa: E501
"""09-17: the MLB games table and detail panel on the synthetic MLB fixture.

Fixture games used here: 0 (2026 relay crew, lineup pending), 1 (2026 506 crew, rated 1.8M,
lineup pending), 6 (2014 wild card, no crew, full lineups), 7 (2014 World Series, Wikipedia
crew, lineup missing), 8 (2019 division, per_network, lineup missing).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

HOOKS = "window.__mlbTestHooks"


@pytest.fixture
def mlb(mlb_guarded_page: Page, open_mlb_app: Callable[..., None]) -> Page:
    open_mlb_app(mlb_guarded_page)
    return mlb_guarded_page


def _open(page: Page, game: int) -> None:
    page.evaluate(f"{HOOKS}.openGame({game})")
    page.wait_for_selector("#mlb-detail-panel[open]")


def _panel(page: Page) -> str:
    return page.inner_text("#mlb-detail-panel")


def test_booth_selection_lists_its_games(mlb: Page) -> None:
    assert mlb.evaluate(f"{HOOKS}.getTableIndexes()") == []
    assert "Nothing selected" in mlb.inner_text("#mlb-matched-games")
    mlb.evaluate(f"{HOOKS}.setState({{ booth: '0' }})")
    assert mlb.evaluate(f"{HOOKS}.getTableIndexes()") == [1, 0]
    headers = mlb.eval_on_selector_all(
        "#mlb-matched-games thead th", "els => els.map(e => e.textContent.replace(/[▲▼]/g, ''))"
    )
    assert headers == ["Date", "Matchup", "Round", "Outlet", "Crew", "Viewers"]
    rows = mlb.locator("#mlb-matched-games tbody tr")
    assert rows.count() == 2
    text = mlb.inner_text("#mlb-matched-games tbody")
    assert "Apr 10, 2026" in text
    assert "1.8M" in text
    assert "not posted yet" in text
    tags = mlb.eval_on_selector_all(
        "#mlb-matched-games .mlb-source-tag", "els => els.map(e => e.textContent)"
    )
    assert sorted(tags) == ["506", "relay"]
    assert "Ada Quill" in text
    assert mlb.locator("#mlb-clear-selection").is_visible()
    mlb.click("#mlb-clear-selection")
    assert mlb.evaluate(f"{HOOKS}.getTableIndexes()") == []


def test_postseason_cell_selection_and_empty_crew(mlb: Page) -> None:
    mlb.evaluate(f"{HOOKS}.setState({{ cell: '2014-wild_card-AL' }})")
    assert mlb.evaluate(f"{HOOKS}.getTableIndexes()") == [6]
    text = mlb.inner_text("#mlb-matched-games tbody")
    assert "crew not listed" in text
    assert "Wild card" in text
    assert "AL, game 1" in text
    mlb.evaluate(f"{HOOKS}.setState({{ cell: '2019-division-AL' }})")
    text = mlb.inner_text("#mlb-matched-games tbody")
    assert "per-network figures only" in text
    assert "Wikipedia" in text


def test_lineups_nine_batters_and_starter_per_side(mlb: Page) -> None:
    _open(mlb, 6)
    for side in ("away", "home"):
        col = mlb.locator(f'#mlb-detail-panel .mlb-lineup[data-side="{side}"]')
        assert col.locator("li").count() == 10
        assert col.locator("li.mlb-sp").count() == 1
        slots = col.locator("li .mlb-slot").all_inner_texts()
        assert slots == ["1", "2", "3", "4", "5", "6", "7", "8", "9", "SP"]
    text = _panel(mlb)
    assert "Invented Player 00" in text
    assert "Harbor City Gulls" in text
    assert "obtained free of charge from and is copyrighted by Retrosheet" in text
    assert "Excitement: 1.2 (WE-swing)" in text
    link = mlb.locator('#mlb-detail-panel a[href="https://www.retrosheet.org"]')
    assert link.get_attribute("rel") == "noopener noreferrer"


def test_pending_2026_lineup_and_excitement(mlb: Page) -> None:
    _open(mlb, 0)
    text = _panel(mlb)
    assert "pending Retrosheet 2026" in text
    assert mlb.locator("#mlb-detail-panel .mlb-lineups").count() == 0
    assert "Excitement: pending Retrosheet 2026" in text


def test_missing_lineup_reads_not_in_retrosheet(mlb: Page) -> None:
    _open(mlb, 7)
    text = _panel(mlb)
    assert "Lineup not in Retrosheet" in text
    assert "Wikipedia list (CC BY-SA 4.0)" in text
    href = mlb.locator('#mlb-detail-panel a:has-text("View article")').get_attribute("href")
    assert href == "https://example.org/wiki/2014_Invented_Series"


def test_wikipedia_outlet_is_credited_with_its_article(mlb: Page) -> None:
    _open(mlb, 7)
    text = _panel(mlb)
    assert "Outlet from Wikipedia (CC BY-SA 4.0)" in text
    link = mlb.locator('#mlb-detail-panel a:has-text("View outlet article")')
    assert link.get_attribute("href") == "https://example.org/wiki/2014_Invented_Series"
    assert "noopener" in (link.get_attribute("rel") or "")
    # A 506 outlet carries no Wikipedia credit.
    _open(mlb, 11)
    assert "Outlet from Wikipedia" not in _panel(mlb)


def test_relay_crew_links_post_and_press_page(mlb: Page) -> None:
    _open(mlb, 0)
    post = mlb.locator('#mlb-detail-panel a[href="https://example.org/relay/post-1"]')
    press = mlb.locator('#mlb-detail-panel a[href="https://example.org/press/release-1"]')
    assert post.count() == 1
    assert press.count() == 1
    assert press.inner_text() == "Invented Press Room"
    for loc in (post, press):
        assert loc.get_attribute("rel") == "noopener noreferrer"
        assert loc.get_attribute("target") == "_blank"
    assert "Relayed from" in _panel(mlb)


def test_rated_game_shows_record_and_publisher_links(mlb: Page) -> None:
    _open(mlb, 1)
    text = _panel(mlb)
    assert "Viewers: 1.8M" in text
    assert "Measured under Invented era." in text
    rr = mlb.locator('#mlb-detail-panel a[href="https://example.org/rr/telecast-1"]')
    src = mlb.locator('#mlb-detail-panel a[href="https://example.org/source/figure-1"]')
    assert rr.count() == 1
    assert src.count() == 1
    assert rr.get_attribute("rel") == "noopener noreferrer"
    assert src.get_attribute("rel") == "noopener noreferrer"
    assert mlb.locator('#mlb-detail-panel a[href="https://example.org/506/mlb-week"]').count() == 1


def test_window_level_figure_is_labelled_not_a_game_audience(mlb: Page) -> None:
    _open(mlb, 10)
    text = _panel(mlb)
    assert "Viewers: 5.5M (whole broadcast window, not this game alone)" in text
    # A per-game figure carries no such note.
    _open(mlb, 7)
    assert "whole broadcast window" not in _panel(mlb)
    mlb.evaluate(f"{HOOKS}.closePanel()")
    mlb.evaluate(f"{HOOKS}.setState({{ view: 'postseason', cell: '2019-lcs-NL' }})")
    tag = mlb.locator("#mlb-matched-games tbody .mlb-source-tag[data-scope='window']")
    assert tag.count() == 1
    assert "Avg" not in mlb.inner_text("#mlb-view-postseason button[data-cell='2019-lcs-NL']")


def test_window_figures_sort_after_game_figures(mlb: Page) -> None:
    mlb.evaluate(f"{HOOKS}.setState({{ view: 'postseason', selection: null }})")
    mlb.evaluate(f"{HOOKS}.setState({{ cell: null }})")
    # 2014 World Series (12.0M game figure) and 2019 LCS (5.5M window) need one table.
    mlb.evaluate(f"{HOOKS}.setState({{ selection: {{ games: [7, 10], label: 'test pair' }} }})")
    mlb.click("#mlb-matched-games th button[data-sort='viewers']")
    rows = mlb.eval_on_selector_all(
        "#mlb-matched-games tbody .nfl-matchup-btn", "els => els.map(e => e.dataset.game)"
    )
    assert rows == ["7", "10"]
    mlb.click("#mlb-matched-games th button[data-sort='viewers']")
    rows = mlb.eval_on_selector_all(
        "#mlb-matched-games tbody .nfl-matchup-btn", "els => els.map(e => e.dataset.game)"
    )
    assert rows == ["7", "10"]  # the window figure stays last in either direction


def test_per_network_game_shows_cause(mlb: Page) -> None:
    _open(mlb, 8)
    text = _panel(mlb)
    assert "Viewers: not available (per-network figures only)" in text
    # This fixture game carries no RR record, so there is no record link to show.
    assert mlb.locator('#mlb-detail-panel a[href*="/rr/"]').count() == 0


def test_escape_closes_and_returns_focus(mlb: Page) -> None:
    mlb.evaluate(f"{HOOKS}.setState({{ booth: '0' }})")
    button = mlb.locator("#mlb-matched-games .nfl-matchup-btn").first
    button.focus()
    button.click()
    mlb.wait_for_selector("#mlb-detail-panel[open]")
    assert mlb.evaluate(f"{HOOKS}.getState().game") is not None
    assert "game=" in mlb.evaluate("location.search")
    mlb.keyboard.press("Escape")
    mlb.wait_for_selector("#mlb-detail-panel:not([open])", state="attached")
    assert mlb.evaluate("document.activeElement.className") == "nfl-matchup-btn"
    assert mlb.evaluate(f"{HOOKS}.getState().game") is None
    assert "game=" not in mlb.evaluate("location.search")


def test_row_click_opens_panel(mlb: Page) -> None:
    mlb.evaluate(f"{HOOKS}.setState({{ booth: '1' }})")
    mlb.locator("#mlb-matched-games tbody tr").first.locator("td").first.click()
    mlb.wait_for_selector("#mlb-detail-panel[open]")
    assert "Cy Fable" in _panel(mlb) or "Dee Hart" in _panel(mlb)


def test_phone_panel_fits_without_sideways_scroll(
    mlb_mobile_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_mobile_page
    open_mlb_app(page)
    _open(page, 6)
    fits = page.evaluate(
        "(() => { const i = document.querySelector('#mlb-detail-panel .panel-inner'); return i.scrollWidth <= i.clientWidth; })()"
    )
    assert fits
    assert page.locator("#mlb-detail-panel .mlb-lineup").count() == 2
