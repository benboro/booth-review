"""Gap round 1 browser tests for the "Only" rows and the Networks popover width
(SITE-29, SITE-31; D-26, D-28..D-31) -- proven against the synthetic contract
fixture build served by `guarded_page`, never real collected data.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

# Row pitches (y distance between consecutive rows' top edges) measured at
# 1280x800 on the CSS before plan 04.2-12; the D-29 fix must not change them.
KICKOFF_PITCH = 35.59
CONFERENCE_PITCH = 35.59

_LONG_NAME = "The Extraordinarily Long Synthetic Conference Network"


def _open_filter(page: Page, name: str) -> None:
    """Clicks `#trigger-{name}` and waits for its popover to open."""
    page.click(f"#trigger-{name}")
    page.wait_for_function(f"document.getElementById('pop-{name}').matches(':popover-open')")
    page.wait_for_function(
        f"document.getElementById('trigger-{name}').getAttribute('aria-expanded') === 'true'"
    )


def _net_item(page: Page, net_id: str) -> Any:
    return page.locator(f".check-item:has(input[data-network-id='{net_id}'])")


def _fam_item(page: Page, family: str) -> Any:
    return page.locator(f".check-item:has(input[data-family-checkbox='{family}'])")


def _only_btn(item: Any) -> Any:
    return item.locator(".only-btn")


def _slot_item(page: Page, slot: str) -> Any:
    return page.locator(f".check-item:has(input[name='slot'][value='{slot}'])")


def _conf_item(page: Page, name: str) -> Any:
    return page.locator(f".check-item:has(input[name='conference'][value='{name}'])")


def _box(loc: Any) -> dict[str, float]:
    box: dict[str, float] = loc.bounding_box()
    assert box is not None
    return box


def _cy(loc: Any) -> float:
    b = _box(loc)
    return b["y"] + b["height"] / 2


def _right(loc: Any) -> float:
    b = _box(loc)
    return b["x"] + b["width"]


def _opacity(loc: Any) -> str:
    return str(loc.evaluate("el => getComputedStyle(el).opacity"))


def _width(page: Page, pop_id: str) -> float:
    return _box(page.locator(f"#{pop_id}"))["width"]


@pytest.fixture
def serve_long_network(fixture_raw: dict[str, Any]) -> Callable[[Page], None]:
    """Renames net-c to a long synthetic name so the unfiltered Networks
    popover is clearly wider than the 240px minimum (D-28 needs headroom to
    narrow). Call before opening the app."""

    def _serve(page: Page) -> None:
        raw = copy.deepcopy(fixture_raw)
        for net in raw["lookups"]["networks"]:
            if net["id"] == "net-c":
                net["name"] = _LONG_NAME
        page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))

    return _serve


# ---------- D-28: Networks popover fits its offered rows ----------


def test_networks_popover_fits_offered_rows(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    serve_long_network: Callable[[Page], None],
) -> None:
    page = guarded_page
    page.set_viewport_size({"width": 1280, "height": 800})
    serve_long_network(page)
    open_app(page, "")
    _open_filter(page, "networks")
    w0 = _width(page, "pop-networks")
    assert w0 > 260, f"fixture width {w0} too near the 240 minimum to measure narrowing"
    assert w0 <= min(360, 1280 - 16)
    page.goto(page.url.split("?")[0] + "?people=dale-harlow")
    page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    _open_filter(page, "networks")
    w1 = _width(page, "pop-networks")
    assert w1 >= 240
    assert w1 <= w0 - 8, f"narrowed width {w1} vs unfiltered {w0}"


@pytest.mark.parametrize("query", ["", "?people=dale-harlow"])
def test_networks_popover_width_stable_on_clicks(
    guarded_page: Page, open_app: Callable[[Page, str], None], query: str
) -> None:
    page = guarded_page
    page.set_viewport_size({"width": 1280, "height": 800})
    open_app(page, query)
    _open_filter(page, "networks")
    w = _width(page, "pop-networks")
    item = _net_item(page, "net-a")
    item.locator("input").click()
    assert abs(_width(page, "pop-networks") - w) <= 0.5
    _only_btn(item).click()
    assert abs(_width(page, "pop-networks") - w) <= 0.5
    _only_btn(item).click()
    assert abs(_width(page, "pop-networks") - w) <= 0.5


# ---------- D-29: Only is vertically centered, family Only at the right edge ----------


def _row_for(page: Page, kind: str) -> Any:
    if kind == "family":
        _open_filter(page, "networks")
        return _fam_item(page, "fox")
    if kind == "channel":
        _open_filter(page, "networks")
        return _net_item(page, "net-b")
    if kind == "kickoff":
        _open_filter(page, "kickoff")
        return _slot_item(page, "noon")
    _open_filter(page, "conference")
    return _conf_item(page, "SEC")


@pytest.mark.parametrize("kind", ["family", "channel", "kickoff", "conference"])
def test_only_is_vertically_centered_on_every_row_type(
    guarded_page: Page, open_app: Callable[[Page, str], None], kind: str
) -> None:
    page = guarded_page
    page.set_viewport_size({"width": 1280, "height": 800})
    open_app(page, "")
    item = _row_for(page, kind)
    diff = _cy(_only_btn(item)) - _cy(item.locator(".option-name"))
    assert abs(diff) <= 1, f"{kind}: Only center is {diff}px off the label center"


def test_family_only_sits_at_the_row_right_edge(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    page = guarded_page
    page.set_viewport_size({"width": 1280, "height": 800})
    open_app(page, "")
    _open_filter(page, "networks")
    fam, net = _fam_item(page, "fox"), _net_item(page, "net-b")
    assert abs(_right(_only_btn(fam)) - _right(_only_btn(net))) <= 1
    assert abs(_right(fam.locator(".option-count")) - _right(net.locator(".option-count"))) <= 1


# ---------- D-30: Only reveals on hover or keyboard focus, not after a mouse click ----------


def test_only_hidden_after_mouse_opens_kickoff(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    page = guarded_page
    page.set_viewport_size({"width": 1280, "height": 800})
    open_app(page, "")
    _open_filter(page, "kickoff")
    page.mouse.move(0, 0)
    assert _opacity(_only_btn(_slot_item(page, "noon"))) == "0"


@pytest.mark.parametrize("kind", ["kickoff", "conference"])
def test_only_hidden_after_mouse_click_then_move_away(
    guarded_page: Page, open_app: Callable[[Page, str], None], kind: str
) -> None:
    page = guarded_page
    page.set_viewport_size({"width": 1280, "height": 800})
    open_app(page, "")
    if kind == "kickoff":
        _open_filter(page, "kickoff")
        item = _slot_item(page, "afternoon")
    else:
        _open_filter(page, "conference")
        item = _conf_item(page, "SEC")
    item.locator("input").click()
    page.mouse.move(0, 0)
    assert _opacity(_only_btn(item)) == "0"


def test_only_visible_on_tab_focus(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    page = guarded_page
    page.set_viewport_size({"width": 1280, "height": 800})
    open_app(page, "")
    _open_filter(page, "kickoff")
    page.mouse.move(0, 0)
    items = [_slot_item(page, s) for s in ("noon", "afternoon", "prime", "late")]
    seen_visible = 0
    for _ in range(3):
        page.keyboard.press("Tab")
        opacities = [_opacity(_only_btn(i)) for i in items]
        focused = [bool(i.evaluate("el => el.contains(document.activeElement)")) for i in items]
        for op, has_focus in zip(opacities, focused, strict=True):
            assert op == ("1" if has_focus else "0")
        seen_visible += sum(1 for f in focused if f)
    assert seen_visible >= 2


# ---------- D-31: Only and All occupy the same width ----------


@pytest.mark.parametrize(
    ("kind", "target", "reference"),
    [("networks", "net-b", "net-a"), ("kickoff", "prime", "noon")],
)
def test_count_column_stays_put_when_only_turns_all(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    kind: str,
    target: str,
    reference: str,
) -> None:
    page = guarded_page
    page.set_viewport_size({"width": 1280, "height": 800})
    open_app(page, "")
    _open_filter(page, kind)
    if kind == "networks":
        row, ref = _net_item(page, target), _net_item(page, reference)
    else:
        row, ref = _slot_item(page, target), _slot_item(page, reference)
    count = row.locator(".option-count")
    btn = _only_btn(row)
    before_right = _right(count)
    before_width = _box(btn)["width"]
    assert btn.evaluate("el => el.scrollWidth <= el.clientWidth")
    btn.click()
    page.wait_for_function("el => el.textContent.trim() === 'All'", arg=btn.element_handle())
    assert abs(_right(count) - before_right) <= 0.5
    assert abs(_right(count) - _right(ref.locator(".option-count"))) <= 0.5
    assert abs(_box(btn)["width"] - before_width) <= 0.5
    assert btn.evaluate("el => el.scrollWidth <= el.clientWidth")


# ---------- Guard: the D-29 fix keeps the compact row spacing ----------


def test_row_pitch_unchanged(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    page = guarded_page
    page.set_viewport_size({"width": 1280, "height": 800})
    open_app(page, "")
    _open_filter(page, "kickoff")
    k = _box(_slot_item(page, "afternoon"))["y"] - _box(_slot_item(page, "noon"))["y"]
    assert abs(k - KICKOFF_PITCH) <= 1, f"kickoff pitch {k}"
    page.keyboard.press("Escape")
    _open_filter(page, "conference")
    c = _box(_conf_item(page, "FBS Independents"))["y"] - _box(_conf_item(page, "Big Ten"))["y"]
    assert abs(c - CONFERENCE_PITCH) <= 1, f"conference pitch {c}"
