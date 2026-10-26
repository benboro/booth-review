"""In-browser proof of the This weekend data adapters (Phase 18, plan 08), on the synthetic
contract fixtures only.

CFB fixture facts (18-01): week "5" is 2026-09-28..2026-10-04 and holds merged index 11 (rated,
played), merged index 19 (the pending unrated game, crew persons 4 and 5, null score) and the 9
scheduled rows (index 4 has a null network, index 3 has no kickoff). The shared fixture has no
tier-a booth, so the lead-star cases add one in the test.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_PRELUDE = """
const D = await import('./modules/data.js');
const S = await import('./modules/select.js');
const W = await import('./modules/weekend-data.js');
const WK = await import('./modules/weekend.js');
const raw = await (await fetch('site-data.json')).json();
const data = D.prepareData(raw);
"""


def _js(body: str, args: str = "") -> str:
    return f"async ({args}) => {{ {_PRELUDE} {body} }}"


def _serve_lead_booth(fixture_raw: dict[str, Any]) -> Callable[[Page], None]:
    """Serve the fixture with a tier-a disney 2026 booth (pbp 4, analyst 5) on the week's
    pending unrated game (merged 19 = unrated 7)."""
    raw = copy.deepcopy(fixture_raw)
    raw["lookups"]["booths"] = [
        {
            "family": "disney",
            "season": 2026,
            "pbp": 4,
            "analyst": 5,
            "rank": 1,
            "tier": "a",
            "lead_network": None,
        }
    ]
    raw["telecasts"]["booth"] = [None] * len(raw["telecasts"]["season"])
    raw["telecasts_unrated"]["booth"] = [None] * len(raw["telecasts_unrated"]["season"])
    raw["telecasts_unrated"]["booth"][7] = 0

    def _serve(page: Page) -> None:
        page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))

    return _serve


@pytest.fixture
def lead_page(
    guarded_page: Page,
    fixture_raw: dict[str, Any],
    open_app: Callable[[Page, str], None],
) -> Page:
    _serve_lead_booth(fixture_raw)(guarded_page)
    open_app(guarded_page, "")
    return guarded_page


def test_scheduled_rows_never_join_the_merged_arrays(lead_page: Page) -> None:
    out = lead_page.evaluate(
        _js(
            """return {
              n: data.n, nRated: data.nRated, tLen: data.t.season.length,
              networkLen: data.t.network.length,
              scheduled: data.scheduledRaw.season.length,
              weeks: data.weeks.length, weekend: data.weekend.label,
              facadeN: W.scheduledFacade(data).n,
              view: S.computeView(data, S.defaultState(data)).visibleCount,
            };"""
        )
    )
    assert out["n"] == out["tLen"] == out["networkLen"] == 20
    assert out["nRated"] == 12
    assert out["scheduled"] == 9 == out["facadeN"]
    assert out["weeks"] == 6
    assert out["weekend"] == "5"
    assert out["view"] == 20


def test_cfb_weekend_games_cover_all_three_blocks_once(lead_page: Page) -> None:
    out = lead_page.evaluate(
        _js(
            """const games = W.cfbWeekendGames(data, '5');
            const keys = games.map((g) => g.key);
            const sched = games.filter((g) => g.block === 'scheduled');
            const played = games.filter((g) => g.block === 't');
            return {
              count: games.length, unique: new Set(keys).size,
              playedIdx: played.map((g) => g.index),
              schedCrew: sched.map((g) => g.crewKnown),
              schedLead: sched.map((g) => g.lead),
              lead: played.filter((g) => g.lead)
                .map((g) => [g.index, g.boothRank, g.pbp, g.analyst]),
              tbd: sched.filter((g) => g.kickoffMin == null).length,
              noNet: sched.filter((g) => g.networkId == null).map((g) => [g.index, g.family]),
              noon: sched.filter((g) => g.kickoffMin === 720).length,
              empty: W.cfbWeekendGames(data, 'nope').length,
              other: W.cfbWeekendGames(data, '4').filter((g) => keys.includes(g.key)).length,
              weekOf: [W.weekOfDate(data.weeks, '2026-10-03'),
                W.weekOfDate(data.weeks, '2030-01-01')],
            };"""
        )
    )
    assert out["count"] == out["unique"] == 11
    assert out["playedIdx"] == [11, 19]
    assert out["schedCrew"] == [False] * 9
    assert out["schedLead"] == [False] * 9
    assert len(out["lead"]) == 1 and out["lead"][0][:2] == [19, 1]
    assert out["lead"][0][2] and out["lead"][0][3]
    assert out["tbd"] == 1
    assert out["noNet"] == [[4, "other"]]
    assert out["noon"] == 3
    assert out["empty"] == 0
    assert out["other"] == 0
    assert out["weekOf"] == ["5", None]


def test_games_file_under_their_own_week_label_not_the_date_span(
    guarded_page: Page,
    fixture_raw: dict[str, Any],
    open_app: Callable[[Page, str], None],
) -> None:
    # 18-13 F1: a Monday game after its week's Saturday slate (Labor Day) keeps its CFBD week
    # even though its date sits in the next week's span (or in no span at all).
    raw = copy.deepcopy(fixture_raw)
    raw["telecasts_scheduled"]["date"][0] = "2026-10-05"  # Monday after week 5, in no span
    raw["telecasts"]["date"][10] = "2026-09-28"  # in week 5's span, but a week-4 game
    guarded_page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    open_app(guarded_page, "")
    out = guarded_page.evaluate(
        _js(
            """const keys = (label) => W.cfbWeekendGames(data, label).map((g) => g.key);
            return { five: keys('5'), four: keys('4') };"""
        )
    )
    assert "cfb:scheduled:0" in out["five"]
    assert "cfb:t:10" not in out["five"]
    assert "cfb:t:10" in out["four"]


def test_pick_parity_with_the_existing_predicates(lead_page: Page) -> None:
    out = lead_page.evaluate(
        _js(
            """const facade = W.scheduledFacade(data);
            const games = W.cfbWeekendGames(data, '5');
            const sched = games.filter((g) => g.block === 'scheduled');
            const slug = data.teamSlugs[facade.t.away_team[0]];
            const conf = data.lookups.conferences[facade.t.home_conference[1]].name;
            const picks = {
              school: { school: [slug] },
              conf: { conferences: [conf] },
              nets: { networks: ['net-b'] },
              netsTba: { networks: ['net-a', 'net-b', 'net-c', 'net-d', 'net-e'] },
              h2h: { school: [slug, data.teamSlugs[facade.t.home_team[0]]], h2h: true },
              booth: { booth: ['a'] },
            };
            const res = {};
            for (const [name, partial] of Object.entries(picks)) {
              const state = Object.assign(S.defaultState(data), partial);
              const pick = WK.weekendPickState(state, S.defaultState(data));
              res[name] = sched.map((g) => [
                W.cfbWeekendPasses(data, state, g),
                S.passesFadeFilters(facade, pick, g.index),
              ]);
            }
            return res;"""
        )
    )
    saw_pass = saw_fail = False
    for name, rows in out.items():
        for adapter, existing in rows:
            assert adapter == existing, name
            saw_pass = saw_pass or adapter
            saw_fail = saw_fail or not adapter
    assert saw_pass and saw_fail
    # A Networks pick that lists every network but the TBA entry fades the null-network row.
    assert out["netsTba"][4] == [False, False]
    assert out["netsTba"][0] == [True, True]
    # No scheduled row has a booth, so a Booth pick fades them all.
    assert all(not a for a, _ in out["booth"])


def test_announcers_pick_passes_only_the_matching_listed_game(lead_page: Page) -> None:
    out = lead_page.evaluate(
        _js(
            """const games = W.cfbWeekendGames(data, '5');
            const person = data.lookups.people[4].id; // pbp on the pending unrated game
            const state = Object.assign(S.defaultState(data), { people: [person] });
            const analystOnly = Object.assign(S.defaultState(data),
              { people: [person], role: 'analyst' });
            return {
              pass: games.filter((g) => W.cfbWeekendPasses(data, state, g)).map((g) => g.key),
              roleMismatch: games.filter((g) => W.cfbWeekendPasses(data, analystOnly, g)).length,
              ring: games.filter((g) => W.cfbWeekendMatches(data, state, g)).map((g) => g.key),
              noPick: games.filter((g) =>
                W.cfbWeekendMatches(data, S.defaultState(data), g)).length,
            };"""
        )
    )
    assert out["pass"] == ["cfb:t:19"]
    assert out["roleMismatch"] == 0
    assert out["ring"] == ["cfb:t:19"]
    assert out["noPick"] == 0


def test_seasons_kickoff_and_postseason_picks_are_ignored(lead_page: Page) -> None:
    out = lead_page.evaluate(
        _js(
            """const games = W.cfbWeekendGames(data, '5');
            const state = Object.assign(S.defaultState(data), {
              seasons: [2000, 2001], slots: ['late'], postseason: 'only',
            });
            return games.filter((g) => W.cfbWeekendPasses(data, state, g)).length;"""
        )
    )
    assert out == 11


def test_scheduled_panel_titles_times_and_not_played(lead_page: Page) -> None:
    out = lead_page.evaluate(
        _js(
            """const P = await import('./modules/panel.js');
            const ctx = { data, state: S.defaultState(data) };
            const read = (j) => {
              P.openScheduledPanel(j, ctx);
              return {
                title: document.getElementById('panel-title').textContent,
                body: document.getElementById('panel-body').textContent,
              };
            };
            const known = read(0);
            const noTime = read(3);
            const noNet = read(4);
            document.getElementById('detail-panel').close();
            P.openPanel(11, { data, state: S.defaultState(data),
              view: S.computeView(data, S.defaultState(data)) });
            const played = document.getElementById('panel-body').textContent;
            document.getElementById('detail-panel').close();
            return { known, noTime, noNet, played };"""
        )
    )
    assert out["known"]["title"] == "Northfield at Foxhollow"
    assert "12:00 PM ET" in out["known"]["body"]
    assert "Not played yet." in out["known"]["body"]
    assert "Viewers" not in out["known"]["body"]
    assert "Excitement" not in out["known"]["body"]
    assert "Time TBA" in out["noTime"]["body"]
    assert "Network TBA" in out["noNet"]["body"]
    assert "Not played yet." not in out["played"]
    assert "Viewers" in out["played"] or "No public rating" in out["played"]


def test_scheduled_press_room_booth_shows_as_a_known_crew(
    guarded_page: Page,
    fixture_raw: dict[str, Any],
    open_app: Callable[[Page, str], None],
) -> None:
    # 18-13 F7: an ESPN Press Room booth on a game 506 has not listed yet fills its cell and
    # its panel, with the page's credit.
    raw = copy.deepcopy(fixture_raw)
    url = "https://espnpressroom.com/us/press-releases/2026/09/synthetic-commentators/"
    sched = raw["telecasts_scheduled"]
    sched["crew"][0] = [
        {"person": 4, "role": "pbp", "feed": "main"},
        {"person": 5, "role": "analyst", "feed": "main"},
    ]
    sched["crew_source_url"][0] = url
    sched["crew_source_label"][0] = "ESPN Press Room"
    guarded_page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    open_app(guarded_page, "")
    out = guarded_page.evaluate(
        _js(
            """const P = await import('./modules/panel.js');
            const games = W.cfbWeekendGames(data, '5').filter((g) => g.block === 'scheduled');
            const g0 = games.find((g) => g.index === 0);
            const g1 = games.find((g) => g.index === 1);
            P.openScheduledPanel(0, { data, state: S.defaultState(data) });
            const body = document.getElementById('panel-body');
            const link = [...body.querySelectorAll('a')].map((a) => [a.textContent, a.href]);
            const text = body.textContent;
            document.getElementById('detail-panel').close();
            return {
              known: [g0.crewKnown, g0.pbp, g0.analyst], other: g1.crewKnown,
              people: [data.lookups.people[4].name, data.lookups.people[5].name],
              text, link,
            };"""
        )
    )
    assert out["known"] == [True, *out["people"]]
    assert out["other"] is False
    assert out["people"][0] in out["text"] and out["people"][1] in out["text"]
    assert "Crew TBA" not in out["text"]
    assert any("ESPN Press Room" in label and href == url for label, href in out["link"])


def test_a6_probe_unplayed_pending_row_in_other_tabs(lead_page: Page) -> None:
    """RESEARCH A6: records how the unplayed pending unrated game (merged 19) is counted by the
    other tabs. An observation only: the numbers are printed for the SUMMARY, not fixed."""
    out = lead_page.evaluate(
        _js(
            """const C = await import('./modules/crew-groups.js');
            const state = S.defaultState(data);
            const view = S.computeView(data, state);
            const rows = C.buildCrewRows(data, view, { mode: 'crew', perSeason: false }).rows;
            const crewGames = rows.reduce((sum, r) => sum + r.gamesCount, 0);
            const inCrews = rows.some((r) => r.games.includes(19));
            return {
              visibleCount: view.visibleCount, visible19: view.visible[19],
              crewGames, inCrews, noPoints: data.t.home_points[19] == null,
              cause: data.t.cause[19],
            };"""
        )
    )
    print("A6 probe:", out)
    assert isinstance(out["visibleCount"], int)
    assert isinstance(out["crewGames"], int)
    assert out["noPoints"] is True
    assert out["cause"] == "pending"


# ---------------------------------------------------------------- NFL

_NFL_PRELUDE = """
const D = await import('./sports/nfl/data.js');
const S = await import('./sports/nfl/state.js');
const W = await import('./sports/nfl/weekend-data.js');
const PN = await import('./sports/nfl/panel.js');
const raw = await (await fetch('nfl-data.json')).json();
const m = D.prepareNfl(raw);
"""


@pytest.fixture
def nfl_run(nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None]) -> Callable[[str], Any]:
    open_flagon_cfb(nfl_guarded_page)

    def _run(body: str) -> Any:
        return nfl_guarded_page.evaluate("async () => {" + _NFL_PRELUDE + body + "}")

    return _run


def test_nfl_upcoming_never_joins_the_games_arrays(
    nfl_run: Callable[[str], Any], nfl_fixture_raw: dict[str, Any]
) -> None:
    got = nfl_run(
        """return { n: m.n, seasonLen: m.cols.season.length, networkLen: m.cols.network.length,
          upcoming: m.upcomingRaw.season.length, week: m.weekend.week };"""
    )
    assert (
        got["n"] == got["seasonLen"] == got["networkLen"] == len(nfl_fixture_raw["games"]["season"])
    )
    assert got["upcoming"] == 10
    assert got["week"] == 5


def test_nfl_weekend_games_blocks_ranks_and_flags(nfl_run: Callable[[str], Any]) -> None:
    got = nfl_run(
        """const games = W.nflWeekendGames(m, 5);
        const played = W.nflWeekendGames(m, 4);
        return {
          count: games.length, unique: new Set(games.map((g) => g.key)).size,
          blocks: [...new Set(games.map((g) => g.block))],
          cbs1pm: games.filter((g) => g.networkId === 'cbs' && g.kickoffMin === 780)
            .map((g) => [g.index, g.boothRank, g.lead]),
          snf: games.filter((g) => g.index === 6).map((g) => [g.networkId, g.networkBasis]),
          tbd: games.filter((g) => g.kickoffMin == null).map((g) => g.index),
          noNet: games.filter((g) => g.networkId == null).map((g) => [g.index, g.family]),
          intl: games.filter((g) => g.neutral).map((g) => g.index),
          pastFlag: [games[0].past, played[0].past],
          playedBlocks: [...new Set(played.map((g) => g.block))], playedCount: played.length,
          none: W.nflWeekendGames(m, 99).length,
        };"""
    )
    assert got["count"] == got["unique"] == 10
    assert got["blocks"] == ["upcoming"]
    assert got["cbs1pm"] == [[0, 1, True], [1, 2, False], [2, None, False], [3, None, False]]
    assert got["snf"] == [["nbc", "slot"]]
    assert got["tbd"] == [7]
    assert got["noNet"] == [[8, "other"]]
    assert got["intl"] == [9]
    assert got["pastFlag"] == [False, True]
    assert got["playedBlocks"] == ["t"]
    assert got["playedCount"] == 2
    assert got["none"] == 0


def test_nfl_pick_parity_and_ignored_picks(nfl_run: Callable[[str], Any]) -> None:
    got = nfl_run(
        """const games = W.nflWeekendGames(m, 5);
        const base = S.defaultNflState(m);
        const ids = (partial) => games
          .filter((g) => W.nflWeekendPasses(m, Object.assign({}, base, partial), g))
          .map((g) => g.index);
        const f0 = m.franchises[0].id;
        const person = m.people[8].id;
        return {
          all: ids({}),
          team: ids({ teams: [f0] }),
          expectTeam: games.filter((g) => {
            const u = m.upcomingRaw;
            return u.home[g.index] === 0 || u.away[g.index] === 0;
          }).map((g) => g.index),
          people: ids({ people: [person] }),
          booth: ids({ booths: ['cbs:' + m.people[8].id] }),
          boothOther: ids({ booths: ['cbs:nobody'] }),
          ignored: ids({ seasons: [2024, 2024], cats: ['tnf'] }),
          ring: games.filter((g) => W.nflWeekendMatches(m, Object.assign({}, base,
            { people: [person] }), g)).map((g) => g.index),
          noRing: games.filter((g) => W.nflWeekendMatches(m, base, g)).length,
        };"""
    )
    assert got["all"] == list(range(10))
    assert got["team"] == got["expectTeam"] and got["team"]
    assert got["people"] == [0]
    assert got["booth"] == [0]
    assert got["boothOther"] == []
    assert got["ignored"] == list(range(10))
    assert got["ring"] == [0]
    assert got["noRing"] == 0


def test_nfl_played_games_use_the_same_predicates(nfl_run: Callable[[str], Any]) -> None:
    got = nfl_run(
        """const games = W.nflWeekendGames(m, 4);
        const base = S.defaultNflState(m);
        const f = m.franchises[m.cols.home[games[0].index]].id;
        const state = Object.assign({}, base, { teams: [f] });
        return games.map((g) => [W.nflWeekendPasses(m, state, g), S.gamePasses(m,
          Object.assign({}, state, { seasons: base.seasons, cats: [] }), g.index)]);"""
    )
    assert got and all(a == b for a, b in got)
    assert got[0][0] is True


def test_nfl_upcoming_panel_branches(nfl_run: Callable[[str], Any]) -> None:
    got = nfl_run(
        """const host = document.body;
        const p = PN.createDetailPanel(host, {});
        const read = (j) => {
          p.open(W.upcomingRow(m, j), null);
          const d = document.getElementById('nfl-detail-panel');
          return {
            title: document.getElementById('nfl-panel-title').textContent,
            text: d.querySelector('.panel-body').textContent,
            anchors: [...d.querySelectorAll('a')].map((a) => [a.textContent, a.href]),
          };
        };
        const out = { crew: read(0), crewless: read(2), slot: read(6), noTime: read(7),
          noNet: read(8) };
        p.close();
        return out;"""
    )
    crew = got["crew"]
    assert crew["title"].count(" at ") == 1 and "Not played yet." in crew["text"]
    assert "Final score" not in crew["text"] and "Viewers" not in crew["text"]
    assert "1:00 PM ET" in crew["text"]
    assert ["Crew from 506 Sports ↗", "https://example.com/lineup"] in crew["anchors"]
    assert "Crew TBA." in got["crewless"]["text"]
    assert "Network follows the slot" in got["slot"]["text"]
    assert "Network follows the slot" not in crew["text"]
    assert "Time TBA" in got["noTime"]["text"]
    assert "Network TBA" in got["noNet"]["text"]
