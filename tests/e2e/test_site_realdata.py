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

Under `-n auto` each worker that runs these tests builds its own real site from
the read-only `processed/site-data.json` (`booth-review site` takes no vault
lock), so workers never contend on the vault.
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


_FADE_HIDE_REAL_JS = """
async () => {
  const { computeView, defaultState } = await import(
    new URL('./modules/select.js', location.href).href
  );
  const data = window.__testHooks.data;
  const t = data.t;
  const pairCounts = new Map();
  for (let i = 0; i < data.n; i += 1) {
    const a = Math.min(t.home_team[i], t.away_team[i]);
    const b = Math.max(t.home_team[i], t.away_team[i]);
    if (a === b) continue;
    const key = a * 100000 + b;
    pairCounts.set(key, (pairCounts.get(key) ?? 0) + 1);
  }
  let bestKey = -1;
  let bestCount = 0;
  for (const [key, count] of pairCounts) {
    if (count > bestCount) { bestKey = key; bestCount = count; }
  }
  const pairA = Math.floor(bestKey / 100000);
  const pairB = bestKey % 100000;
  const h2hState = {
    school: [data.teamSlugs[pairA], data.teamSlugs[pairB]],
    h2h: true,
  };
  const states = data.seasons.map((s) => ({ seasons: [s, s] }));
  states.push({ postseason: 'only' }, { postseason: 'exclude' }, { slots: ['late'] }, h2hState);
  const fade = (s) => ({ ...defaultState(data), ...s, dots: 'fade' });
  const hide = (s) => ({ ...defaultState(data), ...s, dots: 'hide' });
  const facetKey = (f) => JSON.stringify([
    Array.from(f.seasons), Array.from(f.networks), Array.from(f.schools), Array.from(f.people),
  ]);
  let countDiffers = 0;
  let facetsDiffer = 0;
  let fadeNotAll = 0;
  let hideFailing = 0;
  let outsidePair = 0;
  for (const s of states) {
    const vf = computeView(data, fade(s));
    const vh = computeView(data, hide(s));
    if (vf.passingCount !== vh.passingCount) countDiffers += 1;
    if (facetKey(vf.facets) !== facetKey(vh.facets)) facetsDiffer += 1;
    if (vf.visibleCount !== data.n) fadeNotAll += 1;
    for (let i = 0; i < data.n; i += 1) {
      if (vh.visible[i] === 1 && vh.passesFilters[i] === 0) hideFailing += 1;
    }
  }
  const hv = computeView(data, hide(h2hState));
  for (let i = 0; i < data.n; i += 1) {
    if (hv.passesFilters[i] !== 1) continue;
    const a = Math.min(t.home_team[i], t.away_team[i]);
    const b = Math.max(t.home_team[i], t.away_team[i]);
    if (a !== pairA || b !== pairB) outsidePair += 1;
  }
  const tooFew = hv.passingCount < 2 ? 1 : 0;
  const netId = data.lookups.networks[data.primaryNetworks[0]].id;
  const ns = { networks: [netId] };
  const nf = computeView(data, fade(ns));
  const nh = computeView(data, hide(ns));
  const netMismatch = (nf.visibleCount !== nf.passingCount ? 1 : 0)
    + (nh.visibleCount !== nh.passingCount ? 1 : 0);
  const hs = hide(h2hState);
  computeView(data, hs);
  const runs = 20;
  const start = performance.now();
  for (let i = 0; i < runs; i += 1) computeView(data, hs);
  const meanMs = (performance.now() - start) / runs;
  return [countDiffers, facetsDiffer, fadeNotAll, hideFailing, outsidePair, tooFew, netMismatch,
          meanMs];
}
"""


def test_real_fade_hide_and_head_to_head_counts(
    real_guarded_page: Page, real_open_app: Callable[[Page, str], None]
) -> None:
    """D-05, D-06, D-07, D-14: on the real build Fade and Hide never change the
    passing count or facets, Fade draws every dot, Hide draws only passing dots,
    Networks hides in both, and Head-to-head keeps only the pair's games -- integers
    and one timing only."""
    real_open_app(real_guarded_page, "")
    result: list[float] = real_guarded_page.evaluate(_FADE_HIDE_REAL_JS)
    count_differs = result[0]
    facets_differ = result[1]
    fade_not_all = result[2]
    hide_failing = result[3]
    outside_pair = result[4]
    too_few = result[5]
    net_mismatch = result[6]
    mean_ms = result[7]
    assert count_differs == 0, "Fade and Hide gave different passing counts"
    assert facets_differ == 0, "Fade and Hide gave different facets"
    assert fade_not_all == 0, "a Fade state without Networks drew fewer than every dot"
    assert hide_failing == 0, "Hide drew a dot that fails a filter"
    assert outside_pair == 0, "Head-to-head passed a dot outside the selected pair"
    assert too_few == 0, "Head-to-head passed fewer than two games"
    assert net_mismatch == 0, "a Networks state drew dots that did not pass"
    assert mean_ms <= 20, "mean computeView time under Hide + Head-to-head exceeded 20 ms"


_ANNOUNCER_FIT_JS = """
() => {
  const results = document.getElementById('person-results');
  const wrapped = Array.from(results.querySelectorAll('.option-role .role-pill')).filter(
    (e) => e.getBoundingClientRect().height > 1.5 * parseFloat(getComputedStyle(e).lineHeight)
  ).length;
  return [results.scrollWidth, results.clientWidth, wrapped];
}
"""


def test_real_announcers_list_fits(
    real_guarded_page: Page, real_open_app: Callable[[Page, str], None]
) -> None:
    """D-32: on the real build the Announcers list never scrolls sideways and
    no role pill wraps -- numbers only."""
    real_guarded_page.set_viewport_size({"width": 1280, "height": 800})
    real_open_app(real_guarded_page, "")
    real_guarded_page.click("#trigger-announcers")
    real_guarded_page.wait_for_function(
        "document.getElementById('pop-announcers').matches(':popover-open')"
    )
    result: list[float] = real_guarded_page.evaluate(_ANNOUNCER_FIT_JS)
    scroll_width, client_width, wrapped = result
    assert scroll_width <= client_width, "the announcer list scrolls sideways"
    assert wrapped == 0, "a role pill wrapped"


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


_BARS_REAL_JS = """
async () => {
  const bars = await import(new URL('./modules/bars.js', location.href).href);
  const sel = await import(new URL('./modules/select.js', location.href).href);
  const data = window.__testHooks.data;
  const base = sel.defaultState(data);
  let announcerMismatch = 0;
  let stackedMismatch = 0;
  let sharedOver = 0;
  let viewersHits = 0;
  let maxMs = 0;
  const teamGames = (view, slug) => {
    const idx = data.teamIndexBySlug.get(slug);
    return bars.passingIndices(view).filter(
      (i) => data.t.home_team[i] === idx || data.t.away_team[i] === idx
    ).length;
  };
  const count = Math.min(10, data.teamSlugs.length);
  for (let k = 0; k < count; k += 1) {
    const state = { ...base, school: [data.teamSlugs[k]] };
    const t0 = performance.now();
    const view = sel.computeView(data, state);
    const model = bars.barsModel(data, view, state);
    maxMs = Math.max(maxMs, performance.now() - t0);
    for (const row of model.rows) {
      const idx = data.personIndexById.get(row.target.id);
      if (row.total !== view.facets.people[idx]) announcerMismatch += 1;
    }
    if (JSON.stringify(model).includes('viewers')) viewersHits += 1;
    const stackedState = { ...state, by: 'network' };
    const stacked = bars.barsModel(data, view, stackedState);
    for (const row of stacked.rows) {
      const sum = row.segments.reduce((acc, s) => acc + s.count, 0);
      if (row.total !== sum) stackedMismatch += 1;
    }
    if (JSON.stringify(stacked).includes('viewers')) viewersHits += 1;
    if (k + 1 < data.teamSlugs.length) {
      const pair = { ...base, school: [data.teamSlugs[k], data.teamSlugs[k + 1]] };
      const pv = sel.computeView(data, pair);
      const fly = bars.butterflyModel(data, pv, pair);
      const left = teamGames(pv, data.teamSlugs[k]);
      const right = teamGames(pv, data.teamSlugs[k + 1]);
      if (fly.shared > left || fly.shared > right) sharedOver += 1;
      if (JSON.stringify(fly).includes('viewers')) viewersHits += 1;
    }
  }
  return [announcerMismatch, stackedMismatch, sharedOver, viewersHits, maxMs];
}
"""


def test_real_bars_counts_match_facets(
    real_guarded_page: Page, real_open_app: Callable[[Page, str], None]
) -> None:
    """Bar totals agree with the facet counts, stacked totals with their
    segments, butterfly shared counts fit both sides, no model carries a viewer
    figure, and a model builds quickly -- integers and a timing only."""
    real_open_app(real_guarded_page, "")
    result: list[float] = real_guarded_page.evaluate(_BARS_REAL_JS)
    announcer_mismatch, stacked_mismatch, shared_over, viewers_hits, max_ms = result
    assert announcer_mismatch == 0, "an announcer bar total differed from its facet count"
    assert stacked_mismatch == 0, "a stacked row total differed from its segment sum"
    assert shared_over == 0, "a butterfly shared count exceeded a side"
    assert viewers_hits == 0, "a bar model carried a viewer figure"
    assert max_ms < 100, "building a bar model took 100 ms or more"


_FAMILY_REAL_JS = """
async () => {
  const bars = await import(new URL('./modules/bars.js', location.href).href);
  const copy = await import(new URL('./modules/bar-copy.js', location.href).href);
  const sel = await import(new URL('./modules/select.js', location.href).href);
  const data = window.__testHooks.data;
  const base = sel.defaultState(data);
  let segmentMismatch = 0;
  let nonFamilyRows = 0;
  let badShades = 0;
  let untaggedPbp = 0;
  let badTitles = 0;
  let viewersHits = 0;
  const count = Math.min(10, data.teamSlugs.length);
  for (let k = 0; k < count; k += 1) {
    const slug = data.teamSlugs[k];
    const schoolName = data.lookups.teams[data.teamIndexBySlug.get(slug)].name;
    const state = { ...base, school: [slug] };
    const view = sel.computeView(data, state);
    const stacked = bars.barsModel(data, view, { ...state, by: 'network' });
    if (stacked) {
      for (const row of stacked.rows) {
        if (!row.key.startsWith('f:')) nonFamilyRows += 1;
        for (const seg of row.segments) {
          const sum = (seg.channels || []).reduce((acc, c) => acc + c.count, 0);
          if (seg.count !== sum) segmentMismatch += 1;
          for (const c of seg.channels || []) {
            if (c.shade < 0 || c.shade >= row.shadeCount) badShades += 1;
          }
        }
      }
      if (JSON.stringify(stacked).includes('viewers')) viewersHits += 1;
    }
    const pbpState = { ...state, role: 'pbp' };
    const pbpView = sel.computeView(data, pbpState);
    const simple = bars.barsModel(data, pbpView, pbpState);
    if (!simple || simple.rows.length === 0) continue;
    for (const row of simple.rows) {
      if (!(row.roles || []).includes('pbp') || row.label.includes('PBP')) untaggedPbp += 1;
    }
    if (JSON.stringify(simple).includes('viewers')) viewersHits += 1;
    const id = simple.rows[0].target.id;
    const personName = data.lookups.people[data.personIndexById.get(id)].name;
    for (const group of ['announcers', 'teams']) {
      const drilled = { ...state, people: [id], group };
      const dv = sel.computeView(data, drilled);
      const model = bars.barsModel(data, dv, drilled);
      if (!model) continue;
      const title = copy.chartTitle(model, data, drilled);
      if (!title.includes(schoolName) || !title.includes(personName)) badTitles += 1;
      if (JSON.stringify(model).includes('viewers')) viewersHits += 1;
    }
  }
  return [segmentMismatch, nonFamilyRows, badShades, untaggedPbp, badTitles, viewersHits];
}
"""


def test_real_family_bars_roles_and_titles(
    real_guarded_page: Page, real_open_app: Callable[[Page, str], None]
) -> None:
    """Family rows, role filtering, and drill-in titles hold on the real data --
    integers only; names are compared inside the browser."""
    real_open_app(real_guarded_page, "")
    result: list[int] = real_guarded_page.evaluate(_FAMILY_REAL_JS)
    segment_mismatch, non_family_rows, bad_shades, untagged_pbp, bad_titles, viewers_hits = result
    assert segment_mismatch == 0, "a segment count differed from its channel sum"
    assert non_family_rows == 0, "a stacked Announcers row was not a family row"
    assert bad_shades == 0, "a channel shade was out of range"
    assert untagged_pbp == 0, "a PBP-filtered row was not PBP-tagged"
    assert bad_titles == 0, "a drill-in title missed the school or the announcer"
    assert viewers_hits == 0, "a bar model carried a viewer figure"


_MAIN_FAMILY_REAL_JS = """
async () => {
  const bars = await import(new URL('./modules/bars.js', location.href).href);
  const sel = await import(new URL('./modules/select.js', location.href).href);
  const pal = await import(new URL('./modules/palette.js', location.href).href);
  const data = window.__testHooks.data;
  const base = sel.defaultState(data);
  let notFamily = 0;
  let familyDiffers = 0;
  let stackedTotalDiffers = 0;
  let sideTotalDiffers = 0;
  let viewersHits = 0;
  const segSum = (segments) => segments.reduce((acc, s) => acc + s.count, 0);
  const recount = (view, state, personIndex) => {
    const tally = new Map();
    for (const i of bars.gamesForBars(view)) {
      if (sel.personOnGame(data, i, personIndex, state.role) == null) continue;
      const fam = pal.familyKey(data.lookups.networks[data.t.network[i]].family);
      tally.set(fam, (tally.get(fam) || 0) + 1);
    }
    let best = null;
    let bestN = 0;
    for (const fam of pal.FAMILY_ORDER) {
      const n = tally.get(fam) || 0;
      if (n > bestN) {
        best = fam;
        bestN = n;
      }
    }
    return best;
  };
  const count = Math.min(10, data.teamSlugs.length);
  for (let k = 0; k < count; k += 1) {
    const state = { ...base, school: [data.teamSlugs[k]] };
    const view = sel.computeView(data, state);
    const simple = bars.barsModel(data, view, state);
    if (simple) {
      for (const row of simple.rows) {
        if (!pal.FAMILY_ORDER.includes(row.mainFamily)) notFamily += 1;
        const p = data.personIndexById.get(row.target.id);
        if (row.mainFamily !== recount(view, state, p)) familyDiffers += 1;
      }
      if (JSON.stringify(simple).includes('viewers')) viewersHits += 1;
    }
    const stacked = bars.barsModel(data, view, { ...state, by: 'network' });
    if (stacked) {
      for (const row of stacked.rows) {
        if (row.total !== segSum(row.segments)) stackedTotalDiffers += 1;
      }
      if (JSON.stringify(stacked).includes('viewers')) viewersHits += 1;
    }
    if (k < 9 && k + 1 < data.teamSlugs.length) {
      const pair = {
        ...base,
        by: 'network',
        school: [data.teamSlugs[k], data.teamSlugs[k + 1]],
      };
      const pv = sel.computeView(data, pair);
      const fly = bars.butterflyModel(data, pv, pair);
      if (fly) {
        for (const row of fly.rows) {
          for (const side of row.sides) {
            if (side.total !== segSum(side.segments)) sideTotalDiffers += 1;
          }
        }
        if (JSON.stringify(fly).includes('viewers')) viewersHits += 1;
      }
    }
  }
  return [notFamily, familyDiffers, stackedTotalDiffers, sideTotalDiffers, viewersHits];
}
"""


def test_real_main_family_and_stacked_totals(
    real_guarded_page: Page, real_open_app: Callable[[Page, str], None]
) -> None:
    """Main-family colors match an independent recount and stacked totals equal
    their segment sums on the real data -- integers only."""
    real_open_app(real_guarded_page, "")
    result: list[int] = real_guarded_page.evaluate(_MAIN_FAMILY_REAL_JS)
    not_family, family_differs, stacked_total_differs, side_total_differs, viewers_hits = result
    assert not_family == 0, "a simple row's main family was not a known family"
    assert family_differs == 0, "a row's main family differed from the recount"
    assert stacked_total_differs == 0, "a stacked row total differed from its segment sum"
    assert side_total_differs == 0, "a butterfly side total differed from its segment sum"
    assert viewers_hits == 0, "a bar model carried a viewer figure"


_SPREAD_REAL_JS = """
() => {
  const t = window.__testHooks.data.t;
  const n = t.season.length;
  const pregamePresent = 'pregame' in t ? 1 : 0;
  const homeSpreadNotArray = Array.isArray(t.home_spread) && t.home_spread.length === n ? 0 : 1;
  let spreadWithoutInputs = 0;
  let spreadMissing = 0;
  let wrongMagnitude = 0;
  let negativeZero = 0;
  for (let i = 0; i < n; i += 1) {
    const hs = t.home_spread[i];
    const hp = t.home_points[i];
    const ap = t.away_points[i];
    const x = t.spread[i];
    const decided = hp != null && ap != null && hp !== ap;
    if (x != null && (hs == null || !decided)) spreadWithoutInputs += 1;
    if (hs != null && decided && x == null) spreadMissing += 1;
    if (x != null && hs != null && Math.abs(x) !== Math.abs(hs)) wrongMagnitude += 1;
    if (Object.is(x, -0)) negativeZero += 1;
  }
  return [pregamePresent, homeSpreadNotArray, spreadWithoutInputs, spreadMissing,
          wrongMagnitude, negativeZero];
}
"""


def test_real_home_spread_and_spread_axis_counts(
    real_guarded_page: Page, real_open_app: Callable[[Page, str], None]
) -> None:
    """04.8 D-01, D-03, D-10: on the real build the site data has no pregame
    column, home_spread is a full column, and the derived spread x is set exactly
    when a line, a score, and a winner exist, with the line's magnitude -- integers only."""
    real_open_app(real_guarded_page, "")
    counts: list[int] = real_guarded_page.evaluate(_SPREAD_REAL_JS)
    pregame_present, home_spread_not_array, spread_without_inputs = counts[:3]
    spread_missing, wrong_magnitude, negative_zero = counts[3:]
    assert pregame_present == 0, "site data still carries pregame"
    assert home_spread_not_array == 0, "home_spread is not a full column"
    assert spread_without_inputs == 0, "a spread x was set without a line, score, or winner"
    assert spread_missing == 0, "a decided game with a line had no spread x"
    assert wrong_magnitude == 0, "a spread x's magnitude differed from its line"
    assert negative_zero == 0, "a spread x was negative zero"


_NAMED_GAME_COUNTS_JS = """
() => {
  const data = window.__testHooks.data;
  const view = window.__testHooks.getView();
  const counts = view.facets.games;
  let playoffWithRound = 0;
  let playoffNullRound = 0;
  let rivalryOnNonRegular = 0;
  const rivalrySeasons = new Map();
  let rivalryTwiceInSeason = 0;
  for (let i = 0; i < data.n; i += 1) {
    const gameType = data.t.game_type[i];
    const round = data.t.playoff_round[i];
    const riv = data.t.rivalry[i];
    if (gameType === 'playoff') {
      if (round === null) playoffNullRound += 1;
      else playoffWithRound += 1;
    }
    if (riv !== null) {
      if (gameType !== 'regular') rivalryOnNonRegular += 1;
      const key = riv + ':' + data.t.season[i];
      const seen = (rivalrySeasons.get(key) || 0) + 1;
      rivalrySeasons.set(key, seen);
      if (seen === 2) rivalryTwiceInSeason += 1;
    }
  }
  let cfpTotal = 0;
  let franchiseWithoutBowl = 0;
  let gamesWithZeroRows = 0;
  let rivalCount = 0;
  const withDots = new Set();
  for (const memberships of data.dotGames) for (const g of memberships) withDots.add(g);
  for (const g of data.games) {
    if (g.kind === 'cfp') cfpTotal += counts[g.index];
    if (g.kind === 'bowl' && !withDots.has(g.index)) franchiseWithoutBowl += 1;
    if (g.kind !== 'cfp' && counts[g.index] === 0) gamesWithZeroRows += 1;
    if (g.kind === 'rivalry') rivalCount += 1;
  }
  return {
    playoffWithRound,
    cfpTotal,
    playoffNullRound,
    rivalryOnNonRegular,
    rivalryTwiceInSeason,
    franchiseWithoutBowl,
    gamesWithZeroRows,
    rivalCount,
  };
}
"""


def test_real_named_game_counts_are_consistent(
    real_guarded_page: Page, real_open_app: Callable[[Page, str], None]
) -> None:
    """D-11, D-13, D-19: named-game tags on the real build are consistent.
    The four CFP counts sum to the playoff telecasts with a round, no rivalry
    sits on a non-regular telecast or twice in one season, every bowl franchise
    has rows, and no bowl or rivalry game is empty at the default view.
    Integers only; the null-round count is reported, not asserted."""
    real_open_app(real_guarded_page, "")
    counts: dict[str, int] = real_guarded_page.evaluate(_NAMED_GAME_COUNTS_JS)
    playoff_with_round = counts["playoffWithRound"]
    cfp_total = counts["cfpTotal"]
    rivalry_on_non_regular = counts["rivalryOnNonRegular"]
    rivalry_twice = counts["rivalryTwiceInSeason"]
    franchise_without_bowl = counts["franchiseWithoutBowl"]
    zero_rows = counts["gamesWithZeroRows"]
    rival_count = counts["rivalCount"]
    assert cfp_total == playoff_with_round, "CFP round counts did not sum to rounded playoffs"
    assert rivalry_on_non_regular == 0, "a rivalry was tagged on a non-regular telecast"
    assert rivalry_twice == 0, "a rivalry was tagged twice in one season"
    assert franchise_without_bowl == 0, "a bowl franchise had no telecast rows"
    assert zero_rows == 0, "a bowl or rivalry game had zero rows at the default view"
    assert rival_count > 0, "no rivalry games present"


_GEOMETRY_JS = """
() => [
  document.getElementById('toolbar').getBoundingClientRect().height,
  document.getElementById('chart-area').getBoundingClientRect().top,
]
"""

_PICK_LONGEST_GAME_JS = """
() => {
  const games = window.__testHooks.data.games;
  let longest = games[0];
  for (const g of games) if (g.label.length > longest.label.length) longest = g;
  window.__testHooks.setState({ game: longest.slug });
  return true;
}
"""


def test_real_named_game_toolbar_stable_at_1024(
    real_guarded_page: Page, real_open_app: Callable[[Page, str], None]
) -> None:
    """D-21: picking the longest-label game at 1024px leaves the toolbar
    height and chart top unchanged. Numbers only."""
    real_guarded_page.set_viewport_size({"width": 1024, "height": 900})
    real_open_app(real_guarded_page, "?slot=noon,afternoon,prime,late&seasons=2014-2025")
    before: list[float] = real_guarded_page.evaluate(_GEOMETRY_JS)
    toolbar_before = before[0]
    top_before = before[1]
    picked: bool = real_guarded_page.evaluate(_PICK_LONGEST_GAME_JS)
    after: list[float] = real_guarded_page.evaluate(_GEOMETRY_JS)
    toolbar_after = after[0]
    top_after = after[1]
    assert picked
    assert toolbar_after == toolbar_before
    assert top_after == top_before
