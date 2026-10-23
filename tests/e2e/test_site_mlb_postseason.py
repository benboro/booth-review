"""09-19: the MLB postseason booths grid on the synthetic MLB fixture.

Fixture seasons: 2014 (50% crews listed), 2019 (100%), 2025 (100%), 2026 (50%, excitement pending).
Cells: 2014 wild card AL (no crew), 2014 World Series (Wikipedia crew, 12.0M), 2019 division
AL (two games), 2019 LCS NL (5.5M, window-level), 2025 wild card NL, 2025 World Series, 2026 LCS AL,
2026 division NL.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from playwright.sync_api import Page, Route

pytestmark = pytest.mark.e2e

HOOKS = "window.__mlbTestHooks"
VIEW = "#mlb-view-postseason"


@pytest.fixture
def post(mlb_guarded_page: Page, open_mlb_app: Callable[..., None]) -> Page:
    open_mlb_app(mlb_guarded_page, "?sport=mlb&view=postseason")
    return mlb_guarded_page


def test_grid_rows_and_columns(post: Page) -> None:
    seasons = post.eval_on_selector_all(
        f"{VIEW} tbody th .mlb-season", "els => els.map(e => e.textContent)"
    )
    assert seasons == ["2014", "2019", "2025", "2026"]
    heads = post.eval_on_selector_all(
        f"{VIEW} .mlb-grid thead th", "els => els.map(e => e.textContent)"
    )
    assert heads == ["Season", "Wild Card", "Division", "LCS", "World Series"]
    assert post.locator(f"{VIEW} .mlb-grid th[scope='row']").count() == 4


def test_coverage_per_season_and_low_tone(post: Page) -> None:
    cov = post.eval_on_selector_all(
        f"{VIEW} .mlb-grid .mlb-season-coverage", "els => els.map(e => e.textContent)"
    )
    # Counts come from the builder's season table; 2019 has one postseason game that
    # sits in no cell, so its denominator is larger than its cells'.
    assert cov == [
        "Crews listed for 1 of 2 postseason games (50%)",
        "Crews listed for 3 of 4 postseason games (75%)",
        "Crews listed for 2 of 2 postseason games (100%)",
        "Crews listed for 1 of 2 postseason games (50%)",
    ]
    low = post.eval_on_selector_all(
        f"{VIEW} .mlb-grid .mlb-season-coverage[data-low='true']", "els => els.length"
    )
    assert low == 3


def test_wikipedia_outlets_are_credited_per_season(post: Page) -> None:
    links = post.eval_on_selector_all(
        f"{VIEW} .mlb-grid .mlb-season-credit",
        "els => els.map(e => [e.textContent, e.getAttribute('href'), e.getAttribute('rel')])",
    )
    assert [t for t, _, _ in links] == [
        "Outlets: Wikipedia 2014 postseason (CC BY-SA 4.0) ↗",
        "Outlets: Wikipedia 2019 postseason (CC BY-SA 4.0) ↗",
    ]
    assert [h for _, h, _ in links] == [
        "https://example.org/wiki/2014_Invented_Series",
        "https://example.org/wiki/2019_Invented_Series",
    ]
    assert all("noopener" in (r or "") for _, _, r in links)


def _cell_marks(page: Page, cell: str) -> list[dict[str, str | None]]:
    return page.eval_on_selector_all(  # type: ignore[no-any-return]
        f"{VIEW} button[data-cell='{cell}'] .mlb-cell-head .net-mark",
        """els => els.map(m => ({
          alt: m.querySelector('img')?.getAttribute('alt') ?? null,
          title: m.querySelector('img')?.getAttribute('title') ?? null,
          name: m.querySelector('.net-name')?.textContent ?? null,
        }))""",
    )


def test_a_split_cell_shows_every_outlet(post: Page) -> None:
    """SHELL-05: each outlet is a logo by id with alt/title = name, in the lookup order."""
    marks = _cell_marks(post, "2025-wild_card-NL")
    assert marks == [
        {"alt": "ESPN", "title": "ESPN", "name": None},
        {"alt": "TBS", "title": "TBS", "name": None},
    ]
    assert post.locator(f"{VIEW} .mlb-cell-head .pill").count() == 0
    # A logo stands alone: no family dot beside it (brief §5).
    cell = post.locator(f"{VIEW} button[data-cell='2025-wild_card-NL'] .mlb-cell-head")
    assert cell.locator(".net-dot").count() == 0


def test_outlet_without_a_logo_falls_back_to_dot_and_name(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    def handler(route: Route) -> None:
        resp = route.fetch()
        data = json.loads(resp.text())
        data["lookups"]["networks"][1].update({"id": "mlbn", "name": "MLB Network"})
        route.fulfill(response=resp, body=json.dumps(data))

    mlb_guarded_page.route("**/mlb-data.json", handler)
    open_mlb_app(mlb_guarded_page, "?sport=mlb&view=postseason")
    assert _cell_marks(mlb_guarded_page, "2014-world_series-all") == [
        {"alt": None, "title": None, "name": "MLB Network"}
    ]
    head = f"{VIEW} button[data-cell='2014-world_series-all'] .mlb-cell-head"
    assert mlb_guarded_page.locator(f"{head} .net-dot").count() == 1


def test_crew_not_listed_and_al_nl_split(post: Page) -> None:
    wc = post.locator(f"{VIEW} button[data-cell='2014-wild_card-AL']")
    assert "crew not listed" in wc.inner_text()
    assert "AL" in wc.inner_text()
    div = post.locator(f"{VIEW} tr[data-season='2019'] td[data-round='division'] button")
    assert div.count() == 1
    lcs = post.locator(f"{VIEW} tr[data-season='2019'] td[data-round='lcs'] button")
    assert "NL" in lcs.inner_text()
    ws = post.locator(f"{VIEW} button[data-cell='2014-world_series-all']")
    assert "AL" not in ws.inner_text().split()
    assert (
        post.locator(f"{VIEW} tr[data-season='2014'] td[data-round='division']")
        .inner_text()
        .endswith("—")
    )


def test_wikipedia_crew_excitement_and_viewers(post: Page) -> None:
    ws = post.locator(f"{VIEW} button[data-cell='2014-world_series-all']").inner_text()
    assert "Gus Penn" in ws
    assert "Hana Voss" in ws
    assert _cell_marks(post, "2014-world_series-all") == [
        {"alt": "Fox", "title": "Fox", "name": None}
    ]
    assert "Excitement 2.40 (1 game)" in ws
    assert "Avg 12.0M viewers, 1 of 1 games rated" in ws
    two = post.locator(f"{VIEW} button[data-cell='2019-division-AL']").inner_text()
    assert "2 games" in two
    assert "Excitement 1.25 (2 games)" in two
    assert "viewers" not in two


def test_2026_excitement_pending_and_no_stakes(post: Page) -> None:
    cell = post.locator(f"{VIEW} button[data-cell='2026-lcs-AL']").inner_text()
    assert "pending Retrosheet 2026" in cell
    assert "stakes" not in post.inner_text(VIEW).lower()


def test_a_historic_cell_without_excitement_is_not_called_pending(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    def handler(route: Route) -> None:
        resp = route.fetch()
        data = json.loads(resp.text())
        p = data["postseason"]
        k = next(i for i, s in enumerate(p["season"]) if s == 2019 and p["round"][i] == "division")
        p["mean_excitement"][k] = None
        p["excitement_n"][k] = 0
        route.fulfill(response=resp, body=json.dumps(data))

    mlb_guarded_page.route("**/mlb-data.json", handler)
    open_mlb_app(mlb_guarded_page, "?sport=mlb&view=postseason")
    old = mlb_guarded_page.locator(f"{VIEW} button[data-cell='2019-division-AL']").inner_text()
    assert "no excitement figure" in old and "pending" not in old
    # Quality is still pending (Apple booths), and 2026 is past Retrosheet's coverage.
    new = mlb_guarded_page.locator(f"{VIEW} button[data-cell='2026-lcs-AL']").inner_text()
    assert "pending Retrosheet 2026" in new


def test_cell_click_lists_games_and_deep_link(
    post: Page, open_mlb_app: Callable[..., None]
) -> None:
    post.click(f"{VIEW} button[data-cell='2019-division-AL']")
    assert post.evaluate(f"{HOOKS}.getTableIndexes()") == [9, 8]
    assert "cell=2019-division-AL" in post.url
    assert post.locator(f"{VIEW} .mlb-grid button[aria-pressed='true']").count() == 1
    post.click(f"{VIEW} button[data-cell='2019-division-AL']")
    assert post.evaluate(f"{HOOKS}.getTableIndexes()") == []
    open_mlb_app(post, "?sport=mlb&view=postseason&cell=2014-world_series-all")
    assert post.evaluate(f"{HOOKS}.getTableIndexes()") == [7]
    assert (
        post.locator(
            f"{VIEW} button[data-cell='2014-world_series-all'][aria-pressed='true']"
        ).count()
        == 1
    )


def test_unknown_cell_param_is_ignored(post: Page, open_mlb_app: Callable[..., None]) -> None:
    open_mlb_app(post, "?sport=mlb&view=postseason&cell=1999-division-AL")
    assert post.evaluate(f"{HOOKS}.getTableIndexes()") == []
    assert post.evaluate(f"{HOOKS}.getState().cell") is None


def test_phone_twin_has_a_merged_pinned_column_and_booths(
    mlb_mobile_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """13-14: 480px and under swaps the grid for one row per season, round and league."""
    page = mlb_mobile_page
    open_mlb_app(page, "?sport=mlb&view=postseason")
    assert page.locator(f"{VIEW} .mlb-grid").is_hidden()
    twin = page.locator(f"{VIEW} .mlb-phone-grid")
    assert twin.is_visible()
    assert twin.locator("thead th").all_inner_texts() == ["Season and round", "Booths"]
    first = twin.locator("tbody th.mlb-merged-col").first
    assert first.evaluate("e => e.getBoundingClientRect().width") == 96
    assert first.evaluate("e => getComputedStyle(e).position") == "sticky"
    assert first.locator(".mlb-merged-line").all_inner_texts() == ["2014 Wild Card", "AL"]
    assert twin.locator("td.mlb-booths-col").first.evaluate("e => e.offsetWidth") >= 200
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.locator(f"{VIEW} button[data-phone-cell='2014-world_series-all']").tap()
    assert page.evaluate(f"{HOOKS}.getTableIndexes()") == [7]


def test_phone_lists_each_season_credit_and_coverage(
    mlb_mobile_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """RT-13 per season at 480px and under: the season list under the phone twin carries the
    visible Wikipedia credit, the coverage line and its low marker the hidden grid holds."""
    page = mlb_mobile_page
    open_mlb_app(page, "?sport=mlb&view=postseason")
    twin = page.locator(f"{VIEW} .mlb-phone-season-notes")
    assert twin.locator("li .mlb-season").all_inner_texts() == ["2014", "2019", "2025", "2026"]
    credits = twin.locator(".mlb-season-credit")
    assert credits.count() == 2
    assert all(credits.nth(i).is_visible() for i in range(2))
    assert [credits.nth(i).get_attribute("href") for i in range(2)] == [
        "https://example.org/wiki/2014_Invented_Series",
        "https://example.org/wiki/2019_Invented_Series",
    ]
    cov = twin.locator(".mlb-season-coverage")
    assert cov.count() == 4
    assert all(cov.nth(i).is_visible() for i in range(4))
    assert twin.locator(".mlb-season-coverage[data-low='true']").count() == 3


def test_phone_booths_cell_caps_lines_with_plus_n_more(
    mlb_mobile_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """13-14: a cell with more booths than the line budget ends in '+N more'."""

    def handler(route: Route) -> None:
        resp = route.fetch()
        data = json.loads(resp.text())
        p = data["postseason"]
        k = next(i for i, s in enumerate(p["season"]) if s == 2019 and p["round"][i] == "division")
        p["booths"][k] = [[8, 7], [6, 7], [2, 3], [0, 1], [4, 5]]
        route.fulfill(response=resp, body=json.dumps(data))

    mlb_mobile_page.route("**/mlb-data.json", handler)
    open_mlb_app(mlb_mobile_page, "?sport=mlb&view=postseason")
    cell = mlb_mobile_page.locator(f"{VIEW} button[data-phone-cell='2019-division-AL']")
    assert cell.locator(".mlb-cell-booth").count() == 3
    assert cell.locator(".mlb-booth-more").inner_text() == "+2 more"


def test_phone_swipe_cue_shows_on_overflow_and_hides_after_a_scroll(
    mlb_mobile_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_mobile_page
    open_mlb_app(page, "?sport=mlb&view=postseason")
    wrap = page.locator(f"{VIEW} .mlb-grid-wrap")
    # Make the table wider than the scroller so the cue has something to say.
    page.evaluate(
        "() => { document.querySelector('#mlb-view-postseason .mlb-phone-grid')"
        ".style.minWidth = '700px'; }"
    )
    cue = page.locator(".module-head .swipe-cue")
    page.wait_for_function(
        """() => [...document.querySelectorAll('.swipe-cue')].some(
          (c) => c.textContent === 'Swipe for more \\u203a' && c.classList.contains('is-slot')
            && !c.classList.contains('is-idle'))"""
    )
    assert cue.first.inner_text() == "Swipe for more \u203a"
    wrap.evaluate("e => { e.scrollLeft = 120; }")
    page.wait_for_function(
        "() => [...document.querySelectorAll('.swipe-cue')]"
        ".every((c) => c.classList.contains('is-idle'))"
    )
    assert cue.first.evaluate("e => getComputedStyle(e).visibility") == "hidden"


def test_desktop_has_separate_columns_and_no_phone_twin(post: Page) -> None:
    assert post.locator(f"{VIEW} .mlb-grid").is_visible()
    assert post.locator(f"{VIEW} .mlb-phone-grid").is_hidden()
    assert post.locator(f"{VIEW} .mlb-phone-season-notes").is_hidden()
    heads = post.eval_on_selector_all(
        f"{VIEW} .mlb-grid thead th", "els => els.map(e => e.textContent)"
    )
    assert heads == ["Season", "Wild Card", "Division", "LCS", "World Series"]
