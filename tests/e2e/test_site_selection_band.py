"""Announcers popover width, the fixed count line, and special Announcers button
(D-32, D-33, D-34; Phase 26 Plan 07 turned the selection band into the count line)."""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_OPEN_POP = "document.getElementById('pop-announcers').matches(':popover-open')"


def _parse_rgb(css_color: str) -> tuple[float, float, float]:
    nums = re.findall(r"[\d.]+", css_color)
    return float(nums[0]), float(nums[1]), float(nums[2])


def _relative_luminance(rgb: tuple[float, float, float]) -> float:
    def channel(c: float) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast_ratio(fg: tuple[float, float, float], bg: tuple[float, float, float]) -> float:
    l1 = _relative_luminance(fg) + 0.05
    l2 = _relative_luminance(bg) + 0.05
    return max(l1, l2) / min(l1, l2)


def _token(page: Page, name: str) -> str:
    """Resolves a CSS custom property to its computed rgb() color."""
    result: str = page.evaluate(
        "(n) => { const s = document.createElement('span'); s.style.color = `var(${n})`;"
        "document.body.append(s); const c = getComputedStyle(s).color; s.remove(); return c; }",
        name,
    )
    return result


def _open_announcers(page: Page) -> None:
    page.click("#trigger-announcers")
    page.wait_for_function(_OPEN_POP)


def _y(page: Page, selector: str) -> float:
    box = page.locator(selector).bounding_box()
    assert box is not None
    return box["y"]


def _height(page: Page, selector: str) -> float:
    box = page.locator(selector).bounding_box()
    assert box is not None
    return box["height"]


@pytest.mark.parametrize("width", [1280, 800])
def test_announcers_popover_is_wider_and_never_scrolls_sideways(
    guarded_page: Page, open_app: Callable[[Page, str], None], width: int
) -> None:
    guarded_page.set_viewport_size({"width": width, "height": 800})
    open_app(guarded_page, "")
    _open_announcers(guarded_page)
    box = guarded_page.locator("#pop-announcers").bounding_box()
    assert box is not None
    if width == 1280:
        assert box["width"] >= 400
    assert box["x"] + box["width"] <= width - 8
    sizes: list[float] = guarded_page.eval_on_selector(
        "#person-results", "el => [el.scrollWidth, el.clientWidth]"
    )
    assert sizes[0] <= sizes[1]


def test_announcer_role_pills_never_wrap(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 800})
    open_app(guarded_page, "")
    _open_announcers(guarded_page)
    pills: list[list[str]] = guarded_page.eval_on_selector_all(
        "#person-results .option-role",
        "els => els.map(e => Array.from(e.querySelectorAll('.role-pill')).map(p => p.textContent))",
    )
    assert pills
    # Every row carries exactly one pill; an unrecognized usual_role gets the
    # grey Sideline pill rather than a blank cell (D-16).
    assert all(len(p) == 1 and p[0] in ("PBP", "Analyst", "Sideline") for p in pills)
    assert {"PBP", "Analyst", "Sideline"} <= {p[0] for p in pills}
    rights: list[int] = guarded_page.eval_on_selector_all(
        "#person-results .option-role",
        "els => els.map(e => Math.round(e.getBoundingClientRect().right))",
    )
    assert len(set(rights)) == 1  # role cells stay right-aligned with the count column
    wrapped: int = guarded_page.eval_on_selector_all(
        "#person-results .option-role .role-pill",
        "els => els.filter(e => "
        "e.getBoundingClientRect().height > 1.5 * parseFloat(getComputedStyle(e).lineHeight))"
        ".length",
    )
    assert wrapped == 0


def test_phone_announcers_list_has_no_horizontal_scroll(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(mobile_page, "")
    mobile_page.click("#filters-button")
    mobile_page.wait_for_function(
        "document.getElementById('filters-sheet').matches(':popover-open')"
    )
    sizes: list[float] = mobile_page.eval_on_selector(
        "#person-results", "el => [el.scrollWidth, el.clientWidth]"
    )
    assert sizes[0] <= sizes[1]


# Phase 26 Round 3: the count line is one fixed 32px band from 1104px; below it the actions drop
# to a second fixed row (72px). The count line never changes height with the picks, and the long
# toggle labels need 1280px and at most three people.
LONG_LABEL_MIN_WIDTH = 1280
ONE_ROW_MIN_WIDTH = 1104
TIER_WIDTHS = [1280, ONE_ROW_MIN_WIDTH, ONE_ROW_MIN_WIDTH - 1, 800, 481]


def _line_px(width: int) -> int:
    return 32 if width >= ONE_ROW_MIN_WIDTH else 72


FONTS = ["default", "dejavu", "wide"]

# The fixture person with the longest name (the widest one-person chip).
LONGEST_NAME_QUERY = "?people=dale-harlow-jr"
FOUR_PICKS = "?people=dale-harlow,kris-venn,sam-delgado,pat-rowan&mode=compare"


@pytest.mark.parametrize("font_setting", FONTS, indirect=True)
@pytest.mark.parametrize("width", TIER_WIDTHS)
def test_count_line_height_is_fixed(
    guarded_page: Page, open_app: Callable[[Page, str], None], width: int
) -> None:
    """0, 1 and 4 picks all give the same count line and band, and the legend row (the next
    block down) never moves."""
    guarded_page.set_viewport_size({"width": width, "height": 800})
    open_app(guarded_page, "")
    y0 = _y(guarded_page, "#legend-chips")
    band = _height(guarded_page, "#selection-bar")
    assert _height(guarded_page, "#summary") == _line_px(width)
    for query in ("?people=dale-harlow", LONGEST_NAME_QUERY, FOUR_PICKS):
        open_app(guarded_page, query)
        assert abs(_y(guarded_page, "#legend-chips") - y0) <= 0.5, query
        assert _height(guarded_page, "#selection-bar") == band, query
        assert _height(guarded_page, "#summary") == _line_px(width), query
    guarded_page.click("#clear-selection")
    assert abs(_y(guarded_page, "#legend-chips") - y0) <= 0.5


def test_the_selection_row_is_gone_and_the_count_line_has_no_box(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-03 / Round 3: no reserved selection row; chips and toggles sit on the page."""
    guarded_page.set_viewport_size({"width": 1280, "height": 800})
    open_app(guarded_page, "?people=dale-harlow")
    assert guarded_page.locator("#selection-row").count() == 0
    style = guarded_page.eval_on_selector(
        "#summary",
        "el => { const s = getComputedStyle(el); return [s.borderTopWidth, s.backgroundColor]; }",
    )
    assert style[0] == "0px"
    assert style[1] == "rgba(0, 0, 0, 0)"


@pytest.mark.parametrize("width", [1280, 481])
def test_chips_truncate_between_64_and_160px_with_the_full_name(
    guarded_page: Page, open_app: Callable[[Page, str], None], width: int
) -> None:
    guarded_page.set_viewport_size({"width": width, "height": 800})
    open_app(guarded_page, FOUR_PICKS)
    chips = guarded_page.locator("#chips .chip")
    assert chips.count() == 4
    for i in range(chips.count()):
        chip = chips.nth(i)
        box = chip.bounding_box()
        assert box is not None
        assert 64 - 0.5 <= box["width"] <= 160 + 0.5
        assert box["height"] == 28
        name = chip.get_attribute("title")
        assert name
        assert name in (chip.get_attribute("aria-label") or "")
    row = guarded_page.locator("#summary").bounding_box()
    assert row is not None
    assert row["height"] == _line_px(width)


@pytest.mark.parametrize(
    ("width", "long_labels"),
    [(LONG_LABEL_MIN_WIDTH, True), (LONG_LABEL_MIN_WIDTH - 1, False), (800, False)],
)
def test_toggles_switch_to_short_labels_below_1280px(
    guarded_page: Page, open_app: Callable[[Page, str], None], width: int, long_labels: bool
) -> None:
    guarded_page.set_viewport_size({"width": width, "height": 800})
    open_app(guarded_page, "?people=dale-harlow")
    expected = (
        ["Compare people", "Called together", "Clear selection"]
        if long_labels
        else ["Compare", "Together", "Clear people"]
    )
    for selector, label in zip(
        ["#compare-toggle", "#together-toggle", "#clear-selection"], expected, strict=True
    ):
        assert guarded_page.locator(selector).inner_text().strip().lstrip("\u2713\u00d7 ") == label
    # The full name is always the accessible name.
    assert guarded_page.get_attribute("#compare-toggle", "aria-label") == "Compare people"


def test_compare_note_sits_inside_the_summary_box_without_a_new_row(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-03: the transient "up to 4" note lives inside #summary and never grows the band."""
    guarded_page.set_viewport_size({"width": 1280, "height": 800})
    open_app(guarded_page, FOUR_PICKS)
    assert guarded_page.locator("#summary #compare-note").count() == 1
    assert _height(guarded_page, "#summary") == 32


def _gap_under_summary(page: Page) -> float:
    return _y(page, "#chart-tabs") - (_y(page, "#summary") + _height(page, "#summary"))


@pytest.mark.parametrize("font_setting", FONTS, indirect=True)
@pytest.mark.parametrize(("width", "bound"), [(1280, 34), (800, 70)])
def test_summary_gap_is_reclaimed(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    width: int,
    bound: int,
    font_setting: str,
) -> None:
    guarded_page.set_viewport_size({"width": width, "height": 800})
    open_app(guarded_page, "")
    gap = _gap_under_summary(guarded_page)
    print(f"MEASURED {font_setting} {width}px empty gap={gap:.1f}")
    assert gap <= bound


@pytest.mark.parametrize("font_setting", FONTS, indirect=True)
def test_phone_summary_gap_is_reclaimed(
    mobile_page: Page, open_app: Callable[[Page, str], None], font_setting: str
) -> None:
    open_app(mobile_page, "")
    gap = _gap_under_summary(mobile_page)
    print(f"MEASURED {font_setting} phone empty gap={gap:.1f}")
    assert gap <= 24


@pytest.mark.parametrize("font_setting", FONTS, indirect=True)
@pytest.mark.parametrize("width", [1280, ONE_ROW_MIN_WIDTH])
def test_actions_share_the_count_line_with_a_polite_live_region(
    guarded_page: Page, open_app: Callable[[Page, str], None], width: int
) -> None:
    guarded_page.set_viewport_size({"width": width, "height": 800})
    open_app(guarded_page, LONGEST_NAME_QUERY)
    left = guarded_page.locator("#summary .sum-left").bounding_box()
    right = guarded_page.locator("#summary .sum-right").bounding_box()
    assert left is not None
    assert right is not None
    assert abs(left["y"] - right["y"]) <= 0.5
    assert right["x"] >= left["x"]
    assert guarded_page.get_attribute("#summary", "aria-live") == "polite"
    detail = guarded_page.locator("#summary-detail")
    assert detail.get_attribute("title") == detail.inner_text()


@pytest.mark.parametrize("font_setting", FONTS, indirect=True)
def test_below_1104px_the_actions_drop_to_a_second_fixed_row(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    guarded_page.set_viewport_size({"width": ONE_ROW_MIN_WIDTH - 8, "height": 800})
    open_app(guarded_page, LONGEST_NAME_QUERY)
    left = guarded_page.locator("#summary .sum-left").bounding_box()
    right = guarded_page.locator("#summary .sum-right").bounding_box()
    assert left is not None
    assert right is not None
    assert right["y"] >= left["y"] + left["height"] - 0.5
    assert _height(guarded_page, "#summary") == 72


@pytest.mark.parametrize("font_setting", FONTS, indirect=True)
def test_phone_strip_buttons_share_one_row_in_the_filters_panel(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(mobile_page, "?people=dale-harlow")
    mobile_page.click("#filters-button")
    mobile_page.wait_for_function(
        "document.getElementById('filters-sheet').matches(':popover-open')"
    )
    ids = ["#compare-toggle", "#together-toggle", "#clear-selection"]
    boxes = [mobile_page.locator(i).bounding_box() for i in ids]
    for box in boxes:
        assert box is not None
        assert box["height"] >= 44
        assert boxes[0] is not None
        assert abs(box["y"] - boxes[0]["y"]) <= 1
    texts = [mobile_page.locator(i).inner_text().strip() for i in ids]
    assert [t.lstrip("\u2713\u00d7 ").strip() for t in texts] == [
        "Compare",
        "Together",
        "Clear people",
    ]
    names = ["Compare people", "Called together", "Clear selection"]
    for i, name in zip(ids, names, strict=True):
        assert mobile_page.get_attribute(i, "aria-label") == name
        # topbar.js replaces the two toggles' title with their help sentence (the
        # tooltip names the action in full); Clear keeps the static full-name title.
        if i == "#clear-selection":
            assert mobile_page.get_attribute(i, "title") == name


def test_desktop_selection_buttons_show_long_labels(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 800})
    open_app(guarded_page, "?people=dale-harlow")
    for sel, label in [
        ("#compare-toggle", "Compare people"),
        ("#together-toggle", "Called together"),
        ("#clear-selection", "Clear selection"),
    ]:
        assert label in guarded_page.locator(sel).inner_text()


def test_phone_compare_picks_leave_the_page_summary_and_width_alone(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Four Compare people live in the panel strip: the page's summary and width do not move."""
    open_app(mobile_page, "?people=dale-harlow")
    one = _height(mobile_page, "#summary")
    open_app(
        mobile_page,
        "?people=dale-harlow,kris-venn,sam-delgado,pat-rowan&mode=compare",
    )
    assert _height(mobile_page, "#summary") == one == 24
    overflow = mobile_page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0


_FAMILIES = ["disney", "fox", "cbs", "nbc", "cw", "wbd", "conference", "other"]


def _many_networks_raw(fixture_raw: dict[str, Any]) -> dict[str, Any]:
    """The contract fixture with every telecast on its own long-named network, so a
    broad filter passes games on many networks (as on the real data, where a
    Kickoff filter alone passes games on about 20). Synthetic names only."""
    raw = copy.deepcopy(fixture_raw)
    count = len(raw["telecasts"]["network"])
    raw["lookups"]["networks"] = [
        {
            "id": f"net-{k}",
            "name": f"Regional Sports Network {k + 1}",
            "family": _FAMILIES[k % len(_FAMILIES)],
        }
        for k in range(count)
    ]
    raw["telecasts"]["network"] = list(range(count))
    return raw


def test_a_broad_filter_alone_does_not_grow_the_selection_band(
    guarded_page: Page, open_app: Callable[[Page, str], None], fixture_raw: dict[str, Any]
) -> None:
    """WR-01 / SITE-20: the filter-only "N rated of M games" summary caps its network list, so a
    filter passing games on many networks keeps the band height and the chart in place."""
    raw = _many_networks_raw(fixture_raw)
    guarded_page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    guarded_page.set_viewport_size({"width": 800, "height": 800})
    open_app(guarded_page, "")
    band = _height(guarded_page, "#selection-bar")
    chart_top = _y(guarded_page, "#chart-area")
    open_app(guarded_page, "?slot=afternoon,prime,late")
    assert (
        guarded_page.inner_text("#summary-count") == "8 rated of 13 games"
    )  # slots: rated 8 (1,2,4,5,7-10) + unrated 6 (U0,2,3,4,6,7)
    assert guarded_page.inner_text("#summary-detail").endswith(
        " +6 more"
    )  # 9 networks: 8 rated plus lookup 0, which unrated games add
    assert abs(_height(guarded_page, "#selection-bar") - band) <= 0.5
    assert abs(_y(guarded_page, "#chart-area") - chart_top) <= 0.5


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide"], indirect=True)
def test_phone_summary_stays_one_line(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    # CI renders in DejaVu Sans, where dale-harlow's detail line (two networks since his
    # unrated game) is wider than a 390px phone; it must stay one line, not grow the band.
    open_app(mobile_page, "")
    assert _height(mobile_page, "#summary") == 24
    open_app(mobile_page, "?people=dale-harlow")
    # The summary is a fixed 24px box; a second line would be clipped, never grow it.
    assert _height(mobile_page, "#summary") == 24
    detail = mobile_page.locator("#summary-detail")
    assert detail.get_attribute("title") == detail.inner_text()


def test_summary_title_is_smaller(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 800})
    open_app(guarded_page, "?people=dale-harlow")
    size = guarded_page.eval_on_selector("#summary-count", "el => getComputedStyle(el).fontSize")
    # Latin Modern at the +1 step (Round 1: 22/27px) replaced the 20px title.
    assert size == "22px"


def test_announcers_trigger_is_a_plain_filter_that_takes_the_accent_when_changed(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-04 / C7: Announcers has no colour of its own. At rest it matches the other
    triggers; with a pick it uses the accent like any changed filter (accent use 1)."""
    guarded_page.set_viewport_size({"width": 1280, "height": 800})
    open_app(guarded_page, "")
    accent = _token(guarded_page, "--accent")
    style_js = (
        "el => { const s = getComputedStyle(el);"
        "return [s.borderBottomColor, s.color, s.backgroundColor,"
        " getComputedStyle(el.querySelector('.filter-value')).color]; }"
    )
    rest: list[str] = guarded_page.eval_on_selector("#trigger-announcers", style_js)
    seasons: list[str] = guarded_page.eval_on_selector("#trigger-seasons", style_js)
    assert rest == seasons
    bg = guarded_page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert _contrast_ratio(_parse_rgb(rest[1]), _parse_rgb(bg)) >= 4.5

    open_app(guarded_page, "?people=dale-harlow")
    active: list[str] = guarded_page.eval_on_selector("#trigger-announcers", style_js)
    # Round 3b: the accent is the pick's text and a 2px bottom line; there is no fill.
    assert active[0] == accent
    assert active[3] == accent
    assert active[2] == "rgba(0, 0, 0, 0)"
    assert _contrast_ratio(_parse_rgb(active[3]), _parse_rgb(bg)) >= 4.5
