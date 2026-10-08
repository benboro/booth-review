"""The Y-axis control (04.15 D-09..D-12): markup, controls-row layout on every tab,
the Excitement swap, URL persistence, caption, band copy, tooltip, and the
summary/table/passing set staying identical in both Y modes (D-18, D-19).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

OpenApp = Callable[[Page, str], None]


def test_y_toggle_markup_and_default(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, "")
    buttons = guarded_page.locator("#y-toggle button")
    assert buttons.count() == 4
    assert [buttons.nth(i).inner_text() for i in range(4)] == [
        "Viewers",
        "Excitement",
        "Points",
        "Margin",
    ]
    assert [buttons.nth(i).get_attribute("data-y") for i in range(4)] == [
        "viewers",
        "excitement",
        "points",
        "margin",
    ]
    assert [buttons.nth(i).get_attribute("aria-pressed") for i in range(4)] == [
        "true",
        "false",
        "false",
        "false",
    ]
    assert buttons.nth(1).get_attribute("aria-label") == "Excitement"
    assert buttons.nth(1).get_attribute("title") == "Excitement"
    assert buttons.nth(2).get_attribute("title") == "Total points"
    assert buttons.nth(3).get_attribute("title") == "Winning margin"
    group = guarded_page.locator("#y-toggle")
    assert group.get_attribute("role") == "group"
    assert group.get_attribute("aria-label") == "Y-axis measure"
    captions = guarded_page.locator("#scatter-controls .axis-caption")
    assert [captions.nth(i).inner_text() for i in range(captions.count())] == [
        "X axis",
        "Y axis",
    ]


_Y_FIT_JS = """() => {
  const group = document.getElementById('y-toggle');
  const box = group.closest('.axis-group').getBoundingClientRect();
  const buttons = [...group.querySelectorAll('button')];
  return (
    buttons.every((b) => b.scrollWidth <= b.clientWidth) &&
    group.getBoundingClientRect().right <= box.right + 0.5
  );
}"""


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide"], indirect=True)
@pytest.mark.parametrize("width", [360, 390, 641, 700, 800, 1280])
def test_controls_row_height_is_equal_on_every_tab(
    guarded_page: Page, open_app: OpenApp, width: int
) -> None:
    page = guarded_page
    page.set_viewport_size({"width": width, "height": 900})
    open_app(page, "?school=northfield,lakeview")
    height = "document.getElementById('chart-controls').getBoundingClientRect().height"
    scatter = page.evaluate(height)
    overflow = page.evaluate(
        """() => ['#axis-toggle', '#y-toggle'].every((s) => {
            const r = document.querySelector(s).getBoundingClientRect();
            return r.left >= 0 && r.right <= window.innerWidth;
        })"""
    )
    assert overflow
    assert page.evaluate(_Y_FIT_JS)
    # The games table can overflow at 641px in the wide fonts (pre-existing, see
    # deferred-items.md), so check the controls row rather than the whole page.
    assert page.evaluate(
        "document.getElementById('chart-controls').scrollWidth <= window.innerWidth"
    )
    page.locator("#tab-bars").click()
    page.wait_for_selector("#bars-title")
    assert abs(page.evaluate(height) - scatter) <= 1
    page.locator("#tab-butterfly").click()
    assert abs(page.evaluate(height) - scatter) <= 1


def _state(page: Page) -> dict[str, object]:
    return page.evaluate("window.__testHooks.getState()")


def _search(page: Page) -> str:
    return page.evaluate("location.search")


def test_y_click_swaps_x_off_excitement(guarded_page: Page, open_app: OpenApp) -> None:
    page = guarded_page
    open_app(page, "?axis=excitement")
    page.locator('#y-toggle button[data-y="excitement"]').click()
    page.wait_for_function("location.search.includes('y=excitement')")
    state = _state(page)
    assert state["y"] == "excitement"
    assert state["axis"] == "spread"
    assert "axis=excitement" not in _search(page)
    for sel in (
        '#y-toggle button[data-y="excitement"]',
        '#axis-toggle button[data-axis="excitement"]',
    ):
        assert page.locator(sel).get_attribute("disabled") is None


def test_x_click_swaps_y_off_excitement(guarded_page: Page, open_app: OpenApp) -> None:
    page = guarded_page
    open_app(page, "?y=excitement")
    page.locator('#axis-toggle button[data-axis="excitement"]').click()
    page.wait_for_function("location.search.includes('axis=excitement')")
    state = _state(page)
    assert state["axis"] == "excitement"
    assert state["y"] == "viewers"
    assert "y=" not in _search(page).replace("axis=", "")
    assert (
        page.locator('#y-toggle button[data-y="viewers"]').get_attribute("aria-pressed") == "true"
    )


def test_y_persists_across_tabs_and_default_is_omitted(
    guarded_page: Page, open_app: OpenApp
) -> None:
    page = guarded_page
    open_app(page, "?school=northfield,lakeview&y=excitement")
    page.locator("#tab-bars").click()
    page.wait_for_selector("#bars-title")
    assert "y=excitement" in _search(page)
    page.locator("#tab-scatter").click()
    assert "y=excitement" in _search(page)
    pressed = page.locator('#y-toggle button[data-y="excitement"]').get_attribute("aria-pressed")
    assert pressed == "true"
    page.locator('#y-toggle button[data-y="viewers"]').click()
    page.wait_for_function("!location.search.includes('y=')")


def test_band_copy_follows_y_and_note_closes(guarded_page: Page, open_app: OpenApp) -> None:
    page = guarded_page
    open_app(page, "")
    page.wait_for_selector("#band-info:not([hidden])")
    page.click("#band-info")
    assert page.is_visible("#band-note")
    page.locator('#y-toggle button[data-y="excitement"]').click()
    page.wait_for_function("document.getElementById('band-note').hidden")
    assert page.inner_text("#band-info .band-info-text") == "No excitement value"
    assert (
        page.get_attribute("#band-info", "aria-label")
        == "Why do some games have no excitement value?"
    )
    page.locator('#y-toggle button[data-y="viewers"]').click()
    page.wait_for_function(
        "document.querySelector('#band-info .band-info-text').textContent === 'No public rating'"
    )


def test_excitement_caption_shows_for_either_axis(guarded_page: Page, open_app: OpenApp) -> None:
    page = guarded_page
    open_app(page, "")
    assert page.is_hidden("#excitement-caption")
    open_app(page, "?y=excitement")
    assert page.is_visible("#excitement-caption")
    open_app(page, "?axis=excitement")
    assert page.is_visible("#excitement-caption")
    open_app(page, "?school=northfield,lakeview&y=excitement")
    page.locator("#tab-bars").click()
    page.wait_for_selector("#bars-title")
    assert page.is_hidden("#excitement-caption")


_PICK_JS = """() => {
  const d = window.__testHooks.data;
  const out = {};
  for (let i = 0; i < d.n; i++) {
    if (d.rated[i] && d.t.excitement[i] != null && out.rated === undefined) out.rated = i;
    if (!d.rated[i] && d.t.excitement[i] != null && out.unrated === undefined) out.unrated = i;
  }
  return out;
}"""


def test_tooltip_lines_with_excitement_y(guarded_page: Page, open_app: OpenApp) -> None:
    from test_site_chart import _hover_dot, _use_plotly_tooltip

    page = guarded_page
    open_app(page, "?y=excitement")
    picks = page.evaluate(_PICK_JS)
    assert "rated" in picks and "unrated" in picks
    _hover_dot(page, picks["rated"])
    text = page.inner_text("#chart-tooltip")
    assert "Viewers: " in text
    assert " · Excitement: " in text
    _hover_dot(page, picks["unrated"])
    page.wait_for_function(
        "document.getElementById('chart-tooltip').innerText.includes('No public rating · ')"
    )
    assert " · Excitement: " in page.inner_text("#chart-tooltip")

    _use_plotly_tooltip(page)
    hover = page.evaluate(
        """(i) => {
          for (const t of document.getElementById('chart').data) {
            if (!t.customdata) continue;
            const k = t.customdata.indexOf(i);
            if (k !== -1 && t.text && t.text[k]) return String(t.text[k]);
          }
          return '';
        }""",
        picks["rated"],
    )
    assert " · Excitement: " in hover


_SUMMARY_JS = """() => ({
  count: document.getElementById('summary-count').textContent,
  detail: document.getElementById('summary-detail').textContent,
  rows: document.querySelectorAll('#games-table tbody tr').length,
  first: document.querySelector('#games-table tbody tr')?.textContent ?? '',
  passes: JSON.stringify(window.__testHooks.getView().passesFilters),
})"""


@pytest.mark.parametrize("query", ["people=dale-harlow", "school=northfield"])
def test_summary_table_and_passing_set_match_across_y(
    guarded_page: Page, open_app: OpenApp, query: str
) -> None:
    page = guarded_page
    open_app(page, f"?{query}")
    base = page.evaluate(_SUMMARY_JS)
    assert base["rows"] > 0
    open_app(page, f"?{query}&y=excitement")
    assert page.evaluate(_SUMMARY_JS) == base


def test_y_switch_has_no_page_errors(guarded_page: Page, open_app: OpenApp) -> None:
    page = guarded_page
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    for query in ("", "?axis=date"):
        open_app(page, query)
        for y in ("excitement", "viewers", "excitement", "viewers"):
            page.locator(f'#y-toggle button[data-y="{y}"]').click()
            page.wait_for_function("(y) => window.__testHooks.getState().y === y", arg=y)
    assert errors == []


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide"], indirect=True)
def test_y_row_short_excitement_label_below_360(mobile_page: Page, open_app: OpenApp) -> None:
    page = mobile_page
    page.set_viewport_size({"width": 340, "height": 900})
    open_app(page, "")
    button = page.locator('#y-toggle button[data-y="excitement"]')
    assert button.inner_text() == "Excite."
    assert button.get_attribute("aria-label") == "Excitement"
    assert button.get_attribute("title") == "Excitement"
    assert page.evaluate(_Y_FIT_JS)
    boxes = [page.locator("#y-toggle button").nth(i).bounding_box() for i in range(4)]
    assert all(box is not None for box in boxes)
    tops = [box["y"] for box in boxes if box]
    assert max(tops) - min(tops) <= 1
    assert all(box["height"] >= 44 for box in boxes if box)


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide"], indirect=True)
def test_y_row_full_excitement_label_at_360(mobile_page: Page, open_app: OpenApp) -> None:
    page = mobile_page
    page.set_viewport_size({"width": 360, "height": 900})
    open_app(page, "")
    button = page.locator('#y-toggle button[data-y="excitement"]')
    assert button.inner_text() == "Excitement"


@pytest.mark.parametrize("value", ["points", "margin"])
def test_y_url_accepts_points_and_margin(guarded_page: Page, open_app: OpenApp, value: str) -> None:
    page = guarded_page
    open_app(page, f"?y={value}")
    assert _state(page)["y"] == value
    assert f"y={value}" in _search(page)
    pressed = page.locator(f'#y-toggle button[data-y="{value}"]').get_attribute("aria-pressed")
    assert pressed == "true"
    # With X on Excitement both values are kept (no swap).
    open_app(page, f"?axis=excitement&y={value}")
    state = _state(page)
    assert state["axis"] == "excitement"
    assert state["y"] == value


@pytest.mark.parametrize("query", ["?y=bogus", "?y=POINTS", "?y="])
def test_y_unknown_value_is_viewers_and_omitted(
    guarded_page: Page, open_app: OpenApp, query: str
) -> None:
    page = guarded_page
    open_app(page, query)
    assert _state(page)["y"] == "viewers"
    page.evaluate("window.__testHooks.setState({ y: 'bogus' })")
    assert _state(page)["y"] == "viewers"
    page.wait_for_function("!location.search.includes('y=')")


def test_excitement_pair_still_swaps_from_url(guarded_page: Page, open_app: OpenApp) -> None:
    page = guarded_page
    open_app(page, "?axis=excitement&y=excitement")
    state = _state(page)
    assert state["y"] == "excitement"
    assert state["axis"] == "spread"


def test_points_click_keeps_excitement_x_and_persists(
    guarded_page: Page, open_app: OpenApp
) -> None:
    page = guarded_page
    open_app(page, "?axis=excitement&school=northfield,lakeview")
    page.locator('#y-toggle button[data-y="points"]').click()
    page.wait_for_function("location.search.includes('y=points')")
    state = _state(page)
    assert state["y"] == "points"
    assert state["axis"] == "excitement"
    page.locator('#y-toggle button[data-y="margin"]').click()
    page.wait_for_function("location.search.includes('y=margin')")
    pressed = page.locator('#y-toggle button[aria-pressed="true"]')
    assert pressed.count() == 1
    assert pressed.get_attribute("data-y") == "margin"
    page.locator("#tab-bars").click()
    page.wait_for_selector("#bars-title")
    assert "y=margin" in _search(page)
    page.locator("#tab-scatter").click()
    assert "y=margin" in _search(page)
    assert page.locator('#y-toggle button[data-y="margin"]').get_attribute("aria-pressed") == "true"
