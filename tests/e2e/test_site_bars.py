"""The Bars and Butterfly tabs in the real page (SITE-34, SITE-35, SITE-36;
D-01, D-03, D-14, D-18, D-19, D-20).

Hand-worked fixture values: Northfield's five rated telecasts all air on
Alpha Sports (net-a, Disney family), giving announcer rows Dale Harlow 2,
Dale Harlow Jr. 2, Casey Lund 1, ...; Kris Venn works 3 games; Northfield
and Lakeview share 2 games. The Show-all variant is built in-test by
appending synthetic teams to a deep copy of the fixture, never real data.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

OpenApp = Callable[[Page, str], None]

NORTHFIELD = "?school=northfield&view=bars"
FLY = "?school=northfield,lakeview&view=butterfly"


def _bar_boxes(page: Page) -> list[dict[str, float]]:
    """Bounding boxes of every drawn bar point, in DOM order."""
    return page.evaluate(
        """() => Array.from(document.querySelectorAll(
            '#bars-chart .trace.bars .point path'))
            .map(p => { const r = p.getBoundingClientRect();
              return {x: r.x, y: r.y, w: r.width, h: r.height}; })
            .filter(b => b.w > 0 && b.h > 0)"""
    )


def _click_bar(page: Page, index: int = 0) -> None:
    page.mouse.move(2, 2)
    box = _bar_boxes(page)[index]
    page.mouse.click(box["x"] + box["w"] / 2, box["y"] + box["h"] / 2)


def _hover_bar(page: Page, index: int = 0) -> None:
    page.mouse.move(2, 2)
    box = _bar_boxes(page)[index]
    page.mouse.move(box["x"] + box["w"] / 2, box["y"] + box["h"] / 2, steps=4)
    page.wait_for_selector("#chart-tooltip:not([hidden])")


def _state(page: Page) -> dict[str, Any]:
    return page.evaluate("window.__testHooks.getState()")  # type: ignore[no-any-return]


def _tooltip_lines(page: Page) -> list[str]:
    return page.evaluate(
        "Array.from(document.querySelectorAll('#chart-tooltip > *')).map(n => n.textContent)"
    )  # type: ignore[no-any-return]


def _label(page: Page, text: str) -> Any:
    return page.locator("#bars-chart g.annotation-text-g", has_text=text).first


def _bars_text(page: Page) -> str:
    return page.evaluate("document.getElementById('bars-panel').innerText")  # type: ignore[no-any-return]


def _wait_points(page: Page, n: int) -> None:
    page.wait_for_function(
        """n => document.querySelectorAll(
            '#bars-chart .trace.bars .point path').length >= n""",
        arg=n,
    )


# ---------------------------------------------------------------- render


def test_title_names_school_and_drilled_announcer(guarded_page: Page, open_app: OpenApp) -> None:
    """D-21 (notes-7): drilling an announcer keeps the school in the title, and a
    Group-by round trip keeps both."""
    page = guarded_page
    open_app(page, NORTHFIELD)
    title = page.locator("#bars-title")
    assert title.inner_text() == "Announcers by rated telecasts with Northfield"
    _click_bar(page, 0)
    page.wait_for_function("window.__testHooks.getState().people.length === 1")
    both = "with Dale Harlow and Northfield"
    assert title.inner_text() == f"Announcers by rated telecasts {both}"
    aria = page.locator("#bars-chart").get_attribute("aria-label")
    assert aria is not None
    assert aria.startswith(f"Bar chart: announcers by rated telecasts {both}")
    page.locator('#group-by-toggle button[data-group="teams"]').click()
    page.wait_for_function("document.getElementById('bars-title').textContent.startsWith('Teams')")
    assert title.inner_text() == f"Teams by rated telecasts {both}"
    page.locator('#group-by-toggle button[data-group="announcers"]').click()
    page.wait_for_function(
        "document.getElementById('bars-title').textContent.startsWith('Announcers')"
    )
    assert title.inner_text() == f"Announcers by rated telecasts {both}"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (
            "?people=kris-venn,jax-venn&mode=together&view=bars",
            "Teams by rated telecasts with Kris Venn and Jax Venn",
        ),
        (
            "?people=kris-venn,pat-rowan&mode=compare&view=bars",
            "Teams by rated telecasts with Kris Venn or Pat Rowan",
        ),
        (
            "?school=northfield,lakeview&people=dale-harlow&view=butterfly",
            "Announcers: Northfield and Lakeview with Dale Harlow",
        ),
    ],
)
def test_title_joiners_follow_compare_and_together(
    guarded_page: Page, open_app: OpenApp, query: str, expected: str
) -> None:
    open_app(guarded_page, query)
    assert guarded_page.locator("#bars-title").inner_text() == expected


def test_simple_bars_render_title_aria_and_counts(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, NORTHFIELD)
    page = guarded_page
    assert page.locator("#bars-title").inner_text() == (
        "Announcers by rated telecasts with Northfield"
    )
    assert len(_bar_boxes(page)) == 5
    assert page.locator("#bars-chart").get_attribute("aria-label") == (
        "Bar chart: announcers by rated telecasts with Northfield, 2019–2026. "  # noqa: RUF001 - en dash is the real copy
        "Showing 5 of 5. Top: Dale Harlow · PBP 2, Dale Harlow Jr. · Analyst 2, "
        "Casey Lund · PBP 1."
    )
    assert page.locator("#bars-rowcount").inner_text() == "Showing all 5 announcers"
    assert page.locator("#bars-show-all").is_hidden()
    assert page.locator("#bars-captions p").count() == 0
    buttons = page.locator("#bars-counts button")
    assert buttons.count() == 5
    assert buttons.first.get_attribute("aria-label") == (
        "Add Dale Harlow as a filter, 2 rated telecasts"
    )
    assert page.locator("#bars-chart").get_attribute("role") == "img"


def test_stacked_bars_family_row_has_pill_and_segments(
    guarded_page: Page, open_app: OpenApp
) -> None:
    open_app(guarded_page, NORTHFIELD + "&bars=stacked")
    page = guarded_page
    row = page.locator("#bars-counts > li > button").first
    assert row.get_attribute("aria-label") == "Show only ABC/ESPN, 7 rated telecasts"
    assert row.locator('span.pill[data-family="disney"]').count() == 1
    assert page.locator("#bars-counts > li ol button").count() == 5
    assert page.locator("#bars-captions p").count() >= 1


def test_team_bars_for_person_keep_matched_games_table(
    guarded_page: Page, open_app: OpenApp
) -> None:
    open_app(guarded_page, "?people=kris-venn&view=bars")
    page = guarded_page
    assert "Teams by rated telecasts" in page.locator("#bars-title").inner_text()
    assert "Each game counts once for every team" in page.locator("#bars-captions").inner_text()
    assert page.locator("#games-table tbody tr").count() == 3


def test_butterfly_title_caption_and_counts(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, FLY)
    page = guarded_page
    assert page.locator("#bars-title").inner_text() == "Announcers: Northfield and Lakeview"
    assert "2 games include both." in page.locator("#bars-captions").inner_text()
    items = page.locator("#bars-counts > li")
    assert items.count() == 7
    assert items.first.locator("button").text_content() == (
        "Dale Harlow · PBP: Northfield 2, Lakeview 1 rated telecasts"
    )


def test_empty_selection_shows_note(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, "?people=kris-venn,pat-rowan&mode=together&view=bars")
    page = guarded_page
    note = page.locator("#bars-note")
    assert note.is_visible()
    assert note.locator(".season-empty-title").inner_text() == (
        "No rated telecasts for this selection"
    )
    assert note.locator(".season-empty-hint").inner_text() == (
        "Widen the season range or reset a filter."
    )
    assert "hidden" in (page.locator("#bars-chart").evaluate("e => getComputedStyle(e).visibility"))
    for sel in ("#bars-footer", "#bars-captions", "#bars-data"):
        assert page.locator(sel).is_hidden()


def test_legend_toggle_recounts(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, NORTHFIELD)
    page = guarded_page
    chip = page.locator('#legend-chips button[data-family="disney"]')
    chip.click()
    page.wait_for_selector("#bars-note:not([hidden])")
    chip.click()
    page.wait_for_selector("#bars-note", state="hidden")
    _wait_points(page, 5)
    assert len(_bar_boxes(page)) == 5


def _serve_many_teams(page: Page, fixture_raw: dict[str, Any]) -> None:
    raw = copy.deepcopy(fixture_raw)
    base = len(raw["lookups"]["teams"])
    template = copy.deepcopy(raw["lookups"]["teams"][0])
    for n in range(1, 25):
        team = copy.deepcopy(template)
        team["name"] = f"Synthetic Team {n:02d}"
        for key in ("slug", "id"):
            if key in team:
                team[key] = f"synthetic-team-{n:02d}"
        raw["lookups"]["teams"].append(team)
    away = raw["telecasts"]["away_team"]
    home = raw["telecasts"]["home_team"]
    for i in range(len(away)):
        away[i] = base + 2 * i
        home[i] = base + 1 + 2 * i
    page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))


def test_show_all_expands_and_resets(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    _serve_many_teams(guarded_page, fixture_raw)
    open_app(guarded_page, "?networks=net-a,net-b,net-c&view=bars")
    page = guarded_page
    rows = page.evaluate("window.__testHooks.getBarsModel().rows.length")
    assert rows > 15
    assert len(_bar_boxes(page)) == 15
    toggle = page.locator("#bars-show-all")
    assert toggle.inner_text() == f"Show all {rows}"
    assert page.locator("#bars-rowcount").inner_text() == f"Showing top 15 of {rows} teams"
    before = page.url
    toggle.click()
    assert toggle.inner_text() == "Show top 15"
    assert toggle.get_attribute("aria-expanded") == "true"
    assert page.locator("#bars-rowcount").inner_text() == f"Showing all {rows} teams"
    _wait_points(page, rows)
    assert page.url == before
    page.locator('#bar-controls button[data-bars="stacked"]').click()
    page.locator('#bar-controls button[data-bars="simple"]').click()
    assert page.locator("#bars-show-all").inner_text() == f"Show all {rows}"
    assert len(_bar_boxes(page)) == 15


def test_model_hook_has_no_viewers(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, NORTHFIELD)
    model = guarded_page.evaluate("window.__testHooks.getBarsModel()")
    assert "viewers" not in json.dumps(model).lower()


# ---------------------------------------------------------------- drill-in


def test_hover_tooltip_and_click_drill(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, NORTHFIELD)
    page = guarded_page
    _hover_bar(page, 0)
    assert _tooltip_lines(page) == [
        "Dale Harlow · PBP",
        "2 rated telecasts",
        "Click to filter →",
    ]
    assert "viewer" not in page.locator("#chart-tooltip").inner_text().lower()
    page.mouse.move(2, 2)
    _click_bar(page, 0)
    page.wait_for_function("window.__testHooks.getState().people.length === 1")
    assert _state(page)["people"] == ["dale-harlow"]
    assert "people=dale-harlow" in page.url
    assert "view=bars" in page.url
    names = page.evaluate("window.__testHooks.getBarsModel().rows.map(r => [r.name, r.total])")
    assert names[:3] == [["Dale Harlow", 2], ["Dale Harlow Jr.", 2], ["Robin Teague", 1]]


def test_stacked_segment_and_network_label_drill(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, NORTHFIELD + "&bars=stacked")
    page = guarded_page
    _click_bar(page, 0)
    page.wait_for_function("window.__testHooks.getState().people.length === 1")
    open_app(page, NORTHFIELD + "&bars=stacked")
    _label(page, "ABC/ESPN").click()
    page.wait_for_function("window.__testHooks.getState().networks !== null")
    assert "networks=net-a" in page.url


def test_team_bar_click_adds_school_and_keeps_teams(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, "?people=kris-venn&view=bars")
    page = guarded_page
    names = page.evaluate("window.__testHooks.getBarsModel().rows.map(r => r.name)")
    idx = names.index("Foxhollow")
    _click_bar(page, idx)
    page.wait_for_function("window.__testHooks.getState().school.length === 1")
    assert "school=foxhollow" in page.url
    assert "group=teams" in page.url


def test_conference_label_drills_and_non_fbs_does_not(
    guarded_page: Page, open_app: OpenApp
) -> None:
    open_app(guarded_page, "?people=kris-venn&view=bars&bars=stacked")
    page = guarded_page
    _label(page, "SEC").click()
    page.wait_for_function("window.__testHooks.getState().conferences.length === 1")
    assert "conferences=SEC" in page.url

    open_app(
        page,
        "?school=maplecrest&networks=net-d&group=teams&view=bars&bars=stacked",
    )
    before = page.url
    _label(page, "Missouri Valley").click(force=True)
    page.wait_for_timeout(300)
    assert page.url == before
    assert "can't be used as a filter" in page.locator("#bars-captions").inner_text()
    page.locator("#bars-data summary").click()
    row = page.locator("#bars-counts > li", has_text="Missouri Valley").first
    assert row.locator(":scope > button").count() == 0


def test_butterfly_left_bar_adds_announcer(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, FLY)
    page = guarded_page
    _click_bar(page, 0)
    page.wait_for_function("window.__testHooks.getState().people.length === 1")
    state = _state(page)
    assert state["view"] == "butterfly"
    assert state["school"] == ["northfield", "lakeview"]


def test_compare_cap_blocks_drill(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(
        guarded_page,
        "?people=dale-harlow,kris-venn,pat-rowan,casey-lund&mode=compare"
        "&school=northfield&view=bars&group=announcers",
    )
    page = guarded_page
    before = _state(page)["people"]
    names = page.evaluate("window.__testHooks.getBarsModel().rows.map(r => r.target.id)")
    idx = next(i for i, n in enumerate(names) if n not in before)
    _click_bar(page, idx)
    page.wait_for_timeout(300)
    assert _state(page)["people"] == before


def test_reset_and_clear_all_undo_a_drill(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, NORTHFIELD)
    page = guarded_page
    _click_bar(page, 0)
    page.wait_for_function("window.__testHooks.getState().people.length === 1")
    page.click("#trigger-announcers")
    page.locator('.group-reset[data-reset="announcers"]').click()
    page.keyboard.press("Escape")
    page.wait_for_function("window.__testHooks.getState().people.length === 0")
    _click_bar(page, 0)
    page.wait_for_function("window.__testHooks.getState().people.length === 1")
    page.locator("#clear-filters").click()
    page.wait_for_function("window.__testHooks.getState().school.length === 0")
    assert _state(page)["view"] == "bars"
    assert page.locator("#bars-note").is_visible()


def test_keyboard_drill_keeps_focus(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, NORTHFIELD)
    page = guarded_page
    summary = page.locator("#bars-data summary")
    summary.focus()
    page.keyboard.press("Enter")
    page.keyboard.press("Tab")
    page.keyboard.press("Enter")
    page.wait_for_function("window.__testHooks.getState().people.length === 1")
    active = page.evaluate(
        "({tag: document.activeElement.tagName, key: document.activeElement.dataset.key || null})"
    )
    assert active["key"] == "p:dale-harlow" or active["tag"] == "SUMMARY"
    assert page.locator("#bars-data").get_attribute("open") is not None


def test_touch_two_tap_drill(mobile_page: Page, open_app: OpenApp) -> None:
    open_app(mobile_page, NORTHFIELD)
    page = mobile_page
    box = _bar_boxes(page)[0]
    cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
    before = page.url
    page.touchscreen.tap(cx, cy)
    page.wait_for_selector("#chart-tooltip:not([hidden])")
    assert _tooltip_lines(page)[-1] == "Tap again to filter →"
    page.wait_for_timeout(600)
    assert page.url == before
    page.touchscreen.tap(cx, cy)
    page.wait_for_function("window.__testHooks.getState().people.length === 1")


def test_touch_label_tap_drills_immediately(mobile_page: Page, open_app: OpenApp) -> None:
    open_app(mobile_page, NORTHFIELD)
    page = mobile_page
    label = _label(page, "Dale Harlow ·")
    box = label.bounding_box()
    assert box is not None
    page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_function("window.__testHooks.getState().people.length === 1")


# ---------------------------------------------------------------- phone, resize, D-01

PHONE_URLS = [
    NORTHFIELD,
    NORTHFIELD + "&bars=stacked",
    FLY,
    FLY + "&bars=stacked",
]


@pytest.mark.parametrize("query", PHONE_URLS)
def test_phone_no_horizontal_scroll_and_labels_above(
    mobile_page: Page, open_app: OpenApp, query: str
) -> None:
    open_app(mobile_page, query)
    page = mobile_page
    _wait_points(page, 1)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
        "page scrolls horizontally"
    )
    box = page.locator("#bars-chart").bounding_box()
    assert box is not None
    assert box["x"] >= 0
    assert box["x"] + box["width"] <= 390 + 0.5
    overlaps = page.evaluate(
        """() => {
          const bars = Array.from(document.querySelectorAll(
            '#bars-chart .trace.bars .point path'))
            .map(p => p.getBoundingClientRect()).filter(r => r.width > 0 && r.height > 0);
          const labels = Array.from(document.querySelectorAll(
            '#bars-chart g.annotation-text-g')).map(a => a.getBoundingClientRect());
          let n = 0;
          for (const l of labels) for (const b of bars) {
            const ix = Math.min(l.right, b.right) - Math.max(l.left, b.left);
            const iy = Math.min(l.bottom, b.bottom) - Math.max(l.top, b.top);
            if (ix > 1 && iy > 1) n += 1;
          }
          return n;
        }"""
    )
    assert overlaps == 0


def test_phone_touch_targets_are_44px(
    mobile_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    _serve_many_teams(mobile_page, fixture_raw)
    open_app(mobile_page, "?networks=net-a,net-b,net-c&view=bars")
    page = mobile_page
    page.locator("#bars-data summary").click()
    for sel in (".chart-tab", "#bars-show-all", "#bars-counts button", "#bar-controls button"):
        loc = page.locator(sel)
        assert loc.count() > 0, sel
        for i in range(loc.count()):
            if not loc.nth(i).is_visible():
                continue
            box = loc.nth(i).bounding_box()
            assert box is not None
            assert box["height"] >= 43.5, (sel, i, box)
    # D-30: with announcer rows the role and style controls are visible too.
    open_app(page, "?school=northfield&view=bars")
    for sel in ("#bar-role-toggle button", "#bar-style-toggle button"):
        loc = page.locator(sel)
        assert loc.count() > 0, sel
        for i in range(loc.count()):
            assert loc.nth(i).is_visible(), (sel, i)
            box = loc.nth(i).bounding_box()
            assert box is not None
            assert box["height"] >= 43.5 and box["width"] >= 43.5, (sel, i, box)


def test_controls_height_is_stable(mobile_page: Page, open_app: OpenApp) -> None:
    open_app(mobile_page, "?school=northfield&view=scatter")
    page = mobile_page
    h = page.evaluate("document.getElementById('chart-controls').getBoundingClientRect().height")
    page.locator("#tab-bars").click()
    page.wait_for_selector("#bars-title")
    h_bars = page.evaluate(
        "document.getElementById('chart-controls').getBoundingClientRect().height"
    )
    assert abs(h - h_bars) < 1
    page.evaluate("window.__testHooks.setState({networks: ['net-a']})")
    h_net = page.evaluate(
        "document.getElementById('chart-controls').getBoundingClientRect().height"
    )
    assert abs(h - h_net) < 1


def test_desktop_resize_rerenders_butterfly(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, FLY)
    page = guarded_page
    page.set_viewport_size({"width": 1280, "height": 900})
    page.wait_for_timeout(300)
    w1 = page.evaluate("document.getElementById('bars-chart').clientWidth")
    page.set_viewport_size({"width": 900, "height": 900})
    page.wait_for_function(
        """w1 => { const gd = document.getElementById('bars-chart');
          return gd.clientWidth < w1 && gd._fullLayout &&
            Math.abs(gd._fullLayout.width - gd.clientWidth) < 3; }""",
        arg=w1,
        timeout=500,
    )


SCENARIOS = [
    NORTHFIELD,
    NORTHFIELD + "&bars=stacked",
    "?people=kris-venn&view=bars",
    "?people=kris-venn&view=bars&bars=stacked",
    FLY,
    FLY + "&bars=stacked",
    "?people=kris-venn,pat-rowan&mode=together&view=bars",
    "?view=bars",
]


def test_no_viewer_text_and_no_page_errors(guarded_page: Page, open_app: OpenApp) -> None:
    page = guarded_page
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on(
        "console",
        lambda m: errors.append(m.text) if m.type == "error" else None,
    )
    for query in SCENARIOS:
        open_app(page, query)
        assert "viewer" not in _bars_text(page).lower(), query
        assert (
            "viewer" not in (page.locator("#bars-chart").get_attribute("aria-label") or "").lower()
        )
        if page.locator("#bars-chart .trace.bars .point path").count() > 0:
            _hover_bar(page, 0)
            assert "viewer" not in page.locator("#chart-tooltip").inner_text().lower()
    assert errors == []


# ---------------------------------------------------------------- D-23 family bars

FAMILY = NORTHFIELD + "&bars=stacked"
FAMILY_FLY = "?school=northfield,lakeview&view=butterfly&bars=stacked"
FAMILY_URLS = [FAMILY, FAMILY_FLY]
# On the two-channel fixture the first 7 drawn points are channel pieces; the
# overlay announcer segments follow (hover and click resolve on these).
FIRST_SEGMENT = 7


def _hover_segment(page: Page, k: int = 0) -> None:
    page.mouse.move(2, 2)
    box = _bar_boxes(page)[FIRST_SEGMENT + k]
    page.mouse.move(box["x"] + box["w"] / 2, box["y"] + box["h"] / 2, steps=4)
    page.wait_for_selector("#chart-tooltip:not([hidden])")


def _segment_center(page: Page, k: int = 0) -> tuple[float, float]:
    box = _bar_boxes(page)[FIRST_SEGMENT + k]
    return box["x"] + box["w"] / 2, box["y"] + box["h"] / 2


def _computed_shades(page: Page, family: str, n: int) -> list[str]:
    return page.evaluate(  # type: ignore[no-any-return]
        """async ([family, n]) => {
          const P = await import('./modules/palette.js');
          const T = await import('./modules/pill.js');
          return P.channelShades(family, T.currentTheme(), n).map((hex) => {
            const d = document.createElement('div');
            d.style.backgroundColor = hex;
            document.body.appendChild(d);
            const c = getComputedStyle(d).backgroundColor;
            d.remove();
            return c;
          });
        }""",
        [family, n],
    )


def test_family_bars_render_with_channel_counts(
    guarded_page: Page, open_app: OpenApp, serve_multichannel: Callable[..., None]
) -> None:
    page = guarded_page
    serve_multichannel(page)
    open_app(page, FAMILY)
    assert page.locator("#bars-chart g.annotation-text-g", has_text="ABC/ESPN").count() >= 1
    page.locator("#bars-data summary").click()
    row = page.locator("#bars-counts > li").first
    assert row.locator('span.pill[data-family="disney"]').count() == 1
    assert row.locator("> button .counts-n").text_content() == "7"
    assert row.locator("ol.counts-sublist > li > button").all_text_contents() == [
        "Dale Harlow · PBP 2",
        "Dale Harlow Jr. · Analyst 2",
        "Casey Lund · PBP 1",
        "Jamie Oaks · Analyst 1",
        "Robin Teague · Other 1",
    ]
    first = row.locator("ol.counts-sublist > li").first
    assert first.locator("ol.counts-channels > li").all_text_contents() == [
        "Alpha Sports 1",
        "Echo Sports 1",
    ]
    colors = first.locator(".counts-swatch").evaluate_all(
        "els => els.map(e => getComputedStyle(e).backgroundColor)"
    )
    assert colors == _computed_shades(page, "disney", 2)
    assert page.locator("#bars-captions").inner_text().count("Shades within") == 1


def test_family_segment_tooltip_lists_channels(
    guarded_page: Page, open_app: OpenApp, serve_multichannel: Callable[..., None]
) -> None:
    page = guarded_page
    serve_multichannel(page)
    open_app(page, FAMILY)
    _hover_segment(page)
    assert _tooltip_lines(page) == [
        "Dale Harlow · PBP",
        "Alpha Sports: 1",
        "Echo Sports: 1",
        "2 rated telecasts on ABC/ESPN",
        "Click to filter →",
    ]
    assert page.locator("#chart-tooltip .tooltip-swatch").count() == 2
    colors = page.locator("#chart-tooltip .tooltip-swatch").evaluate_all(
        "els => els.map(e => getComputedStyle(e).backgroundColor)"
    )
    assert colors == _computed_shades(page, "disney", 2)


def test_family_label_drill_sets_family_channels(
    guarded_page: Page, open_app: OpenApp, serve_multichannel: Callable[..., None]
) -> None:
    page = guarded_page
    serve_multichannel(page)
    open_app(page, FAMILY)
    _label(page, "ABC/ESPN").click()
    page.wait_for_function("window.__testHooks.getState().networks !== null")
    assert sorted(_state(page)["networks"]) == ["net-a", "net-e"]
    assert "net-a" in page.url
    assert "net-e" in page.url
    page.click("#trigger-networks")
    page.wait_for_function("document.getElementById('pop-networks').matches(':popover-open')")
    only = page.locator(".check-item:has(input[data-family-checkbox='disney']) .only-btn")
    assert only.inner_text().strip() == "All"
    page.locator('.group-reset[data-reset="networks"]').click()
    page.keyboard.press("Escape")
    page.wait_for_function("window.__testHooks.getState().networks === null")


def test_family_segment_click_selects_announcer(
    guarded_page: Page, open_app: OpenApp, serve_multichannel: Callable[..., None]
) -> None:
    page = guarded_page
    serve_multichannel(page)
    open_app(page, FAMILY)
    page.mouse.move(2, 2)
    x, y = _segment_center(page)
    page.mouse.click(x, y)
    page.wait_for_function("window.__testHooks.getState().people.length === 1")
    assert _state(page)["people"] == ["dale-harlow"]


def test_family_butterfly_mirrors_channels(
    guarded_page: Page, open_app: OpenApp, serve_multichannel: Callable[..., None]
) -> None:
    page = guarded_page
    serve_multichannel(page)
    open_app(page, FAMILY_FLY)
    assert (
        page.locator("#bars-title").inner_text()
        == "Network families by announcer: Northfield and Lakeview"
    )
    page.locator("#bars-data summary").click()
    labels = page.locator("#bars-counts > li > button").evaluate_all(
        "els => els.map(e => e.getAttribute('aria-label'))"
    )
    assert labels == [
        "Show only ABC/ESPN, Northfield 7, Lakeview 4 rated telecasts",
        "Show only FOX/FS1/BTN, Northfield 0, Lakeview 2 rated telecasts",
    ]
    side = page.locator("#bars-counts > li").first.locator("ol.counts-sublist").first
    first = side.locator("> li:not(.counts-side)").first
    assert "Dale Harlow" in first.locator("> button").text_content()
    assert first.locator("ol.counts-channels > li").all_text_contents() == [
        "Alpha Sports 1",
        "Echo Sports 1",
    ]


def test_family_touch_two_tap(
    mobile_page: Page, open_app: OpenApp, serve_multichannel: Callable[..., None]
) -> None:
    page = mobile_page
    serve_multichannel(page)
    open_app(page, FAMILY)
    x, y = _segment_center(page)
    page.touchscreen.tap(x, y)
    page.wait_for_selector("#chart-tooltip:not([hidden])")
    lines = _tooltip_lines(page)
    assert "Alpha Sports: 1" in lines
    assert "Echo Sports: 1" in lines
    assert lines[-1] == "Tap again to filter →"
    page.wait_for_timeout(600)
    assert _state(page)["people"] == []
    page.touchscreen.tap(x, y)
    page.wait_for_function("window.__testHooks.getState().people.length === 1")
    assert _state(page)["people"] == ["dale-harlow"]
    open_app(page, FAMILY)
    box = _label(page, "ABC/ESPN").bounding_box()
    assert box is not None
    page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_function("window.__testHooks.getState().networks !== null")


@pytest.mark.parametrize("query", FAMILY_URLS)
def test_family_views_show_no_viewer_text(
    guarded_page: Page,
    open_app: OpenApp,
    serve_multichannel: Callable[..., None],
    query: str,
) -> None:
    page = guarded_page
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    serve_multichannel(page)
    open_app(page, query)
    assert "viewer" not in _bars_text(page).lower()
    page.mouse.move(2, 2)
    box = _bar_boxes(page)[FIRST_SEGMENT if query == FAMILY else -1]
    page.mouse.move(box["x"] + box["w"] / 2, box["y"] + box["h"] / 2, steps=4)
    page.wait_for_selector("#chart-tooltip:not([hidden])")
    assert "viewer" not in page.locator("#chart-tooltip").inner_text().lower()
    assert errors == []
