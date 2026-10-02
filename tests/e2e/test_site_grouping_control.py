"""04.6 SITE-39 (D-21..D-27): the single grouping control.

Which options apply, the default and the position-keeping fallback, that the control's
edges and the role control's left edge never move between subject states, and that on
phones the controls take exactly two rows without text overflow, under the default,
DejaVu and wide fonts. Legacy `bars`/`group` params are ignored and never re-emitted.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from conftest import _apply_font, _assert_guard_clean, _install_guard
from playwright.sync_api import Browser, Page

pytestmark = pytest.mark.e2e

BAR_VIEW = "?school=northfield&networks=net-a&view=bars"
FLY_VIEW = "?school=northfield,lakeview&people=kris-venn,pat-rowan&view=butterfly"
SCHOOL_ONLY = "?school=northfield&view=bars"
ANNOUNCER_ONLY = "?people=kris-venn&view=bars"

_EDGES_JS = """() => {
  const g = document.getElementById('group-by-toggle').getBoundingClientRect();
  const r = document.getElementById('bar-role-toggle').getBoundingClientRect();
  return { gl: g.left, gr: g.right, rl: r.left };
}"""

_VISIBLE_BY_JS = (
    "() => Array.from(document.querySelectorAll('#group-by-toggle button:not([hidden])'))"
    ".map((b) => b.dataset.by)"
)
_PRESSED_BY_JS = (
    "() => Array.from(document.querySelectorAll("
    "'#group-by-toggle button[aria-pressed=\"true\"]')).map((b) => b.dataset.by)"
)


def _visible_by(page: Page) -> list[str]:
    return list(page.evaluate(_VISIBLE_BY_JS))


def _pressed_by(page: Page) -> list[str]:
    return list(page.evaluate(_PRESSED_BY_JS))


def _search(page: Page) -> str:
    return str(page.evaluate("() => location.search"))


@pytest.fixture
def phone_width(request: pytest.FixtureRequest) -> int:
    return int(getattr(request, "param", 390))


@pytest.fixture
def phone_page(
    browser: Browser, site_url: str, font_setting: str, phone_width: int
) -> Iterator[Page]:
    """A guarded touch page at `phone_width` (SITE-19 off-origin guard mirrored)."""
    context = browser.new_context(
        viewport={"width": phone_width, "height": 780}, has_touch=True, is_mobile=True
    )
    page = context.new_page()
    off_origin, csp_errors = _install_guard(page, site_url)
    _apply_font(page, font_setting)
    try:
        yield page
    finally:
        context.close()
    _assert_guard_clean(off_origin, csp_errors)


# --- D-21: options follow the subjects ---------------------------------------


@pytest.mark.parametrize(
    ("query", "options"),
    [
        (SCHOOL_ONLY, ["announcer", "network"]),
        (ANNOUNCER_ONLY, ["team", "conference"]),
        (BAR_VIEW, ["announcer", "network", "team", "conference"]),
        (FLY_VIEW, ["announcer", "network", "team", "conference"]),
        ("?school=northfield,lakeview&view=butterfly", ["announcer", "network"]),
    ],
)
def test_options_follow_subjects(
    guarded_page: Page, open_app: Callable[[Page, str], None], query: str, options: list[str]
) -> None:
    open_app(guarded_page, query)
    assert _visible_by(guarded_page) == options


# --- D-25 / D-26 / D-27: default, fallback, legacy params --------------------


def test_default_and_fallback(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    page = guarded_page
    open_app(page, BAR_VIEW)
    assert _pressed_by(page) == ["announcer"]
    assert "by=" not in _search(page)

    page.locator('#group-by-toggle button[data-by="network"]').click()
    assert "by=network" in _search(page)
    assert _pressed_by(page) == ["network"]

    # Removing the school leaves team rows; the second position (conference) is kept.
    page.click("#trigger-school")
    page.wait_for_function("document.getElementById('pop-school').matches(':popover-open')")
    page.uncheck("#school-list input[value='northfield']")
    page.wait_for_function("window.__testHooks.getState().school.length === 0")
    assert _visible_by(page) == ["team", "conference"]
    assert _pressed_by(page) == ["conference"]

    open_app(page, ANNOUNCER_ONLY + "&by=conference")
    page.locator('#group-by-toggle button[data-by="team"]').click()
    assert "by=" not in _search(page)
    assert _pressed_by(page) == ["team"]


def test_legacy_params_are_ignored_and_not_reemitted(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    page = guarded_page
    open_app(page, "?bars=stacked&group=teams&school=northfield&view=bars")
    assert _pressed_by(page) == ["announcer"]
    page.locator('#group-by-toggle button[data-by="network"]').click()
    page.locator('#group-by-toggle button[data-by="announcer"]').click()
    search = _search(page)
    assert "bars=" not in search
    assert "group=" not in search


# --- D-22: edges never move ---------------------------------------------------


@pytest.mark.parametrize("font_setting", ["default", "dejavu"], indirect=True)
@pytest.mark.parametrize("width", [1280, 800])
def test_edges_never_move(
    guarded_page: Page, open_app: Callable[[Page, str], None], width: int
) -> None:
    page = guarded_page
    page.set_viewport_size({"width": width, "height": 900})
    edges: list[dict[str, float]] = []
    for query in (
        SCHOOL_ONLY,
        ANNOUNCER_ONLY,
        BAR_VIEW,
        BAR_VIEW + "&by=conference",
        FLY_VIEW,
    ):
        open_app(page, query)
        edges.append(page.evaluate(_EDGES_JS))
    for key in ("gl", "gr", "rl"):
        values = [e[key] for e in edges]
        assert max(values) - min(values) <= 0.5, (key, values)


# --- D-24: two phone rows -----------------------------------------------------


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide"], indirect=True)
@pytest.mark.parametrize("phone_width", [360, 390], indirect=True)
def test_two_phone_rows(
    phone_page: Page, open_app: Callable[[Page, str], None], phone_width: int
) -> None:
    page = phone_page
    open_app(page, BAR_VIEW)
    m: dict[str, Any] = page.evaluate(
        """() => {
          const box = (s) => document.querySelector(s).getBoundingClientRect();
          const buttons = Array.from(
            document.querySelectorAll('#group-by-toggle button:not([hidden])'));
          return {
            controls: box('#bar-controls').width,
            group: box('#group-by-toggle'),
            role: box('#bar-role-toggle'),
            buttons: buttons.map((b) => ({
              h: b.getBoundingClientRect().height,
              over: b.scrollWidth > b.clientWidth,
              name: b.dataset.by,
            })),
            prefixes: Array.from(document.querySelectorAll('#group-by-toggle .by-prefix'))
              .filter((p) => p.getClientRects().length > 0 &&
                getComputedStyle(p).display !== 'none').length,
          };
        }"""
    )
    assert abs(m["group"]["width"] - m["controls"]) <= 1, m
    assert m["role"]["top"] >= m["group"]["bottom"] - 0.5, m
    tops = {round(m["group"]["top"]), round(m["role"]["top"])}
    assert len(tops) == 2, m
    assert len(m["buttons"]) == 4
    for b in m["buttons"]:
        assert b["h"] >= 44 - 0.5, b
        assert not b["over"], b
    assert m["prefixes"] == 0


# --- D-24 / SITE-20 / SITE-28: the footprint is the same everywhere ----------

_FOOTPRINT_JS = """() => document.getElementById('chart-panel').getBoundingClientRect().top
  - document.getElementById('chart-controls').getBoundingClientRect().top"""


@pytest.mark.parametrize("phone_width", [360, 390], indirect=True)
def test_footprint_same_on_phones(
    phone_page: Page, open_app: Callable[[Page, str], None], phone_width: int
) -> None:
    _assert_footprint(phone_page, open_app)


def test_footprint_same_on_desktop(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    _assert_footprint(guarded_page, open_app)


def _assert_footprint(page: Page, open_app: Callable[[Page, str], None]) -> None:
    values: dict[str, float] = {}
    for name, query in (
        ("scatter", "?school=northfield"),
        ("school-bars", SCHOOL_ONLY),
        ("announcer-bars", ANNOUNCER_ONLY),
        ("both", BAR_VIEW),
        ("butterfly", FLY_VIEW),
    ):
        open_app(page, query)
        values[name] = page.evaluate(_FOOTPRINT_JS)
    assert max(values.values()) - min(values.values()) <= 1, values


# --- keyboard -----------------------------------------------------------------


def test_keyboard_skips_hidden_options(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    page = guarded_page
    open_app(page, SCHOOL_ONLY)
    page.locator('#group-by-toggle button[data-by="announcer"]').focus()
    reached = [page.evaluate("() => document.activeElement.dataset.by")]
    for _ in range(3):
        page.keyboard.press("Tab")
        if page.evaluate("() => !!document.activeElement.closest('#group-by-toggle')"):
            reached.append(page.evaluate("() => document.activeElement.dataset.by"))
        else:
            break
    assert reached == ["announcer", "network"]
