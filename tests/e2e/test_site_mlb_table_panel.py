# ruff: noqa: E501
"""09-17: the MLB games table and detail panel on the synthetic MLB fixture.

Fixture games used here: 0 (2026 relay crew, lineup pending), 1 (2026 506 crew, rated 1.8MM,
lineup pending), 6 (2014 wild card, no crew, full lineups), 7 (2014 World Series, Wikipedia
crew, lineup missing), 8 (2019 division, per_network, lineup missing).
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
    assert headers == ["Date", "Matchup", "Round", "Network", "Crew", "Viewers"]
    rows = mlb.locator("#mlb-matched-games tbody tr")
    assert rows.count() == 2
    text = mlb.inner_text("#mlb-matched-games tbody")
    assert "Apr 10, 2026" in text
    assert "1.8MM" in text
    assert "not posted yet" in text
    assert mlb.locator("#mlb-matched-games td .mlb-source-tag[data-source]").count() == 0
    assert "Ada Quill" in text
    assert mlb.locator("#mlb-clear-selection").is_visible()
    mlb.click("#mlb-clear-selection")
    assert mlb.evaluate(f"{HOOKS}.getTableIndexes()") == []


def _subtitle(page: Page) -> str:
    return page.inner_text("#mlb-matched-subtitle")


def test_subtitle_follows_sort_and_resets_on_new_selection(mlb: Page) -> None:
    assert mlb.locator("#mlb-matched-subtitle").is_hidden()
    mlb.evaluate(f"{HOOKS}.setState({{ booth: '0' }})")
    label = mlb.evaluate(f"{HOOKS}.getState().booth") and _subtitle(mlb).rsplit(", ", 1)[0]
    assert _subtitle(mlb).endswith(", newest first")
    viewers = "#mlb-matched-games th button[data-sort='viewers']"
    date = "#mlb-matched-games th button[data-sort='date']"
    mlb.click(viewers)
    assert _subtitle(mlb) == f"{label}, most viewers first"
    mlb.click(viewers)
    assert _subtitle(mlb) == f"{label}, fewest viewers first"
    mlb.click(date)
    assert _subtitle(mlb).endswith(", oldest first")
    mlb.click(viewers)
    mlb.evaluate(f"{HOOKS}.setState({{ booth: '1' }})")
    assert _subtitle(mlb).endswith(", newest first")
    mlb.evaluate(f"{HOOKS}.setState({{ booth: null }})")
    assert mlb.locator("#mlb-matched-subtitle").is_hidden()


def test_regular_season_round_cell_and_empty_copy(mlb: Page) -> None:
    assert "Pick a booth, a postseason cell or a season to list its games." in mlb.inner_text(
        "#mlb-matched-games"
    )
    mlb.evaluate(f"{HOOKS}.setState({{ booth: '0' }})")
    cells = mlb.eval_on_selector_all(
        "#mlb-matched-games tbody tr td:nth-child(3)", "els => els.map(e => e.textContent)"
    )
    assert cells and all(c == "Reg. Season" for c in cells)


def test_postseason_cell_selection_and_empty_crew(mlb: Page) -> None:
    mlb.evaluate(f"{HOOKS}.setState({{ cell: '2014-wild_card-AL' }})")
    assert mlb.evaluate(f"{HOOKS}.getTableIndexes()") == [6]
    text = mlb.inner_text("#mlb-matched-games tbody")
    assert "crew not listed" in text
    assert "Wild Card" in text
    assert "AL, Game 1" in text
    mlb.evaluate(f"{HOOKS}.setState({{ cell: '2019-division-AL' }})")
    text = mlb.inner_text("#mlb-matched-games tbody")
    assert "per-network figures only" in text
    assert "Wikipedia" not in text
    # The narrow Round column shortens the league series as a pair (U4), full name in the title.
    assert "LDS" in text
    titles = mlb.eval_on_selector_all(
        "#mlb-matched-games tbody td:nth-child(3)", "els => els.map(e => e.title)"
    )
    assert "Division Series" in titles


def test_lineups_nine_batters_and_starter_per_side(mlb: Page) -> None:
    _open(mlb, 6)
    for side in ("away", "home"):
        col = mlb.locator(f'#mlb-detail-panel .mlb-lineup[data-side="{side}"]')
        assert col.locator("li").count() == 10
        assert col.locator("li.mlb-sp").count() == 1
        slots = col.locator("li .mlb-slot").all_inner_texts()
        assert slots == ["1", "2", "3", "4", "5", "6", "7", "8", "9", "SP"]
    text = _panel(mlb)
    assert mlb.locator("#mlb-detail-panel h3", has_text="Starting Lineups").count() == 1
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


def test_missing_outlet_reads_not_recorded(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    def handler(route: Route) -> None:
        resp = route.fetch()
        data = json.loads(resp.text())
        g = data["games"]
        g["network"][7] = None
        g["network_source"][7] = None
        g["network_source_url"][7] = None
        route.fulfill(response=resp, body=json.dumps(data))

    mlb_guarded_page.route("**/mlb-data.json", handler)
    open_mlb_app(mlb_guarded_page)
    _open(mlb_guarded_page, 7)
    text = _panel(mlb_guarded_page)
    assert "Outlet not recorded." in text
    assert "Outlet: \n" not in text and not text.rstrip().endswith("Outlet:")
    assert "Outlet from Wikipedia" not in text


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
    assert "Viewers: 1.8MM" in text
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
    assert "Viewers: 5.5MM (whole broadcast window, not this game alone)" in text
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
    # 2014 World Series (12.0MM game figure) and 2019 LCS (5.5MM window) need one table.
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
    # The dialog's close event (which restores focus) is queued after `open` clears.
    mlb.wait_for_function("document.activeElement.className === 'nfl-matchup-btn'")
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


def test_panel_round_line(mlb: Page) -> None:
    _open(mlb, 6)
    assert "Wild Card · AL, Game 1" in _panel(mlb)
    _open(mlb, 0)
    assert "Reg. Season" in _panel(mlb)


def test_506_crew_credit_link_text_and_href(mlb: Page) -> None:
    """RT-14: a 506-sourced crew reads 'Crew from 506 Sports ↗' and links to the week page."""
    _open(mlb, 1)
    link = mlb.locator('#mlb-detail-panel a:has-text("506 Sports ↗")')
    assert link.count() == 1
    assert link.inner_text() == "506 Sports ↗"
    assert link.get_attribute("rel") == "noopener noreferrer"
    assert link.get_attribute("href") == "https://example.org/506/mlb-week"
    assert "Crew from 506 Sports ↗" in _panel(mlb)


def _outlet_mark(page: Page) -> dict[str, str | None]:
    return page.evaluate(  # type: ignore[no-any-return]
        """() => {
          const m = document.querySelector('#mlb-detail-panel .panel-networks .net-mark');
          const img = m.querySelector('img');
          return {
            alt: img?.getAttribute('alt') ?? null,
            title: img?.getAttribute('title') ?? null,
            name: m.querySelector('.net-name')?.textContent ?? null,
            pills: String(document.querySelectorAll('#mlb-detail-panel .panel-networks .pill').length),
          };
        }"""
    )


def test_panel_outlet_is_a_logo_by_id(mlb: Page) -> None:
    """SHELL-05: Apple TV shows its logo (alt/title = name), not a pill or text."""
    _open(mlb, 0)
    assert _outlet_mark(mlb) == {"alt": "Apple TV", "title": "Apple TV", "name": None, "pills": "0"}


def test_panel_outlet_without_a_logo_falls_back_to_dot_and_name(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    def handler(route: Route) -> None:
        resp = route.fetch()
        data = json.loads(resp.text())
        data["lookups"]["networks"][0].update({"id": "mlbn", "name": "MLB Network"})
        route.fulfill(response=resp, body=json.dumps(data))

    mlb_guarded_page.route("**/mlb-data.json", handler)
    open_mlb_app(mlb_guarded_page)
    _open(mlb_guarded_page, 0)
    assert _outlet_mark(mlb_guarded_page) == {
        "alt": None,
        "title": None,
        "name": "MLB Network",
        "pills": "0",
    }
    assert mlb_guarded_page.locator("#mlb-detail-panel .panel-networks .net-dot").count() == 1


def _retrosheet_through(page: Page, open_mlb_app: Callable[..., None], through: int) -> None:
    """Open the app with Retrosheet loaded through `through`; game 0 lacks play-by-play, game 13
    moves to the next season, game 1 keeps its pending lineup."""

    def handler(route: Route) -> None:
        resp = route.fetch()
        data = json.loads(resp.text())
        data["freshness"]["retrosheet_through_season"] = through
        g = data["games"]
        g["lineup_status"][0] = "missing"
        g["lineup_status"][13] = "missing"
        g["season"][13] = through + 1
        route.fulfill(response=resp, body=json.dumps(data))

    page.route("**/mlb-data.json", handler)
    open_mlb_app(page)


def test_excitement_pending_follows_retrosheet_freshness(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """F21: 'pending' comes from freshness, not a fixed 2026, and its year from the game."""
    page = mlb_guarded_page
    _retrosheet_through(page, open_mlb_app, 2026)
    # A 2026 game Retrosheet has reached but with no play-by-play: not pending.
    _open(page, 0)
    assert "Excitement: not available" in _panel(page)
    page.evaluate(f"{HOOKS}.closePanel()")
    # A season Retrosheet has not reached reads pending with that season's year.
    _open(page, 13)
    assert "Excitement: pending Retrosheet 2027" in _panel(page)
    page.evaluate(f"{HOOKS}.closePanel()")
    # A pending lineup stays pending.
    _open(page, 1)
    assert "Excitement: pending Retrosheet 2026" in _panel(page)


def _relabel(route: Route) -> None:
    """Give the fixture's rated games the builder's real label values."""
    resp = route.fetch()
    raw = json.loads(resp.text())
    labels = raw["games"]["viewership_label"]
    labels[1] = "per-game"
    labels[7] = "composite"
    labels[10] = "window-level"
    route.fulfill(response=resp, body=json.dumps(raw))


def test_game_figure_reads_as_that_games_viewers_not_its_label(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """U1: a game's own figure reads `Viewers: <value>`, never the data label 'per-game'."""
    page = mlb_guarded_page
    page.route("**/mlb-data.json", _relabel)
    open_mlb_app(page)
    _open(page, 1)
    text = _panel(page)
    assert "Viewers: 1.8MM" in text
    assert "per-game" not in text.lower()
    # A window figure keeps the RT-27 qualifier; a composite says it adds telecasts together.
    _open(page, 10)
    assert "Viewers: 5.5MM (whole broadcast window, not this game alone)" in _panel(page)
    assert "window-level:" not in _panel(page)
    _open(page, 7)
    assert "Viewers: 12.0MM (several telecasts combined)" in _panel(page)


def test_panel_says_retrosheet_not_loaded_without_retrosheet(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """G11: with no Retrosheet loaded the panel names that, not 'pending Retrosheet <year>'."""
    page = mlb_guarded_page

    def handler(route: Route) -> None:
        resp = route.fetch()
        data = json.loads(resp.text())
        data["freshness"]["retrosheet_through_season"] = None
        route.fulfill(response=resp, body=json.dumps(data))

    page.route("**/mlb-data.json", handler)
    open_mlb_app(page)
    _open(page, 1)
    text = _panel(page)
    assert "Excitement: Retrosheet not loaded" in text
    assert "Excitement: pending Retrosheet" not in text


def test_a_composite_window_figure_keeps_both_qualifiers(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """G12: a figure that is both window-level and composite says both, not the window note alone."""
    page = mlb_guarded_page

    def handler(route: Route) -> None:
        resp = route.fetch()
        raw = json.loads(resp.text())
        assert raw["games"]["scope"][10] == "window"
        raw["games"]["viewership_label"][10] = "composite"
        route.fulfill(response=resp, body=json.dumps(raw))

    page.route("**/mlb-data.json", handler)
    open_mlb_app(page)
    _open(page, 10)
    assert (
        "Viewers: 5.5MM (whole broadcast window, not this game alone; several telecasts combined)"
        in _panel(page)
    )
