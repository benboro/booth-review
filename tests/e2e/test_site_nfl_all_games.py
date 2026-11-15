# ruff: noqa: E501, RUF001  (embedded JS lines and the UI copy's typographic characters)
"""NFL view 1 with "Special games only" off: every game by team and network, the toggle, the
Networks filter on every NFL tab, and old links.

Synthetic nfl-data fixture only; no vault rows. Counts are recomputed here from the fixture's
`games` block so the view's numbers are checked against the source.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

VIEW = "#nfl-view-teams"
GD = f"{VIEW} .nfl-chart > div"
LEGEND = f"{VIEW} .legend-chips"
TOGGLE = "#nfl-chart-tools input.nfl-special-only"
# Legend order: the booth picker's (Fox, CBS, NBC, ESPN/ABC), Other, then Network TBA.
FAMILIES = ["fox", "cbs", "nbc", "disney", "other", "tba"]
LABELS = {
    "fox": "FOX",
    "cbs": "CBS",
    "nbc": "NBC/Peacock",
    "disney": "ABC/ESPN",
    "other": "Other",
    "tba": "Network TBA",
}
# Network precedence inside a family: ABC before ESPN, NBC before Peacock, cable before streaming.
PRECEDENCE = ["fox", "abc", "espn", "nbc", "peacock", "cbs", "nfln", "prime", "netflix"]
ALL_IDS = ["fox", "cbs", "nbc", "espn", "prime", "peacock", "abc", "nfln", "netflix", "tba"]

PRELUDE = """
const D = await import('./sports/nfl/data.js');
const S = await import('./sports/nfl/state.js');
const U = await import('./sports/nfl/url-state.js');
const K = await import('./sports/nfl/picks.js');
const raw = await (await fetch('nfl-data.json')).json();
const m = D.prepareNfl(raw);
const d = S.defaultNflState(m);
"""


@pytest.fixture
def app(nfl_guarded_page: Page, open_nfl_app: Callable[..., None]) -> Page:
    nfl_guarded_page.set_viewport_size({"width": 1440, "height": 900})
    open_nfl_app(nfl_guarded_page)
    return nfl_guarded_page


@pytest.fixture
def mobile(nfl_mobile_page: Page, open_nfl_app: Callable[..., None]) -> Page:
    open_nfl_app(nfl_mobile_page)
    return nfl_mobile_page


@pytest.fixture
def run(nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None]) -> Callable[[str], Any]:
    open_flagon_cfb(nfl_guarded_page)

    def _run(body: str) -> Any:
        return nfl_guarded_page.evaluate("async () => {" + PRELUDE + body + "}")

    return _run


def _vm(page: Page) -> dict[str, Any]:
    page.wait_for_function("window.__nflTestHooks.getViewModel('teams').drawn === true")
    return page.evaluate("window.__nflTestHooks.getViewModel('teams')")  # type: ignore[no-any-return]


def _set(page: Page, patch: dict[str, Any]) -> None:
    page.evaluate("p => window.__nflTestHooks.setState(p)", patch)


def _state(page: Page) -> dict[str, Any]:
    return page.evaluate("window.__nflTestHooks.getState()")  # type: ignore[no-any-return]


def _search(page: Page) -> str:
    return page.evaluate("location.search")  # type: ignore[no-any-return]


def _net_id(raw: dict[str, Any], i: int) -> str:
    n = raw["games"]["network"][i]
    return "tba" if n is None else raw["lookups"]["networks"][n]["id"]


def _family(raw: dict[str, Any], i: int) -> str:
    n = raw["games"]["network"][i]
    return "tba" if n is None else raw["lookups"]["networks"][n]["family"]


def _is_special(raw: dict[str, Any], i: int) -> bool:
    g = raw["games"]
    return bool(
        g["standalone"][i] or g["agotw"][i] or g["cbs_national"][i] or g["international"][i]
    )


def _bars(raw: dict[str, Any], keep: Callable[[int], bool]) -> dict[str, dict[str, Any]]:
    """Per franchise id: the kept games, their total and special count, and per family the
    count, the special count and each network's `[count, special]`."""
    g = raw["games"]
    ids = [f["id"] for f in raw["lookups"]["franchises"]]
    out: dict[str, dict[str, Any]] = {}
    for i in range(len(g["season"])):
        if not keep(i):
            continue
        for f in (g["home"][i], g["away"][i]):
            bar = out.setdefault(ids[f], {"games": [], "total": 0, "special": 0, "fam": {}})
            bar["games"].append(i)
            bar["total"] += 1
            bar["special"] += _is_special(raw, i)
            fam = bar["fam"].setdefault(_family(raw, i), {"count": 0, "special": 0, "nets": {}})
            fam["count"] += 1
            fam["special"] += _is_special(raw, i)
            net = fam["nets"].setdefault(_net_id(raw, i), [0, 0])
            net[0] += 1
            net[1] += _is_special(raw, i)
    return out


def _order(raw: dict[str, Any], bars: dict[str, dict[str, Any]], narrowed: bool) -> list[str]:
    names = {f["id"]: f["name"] for f in raw["lookups"]["franchises"]}
    if narrowed:
        return sorted(bars, key=lambda f: (-bars[f]["total"], -bars[f]["special"], names[f], f))
    # Not narrowed: special games, then the name, as the Special games bars rank.
    return sorted(bars, key=lambda f: (-bars[f]["special"], names[f], f))


def _assert_rows(
    raw: dict[str, Any], vm: dict[str, Any], bars: dict[str, dict[str, Any]], narrowed: bool
) -> None:
    assert [r["franchise"] for r in vm["rows"]] == _order(raw, bars, narrowed)
    for row in vm["rows"]:
        bar = bars[row["franchise"]]
        assert (row["total"], row["special"]) == (bar["total"], bar["special"])
        assert sorted(row["games"]) == sorted(bar["games"])
        assert [s["family"] for s in row["segments"]] == [f for f in FAMILIES if f in bar["fam"]]
        for seg in row["segments"]:
            fam = bar["fam"][seg["family"]]
            assert (seg["count"], seg["special"]) == (fam["count"], fam["special"])
            nets = sorted(fam["nets"], key=lambda n: PRECEDENCE.index(n) if n in PRECEDENCE else 99)
            assert [[c["id"], c["count"], c["special"]] for c in seg["channels"]] == [
                [n, *fam["nets"][n]] for n in nets
            ]


def _table_rows(page: Page) -> list[dict[str, Any]]:
    """The season table's body rows: the season, the cells before the totals, Games, Special."""
    return page.eval_on_selector_all(  # type: ignore[no-any-return]
        f"{VIEW} .nfl-breakdown table tbody tr",
        """trs => trs.map(tr => { const c = [...tr.children].map(td => td.textContent);
          return { season: c[0], nets: c.slice(1, -2), games: c[c.length - 2], special: c[c.length - 1] }; })""",
    )


def _click_bar(page: Page, fid: str) -> None:
    """Picks a team through the keyboard-accessible data table (the same handler as a bar click)."""
    page.evaluate(
        """([view, fid]) => document.querySelector(`${view} .nfl-data-table button[data-key="${fid}"]`).click()""",
        [VIEW, fid],
    )


# ------------------------------------------------------------------ the default view


def test_default_tab_counts_every_game_by_network(
    app: Page, nfl_fixture_raw: dict[str, Any]
) -> None:
    assert app.locator("#nfl-tab-teams").inner_text() == "Team games"
    assert app.locator("#nfl-tab-teams").get_attribute("aria-selected") == "true"
    assert not app.is_checked(TOGGLE)
    assert _search(app) == "?sport=nfl"
    vm = _vm(app)
    assert vm["mode"] == "all" and vm["networks"] is None
    g = nfl_fixture_raw["games"]
    bars = _bars(nfl_fixture_raw, lambda i: True)
    _assert_rows(nfl_fixture_raw, vm, bars, narrowed=False)
    # Each game counts once per team: the bar totals sum to twice the games.
    assert sum(r["total"] for r in vm["rows"]) == 2 * len(g["season"])
    for row in vm["rows"]:
        assert row["total"] == sum(s["count"] for s in row["segments"])
    assert app.evaluate(f"document.querySelector('{GD}').layout.xaxis.title.text") == "Games"
    # The end markers carry each bar's total.
    totals = app.evaluate(
        f"document.querySelector('{GD}').layout.annotations.filter(a => a.name === 'total').map(a => a.text)"
    )
    assert totals == [str(r["total"]) for r in vm["rows"]]


def test_legend_chips_are_the_network_families(app: Page, nfl_fixture_raw: dict[str, Any]) -> None:
    _vm(app)
    chips = app.eval_on_selector_all(
        f"{LEGEND} li > button.legend-chip",
        "els => els.map(e => [e.dataset.family, e.textContent, e.getAttribute('aria-pressed'), e.dataset.offered])",
    )
    assert chips == [[f, LABELS[f], "true", "true"] for f in FAMILIES]
    assert app.get_attribute(LEGEND, "aria-label") == "Networks: select to show or hide"
    # A chip takes its family's colour from the shared palette, as on the CFB page.
    colors = app.evaluate(
        """async () => { const P = await import('./modules/palette.js');
          return ['fox', 'cbs', 'nbc', 'disney', 'other'].map(f => P.FAMILY_COLORS.light[f]); }"""
    )
    marks = app.eval_on_selector_all(
        f"{LEGEND} li > button.legend-chip",
        "els => els.map(e => e.style.getPropertyValue('--mark'))",
    )
    assert marks[:5] == colors and marks[5] not in colors
    key = app.locator(f"{VIEW} .nfl-shade-key")
    assert key.is_visible() and key.inner_text().split("\n") == ["Special games", "Not special"]


def test_bar_fills_solid_for_special_and_light_for_the_rest(
    app: Page, nfl_fixture_raw: dict[str, Any]
) -> None:
    """The shared stacked bars: per family a solid piece (special) then a light piece (other)."""
    vm = _vm(app)
    got = app.evaluate(
        f"""() => {{ const gd = document.querySelector('{GD}');
          const pieces = gd.data.filter(t => t.xaxis === 'x');
          return {{ modes: [gd.layout.barmode, pieces[0].orientation],
            row0: pieces.map(t => [t.x[0], t.marker.color[0]]).filter(([w]) => w > 0),
            texts: gd.data.filter(t => t.xaxis === 'x5').length }}; }}"""
    )
    assert got["modes"] == ["stack", "h"] and got["texts"] == 0  # no in-bar text
    colors = app.evaluate(
        """async () => { const P = await import('./sports/nfl/palette.js');
          return Object.fromEntries(['fox', 'cbs', 'nbc', 'disney', 'other', 'tba'].map(f => [f, P.familyColor(f, 'light')])); }"""
    )

    def rgba(hex_: str) -> str:
        n = int(hex_[1:], 16)
        return f"rgba({n >> 16},{(n >> 8) & 255},{n & 255},0.25)"

    expected: list[list[Any]] = []
    for seg in vm["rows"][0]["segments"]:
        tone = colors[seg["family"]]
        special = seg["count"] if seg["family"] == "tba" else seg["special"]
        if special:
            expected.append([special, tone])
        if seg["count"] - special:
            expected.append([seg["count"] - special, rgba(tone)])
    assert got["row0"] == expected


def test_bars_rank_by_special_until_a_filter_narrows_them(
    app: Page, nfl_fixture_raw: dict[str, Any]
) -> None:
    raw = nfl_fixture_raw
    _assert_rows(raw, _vm(app), _bars(raw, lambda i: True), narrowed=False)
    # With no narrowing filter the rows keep the Special games order when the toggle flips.
    all_order = [r["franchise"] for r in _vm(app)["rows"]]
    _set(app, {"special": True})
    app.wait_for_function("window.__nflTestHooks.getViewModel('teams').mode === 'special'")
    assert [r["franchise"] for r in _vm(app)["rows"]] == all_order
    _set(app, {"special": False, "networks": ["fox"]})
    app.wait_for_function("window.__nflTestHooks.getViewModel('teams').networks !== null")
    fox = _bars(raw, lambda i: _net_id(raw, i) == "fox")
    _assert_rows(raw, _vm(app), fox, narrowed=True)


def test_a_tie_on_special_games_keeps_the_special_bars_order(run: Callable[[str], Any]) -> None:
    """Two teams level on special games but not on total games must not swap when the toggle
    flips: unnarrowed, the all-games bars break the tie by name, as the Special games bars do."""
    got = run(
        """
        const bar = (franchise, special, total) => ({ franchise, name: m.franchises[franchise].name, special, total });
        // Franchise 1 sorts before franchise 0 by name but has fewer games in all.
        const bars = [bar(0, 3, 11), bar(1, 3, 10), bar(2, 5, 9)];
        const names = (list) => list.map(b => m.franchises[b.franchise].id);
        const sp = bars.map(b => ({ franchise: b.franchise, name: b.name, segmentFaded: {},
          counts: { solo_thursday: b.special, solo_sunday: 0, solo_monday: 0, solo_holiday: 0, solo_other: 0,
            agotw: 0, cbs_national: 0, international_other: 0 } }));
        return { all: names(S.rankNetworkBars(m, bars, false)), narrowed: names(S.rankNetworkBars(m, bars, true)),
          special: names(S.rankTeamBars(m, sp, [])), byName: [m.franchises[0].name, m.franchises[1].name] };
        """
    )
    assert got["byName"][1] < got["byName"][0]
    assert got["all"] == got["special"] == ["f-foxes", "f-gulls", "f-lanterns"]
    assert got["narrowed"] == ["f-lanterns", "f-gulls", "f-foxes"]  # by total once narrowed


def test_hover_names_each_family_its_networks_and_special_games(
    app: Page, nfl_fixture_raw: dict[str, Any]
) -> None:
    raw = nfl_fixture_raw
    vm = _vm(app)
    names = {n["id"]: n["name"] for n in raw["lookups"]["networks"]} | {"tba": "Network TBA"}
    multi = {"nbc", "disney", "other"}  # families whose label covers several networks
    for k, row in enumerate(vm["rows"]):
        lines = [f"{row['label']}, 2024–2026", f"{row['total']} games, {row['special']} special"]
        for seg in row["segments"]:
            sub = []
            if seg["family"] in multi:
                sub.append(", ".join(f"{names[c['id']]} {c['count']}" for c in seg["channels"]))
            if seg["special"]:
                sub.append(f"{seg['special']} special")
            lines.append(
                f"{LABELS[seg['family']]}: {seg['count']}" + (f" ({'; '.join(sub)})" if sub else "")
            )
        assert vm["hover"][k] == lines
    app.evaluate(
        f"""() => document.querySelector('{GD}').emit('plotly_hover',
          {{ points: [{{ customdata: {{ r: 0, s: 0, side: null }} }}], event: {{ clientX: 300, clientY: 200 }} }})"""
    )
    app.wait_for_function("!document.getElementById('chart-tooltip').hidden")
    tip = app.inner_text("#chart-tooltip")
    assert tip.startswith(vm["hover"][0][0]) and tip.endswith("Click to see seasons and games.")


# ------------------------------------------------------------------ the toggle


def test_toggle_switches_to_the_special_games_view_and_back(
    app: Page, nfl_fixture_raw: dict[str, Any]
) -> None:
    _vm(app)
    app.check(TOGGLE)
    app.wait_for_function("window.__nflTestHooks.getViewModel('teams').mode === 'special'")
    assert _search(app) == "?sport=nfl&special=1"
    vm = _vm(app)
    # The old Special games tab: eight category chips, the category info note, the old axis title.
    chips = app.eval_on_selector_all(
        f"{LEGEND} li > button.legend-chip", "els => els.map(e => e.textContent)"
    )
    assert chips[0] == "Thursday night" and len(chips) == 8
    assert (
        app.get_attribute(LEGEND, "aria-label") == "Special game categories: select to show or hide"
    )
    assert (
        app.evaluate(f"document.querySelector('{GD}').layout.xaxis.title.text") == "Special games"
    )
    assert app.locator(f"{VIEW} .nfl-shade-key").is_hidden()
    sp = nfl_fixture_raw["special"]
    by_franchise: dict[int, int] = {}
    for r in range(len(sp["season"])):
        segs = (
            "solo_thursday",
            "solo_sunday",
            "solo_monday",
            "solo_holiday",
            "solo_other",
            "agotw",
            "cbs_national",
            "international_other",
        )
        by_franchise[sp["franchise"][r]] = by_franchise.get(sp["franchise"][r], 0) + sum(
            sp[k][r] for k in segs
        )
    ids = [f["id"] for f in nfl_fixture_raw["lookups"]["franchises"]]
    assert {r["franchise"]: r["total"] for r in vm["rows"]} == {
        ids[f]: n for f, n in by_franchise.items()
    }
    app.uncheck(TOGGLE)
    app.wait_for_function("window.__nflTestHooks.getViewModel('teams').mode === 'all'")
    assert _search(app) == "?sport=nfl"


def test_info_note_follows_the_toggle(app: Page) -> None:
    _vm(app)
    info = f"{VIEW} button.band-info"
    assert app.get_attribute(info, "aria-label") == "About this chart"
    app.click(info)
    app.wait_for_selector("dialog.info-modal[open]")
    assert app.inner_text("dialog.info-modal h2") == "Games by network"
    text = app.inner_text("dialog.info-modal .panel-body")
    assert "Solid: the network's special games." in text
    assert (
        "A group can hold several networks: NBC and Peacock; ABC and ESPN. The hover counts each one."
        in text
    )
    assert "Other: NFL Network, Prime and Netflix." in text
    assert "Network TBA: a game with no network listed yet." in text
    assert (
        app.get_attribute("dialog.info-modal a", "href") == "methodology.html#nfl-games-by-network"
    )
    app.keyboard.press("Escape")
    app.check(TOGGLE)
    assert app.get_attribute(info, "aria-label") == "About these categories"
    app.click(info)
    app.wait_for_selector("dialog.info-modal[open]")
    assert app.inner_text("dialog.info-modal h2") == "Special game categories"
    assert app.get_attribute("dialog.info-modal a", "href") == "methodology.html#nfl-special-games"


@pytest.mark.parametrize(
    ("query", "special", "view", "canonical"),
    [
        ("?sport=nfl", False, "teams", "?sport=nfl"),
        # The old first tab's name: the same tab with the toggle on.
        ("?sport=nfl&view=special", True, "teams", "?sport=nfl&special=1"),
        ("?sport=nfl&view=special&cat=tnf", True, "teams", "?sport=nfl&special=1&cat=tnf"),
        ("?sport=nfl&special=1", True, "teams", "?sport=nfl&special=1"),
        ("?sport=nfl&special=0", False, "teams", "?sport=nfl"),
        ("?sport=nfl&cat=tnf", False, "teams", "?sport=nfl&cat=tnf"),
        # The toggle belongs to the first tab but is kept while another tab shows.
        ("?sport=nfl&view=crews&special=1", True, "crews", "?sport=nfl&view=crews&special=1"),
    ],
)
def test_old_and_new_links_land_on_the_toggle_state_they_imply(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    query: str,
    special: bool,
    view: str,
    canonical: str,
) -> None:
    open_nfl_app(nfl_guarded_page, query)
    state = _state(nfl_guarded_page)
    assert (state["special"], state["view"]) == (special, view)
    assert _search(nfl_guarded_page) == canonical
    if view == "teams":
        assert _vm(nfl_guarded_page)["mode"] == ("special" if special else "all")
        assert nfl_guarded_page.is_checked(TOGGLE) is special


# ------------------------------------------------------------------ Networks: state and URL


def test_networks_state_and_url_round_trip(run: Callable[[str], Any]) -> None:
    got = run(
        """
        const dec = (q) => U.decodeNflState(q, m).networks;
        const enc = (networks) => U.encodeNflState({ ...d, networks }, m);
        return {
          ids: m.net.ids, families: m.net.families,
          byFamily: m.net.families.map(f => m.net.networksByFamily.get(f).map(i => m.net.lookups.networks[i].id)),
          none: dec('?sport=nfl&networks=none'), order: dec('?sport=nfl&networks=cbs,fox'),
          unknown: dec('?sport=nfl&networks=bogus,%E0%A4%A,fox'), allBogus: dec('?sport=nfl&networks=bogus'),
          tba: dec('?sport=nfl&networks=tba'), every: dec('?sport=nfl&networks=' + m.net.ids.join(',')),
          legacy: dec('?sport=nfl&net=fox'),
          encNull: enc(null), encNone: enc([]), encTwo: enc(['cbs', 'fox']), encAll: enc([...m.net.ids]),
          clean: S.canonicalNflState({ ...d, networks: ['fox', 'fox', 7, 'nope'] }, m).networks,
          count: [S.activeFilterCount(m, d), S.activeFilterCount(m, { ...d, networks: ['fox'] }), S.activeFilterCount(m, { ...d, networks: [] })],
        };
        """
    )
    assert got["ids"] == ALL_IDS and got["families"] == FAMILIES
    assert got["byFamily"] == [
        ["fox"],
        ["cbs"],
        ["nbc", "peacock"],
        ["abc", "espn"],
        ["nfln", "prime", "netflix"],
        ["tba"],
    ]
    assert got["none"] == [] and got["order"] == ["fox", "cbs"]  # lookup order
    assert got["unknown"] == ["fox"] and got["allBogus"] is None
    assert got["tba"] == ["tba"] and got["every"] is None and got["legacy"] is None
    assert got["encNull"] == "?sport=nfl" and got["encNone"] == "?sport=nfl&networks=none"
    assert got["encTwo"] == "?sport=nfl&networks=fox,cbs" and got["encAll"] == "?sport=nfl"
    assert got["clean"] == ["fox"] and got["count"] == [0, 1, 1]


def test_a_stale_network_tba_link_stays_an_empty_pick(run: Callable[[str], Any]) -> None:
    """Once every game has its network there is no Network TBA entry; a link to it alone must
    not widen to every network."""
    got = run(
        """
        const full = structuredClone(raw);
        full.games.network = full.games.network.map(v => v ?? 0);
        full.upcoming.network = full.upcoming.network.map(v => v ?? 0);
        full.upcoming.network_basis = full.upcoming.network_basis.map(v => v ?? '506');
        const m2 = D.prepareNfl(full);
        const dec = (q) => U.decodeNflState(q, m2).networks;
        return { ids: m2.net.ids, families: m2.net.families, tba: dec('?sport=nfl&networks=tba'),
          mixed: dec('?sport=nfl&networks=tba,fox'), bogus: dec('?sport=nfl&networks=bogus') };
        """
    )
    assert "tba" not in got["ids"] and "tba" not in got["families"]
    assert got["tba"] == [] and got["mixed"] == ["fox"] and got["bogus"] is None


def test_game_mask_and_special_recount_follow_the_networks_pick(
    run: Callable[[str], Any], nfl_fixture_raw: dict[str, Any]
) -> None:
    raw = nfl_fixture_raw
    got = run(
        """
        const pass = (st) => { const out = []; for (let i = 0; i < m.n; i++) if (S.gamePasses(m, st, i)) out.push(i); return out; };
        const cols = ['franchise', 'season', 'games', 'international', 'flexed', 'solo_thursday', 'solo_sunday',
          'solo_monday', 'solo_holiday', 'solo_other', 'agotw', 'cbs_national', 'international_other',
          ...['christmas', 'thanksgiving', 'black_friday', 'international', 'tnf', 'snf', 'mnf', 'saturday', 'friday',
            'sunday_early', 'sunday_late', 'other'].map(c => 'standalone_' + c)];
        const pickCols = (rows) => rows.map(r => cols.map(c => r[c]));
        return {
          fox: pass({ ...d, networks: ['fox'] }), tba: pass({ ...d, networks: ['tba'] }), none: pass({ ...d, networks: [] }),
          recount: pickCols(S.specialRowsFromGames(m, () => true)), shipped: pickCols(m.special),
          same: S.specialRows(m, d) === m.special,
          foxBars: S.teamBars(m, { ...d, networks: ['fox'] }).map(b => [m.franchises[b.franchise].id, b.total, b.games]),
          facets: [...S.networkFacets(m, { ...d, networks: ['fox'] })],
        };
        """
    )
    g = raw["games"]
    n = len(g["season"])
    assert got["fox"] == [i for i in range(n) if _net_id(raw, i) == "fox"]
    assert got["tba"] == [i for i in range(n) if g["network"][i] is None] and got["tba"]
    assert got["none"] == []
    # Recounting every game gives the shipped special block, so a Networks pick narrows from it.
    assert got["recount"] == got["shipped"] and got["same"] is True
    fox = _bars(raw, lambda i: _net_id(raw, i) == "fox")
    for fid, total, games in got["foxBars"]:
        bar = fox.get(fid, {"special": 0, "total": 0})
        assert (total, games) == (bar["special"], bar["total"])
    # The list's counts ignore the Networks pick itself.
    counts = [0] * len(ALL_IDS)
    for i in range(n):
        counts[ALL_IDS.index(_net_id(raw, i))] += 1
    assert got["facets"] == counts


# ------------------------------------------------------------------ Networks: the filter bar


def test_networks_entry_list_and_only(app: Page, nfl_fixture_raw: dict[str, Any]) -> None:
    raw = nfl_fixture_raw
    trigger = "#nfl-trigger-networks"
    assert app.inner_text(f"{trigger} .filter-value") == "All"
    assert "is-changed" not in (app.get_attribute(trigger, "class") or "")
    app.click(trigger)
    app.wait_for_selector("#nfl-pop-networks:popover-open")
    pop = "#nfl-filter-networks-pop"
    rows = app.eval_on_selector_all(
        f"{pop} .family-item",
        """els => els.map(e => [e.querySelector('.option-name').textContent, e.querySelector('.option-count').textContent,
          e.querySelector('input').checked, !!e.querySelector('.family-caret')])""",
    )
    n = len(raw["games"]["season"])
    counts = {f: sum(1 for i in range(n) if _family(raw, i) == f) for f in FAMILIES}
    # A caret only where a family holds more than one network.
    assert rows == [
        [LABELS[f], f"({counts[f]})", True, f in ("nbc", "disney", "other")] for f in FAMILIES
    ]
    assert app.locator(f"{pop} .network-list:visible").count() == 0  # every family starts collapsed

    # A family checkbox turns its networks off; the entry lists what stays, in the accent.
    app.uncheck(f'{pop} input[data-family-checkbox="other"]')
    assert _state(app)["networks"] == ["fox", "cbs", "nbc", "espn", "peacock", "abc", "tba"]
    assert _search(app) == "?sport=nfl&networks=fox,cbs,nbc,espn,peacock,abc,tba"
    assert "is-changed" in (app.get_attribute(trigger, "class") or "")
    assert (
        app.inner_text(f"{trigger} .filter-value")
        == "Fox, CBS, NBC, ESPN, Peacock, ABC, Network TBA"
    )

    # One network of a family: the family box is mixed and says how many are on.
    app.click(f'{pop} .family-caret[aria-label="ABC/ESPN channels"]')
    app.uncheck(f'{pop} input[data-network-id="espn"]')
    mixed = app.evaluate(
        f"""() => {{ const box = document.querySelector('{pop} input[data-family-checkbox="disney"]');
          return [box.checked, box.indeterminate]; }}"""
    )
    assert mixed == [False, True]
    app.click(
        f'{pop} .family-caret[aria-label="ABC/ESPN channels"]'
    )  # collapsed again: the hint shows
    assert app.inner_text(f"{pop} #nfl-family-on-disney-pop") == "1 of 2 on"

    # Only, then All, on a family row (the shared rule with the legend's double-click).
    only = f'{pop} .family-item:has(input[data-family-checkbox="fox"]) .only-btn'
    app.hover(f'{pop} .family-item:has(input[data-family-checkbox="fox"])')
    assert app.inner_text(only) == "Only"
    app.click(only)
    assert _state(app)["networks"] == ["fox"] and _search(app) == "?sport=nfl&networks=fox"
    assert (
        app.inner_text(only) == "All"
        and app.get_attribute(only, "aria-label") == "Show all networks"
    )
    app.click(only)
    assert _state(app)["networks"] is None and _search(app) == "?sport=nfl"

    # Reset and Clear all filters both clear the pick.
    app.uncheck(f'{pop} input[data-family-checkbox="cbs"]')
    assert app.get_attribute("#nfl-clear-filters", "aria-disabled") == "false"
    app.click(f"{pop} .group-reset")
    assert _state(app)["networks"] is None
    app.uncheck(f'{pop} input[data-family-checkbox="cbs"]')
    app.keyboard.press("Escape")
    app.click("#nfl-clear-filters")
    assert _state(app)["networks"] is None and _search(app) == "?sport=nfl"
    assert app.get_attribute("#nfl-clear-filters", "aria-disabled") == "true"


def test_networks_list_reopens_collapsed(app: Page) -> None:
    app.click("#nfl-trigger-networks")
    app.wait_for_selector("#nfl-pop-networks:popover-open")
    app.click('#nfl-filter-networks-pop .family-caret[aria-label="NBC/Peacock channels"]')
    assert app.locator("#nfl-filter-networks-pop .network-list:visible").count() == 1
    app.keyboard.press("Escape")
    app.click("#nfl-trigger-networks")
    app.wait_for_selector("#nfl-pop-networks:popover-open")
    assert app.locator("#nfl-filter-networks-pop .network-list:visible").count() == 0


def test_legend_chip_click_and_double_click_drive_the_networks_filter(
    app: Page, nfl_fixture_raw: dict[str, Any]
) -> None:
    raw = nfl_fixture_raw
    _vm(app)
    chip = f'{LEGEND} button[data-family="cbs"]'
    app.click(chip)
    assert _state(app)["networks"] == [i for i in ALL_IDS if i != "cbs"]
    assert app.get_attribute(chip, "aria-pressed") == "false"
    vm = _vm(app)
    assert all("cbs" not in [s["family"] for s in r["segments"]] for r in vm["rows"])
    _assert_rows(raw, vm, _bars(raw, lambda i: _net_id(raw, i) != "cbs"), narrowed=True)
    app.wait_for_timeout(400)  # past the double-click window: a second single click
    app.click(chip)
    assert _state(app)["networks"] is None and app.get_attribute(chip, "aria-pressed") == "true"
    app.wait_for_timeout(400)

    # A double-click shows only that family (its hint says so), and a second one shows all again.
    nbc = f'{LEGEND} button[data-family="nbc"]'
    assert app.get_attribute(nbc, "title") == "Double-click to show only NBC/Peacock"
    app.dblclick(nbc)
    assert _state(app)["networks"] == ["nbc", "peacock"]
    assert _search(app) == "?sport=nfl&networks=nbc,peacock"
    pressed = app.eval_on_selector_all(
        f"{LEGEND} button", "els => els.map(e => e.getAttribute('aria-pressed'))"
    )
    assert pressed == ["false", "false", "true", "false", "false", "false"]
    assert app.get_attribute(nbc, "title") == "Double-click to show all networks"
    app.wait_for_timeout(1100)  # past the double-click window
    app.dblclick(nbc)
    assert _state(app)["networks"] is None


def test_chips_and_only_ignore_team_as_the_bars_do(
    app: Page, nfl_fixture_raw: dict[str, Any]
) -> None:
    """Team only fades bars on this tab, so a network no picked team played on is still on
    offer: its chip is not dotted and Only keeps it."""
    raw = nfl_fixture_raw
    g = raw["games"]
    ids = [f["id"] for f in raw["lookups"]["franchises"]]
    tba = next(i for i in range(len(g["season"])) if g["network"][i] is None)
    outside = next(f for k, f in enumerate(ids) if k not in (g["home"][tba], g["away"][tba]))
    _set(app, {"teams": [outside]})
    vm = _vm(app)
    assert any(s["family"] == "tba" for r in vm["rows"] for s in r["segments"])
    chip = f'{LEGEND} button[data-family="tba"]'
    assert app.get_attribute(chip, "data-offered") == "true"
    assert next(f for f in vm["families"] if f["family"] == "tba")["games"] == 1
    app.dblclick(chip)
    assert _state(app)["networks"] == ["tba"]


def test_a_chip_with_no_games_under_the_other_filters_is_dotted(app: Page) -> None:
    _set(app, {"cats": ["tnf"]})
    app.wait_for_function("window.__nflTestHooks.getViewModel('teams').rows.length > 0")
    offered = app.eval_on_selector_all(
        f"{LEGEND} button",
        "els => Object.fromEntries(els.map(e => [e.dataset.family, e.dataset.offered]))",
    )
    # The fixture's Thursday night games are on Prime and NBC.
    assert offered == {
        "fox": "false",
        "cbs": "false",
        "nbc": "true",
        "disney": "false",
        "other": "true",
        "tba": "false",
    }


# ------------------------------------------------------------------ Networks on every tab


def test_networks_pick_narrows_every_tab(app: Page, nfl_fixture_raw: dict[str, Any]) -> None:
    raw = nfl_fixture_raw
    g = raw["games"]
    n = len(g["season"])
    fox = [i for i in range(n) if _net_id(raw, i) == "fox"]
    _set(app, {"networks": ["fox"]})
    # The headline and the count line count the games on the picked network.
    assert app.inner_text("#nfl-headline") == f"{len(fox)} games, 2024–2026"
    rated = sum(1 for i in fox if g["viewers"][i] is not None)
    assert app.inner_text("#nfl-summary") == f"{rated} rated of {len(fox)} games"
    # A Networks pick alone never fills Matched games (the CFB no-bulk rule).
    assert app.evaluate("window.__nflTestHooks.getTableIndexes()") == []
    # An Announcers pick narrows the all-games bars, so their headline counts its matches.
    p10 = [p["id"] for p in raw["lookups"]["people"]].index("p10")
    called = [i for i in range(n) if any(c["person"] == p10 for c in g["crew"][i])]
    assert called and not set(called) & set(fox)
    _set(app, {"networks": None, "people": ["p10"]})
    assert app.inner_text("#nfl-headline") == f"{len(called)} games, 2024–2026"
    assert sum(r["total"] for r in _vm(app)["rows"]) == 2 * len(called)
    _set(app, {"networks": ["fox"]})
    assert app.inner_text("#nfl-headline") == "0 games, 2024–2026"
    assert app.inner_text("#nfl-summary") == "0 games match"
    app.wait_for_function("window.__nflTestHooks.getViewModel('teams').drawn === false")
    _set(app, {"people": []})

    # Special games only: the bars count the special games on the picked network.
    _set(app, {"special": True})
    app.wait_for_function("window.__nflTestHooks.getViewModel('teams').mode === 'special'")
    bars = _bars(raw, lambda i: _net_id(raw, i) == "fox")
    for row in _vm(app)["rows"]:
        assert row["total"] == bars.get(row["franchise"], {"special": 0})["special"]

    # Scatter: every other network's game fades.
    _set(app, {"special": False, "view": "scatter"})
    app.wait_for_function("window.__nflTestHooks.getViewModel('scatter').drawn === true")
    items = app.evaluate("window.__nflTestHooks.getViewModel('scatter').items")
    assert items and all(it["matched"] == (it["i"] in fox) for it in items)

    # Crews: a pick of a whole booth group is a row filter, so Adjusted is still on offer.
    _set(app, {"view": "crews", "adjusted": True})
    app.wait_for_function("window.__nflTestHooks.getViewModel('crews').drawn === true")
    crews = app.evaluate("window.__nflTestHooks.getViewModel('crews')")
    assert crews["rows"] and {r["network"]["id"] for r in crews["rows"]} == {"fox"}
    assert crews["mode"] == "adjusted" and crews["reason"] is None
    # ESPN without ABC cuts inside the ESPN/ABC booth's seasons: rows recount and Raw is forced.
    _set(app, {"networks": ["espn"]})
    crews = app.evaluate("window.__nflTestHooks.getViewModel('crews')")
    espn = [i for i in range(n) if _net_id(raw, i) == "espn"]
    assert {r["network"]["id"] for r in crews["rows"]} == {"espn_abc"}
    assert sum(r["gamesCount"] for r in crews["rows"]) == sum(1 for i in espn if g["crew"][i])
    assert crews["mode"] == "raw" and "cuts inside each booth" in crews["reason"]

    # Viewership: each point recounts to the picked network's games, and Residual gives way.
    _set(app, {"view": "viewership", "networks": ["nbc"], "viewY": "resid"})
    app.wait_for_function("window.__nflTestHooks.getViewModel('viewership').drawn === true")
    vw = app.evaluate("window.__nflTestHooks.getViewModel('viewership')")
    nbc_rated = sum(1 for i in range(n) if _net_id(raw, i) == "nbc" and g["viewers"][i] is not None)
    assert sum(p["n"] for c in vw["categories"] for p in c["points"]) == nbc_rated
    assert vw["mode"]["effective"] == "mean" and "cuts inside each category" in vw["mode"]["reason"]


def test_networks_pick_on_this_weekend(app: Page, nfl_fixture_raw: dict[str, Any]) -> None:
    raw = nfl_fixture_raw
    _set(app, {"view": "weekend"})
    app.wait_for_selector(".wk-cell")
    cells = app.locator(".wk-cell").count()
    assert app.inner_text("#nfl-summary") == f"{cells} of {cells} games match"
    # The Networks entry stays live on This weekend (Seasons and Category grey out).
    assert app.get_attribute("#nfl-trigger-networks", "aria-disabled") != "true"
    assert app.get_attribute("#nfl-trigger-seasons", "aria-disabled") == "true"
    u = raw["upcoming"]
    ids = [n["id"] for n in raw["lookups"]["networks"]]
    cbs = sum(1 for v in u["network"] if v is not None and ids[v] == "cbs")
    tba = sum(1 for v in u["network"] if v is None)
    assert cbs and tba
    _set(app, {"networks": ["cbs"]})
    assert app.inner_text("#nfl-summary") == f"{cbs} of {cells} games match"
    assert _search(app) == "?sport=nfl&view=weekend&networks=cbs"
    # An upcoming game with no network yet answers to Network TBA.
    _set(app, {"networks": ["tba"]})
    assert app.inner_text("#nfl-summary") == f"{tba} of {cells} games match"


def test_networks_list_counts_this_weekends_games(
    app: Page, nfl_fixture_raw: dict[str, Any]
) -> None:
    """On This weekend the list counts that week's games, whatever Seasons and Category say
    (the tab ignores both), so Only never picks a network with no game that week."""
    raw = nfl_fixture_raw
    u = raw["upcoming"]
    ids = [n["id"] for n in raw["lookups"]["networks"]]
    week = [("tba" if v is None else ids[v]) for v in u["network"]]
    # Stale picks from another tab: Thursday night in 2024 only (Prime and NBC games there).
    _set(app, {"view": "weekend", "cats": ["tnf"], "seasons": [2024, 2024]})
    app.wait_for_selector(".wk-cell")
    app.click("#nfl-trigger-networks")
    app.wait_for_selector("#nfl-pop-networks:popover-open")
    pop = "#nfl-filter-networks-pop"
    counts = app.eval_on_selector_all(
        f"{pop} .family-item",
        "els => els.map(e => [e.querySelector('input').dataset.familyCheckbox, e.querySelector('.option-count').textContent])",
    )
    fam = {
        "fox": ["fox"],
        "cbs": ["cbs"],
        "nbc": ["nbc", "peacock"],
        "disney": ["abc", "espn"],
        "other": ["nfln", "prime", "netflix"],
        "tba": ["tba"],
    }
    assert counts == [[f, f"({sum(week.count(i) for i in fam[f])})"] for f in FAMILIES]
    # Only on Other keeps the network that has a game this week (NFL Network), not Prime.
    app.hover(f'{pop} .family-item:has(input[data-family-checkbox="other"])')
    app.click(f'{pop} .family-item:has(input[data-family-checkbox="other"]) .only-btn')
    assert _state(app)["networks"] == ["nfln"]
    cells = app.locator(".wk-cell").count()
    assert app.inner_text("#nfl-summary") == f"{week.count('nfln')} of {cells} games match"


# ------------------------------------------------------------------ filters on the all-games bars


def test_team_puts_bars_in_focus_and_other_filters_narrow_the_counts(
    app: Page, nfl_fixture_raw: dict[str, Any]
) -> None:
    raw = nfl_fixture_raw
    g = raw["games"]
    slots = raw["lookups"]["slots"]
    # Team: the picked team's bar stays bright; no count changes.
    _set(app, {"teams": ["f-gulls"]})
    vm = _vm(app)
    _assert_rows(raw, vm, _bars(raw, lambda i: True), narrowed=False)
    assert {r["franchise"] for r in vm["rows"] if not r["faded"]} == {"f-gulls"}
    # Category narrows what each bar counts (Team still does not).
    _set(app, {"cats": ["tnf"]})
    tnf = _bars(raw, lambda i: bool(g["standalone"][i]) and slots[g["slot"][i]] == "TNF")
    _assert_rows(raw, _vm(app), tnf, narrowed=True)
    # Announcers narrows to the games the person called.
    _set(app, {"teams": [], "cats": [], "people": ["p10"]})
    idx = [p["id"] for p in raw["lookups"]["people"]].index("p10")
    called = _bars(raw, lambda i: any(c["person"] == idx for c in g["crew"][i]))
    assert called
    _assert_rows(raw, _vm(app), called, narrowed=True)
    # Seasons.
    _set(app, {"people": [], "seasons": [2025, 2025]})
    _assert_rows(raw, _vm(app), _bars(raw, lambda i: g["season"][i] == 2025), narrowed=False)


def test_empty_pick_shows_the_empty_note(app: Page) -> None:
    _set(app, {"networks": []})
    assert _search(app) == "?sport=nfl&networks=none"
    app.wait_for_function("window.__nflTestHooks.getViewModel('teams').drawn === false")
    note = app.locator(f"{VIEW} .season-empty-note")
    assert note.is_visible() and "No games match these filters" in note.inner_text()
    assert app.inner_text("#nfl-trigger-networks .filter-value") == "None"
    assert app.locator(f"{VIEW} .nfl-show-all").is_hidden()


# ------------------------------------------------------------------ bar click: table and season table


def test_bar_click_lists_the_bar_in_matched_games_and_the_season_table(
    app: Page, nfl_fixture_raw: dict[str, Any]
) -> None:
    raw = nfl_fixture_raw
    g = raw["games"]
    vm = _vm(app)
    row = vm["rows"][0]
    app.evaluate(
        f"""() => document.querySelector('{GD}').emit('plotly_click',
          {{ points: [{{ customdata: {{ r: 0, s: 1, side: null }} }}], event: {{ clientX: 300, clientY: 200 }} }})"""
    )
    app.wait_for_function("window.__nflTestHooks.getViewModel('teams').selected !== null")
    assert _vm(app)["selected"] == row["franchise"]
    # Matched games holds exactly the bar's games, and the count line agrees.
    assert sorted(app.evaluate("window.__nflTestHooks.getTableIndexes()")) == sorted(row["games"])
    assert app.inner_text("#nfl-summary") == f"{row['total']} games match"
    # The season table: its header, and per season the family counts, their sum and the special games.
    heads = app.eval_on_selector_all(
        f"{VIEW} .nfl-breakdown thead tr:nth-child(2) th", "els => els.map(e => e.textContent)"
    )
    assert heads == [LABELS[f] for f in FAMILIES]
    assert app.inner_text(f"{VIEW} .nfl-breakdown h3") == f"{row['label']}: season by season"
    bar_games = row["games"]
    table = _table_rows(app)
    assert [r["season"] for r in table] == ["2026", "2025", "2024"]
    for r in table:
        season = [i for i in bar_games if g["season"][i] == int(r["season"])]
        assert r["nets"] == [str(sum(1 for i in season if _family(raw, i) == f)) for f in FAMILIES]
        assert r["games"] == str(len(season)) == str(sum(int(v) for v in r["nets"]))
        assert r["special"] == str(sum(1 for i in season if _is_special(raw, i)))
    assert sum(int(r["games"]) for r in table) == row["total"]

    # A Networks pick narrows the bar, the table and the season table together; an off family is a dash.
    _set(app, {"networks": ["fox", "cbs"]})
    vm = _vm(app)
    picked = next(r for r in vm["rows"] if r["franchise"] == row["franchise"])
    assert sorted(app.evaluate("window.__nflTestHooks.getTableIndexes()")) == sorted(
        picked["games"]
    )
    table = _table_rows(app)
    assert sum(int(r["games"]) for r in table) == picked["total"]
    assert all(r["nets"][2:] == ["–"] * 4 for r in table)
    notes = app.inner_text(f"{VIEW} .nfl-breakdown")
    assert "a dash marks a network turned off" in notes and "only the ones left on" not in notes
    # A family with some of its networks on keeps its column and the note says what it counts.
    _set(app, {"networks": ["fox", "espn"]})
    assert (
        "A column with some of its networks turned off counts only the ones left on."
        in app.inner_text(f"{VIEW} .nfl-breakdown")
    )
    _set(app, {"networks": ["fox", "cbs"]})

    # A second click on the bar clears the selection (after the touch double-fire guard).
    app.wait_for_timeout(600)
    _click_bar(app, row["franchise"])
    app.wait_for_function("window.__nflTestHooks.getViewModel('teams').selected === null")
    assert app.locator(f"{VIEW} .nfl-breakdown").is_hidden()


def test_a_faded_teams_bar_still_lists_every_game_it_shows(
    app: Page, nfl_fixture_raw: dict[str, Any]
) -> None:
    """Team only puts bars in focus, so a click on another team's bar lists that bar's games,
    not just its games against the picked team."""
    _set(app, {"teams": ["f-gulls"]})
    vm = _vm(app)
    other = next(r for r in vm["rows"] if r["faded"])
    _click_bar(app, other["franchise"])
    app.wait_for_function("window.__nflTestHooks.getViewModel('teams').selected !== null")
    assert sorted(app.evaluate("window.__nflTestHooks.getTableIndexes()")) == sorted(other["games"])
    # Flipping the toggle keeps the team picked and lists the special bar's games instead.
    _set(app, {"teams": [], "special": True})
    app.wait_for_function("window.__nflTestHooks.getViewModel('teams').mode === 'special'")
    assert _vm(app)["selected"] == other["franchise"]
    sel = _state(app)["selection"]
    assert "exact" not in sel
    special = [i for i in other["games"] if _is_special(nfl_fixture_raw, i)]
    assert sorted(sel["games"]) == sorted(special)


def test_selection_keeps_the_table_in_step_and_tab_change_drops_it(app: Page) -> None:
    vm = _vm(app)
    fid = vm["rows"][1]["franchise"]
    _click_bar(app, fid)
    app.wait_for_function("window.__nflTestHooks.getViewModel('teams').selected !== null")
    _set(app, {"seasons": [2025, 2026]})
    row = next(r for r in _vm(app)["rows"] if r["franchise"] == fid)
    assert sorted(app.evaluate("window.__nflTestHooks.getTableIndexes()")) == sorted(row["games"])
    _set(app, {"view": "scatter"})
    assert _state(app)["selection"] is None


# ------------------------------------------------------------------ Network TBA


def test_network_tba_caption_chip_and_group(app: Page, nfl_fixture_raw: dict[str, Any]) -> None:
    raw = nfl_fixture_raw
    g = raw["games"]
    tba = [i for i in range(len(g["season"])) if g["network"][i] is None]
    assert len(tba) == 1
    vm = _vm(app)
    assert vm["tba"] == {"seasons": [2024], "games": 1}
    caption = app.locator(f"{VIEW} .nfl-pending-caption")
    assert caption.inner_text() == "1 game has no network listed yet (2024), shown as Network TBA."
    in_bars = [r for r in vm["rows"] if any(s["family"] == "tba" for s in r["segments"])]
    assert len(in_bars) == 2  # the game's two teams
    # Outside its season the caption goes; it never names a game the bars do not count.
    _set(app, {"seasons": [2025, 2026]})
    app.wait_for_function("window.__nflTestHooks.getViewModel('teams').tba.games === 0")
    assert caption.is_hidden()
    text = app.evaluate(
        """async () => { const T = await import('./sports/nfl/views/team-bars.js');
          return [T.tbaText({ seasons: [2025, 2026], games: 12 }), T.tbaText({ seasons: [], games: 0 })]; }"""
    )
    assert text == [
        "12 games have no network listed yet (2025 and 2026), shown as Network TBA.",
        None,
    ]


# ------------------------------------------------------------------ show all, data table, phone


def test_data_table_follows_the_toggle(app: Page) -> None:
    vm = _vm(app)
    heads = app.eval_on_selector_all(
        f"{VIEW} .nfl-data-table thead th", "els => els.map(e => e.textContent)"
    )
    assert heads == ["Team", *[LABELS[f] for f in FAMILIES], "Games", "Special games"]
    assert app.inner_text(f"{VIEW} .nfl-data-table caption") == "Games by team and network"
    first = app.eval_on_selector_all(
        f"{VIEW} .nfl-data-table tbody tr:first-child td", "els => els.map(e => e.textContent)"
    )
    row = vm["rows"][0]
    counts = {s["family"]: s["count"] for s in row["segments"]}
    assert first == [
        *[str(counts.get(f, 0)) for f in FAMILIES],
        str(row["total"]),
        str(row["special"]),
    ]
    _set(app, {"special": True})
    app.wait_for_function("window.__nflTestHooks.getViewModel('teams').mode === 'special'")
    assert app.inner_text(f"{VIEW} .nfl-data-table caption") == "Special games by team"
    heads = app.eval_on_selector_all(
        f"{VIEW} .nfl-data-table thead th", "els => els.map(e => e.textContent)"
    )
    assert heads[0] == "Team" and heads[-1] == "Total" and len(heads) == 10


def test_phone_layout_toggle_chart_and_season_table(
    mobile: Page, nfl_fixture_raw: dict[str, Any]
) -> None:
    vm = _vm(mobile)
    assert vm["mode"] == "all"
    # Nothing scrolls sideways, and the chart fits the module.
    sizes = mobile.evaluate(
        f"""() => {{ const gd = document.querySelector('{GD}').getBoundingClientRect();
          return {{ scroll: document.documentElement.scrollWidth, width: window.innerWidth,
            left: gd.left, right: gd.right }}; }}"""
    )
    assert (
        sizes["scroll"] <= sizes["width"]
        and sizes["left"] >= 0
        and sizes["right"] <= sizes["width"]
    )
    # The toggle is reachable and works by touch.
    box = mobile.locator("#nfl-chart-tools label.nfl-special-only-label").bounding_box()
    assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= sizes["width"]
    mobile.locator("#nfl-chart-tools label.nfl-special-only-label").tap()
    mobile.wait_for_function("window.__nflTestHooks.getViewModel('teams').mode === 'special'")
    mobile.locator("#nfl-chart-tools label.nfl-special-only-label").tap()
    mobile.wait_for_function("window.__nflTestHooks.getViewModel('teams').mode === 'all'")
    # A picked team: the season table scrolls inside its own wrapper, then the hover lines follow.
    row = vm["rows"][0]
    _click_bar(mobile, row["franchise"])
    mobile.wait_for_selector(f"{VIEW} .nfl-breakdown table")
    kids = mobile.eval_on_selector_all(
        f"{VIEW} .nfl-breakdown > *",
        "els => els.map(e => e.classList.contains('table-scroll') ? 'table' : e.classList.contains('nfl-breakdown-lines') ? 'lines' : e.tagName)",
    )
    assert kids.index("table") < kids.index("lines")
    lines = mobile.eval_on_selector_all(
        f"{VIEW} .nfl-breakdown-lines p", "els => els.map(e => e.textContent)"
    )
    assert lines == _vm(mobile)["hover"][0][1:]
    assert mobile.evaluate("document.documentElement.scrollWidth") <= sizes["width"]
    # The Filters sheet lists Networks under Broadcast and counts it as a changed filter.
    _set(mobile, {"networks": ["fox"]})
    assert mobile.inner_text("#nfl-filters-button") == "Filters (1 changed)"
    mobile.click("#nfl-filters-button")
    mobile.wait_for_selector("#nfl-filters-sheet:popover-open")
    assert mobile.locator("#nfl-filter-networks-sheet").is_visible()
    assert mobile.inner_text("#nfl-filter-chips .filter-chip") in ("Networks: Fox", "Networks (1)")
