"""SEC Network+ marks follow the game's season (user, 2026-11-16): logoFor's eras,
networkMark's season option, and the dark-theme swap keeping the season's mark. SEC Network
keeps one mark for every season."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_LOOKUP_JS = """
async (cases) => {
  const m = await import('./modules/logos.js');
  return cases.map(([id, season]) => {
    const logo = m.logoFor(id, season);
    return logo ? logo.file : null;
  });
}
"""

_MARK_JS = """
async ([id, season]) => {
  const m = await import('./modules/network.js');
  const mark = m.networkMark({ id, name: 'SEC Network+', family: 'espn' }, { season });
  document.body.append(mark);
  const img = mark.querySelector('img');
  return { src: img.getAttribute('src'), season: img.dataset.season ?? null };
}
"""


@pytest.fixture
def app_page(guarded_page: Page, open_app: Callable[[Page, str], None]) -> Page:
    guarded_page.set_viewport_size({"width": 1440, "height": 900})
    open_app(guarded_page, "")
    return guarded_page


def _files(page: Page, cases: list[list[Any]]) -> list[str | None]:
    return page.evaluate(_LOOKUP_JS, cases)  # type: ignore[no-any-return]


def test_sec_network_plus_marks_follow_the_game_season(app_page: Page) -> None:
    got = _files(
        app_page,
        [
            ["sec-network", 2014],
            ["sec-network", 2023],
            ["sec-network", 2024],
            ["sec-network", 2026],
            ["sec-network", None],
            ["sec-network", 2010],
            ["sec-network-plus", 2023],
            ["sec-network-plus", 2024],
            ["sec-network-plus", None],
            ["espn", 2014],
            ["espn", None],
            ["not-a-network", 2024],
        ],
    )
    assert got == [
        "logos/sec-network.svg",
        "logos/sec-network.svg",
        "logos/sec-network.svg",
        "logos/sec-network.svg",
        "logos/sec-network.svg",
        "logos/sec-network.svg",
        "logos/sec-network-plus.svg",
        "logos/sec-network-plus-2024.svg",
        "logos/sec-network-plus-2024.svg",
        "logos/espn.svg",
        "logos/espn.svg",
        None,
    ]


def test_mark_keeps_its_season_across_a_theme_flip(app_page: Page) -> None:
    app_page.evaluate("() => { document.documentElement.dataset.theme = 'light'; }")
    old = app_page.evaluate(_MARK_JS, ["sec-network-plus", 2019])
    new = app_page.evaluate(_MARK_JS, ["sec-network-plus", None])
    assert old == {"src": "logos/sec-network-plus.svg", "season": "2019"}
    assert new == {"src": "logos/sec-network-plus-2024.svg", "season": None}

    app_page.evaluate("() => { document.documentElement.dataset.theme = 'dark'; }")
    srcs = app_page.evaluate(
        "() => [...document.querySelectorAll('body > .net-mark img')]"
        ".map((i) => i.getAttribute('src'))"
    )
    assert srcs == [
        "logos/dark/sec-network-plus.svg",
        "logos/dark/sec-network-plus-2024.svg",
    ]
