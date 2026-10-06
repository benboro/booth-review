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
    """Every season lists its game count (rated and unrated) on first load, once the
    "Games per season" disclosure is opened."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "seasons")
    guarded_page.click("#season-counts-details summary")
    text = guarded_page.inner_text("#season-counts")
    # Rated 2/2/4/4 plus unrated 1/4/2/1 (U0; U1-U4; U5, U6; U7).
    assert "2019: 3 games" in text
    assert "2021: 6 games" in text
    assert "2025: 6 games" in text
    assert "2026: 5 games" in text
    assert "telecast" not in text


def test_season_range_fades_dots_by_default_and_leaves_counts_unchanged(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """04.7 D-06: the season range fades dots by default and removes them only
    in Hide mode; it never changes the per-season counts list."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "seasons")
    guarded_page.select_option("#season-from", "2025")
    guarded_page.select_option("#season-to", "2026")
    guarded_page.wait_for_function("location.search.includes('seasons=2025-2026')")

    # 2025-2026: rated 8 plus unrated U5, U6, U7 = 11 passing of 20 games.
    assert _visible_count(guarded_page) == 20
    assert _view(guarded_page)["passingCount"] == 11
    guarded_page.evaluate("window.__testHooks.setState({ dots: 'hide' })")
    guarded_page.wait_for_function("location.search.includes('dots=hide')")
    assert _visible_count(guarded_page) == 11
    assert _view(guarded_page)["passingCount"] == 11
    guarded_page.click("#season-counts-details summary")
    text = guarded_page.inner_text("#season-counts")
    assert "2019: 3 games" in text


@pytest.mark.parametrize(
    ("query", "expected_seasons", "selects", "passing"),
    [
        # Entirely past the last data season: falls back to unfiltered.
        ("?seasons=2030-2040", None, ("2019", "2026"), 20),
        # Ends inside gaps (no 2020/2022-2024 data): snaps onto 2021-2021.
        ("?seasons=2020-2022", [2021, 2021], ("2021", "2021"), 6),
        # Wholly inside a gap: no data season in range, unfiltered.
        ("?seasons=2022-2024", None, ("2019", "2026"), 20),
        # Reversed and starting before the data: swapped, then snapped.
        ("?seasons=2020-2000", [2019, 2019], ("2019", "2019"), 3),
    ],
)
def test_season_link_snaps_to_data_seasons_the_selects_can_show(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    query: str,
    expected_seasons: list[int] | None,
    selects: tuple[str, str],
    passing: int,
) -> None:
    """WR-13: a seasons link never decodes to an inverted range or to a
    season neither `<select>` offers (which blanked both selects and hid
    every dot); it snaps onto data seasons or falls back to unfiltered."""
    open_app(guarded_page, query)
    assert guarded_page.evaluate("window.__testHooks.getState().seasons") == expected_seasons
    assert guarded_page.input_value("#season-from") == selects[0]
    assert guarded_page.input_value("#season-to") == selects[1]
    assert _view(guarded_page)["passingCount"] == passing


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


def test_unchecking_fox_family_hides_its_dots(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """04.7 D-07: Networks always hides -- unchecking a family box removes its
    networks' dots, so `visibleCount` and `passingCount` both drop to 15 (the 5 net-b
    games, 3 rated and 2 unrated, are gone); 9 rated dots stay plotted."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "networks")
    guarded_page.uncheck("input[data-family-checkbox='fox']")
    guarded_page.wait_for_function("location.search.includes('networks=')")

    assert _visible_count(guarded_page) == 15
    assert _view(guarded_page)["passingCount"] == 15
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

    assert _visible_count(guarded_page) == 5  # net-b: rated 1, 5, 9 plus unrated 12, 16
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
        {"id": "net-g", "name": "Gamma Sports", "family": "disney"}
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
    guarded_page.uncheck("input[data-network-id='net-g']")
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
    """04.7 D-06: checking a slot fades non-matching dots, including the one with
    unknown kickoff, rather than removing them."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "kickoff")
    guarded_page.check("input[name='slot'][value='prime']")
    guarded_page.wait_for_function("location.search.includes('slot=prime')")

    assert _visible_count(guarded_page) == 20
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

    assert _visible_count(guarded_page) == 20
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

    # Faceting hides schools left with no games, so pick one that still has games.
    _open_filter(guarded_page, "school")
    school = guarded_page.locator("#school-list .check-item:not([hidden]) input").first
    slug = school.get_attribute("value")
    assert slug
    school.check()
    guarded_page.wait_for_function(f"location.search.includes('school={slug}')")

    url = guarded_page.evaluate("location.search")
    fragments = (
        "seasons=2021-2026",
        "networks=",
        "slot=prime",
        "role=analyst",
        f"school={slug}",
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
            f"() => document.querySelector(\"#school-list input[value='{slug}']\").checked"
        )
        is True
    )
    assert guarded_page.evaluate("() => document.getElementById('school-chips').textContent")

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

    assert _visible_count(guarded_page) == 20
    view = _view(guarded_page)
    assert view["passingCount"] == 20
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
        "trigger-game",
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
        "#conference-list .option-name",
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
        if family_groups.nth(i).locator(".network-list li").count() != 1:
            continue  # only single-network groups are compared (disney has two since 04.13)
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
    """Within one family, adjacent network checkbox rows are tightly spaced. Since
    04.13 the stock fixture's disney family holds two networks (Alpha Sports and
    Stream Plus), so it gives two `<li>` rows inside one `.network-list`."""
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
        "game",
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
        "filter-game",
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
    "game": "Reset game filter",
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
    assert states == ["true"] * 9


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
        ".map((s) => s.querySelectorAll('.section-head .group-reset').length)"
    )
    assert counts == [1] * 9

    reset = mobile_page.locator("#filter-role .group-reset")
    assert reset.get_attribute("aria-disabled") == "false"
    reset.click()
    mobile_page.wait_for_function("!new URLSearchParams(location.search).has('role')")
    assert reset.get_attribute("aria-disabled") == "true"


# ---------- Faceted filters (SITE-29; D-08..D-15) ----------


def _net_item(page: Page, net_id: str) -> Any:
    return page.locator(f".check-item:has(input[data-network-id='{net_id}'])")


def _fam_item(page: Page, family: str) -> Any:
    return page.locator(f".check-item:has(input[data-family-checkbox='{family}'])")


def _count_text(item: Any) -> str:
    return str(item.locator(".option-count").inner_text()).strip()


def test_facet_person_narrows_networks_to_their_family_and_channel(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-09 acceptance case: with only dale-harlow (the Gus Johnson analog) picked,
    Networks offers only the channels of his games: net-a (rated 0, 8) and, since
    04.13, net-c (his unrated game 17)."""
    open_app(guarded_page, "?people=dale-harlow")
    _open_filter(guarded_page, "networks")
    expect(_net_item(guarded_page, "net-a")).to_be_visible()
    expect(_fam_item(guarded_page, "disney")).to_be_visible()
    assert _count_text(_net_item(guarded_page, "net-a")) == "(2)"
    expect(_net_item(guarded_page, "net-c")).to_be_visible()
    assert _count_text(_net_item(guarded_page, "net-c")) == "(1)"
    for net_id in ("net-b", "net-d", "net-e"):
        expect(_net_item(guarded_page, net_id)).to_be_hidden()
    for family in ("fox", "other"):
        expect(_fam_item(guarded_page, family)).to_be_hidden()


def test_facet_default_counts_show_on_every_option(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-12 / 04.13 D-08: each option shows its count of games (rated and unrated), and the
    accessible name says so."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "networks")
    # net-a 3+3, net-b 3+2, net-c 3+1, net-d 3+0, net-e 0+2 (rated + unrated) = 20 games.
    expected = {"net-a": 6, "net-b": 5, "net-c": 4, "net-d": 3, "net-e": 2}
    for net_id, n in expected.items():
        assert _count_text(_net_item(guarded_page, net_id)) == f"({n})"
    box = guarded_page.get_by_role("checkbox", name=re.compile("Alpha Sports.*6 games"))
    expect(box).to_have_count(1)


def test_facet_explicit_networks_pick_made_impossible_stays_greyed(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-11, D-15: 1 of 5 is narrowed, so an impossible pick stays checked, greyed
    '(0)', in the URL, and returns to normal once the causing person is cleared."""
    open_app(guarded_page, "?people=dale-harlow&networks=net-b")
    _open_filter(guarded_page, "networks")
    item = _net_item(guarded_page, "net-b")
    expect(item).to_be_visible()
    expect(item).to_have_class(re.compile("is-zero"))
    assert _count_text(item) == "(0)"
    box = item.locator("input")
    expect(box).to_be_checked()
    expect(box).to_be_enabled()
    expect(_net_item(guarded_page, "net-a")).to_be_visible()
    assert _count_text(_net_item(guarded_page, "net-a")) == "(2)"
    expect(_net_item(guarded_page, "net-c")).to_be_visible()  # Dale's unrated game 17
    expect(_net_item(guarded_page, "net-d")).to_be_hidden()
    assert "net-b" in guarded_page.evaluate("location.search")

    guarded_page.evaluate("window.__testHooks.setState({ people: [] })")
    expect(item).not_to_have_class(re.compile("is-zero"))
    assert _count_text(item) == "(5)"  # net-b: rated 1, 5, 9 plus unrated 12, 16


def test_facet_networks_tie_counts_as_narrowed(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-11 amendment: 2 of 4 checked is narrowed (2 * checked <= total)."""
    open_app(guarded_page, "?people=dale-harlow&networks=net-a,net-b")
    _open_filter(guarded_page, "networks")
    item = _net_item(guarded_page, "net-b")
    expect(item).to_be_visible()
    expect(item).to_have_class(re.compile("is-zero"))
    assert _count_text(item) == "(0)"
    expect(item.locator("input")).to_be_checked()


def test_facet_networks_all_but_a_few_hides_impossible_rows(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-11 amendment: 3 of 5 is default-like, so impossible rows hide instead of grey."""
    open_app(guarded_page, "?people=dale-harlow&networks=net-a,net-b,net-c")
    _open_filter(guarded_page, "networks")
    expect(_net_item(guarded_page, "net-b")).to_be_hidden()
    expect(_net_item(guarded_page, "net-c")).to_be_visible()  # Dale's unrated game 17
    expect(_net_item(guarded_page, "net-a")).to_be_visible()
    expect(_net_item(guarded_page, "net-a").locator("input")).to_be_checked()


def test_facet_conference_counts_use_others_only(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-08: checking a conference leaves the other non-zero conferences visible
    and changes the Networks counts."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "networks")
    before = [_count_text(_net_item(guarded_page, n)) for n in ("net-a", "net-b", "net-c", "net-d")]
    guarded_page.keyboard.press("Escape")
    _open_filter(guarded_page, "conference")
    default_visible = guarded_page.locator("#conference-list .check-item:not([hidden])").count()
    assert default_visible >= 2
    guarded_page.check("#conference-list input[value='Big Ten']")
    guarded_page.wait_for_function("location.search.includes('conferences=Big%20Ten')")
    assert (
        guarded_page.locator("#conference-list .check-item:not([hidden])").count()
        == default_visible
    )
    guarded_page.keyboard.press("Escape")
    _open_filter(guarded_page, "networks")
    after = [_count_text(_net_item(guarded_page, n)) for n in ("net-a", "net-b", "net-c", "net-d")]
    assert before != after


def test_facet_conference_pick_made_impossible_stays_checked_and_greyed(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-11, D-15: a checked conference a person makes impossible stays checked,
    greyed '(0)', and in the URL."""
    open_app(guarded_page, "?people=dale-harlow")
    counts = _view(guarded_page)["facets"]["conferences"]
    all_names = guarded_page.evaluate("window.__testHooks.data.fbsConferences")
    zero = next(name for name in all_names if not counts.get(name))
    guarded_page.evaluate(f"window.__testHooks.setState({{ conferences: [{json.dumps(zero)}] }})")
    _open_filter(guarded_page, "conference")
    item = guarded_page.locator(
        f"#conference-list .check-item:has(input[value={json.dumps(zero)}])"
    )
    expect(item).to_be_visible()
    expect(item).to_have_class(re.compile("is-zero"))
    expect(item.locator("input")).to_be_checked()
    assert _count_text(item) == "(0)"
    assert "conferences=" in guarded_page.evaluate("location.search")


def test_facet_school_zero_rows_hide_and_search_combines(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Facet hiding and text-search hiding are independent (Pitfall 7)."""
    open_app(guarded_page, "?people=dale-harlow")
    _open_filter(guarded_page, "school")
    visible = guarded_page.locator("#school-list .check-item:not([hidden])").count()
    total = guarded_page.locator("#school-list .check-item").count()
    assert 0 < visible < total
    hidden_slug = guarded_page.evaluate(
        "Array.from(document.querySelectorAll('#school-list .check-item[hidden] input'))[0].value"
    )
    guarded_page.fill("#school-search", "zzzz")
    guarded_page.fill("#school-search", "")
    assert guarded_page.locator("#school-list .check-item:not([hidden])").count() == visible
    hidden_item = guarded_page.locator(f".check-item:has(input[value='{hidden_slug}'])")
    expect(hidden_item).to_be_hidden()
    # A search-hidden row stays hidden when facets change.
    guarded_page.fill("#school-search", "zzzz")
    guarded_page.evaluate("window.__testHooks.setState({ people: [] })")
    assert guarded_page.locator("#school-list .check-item:not([hidden])").count() == 0
    guarded_page.fill("#school-search", "")
    assert guarded_page.locator("#school-list .check-item:not([hidden])").count() == total


def test_facet_kickoff_zero_counts_grey_but_stay_clickable(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-13: Kickoff never hides or disables an option."""
    open_app(guarded_page, "?people=dale-harlow")
    _open_filter(guarded_page, "kickoff")
    # Dale: rated 0 (noon), 8 (afternoon) plus unrated 17 (noon).
    expected = {"noon": "(2)", "afternoon": "(1)", "prime": "(0)", "late": "(0)"}
    for slot, text in expected.items():
        item = guarded_page.locator(f".check-item:has(input[name='slot'][value='{slot}'])")
        expect(item).to_be_visible()
        assert _count_text(item) == text
        expect(item.locator("input")).to_be_enabled()
        if text == "(0)":
            expect(item).to_have_class(re.compile("is-zero"))
    guarded_page.check("input[name='slot'][value='prime']")
    guarded_page.wait_for_function("location.search.includes('slot=prime')")


def test_facet_role_counts_show_and_zero_stays_enabled(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-13: Role shows counts and never disables an option."""
    open_app(guarded_page, "?people=dale-harlow")
    _open_filter(guarded_page, "role")
    for value in ("pbp", "analyst"):
        label = guarded_page.locator(f"#filter-role label:has(input[value='{value}'])")
        expect(label.locator(".option-count")).to_have_text(re.compile(r"^\(\d+\)$"))
        expect(label.locator("input")).to_be_enabled()


def test_facet_postseason_counts_and_zero_option_selectable(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-13: Bowls/Playoffs shows All (3), Exclude (3), Only (0) greyed but selectable."""
    open_app(guarded_page, "?people=dale-harlow")
    _open_filter(guarded_page, "postseason")
    texts = {
        v: _count_text(guarded_page.locator(f"[data-postseason='{v}']"))
        for v in ("all", "exclude", "only")
    }
    assert texts == {"all": "(3)", "exclude": "(3)", "only": "(0)"}
    only = guarded_page.locator("[data-postseason='only']")
    expect(only).to_have_class(re.compile("is-zero"))
    only.click()
    guarded_page.wait_for_function("location.search.includes('postseason=only')")


def test_facet_clear_all_and_reset_restore_defaults(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Clear all and the Networks Reset return every list to all-visible default counts."""
    open_app(guarded_page, "?people=dale-harlow&networks=net-b")
    _open_filter(guarded_page, "networks")
    guarded_page.click("#pop-networks .group-reset")
    for net_id in ("net-b", "net-d", "net-e"):  # Dale's games are on net-a and net-c only
        expect(_net_item(guarded_page, net_id)).to_be_hidden()
    guarded_page.keyboard.press("Escape")
    guarded_page.click("#clear-filters")
    _open_filter(guarded_page, "networks")
    expected = {"net-a": 6, "net-b": 5, "net-c": 4, "net-d": 3, "net-e": 2}
    for net_id, n in expected.items():
        expect(_net_item(guarded_page, net_id)).to_be_visible()
        assert _count_text(_net_item(guarded_page, net_id)) == f"({n})"


def test_facet_does_not_change_which_dots_pass(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Carried D-13..D-15: faceting never changes passesFilters."""
    open_app(guarded_page, "?networks=net-a,net-b&slot=noon,afternoon")
    passing = _view(guarded_page)["passesFilters"]
    guarded_page.evaluate("window.__testHooks.setState({ people: ['dale-harlow'] })")
    guarded_page.evaluate("window.__testHooks.setState({ people: [] })")
    assert _view(guarded_page)["passesFilters"] == passing
    assert passing == sorted(passing)
    assert set(passing) <= set(range(20))  # rated 0-11 and unrated 12-19 pass the same way


# ---------- Seasons clamp and empty-state note (D-14) ----------


def _season_options(page: Page, select_id: str) -> list[str]:
    result: list[str] = page.eval_on_selector_all(
        f"#{select_id} option", "els => els.map((el) => el.textContent.trim())"
    )
    return result


def test_facet_seasons_offer_only_matching_seasons(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?people=dale-harlow")
    _open_filter(guarded_page, "seasons")
    # Dale: rated 0 (2019), 8 (2026) plus unrated 17 (2025).
    assert _season_options(guarded_page, "season-from") == ["2019", "2025", "2026"]
    assert _season_options(guarded_page, "season-to") == ["2019", "2025", "2026"]
    assert guarded_page.input_value("#season-from") == "2019"
    assert guarded_page.input_value("#season-to") == "2026"
    assert guarded_page.evaluate("window.__testHooks.getState().seasons") is None


def test_facet_seasons_selected_ends_with_no_games_read_zero_and_show_note(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    # Taylor Vance's games are rated 5 (2025) and 10 (2026), so 2019 and 2021 read zero
    # and the From menu stops at the first season with games (2025).
    open_app(guarded_page, "?people=taylor-vance&seasons=2019-2021")
    _open_filter(guarded_page, "seasons")
    assert _season_options(guarded_page, "season-from") == ["2019 (0)", "2021 (0)", "2025"]
    assert guarded_page.input_value("#season-from") == "2019"
    assert guarded_page.input_value("#season-to") == "2021"
    note = guarded_page.locator("#season-empty-note")
    expect(note).to_be_visible()
    expect(note.locator(".season-empty-title")).to_have_text(
        "No games in 2019\u20132021 for this selection"
    )
    expect(note.locator(".season-empty-hint")).to_have_text(
        "Widen the season range or reset Seasons."
    )
    assert guarded_page.evaluate("window.__testHooks.getState().seasons") == [2019, 2021]
    assert "seasons=2019-2021" in guarded_page.evaluate("location.search")


def test_facet_seasons_single_year_note_wording(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?people=dale-harlow&seasons=2021-2021")
    expect(guarded_page.locator("#season-empty-note .season-empty-title")).to_have_text(
        "No games in 2021 for this selection"
    )


def test_facet_seasons_note_hidden_when_range_has_games_or_nothing_matches(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?seasons=2021-2026")
    expect(guarded_page.locator("#season-empty-note")).to_be_hidden()
    # No season has a matching game at all: another filter is the cause, so no note.
    open_app(guarded_page, "?seasons=2021-2025&people=dale-harlow&role=analyst&slot=late")
    assert sum(_view(guarded_page)["facets"]["seasons"].values()) == 0
    expect(guarded_page.locator("#season-empty-note")).to_be_hidden()


def test_facet_seasons_note_causes_no_layout_shift_and_survives_rerender(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?people=dale-harlow&seasons=2019-2026")
    expect(guarded_page.locator("#season-empty-note")).to_be_hidden()
    js = (
        "() => { const r = document.getElementById('chart-area').getBoundingClientRect();"
        " const s = document.querySelector('#chart .main-svg').getBoundingClientRect();"
        " return [r.x, r.width, r.height, s.width]; }"
    )
    hidden_geom = guarded_page.evaluate(js)
    guarded_page.evaluate("window.__testHooks.setState({ seasons: [2021, 2021] })")
    note = guarded_page.locator("#season-empty-note")
    expect(note).to_be_visible()
    assert guarded_page.evaluate(js) == hidden_geom
    assert (
        guarded_page.evaluate(
            "getComputedStyle(document.getElementById('season-empty-note')).pointerEvents"
        )
        == "none"
    )
    inside = guarded_page.evaluate(
        "document.getElementById('chart').contains(document.getElementById('season-empty-note'))"
    )
    assert inside is True
    guarded_page.click("#axis-toggle [data-axis='excitement']")
    expect(note).to_be_visible()


def test_facet_seasons_reset_clears_range_and_hides_note(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?people=dale-harlow&seasons=2021-2021")
    _open_filter(guarded_page, "seasons")
    expect(guarded_page.locator("#season-empty-note")).to_be_visible()
    guarded_page.click("#pop-seasons .group-reset")
    expect(guarded_page.locator("#season-empty-note")).to_be_hidden()
    assert guarded_page.evaluate("window.__testHooks.getState().seasons") is None
    assert _season_options(guarded_page, "season-from") == ["2019", "2025", "2026"]


def test_facet_seasons_one_sided_edit_keeps_untouched_end_at_data_bound(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """WR-01: with no season filter, the menus clamp to 2021-2026 under net-c
    (D-14), but changing only To must not commit the clamped From: the 2019
    dots stay, and the URL records the range the visitor actually set (D-15)."""
    open_app(guarded_page, "?networks=net-c")
    _open_filter(guarded_page, "seasons")
    assert guarded_page.input_value("#season-from") == "2021"
    guarded_page.select_option("#season-to", "2025")
    assert guarded_page.evaluate("window.__testHooks.getState().seasons") == [2019, 2025]
    assert "seasons=2019-2025" in guarded_page.evaluate("location.search")
    guarded_page.evaluate("window.__testHooks.setState({ networks: null })")
    # 2019-2025 under no network filter: rated 2+2+4 plus unrated 1+4+2 = 15 games.
    assert _view(guarded_page)["passingCount"] == 15


def test_facet_seasons_one_sided_edit_to_the_data_bound_sets_no_filter(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """WR-01: picking To=2026 with From untouched spans every season, so no
    season filter is stored and nothing lands in the URL."""
    open_app(guarded_page, "?networks=net-c")
    _open_filter(guarded_page, "seasons")
    guarded_page.select_option("#season-to", "2026")
    assert guarded_page.evaluate("window.__testHooks.getState().seasons") is None
    assert "seasons=" not in guarded_page.evaluate("location.search")
    expect(guarded_page.locator("#trigger-seasons")).to_have_text("Seasons")


def test_facet_view_exposes_plain_json_facets(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    facets = _view(guarded_page)["facets"]
    assert facets["seasons"] == {"2019": 3, "2021": 6, "2025": 6, "2026": 5}
    assert facets["networks"] == [6, 5, 4, 3, 2]


def test_unrated_only_network_is_counted_and_pickable(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """04.13 D-08: Stream Plus has no rated game, only unrated games 15 and 18; it
    still lists with a real count and picking it leaves exactly those two games."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "networks")
    item = _net_item(guarded_page, "net-e")
    expect(item).to_be_visible()
    assert _count_text(item) == "(2)"
    expect(item).not_to_have_class(re.compile("is-zero"))
    item.locator(".only-btn").click()
    guarded_page.wait_for_function("location.search.includes('networks=net-e')")
    assert _view(guarded_page)["passingCount"] == 2
    assert guarded_page.inner_text("#summary-count") == "0 rated of 2 games"


def test_unrated_only_announcer_is_counted_and_pickable(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """04.13 D-08: Morgan Ash works only unrated game 13; the Announcers list shows
    (1) and selecting him reads '0 rated of 1 game'."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "announcers")
    row = guarded_page.locator("#person-results li[data-person-id='morgan-ash']")
    expect(row).to_be_visible()
    assert str(row.locator(".option-count").inner_text()).strip() == "(1)"
    expect(row).not_to_have_class(re.compile("is-zero"))
    _add_person_by_query(guarded_page, "Morgan Ash")
    guarded_page.wait_for_function("location.search.includes('people=morgan-ash')")
    assert guarded_page.inner_text("#summary-count") == "0 rated of 1 game"


def test_game_picker_counts_the_unrated_bayside_game(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """04.13 D-08: the Harbor Bowl row counts rated game 7 (Acme Harbor Bowl, 2025) and
    unrated game 16 (Bayside Bowl, 2021); under Seasons 2021-2021 it keeps the Bayside
    game (count 1) and stays visible."""
    row_js = "() => document.querySelector('#game-options [data-game=\"harbor-bowl\"]')"
    open_app(guarded_page, "")
    _open_filter(guarded_page, "game")
    count = guarded_page.locator("#game-options [data-game='harbor-bowl'] .option-count")
    assert str(count.inner_text()).strip() == "(2)"
    guarded_page.keyboard.press("Escape")
    open_app(guarded_page, "?seasons=2021-2021")
    _open_filter(guarded_page, "game")
    assert guarded_page.evaluate(row_js + ".offsetParent !== null")
    assert str(count.inner_text()).strip() == "(1)"


def test_screen_reader_count_suffix_reads_games(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """04.13 D-07: the checkbox accessible name ends ', N games' / ', 1 game' and no
    facet string says 'telecast'."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "networks")
    expect(
        guarded_page.get_by_role("checkbox", name=re.compile("Alpha Sports.*, 6 games"))
    ).to_have_count(1)
    expect(
        guarded_page.get_by_role("checkbox", name=re.compile("Conference Network.*, 4 games"))
    ).to_have_count(1)
    guarded_page.evaluate("window.__testHooks.setState({ people: ['dale-harlow'] })")
    expect(
        guarded_page.get_by_role("checkbox", name=re.compile("Conference Network.*, 1 game$"))
    ).to_have_count(1)
    assert "telecast" not in guarded_page.inner_text("#pop-networks")


# ---------- "Only" / "All" shortcut (SITE-31, D-23..D-27) ----------


def _only_btn(item: Any) -> Any:
    return item.locator(".only-btn")


def _state(page: Page) -> dict[str, Any]:
    result: dict[str, Any] = page.evaluate("window.__testHooks.getState()")
    return result


def _slot_item(page: Page, slot: str) -> Any:
    return page.locator(f".check-item:has(input[name='slot'][value='{slot}'])")


def _conf_item(page: Page, name: str) -> Any:
    return page.locator(f".check-item:has(input[name='conference'][value='{name}'])")


def test_only_channel_selects_it_and_all_restores(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-24/D-25: Only on a channel selects it; the same button then reads All and resets."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "networks")
    btn = _only_btn(_net_item(guarded_page, "net-b"))
    expect(btn).to_have_text("Only")
    expect(btn).to_have_attribute("aria-label", "Show only Beta Network")
    btn.click()
    assert _state(guarded_page)["networks"] == ["net-b"]
    assert "networks=net-b" in guarded_page.evaluate("location.search")
    expect(btn).to_have_text("All")
    expect(btn).to_have_attribute("aria-label", "Show all networks")
    expect(guarded_page.locator("#trigger-networks")).to_have_text("Networks · 1")
    expect(guarded_page.locator(".legend-chip[data-family='fox']")).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(guarded_page.locator(".legend-chip[data-family='disney']")).to_have_attribute(
        "aria-pressed", "false"
    )
    btn.click()
    assert _state(guarded_page)["networks"] is None
    assert "networks=" not in guarded_page.evaluate("location.search")


def test_only_family_selects_only_offered_channels(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    """D-24: Only on a family selects its channels that have games under the other filters."""
    mutated = json.loads(json.dumps(fixture_raw))
    fox = mutated["lookups"]["networks"][1]["family"]
    mutated["lookups"]["networks"][3]["family"] = fox
    body = json.dumps(mutated)
    guarded_page.route(
        "**/site-data.json*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=body),
    )
    open_app(guarded_page, "?people=kris-venn")
    _open_filter(guarded_page, "networks")
    expect(_net_item(guarded_page, "net-d")).to_be_hidden()
    _only_btn(_fam_item(guarded_page, fox)).click()
    assert _state(guarded_page)["networks"] == ["net-b"]

    guarded_page.evaluate("window.__testHooks.setState({ people: [], networks: null })")
    _only_btn(_fam_item(guarded_page, fox)).click()
    assert _state(guarded_page)["networks"] == ["net-b", "net-d"]
    expect(_only_btn(_fam_item(guarded_page, fox))).to_have_text("All")


def test_only_kickoff_selects_slot_and_all_draws_unchecked(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-25 correction: All on a slot sets slots null and every box renders unchecked."""
    open_app(guarded_page, "")
    _open_filter(guarded_page, "kickoff")
    btn = _only_btn(_slot_item(guarded_page, "prime"))
    expect(btn).to_have_attribute("aria-label", "Show only Prime time")
    btn.click()
    assert _state(guarded_page)["slots"] == ["prime"]
    expect(guarded_page.locator("#trigger-kickoff")).to_have_text("Kickoff: Prime time")
    expect(btn).to_have_attribute("aria-label", "Show all kickoff times")
    btn.click()
    assert _state(guarded_page)["slots"] is None
    expect(guarded_page.locator("input[name='slot']:checked")).to_have_count(0)


def test_only_conference_replaces_picks_and_all_clears(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?conferences=SEC,Big+Ten")
    _open_filter(guarded_page, "conference")
    item = _conf_item(guarded_page, "Pac-12")
    expect(item).to_be_visible()
    _only_btn(item).click()
    assert _state(guarded_page)["conferences"] == ["Pac-12"]
    expect(_only_btn(item)).to_have_text("All")
    expect(_only_btn(item)).to_have_attribute("aria-label", "Show all conferences")
    _only_btn(item).click()
    assert _state(guarded_page)["conferences"] == []


def test_only_undone_by_group_reset_and_clear_all(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _open_filter(guarded_page, "networks")
    _only_btn(_net_item(guarded_page, "net-b")).click()
    guarded_page.click("#filter-networks .group-reset")
    assert _state(guarded_page)["networks"] is None
    _only_btn(_net_item(guarded_page, "net-b")).click()
    guarded_page.evaluate("document.getElementById('clear-filters').click()")
    assert _state(guarded_page)["networks"] is None


def test_only_click_toggles_no_checkbox_keeps_popover_and_focus(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _open_filter(guarded_page, "kickoff")
    btn = _only_btn(_slot_item(guarded_page, "noon"))
    btn.click()
    assert guarded_page.evaluate("document.getElementById('pop-kickoff').matches(':popover-open')")
    assert guarded_page.evaluate("document.activeElement.classList.contains('only-btn')")
    assert _state(guarded_page)["slots"] == ["noon"]
    expect(guarded_page.locator("input[name='slot']:checked")).to_have_count(1)


def test_only_buttons_exist_only_in_networks_conference_kickoff(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    for sel in ("#filter-school", "#filter-role", "#filter-postseason", "#person-results"):
        expect(guarded_page.locator(f"{sel} .only-btn")).to_have_count(0)
    for sel in ("#filter-networks", "#conference-list", "#filter-slots"):
        assert guarded_page.locator(f"{sel} .only-btn").count() > 0
    assert guarded_page.evaluate(
        "[...document.querySelectorAll('.only-btn')]"
        ".every(b => b.parentElement.classList.contains('check-item'))"
    )
    assert guarded_page.evaluate("document.querySelectorAll('label .only-btn').length") == 0


def test_only_family_button_hidden_when_no_channel_offered(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """A family row shown only via a greyed pick has nothing to select, so no Only button."""
    open_app(guarded_page, "?people=dale-harlow&networks=net-b")
    _open_filter(guarded_page, "networks")
    expect(_fam_item(guarded_page, "fox")).to_be_visible()
    expect(_only_btn(_fam_item(guarded_page, "fox"))).to_be_hidden()
    expect(_only_btn(_net_item(guarded_page, "net-b"))).to_be_visible()


def test_only_button_reveal_on_desktop(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _open_filter(guarded_page, "kickoff")
    item = _slot_item(guarded_page, "prime")
    btn = _only_btn(item)
    assert not guarded_page.evaluate("matchMedia('(hover: none)').matches")

    def opacity() -> str:
        return str(btn.evaluate("el => getComputedStyle(el).opacity"))

    guarded_page.mouse.move(0, 0)
    assert opacity() == "0"
    item.hover()
    assert opacity() == "1"
    guarded_page.mouse.move(0, 0)
    assert opacity() == "0"
    btn.focus()
    guarded_page.keyboard.press("Shift+Tab")
    guarded_page.keyboard.press("Tab")
    assert guarded_page.evaluate("document.activeElement.classList.contains('only-btn')")
    assert opacity() == "1"


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_only_button_touch_contrast_and_target(
    mobile_page: Page, open_app: Callable[[Page, str], None], scheme: str
) -> None:
    mobile_page.emulate_media(color_scheme=scheme)  # type: ignore[arg-type]
    open_app(mobile_page, "")
    assert mobile_page.evaluate("matchMedia('(hover: none)').matches")
    mobile_page.click("#filters-button")
    mobile_page.wait_for_function(
        "document.getElementById('filters-sheet').matches(':popover-open')"
    )
    btn = _only_btn(_slot_item(mobile_page, "prime"))
    btn.scroll_into_view_if_needed()
    assert btn.evaluate("el => getComputedStyle(el).opacity") == "1"
    color = btn.evaluate("el => getComputedStyle(el).color")
    muted_weak = mobile_page.evaluate(
        "(() => { const s = document.createElement('span');"
        "s.style.color = 'var(--muted-weak)'; document.body.append(s);"
        "const c = getComputedStyle(s).color; s.remove(); return c; })()"
    )
    assert color == muted_weak
    bg = mobile_page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert _contrast_ratio(_parse_rgb(color), _parse_rgb(bg)) >= 3.0
    box = btn.bounding_box()
    row = _slot_item(mobile_page, "prime").bounding_box()
    assert box is not None and row is not None
    assert box["width"] >= 44 and box["height"] >= 44
    assert abs((box["x"] + box["width"]) - (row["x"] + row["width"])) <= 1
