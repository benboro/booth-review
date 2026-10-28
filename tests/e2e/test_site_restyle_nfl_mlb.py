"""Phase 26 plan 08: the NFL and MLB shells carry the CFB restyle.

NFL: three ruled groups of boxless entries (Broadcast, Matchup, Calendar), fixed 148px entries with
Announcers 250px, the count line with Clear all filters last, and the phone panel. MLB (flag-on
fixture build only): the 32px selection band with square chips and a right-anchored clear. Every
"stays put" check compares whole-pixel snapshots with `==`, in light and dark. Synthetic data only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from dark_checks import set_theme
from layout_shift import WAIT_TWO_FRAMES
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

NFL_GROUPS = [
    ("Broadcast", ["Announcers", "Booths"]),
    ("Matchup", ["Team", "Category"]),
    ("Calendar", ["Seasons"]),
]
NFL_DEFAULTS = {
    "announcers": "Any",
    "booths": "Any",
    "team": "Any",
    "category": "All",
    "seasons": "2024–2026",  # noqa: RUF001
}

PICK = {"people": ["p00"]}
LONG_PICK = {"teams": ["f-gulls"], "cats": ["intl"], "people": ["p00", "p01"]}

_SNAPSHOT_JS = """() => {
  const rect = (sel) => document.querySelector(sel).getBoundingClientRect();
  return {
    tabs: Math.round(rect('#nfl-chart-tabs').top + window.scrollY),
    toolbar_bottom: Math.round(rect('#nfl-toolbar').bottom + window.scrollY),
    group_x: [...document.querySelectorAll('#nfl-toolbar .fgroup')]
      .map((g) => Math.round(g.getBoundingClientRect().left)),
    entry_x: [...document.querySelectorAll('#nfl-toolbar .filter-trigger')]
      .map((b) => Math.round(b.getBoundingClientRect().left)),
    clear_x: Math.round(rect('#nfl-clear-filters').left),
    summary_h: Math.round(rect('#nfl-summary-band').height),
  };
}"""

_ENTRY_JS = """(key) => {
  const b = document.getElementById('nfl-trigger-' + key);
  const v = b.querySelector('.filter-value');
  const cs = getComputedStyle(b);
  return {
    label: b.querySelector('.filter-label').textContent, value: v.textContent,
    changed: b.classList.contains('is-changed'), title: b.title,
    aria: b.getAttribute('aria-label'), truncated: v.scrollWidth > v.clientWidth,
    width: b.getBoundingClientRect().width, height: b.getBoundingClientRect().height,
    line: cs.borderBottomWidth, disabled: b.getAttribute('aria-disabled'), cursor: cs.cursor,
    valueColor: getComputedStyle(v).color, lineColor: cs.borderBottomColor,
  };
}"""


def _snap(page: Page) -> dict[str, Any]:
    page.evaluate(WAIT_TWO_FRAMES)
    out: dict[str, Any] = page.evaluate(_SNAPSHOT_JS)
    return out


def _set(page: Page, patch: dict[str, Any]) -> None:
    page.evaluate("(patch) => window.__nflTestHooks.setState(patch)", patch)
    page.evaluate(WAIT_TWO_FRAMES)


def _entry(page: Page, key: str) -> dict[str, Any]:
    out: dict[str, Any] = page.evaluate(_ENTRY_JS, key)
    return out


def _open(page: Page, open_nfl_app: Callable[..., None], width: int, query: str = "") -> None:
    page.set_viewport_size({"width": width, "height": 900})
    open_nfl_app(page, f"?sport=nfl{query}")
    page.evaluate("() => document.fonts.ready")


# ---- NFL desktop: grouped bar ----


@pytest.mark.parametrize("width", [1440, 1024])
def test_nfl_groups_labels_and_order(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], width: int
) -> None:
    _open(nfl_guarded_page, open_nfl_app, width)
    groups = nfl_guarded_page.eval_on_selector_all(
        "#nfl-toolbar .fgroup",
        """els => els.map(g => [g.querySelector('.fgroup-label').textContent,
          [...g.querySelectorAll('.filter-label')].map(l => l.textContent)])""",
    )
    assert groups == [[name, labels] for name, labels in NFL_GROUPS]
    roles = nfl_guarded_page.eval_on_selector_all(
        "#nfl-toolbar .fgroup",
        "els => els.map(g => [g.getAttribute('role'),"
        " document.getElementById(g.getAttribute('aria-labelledby')).textContent])",
    )
    assert roles == [["group", name] for name, _ in NFL_GROUPS]


def test_nfl_entries_are_fixed_width_and_read_their_defaults(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    _open(nfl_guarded_page, open_nfl_app, 1440)
    for key, word in NFL_DEFAULTS.items():
        entry = _entry(nfl_guarded_page, key)
        assert entry["value"] == word, key
        assert not entry["changed"], key
        assert entry["width"] == (250 if key == "announcers" else 148), key
        assert entry["height"] == 44, key
        assert entry["title"] == entry["aria"] == entry["label"], key


def test_nfl_a_pick_shows_its_name_in_the_accent(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    _open(nfl_guarded_page, open_nfl_app, 1440)
    _set(nfl_guarded_page, {"people": ["p00", "p01"], "teams": ["f-gulls"]})
    two = _entry(nfl_guarded_page, "announcers")
    assert two["value"] == "Ada Quill +1"
    assert two["title"] == two["aria"] == "Announcers: Ada Quill, Ben Marlow"
    one = _entry(nfl_guarded_page, "team")
    assert one["changed"] and one["value"] == "Harbor City Gulls"
    assert (one["line"], one["height"]) == ("2px", 44)
    assert one["valueColor"] == one["lineColor"]
    assert _entry(nfl_guarded_page, "booths")["value"] == "Any"


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width", [1440, 1024])
def test_nfl_nothing_moves_across_picks_and_this_weekend(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], width: int, theme: str
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app, width)
    set_theme(page, theme)
    base = _snap(page)
    for name, patch in (("pick", PICK), ("long pick", LONG_PICK)):
        _set(page, patch)
        assert _snap(page) == base, name
        _set(page, {"people": [], "teams": [], "cats": []})
    _set(page, {"view": "weekend"})
    assert _snap(page) == base, "this weekend"
    _set(page, {"view": "special", **LONG_PICK})
    assert _snap(page) == base, "back with a long pick"


@pytest.mark.parametrize("width", [1440, 1024])
def test_nfl_a_long_pick_truncates_inside_its_entry(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], width: int
) -> None:
    _open(nfl_guarded_page, open_nfl_app, width)
    base = _snap(nfl_guarded_page)
    _set(nfl_guarded_page, {"cats": ["intl"]})
    entry = _entry(nfl_guarded_page, "category")
    assert entry["changed"] and entry["truncated"], entry
    assert entry["title"] == "Category: International (any window)"
    assert _snap(nfl_guarded_page) == base


def test_nfl_this_weekend_greys_seasons_and_category_and_they_do_not_open(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app, 1440, "&view=weekend")
    for key in ("seasons", "category"):
        entry = _entry(page, key)
        assert entry["disabled"] == "true", key
        assert entry["cursor"] == "not-allowed", key
        page.click(f"#nfl-trigger-{key}", force=True)
        page.evaluate(WAIT_TWO_FRAMES)
        assert not page.locator(f"#nfl-pop-{key}").evaluate("e => e.matches(':popover-open')")
    for key in ("announcers", "booths", "team"):
        assert _entry(page, key)["disabled"] is None, key


def test_nfl_bar_rows_depend_only_on_the_viewport(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    rows_js = """() => new Set([...document.querySelectorAll('#nfl-toolbar .filter-trigger')]
      .map((b) => Math.round(b.getBoundingClientRect().top))).size"""
    for width, rows in ((1440, 1), (1024, 1), (800, 2), (600, 3)):
        _open(page, open_nfl_app, width)
        assert page.evaluate(rows_js) == rows, width
        _set(page, LONG_PICK)
        assert page.evaluate(rows_js) == rows, width


# ---- NFL count line ----


@pytest.mark.parametrize("width", [1440, 1024])
def test_nfl_clear_all_filters_is_last_and_never_moves(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], width: int
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app, width)
    last = page.evaluate(
        "document.querySelector('#nfl-summary-band .sum-right').lastElementChild.id"
    )
    assert last == "nfl-clear-filters"
    assert page.locator("#nfl-selection-row").count() == 0
    xs = []
    for patch in ({}, PICK, LONG_PICK):
        _set(page, {"people": [], "teams": [], "cats": [], **patch})
        xs.append(_snap(page)["clear_x"])
    assert len(set(xs)) == 1, xs
    box = page.locator("#nfl-clear-filters").bounding_box()
    right = page.locator("#nfl-summary-band .sum-right").bounding_box()
    assert box is not None and right is not None
    assert abs(box["x"] + box["width"] - (right["x"] + right["width"])) <= 1


def test_nfl_desktop_count_line_shows_no_person_or_booth_chips(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    """Answer 8: the pick already shows its name, and NFL has no compare mode (CFB rule)."""
    page = nfl_guarded_page
    _open(page, open_nfl_app, 1440)
    assert _snap(page)["summary_h"] == 32
    base = _snap(page)
    _set(page, PICK)
    assert page.locator("#nfl-summary-band #nfl-chips").is_hidden()
    assert (
        page.locator("#nfl-summary-band #nfl-chips .chip").count() == 1
    )  # kept for the phone strip
    assert page.locator("#nfl-clear-filters").is_visible()
    assert _snap(page) == base  # zero layout shift, Clear all filters keeps its x
    page.set_viewport_size({"width": 1024, "height": 900})
    page.evaluate(WAIT_TWO_FRAMES)
    assert _snap(page)["summary_h"] == 72
    assert page.locator("#nfl-chips").is_hidden()


# ---- NFL phone ----


def test_nfl_phone_button_summary_strip_and_grouped_sheet(
    nfl_mobile_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_mobile_page
    open_nfl_app(page)
    page.evaluate("() => document.fonts.ready")
    base = _snap(page)
    assert base["summary_h"] == 24
    assert page.inner_text("#nfl-filters-button") == "Filters"
    _set(page, {"teams": ["f-gulls"], "cats": ["agotw"]})
    assert page.inner_text("#nfl-filters-button") == "Filters (2 changed)"
    after = _snap(page)
    assert after["tabs"] == base["tabs"] and after["summary_h"] == 24
    assert not page.locator("#nfl-summary-band .sum-right").is_visible()
    page.click("#nfl-filters-button")
    page.wait_for_selector("#nfl-filters-sheet:popover-open")
    labels = page.locator("#nfl-filters-sheet .sheet-group-label").all_inner_texts()
    assert labels == ["Broadcast", "Matchup", "Calendar"]
    strip = page.locator("#nfl-people-strip").bounding_box()
    assert strip is not None and strip["height"] == 112
    assert page.locator("#nfl-people-strip #nfl-chips").count() == 1
    assert page.locator("#nfl-people-strip #nfl-clear-selection").count() == 1
    chips = page.locator("#nfl-filter-chips .chip-text")
    assert chips.count() == 2
    for text in chips.all_inner_texts():
        assert "·" not in text
    # The strip keeps its height with and without a person picked.
    _set(page, {"people": ["p00"]})
    strip = page.locator("#nfl-people-strip").bounding_box()
    assert strip is not None and strip["height"] == 112


def test_nfl_phone_chip_wording_follows_the_fit(
    nfl_mobile_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_mobile_page
    open_nfl_app(page)
    page.set_viewport_size({"width": 320, "height": 800})
    _set(page, {"people": ["p00", "p01", "p02", "p03", "p04"], "seasons": [2025, 2026]})
    page.click("#nfl-filters-button")
    page.wait_for_selector("#nfl-filters-sheet:popover-open")
    page.evaluate(WAIT_TWO_FRAMES)
    people = page.locator("#nfl-filter-chips .chip-text[data-name='Announcers']")
    assert people.get_attribute("data-form") == "short"
    assert people.inner_text() == "Announcers (5)"
    # Seasons fits as the long form, and neither chip ever shows a middle dot.
    seasons = page.locator("#nfl-filter-chips .chip-text[data-name='Seasons']")
    assert seasons.get_attribute("data-form") == "long"
    assert seasons.inner_text() == "Seasons: 2025–2026"  # noqa: RUF001
    # Two people fit on the chip: the long form returns, with the names.
    _set(page, {"people": ["p00", "p01"]})
    people = page.locator("#nfl-filter-chips .chip-text[data-name='Announcers']")
    assert people.get_attribute("data-form") == "long"
    assert people.inner_text() == "Announcers: Ada Quill, Ben Marlow"
    for text in page.locator("#nfl-filter-chips .chip-text").all_inner_texts():
        assert "·" not in text


def test_nfl_seasons_chip_never_collapses_to_a_count(
    nfl_mobile_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_mobile_page
    open_nfl_app(page)
    page.set_viewport_size({"width": 240, "height": 800})
    _set(page, {"seasons": [2025, 2026], "people": ["p00", "p01", "p02"]})
    page.click("#nfl-filters-button")
    page.wait_for_selector("#nfl-filters-sheet:popover-open")
    page.evaluate(WAIT_TWO_FRAMES)
    seasons = page.locator("#nfl-filter-chips .chip-text[data-name='Seasons']")
    assert seasons.get_attribute("data-count") == ""
    assert seasons.get_attribute("data-form") == "long"
    assert "(1)" not in seasons.inner_text()
    people = page.locator("#nfl-filter-chips .chip-text[data-name='Announcers']")
    assert people.get_attribute("data-count") == "3"


def test_nfl_scatter_tooltip_date_matches_the_panel(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    """Phase 26 panel F5: the tooltip writes the date as the panel does (AP form with the year)."""
    page = nfl_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    open_nfl_app(page, "?sport=nfl&view=scatter")
    page.wait_for_selector("#nfl-view-scatter .js-plotly-plot")
    lines: list[str] = page.evaluate(
        """() => {
          const gd = document.querySelector('#nfl-view-scatter .js-plotly-plot');
          const seen = new Set();
          for (const tr of gd.data) {
            for (const k of tr.customdata ?? []) {
              if (!Number.isInteger(k)) continue;
              const event = { clientX: 300, clientY: 200 };
              gd.emit('plotly_hover', { points: [{ customdata: k }], event });
              const tip = document.getElementById('chart-tooltip');
              if (!tip || tip.hidden) continue;
              for (const c of tip.children) {
                if (/, Week \\d+$/.test(c.textContent)) seen.add(c.textContent);
              }
            }
          }
          return [...seen];
        }"""
    )
    assert "Sun. Sept. 8, 2024, 1:00 pm ET, Week 1" in lines, lines
    assert all(" PM " not in line and not line.startswith("Sep ") for line in lines)


def test_nfl_clicking_a_chip_keeps_the_sheet_open_and_reaches_its_section(
    nfl_mobile_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_mobile_page
    open_nfl_app(page)
    _set(page, {"teams": ["f-gulls"]})
    page.click("#nfl-filters-button")
    page.wait_for_selector("#nfl-filters-sheet:popover-open")
    chip = page.locator("#nfl-filter-chips .filter-chip").first
    assert chip.get_attribute("popovertarget") is None
    chip.click()
    page.evaluate(WAIT_TWO_FRAMES)
    assert page.evaluate(
        "() => document.getElementById('nfl-filters-sheet').matches(':popover-open')"
    )
    focused = page.evaluate("() => document.activeElement.closest('[id^=nfl-filter-]')?.id")
    assert focused == "nfl-filter-team-sheet"


def test_nfl_clearing_all_filters_leaves_no_dot_wording(
    nfl_mobile_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_mobile_page
    open_nfl_app(page)
    _set(page, {"teams": ["f-gulls"]})
    page.click("#nfl-filters-button")
    page.wait_for_selector("#nfl-filters-sheet:popover-open")
    page.click("#nfl-filters-sheet .nfl-sheet-clear")
    assert page.inner_text("#nfl-filters-button") == "Filters"
    assert page.locator("#nfl-filter-chips li").all_inner_texts() == ["No filters changed"]


# ---- MLB (flag-on fixture build) ----

_MLB_JS = """() => {
  const area = document.getElementById('mlb-selection-area');
  const chip = document.querySelector('#mlb-chips > .chip');
  const clear = document.getElementById('mlb-clear-selection');
  const cs = chip ? getComputedStyle(chip) : null;
  const a = area.getBoundingClientRect();
  const c = clear.getBoundingClientRect();
  return {
    areaH: a.height,
    chipRadius: cs && cs.borderTopLeftRadius,
    chipBg: cs && cs.backgroundColor,
    chipBorder: cs && cs.borderTopWidth,
    clearRightGap: Math.round(a.right - c.right),
    clearVisible: c.width > 0,
    summaryH: document.getElementById('mlb-summary').getBoundingClientRect().height,
  };
}"""


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width", [1440, 390])
def test_mlb_band_chips_and_clear(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None], width: int, theme: str
) -> None:
    page = mlb_guarded_page
    page.set_viewport_size({"width": width, "height": 900})
    open_mlb_app(page, "?sport=mlb&view=apple")
    page.evaluate("() => document.fonts.ready")
    set_theme(page, theme)
    quiet: dict[str, Any] = page.evaluate(_MLB_JS)
    assert quiet["areaH"] == 32
    assert page.locator("#mlb-toolbar").is_hidden()
    page.evaluate(
        "() => window.__mlbTestHooks.setState({ selection: { games: [0], label: 'Fixture pick' } })"
    )
    page.evaluate(WAIT_TWO_FRAMES)
    picked: dict[str, Any] = page.evaluate(_MLB_JS)
    assert picked["areaH"] == 32 and picked["summaryH"] == quiet["summaryH"]
    assert picked["chipRadius"] == "3px"
    assert picked["chipBorder"] == "1px"
    assert picked["chipBg"] == "rgba(0, 0, 0, 0)"
    assert picked["clearVisible"]
    gutter = 0
    assert picked["clearRightGap"] == gutter


_FRAME_JS = """(id) => {
  const cs = getComputedStyle(document.getElementById(id));
  return { border: [cs.borderTopWidth, cs.borderRightWidth, cs.borderBottomWidth, cs.borderLeftWidth],
    borderColor: cs.borderTopColor, radius: cs.borderTopLeftRadius, shadow: cs.boxShadow,
    padding: [cs.paddingTop, cs.paddingRight, cs.paddingBottom, cs.paddingLeft],
    marginBottom: cs.marginBottom };
}"""


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize(("width", "pad"), [(1440, ("20px", "24px")), (390, ("16px", "16px"))])
def test_mlb_matched_games_has_cfbs_module_frame(
    mlb_guarded_page: Page,
    open_mlb_app: Callable[..., None],
    width: int,
    pad: tuple[str, str],
    theme: str,
) -> None:
    """Answer 10a: the same frame as CFB's Matched games module."""
    page = mlb_guarded_page
    page.set_viewport_size({"width": width, "height": 900})
    open_mlb_app(page, "?sport=mlb&view=apple")
    page.evaluate("() => document.fonts.ready")
    set_theme(page, theme)
    mlb: dict[str, Any] = page.evaluate(_FRAME_JS, "mlb-matched-games")
    assert mlb["border"] == ["1px"] * 4
    assert mlb["radius"] == "0px" and mlb["shadow"] == "none"
    assert mlb["padding"] == [pad[0], pad[1], pad[0], pad[1]]
    assert mlb["marginBottom"] == "32px"
    # Same border colour as the other modules (the --rule token).
    chart = page.evaluate(
        "() => getComputedStyle(document.querySelector('#mlb-chart-area .module')).borderTopColor"
    )
    assert mlb["borderColor"] == chart
