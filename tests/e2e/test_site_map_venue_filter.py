"""Phase 11 plan 10 (D-05): a venue filter narrows the Matched games table. Synthetic data only."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

OpenApp = Callable[[Page, str], None]

CHIP_TEXT = "() => document.querySelector('#venue-chips .chip > span')?.textContent ?? null"
ROWS = "() => document.querySelectorAll('#games-table tbody tr').length"


def _open_map(page: Page, open_app: OpenApp, query: str = "?view=map") -> None:
    open_app(page, query)
    page.wait_for_function("() => window.__testHooks.mapRenders >= 1")
    page.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")


def _model(page: Page) -> dict[str, Any]:
    model: dict[str, Any] = page.evaluate("() => window.__testHooks.getMapModel()")
    return model


def _pixel(page: Page, x: float, y: float) -> tuple[float, float]:
    px, py = page.evaluate(
        """([x, y]) => {
          const gd = document.getElementById('map-chart');
          const r = gd.getBoundingClientRect();
          const fl = gd._fullLayout;
          return [r.left + fl.xaxis._offset + fl.xaxis.l2p(x),
                  r.top + fl.yaxis._offset + fl.yaxis.l2p(y)];
        }""",
        [x, y],
    )
    return px, py


def _first_key(page: Page, open_app: OpenApp) -> str:
    _open_map(page, open_app)
    key: str = _model(page)["venueDots"][0]["key"]
    return key


def test_venue_param_fills_table_and_shows_chip(guarded_page: Page, open_app: OpenApp) -> None:
    key = _first_key(guarded_page, open_app)
    open_app(guarded_page, f"?venue={key}")
    guarded_page.wait_for_function("() => document.querySelector('#venue-chips .chip')")
    assert guarded_page.locator("#table-empty").is_hidden()
    assert guarded_page.evaluate(ROWS) > 0
    text = guarded_page.evaluate(CHIP_TEXT)
    assert text.startswith("Venue: ")
    name = text.removeprefix("Venue: ")
    label = guarded_page.locator("#venue-chips .chip-remove").get_attribute("aria-label")
    assert label == f"Remove venue filter: {name}"
    title = guarded_page.locator("#venue-chips .chip").get_attribute("title")
    assert title is not None and title.startswith(name)


def test_removing_chip_clears_venue_without_scrolling(
    guarded_page: Page, open_app: OpenApp
) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 500})
    key = _first_key(guarded_page, open_app)
    open_app(guarded_page, f"?venue={key}")
    guarded_page.wait_for_function("() => document.querySelector('#venue-chips .chip')")
    guarded_page.locator("#venue-chips .chip-remove").scroll_into_view_if_needed()
    before = guarded_page.evaluate("() => window.scrollY")
    guarded_page.locator("#venue-chips .chip-remove").click()
    guarded_page.wait_for_function("() => !location.search.includes('venue=')")
    assert guarded_page.locator("#venue-chips .chip").count() == 0
    assert guarded_page.locator("#table-empty").is_visible()
    assert guarded_page.evaluate(ROWS) == 0
    assert guarded_page.evaluate("() => window.scrollY") == before


def test_clear_all_clears_venue_but_keeps_colors_off(guarded_page: Page, open_app: OpenApp) -> None:
    key = _first_key(guarded_page, open_app)
    open_app(guarded_page, f"?venue={key}&colors=off")
    guarded_page.wait_for_function("() => document.querySelector('#venue-chips .chip')")
    guarded_page.evaluate("() => document.getElementById('clear-filters').click()")
    guarded_page.wait_for_function("() => !location.search.includes('venue=')")
    assert guarded_page.locator("#venue-chips .chip").count() == 0
    assert "colors=off" in guarded_page.evaluate("() => location.search")


def test_venue_intersects_with_school(guarded_page: Page, open_app: OpenApp) -> None:
    key = _first_key(guarded_page, open_app)
    open_app(guarded_page, f"?venue={key}")
    guarded_page.wait_for_function("() => document.querySelector('#venue-chips .chip')")
    venue_rows = guarded_page.evaluate(ROWS)
    open_app(guarded_page, f"?venue={key}&school=boulder-pass")
    guarded_page.wait_for_function("() => document.querySelector('#venue-chips .chip')")
    assert guarded_page.evaluate(ROWS) <= venue_rows


def test_filtered_out_venue_shows_no_match_copy_and_keeps_chip(
    guarded_page: Page, open_app: OpenApp
) -> None:
    key = _first_key(guarded_page, open_app)
    open_app(guarded_page, f"?venue={key}")
    guarded_page.wait_for_function("() => document.querySelector('#venue-chips .chip')")
    guarded_page.evaluate("() => window.__testHooks.setState({ networks: [] })")
    guarded_page.wait_for_function("() => !document.getElementById('venue-nomatch').hidden")
    assert guarded_page.locator("#venue-nomatch").inner_text() == "No games match these filters."
    assert guarded_page.locator("#venue-chips .chip").count() == 1
    assert guarded_page.locator("#games-table").is_hidden()


def test_heading_row_height_is_stable_with_and_without_chip(
    guarded_page: Page, open_app: OpenApp
) -> None:
    key = _first_key(guarded_page, open_app)
    open_app(guarded_page, "")
    plain = guarded_page.evaluate(
        "() => document.querySelector('.matched-heading-row').getBoundingClientRect().height"
    )
    open_app(guarded_page, f"?venue={key}")
    guarded_page.wait_for_function("() => document.querySelector('#venue-chips .chip')")
    chipped = guarded_page.evaluate(
        "() => document.querySelector('.matched-heading-row').getBoundingClientRect().height"
    )
    assert abs(plain - chipped) <= 1


def test_markup_in_a_venue_name_renders_as_text(guarded_page: Page, site_url: str) -> None:
    def mutate(route: Any) -> None:
        response = route.fetch()
        raw = response.json()
        for i, venue in enumerate(raw["lookups"]["venues"]):
            venue["name"] = f"<img src=x onerror=window.__pwned=1>{i}"
        route.fulfill(json=raw)

    guarded_page.route("**/site-data.json*", mutate)
    guarded_page.goto(f"{site_url}/index.html?view=map")
    guarded_page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    guarded_page.wait_for_function("() => window.__testHooks.mapRenders >= 1")
    key = _model(guarded_page)["venueDots"][0]["key"]
    guarded_page.goto(f"{site_url}/index.html?view=map&venue={key}")
    guarded_page.wait_for_function("() => document.querySelector('#venue-chips .chip')")
    assert guarded_page.locator("#venue-chips img").count() == 0
    assert "<img" in guarded_page.evaluate(CHIP_TEXT)
    assert guarded_page.evaluate("() => window.__pwned") is None
