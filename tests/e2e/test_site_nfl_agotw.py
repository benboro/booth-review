# ruff: noqa: E501, RUF001  (embedded JS lines and the UI copy's typographic characters)
"""999.5-15: NFL view 3, AGOTW viewership (season line with crew segments).

Synthetic nfl-data fixture only; no vault rows. Expected values are recomputed
from the fixture's `agotw_viewership` block.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from itertools import pairwise
from typing import Any

import pytest
from playwright.sync_api import Page, Route

pytestmark = pytest.mark.e2e

GD = "#nfl-view-agotw .nfl-chart > div"
MINUS = "−"


def _open(page: Page, open_nfl_app: Callable[..., None], query: str = "") -> None:
    open_nfl_app(page, "?sport=nfl&view=agotw" + query)


def _vm(page: Page) -> dict[str, Any]:
    page.wait_for_function("window.__nflTestHooks.getViewModel('agotw').drawn === true")
    return page.evaluate("window.__nflTestHooks.getViewModel('agotw')")  # type: ignore[no-any-return]


def _set(page: Page, patch: dict[str, Any]) -> None:
    page.evaluate("p => window.__nflTestHooks.setState(p)", patch)


def _rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    b = raw["agotw_viewership"]
    return [{k: b[k][i] for k in b} for i in range(len(b["season"]))]


def _name(raw: dict[str, Any], idx: int | None) -> str:
    return raw["lookups"]["people"][idx]["name"]


def _crew(raw: dict[str, Any], r: dict[str, Any]) -> str:
    return f"{_name(raw, r['pbp_person'])} / {_name(raw, r['analyst_person'])}"


def _emit(page: Page, event: str, k: int) -> None:
    page.evaluate(
        """([ev, k, sel]) => {
          const gd = document.querySelector(sel);
          gd.emit(ev, { points: [{ customdata: k }], event: { clientX: 300, clientY: 200 } });
        }""",
        [event, k, GD],
    )


def _tooltip(page: Page) -> list[str]:
    page.wait_for_function("!document.getElementById('chart-tooltip').hidden")
    return page.evaluate(  # type: ignore[no-any-return]
        "Array.from(document.getElementById('chart-tooltip').children).map(c => c.textContent)"
    )


def _fmt(v: float, resid: bool) -> str:
    r = round(v)
    if not resid:
        return f"{r:,}"
    if r == 0:
        return "0"
    return ("+" if r > 0 else MINUS) + f"{abs(r):,}"


# --------------------------------------------------------------- task 1


def test_crew_segments_connector_and_mean_mode(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    vm = _vm(nfl_guarded_page)
    rows = _rows(nfl_fixture_raw)
    assert vm["y"] == "mean" and vm["axisTitle"] == "Mean AGOTW viewers"
    assert len(vm["segments"]) == 2
    s0, s1 = vm["segments"]
    assert s0["color"] != s1["color"] and s0["symbol"] != s1["symbol"]
    assert s0["crew"] == _crew(nfl_fixture_raw, rows[0])
    assert s0["seasons"] == [2024] and s1["seasons"] == [2025, 2026]
    assert [p["y"] for p in vm["points"]] == [r["mean_viewers"] for r in rows]
    data = nfl_guarded_page.evaluate(
        f"document.querySelector('{GD}').data.map(t => ({{mode: t.mode, dash: t.line && t.line.dash, ey: !!(t.error_y && t.error_y.visible), n: (t.x || []).length}}))"
    )
    assert sum(1 for t in data if t["mode"] == "lines+markers") == 2
    connector = [t for t in data if t["dash"] == "dash"]
    assert len(connector) == 1 and connector[0]["n"] == 3
    assert not any(t["ey"] for t in data)
    title = nfl_guarded_page.evaluate(f"document.querySelector('{GD}').layout.yaxis.title.text")
    assert title == "Mean AGOTW viewers"
    ticks = nfl_guarded_page.evaluate(f"document.querySelector('{GD}').layout.xaxis.tickvals")
    assert ticks == [2024, 2025, 2026]


def test_era_bands_cover_whole_seasons_with_labels(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    vm = _vm(nfl_guarded_page)
    labels = [e["label"] for e in nfl_fixture_raw["lookups"]["eras"]]
    assert [b["era"] for b in vm["bands"]] == labels
    assert [(b["from"], b["to"]) for b in vm["bands"]] == [(2023.5, 2024.5), (2024.5, 2026.5)]
    ann = nfl_guarded_page.evaluate(
        f"document.querySelector('{GD}').layout.annotations.map(a => a.text)"
    )
    assert ann == labels
    shapes = nfl_guarded_page.evaluate(f"document.querySelector('{GD}').layout.shapes")
    assert len(shapes) == 1  # even band only; the odd band has no fill
    assert shapes[0]["layer"] == "below" and shapes[0]["x0"] == 2023.5


def test_residual_mode_whiskers_zero_line_and_low_n(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app, "&ay=resid")
    vm = _vm(nfl_guarded_page)
    rows = _rows(nfl_fixture_raw)
    assert vm["y"] == "resid" and vm["axisTitle"] == "Viewers vs. expected for game quality"
    for got, want in zip(vm["points"], rows, strict=True):
        assert got["y"] == want["viewership_resid"]
        if want["viewership_se"] is not None:
            assert got["err"] == pytest.approx(1.96 * want["viewership_se"])
    err = nfl_guarded_page.evaluate(
        f"document.querySelector('{GD}').data.filter(t => t.error_y && t.error_y.visible).length"
    )
    assert err == 2
    shapes = nfl_guarded_page.evaluate(f"document.querySelector('{GD}').layout.shapes")
    assert any(s["type"] == "line" and s["y0"] == 0 and s["y1"] == 0 for s in shapes)
    title = nfl_guarded_page.evaluate(f"document.querySelector('{GD}').layout.yaxis.title.text")
    assert title == "Viewers vs. expected for game quality"
    ticktext = nfl_guarded_page.evaluate(f"document.querySelector('{GD}').layout.yaxis.ticktext")
    assert any(t.startswith(MINUS) for t in ticktext) and any(t.startswith("+") for t in ticktext)


def test_y_switch_updates_url_and_low_n_point_is_hollow(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    _vm(nfl_guarded_page)
    nfl_guarded_page.get_by_role("button", name="vs. expected for game quality").click()
    nfl_guarded_page.wait_for_function("window.__nflTestHooks.getViewModel('agotw').y === 'resid'")
    assert "ay=resid" in nfl_guarded_page.url
    _set(nfl_guarded_page, {"agotwY": "mean"})
    _vm(nfl_guarded_page)
    marker = nfl_guarded_page.evaluate(
        f"document.querySelector('{GD}').data.filter(t => t.mode === 'lines+markers')[1].marker"
    )
    assert marker["color"][-1] == "rgba(0,0,0,0)" and marker["opacity"][-1] == 0.5
    assert marker["color"][0] != "rgba(0,0,0,0)"
    assert marker["line"]["width"] == [0, 2]


def test_hiding_a_crew_removes_its_segment(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    _vm(nfl_guarded_page)
    chips = nfl_guarded_page.locator("#nfl-view-agotw .legend-chip")
    rows = _rows(nfl_fixture_raw)
    assert chips.count() == 2
    assert chips.nth(0).inner_text() == _crew(nfl_fixture_raw, rows[0])
    assert chips.nth(1).inner_text() == _crew(nfl_fixture_raw, rows[1])
    chips.nth(0).click()
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('agotw').segments.length === 1"
    )
    vm = nfl_guarded_page.evaluate("window.__nflTestHooks.getViewModel('agotw')")
    assert vm["segments"][0]["seasons"] == [2025, 2026]
    assert chips.nth(0).get_attribute("aria-pressed") == "false"


def test_seasons_filter_narrows_to_one_season(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    _open(nfl_guarded_page, open_nfl_app, "&seasons=2025-2025")
    vm = _vm(nfl_guarded_page)
    assert [p["season"] for p in vm["points"]] == [2025]
    assert len(vm["segments"]) == 1
    assert len(vm["bands"]) == 1
    ticks = nfl_guarded_page.evaluate(f"document.querySelector('{GD}').layout.xaxis.tickvals")
    assert ticks == [2025]


# --------------------------------------------------------------- task 2


def test_hover_lines_in_both_modes(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    rows = _rows(nfl_fixture_raw)
    eras = nfl_fixture_raw["lookups"]["eras"]
    vm = _vm(nfl_guarded_page)
    r = rows[1]  # 2025: one fill-in game, not low n
    k = [p["season"] for p in vm["points"]].index(2025)
    _emit(nfl_guarded_page, "plotly_hover", k)
    assert _tooltip(nfl_guarded_page) == [
        f"2025 · {_crew(nfl_fixture_raw, r)}",
        f"Mean AGOTW viewers: {_fmt(r['mean_viewers'], False)}",
        f"{r['games']} games; {r['fill_in_games']} fill-in",
        f"Measured under: {eras[r['era']]['label']}",
        "Window-level, unnormalized",
        "Click to list games.",
    ]
    _set(nfl_guarded_page, {"agotwY": "resid"})
    nfl_guarded_page.wait_for_function("window.__nflTestHooks.getViewModel('agotw').y === 'resid'")
    _emit(nfl_guarded_page, "plotly_hover", k)
    lines = _tooltip(nfl_guarded_page)
    assert lines[1] == f"Viewers vs. expected: {_fmt(r['viewership_resid'], True)}"
    assert "Window-level, unnormalized" in lines


def test_low_n_hover_and_missing_residual(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app, "&ay=resid")
    vm = _vm(nfl_guarded_page)
    k = [p["season"] for p in vm["points"]].index(2026)
    _emit(nfl_guarded_page, "plotly_hover", k)
    lines = _tooltip(nfl_guarded_page)
    n = nfl_fixture_raw["constants"]["low_n_threshold"]
    assert "Viewers vs. expected: not available" in lines
    assert f"Fewer than {n} games. Read with care." in lines


def test_click_fills_games_table_with_that_points_games(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    vm = _vm(nfl_guarded_page)
    rows = _rows(nfl_fixture_raw)
    k = [p["season"] for p in vm["points"]].index(2025)
    _emit(nfl_guarded_page, "plotly_click", k)
    nfl_guarded_page.wait_for_function("window.__nflTestHooks.getTableIndexes().length > 0")
    got = nfl_guarded_page.evaluate("window.__nflTestHooks.getTableIndexes()")
    assert sorted(got) == sorted(rows[1]["game_list"])
    games = nfl_fixture_raw["games"]
    assert all(games["agotw"][i] for i in got)
    sel = nfl_guarded_page.evaluate("window.__nflTestHooks.getState().selection")
    assert sel["kind"] == "agotw" and sel["label"] == "2025 AGOTW"


def test_captions_links_and_hidden_table(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    vm = _vm(nfl_guarded_page)
    cap = nfl_guarded_page.locator("#nfl-view-agotw .nfl-captions")
    text = cap.inner_text()
    assert "Window-level, unnormalized viewers. Only AGOTW games are compared." in text
    assert (
        "Nielsen changed how it measures viewing in 2020, 2025, and 2026, so compare seasons with care; see methodology."
        in text
    )
    hrefs = cap.locator("a").evaluate_all("els => els.map(a => a.getAttribute('href'))")
    assert hrefs[0].endswith("#nfl-window-level-viewership")
    assert hrefs[1].endswith("#nfl-measurement-eras")
    rows = nfl_guarded_page.locator("#nfl-view-agotw .visually-hidden tbody tr")
    assert rows.count() == len(vm["points"])
    first = rows.nth(0).locator("th, td").all_inner_texts()
    r0 = _rows(nfl_fixture_raw)[0]
    assert first == [
        "2024",
        _crew(nfl_fixture_raw, r0),
        _fmt(r0["mean_viewers"], False),
        nfl_fixture_raw["lookups"]["eras"][r0["era"]]["label"],
    ]


def test_mobile_era_labels_inside_plot_agotw(
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
    open_nfl_app(page, "?sport=nfl&view=agotw")
    page.wait_for_function("window.__nflTestHooks.getViewModel('agotw').drawn === true")
    boxes = page.evaluate(
        """() => {
          const view = document.querySelector('#nfl-view-agotw .nfl-chart > div');
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
    caption = page.locator("#nfl-view-agotw .nfl-era-caption").inner_text()
    for lab in labels:
        assert lab in caption


def test_missing_se_is_disclosed_never_a_zero_whisker(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    """JS-WR-06: a null SE draws no whisker and says "not available" in the hover and table."""
    page = nfl_guarded_page

    def _no_se(route: Route) -> None:
        resp = route.fetch()
        raw = json.loads(resp.text())
        raw["agotw_viewership"]["viewership_se"][1] = None  # 2025 keeps its residual
        route.fulfill(response=resp, body=json.dumps(raw))

    page.route("**/nfl-data.json", _no_se)
    _open(page, open_nfl_app, "&ay=resid")
    vm = _vm(page)
    seasons = [p["season"] for p in vm["points"]]
    k25, k24 = seasons.index(2025), seasons.index(2024)
    assert vm["points"][k25]["err"] is None
    nan = page.evaluate(
        f"""(() => {{
          const t = document.querySelector('{GD}').data.find((d) => d.error_y && d.x.includes(2025));
          return Number.isNaN(t.error_y.array[t.x.indexOf(2025)]);
        }})()"""
    )
    assert nan is True
    _emit(page, "plotly_hover", k25)
    assert "±1.96 standard errors: not available" in _tooltip(page)
    r = _rows(nfl_fixture_raw)[0]
    half = 1.96 * r["viewership_se"]
    _emit(page, "plotly_hover", k24)
    lines = _tooltip(page)
    want = f"±1.96 standard errors: {_fmt(r['viewership_resid'] - half, True)} to {_fmt(r['viewership_resid'] + half, True)}"
    assert want in lines
    cells = page.locator("#nfl-view-agotw .visually-hidden tbody tr").nth(k25).locator("td")
    assert cells.nth(1).inner_text().endswith("(±1.96 standard errors: not available)")
