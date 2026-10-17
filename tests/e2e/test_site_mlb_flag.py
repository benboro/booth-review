"""09-15: with MLB off the page never touches MLB; the per-sport switch still serves NFL once."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


def _track(page: Page) -> list[str]:
    urls: list[str] = []
    page.on("request", lambda r: urls.append(r.url))
    return urls


def _count(urls: list[str], name: str) -> int:
    return sum(1 for u in urls if name in u.split("?")[0])


def _errors(page: Page) -> list[str]:
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    return errors


def _ready(page: Page) -> None:
    page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")


def test_cfb_only_never_requests_mlb(guarded_page: Page, site_url: str) -> None:
    page = guarded_page
    urls = _track(page)
    page.goto(f"{site_url}/index.html")
    _ready(page)
    page.wait_for_load_state("networkidle")
    assert _count(urls, "mlb-data.json") == 0
    assert _count(urls, "sports/mlb/index.js") == 0


def _assert_param_falls_back(page: Page, url: str) -> None:
    urls = _track(page)
    errors = _errors(page)
    page.goto(f"{url}/index.html?sport=mlb&view=bars")
    _ready(page)
    assert page.evaluate("location.search") == "?view=bars"
    assert page.evaluate("document.body.dataset.sport") in (None, "", "cfb")
    assert _count(urls, "mlb-data.json") == 0
    assert _count(urls, "sports/mlb/index.js") == 0
    assert errors == []


def test_mlb_param_falls_back_to_cfb_only(guarded_page: Page, site_url: str) -> None:
    _assert_param_falls_back(guarded_page, site_url)


def test_mlb_param_falls_back_to_cfb_with_nfl(nfl_guarded_page: Page, nfl_site_url: str) -> None:
    _assert_param_falls_back(nfl_guarded_page, nfl_site_url)
    assert nfl_guarded_page.locator('#sport-switch button[data-sport="mlb"]').count() == 0
    assert nfl_guarded_page.locator('#sport-switch button[data-sport="nfl"]').count() == 1


def test_no_mlb_button_cfb_only(guarded_page: Page, site_url: str) -> None:
    guarded_page.goto(f"{site_url}/index.html")
    _ready(guarded_page)
    assert guarded_page.locator('#sport-switch button[data-sport="mlb"]').count() == 0


def test_nfl_round_trip_loads_module_once(
    nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    urls = _track(page)
    open_flagon_cfb(page)
    for _ in range(2):
        page.click('#sport-switch button[data-sport="nfl"]')
        page.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.ready === true")
        assert page.evaluate("document.body.dataset.sport") == "nfl"
        page.click('#sport-switch button[data-sport="cfb"]')
        page.wait_for_function("document.body.dataset.sport === 'cfb'")
    assert _count(urls, "sports/nfl/index.js") == 1
    assert _count(urls, "mlb-data.json") == 0
