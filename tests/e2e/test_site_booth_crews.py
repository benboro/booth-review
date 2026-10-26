"""Crews tab shell (Phase 10 plan 10-09, rewritten in Phase 14 plan 14-07): tab, URL, legend,
credits (RT-10), the excitement caption (RT-20) and the pick-does-not-filter rule.

Runs on the synthetic crews dataset (tests/e2e/crews_fixture.py); no vault content. The table
itself is covered in test_site_crews_table.py. Hand-computed expectations, from the CASE_*
constants: the dataset spans 2022-2025 with the excitement model break in 2025, so the
caption shows for the default range and for 2024-2025 and not for 2022-2024; the trio crew
(`trio-pbp`, `trio-a1`, `trio-a2`) is the only crew holding `trio-pbp`, so a pick of that
person highlights exactly one row and drops none; and a Tier A booth filter keeps the one
cited booth (4 games, 1 row).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest
from crews_fixture import CASE_TRIO
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

# The Crew-mode note states A2(a) (14-11 panel fix F6).
_UNKNOWN_NOTE = (
    "A person of unknown role on a telecast with a play-by-play voice is not shown. "
    "Telecasts with no play-by-play voice are grouped by their exact people, and unknown "
    "roles are marked."
)

# RT-10, closing the Phase 12 gap: the three credit lines as full sentences.
CREDITS = [
    "Data provided by CollegeFootballData.com",
    "Viewership figures: Ratings Reference and the second sources credited in each game's "
    "detail panel.",
    "Booth order from network press releases, cited per season in "
    "data/reference/cfb_booth_ranks.csv.",
]
CONFOUND = "Avg viewers (rated games) mostly reflects which games a crew was assigned."


@pytest.fixture
def crews(
    guarded_page: Page,
    serve_crews: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> Page:
    serve_crews(guarded_page)
    open_app(guarded_page, "?view=crews&perseason=0")
    return guarded_page


def _set(page: Page, patch: dict[str, Any]) -> None:
    page.evaluate("(patch) => window.__testHooks.setState(patch)", patch)


def _captions(page: Page) -> list[str]:
    return [
        re.sub(r"\s+", " ", c).strip()
        for c in page.locator("#crews-panel p.caption").all_inner_texts()
    ]


def _rows(page: Page) -> Any:
    return page.locator("#crews-panel tbody tr.crews-row")


def test_credits_are_the_three_rt10_sentences_verbatim(crews: Page) -> None:
    panel = crews.locator("#crews-panel")
    link = panel.get_by_role("link", name=CREDITS[0])
    expect(link).to_have_attribute("href", "https://collegefootballdata.com")
    captions = _captions(crews)
    for line in CREDITS:
        assert line in captions
    assert captions[-3:] == CREDITS
    assert CONFOUND in captions
    assert _UNKNOWN_NOTE in captions
    # Gone with the family-season table.
    assert "Rated shows how many games have a viewership figure." not in " ".join(captions)


def test_credits_stay_with_the_empty_state(crews: Page) -> None:
    _set(crews, {"booth": ["other"]})
    assert _captions(crews)[-3:] == CREDITS


def test_crews_source_never_uses_markup_apis(crews: Page) -> None:
    src = crews.evaluate("async () => (await fetch('modules/crews.js')).text()")
    for banned in ("innerHTML", "insertAdjacentHTML", "outerHTML"):
        assert banned not in src
    for gone in ("CREWS_HINT", "buildCrewsModel", "RATED_NOTE"):
        assert gone not in src


def test_person_selection_highlights_rows_and_the_old_hint_is_gone(crews: Page) -> None:
    """A person pick used to be ignored (hint: "Selected announcers do not change this table.").
    Now it highlights the rows holding the person and drops none."""
    expect(crews.locator("#chart-subtitle")).not_to_contain_text("Selected announcers")
    total = crews.evaluate(
        """async () => {
          const G = await import('./modules/crew-groups.js');
          const h = window.__testHooks;
          return G.buildCrewRows(h.data, h.getView(), {}).totalRows;
        }"""
    )
    _set(crews, {"people": [CASE_TRIO["pbp"]]})
    while crews.locator("#crews-panel .crews-more").count():
        crews.locator("#crews-panel .crews-more").click()
    expect(_rows(crews)).to_have_count(total)
    highlighted = crews.locator("#crews-panel tr.is-highlighted")
    expect(highlighted).to_have_count(1)
    expect(highlighted).to_contain_text("Trio Pbp")


def test_subtitle_is_the_seasons_range(crews: Page) -> None:
    expect(crews.locator("#chart-subtitle")).to_have_text("Seasons 2022\u20132025")
    _set(crews, {"seasons": [2024, 2024]})
    expect(crews.locator("#chart-subtitle")).to_have_text("Season 2024")


def test_url_tab_click_keyboard_and_controls(
    guarded_page: Page,
    serve_crews: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> None:
    serve_crews(guarded_page)
    open_app(guarded_page, "")
    guarded_page.locator("#tab-crews").click()
    assert "view=crews" in guarded_page.url
    assert guarded_page.locator("#tab-crews").get_attribute("aria-selected") == "true"
    assert guarded_page.locator("#crews-panel").is_visible()
    assert not guarded_page.locator("#chart").is_visible()
    for sel in ("#scatter-controls", "#bar-controls"):
        assert (
            guarded_page.evaluate(
                "(s) => getComputedStyle(document.querySelector(s)).visibility", sel
            )
            == "hidden"
        )
    guarded_page.locator("#tab-scatter").click()
    assert "view=crews" not in guarded_page.url
    assert not guarded_page.locator("#crews-panel").is_visible()
    guarded_page.locator("#tab-scatter").focus()
    guarded_page.keyboard.press("End")
    # This weekend (Phase 18) is the last tab; Crews is the one before it.
    assert guarded_page.evaluate("() => document.activeElement.id") == "tab-weekend"
    guarded_page.keyboard.press("ArrowLeft")
    assert guarded_page.evaluate("() => document.activeElement.id") == "tab-crews"
    guarded_page.keyboard.press("Enter")
    assert guarded_page.locator("#tab-crews").get_attribute("aria-selected") == "true"
    # ?view=crews loads selected
    open_app(guarded_page, "?view=crews")
    assert guarded_page.locator("#tab-crews").get_attribute("aria-selected") == "true"
    assert guarded_page.locator("#crews-panel").is_visible()


def test_unknown_view_falls_back_to_scatter(
    guarded_page: Page,
    serve_crews: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> None:
    serve_crews(guarded_page)
    open_app(guarded_page, "?view=crewz")
    assert guarded_page.locator("#tab-scatter").get_attribute("aria-selected") == "true"


def test_excitement_caption_shows_when_the_range_reaches_the_break_season(crews: Page) -> None:
    caption = crews.locator("#excitement-caption")
    expect(caption).to_be_visible()
    assert "2025+ excitement uses CFBD's new win-probability model" in (
        caption.text_content() or ""
    )
    _set(crews, {"seasons": [2022, 2024]})
    expect(caption).to_be_hidden()
    _set(crews, {"seasons": [2022, 2025]})
    expect(caption).to_be_visible()


def test_legend_chips_are_hidden_on_crews_and_networks_filter_still_applies(
    guarded_page: Page,
    serve_crews: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> None:
    serve_crews(guarded_page)
    open_app(guarded_page, "")
    assert guarded_page.locator("#legend-row").is_visible()
    guarded_page.locator("#tab-crews").click()
    assert not guarded_page.locator("#legend-row").is_visible()
    assert guarded_page.locator("#legend-chips").is_hidden()
    before = guarded_page.locator("#crews-panel .crews-count").inner_text()
    _set(guarded_page, {"networks": ["net-a"]})
    assert guarded_page.locator("#crews-panel .crews-count").inner_text() != before
    guarded_page.locator("#tab-scatter").click()
    assert guarded_page.locator("#legend-row").is_visible()


def test_booth_filter_recounts_and_a_crew_pick_leaves_it_alone(crews: Page) -> None:
    _set(crews, {"booth": ["a"]})
    expect(_rows(crews)).to_have_count(1)
    expect(_rows(crews).locator("td.num").first).to_have_text("4")
    _rows(crews).first.click()
    state = crews.evaluate("() => window.__testHooks.getState()")
    assert state["booth"] == ["a"]
    assert state["crew"] is not None
    expect(_rows(crews)).to_have_count(1)
