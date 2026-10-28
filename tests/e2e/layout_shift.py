"""Shared 0px-tolerance geometry helper for the "things stay put" e2e tests (Phase 26).

`layout_snapshot` returns whole-pixel positions of the parts of the page a filter pick must never
move: the tab strip, the bottom of the filter bar and the left edge of each filter group. Tests
compare two snapshots with `==`; there is no tolerance. Plan 07 adds the count-line keys
(`clear_x`, `summary_h`) through `include`.
"""

from __future__ import annotations

from typing import Any

from playwright.sync_api import Page

WAIT_TWO_FRAMES = "() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"

DEFAULT_KEYS = ("tabs", "toolbar_bottom", "group_x")

_SNAPSHOT_JS = """(include) => {
  const out = {};
  const top = (el) => Math.round(el.getBoundingClientRect().top + window.scrollY);
  const want = new Set(include);
  if (want.has('tabs')) out.tabs = top(document.getElementById('chart-tabs'));
  if (want.has('toolbar_bottom')) {
    out.toolbar_bottom = Math.round(
      document.getElementById('toolbar').getBoundingClientRect().bottom + window.scrollY);
  }
  if (want.has('group_x')) {
    out.group_x = [...document.querySelectorAll('#toolbar .fgroup')]
      .map((g) => Math.round(g.getBoundingClientRect().left));
  }
  if (want.has('clear_x')) {
    const el = document.getElementById('clear-filters');
    out.clear_x = el ? Math.round(el.getBoundingClientRect().left) : null;
  }
  if (want.has('summary_h')) {
    const el = document.getElementById('summary');
    out.summary_h = el ? Math.round(el.getBoundingClientRect().height) : null;
  }
  return out;
}"""


def set_state(page: Page, patch: dict[str, Any]) -> None:
    """Applies a state patch through the test hook and lets two frames settle."""
    page.evaluate("(patch) => window.__testHooks.setState(patch)", patch)
    page.evaluate(WAIT_TWO_FRAMES)


def layout_snapshot(page: Page, *, include: tuple[str, ...] = DEFAULT_KEYS) -> dict[str, Any]:
    """Whole-pixel positions named by `include`; equal snapshots mean nothing moved."""
    page.evaluate(WAIT_TWO_FRAMES)
    result: dict[str, Any] = page.evaluate(_SNAPSHOT_JS, list(include))
    return result
