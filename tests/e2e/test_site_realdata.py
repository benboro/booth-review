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
      team: null,
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
    people = real_raw["lookups"]["people"]
    assert len(expected_sets) == len(people)

    actual: list[list[int]] = real_guarded_page.evaluate(_HIGHLIGHT_ALL_PEOPLE_JS)
    assert len(actual) == len(people)

    mismatches = 0
    for expected_set, actual_list in zip(expected_sets, actual, strict=True):
        if sorted(expected_set) != actual_list:
            mismatches += 1

    assert mismatches == 0, f"{mismatches} of {len(people)} people mismatched"


def test_real_default_url_is_clean(
    real_guarded_page: Page, real_open_app: Callable[[Page, str], None]
) -> None:
    """D-12: default load leaves no query string."""
    real_open_app(real_guarded_page, "")
    assert "?" not in real_guarded_page.url
