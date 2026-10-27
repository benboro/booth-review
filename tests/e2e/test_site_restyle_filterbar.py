"""Phase 26 round 3b: the CFB filter bar is three groups of boxless label-over-value entries.

Part 1, structure: rows per width, 82px bar, fixed 40/30/30% groups, group labels and order.
Part 2, entry text and states: defaults, picks, the compare count, truncation, This weekend
greying, contrast, and a 0px layout snapshot across every pick state. Synthetic fixtures only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from contrast import ratio
from dark_checks import set_theme
from layout_shift import layout_snapshot, set_state
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

GROUPS = {
    "broadcast": ("Broadcast", ["announcers", "networks", "booth", "role"]),
    "matchup": ("Matchup", ["conference", "school", "game"]),
    "calendar": ("Calendar", ["seasons", "kickoff", "postseason"]),
}
ORDER = [name for _, names in GROUPS.values() for name in names]

_ENTRY_RECTS_JS = """() => [...document.querySelectorAll('#toolbar .fgroup-row .filter-trigger')]
  .map((b) => ({id: b.id.replace('trigger-', ''), top: Math.round(b.getBoundingClientRect().top),
                left: Math.round(b.getBoundingClientRect().left),
                height: b.getBoundingClientRect().height}))"""

_GROUP_RECTS_JS = """() => {
  const bar = document.getElementById('toolbar');
  const cs = getComputedStyle(bar);
  const content = bar.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  return {
    content,
    height: bar.getBoundingClientRect().height,
    groups: [...bar.querySelectorAll('.fgroup')].map((g) => g.getBoundingClientRect().width),
  };
}"""


def _open(page: Page, open_app: Callable[..., None], width: int, query: str = "") -> None:
    page.set_viewport_size({"width": width, "height": 900})
    open_app(page, query)
    page.evaluate("() => document.fonts.ready")


def _rows(page: Page) -> int:
    rects: list[dict[str, Any]] = page.evaluate(_ENTRY_RECTS_JS)
    return len({r["top"] for r in rects})


# ---- Part 1: structure ----


@pytest.mark.parametrize("width", [1440, 1280])
def test_one_row_82px_bar_and_fixed_group_widths(
    guarded_page: Page, open_app: Callable[..., None], width: int
) -> None:
    _open(guarded_page, open_app, width)
    assert _rows(guarded_page) == 1
    geo: dict[str, Any] = guarded_page.evaluate(_GROUP_RECTS_JS)
    assert geo["height"] == 82
    for got, share in zip(geo["groups"], (0.4, 0.3, 0.3), strict=True):
        assert abs(got - geo["content"] * share) <= 1


def test_group_widths_do_not_move_with_a_long_pick(
    guarded_page: Page, open_app: Callable[..., None]
) -> None:
    _open(guarded_page, open_app, 1280)
    before: dict[str, Any] = guarded_page.evaluate(_GROUP_RECTS_JS)
    set_state(
        guarded_page, {"game": "cfp-national-championship", "conferences": ["FBS Independents"]}
    )
    assert guarded_page.evaluate(_GROUP_RECTS_JS) == before


@pytest.mark.parametrize(("width", "rows"), [(1024, 2), (768, 2), (600, 3), (481, 3)])
def test_rows_depend_only_on_width(
    guarded_page: Page, open_app: Callable[..., None], width: int, rows: int
) -> None:
    _open(guarded_page, open_app, width)
    assert _rows(guarded_page) == rows
    set_state(guarded_page, {"game": "cfp-national-championship", "booth": ["a", "b"]})
    assert _rows(guarded_page) == rows


def test_groups_labels_and_order(guarded_page: Page, open_app: Callable[..., None]) -> None:
    _open(guarded_page, open_app, 1440)
    got = guarded_page.evaluate(
        """() => [...document.querySelectorAll('#toolbar .fgroup')].map((g) => ({
          g: g.dataset.g, role: g.getAttribute('role'),
          label: g.querySelector('.fgroup-label').textContent,
          labelled: document.getElementById(g.getAttribute('aria-labelledby')).textContent,
          ids: [...g.querySelectorAll('.filter-trigger')].map((b) => b.id.replace('trigger-', '')),
        }))"""
    )
    assert [g["g"] for g in got] == list(GROUPS)
    for g in got:
        label, ids = GROUPS[g["g"]]
        assert (g["role"], g["label"], g["labelled"], g["ids"]) == ("group", label, label, ids)


@pytest.mark.parametrize("width", [1440, 1024, 600])
def test_dom_order_is_visual_order(
    guarded_page: Page, open_app: Callable[..., None], width: int
) -> None:
    _open(guarded_page, open_app, width)
    rects: list[dict[str, Any]] = guarded_page.evaluate(_ENTRY_RECTS_JS)
    assert [r["id"] for r in rects] == ORDER
    visual = sorted(rects, key=lambda r: (r["top"], r["left"]))
    assert [r["id"] for r in visual] == ORDER


def test_entries_are_44px_boxless_with_a_bottom_line(
    guarded_page: Page, open_app: Callable[..., None]
) -> None:
    _open(guarded_page, open_app, 1440)
    looks = guarded_page.evaluate(
        """() => [...document.querySelectorAll('#toolbar .fgroup-row .filter-trigger')].map((b) => {
          const s = getComputedStyle(b);
          return [b.getBoundingClientRect().height, s.borderTopWidth, s.borderBottomWidth,
                  s.borderRadius, s.backgroundColor];
        })"""
    )
    assert looks == [[44, "0px", "1px", "0px", "rgba(0, 0, 0, 0)"]] * 10


def test_phone_hides_the_groups_and_keeps_the_filters_button(
    mobile_page: Page, open_app: Callable[..., None]
) -> None:
    open_app(mobile_page, "")
    assert mobile_page.locator("#toolbar .fgroup").first.is_hidden()
    assert mobile_page.locator("#filters-button").is_visible()


# ---- Part 2: entry text and states ----

DEFAULTS = {
    "announcers": "Any",
    "networks": "All",
    "booth": "Any",
    "role": "Both",
    "conference": "Any",
    "school": "Any",
    "game": "Any",
    "kickoff": "Any",
    "postseason": "All games",
}


def _entry(page: Page, name: str) -> dict[str, Any]:
    out: dict[str, Any] = page.evaluate(
        """(name) => {
          const b = document.getElementById('trigger-' + name);
          const v = b.querySelector('.filter-value');
          const l = b.querySelector('.filter-label');
          return {label: l.textContent, value: v.textContent,
                  changed: b.classList.contains('is-changed'), title: b.title,
                  aria: b.getAttribute('aria-label'), truncated: v.scrollWidth > v.clientWidth,
                  valueWeight: getComputedStyle(v).fontWeight,
                  line: getComputedStyle(b).borderBottomWidth, h: b.getBoundingClientRect().height};
        }""",
        name,
    )
    return out


def test_untouched_entries_read_their_defaults_and_none_is_changed(
    guarded_page: Page, open_app: Callable[..., None]
) -> None:
    _open(guarded_page, open_app, 1440)
    seasons = guarded_page.evaluate(
        "() => ({min: Math.min(...window.__testHooks.data.seasons),"
        " max: Math.max(...window.__testHooks.data.seasons)})"
    )
    for name, word in {**DEFAULTS, "seasons": f"{seasons['min']}–{seasons['max']}"}.items():  # noqa: RUF001
        entry = _entry(guarded_page, name)
        assert entry["value"] == word, name
        assert not entry["changed"], name
        assert entry["title"] == entry["label"] == entry["aria"], name


def test_a_changed_entry_shows_the_pick_in_the_accent_and_keeps_44px(
    guarded_page: Page, open_app: Callable[..., None]
) -> None:
    _open(guarded_page, open_app, 1440, "?people=dale-harlow")
    entry = _entry(guarded_page, "announcers")
    assert entry["changed"]
    assert entry["value"] == "Dale Harlow"
    assert entry["title"] == entry["aria"] == "Announcers: Dale Harlow"
    assert (entry["line"], entry["h"], entry["valueWeight"]) == ("2px", 44, "600")
    accent = guarded_page.evaluate(
        "() => getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()"
    )
    colours = guarded_page.evaluate(
        """() => { const b = document.getElementById('trigger-announcers');
          return [getComputedStyle(b.querySelector('.filter-value')).color,
                  getComputedStyle(b).borderBottomColor]; }"""
    )
    assert colours[0] == colours[1]
    assert accent


def test_picks_read_as_words(guarded_page: Page, open_app: Callable[..., None]) -> None:
    _open(guarded_page, open_app, 1440)
    set_state(guarded_page, {"people": ["dale-harlow", "casey-lund"]})
    two = _entry(guarded_page, "announcers")
    assert two["value"] == "Dale Harlow +1"
    assert two["title"] == "Announcers: Dale Harlow, Casey Lund"
    set_state(guarded_page, {"compare": True})
    assert _entry(guarded_page, "announcers")["value"] == "2 people"
    set_state(guarded_page, {"people": ["dale-harlow"]})
    assert _entry(guarded_page, "announcers")["value"] == "1 person"
    set_state(guarded_page, {"compare": False, "people": [], "slots": ["noon", "prime"]})
    assert _entry(guarded_page, "kickoff")["value"] == "Noon +1"
    set_state(guarded_page, {"slots": ["prime"], "booth": ["b"]})
    assert _entry(guarded_page, "kickoff")["value"] == "Prime time"
    assert _entry(guarded_page, "booth")["value"] == "No. 2 (B)"
    set_state(guarded_page, {"seasons": [2021, 2025], "postseason": "only", "role": "analyst"})
    assert _entry(guarded_page, "seasons")["value"] == "2021–2025"  # noqa: RUF001
    assert _entry(guarded_page, "postseason")["value"] == "Only"
    assert _entry(guarded_page, "role")["changed"]


def test_a_long_pick_truncates_in_its_entry(
    guarded_page: Page, open_app: Callable[..., None]
) -> None:
    _open(guarded_page, open_app, 1024)
    base = layout_snapshot(guarded_page)
    set_state(guarded_page, {"game": "cfp-national-championship"})
    entry = _entry(guarded_page, "game")
    assert entry["changed"]
    assert entry["truncated"], entry
    assert layout_snapshot(guarded_page) == base


def test_this_weekend_greys_the_calendar_group_and_game(
    guarded_page: Page, open_app: Callable[..., None]
) -> None:
    _open(guarded_page, open_app, 1440, "?view=weekend")
    for name in ("seasons", "kickoff", "postseason", "game"):
        look = guarded_page.evaluate(
            """(name) => { const b = document.getElementById('trigger-' + name);
              const s = getComputedStyle(b);
              return {disabled: b.getAttribute('aria-disabled'), cursor: s.cursor,
                      popover: b.hasAttribute('popovertarget'), title: b.title,
                      value: getComputedStyle(b.querySelector('.filter-value')).color,
                      label: getComputedStyle(b.querySelector('.filter-label')).color,
                      line: s.borderBottomColor}; }""",
            name,
        )
        assert look["disabled"] == "true", name
        assert look["cursor"] == "not-allowed", name
        assert not look["popover"], name
        assert look["title"], name
        assert look["value"] == look["label"], name
    ink = guarded_page.evaluate("() => getComputedStyle(document.body).color")
    group_label = guarded_page.evaluate(
        "() => getComputedStyle(document.querySelector('#fgroup-calendar')).color"
    )
    assert group_label == ink
    guarded_page.click("#trigger-game", force=True)
    assert not guarded_page.evaluate(
        "() => document.getElementById('pop-game').matches(':popover-open')"
    )
    assert guarded_page.locator("#trigger-announcers").get_attribute("aria-disabled") is None


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_entry_text_is_readable(
    guarded_page: Page, open_app: Callable[..., None], theme: str
) -> None:
    _open(guarded_page, open_app, 1440)
    set_theme(guarded_page, theme)
    for state in ({}, {"people": ["dale-harlow"], "role": "analyst"}):
        set_state(guarded_page, {"people": [], "role": None, **state})
        colours = guarded_page.evaluate(
            """() => ({
              bg: getComputedStyle(document.body).backgroundColor,
              text: [...document.querySelectorAll('#toolbar .fgroup-row .filter-text span')]
                .map((s) => getComputedStyle(s).color),
            })"""
        )
        for colour in colours["text"]:
            assert ratio(colour, colours["bg"]) >= 4.5, (theme, colour)


# The seven states of the zero-shift guard; each is applied to a clean page.
SHIFT_STATES: list[tuple[str, dict[str, Any]]] = [
    ("one-pick", {"conferences": ["FBS Independents"]}),
    (
        "two-picks-long",
        {"game": "cfp-national-championship", "school": ["northfield", "lakeview"], "h2h": True},
    ),
    ("person-and-networks", {"people": ["dale-harlow"], "networks": ["net-a", "net-b"]}),
    ("this-weekend", {"view": "weekend"}),
]
RESET: dict[str, Any] = {
    "seasons": None,
    "networks": None,
    "slots": None,
    "role": None,
    "conferences": [],
    "school": [],
    "h2h": False,
    "postseason": "all",
    "game": None,
    "booth": [],
    "people": [],
    "view": "scatter",
}


@pytest.mark.parametrize("width", [1440, 1280, 1024, 768])
def test_no_pick_moves_a_rule_an_entry_the_bar_or_the_tabs(
    guarded_page: Page, open_app: Callable[..., None], width: int
) -> None:
    _open(guarded_page, open_app, width)
    base = layout_snapshot(guarded_page)
    entries = guarded_page.evaluate(_ENTRY_RECTS_JS)
    for name, patch in SHIFT_STATES:
        set_state(guarded_page, patch)
        assert layout_snapshot(guarded_page) == base, name
        assert guarded_page.evaluate(_ENTRY_RECTS_JS) == entries, name
        set_state(guarded_page, RESET)
    set_theme(guarded_page, "dark")
    assert layout_snapshot(guarded_page) == base, "dark"


@pytest.mark.parametrize("width", [1440, 1024])
def test_this_weekend_map_does_not_move_the_bar(
    guarded_page: Page,
    serve_weekend_map: Callable[..., None],
    open_app: Callable[..., None],
    width: int,
) -> None:
    guarded_page.set_viewport_size({"width": width, "height": 900})
    serve_weekend_map(guarded_page)
    open_app(guarded_page, "")
    base = layout_snapshot(guarded_page, include=("toolbar_bottom", "group_x"))
    set_state(guarded_page, {"view": "weekend", "wview": "map"})
    assert layout_snapshot(guarded_page, include=("toolbar_bottom", "group_x")) == base
