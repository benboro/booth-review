"""In-page parity of the client crew grouping (route two) with `assign_cfb_booths` (plan 14-02).

`site/modules/crew-groups.js` must give the same pbp, regular analyst, fill-in flag, rank and
tier per telecast as `src/booth_review/build/booths.py`, on the inputs of
tests/test_cfb_booths.py plus four added scenarios. Synthetic ids only.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest
from cfb_booth_support import NETWORKS, RANKS, crew, run, tel
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
Item = tuple[dict[str, object], list[dict[str, object]]]


def _seat(tid: str, person: str, pos: int, role: str = "analyst") -> dict[str, object]:
    return {
        "telecast_id": tid,
        "person_id": person,
        "role": role,
        "feed_type": "main",
        "crew_position": pos,
    }


def _scenarios() -> dict[str, tuple[list[Item], Any]]:
    cited_not_modal = [
        (tel("g1"), crew("g1", "p1", "a1")),
        (tel("g2"), crew("g2", "p1", "x")),
        (tel("g3"), crew("g3", "p1", "x")),
    ]
    return {
        "tiers_by_rank_and_scope": (
            [
                (tel("t1"), crew("t1", "p1", "a1")),
                (tel("t2", "d-two"), crew("t2", "p2", "a2")),
                (tel("t3"), crew("t3", "p3", "a3")),
                (tel("t4", "d-one"), crew("t4", "p4", "a4")),
                (tel("t5"), crew("t5", "p5", "a5")),
            ],
            RANKS,
        ),
        "fill_in_keeps_tier": ([(tel("t1"), crew("t1", "p1", "x"))], RANKS),
        "regular_analyst_not_fill_in": ([(tel("t1"), crew("t1", "p1", "a1"))], RANKS),
        "regular_analyst_other_pbp": ([(tel("t1"), crew("t1", "z", "a1"))], RANKS),
        "uncited_family_season": ([(tel("t1", "f-one"), crew("t1", "p1", "a1"))], RANKS),
        "other_family": ([(tel("t1", "c-one"), crew("t1", "p1", "a1"))], RANKS),
        "unmapped_network": ([(tel("t1", "nope"), crew("t1", "p1", "a1"))], RANKS),
        "no_pbp_role": ([(tel("t1"), crew("t1", "p1", None, role="sideline"))], RANKS),
        "multi_pbp_lowest_position": (
            [(tel("t1"), crew("t1", "p2", None, pos=2) + crew("t1", "p1", None, pos=1))],
            RANKS,
        ),
        "alt_feed_crew_never_chooses": (
            [(tel("t1"), crew("t1", "p1", None, feed="alt") + crew("t1", "p2", None))],
            RANKS,
        ),
        "alt_feed_telecast": (
            [(tel("t1", feed="alt"), crew("t1", "p1", "a1", feed="alt"))],
            RANKS,
        ),
        "january_bowl_season": ([(tel("t1", season=2024), crew("t1", "p1", "a1"))], RANKS),
        "three_person_with_regular": (
            [(tel("t1"), [*crew("t1", "p1", "x"), _seat("t1", "a1", 3)])],
            RANKS,
        ),
        "three_person_without_regular": (
            [(tel("t1"), [*crew("t1", "p1", "x"), _seat("t1", "y", 3)])],
            RANKS,
        ),
        "CITED_NOT_MODAL": (cited_not_modal, RANKS),
        "MODAL_TIE": (
            [
                (tel("m1", "f-one"), crew("m1", "z", "m")),
                (tel("m2", "f-one"), crew("m2", "z", "k")),
            ],
            RANKS,
        ),
        "TWO_FAMILIES": (
            [
                (tel("d-one-g"), crew("d-one-g", "p9", "a9")),
                (tel("f-one-g", "f-one"), crew("f-one-g", "p9", "a9")),
            ],
            RANKS,
        ),
        "NON_BIG_FOUR": (
            [
                (tel("c1", "c-one"), crew("c1", "p9", "a9")),
                (tel("c2", "c-two"), crew("c2", "p9", "a9")),
            ],
            RANKS,
        ),
        "two_seasons_and_no_analyst": (
            [
                (tel("t1"), crew("t1", "p1", "a1")),
                (tel("t2", season=2023), crew("t2", "p1", "a1")),
                (tel("t3"), crew("t3", "p2", None)),
            ],
            RANKS,
        ),
    }


def _site_input(
    items: list[Item], ranks: Any
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """(js_input, expected per game, telecast rows) as site_data.py would ship them."""
    result = run(items, ranks)
    net_info = NETWORKS.networks()
    families = {nid: info[_NET_ROW] for nid, info in net_info.items()}
    families.update(_EXTRA_NETWORKS)
    net_ids = sorted(families)
    slugs = {str(r["person_id"]) for _, rows in items for r in rows}
    slugs |= {c.analyst_person_id for cited in ranks.values() for c in cited}
    slugs = sorted(slugs)
    pidx = {s: i for i, s in enumerate(slugs)}

    tiers = {r["telecast_id"]: r for r in result.booth_tiers.iter_rows(named=True)}
    untiered = {
        (r["family"], r["season"], r["pbp_person_id"]): r["analyst_person_id"]
        for r in result.untiered_rows
    }
    booths: list[dict[str, Any]] = []
    booth_index: dict[tuple[Any, ...], int] = {}
    games: list[dict[str, Any]] = []
    expected: list[dict[str, Any]] = []
    for trow, rows in items:
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
                regular=t["analyst_person_id"],
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


@pytest.mark.parametrize("name", list(_scenarios()))
def test_parity_with_assign_cfb_booths(
    name: str, guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    items, ranks = _scenarios()[name]
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
    items, ranks = _scenarios()[name]
    js_input, _, _ = _site_input(items, ranks)
    open_app(page, "")
    return page.evaluate(_GROUP_JS, js_input)  # type: ignore[no-any-return]


def test_cited_not_modal_keeps_cited_regular(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    got = _grouped("CITED_NOT_MODAL", guarded_page, open_app)
    assert [g["regular"] for g in got] == ["a1"] * 3
    assert [g["fillIn"] for g in got] == [False, True, True]


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
        (tel(f"t{i}"), [*crew(f"t{i}", "p1", "a1"), _seat(f"t{i}", "a2", 3)]) for i in range(3)
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
