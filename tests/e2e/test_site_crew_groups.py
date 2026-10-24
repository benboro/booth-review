"""In-page parity of the client crew grouping (route two) with `assign_cfb_booths` (plan 14-02).

`site/modules/crew-groups.js` must give the same pbp, regular analyst, fill-in flag, rank and
tier per telecast as `src/booth_review/build/booths.py`, on every case of
`cfb_booth_support.scenarios()` (the list tests/test_cfb_booths.py also reads), fed in the
shape site_data.py ships: the people lookup holds only people on a crew row or a booth's
play-by-play, so a cited regular analyst on no crew row ships as a null booth analyst, and the
client then names no regular. Synthetic ids only.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest
from cfb_booth_support import NETWORKS, RANKS, Item, crew, run, scenarios, seat, tel
from crews_fixture import (
    CASE_CITED_NOT_MODAL,
    CASE_FILL_IN,
    CASE_MIXED_UNKNOWN,
    CASE_NO_CREW,
    CASE_NO_PBP,
    CASE_NON_BIG_FOUR,
    CASE_SIDELINE,
    CASE_TRIO,
    CASE_TWO_FAMILIES,
)
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_GROUP_JS = """
async (input) => {
  const G = await import('./modules/crew-groups.js');
  return G.groupTelecasts(input);
}
"""

_INDEX_JS = """
async () => {
  const D = await import('./modules/data.js');
  const G = await import('./modules/crew-groups.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const a = G.crewIndex(data);
  const b = G.crewIndex(data);
  const noCrew = a.perGame.map((g, i) => (g.noCrew ? i : -1)).filter((i) => i >= 0);
  return {
    same: a === b,
    keys: Array.from(a.crews.keys()),
    noCrewKeys: noCrew.map((i) => a.keys[i]),
    parsed: G.parseCrewKey('disney:trio-pbp.trio-a1.trio-a2'),
    bad: ['a b', 'x:', 'DISNEY:x', ''].map((k) => G.parseCrewKey(k)),
  };
}
"""

_NET_ROW = 1  # NetworkRow family index, as read by assign_cfb_booths
_EXTRA_NETWORKS = {"c-two": "conference", "nope": None}


def _site_input(
    items: list[Item], ranks: Any, *, unshipped: frozenset[str] = frozenset()
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """(js_input, expected per shipped game, telecast rows) as site_data.py would ship them.

    `assign_cfb_booths` sees every item; telecasts in `unshipped` are left out of the client
    input, as the one-telecast-per-game selection leaves out a game's other main telecasts.
    """
    result = run(items, ranks)
    net_info = NETWORKS.networks()
    families = {nid: info[_NET_ROW] for nid, info in net_info.items()}
    families.update(_EXTRA_NETWORKS)
    net_ids = sorted(families)
    shipped = [(t, rows) for t, rows in items if str(t["telecast_id"]) not in unshipped]
    tiers = {r["telecast_id"]: r for r in result.booth_tiers.iter_rows(named=True)}
    # site_data.py: people come from shipped crew rows and shipped booths' play-by-play only.
    slugs_set = {str(r["person_id"]) for _, rows in shipped for r in rows}
    slugs_set |= {
        str(tiers[str(t["telecast_id"])]["pbp_person_id"])
        for t, _ in shipped
        if str(t["telecast_id"]) in tiers
    }
    slugs = sorted(slugs_set)
    pidx = {s: i for i, s in enumerate(slugs)}

    untiered = {
        (r["family"], r["season"], r["pbp_person_id"]): r["analyst_person_id"]
        for r in result.untiered_rows
    }
    booths: list[dict[str, Any]] = []
    booth_index: dict[tuple[Any, ...], int] = {}
    games: list[dict[str, Any]] = []
    expected: list[dict[str, Any]] = []
    for trow, rows in shipped:
        tid = str(trow["telecast_id"])
        seats = sorted(rows, key=lambda r: (r["feed_type"] != "main", r["crew_position"] or 0))
        game_booth = None
        exp: dict[str, Any] = {"tiered": tid in tiers}
        if tid in tiers:
            t = tiers[tid]
            key = (t["family"], t["season"], t["pbp_person_id"], t["analyst_person_id"])
            if key not in booth_index:
                booth_index[key] = len(booths)
                booths.append(
                    {
                        "family": t["family"],
                        "season": t["season"],
                        "pbp": pidx[t["pbp_person_id"]],
                        "analyst": pidx.get(t["analyst_person_id"]),
                        "rank": t["rank"],
                        "tier": t["tier"],
                        "lead_network": t["lead_network_id"],
                    }
                )
            game_booth = booth_index[key]
            exp.update(
                pbp=t["pbp_person_id"],
                # A regular on no shipped crew row is unknown to the client.
                regular=t["analyst_person_id"] if t["analyst_person_id"] in pidx else None,
                fill_in=t["is_fill_in"],
                rank=t["rank"],
                tier=t["tier"],
            )
        else:
            fam = families.get(str(trow["network_id"]))
            pbp = next(
                (
                    str(r["person_id"])
                    for r in seats
                    if r["role"] == "pbp" and r["feed_type"] == "main"
                ),
                None,
            )
            if trow["feed_type"] == "main" and fam in ("disney", "fox", "cbs", "nbc") and pbp:
                # An untiered family booth: the review row carries the modal analyst.
                exp["regular"] = untiered[(fam, trow["season"], pbp)]
            exp.update(rank=None, tier=None)
        games.append(
            {
                "season": trow["season"],
                "network": net_ids.index(str(trow["network_id"])),
                "booth": game_booth,
                "crew": [
                    {"person": pidx[str(r["person_id"])], "role": r["role"], "feed": r["feed_type"]}
                    for r in seats
                ],
            }
        )
        expected.append(exp)
    js_input = {
        "people": slugs,
        "networks": [{"id": n, "family": families[n]} for n in net_ids],
        "booths": booths,
        "games": games,
    }
    return js_input, expected, []


@pytest.mark.parametrize("name", list(scenarios()))
def test_parity_with_assign_cfb_booths(
    name: str, guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    items, ranks = scenarios()[name]
    js_input, expected, _ = _site_input(items, ranks)
    open_app(guarded_page, "")
    got = guarded_page.evaluate(_GROUP_JS, js_input)
    assert len(got) == len(expected)
    for g, exp in zip(got, expected, strict=True):
        assert g["rank"] == exp["rank"]
        assert g["tier"] == exp["tier"]
        if exp["tiered"]:
            assert g["pbp"] == exp["pbp"]
            assert g["regular"] == exp["regular"]
            assert g["fillIn"] == exp["fill_in"]
        elif "regular" in exp:
            assert g["regular"] == exp["regular"]
        if g["key"] is not None:
            assert re.fullmatch(r"[a-z0-9-]+:~?[a-z0-9-]+(\.[a-z0-9-]+)*", g["key"])


def _grouped(name: str, page: Page, open_app: Callable[[Page, str], None]) -> list[dict[str, Any]]:
    items, ranks = scenarios()[name]
    js_input, _, _ = _site_input(items, ranks)
    open_app(page, "")
    return page.evaluate(_GROUP_JS, js_input)  # type: ignore[no-any-return]


def test_cited_not_modal_keeps_cited_regular(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    got = _grouped("CITED_NOT_MODAL", guarded_page, open_app)
    assert [g["regular"] for g in got] == ["a1"] * 3
    assert [g["fillIn"] for g in got] == [False, True, True]


def test_cited_regular_on_no_crew_ships_null_and_every_analyst_game_is_a_fill_in(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """F5 (14-11): site_data.py ships a null booth analyst when the cited regular is on no
    crew row; the client then names no regular and marks every game with an analyst a
    fill-in, as booths.py does."""
    items, ranks = scenarios()["CITED_ANALYST_ON_NO_CREW"]
    js_input, _, _ = _site_input(items, ranks)
    assert [b["analyst"] for b in js_input["booths"]] == [None]
    assert "a2" not in js_input["people"]
    open_app(guarded_page, "")
    got = guarded_page.evaluate(_GROUP_JS, js_input)
    assert [g["regular"] for g in got] == [None, None, None]
    assert [g["fillIn"] for g in got] == [True, True, False]
    assert [(g["rank"], g["tier"]) for g in got] == [(2, "b")] * 3


def test_untiered_modal_counts_shipped_telecasts_only(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """F8 (14-11), the documented shipped-modal rule: booths.py takes an untiered group's
    modal analyst over every main-feed telecast, a game's unshipped second telecast
    included; the client sees one shipped telecast per game, so its modal can differ."""
    items: list[Item] = [
        (tel("u1", "f-one"), crew("u1", "z", "k")),
        (tel("u2", "f-one"), crew("u2", "z", "m")),
        (tel("u2-dup", "f-one"), crew("u2-dup", "z", "m")),
    ]
    result = run(items, RANKS)
    assert [r["analyst_person_id"] for r in result.untiered_rows] == ["m"]
    js_input, _, _ = _site_input(items, RANKS, unshipped=frozenset({"u2-dup"}))
    open_app(guarded_page, "")
    got = guarded_page.evaluate(_GROUP_JS, js_input)
    # A one-one tie among the shipped telecasts goes to the lower slug.
    assert [g["regular"] for g in got] == ["k", "k"]


def test_modal_tie_picks_lower_slug(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    got = _grouped("MODAL_TIE", guarded_page, open_app)
    assert [g["regular"] for g in got] == ["k", "k"]
    assert got[0]["lineup"] == ["k"]


def test_two_families_two_keys(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    got = _grouped("TWO_FAMILIES", guarded_page, open_app)
    assert [g["key"] for g in got] == ["disney:p9.a9", "fox:p9.a9"]


def test_non_big_four_keys_by_network_without_rank(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    got = _grouped("NON_BIG_FOUR", guarded_page, open_app)
    assert [g["key"] for g in got] == ["c-one:p9.a9", "c-two:p9.a9"]
    assert [g["rank"] for g in got] == [None, None]


def test_no_pbp_key_has_tilde(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    got = _grouped("no_pbp_role", guarded_page, open_app)
    assert got[0]["noPbp"] is True
    assert ":~" in got[0]["key"]


def test_three_person_usual_lineup_names_all_three(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    items: list[Item] = [
        (tel(f"t{i}"), [*crew(f"t{i}", "p1", "a1"), seat(f"t{i}", "a2", 3)]) for i in range(3)
    ]
    js_input, _, _ = _site_input(items, RANKS)
    open_app(guarded_page, "")
    got = guarded_page.evaluate(_GROUP_JS, js_input)
    assert {g["key"] for g in got} == {"disney:p1.a1.a2"}
    assert all(g["fillIn"] is False for g in got)


def test_crew_index_on_crews_dataset(
    guarded_page: Page,
    serve_crews: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> None:
    serve_crews(guarded_page)
    open_app(guarded_page, "?view=crews")
    out = guarded_page.evaluate(_INDEX_JS)
    keys = set(out["keys"])
    t = CASE_TRIO
    assert f"disney:{t['pbp']}.{'.'.join(t['analysts'])}" in keys
    tf = CASE_TWO_FAMILIES
    assert {f"disney:{tf['pbp']}.{tf['analyst']}", f"fox:{tf['pbp']}.{tf['analyst']}"} <= keys
    nb = CASE_NON_BIG_FOUR
    assert {f"net-f:{nb['pbp']}.{nb['analyst']}", f"net-g:{nb['pbp']}.{nb['analyst']}"} <= keys
    assert f"disney:~{'.'.join(CASE_NO_PBP['people'])}" in keys
    s = CASE_SIDELINE
    assert f"fox:{s['pbp']}.{s['analyst']}" in keys
    assert f"disney:{CASE_FILL_IN['pbp']}.{CASE_FILL_IN['regular_analyst']}" in keys
    c = CASE_CITED_NOT_MODAL
    assert f"disney:{c['pbp']}.{c['cited_analyst']}" in keys
    m = CASE_MIXED_UNKNOWN
    assert f"{m['network']}:~{m['x']}.{m['y']}" in keys
    assert out["noCrewKeys"] == [None] * CASE_NO_CREW["games"]
    assert out["same"] is True
    assert out["parsed"] == {
        "groupId": "disney",
        "noPbp": False,
        "slugs": ["trio-pbp", "trio-a1", "trio-a2"],
    }
    assert out["bad"] == [None, None, None, None]
