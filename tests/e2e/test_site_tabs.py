"""Chart tabs, hint row, Bar style / Group-by controls, and the chart panel
(SITE-33; D-10, D-12, D-13, D-14, D-17), proven in the browser against the
12-telecast synthetic fixture.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

BARS_HINT = "Pick a school, network, announcer, or game"
BUTTERFLY_HINT = "Pick exactly two schools or two announcers"
H2H_HINT = "Switch School to Either team to compare two schools"
H2H_URL = "?school=northfield,lakeview&h2h=1"
ONE_SCHOOL = "?school=northfield"
TWO_SUBJECTS = "?school=northfield&networks=net-a"


def _attr(page: Page, selector: str, name: str) -> str | None:
    return page.locator(selector).get_attribute(name)


def _state(page: Page) -> dict[str, Any]:
    return page.evaluate("() => window.__testHooks.getState()")


def _hint(page: Page) -> str:
    return page.locator("#tab-hint").inner_text()


def _box(page: Page, selector: str) -> dict[str, float]:
    box = page.locator(selector).bounding_box()
    assert box is not None, selector
    return box


def _is_concealed(page: Page, selector: str) -> bool:
    return page.evaluate(
        "(s) => getComputedStyle(document.querySelector(s)).visibility === 'hidden'", selector
    )


def test_default_page_has_three_tabs_with_scatter_selected(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    labels = guarded_page.locator("#chart-tabs [role=tab]").all_inner_texts()
    assert labels == ["Scatter", "Bars", "Butterfly"]
    assert _attr(guarded_page, "#tab-scatter", "aria-selected") == "true"
    assert _attr(guarded_page, "#tab-scatter", "tabindex") == "0"
    assert _attr(guarded_page, "#tab-scatter", "aria-disabled") is None
    for tab, hint in (("#tab-bars", BARS_HINT), ("#tab-butterfly", BUTTERFLY_HINT)):
        assert _attr(guarded_page, tab, "aria-disabled") == "true"
        assert _attr(guarded_page, tab, "title") == hint
        assert _attr(guarded_page, tab, "aria-selected") == "false"
    assert _hint(guarded_page) == ""


def test_one_school_enables_bars_only(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, ONE_SCHOOL)
    assert _attr(guarded_page, "#tab-bars", "aria-disabled") is None
    assert _attr(guarded_page, "#tab-butterfly", "aria-disabled") == "true"


def test_clicking_a_disabled_tab_shows_its_hint_without_switching(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, ONE_SCHOOL)
    guarded_page.locator("#tab-butterfly").click(force=True)
    assert _state(guarded_page)["view"] == "scatter"
    assert "view=" not in guarded_page.evaluate("() => location.search")
    assert guarded_page.evaluate("() => document.activeElement.id") == "tab-butterfly"
    assert _hint(guarded_page) == BUTTERFLY_HINT
    guarded_page.keyboard.press("Escape")
    assert _hint(guarded_page) == ""


def test_tablist_keeps_exactly_one_tab_stop_after_render(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """WR-04: focusing a disabled tab, then re-rendering, leaves one tabindex=0."""
    count_js = "() => document.querySelectorAll('#chart-tabs [role=tab][tabindex=\"0\"]').length"
    open_app(guarded_page, ONE_SCHOOL)
    guarded_page.locator("#tab-butterfly").click(force=True)
    guarded_page.evaluate("() => window.__testHooks.setState({ networks: [] })")
    assert guarded_page.evaluate("() => document.activeElement.id") == "tab-butterfly"
    assert guarded_page.evaluate(count_js) == 1
    guarded_page.evaluate("() => document.activeElement.blur()")
    guarded_page.evaluate("() => window.__testHooks.setState({ school: ['northfield'] })")
    assert guarded_page.evaluate(count_js) == 1
    assert _attr(guarded_page, "#tab-scatter", "tabindex") == "0"


def test_hover_and_blur_deliver_and_clear_the_hint(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    guarded_page.locator("#tab-bars").hover()
    assert _hint(guarded_page) == BARS_HINT
    guarded_page.mouse.move(600, 600)
    assert _hint(guarded_page) == ""

    guarded_page.locator("#tab-scatter").focus()
    guarded_page.keyboard.press("ArrowRight")
    assert _hint(guarded_page) == BARS_HINT
    guarded_page.locator("#tab-scatter").focus()
    assert _hint(guarded_page) == ""


def test_any_state_change_clears_the_hint(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    guarded_page.locator("#tab-bars").click(force=True)
    assert _hint(guarded_page) == BARS_HINT
    guarded_page.evaluate("() => window.__testHooks.setState({ axis: 'excitement' })")
    assert _hint(guarded_page) == ""


def test_clicking_an_enabled_tab_selects_it_and_updates_the_url(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, ONE_SCHOOL)
    guarded_page.locator("#tab-bars").click()
    assert _state(guarded_page)["view"] == "bars"
    assert "view=bars" in guarded_page.evaluate("() => location.search")
    assert _attr(guarded_page, "#tab-bars", "aria-selected") == "true"
    assert _attr(guarded_page, "#tab-bars", "tabindex") == "0"
    assert _attr(guarded_page, "#tab-scatter", "tabindex") == "-1"
    assert guarded_page.evaluate("() => document.activeElement.id") == "tab-bars"


def test_keyboard_navigation_is_roving_with_manual_activation(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, ONE_SCHOOL)
    active = "() => document.activeElement.id"
    guarded_page.locator("#tab-scatter").focus()
    guarded_page.keyboard.press("ArrowRight")
    assert guarded_page.evaluate(active) == "tab-bars"
    assert _state(guarded_page)["view"] == "scatter"
    guarded_page.keyboard.press("End")
    assert guarded_page.evaluate(active) == "tab-butterfly"
    guarded_page.keyboard.press("Home")
    assert guarded_page.evaluate(active) == "tab-scatter"
    guarded_page.keyboard.press("ArrowLeft")
    assert guarded_page.evaluate(active) == "tab-butterfly"
    guarded_page.keyboard.press("ArrowLeft")
    assert guarded_page.evaluate(active) == "tab-bars"
    guarded_page.keyboard.press("Enter")
    assert _state(guarded_page)["view"] == "bars"
    assert guarded_page.evaluate(active) == "tab-bars"
    guarded_page.keyboard.press("Home")
    guarded_page.keyboard.press("Space")
    assert _state(guarded_page)["view"] == "scatter"


def test_bar_controls_replace_the_axis_toggle_without_shifting_layout(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?school=northfield,lakeview")
    assert _is_concealed(guarded_page, "#bar-controls")
    assert not _is_concealed(guarded_page, "#axis-toggle")
    assert not _is_concealed(guarded_page, "#y-toggle")
    axis_before = _box(guarded_page, "#axis-toggle")

    guarded_page.locator("#tab-bars").click()
    assert not _is_concealed(guarded_page, "#bar-controls")
    assert _is_concealed(guarded_page, "#axis-toggle")
    assert _is_concealed(guarded_page, "#y-toggle")
    assert _box(guarded_page, "#axis-toggle")["height"] == axis_before["height"]
    guarded_page.locator("#tab-butterfly").click()
    assert _is_concealed(guarded_page, "#axis-toggle")
    assert _is_concealed(guarded_page, "#y-toggle")
    guarded_page.locator("#tab-bars").click()
    assert not _is_concealed(guarded_page, "#group-by-toggle")

    guarded_page.locator('#group-by-toggle button[data-by="network"]').click()
    assert "by=network" in guarded_page.evaluate("() => location.search")
    assert _attr(guarded_page, '#group-by-toggle button[data-by="network"]', "aria-pressed") == (
        "true"
    )
    assert _attr(guarded_page, '#group-by-toggle button[data-by="announcer"]', "aria-pressed") == (
        "false"
    )


def test_group_by_shows_with_two_subjects_and_drives_the_url(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, TWO_SUBJECTS + "&view=bars")
    assert not _is_concealed(guarded_page, "#group-by-toggle")
    announcers = '#group-by-toggle button[data-by="announcer"]'
    assert _attr(guarded_page, announcers, "aria-pressed") == "true"
    guarded_page.locator('#group-by-toggle button[data-by="team"]').click()
    assert "by=team" in guarded_page.evaluate("() => location.search")
    guarded_page.locator(announcers).click()
    assert "by=" not in guarded_page.evaluate("() => location.search")


def test_scatter_tab_shows_axis_toggle_and_conceals_bar_controls(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    assert not _is_concealed(guarded_page, "#axis-toggle")
    assert _is_concealed(guarded_page, "#bar-controls")


# --- Task 3: chart panel branching ----------------------------------------


def _visible(page: Page, selector: str) -> bool:
    return page.locator(selector).is_visible()


def test_stale_bars_tab_stays_selected_and_shows_the_note(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?view=bars")
    assert _attr(guarded_page, "#tab-bars", "aria-selected") == "true"
    assert _attr(guarded_page, "#tab-bars", "aria-disabled") == "true"
    assert not _visible(guarded_page, "#chart")
    assert _visible(guarded_page, "#bars-panel")
    assert _visible(guarded_page, "#bars-note")
    assert guarded_page.locator("#bars-note .season-empty-title").inner_text() == BARS_HINT
    assert guarded_page.locator("#bars-note .season-empty-hint").inner_text() == (
        "Pick a school or a game, narrow Networks, or select an announcer to see counts."
    )
    for selector in ("#bars-title", "#bars-footer", "#bars-captions", "#bars-data"):
        assert not _visible(guarded_page, selector), selector
    assert "view=bars" in guarded_page.evaluate("() => location.search")
    assert _box(guarded_page, "#bars-chart-box")["height"] >= 520


def test_restoring_the_filter_brings_the_bars_panel_back(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?view=bars")
    guarded_page.evaluate("() => window.__testHooks.setState({ school: ['northfield'] })")
    assert not _visible(guarded_page, "#bars-note")
    assert guarded_page.locator("#bars-title").evaluate("e => !e.hidden")
    assert guarded_page.locator("#bars-footer").evaluate("e => !e.hidden")
    assert guarded_page.locator("#bars-captions").evaluate("e => !e.hidden")
    assert guarded_page.locator("#bars-data").evaluate("e => !e.hidden")
    guarded_page.evaluate("() => window.__testHooks.setState({ school: [] })")
    assert _visible(guarded_page, "#bars-note")
    assert _attr(guarded_page, "#tab-bars", "aria-selected") == "true"


def test_stale_butterfly_copy(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    open_app(guarded_page, "?view=butterfly&school=northfield")
    assert guarded_page.locator("#bars-note .season-empty-title").inner_text() == BUTTERFLY_HINT
    assert guarded_page.locator("#bars-note .season-empty-hint").inner_text() == (
        "Select two schools or two announcers to compare them."
    )


def test_tab_switching_never_shifts_the_chart_chrome(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?school=northfield,lakeview")
    before = {s: _box(guarded_page, s) for s in ("#legend-chips", "#chart-controls", "#tab-hint")}
    for view in ("bars", "butterfly", "scatter"):
        guarded_page.locator(f"#tab-{view}").click()
        assert _state(guarded_page)["view"] == view
        for selector, box in before.items():
            now = _box(guarded_page, selector)
            assert now["y"] == box["y"], (view, selector)
            assert now["height"] == box["height"], (view, selector)
    guarded_page.locator("#tab-bars").click()
    assert _box(guarded_page, "#bars-chart-box")["height"] >= 520


def test_scatter_works_after_first_loading_on_a_bar_tab(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, ONE_SCHOOL + "&view=bars")
    guarded_page.locator("#tab-scatter").click()
    assert _visible(guarded_page, "#chart")
    guarded_page.wait_for_function("() => document.querySelector('#chart .main-svg')")
    widths = guarded_page.evaluate(
        "() => ({svg: document.querySelector('#chart .main-svg').getBoundingClientRect().width,"
        " box: document.getElementById('chart').clientWidth})"
    )
    assert abs(widths["svg"] - widths["box"]) <= 1

    guarded_page.locator("#chart").scroll_into_view_if_needed()
    point = guarded_page.evaluate(
        """() => {
          const gd = document.getElementById('chart');
          const layout = gd._fullLayout;
          const rect = gd.getBoundingClientRect();
          for (const t of gd.data) {
            if (!t.customdata) continue;
            return {
              x: rect.left + layout._size.l + layout.xaxis.d2p(t.x[0]),
              y: rect.top + layout._size.t + layout.yaxis.d2p(t.y[0]),
            };
          }
          return null;
        }"""
    )
    assert point is not None
    guarded_page.mouse.move(5, 5)
    guarded_page.mouse.move(point["x"], point["y"])
    guarded_page.wait_for_selector("#chart-tooltip:not([hidden])", timeout=5000)


def test_scatter_only_captions_hide_on_bar_tabs(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, ONE_SCHOOL + "&axis=excitement")
    assert _visible(guarded_page, "#excitement-caption")
    assert _visible(guarded_page, "#era-note")
    guarded_page.locator("#tab-bars").click()
    for selector in ("#excitement-caption", "#era-note", "#shape-legend"):
        assert not _visible(guarded_page, selector), selector
    assert "axis=excitement" in guarded_page.evaluate("() => location.search")
    guarded_page.locator("#tab-scatter").click()
    assert _visible(guarded_page, "#excitement-caption")
    assert _visible(guarded_page, "#era-note")


def test_resizing_on_the_bars_tab_raises_no_errors(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    errors: list[str] = []
    guarded_page.on("pageerror", lambda exc: errors.append(str(exc)))
    guarded_page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    open_app(guarded_page, ONE_SCHOOL + "&view=bars")
    for width in (800, 1280):
        guarded_page.set_viewport_size({"width": width, "height": 800})
        guarded_page.wait_for_timeout(200)
    assert errors == []


# --- D-22: one baseline and height across the controls row -----------------

BAR_VIEW = "?school=northfield&networks=net-a&view=bars"
FLY_VIEW = "?school=northfield,lakeview&people=kris-venn,pat-rowan&view=butterfly"
VIEWPORTS = [("guarded_page", 1280), ("guarded_page", 800), ("mobile_page", 390)]

_ROW_METRICS_JS = """() => {
  const segs = Array.from(document.querySelectorAll('#bar-controls .segmented'))
    .filter((s) => getComputedStyle(s).visibility !== 'hidden');
  // Bottom of the first rendered text run. A range over an element's contents
  // would also count an inline-grid wrapper's line box (the style buttons), whose
  // bottom differs from a bare text run's by the font's own metrics, so it is not
  // a baseline measure; a text node's bottom is baseline + descent in one font.
  const textBottom = (el) => {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (n.parentElement.closest('.is-concealed') || !n.data.trim())
        ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
    });
    const r = document.createRange();
    r.selectNodeContents(walker.nextNode());
    return r.getBoundingClientRect().bottom;
  };
  return {
    segs: segs.map((s) => {
      const b = s.getBoundingClientRect();
      return {
        top: b.top, height: b.height,
        texts: Array.from(s.querySelectorAll('button')).map(textBottom),
      };
    }),
  };
}"""


def _viewport_page(request: pytest.FixtureRequest, fixture: str, width: int) -> Page:
    page: Page = request.getfixturevalue(fixture)
    if fixture == "guarded_page":
        page.set_viewport_size({"width": width, "height": 900})
    return page


@pytest.mark.usefixtures("font_setting")
# No `wide` here: its letter-spacing deliberately overflows the one-line row at 800.
@pytest.mark.parametrize("font_setting", ["default", "dejavu"], indirect=True)
@pytest.mark.parametrize(("fixture", "width"), VIEWPORTS)
@pytest.mark.parametrize("query", [BAR_VIEW, FLY_VIEW])
def test_bar_controls_share_one_baseline_and_height(
    request: pytest.FixtureRequest,
    open_app: Callable[[Page, str], None],
    fixture: str,
    width: int,
    query: str,
) -> None:
    page = _viewport_page(request, fixture, width)
    open_app(page, query)
    assert not _is_concealed(page, "#group-by-toggle")
    m = page.evaluate(_ROW_METRICS_JS)
    segs = m["segs"]
    assert segs
    assert max(s["height"] for s in segs) - min(s["height"] for s in segs) <= 0.5
    lines: list[list[dict[str, Any]]] = []
    for seg in sorted(segs, key=lambda s: s["top"]):
        if lines and abs(lines[-1][0]["top"] - seg["top"]) <= 2:
            lines[-1].append(seg)
        else:
            lines.append([seg])
    # D-31's locked labels need 423px on the first line; 343px are available at 390.
    assert len(lines) == 1 if width >= 800 else len(lines) <= 3
    for line in lines:
        assert max(s["top"] for s in line) - min(s["top"] for s in line) <= 0.5
        bottoms = [b for s in line for b in s["texts"]]
        assert max(bottoms) - min(bottoms) <= 1, bottoms


_FOOTPRINT_JS = """() => document.getElementById('chart-panel').getBoundingClientRect().top
  - document.getElementById('chart-controls').getBoundingClientRect().top"""


@pytest.mark.parametrize(("fixture", "width"), VIEWPORTS)
def test_controls_footprint_is_fixed(
    request: pytest.FixtureRequest,
    open_app: Callable[[Page, str], None],
    fixture: str,
    width: int,
) -> None:
    page = _viewport_page(request, fixture, width)
    values: dict[str, float] = {}
    for name, query in (
        ("scatter", "?school=northfield"),
        ("bars", "?school=northfield&view=bars"),
        ("bars-group", BAR_VIEW),
        ("butterfly", FLY_VIEW),
        ("bars-team-rows", "?people=kris-venn&view=bars"),
        ("bars-group-teams", BAR_VIEW + "&by=team"),
        ("fly-announcers", "?people=kris-venn,pat-rowan&view=butterfly"),
    ):
        open_app(page, query)
        values[name] = page.evaluate(_FOOTPRINT_JS)
    assert max(values.values()) - min(values.values()) <= 1, values


# --- D-25: Both | PBP | Analyst control, one state with the Role filter ------

_ROWS_JS = "window.__testHooks.getBarsModel().rows.map(r => [r.label, r.total])"
_ROLE_PRESSED_JS = """() => Array.from(document.querySelectorAll('#bar-role-toggle button'))
  .map((b) => [b.textContent, b.getAttribute('aria-pressed')])"""
# pbp by total games: Dale Harlow 2, then 1-game ties by name
# (Casey Lund, Kris Venn, Pat Rowan come from unrated games)
PBP_ROWS = [["Dale Harlow", 2], ["Casey Lund", 1], ["Kris Venn", 1], ["Pat Rowan", 1]]
# analyst by total games: Jr. 2, then 1-game ties by name
# (Morgan Ash and Sam Delgado come from unrated games)
ANALYST_ROWS = [["Dale Harlow Jr.", 2], ["Jamie Oaks", 1], ["Morgan Ash", 1], ["Sam Delgado", 1]]


def test_role_control_sets_state_url_and_role_filter(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    page = guarded_page
    open_app(page, ONE_SCHOOL + "&view=bars")
    assert _attr(page, '#bar-role-toggle button[data-role=""]', "aria-pressed") == "true"
    assert len(page.evaluate(_ROWS_JS)) == 9  # 5 rated-game announcers + 4 more on unrated games
    page.locator('#bar-role-toggle button[data-role="pbp"]').click()
    assert _state(page)["role"] == "pbp"
    assert "role=pbp" in page.evaluate("() => location.search")
    assert page.evaluate(
        "() => document.querySelector('#filter-role input[value=\"pbp\"]').checked"
    )
    assert page.evaluate(_ROWS_JS) == PBP_ROWS
    page.locator('#bar-role-toggle button[data-role=""]').click()
    assert _state(page)["role"] is None
    assert "role=" not in page.evaluate("() => location.search")
    assert len(page.evaluate(_ROWS_JS)) == 9  # 5 rated-game announcers + 4 more on unrated games


def test_role_filter_popover_drives_the_role_control(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    page = guarded_page
    open_app(page, ONE_SCHOOL + "&view=bars")
    page.click("#trigger-role")
    page.locator('#filter-role input[value="analyst"]').check()
    assert _state(page)["role"] == "analyst"
    assert page.evaluate(_ROLE_PRESSED_JS) == [
        ["Both", "false"],
        ["PBP", "false"],
        ["Analyst", "true"],
    ]
    assert page.evaluate(_ROWS_JS) == ANALYST_ROWS


def test_role_control_from_url_and_on_butterfly(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    page = guarded_page
    open_app(page, ONE_SCHOOL + "&view=bars&role=analyst")
    assert page.evaluate(_ROLE_PRESSED_JS)[2] == ["Analyst", "true"]
    open_app(page, "?school=northfield,lakeview&view=butterfly")
    assert not _is_concealed(page, "#bar-role-toggle")
    page.locator('#bar-role-toggle button[data-role="pbp"]').click()
    assert _state(page)["role"] == "pbp"
    # D-30 refines D-25: team rows hide the control.
    open_app(page, "?people=kris-venn,pat-rowan&view=butterfly")
    assert _is_concealed(page, "#bar-role-toggle")
    open_app(page, "")
    assert _is_concealed(page, "#bar-role-toggle")


def test_role_control_is_keyboard_operable(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    page = guarded_page
    open_app(page, ONE_SCHOOL + "&view=bars")
    page.locator('#bar-role-toggle button[data-role=""]').focus()
    page.keyboard.press("Tab")
    page.keyboard.press("Enter")
    assert _state(page)["role"] == "pbp"


def test_role_limits_selected_announcer_games(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?people=dale-harlow&view=bars&role=analyst")
    assert guarded_page.locator("#bars-note").is_visible()


# --- D-31: contextual bar-style labels ---------------------------------------

BY_LABELS = {
    "announcer": "by Announcer",
    "network": "by Network",
    "team": "by Team",
    "conference": "by Conference",
}
ANNOUNCER_OPTIONS = ["announcer", "network"]
TEAM_OPTIONS = ["team", "conference"]


def test_by_label_constants(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    open_app(guarded_page, ONE_SCHOOL + "&view=bars")
    got = guarded_page.evaluate(
        """async () => {
          const m = await import('./modules/bar-copy.js');
          return m.BY_LABELS;
        }"""
    )
    assert got == {
        "announcer": "by Announcer",
        "network": "by Network",
        "team": "by Team",
        "conference": "by Conference",
    }
    sizer = guarded_page.evaluate(
        "() => Array.from(document.querySelectorAll('#group-by-toggle .by-sizer > span'))"
        ".map((s) => s.textContent)"
    )
    assert sorted(sizer) == sorted(got.values())


@pytest.mark.parametrize(
    ("query", "options"),
    [
        ("?school=northfield&view=bars", ANNOUNCER_OPTIONS),
        ("?school=northfield&view=bars&by=network", ANNOUNCER_OPTIONS),
        ("?people=kris-venn&view=bars", TEAM_OPTIONS),
        ("?networks=net-a&view=bars", TEAM_OPTIONS),
        (TWO_SUBJECTS + "&view=bars", [*ANNOUNCER_OPTIONS, *TEAM_OPTIONS]),
        (TWO_SUBJECTS + "&view=bars&by=team", [*ANNOUNCER_OPTIONS, *TEAM_OPTIONS]),
        ("?school=northfield,lakeview&view=butterfly", ANNOUNCER_OPTIONS),
        ("?people=kris-venn,pat-rowan&view=butterfly", TEAM_OPTIONS),
    ],
)
def test_by_options_follow_the_rows(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    query: str,
    options: list[str],
) -> None:
    open_app(guarded_page, query)
    shown = guarded_page.evaluate(
        "() => Array.from(document.querySelectorAll('#group-by-toggle button:not([hidden])'))"
        ".map((b) => b.dataset.by)"
    )
    assert shown == options
    for by in options:
        named = guarded_page.get_by_role("button", name=BY_LABELS[by], exact=True)
        assert named.count() == 1
        assert named.get_attribute("data-by") == by


def test_by_url_values(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    page = guarded_page
    open_app(page, "?people=kris-venn&view=bars")
    page.get_by_role("button", name="by Conference", exact=True).click()
    assert _state(page)["by"] == "conference"
    assert "by=conference" in page.evaluate("() => location.search")
    assert page.evaluate("() => window.__testHooks.getBarsModel().rowKind") == "conference"
    page.get_by_role("button", name="by Team", exact=True).click()
    assert "by=" not in page.evaluate("() => location.search")


@pytest.mark.parametrize(("fixture", "width"), VIEWPORTS[:2])
def test_by_labels_do_not_shift_the_row(
    request: pytest.FixtureRequest,
    open_app: Callable[[Page, str], None],
    fixture: str,
    width: int,
) -> None:
    page = _viewport_page(request, fixture, width)
    open_app(page, BAR_VIEW)
    selectors = ("#group-by-toggle", "#bar-role-toggle")

    def record() -> list[float]:
        out: list[float] = []
        for sel in selectors:
            box = _box(page, sel)
            out += [box["x"], box["width"]]
        return out

    before = record()
    page.locator('#group-by-toggle button[data-by="team"]').click()
    after = record()
    assert all(abs(a - b) <= 0.5 for a, b in zip(before, after, strict=True)), (before, after)


# --- D-30: role control only when announcers are the rows --------------------

_ROLE_VISIBLE = [
    "?school=northfield&view=bars",
    "?school=northfield&view=bars&by=network",
    TWO_SUBJECTS + "&view=bars",
    "?school=northfield,lakeview&view=butterfly",
    "?school=northfield,lakeview&view=butterfly&by=network",
    FLY_VIEW,
]
_ROLE_CONCEALED = [
    "?people=kris-venn&view=bars",
    "?people=kris-venn&view=bars&by=conference",
    "?networks=net-a&view=bars",
    TWO_SUBJECTS + "&view=bars&by=team",
    "?people=kris-venn,pat-rowan&view=butterfly",
    FLY_VIEW + "&by=team",
]


@pytest.mark.parametrize(
    ("query", "concealed"),
    [(q, False) for q in _ROLE_VISIBLE] + [(q, True) for q in _ROLE_CONCEALED],
)
def test_role_control_shows_only_for_announcer_rows(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    query: str,
    concealed: bool,
) -> None:
    open_app(guarded_page, query)
    assert _is_concealed(guarded_page, "#bar-role-toggle") is concealed


def test_role_control_follows_group_by(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    page = guarded_page
    open_app(page, TWO_SUBJECTS + "&view=bars")
    height = _box(page, "#bar-controls")["height"]
    page.locator('#group-by-toggle button[data-by="team"]').click()
    assert _is_concealed(page, "#bar-role-toggle")
    assert _box(page, "#bar-controls")["height"] == height
    page.locator('#group-by-toggle button[data-by="announcer"]').click()
    assert not _is_concealed(page, "#bar-role-toggle")
    assert _box(page, "#bar-controls")["height"] == height


def test_concealed_role_control_is_out_of_tab_order(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    page = guarded_page
    open_app(page, TWO_SUBJECTS + "&view=bars&by=team")
    page.locator('#group-by-toggle button[data-by="network"]').focus()
    page.keyboard.press("Tab")
    assert page.evaluate("() => !!document.activeElement.closest('#bar-role-toggle')") is False
    assert page.evaluate("() => !!document.activeElement.closest('#group-by-toggle')") is True


def test_hidden_role_control_keeps_the_role(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    page = guarded_page
    open_app(page, "?people=dale-harlow&view=bars&role=pbp")
    assert _is_concealed(page, "#bar-role-toggle")
    assert "role=pbp" in page.evaluate("() => location.search")
    assert _state(page)["role"] == "pbp"
    assert "Role:" in page.locator("#trigger-role").inner_text()
    page.click("#trigger-role")
    page.locator('#filter-role input[value="analyst"]').check()
    assert _state(page)["role"] == "analyst"
    assert page.locator("#bars-note").is_visible()


def test_head_to_head_disables_the_school_butterfly_with_its_hint(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, H2H_URL)
    assert _attr(guarded_page, "#tab-butterfly", "aria-disabled") == "true"
    assert _attr(guarded_page, "#tab-butterfly", "title") == H2H_HINT
    assert _attr(guarded_page, "#tab-bars", "aria-disabled") is None


def test_head_to_head_hint_shows_on_hover_focus_and_click(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, H2H_URL)
    guarded_page.locator("#tab-butterfly").hover()
    assert _hint(guarded_page) == H2H_HINT
    guarded_page.mouse.move(600, 600)
    assert _hint(guarded_page) == ""
    guarded_page.locator("#tab-butterfly").focus()
    assert _hint(guarded_page) == H2H_HINT
    guarded_page.locator("#tab-scatter").focus()
    guarded_page.locator("#tab-butterfly").click(force=True)
    assert _hint(guarded_page) == H2H_HINT
    assert _attr(guarded_page, "#tab-butterfly", "aria-selected") == "false"
    assert _state(guarded_page)["view"] == "scatter"


def test_two_announcers_keep_the_butterfly_under_head_to_head(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, f"{H2H_URL}&people=dale-harlow,casey-lund")
    assert _attr(guarded_page, "#tab-butterfly", "aria-disabled") is None
    guarded_page.locator("#tab-butterfly").click()
    assert _state(guarded_page)["view"] == "butterfly"
    assert _attr(guarded_page, "#tab-butterfly", "aria-selected") == "true"


def test_legacy_butterfly_hint_is_unchanged_without_head_to_head(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, ONE_SCHOOL)
    assert _attr(guarded_page, "#tab-butterfly", "title") == BUTTERFLY_HINT


def test_stale_copy_is_state_aware(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    out = guarded_page.evaluate(
        """async () => {
          const T = await import('./modules/chart-tabs.js');
          const two = ['northfield', 'lakeview'];
          return {
            h2h: T.staleCopy({ view: 'butterfly', school: two, h2h: true, people: [] }),
            plain: T.staleCopy({ view: 'butterfly', school: [], h2h: false, people: [] }),
            bars: T.staleCopy({ view: 'bars', school: two, h2h: true, people: [] }),
            stale: T.STALE_COPY,
          };
        }"""
    )
    assert out["h2h"] == {
        "title": H2H_HINT,
        "hint": (
            "Head-to-head keeps only the games between the two schools. "
            "Select two announcers to compare them in these games."
        ),
    }
    assert out["plain"] == out["stale"]["butterfly"]
    assert out["bars"] == out["stale"]["bars"]
