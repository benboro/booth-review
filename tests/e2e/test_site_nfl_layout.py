"""Phase 15 plan 11: NFL layout, style and engine checks (V15-1, V15-9, V15-10, V15-11).

The four NFL views draw on the Plotly partial bundle; the Raw reason bar, the Viewership
subtitle row and the module header keep fixed heights; rows and heads do not move on hover,
focus, sort or mode switch; only 12, 14 and 20px type appears; Crews numbers are right-aligned
and tabular with no vertical rules; every logo has alt, title, width and height. Synthetic data
only (`serve_nfl_crews` overlay and the built NFL fixture).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from conftest import logo_images
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

WIDTHS = [1440, 1104, 1024, 768, 390]
VIEWS = ["special", "crews", "viewership", "scatter"]
TRACE_TYPES = {"scatter", "scattergl", "bar"}
TEAM = "f-lanterns"
CREWS = "#nfl-view-crews"
VIEWERSHIP = "#nfl-view-viewership"
HEAD = ".nfl-chart-module .module-head"
SUBTITLE = "#nfl-chart-subtitle"


def _open(page: Page, open_nfl_app: Callable[..., None], query: str, width: int | None) -> None:
    if width is not None:
        page.set_viewport_size({"width": width, "height": 900})
    view = query.split("view=")[1].split("&")[0]
    open_nfl_app(page, "?sport=nfl" + query if query.startswith("&") else query)
    page.wait_for_function(f"window.__nflTestHooks.getViewModel('{view}') !== null")
    page.wait_for_function(f"window.__nflTestHooks.getViewModel('{view}').drawn === true")


def _height(page: Page, selector: str) -> float:
    return page.eval_on_selector(  # type: ignore[no-any-return]
        selector, "e => Math.round(e.getBoundingClientRect().height * 10) / 10"
    )


def _is_displayed(page: Page, selector: str) -> bool:
    return page.eval_on_selector(  # type: ignore[no-any-return]
        selector, "e => getComputedStyle(e).display !== 'none' && e.offsetHeight > 0"
    )


def _page_for(width: int, nfl_guarded_page: Page, nfl_mobile_page: Page) -> Page:
    return nfl_mobile_page if width == 390 else nfl_guarded_page


@pytest.fixture
def pg(request: pytest.FixtureRequest, nfl_guarded_page: Page, nfl_mobile_page: Page) -> Page:
    width = request.node.callspec.params.get("width", 1440)
    return _page_for(width, nfl_guarded_page, nfl_mobile_page)


# ------------------------------------------------------------------ V15-1


@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize("view", VIEWS)
def test_four_views_draw_on_the_partial_bundle(
    pg: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
    view: str,
    width: int,
) -> None:
    serve_nfl_crews(pg)
    _open(pg, open_nfl_app, f"&view={view}", width)
    types: list[str] = pg.evaluate(
        f"""() => {{
          const gd = document.querySelector('#nfl-view-{view} .nfl-chart > div');
          return (gd.data || []).map((t) => t.type);
        }}"""
    )
    assert types, f"{view} drew no traces"
    assert set(types) <= TRACE_TYPES, types


# ------------------------------------------------------------------ V15-10


@pytest.mark.parametrize("width", WIDTHS)
def test_reason_bar_reserves_its_height(
    pg: Page, open_nfl_app: Callable[..., None], width: int
) -> None:
    want = 96 if width <= 480 else 56
    _open(pg, open_nfl_app, f"&view=crews&adj=1&team={TEAM}", width)
    assert _height(pg, "#nfl-reason-crews") == want
    _open(pg, open_nfl_app, f"&view=viewership&ay=resid&team={TEAM}", width)
    assert _height(pg, "#nfl-reason-viewership") == want
    # No pick leaves Adjusted free: the bar is out of the layout.
    _open(pg, open_nfl_app, "&view=crews&adj=1", width)
    assert not _is_displayed(pg, "#nfl-reason-crews")
    _open(pg, open_nfl_app, "&view=viewership&ay=resid", width)
    assert not _is_displayed(pg, "#nfl-reason-viewership")


@pytest.mark.parametrize("width", WIDTHS)
def test_viewership_subtitle_row_height(
    pg: Page, open_nfl_app: Callable[..., None], width: int
) -> None:
    # Below about 1000px the window sentence wraps to two lines, so the row reserves 40px.
    want = 80 if width <= 480 else 40 if width < 1000 else 20
    _open(pg, open_nfl_app, "&view=viewership", width)
    with_note = _height(pg, SUBTITLE)
    pg.evaluate(
        "p => window.__nflTestHooks.setState(p)",
        {"hiddenCategories": ["agotw", "cbs_national"]},
    )
    pg.wait_for_function("!window.__nflTestHooks.getViewModel('viewership').windowKey.shown")
    assert with_note == _height(pg, SUBTITLE) == want


@pytest.mark.parametrize("width", WIDTHS)
def test_module_header_height_constant_across_modes(
    pg: Page, open_nfl_app: Callable[..., None], width: int
) -> None:
    _open(pg, open_nfl_app, "&view=crews", width)
    raw = _height(pg, HEAD)
    _open(pg, open_nfl_app, "&view=crews&adj=1", width)
    assert _height(pg, HEAD) == raw
    _open(pg, open_nfl_app, "&view=viewership", width)
    viewers = _height(pg, HEAD)
    _open(pg, open_nfl_app, "&view=viewership&ay=resid", width)
    assert _height(pg, HEAD) == viewers


_HEIGHTS_JS = """
() => {
  const rows = [...document.querySelectorAll('#nfl-view-crews tr.crews-row')].map(
    (tr) => [tr.dataset.rowKey, Math.round(tr.getBoundingClientRect().height * 10) / 10]);
  const head = document.querySelector('#nfl-view-crews thead tr');
  return { rows: Object.fromEntries(rows),
           head: Math.round(head.getBoundingClientRect().height * 10) / 10 };
}
"""


def _same(before: dict[str, Any], after: dict[str, Any], what: str) -> None:
    assert after["head"] == before["head"], f"head height moved on {what}"
    for key, h in after["rows"].items():
        if key in before["rows"]:
            assert h == before["rows"][key], f"row {key} height moved on {what}"


@pytest.mark.parametrize("width", WIDTHS)
def test_rows_do_not_shift_on_hover_focus_sort_or_mode(
    pg: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
    width: int,
) -> None:
    serve_nfl_crews(pg)
    _open(pg, open_nfl_app, "&view=crews", width)
    base: dict[str, Any] = pg.evaluate(_HEIGHTS_JS)
    assert base["rows"]
    rows = pg.locator(f"{CREWS} tr.crews-row")
    rows.nth(1).hover()
    _same(base, pg.evaluate(_HEIGHTS_JS), "hover")
    rows.nth(2).focus()
    _same(base, pg.evaluate(_HEIGHTS_JS), "focus")
    pg.locator(f"{CREWS} thead button").nth(3).click()
    pg.wait_for_timeout(100)
    sorted_h: dict[str, Any] = pg.evaluate(_HEIGHTS_JS)
    _same(base, sorted_h, "sort")
    pg.locator(
        "#nfl-chart-tools [data-tools-for='crews'] [aria-label='Raw or adjusted'] button",
        has_text="Adjusted",
    ).click()
    pg.wait_for_function("window.__nflTestHooks.getViewModel('crews').mode === 'adjusted'")
    _same(sorted_h, pg.evaluate(_HEIGHTS_JS), "mode switch")


_FONTS_JS = """
(sel) => [...new Set([...document.querySelectorAll(sel + ', ' + sel + ' *')]
  .filter((el) => el.offsetParent !== null)
  .filter((el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()))
  .filter((el) => !el.closest('svg') && !el.closest('.nfl-chart'))
  .map((el) => getComputedStyle(el).fontSize))]
"""


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("view", VIEWS)
def test_font_sizes_are_12_14_20_only(
    pg: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
    view: str,
    width: int,
) -> None:
    serve_nfl_crews(pg)
    _open(pg, open_nfl_app, f"&view={view}", width)
    sizes: list[str] = pg.evaluate(_FONTS_JS, f"#nfl-view-{view}, .nfl-chart-module .module-head")
    assert sizes
    assert set(sizes) <= {"12px", "14px", "20px"}, sizes


# ------------------------------------------------------------------ V15-11


_NUMERIC_JS = """
() => {
  const tbl = document.querySelector('#nfl-view-crews table');
  const first = tbl.tBodies[0].rows[0];
  const cells = [...tbl.querySelectorAll('td.num')].map((el) => {
    const cs = getComputedStyle(el);
    return { align: cs.textAlign, nums: cs.fontVariantNumeric };
  });
  const heads = [...tbl.tHead.rows[0].cells].map((th, c) => ({
    num: !!first.cells[c] && first.cells[c].classList.contains('num'),
    text: th.textContent.trim(),
    align: getComputedStyle(th).textAlign,
    nums: getComputedStyle(th).fontVariantNumeric,
  }));
  const ruled = [...tbl.querySelectorAll('th, td')].filter((el) => {
    const cs = getComputedStyle(el);
    return parseFloat(cs.borderLeftWidth) > 0 || parseFloat(cs.borderRightWidth) > 0;
  }).length;
  return { cells, heads, ruled };
}
"""


@pytest.mark.parametrize("width", WIDTHS)
def test_numeric_cells_right_aligned_tabular_no_vertical_rules(
    pg: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
    width: int,
) -> None:
    serve_nfl_crews(pg)
    _open(pg, open_nfl_app, "&view=crews", width)
    m: dict[str, Any] = pg.evaluate(_NUMERIC_JS)
    assert m["cells"]
    for c in m["cells"]:
        assert c["align"] in {"right", "end"}, c
        assert "tabular-nums" in c["nums"], c
    numeric_heads = [h for h in m["heads"] if h["num"]]
    assert numeric_heads
    for h in numeric_heads:
        assert h["align"] in {"right", "end"}, h
    # The phone layout may pin the name column with one divider; nothing else is ruled.
    assert m["ruled"] <= (1 if width <= 480 else 0) * len(m["cells"]), m["ruled"]
    if width > 480:
        assert m["ruled"] == 0


@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize("view", VIEWS)
def test_logos_have_alt_title_width_height(
    pg: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
    view: str,
    width: int,
) -> None:
    serve_nfl_crews(pg)
    _open(pg, open_nfl_app, f"&view={view}", width)
    attrs: list[dict[str, Any]] = pg.evaluate(
        """() => [...document.querySelectorAll('#nfl-chart-area img')].map((img) => ({
          alt: img.getAttribute('alt'), title: img.getAttribute('title'),
          w: img.getAttribute('width'), h: img.getAttribute('height') }))"""
    )
    for a in attrs:
        assert a["alt"], a
        assert a["title"], a
        assert a["w"], a
        assert a["h"], a
    assert len(logo_images(pg, "#nfl-chart-area")) == len(attrs)


# ------------------------------------------------------------------ V15-9


_AXIS_TITLES_JS = """
(view) => [...document.querySelectorAll(`#nfl-view-${view} .nfl-chart .g-xtitle, ` +
  `#nfl-view-${view} .nfl-chart .g-ytitle`)].map((e) => e.textContent)
"""


@pytest.mark.parametrize("view", ["crews", "viewership"])
def test_no_gei_in_heads_controls_or_axis_titles(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
    view: str,
) -> None:
    page = nfl_guarded_page
    serve_nfl_crews(page)
    _open(page, open_nfl_app, f"&view={view}", 1440)
    chrome = page.locator(
        f"#nfl-view-{view} thead th, #nfl-view-{view} button, "
        f"#nfl-chart-tools [data-tools-for='{view}'] button"
    ).all_inner_texts()
    axes: list[str] = page.evaluate(_AXIS_TITLES_JS, view)
    assert axes, "the chart drew no axis titles"
    assert all("GEI" not in t for t in [*chrome, *axes])


def test_crews_notes_hold_rt17_and_the_confound_caption(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> None:
    page = nfl_guarded_page
    serve_nfl_crews(page)
    _open(page, open_nfl_app, "&view=crews&perseason=0", 1440)
    text = page.locator(f"{CREWS} .nfl-crews-notes").inner_text()
    assert (
        "NFL excitement is GEI-style, built from win probability. It is not CFBD's "
        "excitementIndex; see methodology." in text
    )
    assert "Avg viewers (rated games) mostly reflects which games a booth was assigned." in text
