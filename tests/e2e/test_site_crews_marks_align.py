"""Crews game lists (user 2026-11-11): columns laid under the row table's, the CFB marks column,
the national championship emblem, and the chevron on the first line's baseline.

Runs on the synthetic contract fixture, the synthetic crews dataset and the NFL and MLB
fixtures; no vault content. Contract fixture games used here: 0 a rivalry (unranked), 1 one
team ranked, 4 a rivalry between two ranked teams, 5 the only CFP game (a semifinal at the
Summit Bowl, `serve_round` swaps its round), 7 a bowl between two ranked teams.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

TOL = 1.0

# Each game-list head's anchored edge: (game head class, row-table column, edge).
CFB_EDGES = [
    ("crews-gcol-matchup", "crew", "left"),
    ("crews-gcol-network", "network", "left"),
    ("crews-gcol-exc", "exc", "right"),
    ("crews-gcol-viewers", "viewers", "right"),
]

_EDGES_JS = """
([scope, pairs]) => {
  const root = document.querySelector(scope);
  const table = root.querySelector('table.crews-table');
  const list = table.querySelector('table.crews-games');
  const out = { aligned: list.classList.contains('is-aligned'), pairs: [] };
  for (const [cls, col, edge] of pairs) {
    const head = table.querySelector(`:scope > thead th[data-col="${col}"]`);
    const sub = list.querySelector(`thead th.${cls}`);
    const at = (node) => node.getBoundingClientRect()[edge];
    out.pairs.push([cls, col, at(head), at(sub)]);
  }
  return out;
}
"""


def _assert_edges(page: Page, scope: str, pairs: list[tuple[str, str, str]]) -> None:
    got = page.evaluate(_EDGES_JS, [scope, pairs])
    assert got["aligned"]
    for cls, col, parent, child in got["pairs"]:
        assert abs(parent - child) <= TOL, (cls, col, parent, child)


def _expand_first(page: Page, scope: str) -> None:
    # Click on the name itself (its left edge), never the filter button after it.
    page.locator(f"{scope} tr.crews-row td.crews-name").first.click(position={"x": 20, "y": 12})
    page.wait_for_selector(f"{scope} table.crews-games.is-aligned")


@pytest.mark.parametrize(
    ("query", "date_col"),
    [
        ("?view=crews&perseason=1", "season"),
        ("?view=crews&perseason=0", "rank"),
        ("?view=crews&perseason=1&cmode=pbp", "season"),
    ],
)
def test_cfb_game_list_lines_up_under_the_row_table(
    guarded_page: Page,
    serve_crews: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
    query: str,
    date_col: str,
) -> None:
    """Matchup starts under the names, Date under Season (Rank by season when pooled), Network
    under Network, and Excitement and Viewers end under their averages, at 1440 and 1000."""
    page = guarded_page
    serve_crews(page)
    open_app(page, query)
    _expand_first(page, "#crews-panel")
    pairs = [*CFB_EDGES, ("crews-gcol-date", date_col, "left")]
    _assert_edges(page, "#crews-panel", pairs)
    page.set_viewport_size({"width": 1000, "height": 900})
    page.wait_for_timeout(100)
    _assert_edges(page, "#crews-panel", pairs)


def test_cfb_pooled_person_mode_puts_date_in_its_slot_before_network(
    guarded_page: Page, serve_crews: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    """With no Season or Rank column, Date takes its fixed slot just before Network."""
    page = guarded_page
    serve_crews(page)
    open_app(page, "?view=crews&perseason=0&cmode=pbp")
    _expand_first(page, "#crews-panel")
    _assert_edges(page, "#crews-panel", CFB_EDGES)
    gap = page.evaluate(
        """() => {
          const list = document.querySelector('#crews-panel table.crews-games');
          const d = list.querySelector('thead th.crews-gcol-date').getBoundingClientRect();
          const n = list.querySelector('thead th.crews-gcol-network').getBoundingClientRect();
          return n.left - d.right;
        }"""
    )
    assert abs(gap) <= TOL


def test_nfl_game_list_lines_up_under_the_row_table(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    open_nfl_app(page, "?sport=nfl&view=crews")
    _expand_first(page, "#nfl-view-crews")
    _assert_edges(
        page,
        "#nfl-view-crews",
        [
            ("crews-gcol-matchup", "booth", "left"),
            ("crews-gcol-date", "season", "left"),
            ("crews-gcol-network", "network", "left"),
            ("crews-gcol-exc", "exc", "right"),
            ("crews-gcol-viewers", "viewers", "right"),
        ],
    )


def test_mlb_game_list_lines_up_under_the_row_table(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    page.set_viewport_size({"width": 1440, "height": 900})
    open_mlb_app(page)
    _expand_first(page, "#mlb-view-apple")
    _assert_edges(
        page,
        "#mlb-view-apple",
        [
            ("crews-gcol-matchup", "booth", "left"),
            ("crews-gcol-crew", "network", "left"),
            ("crews-gcol-exc", "excitement", "right"),
            ("crews-gcol-viewers", "prior", "right"),
        ],
    )


_MARKS_JS = """
async (i) => {
  const D = await import('./modules/data.js');
  const M = await import('./modules/game-marks.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const td = M.gameMarksCell(data, i);
  return {
    marks: M.gameMarks(data, i).map(([kind]) => kind),
    shown: [...td.querySelectorAll('.crews-mark')].map((s) => s.dataset.mark),
    hidden: td.querySelector('.visually-hidden')?.textContent ?? null,
    titleImg: td.querySelectorAll('img.title-mark').length,
  };
}
"""


@pytest.mark.parametrize(
    ("round_", "index", "marks"),
    [
        (None, 0, ["rivalry"]),
        (None, 1, []),
        (None, 3, []),
        (None, 4, ["rivalry", "ranked"]),
        (None, 7, ["bowl", "ranked"]),
        ("semifinal", 5, ["bowl", "playoff"]),
        ("first_round", 5, ["playoff"]),
        ("championship", 5, ["playoff", "title"]),
    ],
)
def test_marks_cell_names_every_kind_of_game(
    guarded_page: Page,
    serve_round: Callable[[Page, str | None], None],
    open_app: Callable[[Page, str], None],
    round_: str | None,
    index: int,
    marks: list[str],
) -> None:
    """Rivalry, bowl, playoff, the title emblem (championship only) and the ranked star (both
    teams ranked only), in that order, each drawn, with one hidden line naming them all."""
    serve_round(guarded_page, round_)
    open_app(guarded_page, "")
    got: dict[str, Any] = guarded_page.evaluate(_MARKS_JS, index)
    assert got["marks"] == marks
    assert got["shown"] == marks
    assert got["titleImg"] == (1 if "title" in marks else 0)
    if marks:
        assert got["hidden"]
        if "title" in marks:
            assert "National championship" in got["hidden"]
        if "ranked" in marks:
            assert "Both teams ranked" in got["hidden"]
    else:
        assert got["hidden"] is None


def test_title_game_panel_keeps_the_trophy_and_adds_the_emblem(
    guarded_page: Page,
    serve_round: Callable[[Page, str | None], None],
    open_app: Callable[[Page, str], None],
) -> None:
    serve_round(guarded_page, "championship")
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.openPanel(5)")
    line = guarded_page.locator("#panel-body .panel-game-type", has_text="CFP championship")
    assert line.locator('svg.game-type-icon[data-kind="playoff"]').count() == 1
    img = line.locator("img.title-mark")
    assert img.count() == 1
    assert img.get_attribute("aria-hidden") == "true"
    assert img.get_attribute("src") == "logos/marks/cfp-national-championship.svg"
    guarded_page.click("#panel-close")
    serve_round(guarded_page, "semifinal")
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.openPanel(5)")
    assert guarded_page.locator("#panel-body img.title-mark").count() == 0


def test_title_mark_swaps_to_the_dark_file_with_the_theme(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    guarded_page.evaluate(
        """async () => {
          const T = await import('./modules/title-mark.js');
          const img = T.titleGameMark();
          img.id = 'probe-title-mark';
          document.body.append(img);
        }"""
    )
    probe = guarded_page.locator("#probe-title-mark")
    assert probe.get_attribute("src") == "logos/marks/cfp-national-championship.svg"
    guarded_page.click("#theme-toggle")
    assert probe.get_attribute("src") == "logos/dark/marks/cfp-national-championship.svg"
    assert (
        guarded_page.evaluate(
            "() => fetch('logos/dark/marks/cfp-national-championship.svg').then((r) => r.status)"
        )
        == 200
    )


_CARET_JS = """
(scope) => {
  return [...document.querySelectorAll(`${scope} tr.crews-row`)].slice(0, 6).map((tr) => {
    const td = tr.querySelector('td.crews-name');
    const mark = document.createElement('span');
    mark.style.cssText = 'display:inline-block;width:0;height:0';
    td.prepend(mark);
    const baseline = mark.getBoundingClientRect().bottom;
    mark.remove();
    const button = tr.querySelector('.crews-chevron');
    const b = button.getBoundingClientRect();
    const dy = parseFloat(getComputedStyle(button).getPropertyValue('--caret-dy'));
    // The caret is an 8px square turned 45 degrees: its lowest point is 5.66px below its centre.
    return { baseline, bottom: b.top + b.height / 2 + dy + 4 * Math.SQRT2 };
  });
}
"""


@pytest.mark.parametrize("phone", [False, True])
def test_chevron_sits_on_the_first_lines_baseline(
    guarded_page: Page,
    mobile_page: Page,
    serve_crews: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
    phone: bool,
) -> None:
    """User 2026-11-11: the caret stays on the first line, its lowest point on the baseline,
    on one-line and wrapped rows, desktop and phone."""
    page = mobile_page if phone else guarded_page
    serve_crews(page)
    open_app(page, "?view=crews&perseason=1&cmode=pbp")
    page.wait_for_selector("#crews-panel tr.crews-row")
    for got in page.evaluate(_CARET_JS, "#crews-panel"):
        assert abs(got["bottom"] - got["baseline"]) <= TOL, got
