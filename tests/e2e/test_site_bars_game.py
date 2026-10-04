"""A Game pick alone is a Bars subject (04.9 D-18; orchestrator fix after Plan 07).

Hand-worked against the synthetic fixture: Harbor Bowl is one rated telecast (game 7),
the CFP Semifinal one (game 5), so the Bars count only that game's crew. Head-to-head
(04.7 D-15) and the Butterfly triggers are unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_MODEL_JS = """
async (partial) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const B = await import('./modules/bars.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const state = Object.assign(S.defaultState(data), partial);
  const view = S.computeView(data, state);
  const model = B.barsModel(data, view, state);
  return {
    games: B.gamesForBars(view),
    ctx: B.chartContext(data, state),
    rows: model.rows.map((r) => [r.label ?? r.key, r.total]),
  };
}
"""


def _title(page: Page) -> str:
    page.wait_for_function("() => document.getElementById('bars-title').textContent !== ''")
    return page.inner_text("#bars-title")


def _model(page: Page, partial: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = page.evaluate(_MODEL_JS, partial)
    return result


def test_game_alone_enables_bars_and_counts_only_that_game(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?game=harbor-bowl&view=bars")
    assert guarded_page.get_attribute("#tab-bars", "aria-disabled") is None
    assert guarded_page.get_attribute("#tab-butterfly", "aria-disabled") == "true"
    assert guarded_page.locator("#bars-note").is_hidden()
    assert _title(guarded_page) == "Announcers by rated telecasts of the Harbor Bowl"
    model = _model(guarded_page, {"game": "harbor-bowl"})
    assert model["games"] == [7]
    assert model["ctx"]["group"] == "announcers"
    assert model["ctx"]["groupChoice"] is False
    assert model["ctx"]["byOptions"] == ["announcer", "network"]
    assert model["rows"]
    assert all(total == 1 for _, total in model["rows"])
    guarded_page.wait_for_function(
        "n => document.querySelectorAll('#bars-chart .trace.bars .point path').length >= n",
        arg=len(model["rows"]),
    )


def test_switching_to_network_grouping_titles_networks(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?game=harbor-bowl&view=bars")
    guarded_page.locator('#group-by-toggle button[data-by="network"]').click()
    guarded_page.wait_for_function("() => location.search.includes('by=network')")
    assert _title(guarded_page).startswith("Network")
    assert _title(guarded_page).endswith("the Harbor Bowl")


def test_cfp_round_pick_uses_the_plural_form(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?game=cfp-semifinal&view=bars")
    assert _title(guarded_page) == "Announcers by rated telecasts of CFP semifinals"
    assert _model(guarded_page, {"game": "cfp-semifinal"})["games"] == [5]


def test_game_with_networks_keeps_the_group_choice(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    ctx = _model(guarded_page, {"game": "harbor-bowl", "networks": ["net-a"]})["ctx"]
    assert ctx["groupChoice"] is True
    assert ctx["byOptions"] == ["announcer", "network", "team", "conference"]


def test_game_adds_no_butterfly_trigger_and_h2h_is_unchanged(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    ctx = _model(guarded_page, {"game": "lakeshore"})["ctx"]
    assert ctx["barsEnabled"] is True
    assert ctx["butterflyEnabled"] is False
    h2h = _model(
        guarded_page,
        {"game": "lakeshore", "school": ["northfield", "lakeview"], "h2h": True},
    )["ctx"]
    assert h2h["groupChoice"] is False
    assert h2h["group"] == "announcers"
    assert h2h["butterflyEnabled"] is False
