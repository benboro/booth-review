"""Top-bar browser tests (SITE-02, SITE-08, SITE-10, SITE-12; D-07, D-08, A1)
-- proven against the fixture build served by `guarded_page`/`open_app`, per
`tests/fixtures/contract/site-data.fixture.json`'s 12 dots and 10 people.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from playwright.sync_api import Locator, Page, expect

pytestmark = pytest.mark.e2e


def _parse_rgb(css_color: str) -> tuple[float, float, float]:
    """Parses a `getComputedStyle` `rgb(...)`/`rgba(...)` string into (r, g, b)."""
    nums = re.findall(r"[\d.]+", css_color)
    return float(nums[0]), float(nums[1]), float(nums[2])


def _relative_luminance(rgb: tuple[float, float, float]) -> float:
    def channel(c: float) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast_ratio(fg: tuple[float, float, float], bg: tuple[float, float, float]) -> float:
    """WCAG relative-luminance contrast ratio between two `rgb()` colors."""
    l1 = _relative_luminance(fg) + 0.05
    l2 = _relative_luminance(bg) + 0.05
    return max(l1, l2) / min(l1, l2)


_HIGHLIGHT_CUSTOMDATA_JS = "() => document.getElementById('chart').data.at(-1).customdata"


def _highlight_customdata(page: Page) -> list[int]:
    result: list[int] = page.evaluate(_HIGHLIGHT_CUSTOMDATA_JS)
    return result


def _options(page: Page) -> Locator:
    return page.locator("#person-results li[role='option']:not([aria-disabled])")


def _open_announcers(page: Page) -> None:
    """Opens the Announcers popover (D-21) if it isn't already open, the
    same wait pattern `test_site_filters.py`'s `_open_filter` uses."""
    if page.locator("#pop-announcers").evaluate("(el) => el.matches(':popover-open')"):
        return
    page.click("#trigger-announcers")
    page.wait_for_function("document.getElementById('pop-announcers').matches(':popover-open')")
    page.wait_for_function(
        "document.getElementById('trigger-announcers').getAttribute('aria-expanded') === 'true'"
    )


def _search(page: Page, query: str) -> None:
    _open_announcers(page)
    page.fill("#person-search", query)


def _add_person_by_query(page: Page, query: str, index: int = 0) -> None:
    """Opens the Announcers popover, types `query`, waits for
    `#person-results` to reflect it (D-28's synchronous filter, no
    debounce), and clicks the unchecked option at `index`."""
    _search(page, query)
    trimmed = query.strip()
    page.wait_for_function(
        "(q) => document.getElementById('person-results').dataset.query === q", arg=trimmed
    )
    option = page.locator("#person-results li[role='option'][aria-selected='false']").nth(index)
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


def test_announcer_list_shows_everyone_when_search_is_empty(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-28: with the search empty, #person-results lists every announcer,
    alphabetically, all unchecked -- the Excel AutoFilter-style full list,
    not the old empty-until-typed combobox."""
    open_app(guarded_page, "")
    _open_announcers(guarded_page)
    options = _options(guarded_page)
    expect(options).to_have_count(10)
    names = guarded_page.locator("#person-results li[role='option'] .option-name").all_inner_texts()
    assert names == [
        "Casey Lund",
        "Dale Harlow",
        "Dale Harlow Jr.",
        "Jamie Oaks",
        "Jax Venn",
        "Kris Venn",
        "Pat Rowan",
        "Robin Teague",
        "Sam Delgado",
        "Taylor Vance",
    ]
    for i in range(10):
        expect(options.nth(i)).to_have_attribute("aria-selected", "false")


def test_announcer_list_checks_selected_people(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-28: with a person selected via the URL, the empty-search list still
    shows all 10 options, and exactly that person's option is checked."""
    open_app(guarded_page, "?people=kris-venn")
    _open_announcers(guarded_page)
    options = _options(guarded_page)
    expect(options).to_have_count(10)
    checked = guarded_page.locator("#person-results li[role='option'][aria-selected='true']")
    expect(checked).to_have_count(1)
    assert "Kris Venn" in checked.first.inner_text()


def test_announcer_list_filters_by_variant(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-28: typing a name variant filters #person-results to the matching
    option, and clearing the input restores the full alphabetical list."""
    open_app(guarded_page, "")
    _open_announcers(guarded_page)
    guarded_page.fill("#person-search", "kristopher")
    guarded_page.wait_for_function(
        "document.getElementById('person-results').dataset.query === 'kristopher'"
    )
    options = _options(guarded_page)
    expect(options).to_have_count(1)
    assert "Kris Venn" in options.first.inner_text()

    guarded_page.fill("#person-search", "")
    guarded_page.wait_for_function("document.getElementById('person-results').dataset.query === ''")
    expect(_options(guarded_page)).to_have_count(10)


def test_announcer_pick_clears_search_and_refocuses(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-28: picking a name (Enter, no arrow key, on a query with no active
    row) adds the best-ranked unchecked match, clears the search, and
    refocuses the input, so "Dale" -> Dale Harlow -> "Kris" -> Kris Venn
    leaves both selected, with the popover still open."""
    open_app(guarded_page, "")
    _open_announcers(guarded_page)
    guarded_page.fill("#person-search", "Dale")
    guarded_page.wait_for_function(
        "document.getElementById('person-results').dataset.query === 'Dale'"
    )
    guarded_page.press("#person-search", "Enter")
    guarded_page.wait_for_function("location.search === '?people=dale-harlow'")
    assert guarded_page.input_value("#person-search") == ""
    assert guarded_page.evaluate("() => document.activeElement.id") == "person-search"

    guarded_page.fill("#person-search", "Kris")
    guarded_page.wait_for_function(
        "document.getElementById('person-results').dataset.query === 'Kris'"
    )
    option = guarded_page.locator("#person-results li[role='option'][aria-selected='false']").first
    expect(option).to_be_visible()
    assert "Kris Venn" in option.inner_text()
    option.click()
    guarded_page.wait_for_function("location.search === '?people=dale-harlow,kris-venn'")

    chips = guarded_page.locator("#chips .chip")
    expect(chips).to_have_count(2)
    assert chips.nth(0).inner_text().startswith("Dale Harlow")
    assert not chips.nth(0).inner_text().startswith("Dale Harlow Jr.")
    assert chips.nth(1).inner_text().startswith("Kris Venn")
    assert guarded_page.locator("#pop-announcers").evaluate("(el) => el.matches(':popover-open')")


def test_announcer_uncheck_removes_person(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-28: clicking a checked option removes that person and leaves focus
    in the search input; arrowing to a checked option and pressing Enter
    removes it too."""
    open_app(guarded_page, "?people=dale-harlow,kris-venn")
    _open_announcers(guarded_page)

    dale_row = guarded_page.locator(
        "#person-results li[role='option'][data-person-id='dale-harlow']"
    )
    expect(dale_row).to_have_attribute("aria-selected", "true")
    dale_row.click()
    guarded_page.wait_for_function("location.search === '?people=kris-venn'")
    chips = guarded_page.locator("#chips .chip")
    expect(chips).to_have_count(1)
    assert chips.first.inner_text().startswith("Kris Venn")
    assert guarded_page.evaluate("() => document.activeElement.id") == "person-search"

    kris_row = guarded_page.locator("#person-results li[role='option'][data-person-id='kris-venn']")
    expect(kris_row).to_have_attribute("aria-selected", "true")
    # Alphabetical order: Casey(0) Dale Harlow(1) Dale Harlow Jr.(2)
    # Jamie Oaks(3) Jax Venn(4) Kris Venn(5) -- 6 ArrowDown presses from -1.
    for _ in range(6):
        guarded_page.press("#person-search", "ArrowDown")
    guarded_page.press("#person-search", "Enter")
    guarded_page.wait_for_function("location.search === ''")
    expect(guarded_page.locator("#chips .chip")).to_have_count(0)


def test_announcer_compare_cap_unchanged(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-28/D-07: the 4-person compare cap and #compare-note still hold
    through the new list -- a 5th unchecked pick in compare mode adds no
    one."""
    open_app(guarded_page, "")
    for query in ["Dale Harlow", "Dale Harlow Jr.", "Kris Venn", "Jax Venn"]:
        _add_person_by_query(guarded_page, query)

    guarded_page.click("#compare-toggle")
    guarded_page.wait_for_function("location.search.includes('mode=compare')")

    _open_announcers(guarded_page)
    fifth = guarded_page.locator("#person-results li[role='option'][data-person-id='pat-rowan']")
    expect(fifth).to_have_attribute("aria-selected", "false")
    fifth.click()

    chips = guarded_page.locator("#chips .chip")
    expect(chips).to_have_count(4)
    assert guarded_page.is_visible("#compare-note")
    assert "Compare mode holds up to 4 people." in guarded_page.inner_text("#compare-note")


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
    [("#person-search", "#person-results", "Dale Harlow")],
)
def test_arrow_key_active_option_is_visibly_outlined(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    input_id: str,
    results_id: str,
    query: str,
) -> None:
    """WR-07 (WCAG 2.4.7): the bare `<li role="option">` results get padding
    and a pointer, and the arrow-key active option (identified by the
    `is-active` class, D-28 -- `aria-selected` now means checked, not
    active) shows a visible outline; the other options don't."""
    open_app(guarded_page, "")
    _open_announcers(guarded_page)
    guarded_page.fill(input_id, query)
    guarded_page.wait_for_function(
        "(q) => document.getElementById('person-results').dataset.query === q", arg=query
    )
    options = guarded_page.locator(f"{results_id} li[role='option']:not([aria-disabled])")
    expect(options.nth(1)).to_be_visible()

    guarded_page.press(input_id, "ArrowDown")
    active_class = options.nth(0).get_attribute("class") or ""
    assert "is-active" in active_class
    inactive_class = options.nth(1).get_attribute("class") or ""
    assert "is-active" not in inactive_class
    active_descendant = guarded_page.get_attribute("#person-search", "aria-activedescendant")
    assert active_descendant == options.nth(0).get_attribute("id")

    active = options.nth(0).evaluate(_OPTION_STYLE_JS)
    inactive = options.nth(1).evaluate(_OPTION_STYLE_JS)
    assert active["outlineStyle"] == "solid"
    assert active["outlineWidth"] == "2px"
    assert inactive["outlineStyle"] == "none"
    assert inactive["paddingLeft"] == "16px"
    assert inactive["cursor"] == "pointer"


# ---------- D-30: unmistakable pressed toggles, no row-shift on Compare ----------


@pytest.mark.parametrize("color_scheme", ["light", "dark"])
def test_compare_toggle_pressed_state_is_unmistakable(
    guarded_page: Page, open_app: Callable[[Page, str], None], color_scheme: str
) -> None:
    """D-30: Compare people and Called together show an unmistakable
    pressed state -- a reserved `::before` check slot that's invisible until
    pressed, a filled accent background with inverse (AA-contrast) text, and
    that fill itself reads as distinct against the page background."""
    guarded_page.emulate_media(color_scheme=color_scheme)
    open_app(guarded_page, "")
    _add_person_by_query(guarded_page, "Kris Venn")
    _add_person_by_query(guarded_page, "Sam Delgado")

    body_bg = _parse_rgb(
        guarded_page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    )

    for toggle_id in ("#compare-toggle", "#together-toggle"):
        before_visibility = guarded_page.eval_on_selector(
            toggle_id, "el => getComputedStyle(el, '::before').visibility"
        )
        assert before_visibility == "hidden", toggle_id
        before_bg = guarded_page.eval_on_selector(
            toggle_id, "el => getComputedStyle(el).backgroundColor"
        )

        guarded_page.click(toggle_id)
        guarded_page.wait_for_function(
            "(sel) => document.querySelector(sel).getAttribute('aria-pressed') === 'true'",
            arg=toggle_id,
        )

        after_bg, after_color = guarded_page.eval_on_selector(
            toggle_id,
            "el => { const s = getComputedStyle(el); return [s.backgroundColor, s.color]; }",
        )
        assert after_bg != before_bg, toggle_id

        fg = _parse_rgb(after_color)
        bg = _parse_rgb(after_bg)
        assert _contrast_ratio(fg, bg) >= 4.5, toggle_id
        assert _contrast_ratio(bg, body_bg) >= 3, toggle_id

        after_visibility = guarded_page.eval_on_selector(
            toggle_id, "el => getComputedStyle(el, '::before').visibility"
        )
        assert after_visibility == "visible", toggle_id
        content = guarded_page.eval_on_selector(
            toggle_id, "el => getComputedStyle(el, '::before').content"
        )
        assert "✓" in content, toggle_id


def test_toggling_compare_does_not_shift_the_row(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-30: every person chip reserves its compare-shape icon slot
    (`.chip-glyph`, always present, fixed width) so toggling Compare moves
    no chip or toggle button, and Compare never gains/loses a glyph slot."""
    open_app(guarded_page, "")
    _add_person_by_query(guarded_page, "Kris Venn")
    _add_person_by_query(guarded_page, "Sam Delgado")
    _add_person_by_query(guarded_page, "Dale Harlow")

    rects_js = (
        "() => { "
        "const rect = (el) => { const r = el.getBoundingClientRect(); "
        "return { x: r.x, width: r.width }; }; "
        "return { "
        "chips: [...document.querySelectorAll('#chips .chip')].map(rect), "
        "compare: rect(document.getElementById('compare-toggle')), "
        "together: rect(document.getElementById('together-toggle')), "
        "clear: rect(document.getElementById('clear-selection')), "
        "}; }"
    )
    glyph_counts_js = (
        "() => [...document.querySelectorAll('#chips .chip')]"
        ".map((el) => el.querySelectorAll('.chip-glyph').length)"
    )

    glyphs_before = guarded_page.evaluate(glyph_counts_js)
    assert glyphs_before == [1, 1, 1]

    before = guarded_page.evaluate(rects_js)
    guarded_page.click("#compare-toggle")
    guarded_page.wait_for_function("location.search.includes('mode=compare')")
    after = guarded_page.evaluate(rects_js)

    glyphs_after = guarded_page.evaluate(glyph_counts_js)
    assert glyphs_after == [1, 1, 1]

    assert len(before["chips"]) == len(after["chips"]) == 3
    for b, a in zip(before["chips"], after["chips"], strict=True):
        assert abs(b["x"] - a["x"]) <= 0.5
        assert abs(b["width"] - a["width"]) <= 0.5
    for key in ("compare", "together", "clear"):
        assert abs(before[key]["x"] - after[key]["x"]) <= 0.5, key
        assert abs(before[key]["width"] - after[key]["width"]) <= 0.5, key


def test_summary_detail_lists_networks_most_telecasts_first(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """A6: the summary line lists the dominant network first, not alphabetically."""
    open_app(guarded_page, "?people=pat-rowan")
    assert "Conference Network, Beta Network" in guarded_page.inner_text("#summary-detail")
