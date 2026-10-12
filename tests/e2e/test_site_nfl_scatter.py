# ruff: noqa: E501  (embedded JS lines and the UI copy's typographic characters)
"""999.5-16: NFL view 4, Game scatter.

Synthetic nfl-data fixture only; no vault rows. Expected values are recomputed
from the fixture's `games` block.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from itertools import pairwise
from typing import Any

import pytest
from playwright.sync_api import Page, Route

pytestmark = pytest.mark.e2e

VIEW = "#nfl-view-scatter"
GD = f"{VIEW} .nfl-chart > div"
CAUSES = ("pending", "regional", "none")


def _open(page: Page, open_nfl_app: Callable[..., None], query: str = "") -> None:
    open_nfl_app(page, "?sport=nfl&view=scatter" + query)


def _vm(page: Page) -> dict[str, Any]:
    page.wait_for_function("window.__nflTestHooks.getViewModel('scatter').drawn === true")
    return page.evaluate("window.__nflTestHooks.getViewModel('scatter')")  # type: ignore[no-any-return]


def _set(page: Page, patch: dict[str, Any]) -> None:
    page.evaluate("p => window.__nflTestHooks.setState(p)", patch)


def _g(raw: dict[str, Any]) -> dict[str, list[Any]]:
    return raw["games"]  # type: ignore[no-any-return]


def _emit(page: Page, event: str, i: int) -> None:
    page.evaluate(
        """([ev, i, sel]) => {
          const gd = document.querySelector(sel);
          gd.emit(ev, { points: [{ customdata: i }], event: { clientX: 300, clientY: 200 } });
        }""",
        [event, i, GD],
    )


def _tooltip(page: Page) -> list[str]:
    page.wait_for_function("!document.getElementById('chart-tooltip').hidden")
    return page.evaluate(  # type: ignore[no-any-return]
        "Array.from(document.getElementById('chart-tooltip').children).map(c => c.textContent)"
    )


def _panel_open(page: Page) -> bool:
    return page.evaluate("document.getElementById('nfl-detail-panel').open")  # type: ignore[no-any-return]


# --------------------------------------------------------------- task 1


def test_plots_every_game_with_unrated_band(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    vm = _vm(nfl_guarded_page)
    g = _g(nfl_fixture_raw)
    n = len(g["season"])
    null_viewers = sum(v is None for v in g["viewers"])
    assert vm["counts"]["plotted"] + vm["counts"]["band"] == n
    assert vm["counts"]["band"] == null_viewers
    assert vm["yType"] == "log"
    assert vm["axisTitles"]["y"] == "Viewers"
    assert vm["dateAxis"] == "reused"
    for cause in CAUSES:
        want = sum(
            1 for v, c in zip(g["viewers"], g["cause"], strict=True) if v is None and c == cause
        )
        assert vm["bandCauses"][cause] == want
    assert sum(vm["bandCauses"].values()) == null_viewers
    # Nothing missing is plotted: every band item has no viewer figure.
    banded = {it["i"] for it in vm["items"] if it["band"]}
    assert banded == {i for i, v in enumerate(g["viewers"]) if v is None}
    # The log axis keeps its exact tick labels.
    nfl_guarded_page.wait_for_selector(f"{GD} .ytick text", state="attached")
    ticks = nfl_guarded_page.evaluate(
        f"Array.from(document.querySelectorAll('{GD} .ytick text')).map(t => t.textContent)"
    )
    assert ticks
    assert set(ticks) <= {"500K", "1M", "2M", "5M", "10M", "20M"}
    assert nfl_guarded_page.locator(f"{GD} svg").count() >= 1
    assert nfl_guarded_page.locator(f"{GD} canvas").count() == 0  # svg scatter, never scattergl


def test_excitement_mode_moves_only_null_excitement_to_band(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app, "&y=excitement")
    vm = _vm(nfl_guarded_page)
    g = _g(nfl_fixture_raw)
    null_exc = {i for i, v in enumerate(g["excitement"]) if v is None}
    assert vm["y"] == "excitement"
    assert vm["yType"] == "linear"
    assert vm["axisTitles"]["y"] == "GEI-style excitement"
    assert vm["counts"]["band"] == len(null_exc)
    assert {it["i"] for it in vm["items"] if it["band"]} == null_exc
    assert vm["counts"]["plotted"] + vm["counts"]["band"] == len(g["season"])
    btn = nfl_guarded_page.locator(f"{VIEW} .band-info")
    assert btn.inner_text().replace("\ni", "").strip().startswith("No excitement value")
    assert btn.get_attribute("aria-label") == "Why do some games have no excitement value?"


def test_margin_axis_and_na_strip(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app, "&x=margin")
    vm = _vm(nfl_guarded_page)
    g = _g(nfl_fixture_raw)
    null_margin = {i for i, m in enumerate(g["final_margin"]) if m is None}
    assert null_margin
    assert vm["axisTitles"]["x"] == "Final margin (points)"
    assert {it["i"] for it in vm["items"] if it["na"]} == null_margin
    assert vm["counts"]["naStrip"] == len(null_margin)
    # No game is dropped.
    assert len(vm["items"]) == len(g["season"])
    title = nfl_guarded_page.locator(f"{GD} .g-xtitle").text_content()
    assert title == "Final margin (points)"


def test_team_filter_fades_and_hide_removes(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    g = _g(nfl_fixture_raw)
    fid = nfl_fixture_raw["lookups"]["franchises"][0]["id"]
    _set(nfl_guarded_page, {"teams": [fid]})
    n = len(g["season"])
    matching = sum(1 for i in range(n) if g["home"][i] == 0 or g["away"][i] == 0)
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('scatter').counts.faded > 0"
    )
    vm = _vm(nfl_guarded_page)
    assert vm["counts"]["faded"] == n - matching
    assert vm["counts"]["plotted"] + vm["counts"]["band"] == n
    _set(nfl_guarded_page, {"dots": "hide"})
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('scatter').counts.hidden > 0"
    )
    vm = _vm(nfl_guarded_page)
    assert vm["counts"]["hidden"] == n - matching
    assert vm["counts"]["faded"] == 0
    assert vm["counts"]["plotted"] + vm["counts"]["band"] == matching


def test_announcer_highlight_count(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    g = _g(nfl_fixture_raw)
    people = nfl_fixture_raw["lookups"]["people"]
    pid = people[0]["id"]  # person index 0
    want = sum(1 for crew in g["crew"] if any(m["person"] == 0 for m in crew))
    assert want > 0
    _set(nfl_guarded_page, {"people": [pid]})
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('scatter').counts.highlighted > 0"
    )
    vm = _vm(nfl_guarded_page)
    assert vm["counts"]["highlighted"] == want
    assert vm["counts"]["faded"] == 0


def test_legend_chip_hides_a_category(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    chips = nfl_guarded_page.locator(f"{VIEW} .legend-chip")
    assert chips.all_inner_texts() == [
        "Standalone slot",
        "AGOTW",
        "CBS national",
        "International (not standalone)",
        "Other games",
    ]
    before = _vm(nfl_guarded_page)
    in_agotw = sum(1 for it in before["items"] if it["category"] == "agotw")
    assert in_agotw > 0
    chips.nth(1).click()
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('scatter').hiddenCategories.length === 1"
    )
    after = _vm(nfl_guarded_page)
    assert after["hiddenCategories"] == ["agotw"]
    assert all(it["category"] != "agotw" for it in after["items"])
    assert len(after["items"]) == len(before["items"]) - in_agotw
    assert chips.nth(1).get_attribute("aria-pressed") == "false"
    chips.nth(1).click()  # restore for later tests in this page
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('scatter').hiddenCategories.length === 0"
    )


def test_band_note_text_and_links_exact(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    _vm(nfl_guarded_page)
    btn = nfl_guarded_page.locator(f"{VIEW} .band-info")
    note = nfl_guarded_page.locator(f"{VIEW} .band-note")
    assert btn.is_visible()
    assert btn.get_attribute("aria-label") == "Why do some games have no public rating?"
    assert note.is_hidden()
    btn.click()
    assert note.is_visible()
    shown = nfl_guarded_page.locator(f"{VIEW} .band-note > div:not([hidden])")
    assert shown.locator("p").all_inner_texts() == [
        "No public rating",
        "We found no published viewer count for these games. The reason is shown for each game. The most common ones:",
        "How we count games",
    ]
    assert shown.locator("li").all_inner_texts() == [
        "Ratings Reference compiles national windows, not every regional game.",
        "The figure is not posted yet. This is for the newest games of the current season.",
        "No figure was published.",
    ]
    href = shown.locator("a").get_attribute("href")
    assert href is not None and href.endswith("#nfl-games-with-no-public-rating")
    nfl_guarded_page.keyboard.press("Escape")
    assert note.is_hidden()
    # Excitement copy.
    _set(nfl_guarded_page, {"scatterY": "excitement"})
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('scatter').y === 'excitement'"
    )
    btn.click()
    shown = nfl_guarded_page.locator(f"{VIEW} .band-note > div:not([hidden])")
    assert shown.locator("p").all_inner_texts() == [
        "No excitement value",
        "No win-probability data exists for these games, so they have no height on this chart. They are drawn here instead of being left out. Their viewer figures are unchanged.",
        "How the Y axis works",
    ]
    href = shown.locator("a").get_attribute("href")
    assert href is not None and href.endswith("#nfl-gei-style-excitement")


def test_no_spread_text_anywhere(nfl_guarded_page: Page, open_nfl_app: Callable[..., None]) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    _vm(nfl_guarded_page)
    assert "spread" not in nfl_guarded_page.locator(VIEW).inner_text().lower()
    nfl_guarded_page.locator(f"{VIEW} [aria-label='X axis']").get_by_text("Final margin").click()
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('scatter').x === 'margin'"
    )
    assert "spread" not in nfl_guarded_page.locator(VIEW).inner_text().lower()
    html = nfl_guarded_page.evaluate(f"document.querySelector('{VIEW}').textContent.toLowerCase()")
    assert "spread" not in html


def test_hidden_table_wrapper_not_the_table(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    _vm(nfl_guarded_page)
    assert nfl_guarded_page.locator(f"{VIEW} div.visually-hidden > table").count() == 1
    assert nfl_guarded_page.locator(f"{VIEW} table.visually-hidden").count() == 0


# --------------------------------------------------------------- task 2


def test_hover_lines_rated_window_and_unrated_regional(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    _vm(nfl_guarded_page)
    g = _g(nfl_fixture_raw)
    names = nfl_fixture_raw["lookups"]["team_names"]
    people = nfl_fixture_raw["lookups"]["people"]
    networks = nfl_fixture_raw["lookups"]["networks"]
    rated = next(
        i
        for i in range(len(g["season"]))
        if g["scope"][i] == "window" and g["crew"][i] and g["network"][i] is not None
    )
    _emit(nfl_guarded_page, "plotly_hover", rated)
    lines = _tooltip(nfl_guarded_page)
    assert (
        lines[0]
        == f"{names[g['away_name'][rated]]['name']} at {names[g['home_name'][rated]]['name']}"
    )
    assert lines[1].endswith(f" ET · Week {g['week'][rated]}")
    assert lines[3] == networks[g["network"][rated]]["name"]
    pbp = next(m for m in g["crew"][rated] if m["role"] == "pbp")
    analyst = next(m for m in g["crew"][rated] if m["role"] == "analyst")
    assert lines[4] == f"{people[pbp['person']]['name']} / {people[analyst['person']]['name']}"
    assert lines[5] == f"Viewers: {g['viewers'][rated] / 1e6:.1f}M · window-level"
    exc = g["excitement"][rated]
    assert lines[6] == f"GEI-style excitement: {exc:.1f}"
    assert lines[-1] == "Click for details."
    assert not nfl_guarded_page.locator("#chart-hover-ring").is_hidden()
    _emit(nfl_guarded_page, "plotly_unhover", rated)
    assert nfl_guarded_page.locator("#chart-hover-ring").is_hidden()

    regional = next(
        i
        for i in range(len(g["season"]))
        if g["cause"][i] == "regional" and g["viewers"][i] is None
    )
    _emit(nfl_guarded_page, "plotly_hover", regional)
    lines = _tooltip(nfl_guarded_page)
    assert "Viewers: not available (not compiled for regional games)" in lines
    assert not any("window-level" in ln for ln in lines)
    exc = g["excitement"][regional]
    want = (
        f"GEI-style excitement: {exc:.1f}"
        if exc is not None
        else "GEI-style excitement: not available"
    )
    assert want in lines


def test_faded_dot_has_no_hover_or_click(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    _vm(nfl_guarded_page)
    fid = nfl_fixture_raw["lookups"]["franchises"][0]["id"]
    _set(nfl_guarded_page, {"teams": [fid]})
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('scatter').counts.faded > 0"
    )
    vm = _vm(nfl_guarded_page)
    faded = next(it["i"] for it in vm["items"] if it["faded"])
    _emit(nfl_guarded_page, "plotly_hover", faded)
    assert nfl_guarded_page.locator("#chart-tooltip").is_hidden()
    _emit(nfl_guarded_page, "plotly_click", faded)
    assert not _panel_open(nfl_guarded_page)


def test_click_opens_panel_and_accumulates_picks(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    vm = _vm(nfl_guarded_page)
    ids = [it["i"] for it in vm["items"] if not it["band"]][:2]
    _emit(nfl_guarded_page, "plotly_click", ids[0])
    assert _panel_open(nfl_guarded_page)
    nfl_guarded_page.wait_for_function("window.__nflTestHooks.getTableIndexes().length === 1")
    assert nfl_guarded_page.evaluate("window.__nflTestHooks.getTableIndexes()") == [ids[0]]
    nfl_guarded_page.locator("#nfl-detail-panel .panel-close").click()
    nfl_guarded_page.wait_for_timeout(600)  # past the 500 ms same-target guard
    _emit(nfl_guarded_page, "plotly_click", ids[1])
    nfl_guarded_page.wait_for_function("window.__nflTestHooks.getTableIndexes().length === 2")
    assert set(nfl_guarded_page.evaluate("window.__nflTestHooks.getTableIndexes()")) == set(ids)
    # A repeat click on the same game does not duplicate it.
    nfl_guarded_page.locator("#nfl-detail-panel .panel-close").click()
    nfl_guarded_page.wait_for_timeout(600)
    _emit(nfl_guarded_page, "plotly_click", ids[1])
    assert len(nfl_guarded_page.evaluate("window.__nflTestHooks.getTableIndexes()")) == 2


def test_caption_text_and_links_exact(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    _vm(nfl_guarded_page)
    cap = nfl_guarded_page.locator(f"{VIEW} .nfl-captions")
    assert cap.inner_text() == (
        "Viewers are window-level where marked and unnormalized. "
        "GEI-style excitement is not CFBD's excitement index; see methodology."
    )
    hrefs = cap.locator("a").evaluate_all("els => els.map(a => a.getAttribute('href'))")
    assert [h.split("#")[1] for h in hrefs] == [
        "nfl-window-level-viewership",
        "nfl-gei-style-excitement",
    ]


def test_mobile_tap_opens_panel(nfl_mobile_page: Page, open_nfl_app: Callable[..., None]) -> None:
    _open(nfl_mobile_page, open_nfl_app)
    vm = _vm(nfl_mobile_page)
    i = next(it["i"] for it in vm["items"] if not it["band"])
    _emit(nfl_mobile_page, "plotly_hover", i)
    assert (
        nfl_mobile_page.locator("#chart-tooltip").count() == 0
        or nfl_mobile_page.locator("#chart-tooltip").is_hidden()
    )
    _emit(nfl_mobile_page, "plotly_click", i)
    assert _panel_open(nfl_mobile_page)
    layout = nfl_mobile_page.evaluate(f"document.querySelector('{GD}')._fullLayout.dragmode")
    assert layout is False


def test_resize_repositions_band_button(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    _vm(nfl_guarded_page)
    nfl_guarded_page.wait_for_function(
        f"document.querySelector('{VIEW} .band-info').style.top !== ''"
    )
    top = nfl_guarded_page.evaluate(
        f"parseFloat(document.querySelector('{VIEW} .band-info').style.top)"
    )
    assert top > 0


def test_mobile_era_labels_inside_plot_scatter(
    nfl_mobile_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_mobile_page

    labels = [f"Synthetic Nielsen measurement era {c} with a long label" for c in "ABC"]

    def _long_eras(route: Route) -> None:
        resp = route.fetch()
        raw = json.loads(resp.text())
        eras = raw["lookups"]["eras"]
        eras[:] = [{**eras[0], "id": f"era-{k}", "label": lab} for k, lab in enumerate(labels)]
        rank = {s: k for k, s in enumerate(sorted(set(raw["games"]["season"])))}
        for block in (raw["games"], raw["agotw_viewership"]):
            col = block["era"]
            for i, s in enumerate(block["season"]):
                if col[i] is not None:
                    col[i] = min(rank[s], len(labels) - 1)
        route.fulfill(response=resp, body=json.dumps(raw))

    page.route("**/nfl-data.json", _long_eras)
    open_nfl_app(page, "?sport=nfl&view=scatter")
    page.wait_for_function("window.__nflTestHooks.getViewModel('scatter').drawn === true")
    boxes = page.evaluate(
        """() => {
          const view = document.querySelector('#nfl-view-scatter .nfl-chart > div');
          const c = view.getBoundingClientRect();
          return [...view.querySelectorAll('.annotation-text')]
            .filter((n) => n.textContent.includes('Nielsen'))
            .map((n) => {
              const b = n.getBoundingClientRect();
              return { text: n.textContent, left: b.left - c.left, right: c.right - b.right, w: b.width };
            });
        }"""
    )
    assert boxes
    for b in boxes:
        assert b["left"] >= -0.5 and b["right"] >= -0.5, b
    ordered = sorted(boxes, key=lambda b: b["left"])
    for prev, nxt in pairwise(ordered):
        assert prev["w"] + prev["left"] <= nxt["left"], (prev, nxt)
    caption = page.locator("#nfl-view-scatter .nfl-era-caption").inner_text()
    for lab in labels:
        assert lab in caption
