# ruff: noqa: E501
"""09-17: the MLB mount module on the synthetic MLB fixture (flag-on build)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page

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


def test_footer_credits_and_restore(
    mlb_guarded_page: Page, open_mlb_cfb: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    open_mlb_cfb(page)
    before = page.evaluate("document.getElementById('site-footer').outerHTML")
    page.click('#sport-switch button[data-sport="mlb"]')
    _wait_mlb(page)
    text = page.inner_text("#site-footer")
    assert RETROSHEET in text
    assert "Interested parties may contact Retrosheet at www.retrosheet.org" in text
    assert "RatingsReference.com" in text
    assert "Wikipedia (CC BY-SA 4.0)" in text
    assert "506 Sports" in text
    assert "relayed from a fan schedule blog" in text
    assert "CollegeFootballData" not in text
    rels = page.eval_on_selector_all("#site-footer .credit-line a", "els => els.map(e => e.rel)")
    assert rels and all(rel == "noopener noreferrer" for rel in rels)
    page.click('#sport-switch button[data-sport="cfb"]')
    page.wait_for_function("document.body.dataset.sport === 'cfb'")
    assert page.evaluate("document.getElementById('site-footer').outerHTML") == before


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
    assert search == "?sport=mlb&booth=1&game=3"
    open_mlb_app(page, search)
    state = page.evaluate("window.__mlbTestHooks.getState()")
    assert state["booth"] == "1"
    assert state["game"] == 3
    assert page.evaluate("document.getElementById('mlb-detail-panel').open") is True


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
