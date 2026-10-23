"""Crew pick chrome (plan 14-06, D-07): the selection-row chip, its clears, the phone count and
the Crews subtitle. Runs on the synthetic crews dataset; no vault content.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, expect
from test_site_crew_pick_views import _crew_names, _key, _set

pytestmark = pytest.mark.e2e

_ROW_HEIGHT_JS = "() => document.getElementById('selection-row').getBoundingClientRect().height"
_CHIP_WIDTH_JS = "() => document.querySelector('#chips > .chip-crew').getBoundingClientRect().width"


@pytest.fixture
def app(
    guarded_page: Page,
    serve_crews: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> Page:
    serve_crews(guarded_page)
    open_app(guarded_page, "")
    return guarded_page


def _state(page: Page) -> dict[str, Any]:
    out: dict[str, Any] = page.evaluate("() => window.__testHooks.getState()")
    return out


def _pick(page: Page) -> tuple[str, list[str]]:
    key = _key(page)
    _set(page, {"crew": key})
    return key, _crew_names(page, key)


def test_crew_chip_text_title_and_label(app: Page) -> None:
    _, names = _pick(app)
    chip = app.locator("#chips > .chip-crew")
    expect(chip).to_have_count(1)
    expect(chip).to_have_attribute("data-crew", "1")
    assert len(names) == 3
    text = chip.inner_text()
    assert text.replace("\n", " ").startswith("Crew: ")
    assert " / ".join(names) in text
    expected = f"Crew pick: {' and '.join(names)}. Remove"
    expect(chip).to_have_attribute("title", expected)
    expect(chip).to_have_attribute("aria-label", expected)
    expect(chip.locator(".chip-remove")).to_have_attribute("aria-label", "Remove crew pick")
    expect(app.locator("#chips")).to_be_visible()
    expect(app.locator("#clear-selection")).to_be_visible()
    expect(app.locator("#compare-toggle")).to_be_hidden()
    expect(app.locator("#together-toggle")).to_be_hidden()


def test_chip_x_clears_the_crew(app: Page) -> None:
    _pick(app)
    app.locator("#chips > .chip-crew .chip-remove").click()
    assert _state(app)["crew"] is None
    expect(app.locator("#chips > .chip-crew")).to_have_count(0)


def test_clear_selection_clears_the_crew(app: Page) -> None:
    _pick(app)
    app.locator("#clear-selection").click()
    assert _state(app)["crew"] is None


def test_clear_all_filters_clears_the_crew(app: Page) -> None:
    _pick(app)
    app.locator("#clear-filters").click()
    assert _state(app)["crew"] is None


def test_crew_counts_once_in_changed_controls_and_phone_label(app: Page) -> None:
    app.set_viewport_size({"width": 390, "height": 800})
    before = app.evaluate(
        "async () => { const m = await import('./modules/filters.js');"
        " const h = window.__testHooks;"
        " return m.changedControls(h.data, h.getState(), h.getView()); }"
    )
    assert "crew" not in before
    _pick(app)
    after = app.evaluate(
        "async () => { const m = await import('./modules/filters.js');"
        " const h = window.__testHooks;"
        " return m.changedControls(h.data, h.getState(), h.getView()); }"
    )
    assert after.count("crew") == 1
    assert len(after) == len(before) + 1
    expect(app.locator("#filters-button")).to_have_text(f"Filters · {len(after)} changed")
    expect(app.locator("#filter-chips")).to_contain_text("Crew:")


def test_booth_control_untouched_by_a_crew_pick(app: Page) -> None:
    _set(app, {"booth": ["a"]})
    before = _state(app)["booth"]
    key, _ = _pick(app)
    assert _state(app)["booth"] == before == ["a"]
    _set(app, {"crew": None})
    assert _state(app)["booth"] == before
    assert key


@pytest.mark.parametrize("width", [1440, 1104, 481])
def test_selection_row_does_not_shift_with_a_crew_chip(app: Page, width: int) -> None:
    app.set_viewport_size({"width": width, "height": 900})
    before: float = app.evaluate(_ROW_HEIGHT_JS)
    _pick(app)
    after: float = app.evaluate(_ROW_HEIGHT_JS)
    assert after == before
    chip_width: float = app.evaluate(_CHIP_WIDTH_JS)
    assert 96 <= chip_width <= 280
    names_overflow = app.evaluate(
        "() => getComputedStyle(document.querySelector('.chip-crew-names')).textOverflow"
    )
    assert names_overflow == "ellipsis"


# -- Crews subtitle and hints (Task 2) -----------------------------------------------------


def test_crews_subtitle_follows_the_master_range(app: Page) -> None:
    _set(app, {"view": "crews", "seasons": None})
    years: list[int] = app.evaluate("() => window.__testHooks.data.seasons")
    lo, hi = years[0], years[-1]
    subtitle = app.locator("#chart-subtitle")
    expect(subtitle).to_have_text(f"Seasons {lo}\u2013{hi}")
    assert "Selected announcers do not change this table." not in (subtitle.text_content() or "")
    _set(app, {"seasons": [hi, hi]})
    expect(subtitle).to_have_text(f"Season {hi}")


def test_map_prompt_hides_on_a_crew_pick(app: Page) -> None:
    _set(app, {"view": "map"})
    expect(app.locator("#chart-subtitle")).not_to_have_text("")
    _pick(app)
    expect(app.locator("#chart-subtitle")).to_have_text("")


def test_phone_filter_chip_never_widens_the_page(app: Page) -> None:
    """The phone "Crew: A / B / C" accent chip truncates inside the row (Plan 10 critique)."""
    app.set_viewport_size({"width": 390, "height": 800})
    _pick(app)
    widths = app.evaluate(
        "() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]"
    )
    scroll_w, client_w = widths
    assert scroll_w <= client_w


def test_phone_filter_chip_names_the_crew_once(app: Page) -> None:
    app.set_viewport_size({"width": 390, "height": 800})
    _, names = _pick(app)
    chip = app.locator("#filter-chips .filter-chip")
    expect(chip).to_have_count(1)
    assert chip.inner_text().strip() == f"Crew: {' / '.join(names)}"


def test_crew_chip_label_has_no_left_indent_from_an_empty_icon_slot(app: Page) -> None:
    _pick(app)
    m = app.evaluate(
        """() => {
          const chip = document.querySelector('#chips > .chip-crew');
          const cs = getComputedStyle(chip);
          const label = chip.querySelector('.chip-crew-label').getBoundingClientRect();
          return { inset: label.left - chip.getBoundingClientRect().left,
                   own: parseFloat(cs.borderLeftWidth) + parseFloat(cs.paddingLeft),
                   glyphs: chip.querySelectorAll('.chip-glyph').length };
        }"""
    )
    assert m["glyphs"] == 0
    assert abs(m["inset"] - m["own"]) <= 0.5, f"label is {m['inset'] - m['own']}px past the chip padding"
