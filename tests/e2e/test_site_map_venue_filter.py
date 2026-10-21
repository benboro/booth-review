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


# ---------------------------------------------------------------- click and tap

_TRACE = """(name) => {
  const t = document.getElementById('map-chart').data.find((d) => d.name === name);
  return t ? t.x.length : null;
}"""
_IMAGES = "() => document.getElementById('map-chart').layout.images?.length ?? 0"


def _click_dot(page: Page, x: float, y: float) -> None:
    """Scrolls the dot to mid-viewport, then hovers and clicks it."""
    _, py = _pixel(page, x, y)
    page.evaluate("(dy) => window.scrollBy(0, dy)", py - 300)
    px, py = _pixel(page, x, y)
    # Approach from the left along the marker's row, so the start is inside the plot even for
    # Dublin (near the top edge) and Nassau (near the bottom edge).
    page.mouse.move(px - 40, py)
    page.mouse.move(px, py, steps=4)
    page.mouse.click(px, py)


def test_desktop_click_filters_table_scrolls_focuses_and_announces(
    guarded_page: Page, open_app: OpenApp
) -> None:
    guarded_page.emulate_media(reduced_motion="reduce")
    guarded_page.set_viewport_size({"width": 1280, "height": 700})
    _open_map(guarded_page, open_app)
    dot = _model(guarded_page)["venueDots"][0]
    dots_before = guarded_page.evaluate(_TRACE, "venue-dots")
    images_before = guarded_page.evaluate(_IMAGES)
    _click_dot(guarded_page, dot["x"], dot["y"])
    guarded_page.wait_for_function(f"() => location.search.includes('venue={dot['key']}')")
    guarded_page.wait_for_function("() => document.querySelector('#venue-chips .chip')")
    assert guarded_page.evaluate("() => document.activeElement.id") == "matched-games-title"
    rows = guarded_page.evaluate(ROWS)
    assert rows > 0
    name = guarded_page.evaluate(CHIP_TEXT).removeprefix("Venue: ")
    noun = "game" if rows == 1 else "games"
    assert guarded_page.locator("#venue-status").inner_text() == f"Showing {rows} {noun} at {name}"
    guarded_page.wait_for_function(
        """() => {
          const top = document.getElementById('matched-games').getBoundingClientRect().top;
          const root = document.documentElement;
          const atEnd = window.scrollY + window.innerHeight >= root.scrollHeight - 2;
          return Math.abs(top) <= 2 || (atEnd && top >= -2);
        }"""
    )
    assert guarded_page.evaluate(_TRACE, "venue-selected") == 1
    assert guarded_page.evaluate(_TRACE, "venue-dots") == dots_before
    assert guarded_page.evaluate(_IMAGES) == images_before


@pytest.mark.parametrize("label", ["Dublin", "Nassau"])
def test_clicking_an_edge_marker_filters_to_its_group(
    guarded_page: Page, open_app: OpenApp, label: str
) -> None:
    guarded_page.emulate_media(reduced_motion="reduce")
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    _open_map(guarded_page, open_app)
    marker = next(m for m in _model(guarded_page)["markers"] if m["label"] == label)
    _click_dot(guarded_page, marker["x"], marker["y"])
    guarded_page.wait_for_function(f"() => location.search.includes('venue={label.lower()}')")
    guarded_page.wait_for_function("() => document.querySelector('#venue-chips .chip')")
    assert guarded_page.evaluate(CHIP_TEXT) == f"Venue: {label}"
    assert guarded_page.evaluate(ROWS) > 0


def test_group_key_chip_reads_the_marker_label(guarded_page: Page, open_app: OpenApp) -> None:
    """The Dublin group key lists every Dublin-group game under 'Venue: Dublin' (D-10)."""
    open_app(guarded_page, "?view=map&venue=dublin")
    guarded_page.wait_for_function("() => document.querySelector('#venue-chips .chip')")
    assert guarded_page.evaluate(CHIP_TEXT) == "Venue: Dublin"
    assert guarded_page.evaluate(ROWS) > 0


def test_chip_survives_tab_switch_and_reload(guarded_page: Page, open_app: OpenApp) -> None:
    key = _first_key(guarded_page, open_app)
    open_app(guarded_page, f"?view=map&venue={key}")
    guarded_page.wait_for_function("() => document.querySelector('#venue-chips .chip')")
    guarded_page.evaluate("() => window.__testHooks.setState({ view: 'bars' })")
    guarded_page.wait_for_function("() => location.search.includes('view=bars')")
    assert guarded_page.locator("#venue-chips .chip").count() == 1
    guarded_page.evaluate("() => window.__testHooks.setState({ view: 'map' })")
    assert guarded_page.locator("#venue-chips .chip").count() == 1
    guarded_page.reload()
    guarded_page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    assert guarded_page.locator("#venue-chips .chip").count() == 1
    assert f"venue={key}" in guarded_page.evaluate("() => location.search")
