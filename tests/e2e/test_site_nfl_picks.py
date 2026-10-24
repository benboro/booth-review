"""Phase 15-02: the DOM-free NFL pick layer (picks.js) and mode resolver (mode.js).

In-page tests on the synthetic NFL Crews overlay (tests/e2e/nfl_crews_fixture.py); expected
game sets are computed in Python from the overlay dict. No vault rows.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from nfl_crews_fixture import (
    CASE_FILL_IN,
    CASE_MIXED_SEAT,
    build_nfl_crews_raw,
)
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

PRELUDE = """
const D = await import('./sports/nfl/data.js');
const S = await import('./sports/nfl/state.js');
const C = await import('./sports/nfl/picks.js');
const M = await import('./sports/nfl/mode.js');
const raw = await (await fetch('nfl-data.json')).json();
const m = D.prepareNfl(raw);
const base = S.defaultNflState(m);
"""


@pytest.fixture
def run(
    nfl_guarded_page: Page,
    open_flagon_cfb: Callable[..., None],
    serve_nfl_crews: Callable[[Page], None],
) -> Callable[[str], Any]:
    serve_nfl_crews(nfl_guarded_page)
    open_flagon_cfb(nfl_guarded_page)

    def _run(body: str) -> Any:
        return nfl_guarded_page.evaluate("async () => {" + PRELUDE + body + "}")

    return _run


@pytest.fixture
def overlay(nfl_fixture_raw: dict[str, Any]) -> dict[str, Any]:
    return build_nfl_crews_raw(nfl_fixture_raw)


def _person_index(raw: dict[str, Any], slug: str) -> int:
    return next(i for i, p in enumerate(raw["lookups"]["people"]) if p["id"] == slug)


def _games_with_person(raw: dict[str, Any], slug: str) -> list[int]:
    p = _person_index(raw, slug)
    return [i for i, crew in enumerate(raw["games"]["crew"]) if any(c["person"] == p for c in crew)]


def _booth_games(raw: dict[str, Any], key: str) -> list[int]:
    group_id, slug = key.split(":")
    groups = raw["lookups"]["network_groups"]
    members = next(g["members"] for g in groups if g["id"] == group_id)
    p = _person_index(raw, slug)
    return [
        i
        for i, crew in enumerate(raw["games"]["crew"])
        if raw["games"]["network"][i] in members
        and any(c["person"] == p and c["role"] == "pbp" for c in crew)
    ]


def test_matched_equals_passes_without_a_pick(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const st = { ...base, seasons: [2025, 2025], teams: [m.franchises[0].id] };
        const r = C.computePicks(m, st);
        const want = [];
        for (let i = 0; i < m.n; i++) want.push(S.gamePasses(m, st, i) ? 1 : 0);
        return { hasPick: r.hasPick, passes: [...r.passes], matched: [...r.matched],
                 want, count: r.matchedCount };
        """
    )
    assert got["hasPick"] is False
    assert got["passes"] == got["want"] == got["matched"]
    assert got["count"] == sum(got["want"])
    assert got["count"] > 0


def test_people_pick_matches_any_seat(run: Callable[[str], Any], overlay: dict[str, Any]) -> None:
    # The analyst on the fill-in game and the mixed-seat person both match in any role.
    for slug in (CASE_FILL_IN["fill_in"], CASE_MIXED_SEAT["person"]):
        got = run(
            f"""
            const r = C.computePicks(m, {{ ...base, people: ['{slug}'] }});
            return {{ hasPick: r.hasPick, hasPeople: r.hasPeople,
                      idx: [...r.matched].flatMap((v, i) => (v ? [i] : [])) }};
            """
        )
        assert got["hasPick"] is True
        assert got["hasPeople"] is True
        assert got["idx"] == _games_with_person(overlay, slug)
        assert got["idx"]


def test_booths_pick_matches_booth_games(
    run: Callable[[str], Any], overlay: dict[str, Any]
) -> None:
    key = "fox:synth-pbp-two"
    got = run(
        f"""
        const r = C.computePicks(m, {{ ...base, booths: ['{key}'] }});
        return {{ hasBooths: r.hasBooths,
                  idx: [...r.matched].flatMap((v, i) => (v ? [i] : [])),
                  want: S.boothGames(m, ['{key}']) }};
        """
    )
    assert got["hasBooths"] is True
    assert got["idx"] == got["want"] == _booth_games(overlay, key)
    assert len(got["idx"]) == 27  # 9 games x 3 booth seasons


def test_people_and_booths_intersect(run: Callable[[str], Any], overlay: dict[str, Any]) -> None:
    key = "fox:synth-pbp-two"
    slug = "synth-an-two-b"  # the 2026 analyst only
    got = run(
        f"""
        const r = C.computePicks(m, {{ ...base, booths: ['{key}'], people: ['{slug}'] }});
        return [...r.matched].flatMap((v, i) => (v ? [i] : []));
        """
    )
    want = sorted(set(_booth_games(overlay, key)) & set(_games_with_person(overlay, slug)))
    assert got == want
    assert 0 < len(got) < len(_booth_games(overlay, key))


def test_classify_pbp_voice_is_rowfilter(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const st = { ...base, people: ['synth-many-pbp-00'] };
        return { pbp: C.classifyAnnouncers(m, st, C.crewsScopeRows(m, st)),
                 none: C.classifyAnnouncers(m, base, C.crewsScopeRows(m, base)),
                 absent: C.classifyAnnouncers(m, { ...base, seasons: [2024, 2024],
                   people: ['synth-many-pbp-00'] }, C.crewsScopeRows(m, { ...base,
                   seasons: [2024, 2024] })) };
        """
    )
    assert got == {"pbp": "rowfilter", "none": "none", "absent": "rowfilter"}


def test_classify_mixed_seat_and_fill_in_are_subset(run: Callable[[str], Any]) -> None:
    got = run(
        f"""
        const cls = (people) => {{
          const st = {{ ...base, people }};
          return C.classifyAnnouncers(m, st, C.crewsScopeRows(m, st));
        }};
        return {{ seat: cls(['{CASE_MIXED_SEAT["person"]}']),
                  fill: cls(['{CASE_FILL_IN["fill_in"]}']),
                  analyst: cls(['{CASE_FILL_IN["analyst"]}']) }};
        """
    )
    assert got == {"seat": "subset", "fill": "subset", "analyst": "subset"}


def test_classify_scope_follows_the_booths_filter(run: Callable[[str], Any]) -> None:
    seat = CASE_MIXED_SEAT["person"]
    got = run(
        f"""
        const cls = (booths) => {{
          const st = {{ ...base, people: ['{seat}'], booths }};
          return C.classifyAnnouncers(m, st, C.crewsScopeRows(m, st));
        }};
        return {{ all: cls([]), pbpBooth: cls(['fox:{seat}']),
                  otherBooth: cls(['cbs:synth-pbp-mixb']) }};
        """
    )
    # Only the picked booth's own rows count: as that row's PBP the person is a row filter;
    # on the other booth's rows the person is its analyst.
    assert got == {"all": "subset", "pbpBooth": "rowfilter", "otherBooth": "subset"}


def test_compute_picks_is_memoized(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const st = { ...base, people: ['synth-an-sub'] };
        const a = C.computePicks(m, st);
        const b = C.computePicks(m, { ...st, people: [...st.people] });
        const c = C.computePicks(m, { ...st, people: ['synth-mix-seat'] });
        return { same: a === b, differs: a !== c, signature: a.signature === b.signature };
        """
    )
    assert got == {"same": True, "differs": True, "signature": True}


def test_crews_mode_reasons(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const adj = { adjusted: true, teams: [], cats: [] };
        const mode = (patch, announcers) => M.crewsMode({ ...adj, ...patch }, { announcers });
        return {
          rawStored: mode({ adjusted: false, teams: ['t'] }, 'subset'),
          team: mode({ teams: ['t'] }),
          cat: mode({ cats: ['agotw'] }),
          subset: mode({}, 'subset'),
          both: mode({ teams: ['t'], cats: ['agotw'] }),
          rowfilter: mode({ seasons: [2025, 2025], booths: ['fox:x'] }, 'rowfilter'),
          none: mode({}, 'none'),
        };
        """
    )
    team = (
        "Showing Raw: a Team pick cuts inside each booth\u2019s season, and adjusted values are "
        "shipped only for whole booth seasons. Clear the Team pick to see Adjusted again."
    )
    subset = (
        "Showing Raw: this filter cuts inside each booth\u2019s season. "
        "Clear it to see Adjusted again."
    )
    assert got["rawStored"] == {
        "stored": "raw",
        "effective": "raw",
        "forced": False,
        "reason": None,
    }
    assert got["team"]["effective"] == "raw" and got["team"]["reason"] == team
    assert got["team"]["stored"] == "adjusted"
    assert got["cat"]["reason"] == subset
    assert got["subset"]["reason"] == subset
    assert got["both"]["reason"] == team
    for k in ("rowfilter", "none"):
        assert got[k] == {
            "stored": "adjusted",
            "effective": "adjusted",
            "forced": False,
            "reason": None,
        }


def test_viewership_mode_reasons(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const v = (patch) => M.viewershipMode({ viewY: 'resid', teams: [], cats: [],
                                                people: [], booths: [], ...patch });
        return {
          mean: v({ viewY: 'mean', cats: ['agotw'] }),
          cat: v({ cats: ['agotw'], teams: ['t'] }),
          team: v({ teams: ['t'] }),
          people: v({ people: ['p'] }),
          booths: v({ booths: ['fox:x'] }),
          clear: v({}),
          frozen: Object.isFrozen(M.REASONS),
        };
        """
    )
    category = (
        "Showing Viewers: Category picks do not line up with the viewership categories, so "
        "residuals are off. Clear the Category pick to see Residual again."
    )
    subset = (
        "Showing Viewers: this filter cuts inside each category\u2019s season. "
        "Clear it to see Residual again."
    )
    assert got["mean"] == {"stored": "mean", "effective": "mean", "forced": False, "reason": None}
    assert got["cat"]["effective"] == "mean" and got["cat"]["reason"] == category
    for k in ("team", "people", "booths"):
        assert got[k]["effective"] == "mean" and got[k]["reason"] == subset
        assert got[k]["stored"] == "resid"
    assert got["clear"] == {
        "stored": "resid",
        "effective": "resid",
        "forced": False,
        "reason": None,
    }
    assert got["frozen"] is True
