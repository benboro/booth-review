"""Detail-modal gap-round-1 browser tests (D-38, D-39; D-38 tests are added later
by plan 04.2-16). Proven against the synthetic contract fixture, route-mutated
where a case needs data the fixture lacks.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _serve_patched(
    page: Page, fixture_raw: dict[str, Any], patch: Callable[[dict[str, Any]], None]
) -> None:
    """Serves a deep copy of the fixture, mutated by `patch`, as site-data.json."""
    raw = copy.deepcopy(fixture_raw)
    patch(raw)
    page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))


def _open(
    page: Page,
    open_app: Callable[[Page, str], None],
    index: int,
    fixture_raw: dict[str, Any] | None = None,
    patch: Callable[[dict[str, Any]], None] | None = None,
) -> str:
    page.set_viewport_size({"width": 1280, "height": 800})
    if fixture_raw is not None and patch is not None:
        _serve_patched(page, fixture_raw, patch)
    open_app(page, "")
    page.evaluate(f"window.__testHooks.openPanel({index})")
    return page.locator("#panel-body").inner_text()


def test_empty_crew_shows_crew_not_listed(
    guarded_page: Page, open_app: Callable[[Page, str], None], fixture_raw: dict[str, Any]
) -> None:
    """D-39: an empty crew reads 'Crew not listed', never a bare heading."""

    def patch(raw: dict[str, Any]) -> None:
        raw["telecasts"]["crew"][3] = []

    _open(guarded_page, open_app, 3, fixture_raw, patch)
    heading = guarded_page.locator("#panel-body h3", has_text="Crew")
    expect(heading).to_have_count(1)
    expect(heading.locator("xpath=following-sibling::*[1]")).to_have_text("Crew not listed")
    expect(guarded_page.locator("#panel-body .panel-crew li")).to_have_count(0)


def test_nielsen_adobe_label_shows_once(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-39: the Nielsen + Adobe label appears once, as the linked badge."""
    text = _open(guarded_page, open_app, 5)
    assert text.count("Nielsen + Adobe") == 1
    assert "Nielsen+Adobe measurement" not in text
    badge = guarded_page.locator("#panel-body .badge")
    expect(badge).to_have_text("Nielsen + Adobe (streaming)")
    expect(badge).to_have_attribute("href", "https://example.com/measurement-nielsen-adobe")


def test_combined_feeds_line_shows_once(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-39: one 'Combined across 3 feeds' line, linked to the flag's source."""
    text = _open(guarded_page, open_app, 7)
    assert text.count("Combined across") == 1
    assert "Combined across 3 feeds" in text
    assert "(MegaCast)" not in text
    link = guarded_page.locator("#panel-body a:has-text('Combined across 3 feeds')")
    expect(link).to_have_attribute("href", "https://example.com/combined-megacast")


def test_combined_flag_kept_without_feed_count(
    guarded_page: Page, open_app: Callable[[Page, str], None], fixture_raw: dict[str, Any]
) -> None:
    """D-39: with no feed count, the combined flag still lists with its label."""

    def patch(raw: dict[str, Any]) -> None:
        raw["telecasts"]["combined_feeds"][7] = None

    text = _open(guarded_page, open_app, 7, fixture_raw, patch)
    assert text.count("Combined across feeds (MegaCast)") == 1


def test_other_flags_still_listed(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-39 guard: era and model_break flags still list."""
    assert "Nielsen out-of-home (Aug 2020)" in _open(guarded_page, open_app, 1)
    guarded_page.evaluate("window.__testHooks.openPanel(11)")
    assert (
        "CFBD win-probability model break (2025+)"
        in guarded_page.locator("#panel-body").inner_text()
    )


SCROLLERS = """
() => {
  const dialog = document.getElementById('detail-panel');
  return [dialog, ...dialog.querySelectorAll('*')]
    .filter((el) => {
      const oy = getComputedStyle(el).overflowY;
      return (oy === 'auto' || oy === 'scroll') && el.scrollHeight > el.clientHeight + 1;
    })
    .map((el) => el.className || el.tagName);
}
"""


def _open_sized(
    page: Page, open_app: Callable[[Page, str], None], width: int, height: int, index: int
) -> None:
    page.set_viewport_size({"width": width, "height": height})
    open_app(page, "")
    page.evaluate(f"window.__testHooks.openPanel({index})")


def test_modal_has_one_scroller_when_content_is_long(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-38: .panel-inner is the only scroll container; the dialog never scrolls."""
    _open_sized(guarded_page, open_app, 1280, 480, 7)
    assert guarded_page.evaluate(SCROLLERS) == ["panel-inner"]
    sizes: list[float] = guarded_page.eval_on_selector(
        "#detail-panel", "el => [el.scrollHeight, el.clientHeight]"
    )
    assert sizes[0] <= sizes[1] + 1


def test_modal_has_no_scroller_when_content_fits(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-38: a short panel in a tall viewport has no scrollbar at all."""
    _open_sized(guarded_page, open_app, 1280, 1400, 0)
    assert guarded_page.evaluate(SCROLLERS) == []


def test_phone_sheet_has_at_most_one_scroller(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-38: on the phone sheet the dialog itself never scrolls."""
    open_app(mobile_page, "")
    mobile_page.evaluate("window.__testHooks.openPanel(7)")
    found: list[str] = mobile_page.evaluate(SCROLLERS)
    assert found in ([], ["panel-inner"])
    assert "DIALOG" not in found


def test_close_then_reopen_in_one_task_keeps_the_panel_live(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """WR-03: `close` fires as a queued task, so a close and reopen in the same
    task must not let the stale event forget the open panel: a later render
    still refreshes it."""
    _open(guarded_page, open_app, 0)
    guarded_page.evaluate(
        """() => new Promise((resolve) => {
          window.__testHooks.closePanel();
          window.__testHooks.openPanel(1);
          setTimeout(resolve, 50);
        })"""
    )
    expect(guarded_page.locator("#detail-panel")).to_have_attribute("open", "")
    body = guarded_page.locator("#panel-body")
    expect(body).to_contain_text("Spread: 7.0 · Excitement: 6.8")
    guarded_page.evaluate("window.__testHooks.setState({ axis: 'excitement' })")
    expect(body).to_contain_text("Excitement: 6.8 · Spread: 7.0")


CLOSE_IN_VIEW = """
() => {
  const inner = document.querySelector('#detail-panel .panel-inner');
  inner.scrollTop = inner.scrollHeight;
  const port = inner.getBoundingClientRect();
  const btn = document.getElementById('panel-close').getBoundingClientRect();
  const hit = document.elementFromPoint(btn.x + btn.width / 2, btn.y + btn.height / 2);
  return {
    scrolled: inner.scrollTop > 0,
    inside: btn.top >= port.top - 1 && btn.bottom <= port.bottom + 1,
    onTop: hit === document.getElementById('panel-close'),
    size: [btn.width, btn.height],
  };
}
"""


def test_close_button_stays_in_view_when_the_modal_scrolls(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """WR-04: scrolled to the bottom of a long panel, the x is still in view
    and on top, and clicking it closes the modal."""
    _open_sized(guarded_page, open_app, 1280, 400, 7)
    found = guarded_page.evaluate(CLOSE_IN_VIEW)
    assert found["scrolled"] and found["inside"] and found["onTop"]
    assert guarded_page.evaluate(SCROLLERS) == ["panel-inner"]
    guarded_page.click("#panel-close")
    assert guarded_page.evaluate("document.getElementById('detail-panel').open") is False


def test_phone_close_button_stays_in_view_and_keeps_its_target(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """WR-04 on the phone sheet: the x stays in view after scrolling, at 44px."""
    open_app(mobile_page, "")
    mobile_page.evaluate("window.__testHooks.openPanel(7)")
    found = mobile_page.evaluate(CLOSE_IN_VIEW)
    assert found["scrolled"] and found["inside"] and found["onTop"]
    assert found["size"][0] >= 44 and found["size"][1] >= 44
    assert mobile_page.evaluate(SCROLLERS) == ["panel-inner"]
