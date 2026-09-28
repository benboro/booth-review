"""Top-bar browser tests (SITE-02, SITE-08, SITE-10, SITE-12; D-07, D-08, A1)
-- proven against the fixture build served by `guarded_page`/`open_app`, per
`tests/fixtures/contract/site-data.fixture.json`'s 12 dots and 10 people.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Locator, Page, expect

pytestmark = pytest.mark.e2e


_HIGHLIGHT_CUSTOMDATA_JS = "() => document.getElementById('chart').data.at(-1).customdata"


def _highlight_customdata(page: Page) -> list[int]:
    result: list[int] = page.evaluate(_HIGHLIGHT_CUSTOMDATA_JS)
    return result


def _options(page: Page) -> Locator:
    return page.locator("#person-results li[role='option']:not([aria-disabled])")


def _search(page: Page, query: str) -> None:
    page.fill("#person-search", query)


def _add_person_by_query(page: Page, query: str, index: int = 0) -> None:
    """Types `query`, waits out the 120ms debounce, and clicks the option at `index`."""
    _search(page, query)
    option = _options(page).nth(index)
    expect(option).to_be_visible()
    option.click()


def test_search_dale_harlow_shows_two_options_and_click_adds_chip(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Same-surname people (dale-harlow / dale-harlow-jr) stay distinct
    options, ordered canonical-name first; clicking one adds a chip,
    highlights exactly its own dots, and updates the summary and URL."""
    open_app(guarded_page, "")
    _search(guarded_page, "Dale Harlow")
    options = _options(guarded_page)
    expect(options).to_have_count(2)
    texts = options.all_text_contents()
    assert "Jr." not in texts[0]
    assert texts[0].startswith("Dale Harlow")
    assert texts[1].startswith("Dale Harlow Jr.")

    options.nth(0).click()
    guarded_page.wait_for_function("location.search === '?people=dale-harlow'")

    chips = guarded_page.locator("#chips .chip")
    expect(chips).to_have_count(1)
    assert chips.first.inner_text().startswith("Dale Harlow")

    assert sorted(_highlight_customdata(guarded_page)) == [0, 8]
    assert guarded_page.inner_text("#summary-count") == "2 rated telecasts"
    expected_detail = f"2019{chr(0x2013)}2026 {chr(0x00B7)} Alpha Sports"
    assert guarded_page.inner_text("#summary-detail") == expected_detail


def test_kristopher_query_keyboard_path_adds_kris_venn(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Searching a variant shows it in the option text; ArrowDown then Enter
    adds the person via the keyboard (no click)."""
    open_app(guarded_page, "")
    _search(guarded_page, "kristopher")
    options = _options(guarded_page)
    expect(options).to_have_count(1)
    assert "Kristopher Venn" in options.first.inner_text()

    guarded_page.press("#person-search", "ArrowDown")
    guarded_page.press("#person-search", "Enter")
    guarded_page.wait_for_function("location.search === '?people=kris-venn'")

    chips = guarded_page.locator("#chips .chip")
    expect(chips).to_have_count(1)
    assert chips.first.inner_text().startswith("Kris Venn")


def test_venn_query_lists_kris_and_jax_as_separate_options(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Two different people sharing a surname both surface for a surname-only query."""
    open_app(guarded_page, "")
    _search(guarded_page, "venn")
    options = _options(guarded_page)
    expect(options).to_have_count(2)
    joined = " ".join(options.all_text_contents())
    assert "Kris Venn" in joined
    assert "Jax Venn" in joined


def test_alt_cast_selection_notes_it_in_the_summary(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-08: taylor-vance's alt-cast appearance on the combined-feed dot 7
    is called out in the counts-only summary line."""
    open_app(guarded_page, "")
    _add_person_by_query(guarded_page, "Taylor Vance")
    assert "includes 1 alt-cast game" in guarded_page.inner_text("#summary-detail")


def test_compare_mode_assigns_shapes_and_shows_shared_booth(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-07: each selected person gets a shape in selection order, a shared
    game gets the star marker, and the shape legend lists "Shared booth"."""
    open_app(guarded_page, "")
    _add_person_by_query(guarded_page, "Kris Venn")
    _add_person_by_query(guarded_page, "Sam Delgado")

    guarded_page.click("#compare-toggle")
    guarded_page.wait_for_function("location.search.includes('mode=compare')")

    symbols = guarded_page.evaluate("() => window.__testHooks.getView().symbols")
    assert symbols == {"1": "circle", "2": "square", "6": "star", "9": "circle", "10": "square"}

    chips = guarded_page.locator("#chips .chip")
    assert chips.nth(0).inner_text().startswith("●")
    assert chips.nth(1).inner_text().startswith("■")

    assert "Shared booth" in guarded_page.inner_text("#shape-legend")


def test_compare_mode_caps_at_four_people(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-07: a 5th person can't be added in compare mode; the chips stay at
    4 and the cap note appears."""
    open_app(guarded_page, "")
    for query in ["Dale Harlow", "Dale Harlow Jr.", "Kris Venn", "Jax Venn"]:
        _add_person_by_query(guarded_page, query)

    guarded_page.click("#compare-toggle")
    guarded_page.wait_for_function("location.search.includes('mode=compare')")

    _add_person_by_query(guarded_page, "Pat Rowan")

    chips = guarded_page.locator("#chips .chip")
    expect(chips).to_have_count(4)
    assert guarded_page.is_visible("#compare-note")
    assert "Compare mode holds up to 4 people." in guarded_page.inner_text("#compare-note")


def test_called_together_intersects_and_updates_url(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-10: "Called together" switches multi-select to AND."""
    open_app(guarded_page, "")
    _add_person_by_query(guarded_page, "Kris Venn")
    _add_person_by_query(guarded_page, "Sam Delgado")

    guarded_page.click("#together-toggle")
    guarded_page.wait_for_function("location.search.includes('mode=together')")

    assert _highlight_customdata(guarded_page) == [6]


def test_reload_restores_compare_and_together_selection(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-12: people, compare, and together all survive a reload from the
    copied URL, in selection order, with the same highlight."""
    open_app(guarded_page, "")
    _add_person_by_query(guarded_page, "Kris Venn")
    _add_person_by_query(guarded_page, "Sam Delgado")
    guarded_page.click("#compare-toggle")
    guarded_page.wait_for_function("location.search.includes('mode=')")
    guarded_page.click("#together-toggle")
    guarded_page.wait_for_function("location.search.includes('together')")

    before_highlight = _highlight_customdata(guarded_page)
    assert before_highlight == [6]

    guarded_page.reload()
    guarded_page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")

    chips = guarded_page.locator("#chips .chip")
    expect(chips).to_have_count(2)
    assert "Kris Venn" in chips.nth(0).inner_text()
    assert "Sam Delgado" in chips.nth(1).inner_text()
    assert guarded_page.get_attribute("#compare-toggle", "aria-pressed") == "true"
    assert guarded_page.get_attribute("#together-toggle", "aria-pressed") == "true"
    assert _highlight_customdata(guarded_page) == before_highlight


def test_removing_a_person_below_two_turns_called_together_off(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """WR-12: "Called together" needs 2+ people. Dropping to one person turns
    it off (the toggle is disabled then, so it could never be switched off),
    drops `mode=together` from the URL, and a person added afterwards is
    OR'ed in rather than silently AND'ed."""
    open_app(guarded_page, "")
    _add_person_by_query(guarded_page, "Kris Venn")
    _add_person_by_query(guarded_page, "Sam Delgado")
    guarded_page.click("#together-toggle")
    guarded_page.wait_for_function("location.search.includes('mode=together')")

    guarded_page.click('button[aria-label="Remove Sam Delgado"]')
    guarded_page.wait_for_function("location.search === '?people=kris-venn'")
    assert guarded_page.get_attribute("#together-toggle", "aria-pressed") == "false"
    assert guarded_page.is_disabled("#together-toggle")

    _add_person_by_query(guarded_page, "Sam Delgado")
    guarded_page.wait_for_function("location.search === '?people=kris-venn,sam-delgado'")
    assert _highlight_customdata(guarded_page) == [1, 2, 6, 9, 10]


def test_single_person_together_link_decodes_with_together_off(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """WR-12: a shared link with one person and `mode=together` opens with
    the toggle off, and the URL canonicalizes the stale mode away."""
    open_app(guarded_page, "?people=dale-harlow&mode=together")
    assert guarded_page.evaluate("window.__testHooks.getState().together") is False
    assert guarded_page.get_attribute("#together-toggle", "aria-pressed") == "false"
    guarded_page.wait_for_function("location.search === '?people=dale-harlow'")


def test_remove_chip_and_clear_selection_reset_state(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Removing a chip clears the highlight/summary; Clear selection resets
    everything and the URL back to no query."""
    open_app(guarded_page, "")
    _add_person_by_query(guarded_page, "Dale Harlow")

    guarded_page.click('button[aria-label="Remove Dale Harlow"]')
    guarded_page.wait_for_function("location.search === ''")
    assert _highlight_customdata(guarded_page) == []
    assert guarded_page.inner_text("#summary-count") == ""

    _add_person_by_query(guarded_page, "Dale Harlow")
    guarded_page.click("#clear-selection")
    guarded_page.wait_for_function("location.search === ''")

    chips = guarded_page.locator("#chips .chip")
    expect(chips).to_have_count(0)
    assert guarded_page.get_attribute("#compare-toggle", "aria-pressed") == "false"
    assert guarded_page.get_attribute("#together-toggle", "aria-pressed") == "false"


def test_summary_never_reads_like_a_ranking(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """A1: the summary text never contains a computed viewer statistic,
    across a no-selection, single-person, and compare+together state."""
    forbidden = ("average", "median", "avg")

    def _assert_clean() -> None:
        count_text = guarded_page.inner_text("#summary-count")
        detail_text = guarded_page.inner_text("#summary-detail")
        text = f"{count_text} {detail_text}".lower()
        for word in forbidden:
            assert word not in text

    open_app(guarded_page, "")
    _assert_clean()

    _add_person_by_query(guarded_page, "Dale Harlow")
    _assert_clean()

    _add_person_by_query(guarded_page, "Taylor Vance")
    _assert_clean()

    guarded_page.click("#compare-toggle")
    guarded_page.wait_for_function("location.search.includes('mode=')")
    _assert_clean()

    guarded_page.click("#together-toggle")
    guarded_page.wait_for_function("location.search.includes('together')")
    _assert_clean()


_OPTION_STYLE_JS = """
(el) => {
  const cs = getComputedStyle(el);
  return {
    outlineStyle: cs.outlineStyle,
    outlineWidth: cs.outlineWidth,
    paddingLeft: cs.paddingLeft,
    cursor: cs.cursor,
  };
}
"""


@pytest.mark.parametrize(
    ("input_id", "results_id", "query"),
    [("#person-search", "#person-results", "Dale Harlow"), ("#team-search", "#team-results", "o")],
)
def test_arrow_key_active_option_is_visibly_outlined(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    input_id: str,
    results_id: str,
    query: str,
) -> None:
    """WR-07 (WCAG 2.4.7): the bare `<li role="option">` results get padding
    and a pointer, and the arrow-key active option (`aria-selected="true"`)
    shows a visible outline; the other options don't."""
    open_app(guarded_page, "")
    guarded_page.fill(input_id, query)
    options = guarded_page.locator(f"{results_id} li[role='option']:not([aria-disabled])")
    expect(options.nth(1)).to_be_visible()

    guarded_page.press(input_id, "ArrowDown")
    expect(options.nth(0)).to_have_attribute("aria-selected", "true")

    active = options.nth(0).evaluate(_OPTION_STYLE_JS)
    inactive = options.nth(1).evaluate(_OPTION_STYLE_JS)
    assert active["outlineStyle"] == "solid"
    assert active["outlineWidth"] == "2px"
    assert inactive["outlineStyle"] == "none"
    assert inactive["paddingLeft"] == "16px"
    assert inactive["cursor"] == "pointer"
