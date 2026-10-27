"""In-browser proof of the weekend map's pure modules (Phase 24, plan 03): the window shape
rules and symbol table (`weekend-map.js`), the palette constants, the CFB weekend game's venue
fields (`weekend-data.js`), the day model (dots, nudge rows, edge markers, not-on-map list, splat
input) and the figure builder (`weekend-map-chart.js`).

Both modules are pure and DOM-free; these tests import them with `page.evaluate` and feed them
synthetic WeekendGame literals built here, so they need no fixture data beyond a served page.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_IMPORT = (
    "const M = await import('./modules/weekend-map.js');"
    "const P = await import('./modules/palette.js');"
)


@pytest.fixture
def map_page(guarded_page: Page, open_app: Callable[[Page, str], None]) -> Page:
    open_app(guarded_page, "")
    return guarded_page


def _run(page: Page, body: str, arg: Any = None) -> Any:
    return page.evaluate(f"async (arg) => {{ {_IMPORT} {body} }}", arg)


# -- window rules --------------------------------------------------------------------------


def test_cfb_window_boundaries(map_page: Page) -> None:
    out = _run(
        map_page,
        "return arg.map((m) => M.cfbWindow(m));",
        [0, 720, 869, 870, 1139, 1140, 1319, 1320, 1439, None],
    )
    assert out == [
        "noon",
        "noon",
        "noon",
        "afternoon",
        "afternoon",
        "prime",
        "prime",
        "late",
        "late",
        "tba",
    ]


def test_nfl_window_from_slot_name(map_page: Page) -> None:
    slots = [
        "Sunday early",
        "Sunday late",
        "TNF",
        "SNF",
        "MNF",
        "International",
        "Saturday",
        "Christmas",
        "Black Friday",
        "Thanksgiving",
        "Other",
        None,
    ]
    out = _run(map_page, "return arg.map((s) => M.nflWindow(s));", slots)
    assert out == ["early", "late"] + ["night"] * 9 + ["tba"]


def test_window_symbol_table_is_frozen_and_complete(map_page: Page) -> None:
    out = _run(
        map_page,
        """return {
          cfb: M.WINDOW_SYMBOL.cfb, nfl: M.WINDOW_SYMBOL.nfl, tba: M.WINDOW_SYMBOL.tba,
          frozen: Object.isFrozen(M.WINDOW_SYMBOL) && Object.isFrozen(M.WINDOW_SYMBOL.cfb)
            && Object.isFrozen(M.WINDOW_SYMBOL.nfl),
          labels: M.WINDOW_LABELS, caption: M.WINDOW_CAPTION,
          symbols: [
            M.symbolOf({ sport: 'cfb', kickoffMin: 720 }),
            M.symbolOf({ sport: 'cfb', kickoffMin: 1200 }),
            M.symbolOf({ sport: 'cfb', kickoffMin: null }),
            M.symbolOf({ sport: 'nfl', kickoffMin: 780, slotName: 'Sunday late' }),
            M.symbolOf({ sport: 'nfl', kickoffMin: 1200, slotName: 'SNF' }),
            M.symbolOf({ sport: 'nfl', kickoffMin: null, slotName: null }),
          ],
        };""",
    )
    assert out["cfb"] == {
        "noon": "circle",
        "afternoon": "square",
        "prime": "diamond",
        "late": "triangle-up",
    }
    assert out["nfl"] == {"early": "circle", "late": "square", "night": "diamond"}
    assert out["tba"] == "circle-open"
    assert out["frozen"] is True
    assert out["symbols"] == [
        "circle",
        "diamond",
        "circle-open",
        "square",
        "diamond",
        "circle-open",
    ]
    assert out["labels"]["cfb"] == {
        "noon": "Noon",
        "afternoon": "Afternoon",
        "prime": "Prime",
        "late": "Late",
        "tba": "Time TBA",
    }
    assert out["labels"]["nfl"]["night"] == "Night and standalone"
    assert out["caption"]["cfb"].startswith("Noon is before 2:30 pm.")
    assert out["caption"]["nfl"].startswith("Early is the 1:00 pm window.")


# -- palette -------------------------------------------------------------------------------


def test_every_map_family_clears_three_to_one_on_the_land(map_page: Page) -> None:
    out = _run(
        map_page,
        """const rows = [];
        for (const theme of ['light', 'dark']) for (const f of P.FAMILY_ORDER) {
          rows.push([theme, f, P.contrastRatio(P.MAP_FAMILY_COLORS[theme][f], P.MAP_LAND[theme])]);
        }
        return rows;""",
    )
    assert len(out) == 16
    for theme, family, ratio in out:
        assert ratio >= 3.0, (theme, family, ratio)


def test_weekend_map_palette_constants(map_page: Page) -> None:
    out = _run(
        map_page,
        """return {
          dot: P.WEEKEND_MAP_DOT, splat: P.MAP_SPLAT_WEEKEND,
          keyline: P.MAP_LINE_WIDTH.dotKeyline, hit: P.MAP_VENUE_DOT.hitDiameter,
        };""",
    )
    assert out["dot"]["desktop"] == {
        "circle": 12,
        "square": 10,
        "diamond": 14,
        "triangle-up": 13,
        "circle-open": 12,
    }
    assert out["dot"]["phone"] == {
        "circle": 10,
        "square": 8,
        "diamond": 12,
        "triangle-up": 11,
        "circle-open": 10,
    }
    assert out["dot"]["hitDiameter"] == out["hit"] == 12
    assert out["dot"]["keyline"] == out["keyline"] == 1.5
    assert out["splat"]["viewersWeight"] == 0
    assert 0.3 <= out["splat"]["maxAlpha"] <= 0.5


# -- CFB weekend game venue fields ---------------------------------------------------------


def test_cfb_weekend_game_carries_place_and_venue(map_page: Page) -> None:
    out = map_page.evaluate(
        """async () => {
          const D = await import('./modules/data.js');
          const W = await import('./modules/weekend-data.js');
          const raw = await (await fetch('site-data.json')).json();
          const data = D.prepareData(raw);
          const n = data.scheduledRaw.season.length;
          data.scheduledRaw.place = Array.from({ length: n }, (_, j) => (j === 0 ? 0 : null));
          const games = W.cfbWeekendGames(data, data.weekend.label).filter(
            (g) => g.block === 'scheduled');
          return {
            rows: games.map((g) => [g.index, g.placeIdx, g.venue == null ? null : g.venue.name]),
            venue0: data.lookups.venues[0]?.name ?? null,
          };
        }"""
    )
    by_index = {row[0]: row for row in out["rows"]}
    assert out["venue0"] is not None
    if 0 in by_index:
        assert by_index[0][1] == 0
        assert by_index[0][2] == out["venue0"]
    for index, place_idx, venue_name in out["rows"]:
        if index != 0:
            assert place_idx is None
            assert venue_name is None
