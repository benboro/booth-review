"""U7: one network precedence orders every group of networks shown together.

The user's orderings: FOX before FS1; ABC before ESPN before ESPN2 / ESPNEWS / ESPNU; NBC
before Peacock. In-page tests of site/modules/network.js plus the MLB Postseason cell heads, on
synthetic data only.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, Route

pytestmark = pytest.mark.e2e

_SORT_JS = """
async (ids) => {
  const N = await import('./modules/network.js');
  return N.sortNetworks(ids.map((id) => ({ id }))).map((n) => n.id);
}
"""


def _sorted(page: Page, ids: list[str]) -> list[str]:
    return page.evaluate(_SORT_JS, ids)  # type: ignore[no-any-return]


def test_user_orderings_are_pinned(guarded_page: Page, open_app: Callable[..., None]) -> None:
    open_app(guarded_page, "")
    assert _sorted(guarded_page, ["fs1", "fox"]) == ["fox", "fs1"]
    assert _sorted(guarded_page, ["espnu", "espnews", "espn2", "espn", "abc"]) == [
        "abc",
        "espn",
        "espn2",
        "espnews",
        "espnu",
    ]
    assert _sorted(guarded_page, ["peacock", "nbc"]) == ["nbc", "peacock"]
    # Broadcast before cable before streaming in the other families too.
    assert _sorted(guarded_page, ["paramount-plus", "cbs-sports-network", "cbs"]) == [
        "cbs",
        "cbs-sports-network",
        "paramount-plus",
    ]
    assert _sorted(guarded_page, ["trutv", "tnt", "tbs"]) == ["tbs", "tnt", "trutv"]
    # An unlisted network keeps its place after the listed ones; the sort is stable.
    assert _sorted(guarded_page, ["zz-local", "fs1", "aa-local", "fox"]) == [
        "fox",
        "fs1",
        "zz-local",
        "aa-local",
    ]


def _reorder(route: Route) -> None:
    resp = route.fetch()
    data: dict[str, Any] = json.loads(resp.text())
    nets = data["lookups"]["networks"]
    nets.append({"family": "fox", "id": "fs1", "name": "FS1"})
    nets.append({"family": "disney", "id": "abc", "name": "ABC"})
    fs1, abc = len(nets) - 2, len(nets) - 1
    fox = next(k for k, n in enumerate(nets) if n["id"] == "fox")
    espn = next(k for k, n in enumerate(nets) if n["id"] == "espn")
    p = data["postseason"]
    for k, (season, rnd) in enumerate(zip(p["season"], p["round"], strict=True)):
        if season == 2025 and rnd == "world_series":
            p["networks"][k] = [fs1, fox]  # listed FS1 first in the data
        if season == 2025 and rnd == "wild_card":
            p["networks"][k] = [espn, abc]  # listed ESPN first in the data
    route.fulfill(response=resp, body=json.dumps(data))


def test_mlb_postseason_cell_outlets_follow_precedence(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    page.route("**/mlb-data.json", _reorder)
    open_mlb_app(page, "?sport=mlb&view=postseason")

    def alts(cell: str) -> list[str]:
        return page.eval_on_selector_all(  # type: ignore[no-any-return]
            f"#mlb-view-postseason .mlb-grid button[data-cell='{cell}'] .mlb-cell-head img",
            "els => els.map((e) => e.alt)",
        )

    assert alts("2025-world_series-all") == ["Fox", "FS1"]
    assert alts("2025-wild_card-NL") == ["ABC", "ESPN"]
