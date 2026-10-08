"""Layout/geometry and contrast browser tests for D-21 (Announcers popover,
selection bar) and D-25 (visual fixes: readable Clear selection, distinct
Clear all filters, side gutters, no empty band) -- proven against the
fixture build served by `guarded_page`/`mobile_page`/`open_app`, per
`tests/fixtures/contract/site-data.fixture.json`'s 12 dots and 10 people.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from playwright.sync_api import Page, expect

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


def _add_person_by_query(page: Page, query: str, index: int = 0) -> None:
    """Opens the Announcers popover (D-21) if it isn't already open, types
    `query` into the person search, waits for `#person-results` to reflect
    it (D-28's synchronous filter, no debounce), and clicks the unchecked
    option at `index`."""
    if not page.locator("#pop-announcers").evaluate("(el) => el.matches(':popover-open')"):
        page.click("#trigger-announcers")
        page.wait_for_function("document.getElementById('pop-announcers').matches(':popover-open')")
        page.wait_for_function(
            "document.getElementById('trigger-announcers').getAttribute('aria-expanded') === 'true'"
        )
    page.fill("#person-search", query)
    trimmed = query.strip()
    page.wait_for_function(
        "(q) => document.getElementById('person-results').dataset.query === q", arg=trimmed
    )
    option = page.locator("#person-results li[role='option'][aria-selected='false']").nth(index)
    expect(option).to_be_visible()
    option.click()


def _add_person_via_sheet(page: Page, query: str, index: int = 0) -> None:
    """The phone equivalent of `_add_person_by_query`: opens the Filters
    bottom sheet (if it isn't already open) instead of the desktop popover,
    since the Announcers picker lives inside it there (D-21)."""
    if not page.locator("#filters-sheet").evaluate("(el) => el.matches(':popover-open')"):
        page.click("#filters-button")
        page.wait_for_function("document.getElementById('filters-sheet').matches(':popover-open')")
    page.fill("#person-search", query)
    trimmed = query.strip()
    page.wait_for_function(
        "(q) => document.getElementById('person-results').dataset.query === q", arg=trimmed
    )
    option = page.locator("#person-results li[role='option'][aria-selected='false']").nth(index)
    expect(option).to_be_visible()
    option.click()


def _assert_no_horizontal_overflow(page: Page) -> None:
    """Every chip and end-of-row control stays within a >=16px gutter on
    both edges, and #selection-bar's own content never exceeds its own box
    (D-21: "chips never run off the right edge").

    Reads true CSS-pixel geometry via `getBoundingClientRect` inside one
    `page.evaluate` call rather than Playwright's own screenshot-derived
    `Locator.bounding_box()`: `tests/fixtures/contract/site-data.fixture.json`
    people can have enough matched games that `#games-table`'s Source column
    (two links per row, no `table-layout: fixed`) overflows its own
    container on a narrow phone -- a pre-existing defect outside this
    plan's `#selection-bar`/D-21 scope (`deferred-items.md`). When that
    happens, mobile Chromium's zoom-to-fit response distorts
    `bounding_box()`'s reported coordinates for *every* element on the
    page, not just the overflowing table, which would otherwise fail this
    row's own, unrelated geometry. `getBoundingClientRect` reports the true
    CSS-pixel layout regardless of that rendering-time scaling."""
    info = page.evaluate(
        "() => { const iw = window.innerWidth; "
        "const els = document.querySelectorAll("
        "'#chips .chip, #compare-toggle, #together-toggle, #clear-selection'); "
        "const sb = document.getElementById('selection-bar'); "
        "return { iw, sbScrollWidth: sb.scrollWidth, sbClientWidth: sb.clientWidth, "
        "boxes: Array.from(els).map((el) => { const r = el.getBoundingClientRect(); "
        "return { x: r.x, right: r.right }; }) }; }"
    )
    assert len(info["boxes"]) > 0
    inner_width = info["iw"]
    for i, box in enumerate(info["boxes"]):
        assert box["x"] >= 16 - 0.5, f"control {i} sits left of the 16px gutter: {box}"
        assert box["right"] <= inner_width - 16 + 0.5, (
            f"control {i} overflows the right gutter: {box}, innerWidth={inner_width}"
        )

    assert info["sbScrollWidth"] <= info["sbClientWidth"] + 1, (
        "#selection-bar's own content overflows its own box"
    )


def test_announcers_trigger_opens_a_searchable_popover(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-21: the Announcers toolbar button opens a searchable popover with
    name-variant search; Escape closes it and returns focus to the trigger."""
    open_app(guarded_page, "")
    guarded_page.click("#trigger-announcers")
    guarded_page.wait_for_function(
        "document.getElementById('pop-announcers').matches(':popover-open')"
    )
    # The native `toggle` event (which filters.js's bindPopoverMechanics uses
    # to move focus) fires asynchronously relative to `:popover-open`
    # becoming true (an established race elsewhere in this suite), so wait
    # for the focus move itself rather than racing it.
    guarded_page.wait_for_function("document.activeElement.id === 'person-search'")

    guarded_page.fill("#person-search", "kristopher")
    options = guarded_page.locator("#person-results li[role='option']:not([aria-disabled])")
    expect(options).to_have_count(1)
    assert "Kris Venn" in options.first.inner_text()
    assert "as" in options.first.inner_text().lower()

    guarded_page.keyboard.press("Escape")
    guarded_page.wait_for_function(
        "!document.getElementById('pop-announcers').matches(':popover-open')"
    )
    assert guarded_page.evaluate("() => document.activeElement.id") == "trigger-announcers"


def test_announcers_popover_is_tall_and_list_fills_it(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-28: the desktop popover is about 60vh tall, and #person-results
    fills it via its own scroll -- not the ~1-row absolute-positioned clip
    in 04.1-gap2-announcers-screenshot.png."""
    guarded_page.set_viewport_size({"width": 1280, "height": 800})
    open_app(guarded_page, "")
    guarded_page.click("#trigger-announcers")
    guarded_page.wait_for_function(
        "document.getElementById('pop-announcers').matches(':popover-open')"
    )

    info = guarded_page.evaluate(
        "() => { const pop = document.getElementById('pop-announcers'); "
        "const results = document.getElementById('person-results'); "
        "const popRect = pop.getBoundingClientRect(); "
        "const resultsRect = results.getBoundingClientRect(); "
        "const style = getComputedStyle(results); "
        "return { innerHeight: window.innerHeight, popHeight: popRect.height, "
        "popBottom: popRect.bottom, resultsHeight: results.clientHeight, "
        "resultsBottom: resultsRect.bottom, resultsPosition: style.position, "
        "resultsOverflowY: style.overflowY }; }"
    )
    assert info["popHeight"] >= 0.55 * info["innerHeight"]
    assert abs(info["popBottom"] - info["resultsBottom"]) <= 24
    assert info["resultsHeight"] >= 0.5 * info["popHeight"]
    assert info["resultsPosition"] != "absolute"
    assert info["resultsOverflowY"] in ("auto", "scroll")


def test_phone_sheet_announcer_list_matches_desktop(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-28: the phone Filters sheet's Announcers section shows the same
    full alphabetical list with the search empty, every row is at least
    44px tall, and picking a name still clears the search."""
    open_app(mobile_page, "")
    mobile_page.click("#filters-button")
    mobile_page.wait_for_function(
        "document.getElementById('filters-sheet').matches(':popover-open')"
    )

    options = mobile_page.locator("#person-results li[role='option']:not([aria-disabled])")
    # 11 people in the fixture: 10 on rated games + morgan-ash, who is only on unrated game 13
    expect(options).to_have_count(11)

    heights = mobile_page.evaluate(
        "() => Array.from(document.querySelectorAll("
        "'#person-results li[role=\"option\"]')).map((el) => el.getBoundingClientRect().height)"
    )
    assert len(heights) == 11  # same 11 options as above
    for h in heights:
        assert h >= 44 - 0.5

    mobile_page.fill("#person-search", "Dale")
    mobile_page.wait_for_function(
        "document.getElementById('person-results').dataset.query === 'Dale'"
    )
    option = mobile_page.locator("#person-results li[role='option'][aria-selected='false']").first
    expect(option).to_be_visible()
    option.click()
    mobile_page.wait_for_function("location.search === '?people=dale-harlow'")
    assert mobile_page.input_value("#person-search") == ""


def test_no_topbar_search_remains(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-21: the top-right search box is gone -- the top bar holds only the
    site title now."""
    open_app(guarded_page, "")
    assert guarded_page.locator("#topbar #person-search").count() == 0
    assert guarded_page.locator("#topbar input").count() == 0


@pytest.mark.parametrize(("width", "height"), [(1280, 800), (800, 900)])
def test_chip_row_sits_between_toolbar_and_chart_and_wraps_without_overflow(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    width: int,
    height: int,
) -> None:
    """D-21: the chip row (with Compare/Called together/Clear selection at
    its end) sits between the toolbar and the chart, wraps, and never runs
    off the right edge at desktop/tablet widths."""
    guarded_page.set_viewport_size({"width": width, "height": height})
    open_app(guarded_page, "")

    for query in ["Dale Harlow", "Dale Harlow Jr.", "Kris Venn", "Jax Venn"]:
        _add_person_by_query(guarded_page, query)

    selection_row = guarded_page.locator("#selection-row")
    expect(selection_row).to_be_visible()

    toolbar_box = guarded_page.locator("#toolbar").bounding_box()
    selection_row_box = selection_row.bounding_box()
    selection_bar_box = guarded_page.locator("#selection-bar").bounding_box()
    chart_area_box = guarded_page.locator("#chart-area").bounding_box()
    assert toolbar_box is not None
    assert selection_row_box is not None
    assert selection_bar_box is not None
    assert chart_area_box is not None
    assert toolbar_box["y"] + toolbar_box["height"] <= selection_row_box["y"] + 0.5
    assert selection_bar_box["y"] + selection_bar_box["height"] <= chart_area_box["y"] + 0.5

    _assert_no_horizontal_overflow(guarded_page)


def test_chip_row_wraps_without_overflow_on_phone(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Same D-21 non-overflow guarantee at the phone breakpoint (390x844),
    adding people through the Filters bottom sheet (D-21: phones keep the
    Announcers picker inside it)."""
    open_app(mobile_page, "")

    for query in ["Dale Harlow", "Dale Harlow Jr.", "Kris Venn", "Jax Venn"]:
        _add_person_via_sheet(mobile_page, query)

    mobile_page.click("#filters-show-results")
    mobile_page.wait_for_function(
        "!document.getElementById('filters-sheet').matches(':popover-open')"
    )

    expect(mobile_page.locator("#selection-row")).to_be_visible()
    _assert_no_horizontal_overflow(mobile_page)


def test_trigger_counts_selected_announcers(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-21/D-02: the Announcers trigger reads its own selection count,
    like every other filter trigger."""
    open_app(guarded_page, "")
    trigger = guarded_page.locator("#trigger-announcers")
    expect(trigger).to_have_text("Announcers")
    assert trigger.get_attribute("data-active") == "false"

    _add_person_by_query(guarded_page, "Dale Harlow")
    _add_person_by_query(guarded_page, "Kris Venn")

    expect(trigger).to_have_text("Announcers · 2")
    assert trigger.get_attribute("data-active") == "true"


def test_summary_is_one_line_under_the_chip_row(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-21: below the beside-the-box breakpoint (04.15 D-02; see
    test_site_selection_band.BESIDE_MIN_WIDTH) the summary line sits on one line
    under the chip row and never wraps into a narrow column."""
    guarded_page.set_viewport_size({"width": 800, "height": 800})
    open_app(guarded_page, "")
    for query in ["Dale Harlow", "Kris Venn", "Sam Delgado"]:
        _add_person_by_query(guarded_page, query)

    selection_row_box = guarded_page.locator("#selection-row").bounding_box()
    summary_box = guarded_page.locator("#summary").bounding_box()
    count_box = guarded_page.locator("#summary-count").bounding_box()
    detail_box = guarded_page.locator("#summary-detail").bounding_box()
    assert selection_row_box is not None
    assert summary_box is not None
    assert count_box is not None
    assert detail_box is not None

    assert summary_box["y"] >= selection_row_box["y"] + selection_row_box["height"] - 0.5

    count_center = count_box["y"] + count_box["height"] / 2
    detail_center = detail_box["y"] + detail_box["height"] / 2
    assert abs(count_center - detail_center) <= 12

    inner_width = guarded_page.evaluate("() => window.innerWidth")
    assert summary_box["width"] >= 0.5 * inner_width


def test_selection_row_hidden_with_no_people(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """With nothing selected, #selection-row is hidden but #summary still
    shows the unfiltered count."""
    open_app(guarded_page, "")
    expect(guarded_page.locator("#selection-row")).to_be_hidden()
    expect(guarded_page.locator("#summary")).to_be_visible()


def test_phone_announcers_picker_is_in_the_filters_sheet(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-21: on phones the Announcers picker is the first section of the
    Filters bottom sheet, and a picked person still shows in the chip row
    above the chart once the sheet closes."""
    open_app(mobile_page, "")

    mobile_page.click("#filters-button")
    mobile_page.wait_for_function(
        "document.getElementById('filters-sheet').matches(':popover-open')"
    )
    first_section_id = mobile_page.evaluate(
        "() => document.querySelector('.sheet-body').firstElementChild.id"
    )
    assert first_section_id == "filter-announcers"

    mobile_page.fill("#person-search", "Dale Harlow")
    option = mobile_page.locator("#person-results li[role='option']:not([aria-disabled])").first
    expect(option).to_be_visible()
    option.click()
    expect(mobile_page.locator("#chips .chip")).to_have_count(1)

    mobile_page.click("#filters-show-results")
    mobile_page.wait_for_function(
        "!document.getElementById('filters-sheet').matches(':popover-open')"
    )

    selection_row_box = mobile_page.locator("#selection-row").bounding_box()
    chart_area_box = mobile_page.locator("#chart-area").bounding_box()
    assert selection_row_box is not None
    assert chart_area_box is not None
    expect(mobile_page.locator("#selection-row")).to_be_visible()
    assert selection_row_box["y"] + selection_row_box["height"] <= chart_area_box["y"] + 0.5


def test_clear_selection_is_readable_in_light_and_dark(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-25a: Clear selection is readable (WCAG AA) against its own
    background in both themes, and the dark background is never the UA's
    default white button face."""
    for scheme in ("light", "dark"):
        guarded_page.emulate_media(color_scheme=scheme)
        open_app(guarded_page, "")
        _add_person_by_query(guarded_page, "Dale Harlow")

        colors = guarded_page.eval_on_selector(
            "#clear-selection",
            "el => { const s = getComputedStyle(el); return [s.color, s.backgroundColor]; }",
        )
        fg = _parse_rgb(colors[0])
        bg = _parse_rgb(colors[1])
        assert _contrast_ratio(fg, bg) >= 4.5, scheme
        if scheme == "dark":
            assert colors[1] != "rgb(255, 255, 255)"


def test_clear_all_filters_is_distinct_and_aa_in_both_themes(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-25b: Clear all filters clears WCAG AA against the toolbar background
    in both themes, and its color/border differ from a plain filter
    trigger's in both themes too."""
    for scheme in ("light", "dark"):
        guarded_page.emulate_media(color_scheme=scheme)
        open_app(guarded_page, "")

        styles = guarded_page.evaluate(
            "() => { const toolbarBg = getComputedStyle(document.getElementById('toolbar'))"
            ".backgroundColor; "
            "const clear = getComputedStyle(document.getElementById('clear-filters')); "
            "const trig = getComputedStyle(document.getElementById('trigger-seasons')); "
            "return { toolbarBg, clearColor: clear.color, clearBorderTop: clear.borderTopColor, "
            "trigColor: trig.color, trigBorderTop: trig.borderTopColor }; }"
        )
        fg = _parse_rgb(styles["clearColor"])
        bg = _parse_rgb(styles["toolbarBg"])
        assert _contrast_ratio(fg, bg) >= 4.5, scheme
        assert styles["clearColor"] != styles["trigColor"], scheme
        assert styles["clearBorderTop"] != styles["trigBorderTop"], scheme


def test_clear_selection_is_distinct_and_aa(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-30: Clear selection reads as its own kind of control -- a dashed
    secondary treatment, not the toggle's border style and not
    Clear all filters' `--reset` red -- and clears WCAG AA in both themes."""
    for scheme in ("light", "dark"):
        guarded_page.emulate_media(color_scheme=scheme)
        open_app(guarded_page, "")
        _add_person_by_query(guarded_page, "Dale Harlow")

        styles = guarded_page.evaluate(
            "() => { "
            "const cs = getComputedStyle(document.getElementById('clear-selection')); "
            "const ct = getComputedStyle(document.getElementById('compare-toggle')); "
            "const cf = getComputedStyle(document.getElementById('clear-filters')); "
            "const bodyBg = getComputedStyle(document.body).backgroundColor; "
            "return { csBorderStyle: cs.borderTopStyle, csColor: cs.color, "
            "csBorderColor: cs.borderTopColor, csBg: cs.backgroundColor, "
            "ctBorderStyle: ct.borderTopStyle, cfColor: cf.color, "
            "cfBorderColor: cf.borderTopColor, bodyBg }; }"
        )
        assert styles["csBorderStyle"] != styles["ctBorderStyle"], scheme
        assert styles["csColor"] != styles["cfColor"], scheme
        assert styles["csBorderColor"] != styles["cfBorderColor"], scheme

        fg = _parse_rgb(styles["csColor"])
        bg = _parse_rgb(styles["csBg"])
        assert _contrast_ratio(fg, bg) >= 4.5, scheme

        border = _parse_rgb(styles["csBorderColor"])
        effective_bg = _parse_rgb(styles["bodyBg"])
        assert _contrast_ratio(border, effective_bg) >= 3, scheme

        has_toggle_class = guarded_page.eval_on_selector(
            "#clear-selection", "el => el.classList.contains('toggle')"
        )
        assert has_toggle_class is False, scheme


@pytest.mark.parametrize(("width", "height"), [(1280, 800), (390, 844)])
def test_page_has_side_gutters(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    width: int,
    height: int,
) -> None:
    """D-25c: content never sits flush with the viewport edge -- every named
    element has at least a 16px left gutter, and at 1280px the chart itself
    respects the right gutter too (panel closed)."""
    guarded_page.set_viewport_size({"width": width, "height": height})
    open_app(guarded_page, "")

    for selector in (
        "#chart-tabs",
        "#legend-chips",
        "#axis-toggle",
        "#chart",
        "#era-note",
        "#summary",
        "#matched-games h2",
    ):
        box = guarded_page.locator(selector).bounding_box()
        assert box is not None, selector
        assert box["x"] >= 16 - 0.5, f"{selector} sits left of the 16px gutter: {box}"

    if width == 1280:
        inner_width = guarded_page.evaluate("() => window.innerWidth")
        chart_box = guarded_page.locator("#chart").bounding_box()
        assert chart_box is not None
        assert chart_box["x"] + chart_box["width"] <= inner_width - 16 + 0.5


def test_no_empty_band_between_toolbar_and_chart(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-25d/D-08: Phase 04.4 D-10 fills the chart-tab slot (40px), and the gap
    between the toolbar and the legend row is no more than the selection bar,
    the tabs, the hint row, and a small gutter -- not the old empty band."""
    guarded_page.set_viewport_size({"width": 1280, "height": 800})
    open_app(guarded_page, "")

    chart_tabs_box = guarded_page.locator("#chart-tabs").bounding_box()
    assert chart_tabs_box is not None
    assert chart_tabs_box["height"] == 40
    tab_hint_box = guarded_page.locator("#tab-hint").bounding_box()
    assert tab_hint_box is not None

    toolbar_box = guarded_page.locator("#toolbar").bounding_box()
    legend_box = guarded_page.locator("#legend-chips").bounding_box()
    selection_bar_box = guarded_page.locator("#selection-bar").bounding_box()
    assert toolbar_box is not None
    assert legend_box is not None
    assert selection_bar_box is not None

    gap = legend_box["y"] - (toolbar_box["y"] + toolbar_box["height"])
    assert gap <= (
        selection_bar_box["height"] + chart_tabs_box["height"] + tab_hint_box["height"] + 16
    )


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide"], indirect=True)
@pytest.mark.parametrize("width", [360, 641, 700, 800, 1024])
def test_games_table_never_scrolls_the_page(
    guarded_page: Page, open_app: Callable[[Page, str], None], width: int
) -> None:
    """SITE-20: a table too wide for its text scrolls inside `#matched-games` at every
    width, never the page. Wider fonts pushed it past 641px (deferred in 04.17-02)."""
    page = guarded_page
    page.set_viewport_size({"width": width, "height": 900})
    open_app(page, "?school=northfield,lakeview")
    expect(page.locator("#games-table")).to_be_visible()
    sizes = page.evaluate(
        """() => ({
            page: document.documentElement.scrollWidth,
            view: document.documentElement.clientWidth,
            box: document.getElementById('matched-games').getBoundingClientRect().right,
        })"""
    )
    page_width = sizes["page"]
    view_width = sizes["view"]
    box_right = sizes["box"]
    assert page_width <= view_width
    assert box_right <= view_width + 0.5
