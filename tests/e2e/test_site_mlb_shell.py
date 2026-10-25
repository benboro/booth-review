"""09-17: the MLB mount module on the synthetic MLB fixture (flag-on build)."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from playwright.sync_api import Page, Route

pytestmark = pytest.mark.e2e

RETROSHEET = "obtained free of charge from and is copyrighted by Retrosheet"


def _track(page: Page) -> list[str]:
    urls: list[str] = []
    page.on("request", lambda r: urls.append(r.url))
    return urls


def _count(urls: list[str], name: str) -> int:
    return sum(1 for u in urls if name in u.split("?")[0])


def _wait_mlb(page: Page) -> None:
    page.wait_for_function("window.__mlbTestHooks && window.__mlbTestHooks.ready === true")


def test_mlb_button_and_single_mount(
    mlb_guarded_page: Page, open_mlb_cfb: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    urls = _track(page)
    open_mlb_cfb(page)
    assert page.locator('#sport-switch button[data-sport="mlb"]').count() == 1
    for _ in range(2):
        page.click('#sport-switch button[data-sport="mlb"]')
        _wait_mlb(page)
        assert page.evaluate("document.body.dataset.sport") == "mlb"
        page.click('#sport-switch button[data-sport="cfb"]')
        page.wait_for_function("document.body.dataset.sport === 'cfb'")
    assert _count(urls, "sports/mlb/index.js") == 1
    assert _count(urls, "mlb-data.json") == 1


_TRADEMARK_LINE = (
    "Network logos are trademarks of their owners, shown only to identify each network. "
    "Their use does not imply endorsement, and they are not covered by this site's MIT license."
)

_TYPE_LINE = (
    "Type: Crimson Text (copyright 2010 The Crimson Text Project Authors), "
    "Roboto (copyright 2011 The Roboto Project Authors) and "
    "Roboto Condensed (copyright 2011 Google Inc.), "
    "used under the SIL Open Font License 1.1."
)

_RT05_TEXT = (
    "The information used here was obtained free of charge from and is copyrighted by "
    "Retrosheet. Interested parties may contact Retrosheet at www.retrosheet.org · "
    "Viewership: RatingsReference.com (CC BY 4.0), modified: filtered and joined with crew and "
    "game data · Postseason outlets and some crews: Wikipedia (CC BY-SA 4.0) · "
    "Crews and networks: 506 Sports · Some 2026 crews: relayed from a fan schedule blog, "
    "each linked in the game panel with the press page it cites"
)

_RT05_LINKS = [
    ("www.retrosheet.org", "https://www.retrosheet.org"),
    ("RatingsReference.com", "https://ratingsreference.com"),
    ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"),
    ("Wikipedia", "https://www.wikipedia.org"),
    ("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/"),
    ("506 Sports", "https://506sports.com"),
]


def _norm(text: str) -> str:
    return " ".join(text.split())


def _static_lines(page: Page) -> tuple[str, str, list[str]]:
    """RT-23 and RT-24 text and RT-24 link targets as the footer shows them now."""
    trademark = _norm(page.locator("#site-footer p.trademark-line").inner_text())
    type_line = _norm(page.locator("#site-footer p.type-line").inner_text())
    hrefs = page.locator("#site-footer p.type-line a").evaluate_all(
        "els => els.map(e => e.getAttribute('href'))"
    )
    return trademark, type_line, hrefs


def test_footer_credits_and_restore(
    mlb_guarded_page: Page, open_mlb_cfb: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    open_mlb_cfb(page)
    before = page.evaluate("document.getElementById('site-footer').outerHTML")
    lines_before = _static_lines(page)
    assert lines_before[0] == _TRADEMARK_LINE
    assert lines_before[1] == _TYPE_LINE
    page.click('#sport-switch button[data-sport="mlb"]')
    _wait_mlb(page)
    credit = page.locator("#site-footer .credit-line")
    assert _norm(credit.inner_text()) == _RT05_TEXT
    assert RETROSHEET in _norm(credit.inner_text())
    anchors = credit.locator("a")
    assert anchors.evaluate_all("els => els.map(e => [e.textContent, e.getAttribute('href')])") == [
        list(pair) for pair in _RT05_LINKS
    ]
    assert anchors.evaluate_all("els => els.map(e => e.rel)") == ["noopener noreferrer"] * 6
    assert "CollegeFootballData" not in page.inner_text("#site-footer")
    # RT-23 and RT-24 stay present and untouched while MLB is shown.
    assert _static_lines(page) == lines_before
    page.click('#sport-switch button[data-sport="cfb"]')
    page.wait_for_function("document.body.dataset.sport === 'cfb'")
    assert page.evaluate("document.getElementById('site-footer').outerHTML") == before
    assert _static_lines(page) == lines_before


def test_selection_area_copy_and_module_subtitle(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    open_mlb_app(page)
    assert (
        _norm(page.locator(".mlb-selection-note").inner_text())
        == "Filters: none. MLB is selection-driven; pick a row below."
    )
    assert page.locator("#mlb-chart-subtitle").count() == 1


def test_state_survives_sport_switch(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    open_mlb_app(page)
    page.evaluate("window.__mlbTestHooks.setState({ booth: '1' })")
    assert page.evaluate("window.__mlbTestHooks.getState().booth") == "1"
    page.click('#sport-switch button[data-sport="cfb"]')
    page.wait_for_function("document.body.dataset.sport === 'cfb'")
    page.click('#sport-switch button[data-sport="mlb"]')
    _wait_mlb(page)
    assert page.evaluate("window.__mlbTestHooks.getState().booth") == "1"
    assert page.evaluate("window.__mlbTestHooks.getTableIndexes()") == [3, 2]


def test_url_state_round_trip(mlb_guarded_page: Page, open_mlb_app: Callable[..., None]) -> None:
    page = mlb_guarded_page
    open_mlb_app(page)
    page.evaluate("window.__mlbTestHooks.setState({ booth: '1', game: 3 })")
    search = page.evaluate("location.search")
    # Stable ids, not positions: the booth's play-by-play person and the game's date and clubs.
    assert search == "?sport=mlb&booth=p2&game=2026-04-24~owls~gulls~0"
    open_mlb_app(page, search)
    state = page.evaluate("window.__mlbTestHooks.getState()")
    assert state["booth"] == "1"
    assert state["game"] == 3
    assert page.evaluate("document.getElementById('mlb-detail-panel').open") is True


def test_booth_link_follows_the_booth_when_the_data_is_reordered(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    def rotate(route: Route) -> None:
        resp = route.fetch()
        data = json.loads(resp.text())
        for name, col in data["apple_booths"].items():
            data["apple_booths"][name] = [*col[1:], col[0]]
        route.fulfill(response=resp, body=json.dumps(data))

    page = mlb_guarded_page
    page.route("**/mlb-data.json", rotate)
    open_mlb_app(page, "?sport=mlb&booth=p2")
    # Booth p2 moved from position 1 to 0, and the link still opens it.
    assert page.evaluate("window.__mlbTestHooks.getState().booth") == "0"
    assert page.evaluate("window.__mlbTestHooks.getTableIndexes()") == [3, 2]
    assert page.evaluate("location.search") == "?sport=mlb&booth=p2"


def test_old_positional_links_fall_back_to_the_default_view(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    open_mlb_app(page, "?sport=mlb&booth=1&game=3")
    state = page.evaluate("window.__mlbTestHooks.getState()")
    assert state["booth"] is None and state["game"] is None
    assert page.evaluate("document.getElementById('mlb-detail-panel').open") is False
    assert page.evaluate("location.search") == "?sport=mlb"


def test_cell_key_and_junk_params(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    open_mlb_app(page, "?sport=mlb&cell=2019-lcs-NL&booth=99&game=abc")
    state = page.evaluate("window.__mlbTestHooks.getState()")
    assert state["cell"] == "2019-lcs-NL"
    assert state["booth"] is None
    assert state["game"] is None
    assert page.evaluate("window.__mlbTestHooks.getTableIndexes()") == [10]
    assert page.evaluate("location.search") == "?sport=mlb&cell=2019-lcs-NL"


def test_only_mlb_data_is_fetched(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    urls = _track(page)
    open_mlb_app(page)
    page.wait_for_load_state("networkidle")
    json_files = {
        u.split("?")[0].rsplit("/", 1)[-1] for u in urls if u.split("?")[0].endswith(".json")
    }
    assert "nfl-data.json" not in json_files
    assert "mlb-data.json" in json_files


def test_tab_bar_lists_exactly_the_registered_views(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    open_mlb_app(mlb_guarded_page)
    tabs = mlb_guarded_page.eval_on_selector_all(
        "#mlb-chart-tabs [role=tab]", "els => els.map(e => e.textContent)"
    )
    assert tabs == ["Apple crews", "Postseason booths", "Scatter"]
    assert mlb_guarded_page.locator("#mlb-chart-tabs").is_visible()
    assert mlb_guarded_page.locator("#mlb-tab-apple[aria-selected='true']").count() == 1
    mlb_guarded_page.click("#mlb-tab-postseason")
    assert mlb_guarded_page.locator("#mlb-tab-postseason[aria-selected='true']").count() == 1
    assert mlb_guarded_page.locator("#mlb-view-postseason").is_visible()
    assert mlb_guarded_page.locator("#mlb-view-apple").is_hidden()
    assert "view=postseason" in mlb_guarded_page.url


def test_view_deep_links(mlb_guarded_page: Page, open_mlb_app: Callable[..., None]) -> None:
    page = mlb_guarded_page
    open_mlb_app(page, "?sport=mlb&view=postseason")
    assert page.locator("#mlb-tab-postseason[aria-selected='true']").count() == 1
    assert page.locator("#mlb-view-postseason table.mlb-grid").is_visible()
    assert page.locator("#mlb-view-apple").is_hidden()
    open_mlb_app(page, "?sport=mlb&view=apple")
    assert page.locator("#mlb-tab-apple[aria-selected='true']").count() == 1
    assert page.locator("#mlb-view-apple table.mlb-apple-table").is_visible()
    assert page.locator("#mlb-view-postseason").is_hidden()
    open_mlb_app(page, "?sport=mlb&view=scatter")
    assert page.locator("#mlb-tab-scatter[aria-selected='true']").count() == 1
    assert page.locator("#mlb-view-scatter").is_visible()
    assert page.locator("#mlb-view-apple").is_hidden()
    assert page.evaluate("window.__mlbTestHooks.getState().view") == "scatter"


def test_sport_switch_with_an_open_game_does_not_redraw_the_hidden_scatter(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """F14: unmount closes the panel; onClose must not re-render the Scatter once MLB is gone."""
    page = mlb_guarded_page
    open_mlb_app(page, "?sport=mlb&view=scatter")
    page.wait_for_function("window.__mlbTestHooks.getViewModel('scatter').drawn === true")
    page.evaluate("window.__mlbTestHooks.openGame(1)")
    page.wait_for_function("document.getElementById('mlb-detail-panel').open")
    page.evaluate(
        """() => {
          window.__mlbReacts = 0;
          const gd = document.querySelector('#mlb-view-scatter .js-plotly-plot');
          const react = window.Plotly.react;
          window.Plotly.react = function (el, ...rest) {
            if (el === gd) window.__mlbReacts += 1;
            return react.call(this, el, ...rest);
          };
        }"""
    )
    # The modal panel covers the switch, so the sport change is driven programmatically.
    page.evaluate("document.querySelector('#sport-switch button[data-sport=\"cfb\"]').click()")
    page.wait_for_function("document.body.dataset.sport === 'cfb'")
    page.wait_for_timeout(200)
    assert page.evaluate("document.getElementById('mlb-detail-panel').open") is False
    assert page.evaluate("window.__mlbReacts") == 0
