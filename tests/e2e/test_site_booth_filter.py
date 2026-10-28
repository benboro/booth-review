"""The Booth toolbar trigger and popover (Phase 10, D-12), proven in the browser on the
synthetic booth overlay (plan 10-03): facet counts, fade and Hide, URL state, resets, the
phone sheet and Bars by Network.

Merged indices: tier a at 5, 8, 14; b at 9, 13; other at 4 and 15; the rest untiered.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

A = [5, 8, 14]
HELPER = (
    "Network families with a published booth order only. Games without one are faded or hidden."
)

_PASSES_JS = "() => window.__testHooks.getView().passesFilters"

_BARS_JS = """
async ([partial]) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const B = await import('./modules/bars.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const networks = raw.lookups.networks.map((n) => n.id);
  const state = Object.assign(S.defaultState(data), partial, { networks });
  const view = S.computeView(data, state);
  const pick = { school: ['ironpeak'], by: 'network' };
  const school = Object.assign(S.defaultState(data), partial, pick);
  const schoolView = S.computeView(data, school);
  const rows = (m) => m.rows.map((r) => [r.label, r.total, r.rated]);
  return {
    games: B.gamesForBars(view),
    passing: B.passingIndices(schoolView),
    rows: rows(B.barsModel(data, schoolView, school)),
  };
}
"""


def _open(
    page: Page,
    serve_booths: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
    query: str = "",
) -> None:
    serve_booths(page)
    open_app(page, query)


def _open_popover(page: Page) -> None:
    page.click("#trigger-booth")
    page.wait_for_function("document.getElementById('pop-booth').matches(':popover-open')")


def _passes(page: Page) -> list[int]:
    result: list[int] = page.evaluate(_PASSES_JS)
    return result


def _visible_dots(page: Page) -> int:
    result: int = page.evaluate(
        "() => document.getElementById('chart').data.reduce("
        "(n, t) => n + (/^(unrated-)?lead-((filled-)?halo|rim):/.test(String(t.meta))"
        " ? 0 : t.x.length), 0)"
    )
    return result


def test_popover_lists_three_tiers_with_facet_counts(
    guarded_page: Page,
    serve_booths: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> None:
    _open(guarded_page, serve_booths, open_app)
    expect(guarded_page.locator("#trigger-booth .filter-value")).to_have_text("Any")
    in_group = guarded_page.evaluate(
        "() => document.getElementById('trigger-booth').closest('.fgroup').dataset.g"
    )
    assert in_group == "broadcast"  # Round 3b: Booth sits with Announcers, Networks and Role
    _open_popover(guarded_page)
    expect(guarded_page.locator("#pop-booth .helper")).to_have_text(HELPER)
    rows = guarded_page.locator("#booth-list .check-item")
    assert rows.count() == 3
    names = guarded_page.locator("#booth-list .option-name").all_inner_texts()
    counts = guarded_page.locator("#booth-list .option-count").all_inner_texts()
    assert list(zip(names, counts, strict=True)) == [
        ("Lead (A)", "(3)"),
        ("No. 2 (B)", "(2)"),
        ("Other", "(2)"),
    ]
    assert guarded_page.locator("#booth-list input:checked").count() == 0
    assert len(_passes(guarded_page)) == 19  # no pick filters nothing (19 is unplayed)


def test_lead_pick_fades_the_rest_and_labels_the_trigger(
    guarded_page: Page,
    serve_booths: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> None:
    _open(guarded_page, serve_booths, open_app)
    _open_popover(guarded_page)
    guarded_page.check("#booth-list input[value='a']")
    guarded_page.wait_for_function("location.search.includes('booth=a')")
    assert _passes(guarded_page) == A  # 17 of 20 fail the filter and are faded
    trigger = guarded_page.locator("#trigger-booth")
    expect(trigger.locator(".filter-value")).to_have_text("Lead (A)")
    assert trigger.get_attribute("title") == "Booth: Lead (A)"
    assert trigger.get_attribute("data-active") == "true"
    assert _visible_dots(guarded_page) == 19
    # Counts keep describing the other tiers while one is picked (own-excluded facets).
    expect(guarded_page.locator("#booth-list .check-item").nth(1)).to_contain_text("(2)")


def test_hide_mode_draws_only_the_picked_tier(
    guarded_page: Page,
    serve_booths: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> None:
    _open(guarded_page, serve_booths, open_app, "?booth=a")
    guarded_page.click('#dots-toggle [data-dots="hide"]')
    guarded_page.wait_for_function("document.getElementById('chart').data.length > 0")
    guarded_page.wait_for_function(
        "document.getElementById('chart').data.reduce("
        "(n, t) => n + (/^(unrated-)?lead-((filled-)?halo|rim):/.test(String(t.meta))"
        " ? 0 : t.x.length), 0) === 3"
    )
    assert _visible_dots(guarded_page) == 3


def test_url_decodes_to_checked_boxes_and_multi_label(
    guarded_page: Page,
    serve_booths: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> None:
    _open(guarded_page, serve_booths, open_app, "?booth=b,other")
    _open_popover(guarded_page)
    checked = guarded_page.eval_on_selector_all(
        "#booth-list input:checked", "(els) => els.map((e) => e.value)"
    )
    assert checked == ["b", "other"]
    expect(guarded_page.locator("#trigger-booth .filter-value")).to_have_text("No. 2 (B) +1")
    assert _passes(guarded_page) == [4, 9, 13, 15]


def test_section_reset_and_clear_all_clear_the_pick(
    guarded_page: Page,
    serve_booths: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> None:
    _open(guarded_page, serve_booths, open_app, "?booth=b,other")
    _open_popover(guarded_page)
    reset = guarded_page.locator("#filter-booth .group-reset")
    assert reset.get_attribute("aria-disabled") == "false"
    reset.click()
    guarded_page.wait_for_function("!new URLSearchParams(location.search).has('booth')")
    assert reset.get_attribute("aria-disabled") == "true"
    assert guarded_page.locator("#booth-list input:checked").count() == 0
    guarded_page.keyboard.press("Escape")

    guarded_page.goto(guarded_page.url.split("?")[0] + "?booth=a")
    guarded_page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    guarded_page.click("#clear-filters")
    guarded_page.wait_for_function("location.search === ''")
    expect(guarded_page.locator("#trigger-booth .filter-value")).to_have_text("Any")


def test_bars_by_network_follows_the_booth_filter(
    guarded_page: Page,
    serve_booths: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> None:
    """Bars read the games passing every filter (`passingIndices`; no rated-only rule
    applies, unrated games count). With every network offered, booth=a leaves exactly the
    three A games (5, 8, 14). Scoped to one school, the network bars shrink to that
    school's A games and differ from the unfiltered bars."""
    _open(guarded_page, serve_booths, open_app)
    with_a = guarded_page.evaluate(_BARS_JS, [{"booth": ["a"]}])
    without = guarded_page.evaluate(_BARS_JS, [{}])
    assert with_a["games"] == A
    assert with_a["passing"] == [5, 8]
    assert with_a["rows"] == [["ABC/ESPN", 3, 3], ["FOX/FS1/BTN", 2, 2]]
    assert without["rows"] != with_a["rows"]
    assert len(without["passing"]) > len(with_a["passing"])


def test_phone_sheet_carries_booth_with_44px_rows(
    mobile_page: Page,
    serve_booths: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> None:
    _open(mobile_page, serve_booths, open_app, "?booth=a")
    expect(mobile_page.locator("#trigger-booth")).to_be_hidden()
    expect(mobile_page.locator("#filters-button")).to_have_text("Filters (1 changed)")
    mobile_page.click("#filters-button")
    mobile_page.wait_for_function(
        "document.getElementById('filters-sheet').matches(':popover-open')"
    )
    assert mobile_page.locator(".sheet-body #filter-booth").count() == 1
    labels = mobile_page.locator("#filter-booth .check-row")
    assert labels.count() == 3
    for i in range(3):
        box = labels.nth(i).bounding_box()
        assert box is not None
        assert box["height"] >= 44, box


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "narrow"], indirect=True)
@pytest.mark.parametrize("width", [800, 900, 1024, 1280])
def test_toolbar_does_not_overflow_and_keeps_order(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    width: int,
    font_setting: str,
) -> None:
    guarded_page.set_viewport_size({"width": width, "height": 900})
    open_app(guarded_page, "")
    result: dict[str, Any] = guarded_page.evaluate(
        """() => {
          const bar = document.getElementById('toolbar');
          const box = bar.getBoundingClientRect();
          const cells = [...bar.querySelectorAll('.fgroup-row .filter-trigger')]
            .filter((b) => b.offsetParent !== null);
          return {
            scroll: bar.scrollWidth <= bar.clientWidth,
            inside: cells.every((c) => {
              const r = c.getBoundingClientRect();
              return r.left >= box.left - 0.5 && r.right <= box.right + 0.5;
            }),
            ids: cells.map((c) => c.id),
          };
        }"""
    )
    assert result["scroll"]
    assert result["inside"]
    assert result["ids"] == [
        "trigger-announcers",
        "trigger-networks",
        "trigger-booth",
        "trigger-role",
        "trigger-conference",
        "trigger-school",
        "trigger-game",
        "trigger-seasons",
        "trigger-kickoff",
        "trigger-postseason",
    ]
