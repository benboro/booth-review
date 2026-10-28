"""Phase 13 shell measurement suite (plan 13-17): the two vertical gaps and the band
height on every tab of every sport (SHELL-04, V4), filter-bar identity and persistence
(SHELL-03, V5), the type and request rules (V3), the changed-control contrast at runtime
(V8) and the font-swap layout-shift guard. Runs against the synthetic CFB + NFL + MLB
fixture build; no vault data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from conftest import element_height, measure_gap
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

WIDTHS = (1440, 1104, 1024, 768, 390)
FONT_FILES = {
    "lm-roman-demi-latin-600-normal.woff2",
    "roboto-latin-400-normal.woff2",
    "roboto-latin-600-normal.woff2",
    "roboto-condensed-latin-400-normal.woff2",
}


@dataclass(frozen=True)
class Sport:
    key: str
    query: str
    hooks: str
    tabs: tuple[str, ...]  # tab button selectors, in order
    tab_row: str
    module: str
    # The element whose bottom starts the 8px gap, and the one whose top ends it. For CFB
    # and NFL that is filter bar -> selection row; MLB has no filter bar, so its labelled
    # selection area takes the bar's place and the 8px gap runs to its summary line.
    bar: str
    below_bar: str
    # Selection row top .. summary bottom is the 64px band (CFB: the count line, 32px or 72px).
    band_top: str
    summary: str


CFB = Sport(
    "cfb",
    # Two compared people enable every tab (Bars and Butterfly are disabled with none).
    "?people=dale-harlow,kris-venn&mode=compare",
    "__testHooks",
    tuple(f"#tab-{v}" for v in ("scatter", "bars", "butterfly", "map", "crews")),
    "#chart-tabs",
    "#chart-module",
    "#toolbar",
    "#selection-bar",
    "#summary",
    "#summary",
)
NFL = Sport(
    "nfl",
    "?sport=nfl",
    "__nflTestHooks",
    tuple(f"#nfl-tab-{v}" for v in ("special", "crews", "viewership", "scatter")),
    "#nfl-chart-tabs",
    "#nfl-chart-area .nfl-chart-module",
    "#nfl-toolbar",
    "#nfl-selection-row",
    "#nfl-selection-row",
    "#nfl-summary",
)
MLB = Sport(
    "mlb",
    "?sport=mlb",
    "__mlbTestHooks",
    tuple(f"#mlb-tab-{v}" for v in ("apple", "postseason", "scatter")),
    "#mlb-chart-tabs",
    "#mlb-chart-area .nfl-chart-module",
    "#mlb-selection-area",
    "#mlb-summary",
    "#mlb-selection-area",
    "#mlb-summary",
)
SPORTS = (CFB, NFL, MLB)
SPORT_BY_KEY = {s.key: s for s in SPORTS}
TAB_CASES = [(s.key, i) for s in SPORTS for i in range(len(s.tabs))]
TAB_IDS = [f"{key}-{SPORT_BY_KEY[key].tabs[i].split('-')[-1]}" for key, i in TAB_CASES]


def _open(page: Page, base: str, sport: Sport, query: str | None = None) -> None:
    q = sport.query if query is None else query
    page.goto(f"{base}/index.html{q}")
    page.wait_for_function(f"window.{sport.hooks} && window.{sport.hooks}.ready === true")


def _select_tab(page: Page, sport: Sport, index: int) -> None:
    sel = sport.tabs[index]
    page.click(sel)
    page.wait_for_function(
        "(s) => document.querySelector(s).getAttribute('aria-selected') === 'true'", arg=sel
    )
    page.wait_for_timeout(250)


# ---------------------------------------------------------------------------
# V4: the 8px and 16px gaps, identical across tabs, sports and widths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize(("sport_key", "tab_index"), TAB_CASES, ids=TAB_IDS)
def test_gap_bar_to_selection_8_and_tabs_to_module_16(
    both_guarded_page: Page, both_site_url: str, sport_key: str, tab_index: int, width: int
) -> None:
    """V4: filter bar (MLB: selection area) bottom to selection row top is 8px and the
    tab row bottom to the first module top is 16px, at every width on every tab."""
    page = both_guarded_page
    sport = SPORT_BY_KEY[sport_key]
    page.set_viewport_size({"width": width, "height": 900})
    _open(page, both_site_url, sport)
    _select_tab(page, sport, tab_index)
    assert measure_gap(page, sport.bar, sport.below_bar) == pytest.approx(8, abs=0.5)
    assert measure_gap(page, sport.tab_row, sport.module) == pytest.approx(16, abs=0.5)


def _band_height(page: Page, sport: Sport) -> float:
    return float(
        page.evaluate(
            """([top, summary]) => document.querySelector(summary).getBoundingClientRect().bottom
              - document.querySelector(top).getBoundingClientRect().top""",
            [sport.band_top, sport.summary],
        )
    )


CFB_PEOPLE = ["dale-harlow", "kris-venn", "sam-delgado", "pat-rowan"]
NFL_PEOPLE = ["p00", "p01", "p02", "p03"]


@pytest.mark.parametrize("width", (1440, 1104, 768, 481))
@pytest.mark.parametrize("count", (0, 1, 4))
@pytest.mark.parametrize("sport_key", ("cfb", "nfl"))
def test_band_is_64px_with_zero_one_and_four_people(
    both_guarded_page: Page, both_site_url: str, sport_key: str, count: int, width: int
) -> None:
    """V4/C3: the selection band (row top to summary bottom) is 64px at 481px and up
    with no, one and four people picked."""
    page = both_guarded_page
    sport = SPORT_BY_KEY[sport_key]
    page.set_viewport_size({"width": width, "height": 900})
    people = (CFB_PEOPLE if sport_key == "cfb" else NFL_PEOPLE)[:count]
    if sport_key == "cfb":
        query = (
            ("?people=" + ",".join(people) + ("&mode=compare" if count > 1 else ""))
            if people
            else ""
        )
    else:
        query = "?sport=nfl" + (("&people=" + ",".join(people)) if people else "")
    _open(page, both_site_url, sport, query)
    if people:
        chip_sel = "#chips li" if sport_key == "cfb" else "#nfl-chips li"
        # CFB shows person chips on the count line only in compare mode (two or more here).
        shown = count if sport_key != "cfb" or count > 1 else 0
        assert page.locator(chip_sel).count() == shown
    expected = (32 if width >= 1104 else 72) if sport_key == "cfb" else 64
    assert _band_height(page, sport) == pytest.approx(expected, abs=0.5)


def test_mlb_selection_area_is_32px_with_summary_8px_below(
    both_guarded_page: Page, both_site_url: str
) -> None:
    """MLB's labelled area is the 32px row; its summary starts 8px below it (band 64)."""
    page = both_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, both_site_url, MLB)
    assert element_height(page, "#mlb-selection-area") == pytest.approx(32, abs=0.5)
    assert _band_height(page, MLB) == pytest.approx(64, abs=0.5)


# A changed value per CFB control, as a URL. The URL decoder snaps unknown values back to
# the default, so each case also asserts the trigger really shows the changed state.
CFB_CHANGES = {
    "seasons": "?seasons=2021-2025",
    "networks": "?networks=net-c",
    "kickoff": "?slot=prime",
    "role": "?people=dale-harlow&role=pbp",
    "conference": "?conferences=SEC",
    "school": "?school=northfield",
    "postseason": "?postseason=only",
    "game": "?game=bridge-game",
}
NFL_CHANGES = {
    "seasons": "&seasons=2024-2025",
    "team": "&team=f-gulls",
    "announcers": "&people=p00",
    "category": "&cat=tnf",
}


@pytest.mark.parametrize("control", sorted(CFB_CHANGES))
def test_cfb_filter_bar_height_is_constant_when_a_filter_changes(
    both_guarded_page: Page, both_site_url: str, control: str
) -> None:
    """C3: changing any CFB filter's value never changes the filter bar's height."""
    page = both_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, both_site_url, CFB)
    baseline = element_height(page, "#toolbar")
    _open(page, both_site_url, CFB, CFB_CHANGES[control])
    assert page.locator(f"#trigger-{control}.is-changed").count() == 1, control
    assert element_height(page, "#toolbar") == pytest.approx(baseline, abs=0.5)


@pytest.mark.parametrize("control", sorted(NFL_CHANGES))
def test_nfl_filter_bar_height_is_constant_when_a_filter_changes(
    both_guarded_page: Page, both_site_url: str, control: str
) -> None:
    page = both_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, both_site_url, NFL)
    baseline = element_height(page, "#nfl-toolbar")
    _open(page, both_site_url, NFL, "?sport=nfl" + NFL_CHANGES[control])
    assert page.locator(f"#nfl-trigger-{control}.is-changed").count() == 1, control
    assert element_height(page, "#nfl-toolbar") == pytest.approx(baseline, abs=0.5)


def test_filter_bar_height_is_constant_across_all_changes_together(
    both_guarded_page: Page, both_site_url: str
) -> None:
    """Every CFB control changed at once keeps the bar at its clean-load height."""
    page = both_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, both_site_url, CFB)
    baseline = element_height(page, "#toolbar")
    _open(
        page,
        both_site_url,
        CFB,
        "?people=dale-harlow&role=pbp&seasons=2021-2025&networks=net-c&slot=prime"
        "&conferences=SEC&school=northfield&postseason=only",
    )
    assert page.locator("#toolbar .filter-trigger.is-changed").count() >= 6
    assert element_height(page, "#toolbar") == pytest.approx(baseline, abs=0.5)


# ---------------------------------------------------------------------------
# V5: the same filter set on every tab, enabled, and persistent across tabs
# ---------------------------------------------------------------------------

_SERIALIZE = """(sel) => [...document.querySelectorAll(
  ['button', 'input', 'select'].map((t) => sel + ' ' + t).join(', '))].map((e) => ({
  id: e.id,
  tag: e.tagName,
  label: (e.querySelector('.filter-label') || e).textContent.trim(),
  disabled: e.disabled === true,
  ariaDisabled: e.getAttribute('aria-disabled'),
  hidden: e.hidden === true,
  visible: e.getClientRects().length > 0,
}))"""

CFB_CONTROLS = [
    "trigger-announcers",
    "trigger-seasons",
    "trigger-networks",
    "trigger-kickoff",
    "trigger-role",
    "trigger-conference",
    "trigger-school",
    "trigger-postseason",
    "trigger-game",
    "trigger-booth",
]
NFL_CONTROLS = [f"nfl-trigger-{k}" for k in ("announcers", "seasons", "category", "team", "booths")]


@pytest.mark.parametrize(
    ("sport", "bar", "controls"),
    [(CFB, "#toolbar", CFB_CONTROLS), (NFL, "#nfl-toolbar", NFL_CONTROLS)],
    ids=["cfb", "nfl"],
)
def test_filter_set_is_identical_and_enabled_on_every_tab(
    both_guarded_page: Page,
    both_site_url: str,
    sport: Sport,
    bar: str,
    controls: list[str],
) -> None:
    """V5/SHELL-03: every master control is present and enabled on every tab (NFL Booths on
    all four views), and the filter bar's DOM is the same serialization on every tab."""
    page = both_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, both_site_url, sport)
    serial: list[list[dict[str, Any]]] = []
    for i in range(len(sport.tabs)):
        _select_tab(page, sport, i)
        items: list[dict[str, Any]] = page.evaluate(_SERIALIZE, bar)
        by_id = {it["id"]: it for it in items}
        for cid in controls:
            assert cid in by_id, f"{cid} missing on {sport.tabs[i]}"
            it = by_id[cid]
            assert it["visible"], f"{cid} not visible on {sport.tabs[i]}"
            assert not it["disabled"] and it["ariaDisabled"] != "true", (
                f"{cid} disabled on {sport.tabs[i]}"
            )
            assert not it["hidden"]
        serial.append(items)
    assert all(s == serial[0] for s in serial), "filter bar DOM differs between tabs"


def test_mlb_selection_area_is_identical_on_both_tabs(
    both_guarded_page: Page, both_site_url: str
) -> None:
    page = both_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, both_site_url, MLB)
    serial = []
    for i in range(len(MLB.tabs)):
        _select_tab(page, MLB, i)
        serial.append(page.evaluate(_SERIALIZE, "#mlb-selection-area"))
        assert (
            page.locator(".mlb-selection-note").inner_text()
            == "Filters: none. MLB is selection-driven; pick a row below."
        )
    assert serial[0] == serial[1]


def test_cfb_seasons_filter_picked_on_the_first_tab_survives_every_tab(
    both_guarded_page: Page, both_site_url: str
) -> None:
    """V5: pick Seasons through the popover on the first tab; it stays set on the rest."""
    page = both_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, both_site_url, CFB)
    page.click("#trigger-seasons")
    page.wait_for_function("document.getElementById('pop-seasons').matches(':popover-open')")
    page.select_option("#season-from", "2021")
    page.keyboard.press("Escape")
    page.wait_for_function("document.querySelector('#trigger-seasons.is-changed') !== null")
    for i in range(len(CFB.tabs)):
        _select_tab(page, CFB, i)
        assert page.locator("#trigger-seasons.is-changed").count() == 1, CFB.tabs[i]
        assert "seasons=2021-" in page.evaluate("location.search")


def test_nfl_seasons_filter_set_on_the_first_tab_survives_every_tab(
    both_guarded_page: Page, both_site_url: str
) -> None:
    page = both_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, both_site_url, NFL)
    page.evaluate("window.__nflTestHooks.setState({ seasons: [2024, 2025] })")
    page.wait_for_function("document.querySelector('#nfl-trigger-seasons.is-changed') !== null")
    for i in range(len(NFL.tabs)):
        _select_tab(page, NFL, i)
        assert page.evaluate("window.__nflTestHooks.getState().seasons") == [2024, 2025]
        assert page.locator("#nfl-trigger-seasons.is-changed").count() == 1, NFL.tabs[i]
        assert "seasons=2024-2025" in page.evaluate("location.search")


# ---------------------------------------------------------------------------
# Overlap and horizontal scroll at 768 and 1024
# ---------------------------------------------------------------------------

_BOXES = """(sels) => sels.map((s) => {
  const r = document.querySelector(s).getBoundingClientRect();
  return { s, left: r.left, right: r.right, top: r.top, bottom: r.bottom };
})"""


@pytest.mark.parametrize("width", (768, 1024))
@pytest.mark.parametrize("sport_key", ("cfb", "nfl", "mlb"))
def test_no_overlap_between_shell_regions_and_no_horizontal_scroll(
    both_guarded_page: Page, both_site_url: str, sport_key: str, width: int
) -> None:
    """Header, filter bar, selection row, tabs and module never intersect, and the page
    never scrolls sideways, on every tab at 768 and 1024px."""
    page = both_guarded_page
    sport = SPORT_BY_KEY[sport_key]
    page.set_viewport_size({"width": width, "height": 900})
    _open(page, both_site_url, sport)
    if sport.key in ("mlb", "cfb"):
        # CFB's selection bar wraps its count line, so only the line itself is compared.
        regions = ["#topbar", sport.bar, sport.summary, sport.tab_row, sport.module]
    else:
        regions = [
            "#topbar",
            sport.bar,
            sport.below_bar,
            sport.summary,
            sport.tab_row,
            sport.module,
        ]
    for i in range(len(sport.tabs)):
        _select_tab(page, sport, i)
        boxes: list[dict[str, Any]] = page.evaluate(_BOXES, regions)
        for a_i, a in enumerate(boxes):
            for b in boxes[a_i + 1 :]:
                overlap_x = min(a["right"], b["right"]) - max(a["left"], b["left"])
                overlap_y = min(a["bottom"], b["bottom"]) - max(a["top"], b["top"])
                assert not (overlap_x > 0.5 and overlap_y > 0.5), (a["s"], b["s"], sport.tabs[i])
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        ), f"horizontal scroll on {sport.tabs[i]} at {width}"


@pytest.mark.parametrize("width", (1440, 1280, 1104, 1024, 768))
def test_cfb_filter_bar_row_count_is_recorded(
    both_guarded_page: Page, both_site_url: str, width: int, record_property: Any
) -> None:
    """UI-SPEC asks for the CFB filter bar's row count at five widths; recorded, and
    exact: one row from 1280px, two below (Round 3b, layout depends only on width)."""
    page = both_guarded_page
    page.set_viewport_size({"width": width, "height": 900})
    _open(page, both_site_url, CFB)
    rows = page.evaluate(
        """new Set([...document.querySelectorAll('#toolbar .fgroup-row .filter-trigger')]
          .filter((e) => e.getClientRects().length > 0)
          .map((e) => Math.round(e.getBoundingClientRect().top))).size"""
    )
    record_property("cfb_filter_bar_rows", rows)
    print(f"CFB_ROWS width={width} rows={rows}")
    assert rows == (1 if width >= 1280 else 2)


# ---------------------------------------------------------------------------
# V3: type scale, weights and requests
# ---------------------------------------------------------------------------

_WALK = """() => {
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'TITLE'].includes(el.tagName)) continue;
    const isField = ['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName);
    let text = '';
    for (const n of el.childNodes) if (n.nodeType === 3) text += n.nodeValue;
    text = text.trim();
    if (!text && !isField) continue;
    if (el.getClientRects().length === 0) continue;
    // Screen-reader-only text (the accessible data tables) is clipped to 1px, not seen.
    if (el.closest('.visually-hidden')) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 1 && r.height <= 1) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden') continue;
    out.push({
      tag: el.tagName.toLowerCase(),
      cls: String(el.getAttribute('class') || ''),
      text: text.slice(0, 30),
      size: parseFloat(cs.fontSize),
      weight: cs.fontWeight,
      inSheet: !!el.closest('.filters-sheet'),
      field: isField,
    });
  }
  return out;
}"""

ALLOWED_SIZES = {12.0, 14.0, 20.0, 22.0, 27.0}
ALLOWED_WEIGHTS = {"400", "600"}


@pytest.mark.parametrize("width", (1440, 390))
@pytest.mark.parametrize("sport_key", ("cfb", "nfl", "mlb"))
def test_type_scale_weights_and_requests_across_every_view(
    both_guarded_page: Page, both_site_url: str, sport_key: str, width: int
) -> None:
    """V3: no text below 12px, only 12/14/20/22/27 (plus 16px inputs in the phone sheet), only
    weights 400 and 600, only the four font files requested, and nothing off-origin."""
    page = both_guarded_page
    sport = SPORT_BY_KEY[sport_key]
    urls: list[str] = []
    page.on("request", lambda r: urls.append(r.url))
    page.set_viewport_size({"width": width, "height": 900})
    _open(page, both_site_url, sport)
    bad: list[str] = []
    sizes: set[float] = set()
    weights: set[str] = set()
    for i in range(len(sport.tabs)):
        _select_tab(page, sport, i)
        page.wait_for_timeout(250)
        for item in page.evaluate(_WALK):
            sizes.add(item["size"])
            weights.add(item["weight"])
            ok_size = item["size"] in ALLOWED_SIZES or (
                item["size"] == 16.0 and item["field"] and item["inSheet"]
            )
            if not ok_size or item["size"] < 12 or item["weight"] not in ALLOWED_WEIGHTS:
                bad.append(f"{sport.tabs[i]} {item}")
    assert not bad, "\n".join(bad[:20])
    assert weights <= ALLOWED_WEIGHTS and len(weights) == 2, weights
    assert min(sizes) >= 12
    fonts = {u.split("?")[0].rsplit("/", 1)[-1] for u in urls if ".woff2" in u}
    assert fonts <= FONT_FILES, fonts - FONT_FILES
    assert fonts, "no woff2 file was requested"
    assert all(u.startswith(both_site_url + "/") or u.startswith(("data:", "blob:")) for u in urls)


# ---------------------------------------------------------------------------
# V8 (runtime) contrast of the changed control; font-swap layout shift
# ---------------------------------------------------------------------------

_COLORS = """(sel) => {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const rgba = (css) => {
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = '#000';
    ctx.fillStyle = css;
    ctx.fillRect(0, 0, 1, 1);
    const d = ctx.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3] / 255];
  };
  const el = document.querySelector(sel);
  let backdrop = [255, 255, 255, 1];
  for (let p = el.parentElement; p; p = p.parentElement) {
    const c = rgba(getComputedStyle(p).backgroundColor);
    if (c[3] > 0) { backdrop = c; break; }
  }
  const out = (node) => rgba(getComputedStyle(node).color);
  return {
    fill: rgba(getComputedStyle(el).backgroundColor),
    border: rgba(getComputedStyle(el).borderTopColor),
    label: out(el.querySelector('.filter-label')),
    value: out(el.querySelector('.filter-value')),
    backdrop,
  };
}"""


def _luminance(rgb: list[float]) -> float:
    def ch(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * ch(rgb[0]) + 0.7152 * ch(rgb[1]) + 0.0722 * ch(rgb[2])


def _over(top: list[float], under: list[float]) -> list[float]:
    a = top[3]
    return [top[i] * a + under[i] * (1 - a) for i in range(3)]


def _ratio(a: list[float], b: list[float]) -> float:
    la, lb = _luminance(a) + 0.05, _luminance(b) + 0.05
    return max(la, lb) / min(la, lb)


@pytest.mark.parametrize(
    ("sport", "selector", "query"),
    [
        (CFB, "#trigger-seasons", "?seasons=2021-2025"),
        (NFL, "#nfl-trigger-seasons", "?sport=nfl&seasons=2024-2025"),
    ],
    ids=["cfb", "nfl"],
)
def test_changed_control_text_meets_4_5_to_1_on_its_fill(
    both_guarded_page: Page,
    both_site_url: str,
    sport: Sport,
    selector: str,
    query: str,
    record_property: Any,
) -> None:
    """V8 runtime: the changed trigger's label and value colour on its fill are >= 4.5:1."""
    page = both_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, both_site_url, sport, query)
    assert page.locator(f"{selector}.is-changed").count() == 1
    colors = page.evaluate(_COLORS, selector)
    fill = _over(colors["fill"], colors["backdrop"])
    label_ratio = _ratio(_over(colors["label"], fill), fill)
    value_ratio = _ratio(_over(colors["value"], fill), fill)
    border_ratio = _ratio(_over(colors["border"], colors["backdrop"]), colors["backdrop"])
    record_property("changed_label_contrast", round(label_ratio, 2))
    print(
        f"CONTRAST {sport.key} label={label_ratio:.2f} value={value_ratio:.2f} "
        f"border_vs_page={border_ratio:.2f}"
    )
    assert label_ratio >= 4.5
    assert value_ratio >= 4.5


_CLS_INIT = """
window.__shifts = [];
window.__chromeShift = 0;
window.__totalShift = 0;
new PerformanceObserver((list) => {
  for (const e of list.getEntries()) {
    if (e.hadRecentInput) continue;
    window.__totalShift += e.value;
    // A source that already had a box and moved is a shift of existing chrome (what a font
    // swap does). A source whose previous box was empty is a node appearing when the app
    // first renders its triggers (the filter caret), which is not a font swap.
    const inChrome = (e.sources || []).some((s) => s.node && s.node.nodeType === 1
      && s.node.closest && s.node.closest('header, #topbar, #toolbar, #chart-tabs')
      && s.previousRect.width * s.previousRect.height > 0);
    if (inChrome) window.__chromeShift += e.value;
    window.__shifts.push({ value: e.value, inChrome,
      nodes: (e.sources || []).map((s) => s.node && (s.node.id || s.node.tagName)), t: e.startTime,
      rects: (e.sources || []).map((s) => [
        s.previousRect.top, s.previousRect.left, s.currentRect.top, s.currentRect.left,
      ]) });
  }
}).observe({ type: 'layout-shift', buffered: true });
"""


def test_font_swap_causes_no_layout_shift_in_header_filter_bar_or_tab_row(
    both_guarded_page: Page, both_site_url: str, record_property: Any
) -> None:
    """Fonts layout-shift guard: on a throttled (Slow 3G) load the header, #toolbar and
    #chart-tabs never move when the web fonts swap in; the total page CLS is recorded."""
    page = both_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    page.add_init_script(_CLS_INIT)
    cdp = page.context.new_cdp_session(page)
    cdp.send("Network.enable")
    # A slow CPU, like the CI runner's, lets the half-parsed page paint while a script below
    # the toolbar still downloads; without it a fast machine never shows that first paint.
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 6})
    cdp.send(
        "Network.emulateNetworkConditions",
        {
            "offline": False,
            "latency": 400,
            "downloadThroughput": 400 * 1024 / 8,
            "uploadThroughput": 400 * 1024 / 8,
        },
    )
    page.goto(f"{both_site_url}/index.html", timeout=180_000)
    page.wait_for_function(
        "window.__testHooks && window.__testHooks.ready === true", timeout=180_000
    )
    page.wait_for_function("document.fonts.status === 'loaded'", timeout=60_000)
    page.wait_for_timeout(500)
    cdp.send(
        "Network.emulateNetworkConditions",
        {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1},
    )
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
    chrome = page.evaluate("window.__chromeShift")
    total = page.evaluate("window.__totalShift")
    shifts = page.evaluate("window.__shifts")
    record_property("page_cls", round(total, 4))
    print(f"CLS total={total:.4f} chrome={chrome:.4f} entries={shifts}")
    fonts = page.evaluate("[...document.fonts].filter((f) => f.status === 'loaded').length")
    assert fonts >= 1, "no web font loaded during the throttled load"
    assert chrome == 0, shifts


@pytest.mark.parametrize("sport_key", [s.key for s in SPORTS])
def test_summary_line_is_filled_at_rest_in_every_sport(
    both_guarded_page: Page, both_site_url: str, sport_key: str
) -> None:
    """With nothing selected every sport's summary line reads "N rated of M games", so no
    sport leaves an empty gap above its tabs (CFB's own line is the model)."""
    page = both_guarded_page
    sport = SPORT_BY_KEY[sport_key]
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, both_site_url, sport)
    page.wait_for_function(
        "(s) => /^[\\d,]+ rated of [\\d,]+ games?/.test("
        "document.querySelector(s).textContent.trim())",
        arg=sport.summary,
    )


@pytest.mark.parametrize("sport_key", ("nfl", "mlb"))
def test_summary_line_reads_zero_matches_for_an_empty_selection(
    both_guarded_page: Page, both_site_url: str, sport_key: str
) -> None:
    """A selection that matches no game reads "0 games match", never the at-rest
    "N rated of M games" line (which would contradict the table's filtered empty state)."""
    page = both_guarded_page
    sport = SPORT_BY_KEY[sport_key]
    page.set_viewport_size({"width": 1440, "height": 900})
    _open(page, both_site_url, sport)
    page.evaluate(
        f"window.{sport.hooks}.setState({{ selection: {{ label: 'Nothing', games: [] }} }})"
    )
    page.wait_for_function(
        "(s) => document.querySelector(s).textContent.trim() === '0 games match'",
        arg=sport.summary,
    )
