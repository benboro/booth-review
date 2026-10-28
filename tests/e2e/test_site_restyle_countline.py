"""Phase 26 round 3: the count line is the one fixed band that holds the count and detail on the
left and every selection action on the right (the reserved selection row is gone).

Covers the structure (no #selection-row, Clear all filters always last), the compare-only person
chips, the width/people label switch, and a 0px layout snapshot across every pick state at four
widths. Synthetic fixtures only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from contrast import ratio
from dark_checks import set_theme
from layout_shift import layout_snapshot, set_state
from playwright.sync_api import Page
from test_site_crew_pick_views import _key
from test_site_crew_pick_views import _set as _set_crew

pytestmark = pytest.mark.e2e

KEYS = ("tabs", "toolbar_bottom", "group_x", "clear_x", "summary_h")
TWO = "?people=dale-harlow,kris-venn&mode=compare"
FOUR = "?people=dale-harlow,kris-venn,sam-delgado,pat-rowan&mode=compare"
STATES = {
    "no picks": "",
    "one pick": "?people=dale-harlow",
    "one person plus Networks": "?people=dale-harlow&networks=net-c",
    "compare, 2 people": TWO,
    "compare, 4 people": FOUR,
}
LABEL_JS = """() => ['compare-toggle', 'together-toggle', 'clear-selection'].map((id) => {
  const long = document.querySelector(`#${id} .lbl-long`);
  return getComputedStyle(long).display !== 'none' ? 'long' : 'short';
})"""


def _open(page: Page, open_app: Callable[..., None], width: int, query: str = "") -> None:
    page.set_viewport_size({"width": width, "height": 900})
    open_app(page, query)
    page.evaluate("() => document.fonts.ready")


# ---- structure ----


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_selection_row_is_gone_and_clear_all_is_always_last(
    guarded_page: Page, open_app: Callable[..., None], theme: str
) -> None:
    _open(guarded_page, open_app, 1440)
    set_theme(guarded_page, theme)
    for name, query in STATES.items():
        open_app(guarded_page, query)
        set_theme(guarded_page, theme)
        assert guarded_page.locator("#selection-row").count() == 0, name
        last = guarded_page.evaluate(
            "document.querySelector('#summary .sum-right').lastElementChild.id"
        )
        assert last == "clear-filters", name
        assert guarded_page.locator("#clear-filters").is_visible(), name


# ---- zero shift ----


@pytest.mark.parametrize("width", [1440, 1280, 1024, 768])
def test_no_state_moves_the_count_line_or_clear_all(
    guarded_page: Page, open_app: Callable[..., None], width: int
) -> None:
    _open(guarded_page, open_app, width)
    base = layout_snapshot(guarded_page, include=KEYS)
    assert base["summary_h"] == (32 if width >= 1104 else 72)
    for name, query in STATES.items():
        open_app(guarded_page, query)
        assert layout_snapshot(guarded_page, include=KEYS) == base, name
    set_state(guarded_page, {"view": "weekend"})
    assert layout_snapshot(guarded_page, include=KEYS) == base, "This weekend"


@pytest.mark.parametrize("width", [1440, 1024])
def test_a_crew_pick_moves_nothing(
    guarded_page: Page,
    serve_crews: Callable[[Page], None],
    open_app: Callable[..., None],
    width: int,
) -> None:
    serve_crews(guarded_page)
    _open(guarded_page, open_app, width)
    base = layout_snapshot(guarded_page, include=KEYS)
    _set_crew(guarded_page, {"crew": _key(guarded_page)})
    assert guarded_page.locator("#chips > .chip-crew").count() == 1
    assert layout_snapshot(guarded_page, include=KEYS) == base


# ---- labels ----


@pytest.mark.parametrize(
    ("width", "query", "expected"),
    [
        (1440, TWO, "long"),
        (1280, TWO, "long"),
        (1440, FOUR, "short"),
        (1200, TWO, "short"),
        (1024, TWO, "short"),
    ],
)
def test_toggle_labels_follow_width_and_people(
    guarded_page: Page, open_app: Callable[..., None], width: int, query: str, expected: str
) -> None:
    _open(guarded_page, open_app, width, query)
    assert guarded_page.evaluate(LABEL_JS) == [expected] * 3


def test_short_clear_label_is_clear_people_and_names_stay_long(
    guarded_page: Page, open_app: Callable[..., None]
) -> None:
    _open(guarded_page, open_app, 1024, TWO)
    assert guarded_page.locator("#clear-selection .lbl-short").text_content() == "Clear people"
    assert guarded_page.get_attribute("#clear-selection", "aria-label") == "Clear selection"
    assert guarded_page.get_attribute("#compare-toggle", "aria-label") == "Compare people"
    assert guarded_page.get_attribute("#together-toggle", "aria-label") == "Called together"


# ---- chips ----


def test_person_chips_show_only_in_compare_mode(
    guarded_page: Page, open_app: Callable[..., None]
) -> None:
    _open(guarded_page, open_app, 1440, "?people=dale-harlow,kris-venn")
    assert guarded_page.locator("#chips .chip").count() == 0
    assert (
        guarded_page.locator("#trigger-announcers .filter-value").inner_text() == "Dale Harlow +1"
    )

    _open(guarded_page, open_app, 1440, TWO)
    chips = guarded_page.locator("#chips .chip")
    assert chips.count() == 2
    for i, name in enumerate(["Dale Harlow", "Kris Venn"]):
        chip = chips.nth(i)
        assert chip.locator(".chip-glyph").text_content() != ""
        assert chip.locator("span:not(.chip-glyph)").text_content() == name
        assert chip.locator(".chip-remove").get_attribute("aria-label") == f"Remove {name}"
    # Each name appears once: the Announcers entry counts people.
    assert guarded_page.locator("#trigger-announcers .filter-value").inner_text() == "2 people"


# ---- detail and contrast ----


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_detail_contrast_and_text_after_a_networks_pick(
    guarded_page: Page, open_app: Callable[..., None], theme: str
) -> None:
    _open(guarded_page, open_app, 1440, "?networks=net-c")
    set_theme(guarded_page, theme)
    detail = guarded_page.locator("#summary-detail")
    text = detail.inner_text()
    assert text == "2021\u20132026, Conference Network"
    colors: dict[str, Any] = guarded_page.evaluate(
        "() => ({fg: getComputedStyle(document.getElementById('summary-detail')).color,"
        " bg: getComputedStyle(document.body).backgroundColor})"
    )
    assert ratio(colors["fg"], colors["bg"]) >= 4.5
