"""Filter toolbar browser tests (SITE-20, SITE-21, SITE-22, SITE-24, SITE-27;
D-02, D-03, D-10, D-11, D-13, D-18) -- proven against the fixture build
served by `guarded_page`/`mobile_page`/`open_app`, per
`tests/fixtures/contract/site-data.fixture.json`'s 12 dots and 10 people.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

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


def _boxes_intersect(a: dict[str, float], b: dict[str, float]) -> bool:
    return (
        a["x"] < b["x"] + b["width"]
        and a["x"] + a["width"] > b["x"]
        and a["y"] < b["y"] + b["height"]
        and a["y"] + a["height"] > b["y"]
    )


def _view(page: Page) -> dict[str, Any]:
    result: dict[str, Any] = page.evaluate("() => window.__testHooks.getView()")
    return result


def _visible_count(page: Page) -> int:
    return int(_view(page)["visibleCount"])


def _highlighted(page: Page) -> list[int]:
    result: list[int] = _view(page)["highlighted"]
    return result


def _visible_customdata(page: Page) -> list[int]:
    """Every telecast index currently plotted in an *active* family trace
    (passes every fade filter, not highlighted) -- excludes the inert traces
    (D-14/D-15) and the highlight overlay."""
    js = """
    () => document.getElementById('chart').data
      .filter((t) => typeof t.meta === 'string' && t.meta.startsWith('family:'))
      .flatMap((t) => t.customdata)
    """
    result: list[int] = page.evaluate(js)
    return result


def _options(page: Page, results_id: str) -> Any:
    return page.locator(f"#{results_id} li[role='option']:not([aria-disabled])")


def _add_person_by_query(page: Page, query: str, index: int = 0) -> None:
    """Opens the Announcers popover (D-21), types `query` into the person
    search, waits for `#person-results` to reflect it (D-28's synchronous
    filter, no debounce), and clicks the unchecked option."""
    if not page.locator("#pop-announcers").evaluate("(el) => el.matches(':popover-open')"):
        _open_filter(page, "announcers")
    page.fill("#person-search", query)
    trimmed = query.strip()
    page.wait_for_function(
        "(q) => document.getElementById('person-results').dataset.query === q", arg=trimmed
    )
    option = page.locator("#person-results li[role='option'][aria-selected='false']").nth(index)
    expect(option).to_be_visible()
    option.click()


def _open_filter(page: Page, name: str) -> None:
    """Clicks `#trigger-{name}` and waits for its `#pop-{name}` popover to
    open (D-02). The native `toggle` event (which filters.js uses to set
    `aria-expanded` and move focus) fires asynchronously relative to
    `:popover-open` becoming true, so this also waits for `aria-expanded`
    before returning -- otherwise a caller reading it right after this
    returns can race the still-pending event."""
    page.click(f"#trigger-{name}")
    page.wait_for_function(f"document.getElementById('pop-{name}').matches(':popover-open')")
    page.wait_for_function(
        f"document.getElementById('trigger-{name}').getAttribute('aria-expanded') === 'true'"
    )


def test_season_counts_hidden_until_disclosure_opened(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """The per-season counts list is noisy by default, so it stays behind a
    collapsed `<details>` disclosure and is invisible until opened."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "seasons")
    assert guarded_page.locator("#season-counts-details").get_attribute("open") is None
    expect(guarded_page.locator("#season-counts")).to_be_hidden()
    assert guarded_page.inner_text("#season-counts") == ""

    guarded_page.click("#season-counts-details summary")
    expect(guarded_page.locator("#season-counts")).to_be_visible()


def test_default_season_counts(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    """Every season lists its rated-telecast count on first load, once the
    "Games per season" disclosure is opened."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "seasons")
    guarded_page.click("#season-counts-details summary")
    text = guarded_page.inner_text("#season-counts")
    assert "2019: 2 rated telecasts" in text
    assert "2021: 2 rated telecasts" in text
    assert "2025: 4 rated telecasts" in text
    assert "2026: 4 rated telecasts" in text


def test_season_range_hides_dots_and_leaves_counts_unchanged(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-13: the season range is the only filter that removes dots; it never
    changes the per-season counts list."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "seasons")
    guarded_page.select_option("#season-from", "2025")
    guarded_page.select_option("#season-to", "2026")
    guarded_page.wait_for_function("location.search.includes('seasons=2025-2026')")

    assert _visible_count(guarded_page) == 8
    guarded_page.click("#season-counts-details summary")
    text = guarded_page.inner_text("#season-counts")
    assert "2019: 2 rated telecasts" in text


@pytest.mark.parametrize(
    ("query", "expected_seasons", "selects", "visible"),
    [
        # Entirely past the last data season: falls back to unfiltered.
        ("?seasons=2030-2040", None, ("2019", "2026"), 12),
        # Ends inside gaps (no 2020/2022-2024 data): snaps onto 2021-2021.
        ("?seasons=2020-2022", [2021, 2021], ("2021", "2021"), 2),
        # Wholly inside a gap: no data season in range, unfiltered.
        ("?seasons=2022-2024", None, ("2019", "2026"), 12),
        # Reversed and starting before the data: swapped, then snapped.
        ("?seasons=2020-2000", [2019, 2019], ("2019", "2019"), 2),
    ],
)
def test_season_link_snaps_to_data_seasons_the_selects_can_show(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    query: str,
    expected_seasons: list[int] | None,
    selects: tuple[str, str],
    visible: int,
) -> None:
    """WR-13: a seasons link never decodes to an inverted range or to a
    season neither `<select>` offers (which blanked both selects and hid
    every dot); it snaps onto data seasons or falls back to unfiltered."""
    open_app(guarded_page, query)
    assert guarded_page.evaluate("window.__testHooks.getState().seasons") == expected_seasons
    assert guarded_page.input_value("#season-from") == selects[0]
    assert guarded_page.input_value("#season-to") == selects[1]
    assert _visible_count(guarded_page) == visible


def test_blank_season_select_value_is_ignored(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """WR-13: a change event while a select reads blank never becomes a
    season range of 0."""
    open_app(guarded_page, "?seasons=2021-2025")
    guarded_page.evaluate(
        "() => { const el = document.getElementById('season-from'); el.value = ''; "
        "el.dispatchEvent(new Event('change', {bubbles: true})); }"
    )
    assert guarded_page.evaluate("window.__testHooks.getState().seasons") == [2021, 2025]


def test_unchecking_fox_family_fades_its_dots_into_the_inert_trace(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-13: unchecking a family box fades its networks' dots (moves them to
    the inert trace) rather than removing them -- `visibleCount` (season-only
    removal) is unchanged; only the active/passing count drops."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "networks")
    guarded_page.uncheck("input[data-family-checkbox='fox']")
    guarded_page.wait_for_function("location.search.includes('networks=')")

    assert _visible_count(guarded_page) == 12
    active = _visible_customdata(guarded_page)
    assert len(active) == 9
    assert 1 not in active


def test_isolating_a_single_network_via_family_checkboxes(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Unchecking every other family leaves a single network ("ESPN2 only"-style) active."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "networks")
    guarded_page.uncheck("input[data-family-checkbox='disney']")
    guarded_page.uncheck("input[data-family-checkbox='conference']")
    guarded_page.uncheck("input[data-family-checkbox='other']")
    guarded_page.wait_for_function("location.search.includes('networks=net-b')")

    assert _visible_count(guarded_page) == 12
    assert sorted(_visible_customdata(guarded_page)) == [1, 5, 9]


def test_unchecking_one_network_leaves_family_indeterminate(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    """With a second Disney network in play, unchecking just that one
    network fades only its own dot and leaves the family box indeterminate."""
    mutated = json.loads(json.dumps(fixture_raw))
    mutated["lookups"]["networks"].append(
        {"id": "net-e", "name": "Gamma Sports", "family": "disney"}
    )
    new_idx = len(mutated["lookups"]["networks"]) - 1
    mutated["telecasts"]["network"][4] = new_idx
    mutated["telecasts"]["outlets"][4] = [new_idx]
    body = json.dumps(mutated)

    guarded_page.route(
        "**/site-data.json*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=body),
    )
    open_app(guarded_page, "")

    before = _visible_customdata(guarded_page)
    assert 4 in before

    _open_filter(guarded_page, "networks")
    guarded_page.uncheck("input[data-network-id='net-e']")
    guarded_page.wait_for_function("location.search.includes('networks=')")

    after = _visible_customdata(guarded_page)
    assert 4 not in after
    assert 0 in after
    assert 8 in after
    assert len(after) == len(before) - 1

    family_checkbox = guarded_page.locator("input[data-family-checkbox='disney']")
    assert family_checkbox.evaluate("(el) => el.indeterminate") is True


def test_prime_time_slot_fades_non_matching_including_unknown_kickoff(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-13: checking a slot fades non-matching dots, including the one with
    unknown kickoff, rather than removing them."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "kickoff")
    guarded_page.check("input[name='slot'][value='prime']")
    guarded_page.wait_for_function("location.search.includes('slot=prime')")

    assert _visible_count(guarded_page) == 12
    assert sorted(_visible_customdata(guarded_page)) == [5, 7, 9]


def test_after_dark_slot_passes_only_the_late_kickoff(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-20/D-26: the After dark checkbox writes slot=late and fades every
    dot except the one late-kickoff telecast (index 2, 22:30 ET). Its
    detail panel shows the After dark label."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "kickoff")
    guarded_page.check("input[name='slot'][value='late']")
    guarded_page.wait_for_function("location.search.includes('slot=late')")

    assert _visible_count(guarded_page) == 12
    assert sorted(_visible_customdata(guarded_page)) == [2]

    guarded_page.evaluate("window.__testHooks.openPanel(2)")
    assert "After dark (10 PM ET or later)" in guarded_page.inner_text("#panel-body")


def test_legacy_prime_link_still_decodes(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-20: an existing ?slot=prime link still decodes; the prime checkbox
    is checked, the new late checkbox is not, and the URL is left alone."""
    open_app(guarded_page, "?slot=prime")

    assert guarded_page.is_checked("input[name='slot'][value='prime']") is True
    assert guarded_page.is_checked("input[name='slot'][value='late']") is False
    assert guarded_page.evaluate("location.search") == "?slot=prime"


def test_prime_and_late_together_encode_canonically(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-20: checking late then prime encodes slot=prime,late (canonical
    SLOT_ORDER order) and the Kickoff trigger reads the count form; late
    alone reads its short label."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "kickoff")

    guarded_page.check("input[name='slot'][value='late']")
    guarded_page.wait_for_function("location.search.includes('slot=late')")
    assert guarded_page.inner_text("#trigger-kickoff") == "Kickoff: After dark"

    guarded_page.check("input[name='slot'][value='prime']")
    guarded_page.wait_for_function("location.search.includes('slot=prime,late')")
    assert guarded_page.inner_text("#trigger-kickoff") == "Kickoff · 2"


def test_role_filter_limits_taylor_vance_to_her_main_feed_role(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-13: Role never fades or removes a dot on its own -- it limits how a
    person matches."""
    open_app(guarded_page, "")
    _add_person_by_query(guarded_page, "Taylor Vance")

    _open_filter(guarded_page, "role")
    guarded_page.check("input[name='role'][value='pbp']")
    guarded_page.wait_for_function("location.search.includes('role=pbp')")
    assert _highlighted(guarded_page) == []
    assert "No games match the current filters for Taylor Vance." in guarded_page.inner_text(
        "#summary-detail"
    )

    guarded_page.check("input[name='role'][value='analyst']")
    guarded_page.wait_for_function("location.search.includes('role=analyst')")
    assert _highlighted(guarded_page) == [5]
    assert guarded_page.is_checked("input[name='role'][value='pbp']") is False


def test_role_filter_never_matches_sideline_crew(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """A sideline/unknown-role person never matches a PBP or analyst role filter."""
    open_app(guarded_page, "")
    _add_person_by_query(guarded_page, "Robin Teague")

    _open_filter(guarded_page, "role")
    guarded_page.check("input[name='role'][value='analyst']")
    guarded_page.wait_for_function("location.search.includes('role=analyst')")
    assert _highlighted(guarded_page) == []


def test_reload_restores_full_filter_state(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """SITE-12: seasons, networks, slot, role, and school all survive a reload."""
    open_app(guarded_page, "")

    _open_filter(guarded_page, "seasons")
    guarded_page.select_option("#season-from", "2021")
    guarded_page.select_option("#season-to", "2026")
    guarded_page.wait_for_function("location.search.includes('seasons=2021-2026')")

    _open_filter(guarded_page, "networks")
    guarded_page.uncheck("input[data-family-checkbox='other']")
    guarded_page.wait_for_function("location.search.includes('networks=')")

    _open_filter(guarded_page, "kickoff")
    guarded_page.check("input[name='slot'][value='prime']")
    guarded_page.wait_for_function("location.search.includes('slot=prime')")

    _open_filter(guarded_page, "role")
    guarded_page.check("input[name='role'][value='analyst']")
    guarded_page.wait_for_function("location.search.includes('role=analyst')")

    _open_filter(guarded_page, "school")
    guarded_page.check("#school-list input[value='northfield']")
    guarded_page.wait_for_function("location.search.includes('school=northfield')")

    url = guarded_page.evaluate("location.search")
    fragments = (
        "seasons=2021-2026",
        "networks=",
        "slot=prime",
        "role=analyst",
        "school=northfield",
    )
    for fragment in fragments:
        assert fragment in url

    before_visible = _visible_count(guarded_page)
    before_active = sorted(_visible_customdata(guarded_page))

    guarded_page.reload()
    guarded_page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")

    assert guarded_page.evaluate("() => document.getElementById('season-from').value") == "2021"
    assert guarded_page.evaluate("() => document.getElementById('season-to').value") == "2026"
    assert (
        guarded_page.evaluate(
            "() => document.querySelector(\"input[data-family-checkbox='other']\").checked"
        )
        is False
    )
    assert (
        guarded_page.evaluate(
            "() => document.querySelector(\"input[name='slot'][value='prime']\").checked"
        )
        is True
    )
    assert (
        guarded_page.evaluate(
            "() => document.querySelector(\"input[name='role'][value='analyst']\").checked"
        )
        is True
    )
    assert (
        guarded_page.evaluate(
            "() => document.querySelector(\"#school-list input[value='northfield']\").checked"
        )
        is True
    )
    assert "Northfield" in guarded_page.evaluate(
        "() => document.getElementById('school-chips').textContent"
    )

    assert _visible_count(guarded_page) == before_visible
    assert sorted(_visible_customdata(guarded_page)) == before_active


def test_clear_all_filters_resets_every_filter_and_the_url(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Clear all filters resets seasons/networks/slots/role/conferences/school/postseason
    back to `location.search === ''` when no person is selected."""
    open_app(guarded_page, "")

    _open_filter(guarded_page, "school")
    guarded_page.check("#school-list input[value='northfield']")
    guarded_page.wait_for_function("location.search.includes('school=northfield')")

    _open_filter(guarded_page, "postseason")
    guarded_page.click("[data-postseason='only']")
    guarded_page.wait_for_function("location.search.includes('postseason=only')")

    _open_filter(guarded_page, "kickoff")
    guarded_page.check("input[name='slot'][value='prime']")
    guarded_page.wait_for_function("location.search.includes('slot=prime')")

    guarded_page.click("#clear-filters")
    guarded_page.wait_for_function("location.search === ''")

    assert _visible_count(guarded_page) == 12
    view = _view(guarded_page)
    assert view["passingCount"] == 12
    assert view["hasSelection"] is False


def test_clear_all_filters_also_clears_people(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-27 (overrides the earlier "people are not cleared" proposal): Clear
    all filters removes every selected announcer, compare mode, and
    called-together, alongside the ordinary filter reset."""
    open_app(guarded_page, "")

    _add_person_by_query(guarded_page, "Dale Harlow")
    guarded_page.click("#compare-toggle")
    guarded_page.wait_for_function("location.search.includes('mode=compare')")

    _open_filter(guarded_page, "school")
    guarded_page.check("#school-list input[value='northfield']")
    guarded_page.wait_for_function("location.search.includes('school=northfield')")

    guarded_page.click("#clear-filters")
    guarded_page.wait_for_function("location.search === ''")

    state = guarded_page.evaluate("window.__testHooks.getState()")
    assert state["people"] == []
    assert state["school"] == []
    assert state["compare"] is False
    assert state["together"] is False
    expect(guarded_page.locator("#selection-row")).to_be_hidden()


def test_phone_filters_button_count_includes_selected_people(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-27: the phone `Filters(N)` badge counts selected announcers too,
    since the Announcers picker lives inside the same Filters sheet."""
    open_app(mobile_page, "?people=dale-harlow")
    expect(mobile_page.locator("#filters-button")).to_have_text("Filters (1)")


def test_toolbar_order_and_clear_all_contrast(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-02/SITE-27: "Clear all filters" is the first visible toolbar item,
    followed by the Announcers trigger and the seven filter triggers in
    order (D-21). D-25: its computed color against the *toolbar's own*
    background (its own background is transparent) clears WCAG AA's 4.5:1
    minimum, and its color/border-top-color differ from a plain filter
    trigger's -- a style distinct from the filter buttons, not the Phase 4
    low-contrast secondary tone."""
    open_app(guarded_page, "")

    ids = guarded_page.evaluate(
        "() => Array.from(document.querySelectorAll('#toolbar > *'))"
        ".filter((el) => getComputedStyle(el).display !== 'none').map((el) => el.id)"
    )
    assert ids == [
        "clear-filters",
        "trigger-announcers",
        "trigger-seasons",
        "trigger-networks",
        "trigger-kickoff",
        "trigger-role",
        "trigger-conference",
        "trigger-school",
        "trigger-postseason",
    ]

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
    assert _contrast_ratio(fg, bg) >= 4.5
    assert styles["clearColor"] != styles["trigColor"]
    assert styles["clearBorderTop"] != styles["trigBorderTop"]


def test_chrome_buttons_use_the_theme_text_color_in_dark_mode(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Buttons don't inherit `color`, so without an explicit rule the toolbar/
    sheet/panel controls fall back to the UA's button text color, unreadable
    against the dark theme's background. "Clear all filters" no longer
    belongs in this list (D-25 gives it its own distinct `--reset` color);
    Clear selection (D-25a) takes its place, checked with a person selected
    so it's visible."""
    guarded_page.emulate_media(color_scheme="dark")
    open_app(guarded_page, "")
    _add_person_by_query(guarded_page, "Dale Harlow")
    colors = guarded_page.evaluate(
        "() => { const body = getComputedStyle(document.body).color; "
        "return ['#filters-button', '#panel-close', '#trigger-seasons', '#clear-selection']"
        ".map(sel => [sel, getComputedStyle(document.querySelector(sel)).color, body]); }"
    )
    for selector, color, body_color in colors:
        assert color == body_color, selector


@pytest.mark.parametrize(
    ("query", "trigger_id", "expected_text"),
    [
        ("?seasons=2019-2025", "trigger-seasons", "Seasons 2019–2025"),  # noqa: RUF001
        ("?networks=net-a", "trigger-networks", "Networks · 1"),
        ("?conferences=SEC", "trigger-conference", "Conference: SEC"),
        ("?conferences=SEC,Big+Ten", "trigger-conference", "Conference · 2"),
        ("?school=northfield", "trigger-school", "School: Northfield"),
        ("?postseason=only", "trigger-postseason", "Bowls/Playoffs: Only"),
    ],
)
def test_active_trigger_shows_a_summary_and_is_marked_active(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    query: str,
    trigger_id: str,
    expected_text: str,
) -> None:
    """D-02: a filter button with an active value is highlighted and reads a
    short summary."""
    open_app(guarded_page, query)
    trigger = guarded_page.locator(f"#{trigger_id}")
    expect(trigger).to_have_text(expected_text)
    assert trigger.get_attribute("data-active") == "true"


def test_popover_opens_focuses_search_and_positions_below_trigger(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-02: opening a filter popover sets `aria-expanded`, moves focus into
    it, and positions it under its trigger button."""
    open_app(guarded_page, "")
    trigger = guarded_page.locator("#trigger-conference")
    _open_filter(guarded_page, "conference")

    assert trigger.get_attribute("aria-expanded") == "true"
    assert guarded_page.evaluate("() => document.activeElement.id") == "conference-search"

    trigger_box = trigger.bounding_box()
    popover_box = guarded_page.locator("#pop-conference").bounding_box()
    assert trigger_box is not None
    assert popover_box is not None
    assert popover_box["y"] >= trigger_box["y"] + trigger_box["height"] - 1


def test_popover_closes_on_escape_and_returns_focus(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-02: Esc closes an open popover and returns focus to its trigger."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "conference")

    guarded_page.keyboard.press("Escape")
    guarded_page.wait_for_function(
        "!document.getElementById('pop-conference').matches(':popover-open')"
    )
    guarded_page.wait_for_function(
        "document.getElementById('trigger-conference').getAttribute('aria-expanded') === 'false'"
    )
    assert guarded_page.evaluate("() => document.activeElement.id") == "trigger-conference"


def test_popover_closes_on_outside_click(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-02: clicking outside an open popover closes it (native light-dismiss)."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "conference")

    guarded_page.click("#era-note")
    guarded_page.wait_for_function(
        "!document.getElementById('pop-conference').matches(':popover-open')"
    )


def test_opening_the_modal_closes_the_popover_and_escape_returns_focus(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-03: opening the detail modal closes an open filter popover; Escape
    then closes the modal."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "conference")
    guarded_page.evaluate("() => window.__testHooks.openPanel(0)")
    guarded_page.wait_for_function(
        "!document.getElementById('pop-conference').matches(':popover-open')"
    )
    assert guarded_page.evaluate("document.getElementById('detail-panel').open") is True

    guarded_page.keyboard.press("Escape")
    guarded_page.wait_for_function("document.getElementById('detail-panel').open === false")


def test_conference_checklist_lists_only_fbs_conferences_present_plus_independents(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-10: the checklist holds only FBS conferences present in the data
    plus FBS Independents, alphabetical -- Missouri Valley (FCS) is excluded."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "conference")
    labels = guarded_page.eval_on_selector_all(
        "#conference-list label.check-row",
        "els => els.map((el) => el.textContent.trim())",
    )
    assert labels == ["Big Ten", "FBS Independents", "Mountain West", "Pac-12", "SEC"]


def test_conference_filter_matches_either_team_in_season_and_is_era_correct(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-10: a game matches when either team was in a selected conference
    that season -- Telecast 0 (Northfield, 2019, Pac-12) is not a Big Ten
    match (the USC case: conference membership is season-scoped)."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "conference")
    guarded_page.check("#conference-list input[value='Big Ten']")
    guarded_page.wait_for_function("location.search.includes('conferences=Big%20Ten')")

    active = sorted(_visible_customdata(guarded_page))
    assert active == [1, 4, 5, 8]
    assert 0 not in active

    guarded_page.fill("#conference-search", "pac")
    visible_rows = guarded_page.locator("#conference-list label.check-row:visible")
    expect(visible_rows).to_have_count(1)
    assert "Pac-12" in visible_rows.inner_text()


def test_school_filter_fades_without_highlighting(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-11: School fades non-matching games; it never highlights."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "school")
    guarded_page.check("#school-list input[value='northfield']")
    guarded_page.wait_for_function("location.search.includes('school=northfield')")

    assert sorted(_visible_customdata(guarded_page)) == [0, 4, 8]
    assert _highlighted(guarded_page) == []


def test_legacy_team_link_migrates_into_school_as_a_fade_filter(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """A legacy Phase 4 `?team=` link decodes straight into the School
    filter (a fade, not a highlight -- Pitfall 4)."""
    open_app(guarded_page, "?team=northfield")
    assert (
        guarded_page.evaluate(
            "() => document.querySelector(\"#school-list input[value='northfield']\").checked"
        )
        is True
    )
    expect(guarded_page.locator("#trigger-school")).to_have_text("School: Northfield")
    assert _highlighted(guarded_page) == []


def test_school_chip_remove_clears_the_filter(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _open_filter(guarded_page, "school")
    guarded_page.check("#school-list input[value='northfield']")
    guarded_page.wait_for_function("location.search.includes('school=northfield')")

    guarded_page.click("#school-chips button.chip-remove")
    guarded_page.wait_for_function("location.search === ''")
    assert (
        guarded_page.evaluate(
            "() => document.querySelector(\"#school-list input[value='northfield']\").checked"
        )
        is False
    )


def test_school_search_keyboard_arrowdown_focuses_first_row_and_space_checks_it(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """The searchable checklist's keyboard path: ArrowDown from the search
    input focuses the first visible checkbox, Space checks it natively."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "school")
    guarded_page.focus("#school-search")
    guarded_page.keyboard.press("ArrowDown")
    assert guarded_page.evaluate("() => document.activeElement.value") == "boulder-pass"

    guarded_page.keyboard.press("Space")
    guarded_page.wait_for_function("location.search.includes('school=boulder-pass')")
    assert (
        guarded_page.evaluate(
            "() => document.querySelector(\"#school-list input[value='boulder-pass']\").checked"
        )
        is True
    )


def test_postseason_only_isolates_bowl_and_playoff_games(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-18: "Only bowls & playoffs" leaves just the bowl/playoff dots active."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "postseason")
    guarded_page.click("[data-postseason='only']")
    guarded_page.wait_for_function("location.search.includes('postseason=only')")

    assert sorted(_visible_customdata(guarded_page)) == [5, 7]
    assert guarded_page.get_attribute("[data-postseason='only']", "aria-checked") == "true"


def test_postseason_exclude_fades_bowl_and_playoff_games(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-18: "Exclude bowls & playoffs" fades exactly the bowl/playoff dots."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "postseason")
    guarded_page.click("[data-postseason='exclude']")
    guarded_page.wait_for_function("location.search.includes('postseason=exclude')")

    active = sorted(_visible_customdata(guarded_page))
    assert 5 not in active
    assert 7 not in active
    assert len(active) == 10


def test_postseason_all_games_clears_the_url_param(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?postseason=only")
    _open_filter(guarded_page, "postseason")
    guarded_page.click("[data-postseason='all']")
    guarded_page.wait_for_function("!location.search.includes('postseason=')")
    assert sorted(_visible_customdata(guarded_page)) == list(range(12))


def test_postseason_keyboard_arrow_and_home_end_move_focus_and_selection(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """WR-05: `role="radiogroup"`/`role="radio"` on `#postseason-options`
    promises the WAI-ARIA APG radiogroup keyboard pattern -- roving tabindex
    (only the selected radio is Tab-reachable) plus ArrowRight/Home/End
    moving both focus and selection together."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "postseason")

    all_btn = "[data-postseason='all']"
    exclude_btn = "[data-postseason='exclude']"
    only_btn = "[data-postseason='only']"

    assert guarded_page.get_attribute(all_btn, "tabindex") == "0"
    assert guarded_page.get_attribute(exclude_btn, "tabindex") == "-1"
    assert guarded_page.get_attribute(only_btn, "tabindex") == "-1"

    guarded_page.focus(all_btn)
    guarded_page.keyboard.press("ArrowRight")
    guarded_page.wait_for_function("location.search.includes('postseason=exclude')")
    assert guarded_page.evaluate("() => document.activeElement.dataset.postseason") == "exclude"
    assert guarded_page.get_attribute(exclude_btn, "aria-checked") == "true"
    assert guarded_page.get_attribute(exclude_btn, "tabindex") == "0"
    assert guarded_page.get_attribute(all_btn, "tabindex") == "-1"

    guarded_page.keyboard.press("End")
    guarded_page.wait_for_function("location.search.includes('postseason=only')")
    assert guarded_page.evaluate("() => document.activeElement.dataset.postseason") == "only"
    assert guarded_page.get_attribute(only_btn, "aria-checked") == "true"
    assert guarded_page.get_attribute(only_btn, "tabindex") == "0"

    guarded_page.keyboard.press("Home")
    guarded_page.wait_for_function("!location.search.includes('postseason=')")
    assert guarded_page.evaluate("() => document.activeElement.dataset.postseason") == "all"
    assert guarded_page.get_attribute(all_btn, "aria-checked") == "true"
    assert guarded_page.get_attribute(all_btn, "tabindex") == "0"


def test_desktop_chart_never_overlaps_matched_games_table_on_page_scroll(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Regression (screenshot 2026-09-27): the chart must stay in normal
    flow (never sticky/fixed) so the table always sits below it after
    scrolling."""
    guarded_page.set_viewport_size({"width": 1280, "height": 700})
    open_app(guarded_page, "")

    guarded_page.locator("#matched-games").scroll_into_view_if_needed()

    chart_box = guarded_page.locator("#chart").bounding_box()
    table_box = guarded_page.locator("#matched-games").bounding_box()
    assert chart_box is not None
    assert table_box is not None
    assert not _boxes_intersect(chart_box, table_box), (
        "the chart's bounding box overlaps the matched-games table's after scrolling"
    )


def test_desktop_chart_never_overlaps_matched_games_table_on_page_scroll_at_800x900(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Same regression check at a second, narrower desktop/tablet viewport."""
    guarded_page.set_viewport_size({"width": 800, "height": 900})
    open_app(guarded_page, "")

    guarded_page.locator("#matched-games").scroll_into_view_if_needed()

    chart_box = guarded_page.locator("#chart").bounding_box()
    table_box = guarded_page.locator("#matched-games").bounding_box()
    assert chart_box is not None
    assert table_box is not None
    assert not _boxes_intersect(chart_box, table_box)


@pytest.mark.parametrize("width", [1280, 800, 390])
def test_toolbar_never_overlaps_matched_games_table(
    guarded_page: Page, open_app: Callable[[Page, str], None], width: int
) -> None:
    """The left-rail-over-table defect (SITE-20) cannot recur: the toolbar
    and the matched-games table never intersect at any width."""
    guarded_page.set_viewport_size({"width": width, "height": 900})
    open_app(guarded_page, "")

    toolbar_box = guarded_page.locator("#toolbar").bounding_box()
    table_box = guarded_page.locator("#games-table, #table-empty").first.bounding_box()
    assert toolbar_box is not None
    assert table_box is not None
    assert not _boxes_intersect(toolbar_box, table_box)


def test_network_family_group_has_no_leftover_ua_padding_on_desktop(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Root cause of "too much vertical spacing between network entries":
    `<fieldset>`'s and `<ul>`'s own UA-default padding/margin were never
    fully reset, adding ~44px of unstyled space around every family group on
    top of its actual content -- most families hold just 1-3 networks, so
    this read as oversized gaps between "network entries." Each single-
    network family group's total rendered height must stay compact."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "networks")

    family_groups = guarded_page.locator(".family-group")
    count = family_groups.count()
    assert count >= 1
    for i in range(count):
        box = family_groups.nth(i).bounding_box()
        assert box is not None
        assert box["height"] <= 60, (
            f"family group {i} is {box['height']}px tall, expected a compact block"
        )

    padding = guarded_page.eval_on_selector(".family-group", "el => getComputedStyle(el).padding")
    assert padding == "0px"
    list_margin = guarded_page.eval_on_selector(
        ".network-list", "el => getComputedStyle(el).margin"
    )
    assert list_margin == "0px"


def test_network_checklist_rows_are_compact_on_desktop(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    """Within one family, adjacent network checkbox rows are tightly spaced.
    The stock fixture has only one network per family, so a second `disney`
    network is added the same way
    `test_unchecking_one_network_leaves_family_indeterminate` does, to get
    two `<li>` rows inside one `.network-list`."""
    mutated = json.loads(json.dumps(fixture_raw))
    mutated["lookups"]["networks"].append(
        {"id": "net-e", "name": "Gamma Sports", "family": "disney"}
    )
    new_idx = len(mutated["lookups"]["networks"]) - 1
    mutated["telecasts"]["network"][4] = new_idx
    mutated["telecasts"]["outlets"][4] = [new_idx]
    body = json.dumps(mutated)

    guarded_page.route(
        "**/site-data.json*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=body),
    )
    open_app(guarded_page, "")
    _open_filter(guarded_page, "networks")

    rows = guarded_page.locator(
        "fieldset.family-group:has(input[data-family-checkbox='disney']) .network-list li"
    )
    expect(rows).to_have_count(2)

    tops = [rows.nth(i).bounding_box()["y"] for i in range(2)]
    gap = tops[1] - tops[0]
    assert gap <= 26, f"adjacent network rows sit {gap}px apart, expected a compact list"


def test_mobile_filters_sheet(mobile_page: Page, open_app: Callable[[Page, str], None]) -> None:
    """D-03: the phone Filters(N) button opens a full-height bottom sheet
    with every filter section stacked, Clear all on top and Show results at
    the bottom."""
    open_app(mobile_page, "")
    filters_button = mobile_page.locator("#filters-button")
    expect(filters_button).to_be_visible()
    for name in (
        "announcers",
        "seasons",
        "networks",
        "kickoff",
        "role",
        "conference",
        "school",
        "postseason",
    ):
        expect(mobile_page.locator(f"#trigger-{name}")).to_be_hidden()

    filters_button.click()
    mobile_page.wait_for_function(
        "document.getElementById('filters-sheet').matches(':popover-open')"
    )
    # The native `toggle` event (which moves focus) fires asynchronously
    # relative to `:popover-open` becoming true, so wait for the focus move
    # itself rather than racing it.
    mobile_page.wait_for_function("document.activeElement.id === 'clear-filters'")

    section_order = mobile_page.evaluate(
        "() => Array.from(document.querySelector('.sheet-body').children).map((el) => el.id)"
    )
    assert section_order == [
        "filter-announcers",
        "filter-seasons",
        "filter-networks",
        "filter-slots",
        "filter-role",
        "filter-conference",
        "filter-school",
        "filter-postseason",
    ]

    mobile_page.check("input[name='slot'][value='prime']")
    mobile_page.wait_for_function("location.search.includes('slot=prime')")
    expect(filters_button).to_have_text("Filters (1)")

    mobile_page.click("#filters-show-results")
    mobile_page.wait_for_function(
        "!document.getElementById('filters-sheet').matches(':popover-open')"
    )

    filters_button.click()
    mobile_page.wait_for_function(
        "document.getElementById('filters-sheet').matches(':popover-open')"
    )
    tappable = mobile_page.locator("#filters-sheet button:visible, #filters-sheet label:visible")
    count = tappable.count()
    assert count > 0
    for i in range(count):
        box = tappable.nth(i).bounding_box()
        assert box is not None
        assert box["height"] >= 44


def test_mobile_filters_button_badge_reflects_school_filter(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(mobile_page, "?school=northfield")
    expect(mobile_page.locator("#filters-button")).to_have_text("Filters (1)")


_POPOVER_TRIGGERS = (
    "announcers",
    "seasons",
    "networks",
    "kickoff",
    "role",
    "conference",
    "school",
    "postseason",
)

_FIRST_BOX_PROBE_JS = """
(id) => {
  window.__first = null;
  const pop = document.getElementById(id);
  const trigger = document.querySelector(`[popovertarget="${id}"]`);
  const ro = new ResizeObserver(() => {
    if (window.__first || !pop.matches(':popover-open')) return;
    const r = pop.getBoundingClientRect();
    const t = trigger.getBoundingClientRect();
    window.__first = {
      top: r.top,
      left: r.left,
      width: r.width,
      expectTop: t.bottom + 4,
      expectLeft: Math.max(8, Math.min(t.left, Math.max(8, innerWidth - r.width - 8))),
    };
    ro.disconnect();
  });
  ro.observe(pop);
}
"""


def _assert_first_frame_anchored(page: Page, name: str) -> None:
    """Opens `#trigger-{name}` and asserts the popover's first rendered box is
    anchored under its trigger (A5). A ResizeObserver fires in the first
    rendering update where the popover has a box -- after every rAF callback
    and layout, before paint -- so it sees what the first painted frame shows.
    (A capture-phase `beforetoggle` + rAF probe would sample before the app's
    own rAF refine and fail falsely.)"""
    popover_id = f"pop-{name}"
    page.evaluate(_FIRST_BOX_PROBE_JS, popover_id)
    page.click(f"#trigger-{name}")
    page.wait_for_function("() => window.__first !== null")
    first = page.evaluate("() => window.__first")
    assert abs(first["top"] - first["expectTop"]) < 1, (name, first)
    assert abs(first["left"] - first["expectLeft"]) < 1, (name, first)
    page.keyboard.press("Escape")
    page.wait_for_function(f"!document.getElementById('{popover_id}').matches(':popover-open')")


def test_popover_first_open_paints_anchored_at_1280(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """A5: on one fresh load every popover's first frame is anchored under its
    trigger, never at the top-left."""
    open_app(guarded_page, "")
    for name in _POPOVER_TRIGGERS:
        _assert_first_frame_anchored(guarded_page, name)


def test_popover_first_open_paints_anchored_at_1040_right_edge_clamp(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """A5: at 1040px wide the right-edge clamp applies to School and
    Bowls/Playoffs; their first frame must already be clamped."""
    guarded_page.set_viewport_size({"width": 1040, "height": 720})
    open_app(guarded_page, "")
    for name in _POPOVER_TRIGGERS:
        _assert_first_frame_anchored(guarded_page, name)


def test_popover_reopen_after_resize_paints_anchored(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """A5: a reopen after a viewport resize must not first paint at the stale
    inline top/left from the previous open."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "school")
    guarded_page.keyboard.press("Escape")
    guarded_page.wait_for_function(
        "!document.getElementById('pop-school').matches(':popover-open')"
    )
    guarded_page.set_viewport_size({"width": 900, "height": 720})
    _assert_first_frame_anchored(guarded_page, "school")


# ---------------------------------------------------------------------------
# A4: per-group Reset buttons
# ---------------------------------------------------------------------------

# (trigger name, section id, a non-default URL param, that param's key)
_RESET_GROUPS = [
    ("announcers", "filter-announcers", "people=pat-rowan", "people"),
    ("seasons", "filter-seasons", "seasons=2021-2026", "seasons"),
    ("networks", "filter-networks", "networks=net-a", "networks"),
    ("kickoff", "filter-slots", "slot=noon", "slot"),
    ("role", "filter-role", "role=pbp", "role"),
    ("conference", "filter-conference", "conferences=SEC", "conferences"),
    ("school", "filter-school", "school=northfield", "school"),
    ("postseason", "filter-postseason", "postseason=only", "postseason"),
]

_RESET_IDS = [group[0] for group in _RESET_GROUPS]


def _search_has_param(page: Page, key: str) -> bool:
    return bool(page.evaluate("(k) => new URLSearchParams(location.search).has(k)", key))


def test_popover_open_focus_skips_group_reset(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """A4: adding a Reset button to each popover header must not steal the
    open-time focus -- every popover still focuses the same first control as
    before (its search field / combobox / first checkbox / first radio), and
    focus never lands on a Reset button or its header."""
    open_app(guarded_page, "")

    expected: dict[str, str] = {
        "announcers": "el.id === 'person-search'",
        "conference": "el.id === 'conference-search'",
        "school": "el.id === 'school-search'",
        "postseason": "el.dataset.postseason === 'all'",
        "kickoff": "el.tagName === 'INPUT' && el.value === 'noon'",
        "role": "el.tagName === 'INPUT' && el.value === 'pbp'",
        "networks": "el.matches('input[type=\"checkbox\"]') && !!el.closest('#filter-networks')",
    }
    for name in _RESET_IDS:
        _open_filter(guarded_page, name)
        if name in expected:
            assert guarded_page.evaluate(
                f"(() => {{ const el = document.activeElement; return {expected[name]}; }})()"
            ), name
        assert (
            guarded_page.evaluate(
                "() => document.activeElement.closest('.group-reset, .section-head')"
            )
            is None
        ), name
        guarded_page.keyboard.press("Escape")
        guarded_page.wait_for_function(
            f"!document.getElementById('pop-{name}').matches(':popover-open')"
        )


@pytest.mark.parametrize(("name", "section", "param", "key"), _RESET_GROUPS, ids=_RESET_IDS)
def test_group_reset_sits_right_of_title_and_is_disabled_at_default(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    name: str,
    section: str,
    param: str,
    key: str,
) -> None:
    """A4: each popover header has a Reset button at the right of the title;
    at the group's default it reads aria-disabled and clicking it is a no-op
    that leaves focus inside the open popover (never on <body>)."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, name)

    reset = guarded_page.locator(f"#{section} .group-reset")
    expect(reset).to_be_visible()
    assert reset.get_attribute("aria-disabled") == "true"
    assert reset.inner_text() == "Reset"
    assert reset.get_attribute("aria-label", timeout=1000).startswith("Reset ")

    h3_box = guarded_page.locator(f"#{section} .section-head h3").bounding_box()
    reset_box = reset.bounding_box()
    assert h3_box is not None
    assert reset_box is not None
    assert reset_box["x"] > h3_box["x"] + h3_box["width"]

    # Playwright treats aria-disabled as not-enabled, so force the click (a real user can click it).
    reset.click(force=True)
    # Flush two animation frames (any state change would have rendered and
    # replaced the URL by then) instead of sleeping a fixed time.
    guarded_page.evaluate(
        "() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"
    )
    assert guarded_page.evaluate("() => location.search") == ""
    assert guarded_page.evaluate("() => !!document.activeElement.closest('.filter-popover')")
    assert guarded_page.locator(f"#pop-{name}").evaluate("el => el.matches(':popover-open')")


@pytest.mark.parametrize(("name", "section", "param", "key"), _RESET_GROUPS, ids=_RESET_IDS)
def test_group_reset_resets_only_its_own_group(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    name: str,
    section: str,
    param: str,
    key: str,
) -> None:
    """A4: with this group and one other group non-default, Reset is enabled;
    clicking it returns only this group to default (trigger inactive, URL
    param gone), leaves the other group alone, and disables itself again."""
    other = "postseason=only" if name == "role" else "role=pbp"
    other_key = other.split("=")[0]
    other_trigger = "postseason" if name == "role" else "role"
    open_app(guarded_page, f"?{param}&{other}")
    _open_filter(guarded_page, name)

    reset = guarded_page.locator(f"#{section} .group-reset")
    assert reset.get_attribute("aria-disabled") == "false"
    assert guarded_page.locator(f"#trigger-{name}").get_attribute("data-active") == "true"

    reset.click()
    guarded_page.wait_for_function(
        f"document.getElementById('trigger-{name}').dataset.active === 'false'"
    )
    assert not _search_has_param(guarded_page, key)
    assert _search_has_param(guarded_page, other_key)
    assert guarded_page.locator(f"#trigger-{other_trigger}").get_attribute("data-active") == "true"
    assert reset.get_attribute("aria-disabled") == "true"
    assert guarded_page.evaluate("() => !!document.activeElement.closest('.filter-popover')")


def test_announcers_reset_is_active_for_compare_mode_without_people(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """IN-02: `?mode=compare` with no people selected is a non-default
    Announcers state (its Reset clears compare/together), so the Reset must
    be enabled and clear it."""
    open_app(guarded_page, "?mode=compare")
    assert _search_has_param(guarded_page, "mode")
    _open_filter(guarded_page, "announcers")

    reset = guarded_page.locator("#filter-announcers .group-reset")
    assert reset.get_attribute("aria-disabled") == "false"
    reset.click()
    guarded_page.wait_for_function("location.search === ''")
    assert reset.get_attribute("aria-disabled") == "true"


_RESET_ARIA_LABELS = {
    "announcers": "Reset Announcers",
    "seasons": "Reset Seasons",
    "networks": "Reset Networks",
    "kickoff": "Reset Kickoff time",
    "role": "Reset Role",
    "conference": "Reset conference filter",
    "school": "Reset school filter",
    "postseason": "Reset bowls and playoffs filter",
}


def test_group_reset_aria_labels_read_naturally(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """IN-03: each Reset's accessible name starts with the visible "Reset"
    (WCAG 2.5.3) and names its group the way it reads aloud, not the
    section's "Filter by ..." heading."""
    open_app(guarded_page, "")
    labels = guarded_page.evaluate(
        "() => Object.fromEntries(Array.from(document.querySelectorAll('.group-reset'))"
        ".map((el) => [el.dataset.reset, el.getAttribute('aria-label')]))"
    )
    assert labels == _RESET_ARIA_LABELS


def test_group_reset_networks_header_survives_checklist_build(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """A4: `buildNetworkChecklist` rebuilds #filter-networks; its header
    wrapper (title + Reset) must be kept as the first child."""
    open_app(guarded_page, "")
    head = guarded_page.locator("#filter-networks > .section-head")
    assert head.count() == 1
    assert head.locator("h3").inner_text() == "Networks"
    assert head.locator(".group-reset").count() == 1
    assert (
        guarded_page.evaluate(
            "() => document.getElementById('filter-networks').firstElementChild.className"
        )
        == "section-head"
    )


def test_group_reset_and_clear_all_stay_consistent(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """A4: Clear all filters still resets every group (and people), leaving
    every Reset disabled."""
    open_app(guarded_page, "?people=pat-rowan&role=pbp&school=northfield&postseason=only")
    guarded_page.click("#clear-filters")
    guarded_page.wait_for_function("location.search === ''")
    states = guarded_page.evaluate(
        "() => Array.from(document.querySelectorAll('.group-reset'))"
        ".map((el) => el.getAttribute('aria-disabled'))"
    )
    assert states == ["true"] * 8


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_group_reset_text_meets_aa_contrast_enabled_and_disabled(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    scheme: str,
) -> None:
    """A4: the Reset text (enabled --reset, dimmed --muted) clears WCAG AA
    4.5:1 against the popover background in both themes -- dimming is by
    color, never opacity."""
    guarded_page.emulate_media(color_scheme=scheme)  # type: ignore[arg-type]
    open_app(guarded_page, "?role=pbp")
    colors = guarded_page.evaluate(
        "() => ({"
        " bg: getComputedStyle(document.getElementById('pop-role')).backgroundColor,"
        " enabled: getComputedStyle(document.querySelector('#filter-role .group-reset')).color,"
        " disabled: getComputedStyle(document.querySelector('#filter-slots .group-reset')).color,"
        " opacity: getComputedStyle(document.querySelector('#filter-slots .group-reset')).opacity,"
        "})"
    )
    bg = _parse_rgb(colors["bg"])
    assert _contrast_ratio(_parse_rgb(colors["enabled"]), bg) >= 4.5
    assert _contrast_ratio(_parse_rgb(colors["disabled"]), bg) >= 4.5
    assert colors["enabled"] != colors["disabled"]
    assert colors["opacity"] == "1"


def test_group_reset_takes_no_label_rule_styling(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """A4: the Reset is a plain button -- the `.filter-popover label` rules
    (display flex, margin-bottom) never apply to it, and its font is the
    shared label font."""
    open_app(guarded_page, "")
    result = guarded_page.evaluate(
        """() => {
          const btn = document.querySelector('#filter-role .group-reset');
          const probe = document.createElement('span');
          probe.style.font = 'var(--font-label)';
          document.body.appendChild(probe);
          const want = getComputedStyle(probe);
          const got = getComputedStyle(btn);
          const out = {
            marginBottom: got.marginBottom,
            display: got.display,
            font: [got.fontFamily, got.fontSize, got.fontWeight],
            want: [want.fontFamily, want.fontSize, want.fontWeight],
          };
          probe.remove();
          return out;
        }"""
    )
    assert result["marginBottom"] == "0px"
    assert result["display"] != "flex"
    assert result["font"] == result["want"]


@pytest.mark.parametrize(("name", "section", "param", "key"), _RESET_GROUPS, ids=_RESET_IDS)
def test_group_reset_focus_outline_is_not_clipped(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    name: str,
    section: str,
    param: str,
    key: str,
) -> None:
    """A4: a keyboard-focused Reset shows a solid focus ring, and the ring
    (2px outline + 2px offset) lies fully inside the popover's padding box --
    including the `overflow: hidden` Announcers popover."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, name)

    is_reset = "() => document.activeElement.classList.contains('group-reset')"
    if name == "seasons":
        # Seasons has no first-focus target: focus stays on the trigger, so Tab
        # moves forward into the popover's first control -- the Reset.
        guarded_page.keyboard.press("Tab")
    else:
        for _ in range(3):
            if guarded_page.evaluate(is_reset):
                break
            guarded_page.keyboard.press("Shift+Tab")
    assert guarded_page.evaluate(is_reset), name

    geometry = guarded_page.evaluate(
        f"""() => {{
          const btn = document.activeElement;
          const pop = document.getElementById('pop-{name}');
          const b = btn.getBoundingClientRect();
          const p = pop.getBoundingClientRect();
          const padLeft = p.left + pop.clientLeft;
          const padTop = p.top + pop.clientTop;
          return {{
            focusVisible: btn.matches(':focus-visible'),
            outlineStyle: getComputedStyle(btn).outlineStyle,
            leftGap: b.left - 4 - padLeft,
            rightGap: padLeft + pop.clientWidth - (b.right + 4),
            topGap: b.top - 4 - padTop,
            bottomGap: padTop + pop.clientHeight - (b.bottom + 4),
          }};
        }}"""
    )
    assert geometry["focusVisible"], name
    assert geometry["outlineStyle"] == "solid", name
    for edge in ("leftGap", "rightGap", "topGap", "bottomGap"):
        assert geometry[edge] >= -0.5, (name, edge, geometry)


def test_group_reset_in_phone_sheet_sections(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """A4: every phone-sheet section heading has a Reset at its right, and it
    resets that group."""
    open_app(mobile_page, "?role=pbp")
    mobile_page.click("#filters-button")
    mobile_page.wait_for_function(
        "document.getElementById('filters-sheet').matches(':popover-open')"
    )
    counts = mobile_page.evaluate(
        "() => Array.from(document.querySelectorAll('.sheet-body section'))"
        ".map((s) => s.querySelectorAll(':scope > .section-head .group-reset').length)"
    )
    assert counts == [1] * 8

    reset = mobile_page.locator("#filter-role .group-reset")
    assert reset.get_attribute("aria-disabled") == "false"
    reset.click()
    mobile_page.wait_for_function("!new URLSearchParams(location.search).has('role')")
    assert reset.get_attribute("aria-disabled") == "true"
