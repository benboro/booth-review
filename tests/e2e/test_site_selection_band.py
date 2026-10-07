"""Announcers popover width, fixed selection band, and special Announcers button
(D-32, D-33, D-34), proven against the fixture build."""

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


# 04.15 D-02: the width at which the summary moves beside the person box. It is the
# `@media (min-width: ...)` that carries the 61px reserve in site/style.css.
BESIDE_MIN_WIDTH = 1104
# The 91px tier starts here (the box stops wrapping its buttons); below it the box wraps
# and the reserve is 127px.
ONE_ROW_MIN_WIDTH = 752
TIER_WIDTHS = [1280, BESIDE_MIN_WIDTH, BESIDE_MIN_WIDTH - 8, 800, ONE_ROW_MIN_WIDTH, 641]
FONTS = ["default", "dejavu", "wide"]

# The fixture person with the longest name (the widest one-person box).
LONGEST_NAME_QUERY = "?people=dale-harlow-jr"

_NATURAL_JS = """() => { const bar = document.getElementById('selection-bar');
  const old = bar.style.minHeight; bar.style.minHeight = '0px';
  const natural = bar.getBoundingClientRect().height; bar.style.minHeight = old;
  return [natural, parseFloat(getComputedStyle(bar).minHeight)]; }"""


@pytest.mark.parametrize("font_setting", FONTS, indirect=True)
@pytest.mark.parametrize("width", TIER_WIDTHS)
def test_selection_band_height_is_fixed(
    guarded_page: Page, open_app: Callable[[Page, str], None], width: int
) -> None:
    guarded_page.set_viewport_size({"width": width, "height": 800})
    open_app(guarded_page, "")
    y0 = _y(guarded_page, "#legend-chips")
    h0 = _height(guarded_page, "#selection-bar")
    open_app(guarded_page, "?people=dale-harlow")
    assert abs(_y(guarded_page, "#legend-chips") - y0) <= 0.5
    assert abs(_height(guarded_page, "#selection-bar") - h0) <= 0.5
    guarded_page.click("#clear-selection")
    assert abs(_y(guarded_page, "#legend-chips") - y0) <= 0.5


@pytest.mark.parametrize("font_setting", FONTS, indirect=True)
@pytest.mark.parametrize("width", TIER_WIDTHS)
def test_selection_band_reserve_has_small_headroom(
    guarded_page: Page, open_app: Callable[[Page, str], None], width: int, font_setting: str
) -> None:
    """The reserve is the natural one-person height plus a little: too small shifts the chart,
    too large leaves the gap this phase set out to shrink."""
    guarded_page.set_viewport_size({"width": width, "height": 800})
    open_app(guarded_page, LONGEST_NAME_QUERY)
    natural, reserve = guarded_page.evaluate(_NATURAL_JS)
    print(f"MEASURED {font_setting} {width}px natural={natural:.1f} reserve={reserve:.1f}")
    assert 2 <= reserve - natural <= 8


@pytest.mark.parametrize("font_setting", FONTS, indirect=True)
def test_phone_selection_band_reserve_has_small_headroom(
    mobile_page: Page, open_app: Callable[[Page, str], None], font_setting: str
) -> None:
    open_app(mobile_page, LONGEST_NAME_QUERY)
    natural, reserve = mobile_page.evaluate(_NATURAL_JS)
    print(f"MEASURED {font_setting} phone natural={natural:.1f} reserve={reserve:.1f}")
    assert 2 <= reserve - natural <= 8


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
    band = _height(mobile_page, "#selection-bar")
    print(f"MEASURED {font_setting} phone empty band={band:.1f}")
    assert band <= 162


@pytest.mark.parametrize("font_setting", FONTS, indirect=True)
@pytest.mark.parametrize("width", [1280, BESIDE_MIN_WIDTH])
def test_beside_layout_puts_summary_right_of_the_box(
    guarded_page: Page, open_app: Callable[[Page, str], None], width: int
) -> None:
    guarded_page.set_viewport_size({"width": width, "height": 800})
    open_app(guarded_page, LONGEST_NAME_QUERY)
    row = guarded_page.locator("#selection-row").bounding_box()
    summary = guarded_page.locator("#summary").bounding_box()
    assert row is not None
    assert summary is not None
    assert summary["x"] >= row["x"] + row["width"] + 7
    assert abs((summary["y"] + summary["height"] / 2) - (row["y"] + row["height"] / 2)) <= 4
    assert guarded_page.get_attribute("#summary", "aria-live") == "polite"
    detail = guarded_page.locator("#summary-detail")
    assert detail.get_attribute("title") == detail.inner_text()


@pytest.mark.parametrize("font_setting", FONTS, indirect=True)
def test_below_the_breakpoint_the_summary_sits_under_the_box(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    guarded_page.set_viewport_size({"width": BESIDE_MIN_WIDTH - 8, "height": 800})
    open_app(guarded_page, LONGEST_NAME_QUERY)
    row = guarded_page.locator("#selection-row").bounding_box()
    summary = guarded_page.locator("#summary").bounding_box()
    assert row is not None
    assert summary is not None
    assert summary["y"] >= row["y"] + row["height"] - 0.5


@pytest.mark.parametrize("font_setting", FONTS, indirect=True)
def test_phone_selection_buttons_share_one_row(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(mobile_page, "?people=dale-harlow")
    ids = ["#compare-toggle", "#together-toggle", "#clear-selection"]
    boxes = [mobile_page.locator(i).bounding_box() for i in ids]
    for box in boxes:
        assert box is not None
        assert box["height"] >= 44
        assert boxes[0] is not None
        assert abs(box["y"] - boxes[0]["y"]) <= 1
    texts = [mobile_page.locator(i).inner_text().strip() for i in ids]
    assert [t.lstrip("\u2713\u00d7 ").strip() for t in texts] == ["Compare", "Together", "Clear"]
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


def test_phone_compare_row_may_grow_without_horizontal_overflow(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-04: the reserve covers 0 or 1 person; four Compare people may grow the band."""
    open_app(
        mobile_page,
        "?people=dale-harlow,kris-venn,sam-delgado,pat-rowan&mode=compare",
    )
    assert _height(mobile_page, "#selection-bar") >= 156
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
        guarded_page.inner_text("#summary-count") == "8 rated of 14 games"
    )  # slots: rated 8 (1,2,4,5,7-10) + unrated 6 (U0,2,3,4,6,7)
    assert guarded_page.inner_text("#summary-detail").endswith(
        " +6 more"
    )  # 9 networks: 8 rated plus lookup 0, which unrated games add
    assert abs(_height(guarded_page, "#selection-bar") - band) <= 0.5
    assert abs(_y(guarded_page, "#chart-area") - chart_top) <= 0.5


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide"], indirect=True)
def test_selection_band_height_is_fixed_on_phone(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    # CI renders in DejaVu Sans, where dale-harlow's detail line (two networks since his
    # unrated game) is wider than a 390px phone; it must stay one line, not grow the band.
    open_app(mobile_page, "")
    y0 = _y(mobile_page, "#chart")
    open_app(mobile_page, "?people=dale-harlow")
    assert abs(_y(mobile_page, "#chart") - y0) <= 0.5
    detail = mobile_page.locator("#summary-detail")
    assert detail.get_attribute("title") == detail.inner_text()


def test_summary_title_is_smaller(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 800})
    open_app(guarded_page, "?people=dale-harlow")
    size = guarded_page.eval_on_selector("#summary-count", "el => getComputedStyle(el).fontSize")
    assert size == "20px"


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_announcers_trigger_is_the_special_filter(
    guarded_page: Page, open_app: Callable[[Page, str], None], scheme: str
) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 800})
    guarded_page.emulate_media(color_scheme=scheme)  # type: ignore[arg-type]
    open_app(guarded_page, "")
    special = _token(guarded_page, "--special")
    on_special = _token(guarded_page, "--on-special")
    reset = _token(guarded_page, "--reset")
    border = _token(guarded_page, "--border")
    style_js = (
        "el => { const s = getComputedStyle(el);"
        "return [s.borderTopColor, s.color, s.backgroundColor]; }"
    )

    rest: list[str] = guarded_page.eval_on_selector("#trigger-announcers", style_js)
    assert rest[0] == special
    assert rest[1] == special
    assert rest[1] != reset
    bg = guarded_page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert _contrast_ratio(_parse_rgb(rest[1]), _parse_rgb(bg)) >= 4.5
    seasons: str = guarded_page.eval_on_selector(
        "#trigger-seasons", "el => getComputedStyle(el).borderTopColor"
    )
    assert seasons == border

    open_app(guarded_page, "?people=dale-harlow")
    active: list[str] = guarded_page.eval_on_selector("#trigger-announcers", style_js)
    assert active[2] == special
    assert active[1] == on_special
    assert active[1] != reset
    assert _contrast_ratio(_parse_rgb(active[1]), _parse_rgb(active[2])) >= 4.5
