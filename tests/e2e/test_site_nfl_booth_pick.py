"""15-04: the NFL controller's one-at-a-time Booths/Announcers rule (D-04, D-05), driven
through the test hooks before the Crews table exists."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_HOOKS = "window.__nflTestHooks"


def _status(page: Page) -> str:
    return (page.locator("#pick-status").text_content() or "").strip()


def _state(page: Page) -> dict[str, Any]:
    return page.evaluate(f"{_HOOKS}.getState()")


def _setup(page: Page, open_nfl_app: Callable[..., None]) -> tuple[dict[str, str], str]:
    """Open the app; return one catalog entry and a person id that is not its play-by-play."""
    open_nfl_app(page)
    catalog = page.evaluate(f"{_HOOKS}.getBoothCatalog()")
    first = catalog[0]
    own = first["key"].split(":", 1)[1]
    other = next(e["key"].split(":", 1)[1] for e in catalog if e["key"].split(":", 1)[1] != own)
    return first, other


def test_row_pick_replaces_booths_and_clears_announcers(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    booth, person = _setup(page, open_nfl_app)
    page.evaluate(f"p => {_HOOKS}.setState({{ people: [p] }})", person)
    assert _state(page)["people"] == [person]
    page.evaluate(f"([k, l]) => {_HOOKS}.pickBoothRow(k, l)", [booth["key"], "A and B"])
    state = _state(page)
    assert state["booths"] == [booth["key"]]
    assert state["people"] == []
    assert _status(page) == "Booths pick set to A and B. Announcers pick cleared."


def test_row_pick_without_announcers_has_no_cleared_note(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    booth, _ = _setup(page, open_nfl_app)
    page.evaluate(f"([k, l]) => {_HOOKS}.pickBoothRow(k, l)", [booth["key"], "A and B"])
    assert _status(page) == "Booths pick set to A and B."


def test_same_row_pick_clears_booths(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    booth, _ = _setup(page, open_nfl_app)
    pick = f"([k, l]) => {_HOOKS}.pickBoothRow(k, l)"
    page.evaluate(pick, [booth["key"], "A and B"])
    page.evaluate(pick, [booth["key"], "A and B"])
    assert _state(page)["booths"] == []
    assert _status(page) == "Booths pick cleared."


def test_announcers_pick_clears_a_row_made_booths_pick(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    booth, person = _setup(page, open_nfl_app)
    page.evaluate(f"([k, l]) => {_HOOKS}.pickBoothRow(k, l)", [booth["key"], "A and B"])
    page.evaluate(f"p => {_HOOKS}.setState({{ people: [p] }})", person)
    state = _state(page)
    assert state["booths"] == []
    assert state["people"] == [person]
    name = page.evaluate("document.querySelector('#nfl-chips .chip-label').textContent")
    assert _status(page) == f"Announcers pick set to {name}. Booths pick cleared."


def test_filter_bar_booths_and_announcers_intersect(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    booth, person = _setup(page, open_nfl_app)
    page.evaluate(f"k => {_HOOKS}.setState({{ booths: [k] }})", booth["key"])
    page.evaluate(f"p => {_HOOKS}.setState({{ people: [p] }})", person)
    state = _state(page)
    assert state["booths"] == [booth["key"]]
    assert state["people"] == [person]


def test_row_made_flag_is_memory_only_after_reload(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    booth, person = _setup(page, open_nfl_app)
    page.evaluate(f"([k, l]) => {_HOOKS}.pickBoothRow(k, l)", [booth["key"], "A and B"])
    page.reload()
    page.wait_for_function(f"{_HOOKS} && {_HOOKS}.ready === true")
    assert _state(page)["booths"] == [booth["key"]]
    page.evaluate(f"p => {_HOOKS}.setState({{ people: [p] }})", person)
    state = _state(page)
    assert state["booths"] == [booth["key"]]
    assert state["people"] == [person]
