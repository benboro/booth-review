"""Opt-in, count-only real-data browser check (SITE-01, SITE-02, SITE-05,
SITE-12, SITE-18, SITE-19).

Runs only with `BOOTH_REVIEW_E2E_REAL=1` set, against the developer's own
local vault -- never in CI, never on a machine without the vault. Builds its
own `dist/site` from `data/vault/processed/site-data.json` (not the synthetic
fixture `site_dist`/`site_url` in conftest.py serve) and serves it the same
way. Every assertion below carries only counts: no person name, id, team
name, or row ever appears in an assertion message, a print, or a test id
(AGENTS.md: the vault is private and never goes into fixtures, logs, or
commit messages; T-04-38 in this plan's own threat register).

Every `assert` compares plain local ints/bools only, computed on an earlier
line (WR-09): pytest's assertion rewriting prints the repr of every
sub-expression on failure (`where 3 = len([{'id': ..., 'name': ...}])`), so
an assert that calls `len(people)` or reads `page.url` inline would dump
vault records into the test log. `tests/test_realdata_assert_hygiene.py`
enforces this.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import _assert_guard_clean, _install_guard, _serve_directory
from playwright.sync_api import Page

from booth_review.cli import main
from booth_review.config import DataPaths

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("BOOTH_REVIEW_E2E_REAL") != "1",
        reason="real-data check is opt-in: BOOTH_REVIEW_E2E_REAL=1",
    ),
]

_TRACES_JS = "() => document.getElementById('chart').data.map(t => ({meta: t.meta, x: t.x}))"

_HIGHLIGHT_ALL_PEOPLE_JS = """
() => {
  const data = window.__testHooks.data;
  const results = [];
  for (const p of data.lookups.people) {
    window.__testHooks.setState({
      people: [p.id],
      conferences: [],
      school: [],
      postseason: 'all',
      role: null,
      seasons: null,
      networks: null,
      slots: null,
      together: false,
      compare: false,
    });
    const view = window.__testHooks.getView();
    results.push([...view.highlighted].sort((a, b) => a - b));
  }
  return results;
}
"""

_BIG_TEN_ERA_CORRECT_JS = """
() => {
  const data = window.__testHooks.data;
  const teamIdx = data.lookups.teams.findIndex((t) => t.name === 'USC');
  const confIdx = data.lookups.conferences.findIndex((c) => c.name === 'Big Ten');
  if (teamIdx === -1 || confIdx === -1) return null;
  window.__testHooks.setState({ conferences: ['Big Ten'] });
  const view = window.__testHooks.getView();
  const passing = new Set(view.passesFilters);
  let before2024 = 0;
  let from2024 = 0;
  for (let i = 0; i < data.n; i += 1) {
    const isHome = data.t.home_team[i] === teamIdx;
    const isAway = data.t.away_team[i] === teamIdx;
    if (!isHome && !isAway) continue;
    // The conference filter is OR-within (D-10): a pre-2024 USC (then
    // Pac-12) game against a Big Ten opponent -- e.g. a Rose Bowl --
    // legitimately passes the filter on the opponent's side. The
    // era-correct invariant is about USC's own conference assignment, so
    // this counts only games where USC's own side is Big Ten.
    const uscConf = isHome ? data.t.home_conference[i] : data.t.away_conference[i];
    if (uscConf !== confIdx) continue;
    if (!passing.has(i)) continue;
    if (data.t.season[i] < 2024) before2024 += 1;
    else from2024 += 1;
  }
  return [before2024, from2024];
}
"""

_PLAYOFF_BRACKET_JS = """
() => {
  const data = window.__testHooks.data;
  const knownRounds = new Set(['first_round', 'quarterfinal', 'semifinal', 'championship']);
  const perSeasonPlayoffCount = new Map();
  let badRound = 0;
  let regularWithRound = 0;
  for (let i = 0; i < data.n; i += 1) {
    const gameType = data.t.game_type[i];
    const round = data.t.playoff_round[i];
    if (round !== null && !knownRounds.has(round)) badRound += 1;
    if (gameType === 'regular' && round !== null) regularWithRound += 1;
    if (gameType === 'playoff') {
      const season = data.t.season[i];
      perSeasonPlayoffCount.set(season, (perSeasonPlayoffCount.get(season) || 0) + 1);
    }
  }
  if (perSeasonPlayoffCount.size === 0) return null;
  let overBefore2024 = 0;
  let over2024Plus = 0;
  for (const [season, count] of perSeasonPlayoffCount) {
    if (season < 2024) {
      if (count > 3) overBefore2024 += 1;
    } else if (count > 11) {
      over2024Plus += 1;
    }
  }
  return [badRound, regularWithRound, overBefore2024, over2024Plus];
}
"""


@pytest.fixture(scope="module")
def real_data_path() -> Path:
    """The vault's built site-data.json; skips the whole module when absent."""
    path = DataPaths.from_env().processed / "site-data.json"
    if not path.is_file():
        pytest.skip("site-data.json not found (real vault data unavailable)")
    return path


@pytest.fixture(scope="module")
def real_site_dist(tmp_path_factory: pytest.TempPathFactory, real_data_path: Path) -> Path:
    """Builds dist/site from the real vault data (non-fixture `booth-review site`)."""
    del real_data_path  # only used to gate/skip before this fixture runs
    out = tmp_path_factory.mktemp("real-site") / "site"
    returncode = main(["site", "--out", str(out)])
    assert returncode == 0, f"booth-review site exited {returncode}"
    return out


@pytest.fixture(scope="module")
def real_raw(real_site_dist: Path) -> dict[str, Any]:
    """The real built site-data.json, parsed -- read only for counts (never printed)."""
    return json.loads((real_site_dist / "site-data.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def real_site_url(real_site_dist: Path) -> Iterator[str]:
    """Serves `real_site_dist` (the real-data build), same pattern as conftest's `site_url`."""
    yield from _serve_directory(real_site_dist)


@pytest.fixture
def real_guarded_page(page: Page, real_site_url: str) -> Iterator[Page]:
    """`page`, guarded against off-origin requests/CSP violations, against the real build."""
    off_origin, csp_errors = _install_guard(page, real_site_url)
    yield page
    _assert_guard_clean(off_origin, csp_errors)


@pytest.fixture
def real_open_app(real_site_url: str) -> Callable[[Page, str], None]:
    """`open(page, query="")` against the real-data build, same pattern as conftest's `open_app`."""

    def _open(page: Page, query: str = "") -> None:
        page.goto(f"{real_site_url}/index.html{query}")
        page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")

    return _open


def _python_highlighted_sets(raw: dict[str, Any]) -> list[set[int]]:
    """Independently computes, for every person index, the set of dot indices
    they'd highlight with no other filter set: every main-feed entry, plus
    every alt-feed entry on a combined-feed dot (mirrors select.js's
    `personOnGame` for `role=null`; a spanish-feed entry never matches)."""
    telecasts = raw["telecasts"]
    people = raw["lookups"]["people"]
    crew = telecasts["crew"]
    combined_feeds = telecasts["combined_feeds"]
    n = len(telecasts["season"])

    result: list[set[int]] = [set() for _ in people]
    for i in range(n):
        for entry in crew[i]:
            person = entry["person"]
            feed = entry["feed"]
            if feed == "main" or (feed == "alt" and combined_feeds[i] is not None):
                result[person].add(i)
            # feed == "spanish" never matches (D-08/D-18).
    return result


def test_real_dot_count_and_origin(
    real_guarded_page: Page,
    real_open_app: Callable[[Page, str], None],
    real_raw: dict[str, Any],
) -> None:
    """SITE-01/SITE-19: the chart renders exactly one dot per telecast and
    makes no off-origin request (checked by `real_guarded_page`'s teardown)."""
    real_open_app(real_guarded_page, "")
    traces: list[dict[str, Any]] = real_guarded_page.evaluate(_TRACES_JS)
    family_traces = [t for t in traces if str(t["meta"]).startswith("family:")]
    total_dots = len(real_raw["telecasts"]["season"])
    # A family trace with no dots of its own carries one null legend
    # placeholder (CR-03); a real dot always has a numeric x (the n/a strip
    # sentinel when its axis value is missing), so count only non-null x.
    plotted = sum(1 for t in family_traces for x in t["x"] if x is not None)
    assert plotted == total_dots


def test_real_every_person_highlights_exactly_their_games(
    real_guarded_page: Page,
    real_open_app: Callable[[Page, str], None],
    real_raw: dict[str, Any],
) -> None:
    """SITE-02, D-08: for every person in the real people lookup, the
    browser's highlighted set equals an independent Python computation of
    that person's main-feed plus combined-feed alt-cast games -- the core
    promise over all people, reported as counts only."""
    real_open_app(real_guarded_page, "")
    expected_sets = _python_highlighted_sets(real_raw)
    n_people = len(real_raw["lookups"]["people"])
    n_expected = len(expected_sets)
    assert n_expected == n_people, "expected-set count differs from people count"

    actual: list[list[int]] = real_guarded_page.evaluate(_HIGHLIGHT_ALL_PEOPLE_JS)
    n_actual = len(actual)
    assert n_actual == n_people, "browser result count differs from people count"

    mismatches = 0
    for expected_set, actual_list in zip(expected_sets, actual, strict=True):
        if sorted(expected_set) != actual_list:
            mismatches += 1

    assert mismatches == 0, f"{mismatches} of {n_people} people mismatched"


def test_real_default_url_is_clean(
    real_guarded_page: Page, real_open_app: Callable[[Page, str], None]
) -> None:
    """D-12: default load leaves no query string."""
    real_open_app(real_guarded_page, "")
    has_query = "?" in real_guarded_page.url
    assert has_query is False, "default load left a query string"


def test_real_big_ten_is_era_correct(
    real_guarded_page: Page, real_open_app: Callable[[Page, str], None]
) -> None:
    """D-09: the Big Ten conference filter never passes a USC telecast
    before 2024 (USC joined the Big Ten in 2024) and does pass at least one
    USC telecast from 2024 on, on the real vault build -- counts only."""
    real_open_app(real_guarded_page, "")
    result: list[int] | None = real_guarded_page.evaluate(_BIG_TEN_ERA_CORRECT_JS)
    if result is None:
        pytest.skip("USC or Big Ten not present in the real vault data")
    before_2024, from_2024 = result
    assert before_2024 == 0, "a USC telecast before 2024 passed the Big Ten filter"
    assert from_2024 > 0, "no USC telecast from 2024 on passed the Big Ten filter"


_TIME_SLOTS_MATCH_KICKOFF_HOURS_JS = """
() => {
  const data = window.__testHooks.data;
  const knownSlots = new Set(['noon', 'afternoon', 'prime', 'late']);
  let mismatches = 0;
  let unknown = 0;
  let late = 0;
  for (let i = 0; i < data.n; i += 1) {
    const kickoff = data.t.kickoff[i];
    const actual = data.t.time_slot[i];
    let expected;
    if (kickoff === null) {
      expected = null;
    } else {
      const hour = Number(kickoff.slice(11, 13));
      if (hour < 5) expected = 'late';
      else if (hour < 14) expected = 'noon';
      else if (hour < 18) expected = 'afternoon';
      else if (hour < 22) expected = 'prime';
      else expected = 'late';
    }
    if (actual !== null && !knownSlots.has(actual)) unknown += 1;
    if (actual !== expected) mismatches += 1;
    if (actual === 'late') late += 1;
  }
  return [mismatches, unknown, late];
}
"""


def test_real_time_slots_match_kickoff_hours(
    real_guarded_page: Page, real_open_app: Callable[[Page, str], None]
) -> None:
    """D-20/D-26: every real telecast's `time_slot` matches the four-slot
    rule derived from its own ET kickoff hour (hour < 5 or >= 22 -> late,
    < 14 -> noon, < 18 -> afternoon, < 22 -> prime; a null kickoff is a null
    slot), and every non-null slot is one of the four known values --
    counts only."""
    real_open_app(real_guarded_page, "")
    result: list[int] = real_guarded_page.evaluate(_TIME_SLOTS_MATCH_KICKOFF_HOURS_JS)
    mismatches, unknown, late = result
    assert mismatches == 0, f"{mismatches} telecasts had a time_slot inconsistent with kickoff"
    assert unknown == 0, f"{unknown} telecasts had a time_slot outside the four known values"
    print(f"After-dark (late) telecast count: {late}")


_ANNOUNCER_LIST_JS = """
() => {
  const results = document.getElementById('person-results');
  const rowCount = results.querySelectorAll('li[role="option"]:not([aria-disabled])').length;
  const peopleCount = window.__testHooks.data.lookups.people.length;
  const input = document.getElementById('person-search');
  const start = performance.now();
  input.value = 'a';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  const elapsedMs = performance.now() - start;
  const filteredCount = results.querySelectorAll('li[role="option"]:not([aria-disabled])').length;
  return [rowCount, peopleCount, filteredCount, elapsedMs];
}
"""


def test_real_announcer_list_lists_everyone(
    real_guarded_page: Page, real_open_app: Callable[[Page, str], None]
) -> None:
    """D-28: with the search empty, #person-results lists every real
    announcer, and one synchronous filter pass (D-28: no debounce) stays
    well under 100ms -- counts and a timing number only."""
    real_open_app(real_guarded_page, "")
    real_guarded_page.click("#trigger-announcers")
    real_guarded_page.wait_for_function(
        "document.getElementById('pop-announcers').matches(':popover-open')"
    )
    result: list[float] = real_guarded_page.evaluate(_ANNOUNCER_LIST_JS)
    row_count, people_count, filtered_count, elapsed_ms = result
    assert row_count == people_count, "row count differs from people count"
    assert elapsed_ms < 100, "one filter pass took too long"
    assert filtered_count > 0, "filtering matched zero rows"
    assert filtered_count <= people_count, "filtered count exceeds people count"


_CHART_SVG_WIDTH_JS = (
    "() => document.querySelector('#chart .main-svg').getBoundingClientRect().width"
)


def test_real_chart_width_unchanged_when_the_modal_opens(
    real_guarded_page: Page, real_open_app: Callable[[Page, str], None]
) -> None:
    """D-01: opening the detail modal on the real build leaves the chart's
    width as it was. The evaluate calls return plain numbers/bools only
    (WR-09) -- no vault record ever appears in an assertion."""
    real_open_app(real_guarded_page, "")

    w0: float = real_guarded_page.evaluate(_CHART_SVG_WIDTH_JS)
    real_guarded_page.evaluate("window.__testHooks.openPanel(0)")
    is_open: bool = real_guarded_page.evaluate("document.getElementById('detail-panel').open")
    w_open: float = real_guarded_page.evaluate(_CHART_SVG_WIDTH_JS)

    assert is_open
    assert w_open == w0


def test_real_playoff_counts_fit_the_bracket(
    real_guarded_page: Page, real_open_app: Callable[[Page, str], None]
) -> None:
    """D-17: every season's playoff telecast count fits the CFP bracket size
    (at most 3 before 2024, at most 11 from 2024 on), every playoff_round is
    one of the four known CFP rounds or null, and no regular-season
    telecast carries a playoff_round -- on the real vault build, counts
    only."""
    real_open_app(real_guarded_page, "")
    result: list[int] | None = real_guarded_page.evaluate(_PLAYOFF_BRACKET_JS)
    if result is None:
        pytest.skip("no playoff telecasts present in the real vault data")
    bad_round, regular_with_round, over_before_2024, over_2024_plus = result
    assert bad_round == 0, "a telecast had a playoff_round outside the four known rounds"
    assert regular_with_round == 0, "a regular-season telecast carried a playoff_round"
    assert over_before_2024 == 0, "a pre-2024 season exceeded the 3-game CFP bracket size"
    assert over_2024_plus == 0, "a 2024-or-later season exceeded the 11-game CFP bracket size"


_FACET_TIMING_JS = """
async () => {
  const { computeView } = await import(new URL('./modules/select.js', location.href).href);
  const hooks = window.__testHooks;
  const data = hooks.data;
  const state = hooks.getState();
  state.people = data.lookups.people.slice(0, 3).map((p) => p.id);
  computeView(data, state);
  const runs = 20;
  const start = performance.now();
  for (let i = 0; i < runs; i += 1) computeView(data, state);
  return (performance.now() - start) / runs;
}
"""


def test_real_facet_pass_is_fast(
    real_guarded_page: Page, real_open_app: Callable[[Page, str], None]
) -> None:
    """T-04.2-26: the per-render facet pass stays cheap on real data. Asserts
    on a local timing number only; nothing from the vault is printed."""
    real_open_app(real_guarded_page, "")
    mean_ms: float = real_guarded_page.evaluate(_FACET_TIMING_JS)
    assert mean_ms <= 20, "mean computeView time (facets included) exceeded 20 ms"


_ANNOUNCER_FIT_JS = """
() => {
  const results = document.getElementById('person-results');
  const wrapped = Array.from(results.querySelectorAll('.option-role')).filter(
    (e) => e.textContent === 'Play-by-play'
      && e.getBoundingClientRect().height > 1.5 * parseFloat(getComputedStyle(e).lineHeight)
  ).length;
  return [results.scrollWidth, results.clientWidth, wrapped];
}
"""


def test_real_announcers_list_fits(
    real_guarded_page: Page, real_open_app: Callable[[Page, str], None]
) -> None:
    """D-32: on the real build the Announcers list never scrolls sideways and
    no Play-by-play label wraps -- numbers only."""
    real_guarded_page.set_viewport_size({"width": 1280, "height": 800})
    real_open_app(real_guarded_page, "")
    real_guarded_page.click("#trigger-announcers")
    real_guarded_page.wait_for_function(
        "document.getElementById('pop-announcers').matches(':popover-open')"
    )
    result: list[float] = real_guarded_page.evaluate(_ANNOUNCER_FIT_JS)
    scroll_width, client_width, wrapped = result
    assert scroll_width <= client_width, "the announcer list scrolls sideways"
    assert wrapped == 0, "a Play-by-play label wrapped"


_SCROLLERS_JS = """
() => {
  const dialog = document.getElementById('detail-panel');
  const over = (el) => {
    const oy = getComputedStyle(el).overflowY;
    return (oy === 'auto' || oy === 'scroll') && el.scrollHeight > el.clientHeight + 1;
  };
  const count = [dialog, ...dialog.querySelectorAll('*')].filter(over).length;
  return [count, over(dialog) ? 1 : 0];
}
"""


def test_real_modal_never_shows_two_scrollers(
    real_guarded_page: Page,
    real_open_app: Callable[[Page, str], None],
    real_raw: dict[str, Any],
) -> None:
    """D-38: on the real build no sampled panel shows more than one scroller and
    the dialog itself never scrolls -- numbers only."""
    real_guarded_page.set_viewport_size({"width": 1280, "height": 480})
    real_open_app(real_guarded_page, "")
    total = len(real_raw["telecasts"]["season"])
    worst = 0
    dialog_scrolls = 0
    for i in range(0, total, 25):
        real_guarded_page.evaluate(f"window.__testHooks.openPanel({i})")
        count, dialog_scrolled = real_guarded_page.evaluate(_SCROLLERS_JS)
        worst = max(worst, count)
        dialog_scrolls += dialog_scrolled
        real_guarded_page.evaluate("window.__testHooks.closePanel()")
    assert worst <= 1
    assert dialog_scrolls == 0
