"""16-05 (D-12): keyboard navigation over the MLB Postseason grid.

Synthetic grid, newest first: 2026 (division NL, LCS AL), 2025 (wild card NL, World Series),
2019 (division AL, LCS NL), 2014 (wild card AL, World Series). Columns are Season, Wild Card,
Division Series, League Championship Series, World Series.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

HOOKS = "window.__mlbTestHooks"
VIEW = "#mlb-view-postseason"
MODULE = "./sports/mlb/views/postseason.js"


def _next(page: Page, grid: list[list[list[str]]], pos: dict[str, int], key: str) -> dict[str, int]:
    return page.evaluate(  # type: ignore[no-any-return]
        "async ([m, grid, pos, key]) => (await import(m)).nextGridTarget(grid, pos, key)",
        [MODULE, grid, pos, key],
    )


@pytest.fixture
def post(mlb_guarded_page: Page, open_mlb_app: Callable[..., None]) -> Page:
    open_mlb_app(mlb_guarded_page, "?sport=mlb&view=postseason")
    return mlb_guarded_page


# Rows of columns of sub-blocks; column 1 is empty in row 1 and 2 (an empty cell), row 0 splits.
GRID = [
    [["s0"], [], ["a", "b"], ["c"]],
    [["s1"], ["d"], [], ["e"]],
    [["s2"], [], ["f"], []],
    [["s3"], ["g"], ["h"], ["i"]],
]


def test_next_grid_target_across_a_row(post: Page) -> None:
    assert _next(post, GRID, {"row": 0, "col": 0, "sub": 0}, "ArrowRight") == {
        "row": 0,
        "col": 2,
        "sub": 0,
    }
    # The sub-block index is kept when the next cell has it, else the first one.
    assert _next(post, GRID, {"row": 0, "col": 2, "sub": 1}, "ArrowRight") == {
        "row": 0,
        "col": 3,
        "sub": 0,
    }
    assert _next(post, GRID, {"row": 0, "col": 3, "sub": 0}, "ArrowLeft") == {
        "row": 0,
        "col": 2,
        "sub": 0,
    }
    assert _next(post, GRID, {"row": 0, "col": 3, "sub": 0}, "ArrowRight") == {
        "row": 0,
        "col": 3,
        "sub": 0,
    }
    assert _next(post, GRID, {"row": 1, "col": 3, "sub": 0}, "Home") == {
        "row": 1,
        "col": 0,
        "sub": 0,
    }
    assert _next(post, GRID, {"row": 2, "col": 0, "sub": 0}, "End") == {
        "row": 2,
        "col": 2,
        "sub": 0,
    }
    # F22: End lands on the row's last button, the final column's last sub-block (UI-SPEC:257).
    assert _next(
        post, [[["season-2018"], ["AL", "NL"]]], {"row": 0, "col": 0, "sub": 0}, "End"
    ) == {
        "row": 0,
        "col": 1,
        "sub": 1,
    }


def test_next_grid_target_down_and_up(post: Page) -> None:
    # Down walks the sub-blocks of a cell first, then drops to the next row.
    assert _next(post, GRID, {"row": 0, "col": 2, "sub": 0}, "ArrowDown") == {
        "row": 0,
        "col": 2,
        "sub": 1,
    }
    # Row 1 has no Division cell: the nearest non-empty column wins.
    nearest = _next(post, GRID, {"row": 0, "col": 2, "sub": 1}, "ArrowDown")
    assert nearest["row"] == 1 and nearest["col"] in (1, 3)
    assert _next(post, GRID, {"row": 1, "col": 0, "sub": 0}, "ArrowDown") == {
        "row": 2,
        "col": 0,
        "sub": 0,
    }
    # Up from the first sub-block lands on the last sub-block of the cell above.
    assert _next(post, GRID, {"row": 1, "col": 2, "sub": 0}, "ArrowUp")["row"] == 0
    assert _next(post, GRID, {"row": 0, "col": 2, "sub": 1}, "ArrowUp") == {
        "row": 0,
        "col": 2,
        "sub": 0,
    }
    # Out of range stays put.
    assert _next(post, GRID, {"row": 0, "col": 0, "sub": 0}, "ArrowUp") == {
        "row": 0,
        "col": 0,
        "sub": 0,
    }
    assert _next(post, GRID, {"row": 3, "col": 3, "sub": 0}, "ArrowDown") == {
        "row": 3,
        "col": 3,
        "sub": 0,
    }


def test_next_grid_target_pages_clamp_at_five_rows(post: Page) -> None:
    tall = [[["s"], ["x"]] for _ in range(8)]
    assert _next(post, tall, {"row": 0, "col": 1, "sub": 0}, "PageDown") == {
        "row": 5,
        "col": 1,
        "sub": 0,
    }
    assert _next(post, tall, {"row": 5, "col": 1, "sub": 0}, "PageDown") == {
        "row": 7,
        "col": 1,
        "sub": 0,
    }
    assert _next(post, tall, {"row": 7, "col": 1, "sub": 0}, "PageDown") == {
        "row": 7,
        "col": 1,
        "sub": 0,
    }
    assert _next(post, tall, {"row": 3, "col": 1, "sub": 0}, "PageUp") == {
        "row": 0,
        "col": 1,
        "sub": 0,
    }
    assert _next(post, tall, {"row": 0, "col": 1, "sub": 0}, "PageUp") == {
        "row": 0,
        "col": 1,
        "sub": 0,
    }
    assert _next(post, tall, {"row": 2, "col": 1, "sub": 0}, "q") == {
        "row": 2,
        "col": 1,
        "sub": 0,
    }


def _active(page: Page) -> str | None:
    return page.evaluate(  # type: ignore[no-any-return]
        "() => { const a = document.activeElement;"
        " return a.dataset.seasonCell ?? a.dataset.cell ?? null; }"
    )


def test_the_grid_is_one_tab_stop(post: Page) -> None:
    assert post.get_attribute(f"{VIEW} table.mlb-grid", "role") == "grid"
    stops = post.eval_on_selector_all(
        f"{VIEW} .mlb-grid button",
        "els => els.filter(e => e.tabIndex === 0).map(e => e.dataset.seasonCell ?? e.dataset.cell)",
    )
    assert stops == ["season-2026"]
    post.focus(f"{VIEW} .mlb-grid button[data-season-cell='season-2026']")
    post.keyboard.press("Tab")
    # Tab leaves the grid buttons: the next stop is a season's Wikipedia credit link.
    assert post.evaluate("() => document.activeElement.matches('a.mlb-season-credit')")


def test_arrow_keys_move_focus_and_the_tab_stop(post: Page) -> None:
    post.focus(f"{VIEW} .mlb-grid button[data-season-cell='season-2026']")
    post.keyboard.press("ArrowRight")
    assert _active(post) == "2026-division-NL"
    post.keyboard.press("ArrowRight")
    assert _active(post) == "2026-lcs-AL"
    post.keyboard.press("ArrowDown")
    assert _active(post) in ("2025-wild_card-NL", "2025-world_series-all")
    post.keyboard.press("Home")
    assert _active(post) == "season-2025"
    post.keyboard.press("End")
    assert _active(post) == "2025-world_series-all"
    post.keyboard.press("PageDown")
    assert _active(post) == "2014-world_series-all"
    post.keyboard.press("PageUp")
    assert _active(post) == "2026-lcs-AL" or _active(post) == "2026-division-NL"
    stops = post.eval_on_selector_all(
        f"{VIEW} .mlb-grid button", "els => els.filter(e => e.tabIndex === 0).length"
    )
    assert stops == 1


def test_enter_and_space_toggle_and_escape_clears(post: Page) -> None:
    btn = f"{VIEW} .mlb-grid button[data-cell='2019-division-AL']"
    post.focus(btn)
    post.keyboard.press("Enter")
    assert post.evaluate(f"{HOOKS}.getState().cell") == "2019-division-AL"
    # Focus returns to the same logical button after the grid re-renders.
    assert _active(post) == "2019-division-AL"
    post.keyboard.press("Enter")
    assert post.evaluate(f"{HOOKS}.getState().cell") is None
    post.keyboard.press("Space")
    assert post.evaluate(f"{HOOKS}.getState().cell") == "2019-division-AL"
    post.keyboard.press("Escape")
    assert post.evaluate(f"{HOOKS}.getState().cell") is None
    assert _active(post) == "2019-division-AL"
    post.keyboard.press("Space")
    assert post.evaluate(f"{HOOKS}.getState().cell") == "2019-division-AL"
    assert (
        post.get_attribute(f"{VIEW} .mlb-grid button[data-cell='2019-division-AL']", "tabindex")
        == "0"
    )


def test_live_region_announces_picks(post: Page) -> None:
    status = post.locator(f"{VIEW} .mlb-grid-status")
    assert status.get_attribute("role") == "status"
    post.focus(f"{VIEW} .mlb-grid button[data-season-cell='season-2014']")
    post.keyboard.press("Enter")
    assert status.text_content() == "Selected 2014 postseason, 2 games."
    post.keyboard.press("Enter")
    assert status.text_content() == "Selection cleared."
    post.click(f"{VIEW} button[data-cell='2019-division-AL']")
    assert status.text_content() == "Selected 2019 Division Series, AL, 2 games."
