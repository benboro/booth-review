# ruff: noqa: E501
"""16-01: MLB round labels, season cells, Scatter control codec, tab carry rule.

In-page tests on the synthetic MLB fixture (no vault rows).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

PRELUDE = """
const D = await import('./sports/mlb/data.js');
const S = await import('./sports/mlb/state.js');
const U = await import('./sports/mlb/url-state.js');
const raw = await (await fetch('mlb-data.json')).json();
const m = D.prepareMlb(raw);
"""

LONG = {
    "regular": "Reg. Season",
    "wild_card": "Wild Card",
    "division": "Division Series",
    "lcs": "League Championship Series",
    "world_series": "World Series",
    "tiebreak": "Tiebreaker",
}


@pytest.fixture
def run(mlb_guarded_page: Page, open_mlb_app: Callable[..., None]) -> Callable[[str], Any]:
    open_mlb_app(mlb_guarded_page)

    def _run(body: str) -> Any:
        return mlb_guarded_page.evaluate("async () => {" + PRELUDE + body + "}")

    return _run


def test_round_maps(run: Callable[[str], Any]) -> None:
    got = run("return { long: D.ROUND_LABELS, short: D.ROUND_SHORT };")
    assert got["long"] == LONG
    assert got["short"] == {**LONG, "lcs": "LCS"}


def test_cell_labels(run: Callable[[str], Any]) -> None:
    got = run(
        """
        return {
          lcs: D.cellLabel({ season: 2019, round: 'lcs', league: 'NL', kind: 'round' }),
          reg: D.cellLabel({ season: 2019, round: 'regular', league: null, kind: 'round' }),
          season: D.cellLabel({ season: 2014, round: null, league: null, kind: 'season' }),
        };
        """
    )
    assert got == {
        "lcs": "2019 League Championship Series, NL",
        "reg": "2019 Reg. Season",
        "season": "2014 postseason",
    }


def test_season_cells_union_their_round_cells(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const out = [];
        for (const c of m.cells.values()) {
          if (c.kind !== 'season') continue;
          const rounds = [...m.cells.values()].filter((r) => r.kind === 'round' && r.season === c.season);
          const union = new Set(rounds.flatMap((r) => r.games));
          out.push({ key: c.key, round: c.round, league: c.league,
            same: c.games.length === union.size && c.games.every((g) => union.has(g)) });
        }
        const kinds = [...m.cells.values()].filter((c) => c.kind === 'round').length;
        return { out, kinds, seasons: m.postseasonSeasons.length };
        """
    )
    assert got["out"]
    assert all(c["same"] and c["round"] is None and c["league"] is None for c in got["out"])
    assert all(c["key"].startswith("season-") for c in got["out"])
    assert got["kinds"] > 0


def test_game_row_labels(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const seen = {};
        for (let i = 0; i < m.n; i += 1) {
          const r = D.gameRow(m, i);
          seen[r.round] = [r.roundLabel, r.roundShort];
        }
        return seen;
        """
    )
    assert got["regular"] == ["Reg. Season", "Reg. Season"]
    for rnd, (long, short) in got.items():
        assert long == LONG[rnd]
        assert short == ("LCS" if rnd == "lcs" else LONG[rnd])


def test_season_cell_round_trips(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const key = [...m.cells.keys()].find((k) => k.startsWith('season-'));
        const s = U.decodeMlbState('?sport=mlb&cell=' + key, m);
        return { key, cell: s.cell, enc: U.encodeMlbState(s, m),
                 bad: U.decodeMlbState('?sport=mlb&cell=season-1900', m).cell };
        """
    )
    assert got["cell"] == got["key"]
    assert f"cell={got['key']}" in got["enc"]
    assert got["bad"] is None


def test_scatter_codec(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const d = (q) => U.decodeMlbState(q, m);
        const a = d('?sport=mlb&stype=post&sround=lcs');
        const b = d('?sport=mlb&stype=reg&sround=lcs');
        return {
          a: [a.stype, a.sround], enc: U.encodeMlbState(a, m),
          b: [b.stype, b.sround],
          junk1: d('?sport=mlb&stype=junk').stype,
          junk2: d('?sport=mlb&stype=post&sround=junk').sround,
          def: U.encodeMlbState(S.defaultMlbState(), m),
        };
        """
    )
    assert got["a"] == ["post", "lcs"]
    assert "stype=post" in got["enc"]
    assert "sround=lcs" in got["enc"]
    assert got["b"] == ["reg", None]
    assert got["junk1"] is None
    assert got["junk2"] is None
    assert got["def"] == "?sport=mlb"
