"""16-03: the MLB Apple crews row model (site/sports/mlb/apple-rows.js).

In-page tests of the DOM-free module on the synthetic MLB fixture, densified through a
route handler. Densified booths: 0 works games 0-8 (analysts Ben x3, Dee x2, Cy x2, Ada x1
and one game with an empty crew), 1 works games 0-2 and 9-14, 2 stays pending.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, Route

pytestmark = pytest.mark.e2e

PRELUDE = """
const D = await import('./sports/mlb/data.js');
const R = await import('./sports/mlb/apple-rows.js');
const raw = await (await fetch('mlb-data.json')).json();
const model = D.prepareMlb(raw);
"""


def _densify(route: Route) -> None:
    resp = route.fetch()
    data = json.loads(resp.text())
    g = data["games"]
    n = len(g["date"])
    g["wp_excitement"] = [1.0 if i in (0, 1, 2, 9, 10, 11, 12, 13, 14) else None for i in range(n)]
    g["stakes"] = [0.5 if i in (0, 1, 2, 9, 10, 11, 12, 13) else None for i in range(n)]
    # Booth 0 analysts: Ben (1) x3, Dee (3) x2, Cy (2) x2, Ada (0) x1; game 8 has no crew.
    analyst_by_game = {0: 1, 1: 1, 2: 1, 3: 3, 4: 3, 5: 2, 6: 2, 7: 0}
    for i, a in analyst_by_game.items():
        g["crew"][i] = [{"person": 4, "role": "pbp"}, {"person": a, "role": "analyst"}]
    g["crew"][8] = []
    b = data["apple_booths"]
    b["quality_status"] = ["ready", "ready", "pending"]
    b["game_list"] = [list(range(9)), [0, 1, 2, 9, 10, 11, 12, 13, 14], [4]]
    b["raw_stakes"] = [1.1, 0.9, None]
    b["raw_stakes_n"] = [3, 8, 0]
    b["adj_stakes"] = [0.2, -0.1, None]
    b["raw_excitement"] = [1.5, 1.2, None]
    b["adj_excitement"] = [0.3, -0.2, None]
    b["strength_prior"] = [0.55, 0.5, None]
    data["freshness"]["quality_pending"] = True
    route.fulfill(response=resp, body=json.dumps(data))


@pytest.fixture
def run(mlb_guarded_page: Page, open_mlb_app: Callable[..., None]) -> Callable[[str], Any]:
    mlb_guarded_page.route("**/mlb-data.json", _densify)
    open_mlb_app(mlb_guarded_page)

    def _run(body: str) -> Any:
        return mlb_guarded_page.evaluate("async () => {" + PRELUDE + body + "}")

    return _run


def test_analyst_tally_orders_by_count_then_name(run: Callable[[str], Any]) -> None:
    out = run("return R.analystTally(model, [0,1,2,3,4,5,6,7,8]);")
    assert [(a["name"], a["n"]) for a in out] == [
        ("Ben Marlow", 3),
        ("Cy Fable", 2),
        ("Dee Hart", 2),
        ("Ada Quill", 1),
    ]


def test_tally_ignores_pbp_and_missing_crew(run: Callable[[str], Any]) -> None:
    out = run(
        "model.cols.crew[8] = undefined;"
        "model.cols.crew[7] = [{person: 0, role: 'pbp'}, {person: 5, role: 'odd'}];"
        "return R.analystTally(model, [7, 8]);"
    )
    assert out == []


def test_rows_shape_and_order_fields(run: Callable[[str], Any]) -> None:
    rows = run(
        "return R.buildAppleRows(model, {adjusted: false}).map((r) => ({"
        " rowKey: r.rowKey, rank: r.rank, rankOrder: r.rankOrder, pbpName: r.pbpName,"
        " names: r.names, games: r.games, network: r.network, gamesCount: r.gamesCount,"
        " listed: r.listed, relay: r.relay, prior: r.prior }));"
    )
    assert [r["rowKey"] for r in rows] == ["0", "1", "2"]
    assert [r["rank"] for r in rows] == ["Lead", "#2", "#3"]
    assert [r["rankOrder"] for r in rows] == [0, 1, 2]
    assert rows[0]["pbpName"]
    assert rows[0]["names"][0] == rows[0]["pbpName"]
    assert len(rows[0]["names"]) == 5
    assert rows[0]["gamesCount"] == 9
    assert rows[0]["network"]["name"]
    assert rows[0]["prior"] == 0.55
    # newest first: date descending, ties by index descending
    dates = run("return model.cols.date;")
    ordered = [dates[g] for g in rows[0]["games"]]
    assert ordered == sorted(ordered, reverse=True)


def test_cell_n_and_values_by_mode(run: Callable[[str], Any]) -> None:
    raw = run(
        "const r = R.buildAppleRows(model, {adjusted: false});"
        "return r.map((x) => [x.stakes, x.excitement]);"
    )
    assert raw[0][0] == {"value": 1.1, "n": 3, "flagged": True, "pending": False}
    assert raw[0][1]["n"] == 3  # wp_excitement non-null on games 0-2 only
    assert raw[0][1]["value"] == 1.5
    assert raw[1][1]["n"] == 9
    adj = run(
        "const r = R.buildAppleRows(model, {adjusted: true});"
        "return r.map((x) => [x.stakes, x.excitement]);"
    )
    assert adj[0][0]["value"] == 0.2
    assert adj[0][1]["value"] == 0.3
    # adjusted excitement n needs both wp_excitement and stakes: booth 0 has games 0-2
    assert adj[0][1]["n"] == 3
    # booth 1: wp_excitement on 0,1,2,9-14; stakes missing on 14 -> 8
    assert adj[1][1]["n"] == 8


def test_flags_are_per_cell_and_pending_never_flagged(run: Callable[[str], Any]) -> None:
    rows = run(
        "return R.buildAppleRows(model, {adjusted: false})"
        ".map((x) => ({ s: x.stakes, e: x.excitement, ok: x.gamesCount }));"
    )
    assert rows[0]["s"]["flagged"] is True
    assert rows[0]["e"]["flagged"] is True
    # n equals the threshold (8): not flagged
    assert rows[1]["s"]["flagged"] is False
    assert rows[1]["e"]["flagged"] is False
    assert rows[2]["s"]["pending"] is True
    assert rows[2]["s"]["flagged"] is False
    assert rows[2]["e"]["pending"] is True
    assert rows[2]["e"]["flagged"] is False


def test_low_n_booth_with_full_cell_is_not_flagged(run: Callable[[str], Any]) -> None:
    out = run(
        "const b = model.appleBooths[1]; b.low_n = true;"
        "const r = R.buildAppleRows(model, {adjusted: false});"
        "return [r[1].stakes.flagged, r[1].excitement.flagged];"
    )
    assert out == [False, False]


def test_sort_spec_defaults(run: Callable[[str], Any]) -> None:
    out = run(
        "return { dir: R.APPLE_SORT_SPEC.naturalDir,"
        " d1: R.APPLE_SORT_SPEC.defaultSort(true), d2: R.APPLE_SORT_SPEC.defaultSort(false) };"
    )
    assert out["dir"] == {
        "position": "asc",
        "booth": "asc",
        "network": "asc",
        "games": "desc",
        "listed": "desc",
        "stakes": "desc",
        "excitement": "desc",
        "prior": "desc",
    }
    assert out["d1"] == {"key": "position", "dir": "asc"}
    assert out["d2"] == {"key": "position", "dir": "asc"}


SORT_ROWS = """
const mk = (k, rankOrder, gamesCount, stakes, extra = {}) => ({
  rowKey: k, rankOrder, gamesCount, names: [k], network: { name: 'N' + k },
  listed: gamesCount, prior: null,
  stakes, excitement: { value: null, n: 0, flagged: false, pending: true }, ...extra });
const cell = (v, n, flagged, pending) => ({ value: v, n, flagged: !!flagged, pending: !!pending });
const rows = [
  mk('a', 3, 2, cell(5, 9)),
  mk('b', 0, 4, cell(3, 2, true)),
  mk('c', 1, 4, cell(null, 0, false, true)),
  mk('d', 2, 1, cell(9, 20)),
  mk('e', 1, 4, cell(4, 9)),
];
"""


def test_default_sort_is_position_then_games(run: Callable[[str], Any]) -> None:
    out = run(SORT_ROWS + "return R.sortAppleRows(rows, null).map((r) => r.rowKey);")
    assert out == ["b", "c", "e", "d", "a"] or out == ["b", "e", "c", "d", "a"]
    # ties on rank 1 (c, e) both have 4 games; rankOrder ties then keep a stable order
    assert out[0] == "b"
    assert out[-1] == "a"


@pytest.mark.parametrize("dir_", ["asc", "desc"])
def test_numeric_sort_keeps_flagged_then_pending_last(run: Callable[[str], Any], dir_: str) -> None:
    out = run(
        SORT_ROWS + f"return R.sortAppleRows(rows, {{ key: 'stakes', dir: '{dir_}' }})"
        ".map((r) => r.rowKey);"
    )
    full = out[:3]
    assert set(full) == {"a", "d", "e"}
    assert out[3] == "b"  # flagged after full-n
    assert out[4] == "c"  # pending last
    assert full == (["d", "a", "e"] if dir_ == "desc" else ["e", "a", "d"])


def test_booth_and_network_sorts_use_locale_compare(run: Callable[[str], Any]) -> None:
    out = run(
        SORT_ROWS + "return {"
        " booth: R.sortAppleRows(rows, { key: 'booth', dir: 'desc' }).map((r) => r.rowKey),"
        " net: R.sortAppleRows(rows, { key: 'network', dir: 'asc' }).map((r) => r.rowKey),"
        " pos: R.sortAppleRows(rows, { key: 'position', dir: 'desc' }).map((r) => r.rowKey) };"
    )
    assert out["booth"] == ["e", "d", "c", "b", "a"]
    assert out["net"] == ["a", "b", "c", "d", "e"]
    assert out["pos"][0] == "a"
