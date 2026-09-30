"""Announcers popover width, fixed selection band, and special Announcers button
(D-32, D-33, D-34), proven against the fixture build."""

from __future__ import annotations

import re
from collections.abc import Callable

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


def test_announcer_roles_have_no_dash_and_play_by_play_never_wraps(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 800})
    open_app(guarded_page, "")
    _open_announcers(guarded_page)
    texts: list[str] = guarded_page.eval_on_selector_all(
        "#person-results .option-role", "els => els.map(e => e.textContent)"
    )
    assert texts
    assert all(t in ("", "Play-by-play", "Analyst", "Sideline/other") for t in texts)
    wrapped: int = guarded_page.eval_on_selector_all(
        "#person-results .option-role",
        "els => els.filter(e => e.textContent === 'Play-by-play' && "
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


@pytest.mark.parametrize("width", [1280, 800])
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


def test_selection_band_height_is_fixed_on_phone(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(mobile_page, "")
    y0 = _y(mobile_page, "#chart")
    open_app(mobile_page, "?people=dale-harlow")
    assert abs(_y(mobile_page, "#chart") - y0) <= 0.5


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
