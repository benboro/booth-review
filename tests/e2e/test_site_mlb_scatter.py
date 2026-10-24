"""16-07: the MLB Scatter tab (D-04..D-10) on the densified synthetic MLB fixture.

The route handler rewrites game columns through ``densify_scatter`` so every placement
(plot, bottom strip, left strip, corner) occurs. No vault data is used.
"""

# ruff: noqa: E501
from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from mlb_scatter_fixture import CONTROLS, SCATTER_CASE, densify_scatter
from playwright.sync_api import Page, Route

pytestmark = pytest.mark.e2e

VIEW = "#mlb-view-scatter"
TOOLS = "#mlb-chart-tools [data-tools-for='scatter']"
GD = f"{VIEW} .js-plotly-plot"
HOOKS = "window.__mlbTestHooks"

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "contract" / "mlb-data.fixture.json"
_RAW: dict[str, Any] = json.loads(_FIXTURE.read_text(encoding="utf-8"))
_DENSE: dict[str, Any] = densify_scatter(_RAW)
_G = _DENSE["games"]
_POST_ROUNDS = {"wild_card", "division", "lcs", "world_series", "tiebreak"}

VIEWER_TICKS = {"500K", "1M", "2M", "5M", "10M", "20M"}
PAGE_BG_LIGHT = "#FBF9F5"


def _densify(route: Route) -> None:
    resp = route.fetch()
    route.fulfill(response=resp, body=json.dumps(densify_scatter(json.loads(resp.text()))))


def _open(page: Page, open_mlb_app: Callable[..., None], query: str = "") -> None:
    page.route("**/mlb-data.json", _densify)
    open_mlb_app(page, "?sport=mlb&view=scatter" + query)
    page.wait_for_function(f"{HOOKS}.getViewModel('scatter').drawn === true")


def _vm(page: Page) -> dict[str, Any]:
    page.wait_for_function(f"{HOOKS}.getViewModel('scatter') !== null")
    return page.evaluate(f"{HOOKS}.getViewModel('scatter')")  # type: ignore[no-any-return]


def _plot(page: Page) -> dict[str, Any]:
    return page.evaluate(  # type: ignore[no-any-return]
        """sel => {
          const gd = document.querySelector(sel);
          return JSON.parse(JSON.stringify({ data: gd.data, layout: gd.layout }));
        }""",
        GD,
    )


def _place(i: int) -> str:
    has_v = _G["viewers"][i] is not None
    has_e = _G["wp_excitement"][i] is not None
    if has_v and has_e:
        return "plot"
    if has_e:
        return "bottom"
    return "left" if has_v else "corner"


def _in_control(i: int, name: str) -> bool:
    stype, sround = CONTROLS[name]
    rnd = _G["round"][i]
    if stype == "reg":
        return rnd == "regular"
    if stype == "post":
        return rnd in _POST_ROUNDS and (sround is None or rnd == sround)
    return True


def _status(counts: dict[str, int]) -> str:
    rest = []
    if counts["noRating"]:
        rest.append(f"{counts['noRating']} with no rating")
    if counts["noExcitement"]:
        rest.append(f"{counts['noExcitement']} with no excitement")
    if counts["neither"]:
        rest.append(f"{counts['neither']} with neither")
    plotted = (
        f"{counts['plotted']} {'game' if counts['plotted'] == 1 else 'games'} plotted."
        if counts["plotted"]
        else ""
    )
    tail = f"{', '.join(rest)}." if rest else ""
    return " ".join(p for p in (plotted, tail) if p)


def _points(plot: dict[str, Any]) -> list[dict[str, Any]]:
    """Every drawn point: game index, trace axis, x, y, marker colour and outline width."""
    out = []
    for t in plot["data"]:
        marker = t["marker"]
        for k, i in enumerate(t["customdata"]):
            out.append(
                {
                    "i": i,
                    "yaxis": t["yaxis"],
                    "x": t["x"][k],
                    "y": t["y"][k],
                    "color": marker["color"][k],
                    "line_w": marker["line"]["width"][k],
                    "line_c": marker["line"]["color"][k],
                    "meta": t["meta"],
                }
            )
    return out


def test_tab_bar_subtitle_and_deep_link(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    _open(page, open_mlb_app)
    tabs = page.eval_on_selector_all(
        "#mlb-chart-tabs [role=tab]", "els => els.map(e => e.textContent)"
    )
    assert tabs == ["Apple crews", "Postseason booths", "Scatter"]
    assert page.locator("#mlb-tab-scatter[aria-selected='true']").count() == 1
    assert page.locator(VIEW).is_visible()
    assert page.locator("#mlb-view-apple").is_hidden()
    assert (
        page.locator("#mlb-chart-subtitle").inner_text()
        == "One dot per game. Pick a booth, cell or season on its tab to highlight its games here."
    )
    assert "view=scatter" in page.url
    # The tools show only on the Scatter tab.
    assert page.eval_on_selector(TOOLS, "e => e.hidden") is False
    page.click("#mlb-tab-apple")
    assert page.eval_on_selector(TOOLS, "e => e.hidden") is True


def test_counts_equal_the_case_and_every_game_is_drawn_once(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    _open(page, open_mlb_app)
    vm = _vm(page)
    expected = SCATTER_CASE["all"]
    for key, value in expected.items():
        assert vm["counts"][key] == value, key
    pts = _points(_plot(page))
    indexes = sorted(p["i"] for p in pts)
    assert indexes == list(range(len(_G["viewers"])))
    assert all(isinstance(i, int) for i in indexes)


def test_axes_titles_ticks_and_ranges(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    _open(page, open_mlb_app)
    layout = _plot(page)["layout"]
    assert layout["yaxis"]["type"] == "log"
    assert layout["yaxis"]["title"]["text"] == "Viewers"
    assert layout["xaxis"]["title"]["text"] == "Excitement"
    assert layout["xaxis"].get("type", "linear") == "linear"
    labels = layout["yaxis"]["ticktext"]
    assert labels and set(labels) <= VIEWER_TICKS
    top = max(e for e in _G["wp_excitement"] if e is not None)
    nice = math.ceil(top * 2) / 2
    lo, hi = layout["xaxis"]["range"]
    assert lo < 0  # the left strip sits at negative x
    assert nice <= hi < nice + 0.5
    assert layout["xaxis"]["tickvals"][0] == 0


def test_placements_strips_and_divider(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, open_mlb_app)
    plot = _plot(page)
    divider = [s for s in plot["layout"]["shapes"] if s["line"].get("dash") == "dash"]
    assert len(divider) == 1
    edge = divider[0]["x0"]
    assert edge < 0
    assert divider[0]["line"]["color"]
    seen = set()
    for p in _points(plot):
        place = _place(p["i"])
        seen.add(place)
        assert (p["yaxis"] == "y2") == (place in ("bottom", "corner")), p
        if place in ("left", "corner"):
            assert p["x"] < edge, p
        else:
            assert p["x"] >= 0, p
        assert p["y"] is not None and p["y"] != 0
        assert p["x"] is not None
        if place in ("plot", "left"):
            assert p["y"] == _G["viewers"][p["i"]]
        if place in ("plot", "bottom"):
            assert p["x"] == _G["wp_excitement"][p["i"]]
    assert seen == {"plot", "bottom", "left", "corner"}
    # Strip labels are the info buttons; their texts are fixed copy.
    assert (
        page.locator(f"{VIEW} .band-info.mlb-bottom-info .band-info-text").inner_text()
        == "No public rating"
    )
    assert (
        page.locator(f"{VIEW} .band-info.mlb-left-info .band-info-text").inner_text()
        == "No excitement"
    )
    # The left strip is 72px wide (the divider sits 72px from the axis start).
    px = page.evaluate(
        """([sel, edge]) => {
          const xa = document.querySelector(sel)._fullLayout.xaxis;
          return (edge - xa.range[0]) / (xa.range[1] - xa.range[0]) * xa._length;
        }""",
        [GD, edge],
    )
    assert abs(px - 72) <= 2, px


def test_window_dots_are_open_and_game_dots_solid(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    _open(page, open_mlb_app)
    pts = {p["i"]: p for p in _points(_plot(page))}
    window = [i for i, s in enumerate(_G["scope"]) if s == "window"]
    assert window
    for i in window:
        assert pts[i]["color"].upper() == PAGE_BG_LIGHT
        assert pts[i]["line_w"] == 1.5
        assert pts[i]["line_c"].upper() != PAGE_BG_LIGHT
    solid = [i for i, s in enumerate(_G["scope"]) if s == "game"]
    for i in solid:
        assert pts[i]["color"].upper() != PAGE_BG_LIGHT
        assert pts[i]["line_w"] == 0


def test_status_line_equals_counts(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    _open(page, open_mlb_app)
    status = page.locator(f"{VIEW} p.mlb-scatter-status")
    assert status.get_attribute("role") == "status"
    assert status.inner_text() == _status(SCATTER_CASE["all"])
    counts = SCATTER_CASE["all"]
    # plotted + the strip groups add up to the games in the control.
    assert (
        counts["plotted"] + counts["noRating"] + counts["noExcitement"] + counts["neither"]
        == counts["total"]
    )


def test_plot_height_desktop_and_phone(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, open_mlb_app)
    assert page.locator(f"{VIEW} .mlb-scatter-plot").bounding_box()["height"] == 480  # type: ignore[index]


def test_plot_height_phone(mlb_mobile_page: Page, open_mlb_app: Callable[..., None]) -> None:
    page = mlb_mobile_page
    _open(page, open_mlb_app)
    assert page.locator(f"{VIEW} .mlb-scatter-plot").bounding_box()["height"] == 360  # type: ignore[index]


def test_one_trace_group_per_family_present(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    _open(page, open_mlb_app)
    plot = _plot(page)
    vm = _vm(page)
    assert vm["families"] == ["apple", "fox", "tbs", "disney"]
    metas = {t["meta"] for t in plot["data"]}
    assert metas == set(vm["families"])
    for fam in vm["families"]:
        axes = [t["yaxis"] for t in plot["data"] if t["meta"] == fam]
        assert len(axes) == len(set(axes)) and set(axes) <= {"y", "y2"}
    assert {t["type"] for t in plot["data"]} == {"scatter"}


def test_desktop_drag_zoom_is_vertical_and_both_strips_survive(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """Zoom spike (RESEARCH A3): a drag zooms the viewers axis only; the strips stay put."""
    page = mlb_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, open_mlb_app)
    page.wait_for_timeout(300)
    info = page.evaluate(
        """sel => {
          const gd = document.querySelector(sel);
          const r = gd.getBoundingClientRect();
          const f = gd._fullLayout;
          return { l: r.left, t: r.top, size: f._size, xr: [...f.xaxis.range], yr: [...f.yaxis.range], drag: f.dragmode };
        }""",
        GD,
    )
    assert info["drag"] == "zoom"
    s = info["size"]
    x0 = info["l"] + s["l"] + s["w"] * 0.35
    x1 = info["l"] + s["l"] + s["w"] * 0.7
    y0 = info["t"] + s["t"] + s["h"] * 0.16
    y1 = info["t"] + s["t"] + s["h"] * 0.6
    page.mouse.move(x0, y0)
    page.mouse.down()
    page.mouse.move((x0 + x1) / 2, (y0 + y1) / 2, steps=5)
    page.mouse.move(x1, y1, steps=5)
    page.mouse.up()
    page.wait_for_timeout(500)
    after = page.evaluate(
        """sel => {
          const gd = document.querySelector(sel);
          const f = gd._fullLayout;
          const left = gd.data.flatMap(t => t.customdata.map((c, k) => ({ x: t.x[k], ya: t.yaxis }))).filter(p => p.x < 0 && p.ya === 'y');
          return {
            xr: [...f.xaxis.range], yr: [...f.yaxis.range],
            leftPx: left.map(p => f.xaxis.l2p(p.x)), len: f.xaxis._length,
            bottom: !document.querySelector('.mlb-bottom-info').hidden,
            leftBtn: !document.querySelector('.mlb-left-info').hidden,
          };
        }""",
        GD,
    )
    assert after["yr"] != info["yr"]
    assert after["yr"][1] - after["yr"][0] < info["yr"][1] - info["yr"][0]
    assert after["xr"] == info["xr"]
    assert after["leftPx"] and all(0 <= px <= 72 for px in after["leftPx"])
    assert after["bottom"] and after["leftBtn"]
    page.mouse.dblclick(x0, y0)
    page.wait_for_timeout(500)
    back = page.evaluate(
        "sel => { const f = document.querySelector(sel)._fullLayout; return { xr: [...f.xaxis.range], yr: [...f.yaxis.range] }; }",
        GD,
    )
    assert back == {"xr": info["xr"], "yr": info["yr"]}


def test_phone_scatter_is_not_zoomable(
    mlb_mobile_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_mobile_page
    _open(page, open_mlb_app)
    layout = _plot(page)["layout"]
    assert layout["dragmode"] is False
    assert layout["xaxis"]["fixedrange"] is True and layout["yaxis"]["fixedrange"] is True

