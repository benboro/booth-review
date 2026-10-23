# ruff: noqa: E501, RUF001  (embedded JS lines and the UI copy's typographic characters)
"""999.5-13: NFL view 1, Special games by team (stacked exclusive-category bars).

Synthetic nfl-data fixture only; no vault rows. Counts are recomputed here from the
fixture's `special` block so the view's numbers are checked against the source.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, Route

pytestmark = pytest.mark.e2e

SEGMENT_KEYS = [
    "solo_thursday",
    "solo_sunday",
    "solo_monday",
    "solo_holiday",
    "solo_other",
    "agotw",
    "cbs_national",
    "international_other",
]
SEGMENT_LABELS = [
    "Thursday night",
    "Sunday night",
    "Monday night",
    "Holiday",
    "Other solo slot",
    "Fox AGOTW",
    "CBS late national",
    "International, shared window",
]
NOTE_LINES = [
    "Solo slot = no other NFL game kicks off within 3 hours.",
    "Thursday night: solo-slot games on Thursday.",
    "Sunday night: solo-slot Sunday night games.",
    "Monday night: solo-slot Monday games. Monday doubleheader games share a window, so they are not counted here.",
    "Holiday: Thanksgiving, Christmas and Black Friday games in a solo slot.",
    "Other solo slot: any other game with no NFL game within 3 hours, such as Saturday or an international morning game.",
    "Fox AGOTW: Fox's top game on a Sunday afternoon doubleheader.",
    "CBS late national: CBS's national game in the late Sunday window.",
    "International, shared window: a game played abroad that shares its window with other games.",
]
LEGEND = "#nfl-view-special .legend-chips"
SLOT_ORDER = [
    ("tnf", "TNF"),
    ("snf", "SNF"),
    ("mnf", "MNF"),
    ("thanksgiving", "Thanksgiving"),
    ("christmas", "Christmas"),
    ("black_friday", "Black Friday"),
    ("saturday", "Saturday"),
    ("international", "International"),
    ("friday", "Friday"),
    ("sunday_early", "Sunday early"),
    ("sunday_late", "Sunday late"),
    ("other", "other"),
]
GD = "#nfl-view-special .nfl-chart > div"


@pytest.fixture
def app(nfl_guarded_page: Page, open_nfl_app: Callable[..., None]) -> Page:
    open_nfl_app(nfl_guarded_page)
    return nfl_guarded_page


@pytest.fixture
def mobile(nfl_mobile_page: Page, open_nfl_app: Callable[..., None]) -> Page:
    open_nfl_app(nfl_mobile_page)
    return nfl_mobile_page


def _vm(page: Page) -> dict[str, Any]:
    page.wait_for_function("window.__nflTestHooks.getViewModel('special').drawn === true")
    return page.evaluate("window.__nflTestHooks.getViewModel('special')")  # type: ignore[no-any-return]


def _set(page: Page, patch: dict[str, Any]) -> None:
    page.evaluate("p => window.__nflTestHooks.setState(p)", patch)


def _special_rows(raw: dict[str, Any], lo: int, hi: int) -> list[dict[str, Any]]:
    sp = raw["special"]
    keys = list(sp)
    n = len(sp["season"])
    return [{k: sp[k][r] for k in keys} for r in range(n) if lo <= sp["season"][r] <= hi]


def _agg(raw: dict[str, Any], lo: int, hi: int) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for r in _special_rows(raw, lo, hi):
        a = out.setdefault(
            r["franchise"],
            {
                **dict.fromkeys(SEGMENT_KEYS, 0),
                "international": 0,
                "flexed": 0,
                "special": 0,
                "slots": {},
            },
        )
        for k in SEGMENT_KEYS:
            a[k] += r[k]
        a["international"] += r["international"]
        a["flexed"] += r["flexed"]
        a["special"] += r["special"]
        for col, _ in SLOT_ORDER:
            a["slots"][col] = a["slots"].get(col, 0) + r["standalone_" + col]
    return out


def _denoms(raw: dict[str, Any], lo: int, hi: int) -> tuple[int, int]:
    w = raw["season_weeks"]
    fox = cbs = 0
    for k, s in enumerate(w["season"]):
        if lo <= s <= hi:
            fox += w["fox_doubleheader_weeks"][k] - w["fox_ambiguous_weeks"][k]
            cbs += w["cbs_doubleheader_weeks"][k] - w["cbs_ambiguous_weeks"][k]
    return fox, cbs


def _rate(count: int, denom: int) -> str:
    if denom <= 0:
        return "n/a"
    return f"{count} of {denom} weeks ({int(count / denom * 100 + 0.5)}%)"


def _hover(raw: dict[str, Any], f: int, lo: int, hi: int) -> list[str]:
    a = _agg(raw, lo, hi)[f]
    fox, cbs = _denoms(raw, lo, hi)
    name = raw["lookups"]["franchises"][f]["name"]
    slots = ", ".join(f"{lbl} {a['slots'][col]}" for col, lbl in SLOT_ORDER if a["slots"][col] > 0)
    total = sum(a[k] for k in SEGMENT_KEYS)
    out = [
        f"{name}, {lo}" if lo == hi else f"{name}, {lo}–{hi}",
        f"{total} special games",
    ]
    out += [f"{lbl}: {a[k]}" for k, lbl in zip(SEGMENT_KEYS, SEGMENT_LABELS, strict=True) if a[k]]
    if slots:
        out.append(f"Solo slots: {slots}")
    out += [
        f"International, all windows: {a['international']}",
        f"Fox AGOTW weeks: {_rate(a['agotw'], fox)}",
        f"CBS late national weeks: {_rate(a['cbs_national'], cbs)}",
        f"Flexed: {a['flexed']}",
        "Click to see seasons and games.",
    ]
    return out


def _emit(page: Page, event: str, k: int) -> None:
    page.evaluate(
        """([ev, k, sel]) => {
          const gd = document.querySelector(sel);
          gd.emit(ev, { points: [{ customdata: k }], event: { clientX: 300, clientY: 200 } });
        }""",
        [event, k, GD],
    )


def _tooltip(page: Page) -> list[str]:
    page.wait_for_function("!document.getElementById('chart-tooltip').hidden")
    return page.evaluate(  # type: ignore[no-any-return]
        "Array.from(document.getElementById('chart-tooltip').children).map(c => c.textContent)"
    )


def _franchise_idx(raw: dict[str, Any], fid: str) -> int:
    return [f["id"] for f in raw["lookups"]["franchises"]].index(fid)


def _expected_order(raw: dict[str, Any], lo: int, hi: int) -> list[str]:
    agg = _agg(raw, lo, hi)
    fr = raw["lookups"]["franchises"]
    rows = []
    for idx, f in enumerate(fr):
        a = agg.get(idx)
        total = sum(a[k] for k in SEGMENT_KEYS) if a else 0
        rows.append((-total, f["name"], f["id"]))
    return [r[2] for r in sorted(rows)]


# ------------------------------------------------------------------ chart


def test_traces_legend_and_counts(app: Page, nfl_fixture_raw: dict[str, Any]) -> None:
    vm = _vm(app)
    names = app.evaluate(f"document.querySelector('{GD}').data.map(t => t.name)")
    assert names == SEGMENT_LABELS
    modes = app.evaluate(
        f"[document.querySelector('{GD}').layout.barmode, document.querySelector('{GD}').data[0].orientation]"
    )
    assert modes == ["stack", "h"]
    marker_lines = app.evaluate(
        f"document.querySelector('{GD}').data.map(t => t.marker.line.width[0])"
    )
    assert marker_lines == [1] * 8
    chips = app.eval_on_selector_all(
        f"{LEGEND} li > button.legend-chip.pill",
        "els => els.map(e => [e.textContent, e.getAttribute('aria-pressed')])",
    )
    assert chips == [[label, "true"] for label in SEGMENT_LABELS]

    lo, hi = 2024, 2026
    agg = _agg(nfl_fixture_raw, lo, hi)
    sp_sum = sum(r["special"] for r in _special_rows(nfl_fixture_raw, lo, hi))
    io_sum = sum(r["international_other"] for r in _special_rows(nfl_fixture_raw, lo, hi))
    ids = [f["id"] for f in nfl_fixture_raw["lookups"]["franchises"]]
    total_sum = 0
    for row in vm["rows"]:
        a = agg[ids.index(row["franchise"])]
        assert row["counts"] == {k: a[k] for k in SEGMENT_KEYS}
        # Each game counts once: the eight segments sum to the team total.
        assert row["total"] == sum(row["counts"].values())
        assert row["total"] == a["special"] + a["international_other"]
        total_sum += row["total"]
    assert total_sum == sp_sum + io_sum


def test_sorted_by_total_then_name(app: Page, nfl_fixture_raw: dict[str, Any]) -> None:
    vm = _vm(app)
    assert [r["franchise"] for r in vm["rows"]] == _expected_order(nfl_fixture_raw, 2024, 2026)


def test_hover_lines_exact_and_na_for_2026(app: Page, nfl_fixture_raw: dict[str, Any]) -> None:
    vm = _vm(app)
    ids = [f["id"] for f in nfl_fixture_raw["lookups"]["franchises"]]
    k = 0
    f = ids.index(vm["rows"][k]["franchise"])
    _emit(app, "plotly_hover", k)
    assert _tooltip(app) == _hover(nfl_fixture_raw, f, 2024, 2026)
    _emit(app, "plotly_unhover", k)
    assert app.evaluate("document.getElementById('chart-tooltip').hidden") is True

    _set(app, {"seasons": [2026, 2026]})
    vm = _vm(app)
    f = ids.index(vm["rows"][0]["franchise"])
    _emit(app, "plotly_hover", 0)
    lines = _tooltip(app)
    assert lines == _hover(nfl_fixture_raw, f, 2026, 2026)
    fox_line = next(x for x in lines if x.startswith("Fox AGOTW weeks"))
    cbs_line = next(x for x in lines if x.startswith("CBS late national weeks"))
    assert fox_line.endswith("n/a") and cbs_line.endswith("n/a")
    assert "0 of" not in fox_line and "(0%)" not in "".join(lines)


def test_legend_chip_hides_segment(app: Page) -> None:
    _vm(app)
    chip = f"{LEGEND} button[data-segment=agotw]"
    app.click(chip)
    app.wait_for_function(
        "window.__nflTestHooks.getViewModel('special').hiddenSegments.includes('agotw')"
    )
    assert app.get_attribute(chip, "aria-pressed") == "false"
    visible = app.evaluate(f"document.querySelector('{GD}').data.map(t => t.visible)")
    assert visible == [True] * 5 + [False, True, True]
    app.wait_for_timeout(400)  # past the 300 ms double-tap window
    app.click(chip)
    app.wait_for_function(
        "window.__nflTestHooks.getViewModel('special').hiddenSegments.length === 0"
    )


def test_info_note_lists_definitions_and_closes_on_escape(app: Page) -> None:
    _vm(app)
    button = app.locator("#nfl-view-special .legend-row button.band-info")
    note = app.locator("#nfl-view-special .legend-row .band-note")
    assert button.get_attribute("aria-label") == "About these categories"
    assert note.is_hidden()
    button.click()
    assert note.is_visible()
    lines = note.locator("p").all_inner_texts()
    assert lines[:9] == NOTE_LINES
    assert lines[9] == "Each game counts once. See methodology for the full rules."
    assert note.locator("a").get_attribute("href") == "methodology.html#nfl-special-games"
    app.keyboard.press("Escape")
    assert note.is_hidden()


def test_no_standalone_label_anywhere(app: Page) -> None:
    _vm(app)
    assert "standalone" not in app.inner_text("#nfl-view-special").lower()
    assert (
        "standalone"
        not in app.evaluate("document.querySelector('#nfl-view-special').textContent").lower()
    )


def test_team_filter_fades_and_announcers_do_not(
    app: Page, nfl_fixture_raw: dict[str, Any]
) -> None:
    fid = nfl_fixture_raw["lookups"]["franchises"][2]["id"]
    _vm(app)
    _set(app, {"teams": [fid]})
    vm = _vm(app)
    assert {r["franchise"]: r["faded"] for r in vm["rows"]} == {
        f["id"]: f["id"] != fid for f in nfl_fixture_raw["lookups"]["franchises"]
    }
    _set(app, {"teams": [], "people": [nfl_fixture_raw["lookups"]["people"][0]["id"]]})
    vm = _vm(app)
    assert not any(r["faded"] for r in vm["rows"])
    assert not any(any(r["segmentFaded"].values()) for r in vm["rows"])


def test_category_filter_fades_segments(app: Page) -> None:
    _vm(app)
    _set(app, {"cats": ["agotw"]})
    row = _vm(app)["rows"][0]
    assert row["segmentFaded"] == {k: k != "agotw" for k in SEGMENT_KEYS}
    ops = app.evaluate(f"document.querySelector('{GD}').data.map(t => t.marker.opacity[0])")
    assert ops == [0.4, 0.4, 0.4, 0.4, 0.4, 1, 0.4, 0.4]


def _many_franchises(route: Route) -> None:
    resp = route.fetch()
    raw = json.loads(resp.text())
    fr = raw["lookups"]["franchises"]
    base = len(fr)
    sp = raw["special"]
    for k in range(14):
        fr.append({"id": f"f-x{k}", "name": f"Extra {k:02d}" if k else "Odd <b>&Co"})
        raw["lookups"]["team_names"].append({"name": fr[-1]["name"], "short": f"X{k}"})
        for col in sp:
            if col == "franchise":
                sp[col].append(base + k)
            elif col == "season":
                sp[col].append(2025)
            elif col in ("special", "standalone_total", "standalone_tnf", "games"):
                sp[col].append(1)
            elif col.endswith("_rate"):
                sp[col].append(None)
            else:
                sp[col].append(0)
    route.fulfill(response=resp, body=json.dumps(raw))


def test_show_all_toggle_and_escaping(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    nfl_guarded_page.route("**/nfl-data.json", _many_franchises)
    open_nfl_app(nfl_guarded_page)
    vm = _vm(nfl_guarded_page)
    assert len(vm["rows"]) == 15 and vm["totalTeams"] == 20
    btn = nfl_guarded_page.locator("#nfl-view-special .nfl-show-all")
    assert btn.inner_text() == "Show all 20 teams"
    btn.click()
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('special').rows.length === 20"
    )
    assert btn.inner_text() == "Show top 15"
    labels = nfl_guarded_page.evaluate(f"document.querySelector('{GD}').layout.yaxis.ticktext")
    assert "Odd &lt;b&gt;&amp;Co" in labels
    assert not any("<" in t for t in labels)
    assert nfl_guarded_page.locator("#nfl-view-special b").count() == 0
    btn.click()
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('special').rows.length === 15"
    )


# -------------------------------------------------------------- selection


def test_click_selects_team_and_fills_games_and_breakdown(
    app: Page, nfl_fixture_raw: dict[str, Any]
) -> None:
    vm = _vm(app)
    ids = [f["id"] for f in nfl_fixture_raw["lookups"]["franchises"]]
    fid = vm["rows"][0]["franchise"]
    f = ids.index(fid)
    # A real click on the first bar's first visible segment.
    box = app.locator(f"{GD} .barlayer .trace .point path").first.bounding_box()
    assert box
    app.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    app.wait_for_function("window.__nflTestHooks.getViewModel('special').selected !== null")
    assert _vm(app)["selected"] == fid

    g = nfl_fixture_raw["games"]
    expected = sorted(
        i
        for i in range(len(g["season"]))
        if f in (g["home"][i], g["away"][i])
        and (g["standalone"][i] or g["agotw"][i] or g["cbs_national"][i] or g["international"][i])
    )
    assert sorted(app.evaluate("window.__nflTestHooks.getTableIndexes()")) == expected

    heading = app.locator("#nfl-view-special .nfl-breakdown h3").inner_text()
    assert heading == f"{nfl_fixture_raw['lookups']['franchises'][f]['name']}: season by season"
    seasons = app.eval_on_selector_all(
        "#nfl-view-special .nfl-breakdown tbody tr", "els => els.map(e => e.dataset.season)"
    )
    assert seasons == ["2026", "2025", "2024"]
    link = app.get_attribute("#nfl-view-special .nfl-breakdown a", "href")
    assert link == "methodology.html#nfl-doubleheader-weeks-and-rates"
    assert "Rates count doubleheader weeks only." in app.inner_text(
        "#nfl-view-special .nfl-breakdown"
    )

    # Selected bar outlined, others at 40%.
    opac = app.evaluate(f"document.querySelector('{GD}').data[0].marker.opacity")
    assert opac[0] == 1 and all(o == 0.4 for o in opac[1:])
    width = app.evaluate(f"document.querySelector('{GD}').data[0].marker.line.width")
    assert width[0] == 1.5

    app.wait_for_timeout(600)  # past the touch double-fire guard
    _emit(app, "plotly_click", 0)
    app.wait_for_function("window.__nflTestHooks.getViewModel('special').selected === null")
    assert app.locator("#nfl-view-special .nfl-breakdown").is_hidden()
    assert app.evaluate("window.__nflTestHooks.getTableIndexes()") == []


def test_end_markers_are_ink_until_a_team_is_picked_then_accent(app: Page) -> None:
    """UI-SPEC ranked bars: end markers (--ink at 80%) with a value column; the picked
    team's marker takes the accent."""
    layout = f"document.querySelector('{GD}').layout"
    fills = app.evaluate(f"{layout}.shapes.map(s => s.fillcolor)")
    assert fills
    hero = app.evaluate(
        """async () => { const P = await import('./modules/palette.js');
          return {ink: P.mixHex(P.INK.light, P.PAGE_BG.light, 0.8), accent: P.SPECIAL.light,
                  bg: P.PAGE_BG.light}; }"""
    )
    assert set(fills) == {hero["ink"]}
    ring = app.evaluate(f"{layout}.shapes.map(s => [s.line.color, s.line.width])")
    assert all(r == [hero["bg"], 2] for r in ring)
    annos = app.evaluate(f"{layout}.annotations")
    totals = [a for a in annos if a.get("name") == "total"]
    values = [a for a in annos if a.get("name") == "value"]
    assert len(totals) == len(fills) == len(values)
    assert all(a["font"]["weight"] == 600 for a in totals)
    assert all((v["xref"], v["xanchor"]) == ("paper", "right") for v in values)
    _emit(app, "plotly_click", 0)
    app.wait_for_function("window.__nflTestHooks.getViewModel('special').selected !== null")
    picked = app.evaluate(f"{layout}.shapes.map(s => s.fillcolor)")
    assert picked[0] == hero["accent"] == "#1B4F5C"
    assert set(picked[1:]) == {hero["ink"]}


def test_breakdown_rows_match_fixture(app: Page, nfl_fixture_raw: dict[str, Any]) -> None:
    sp = _special_rows(nfl_fixture_raw, 2024, 2026)
    # F-owls (index 3): Thursday night one week, AGOTW another, in 2026 (special 2).
    row = next(
        r
        for r in sp
        if r["season"] == 2026
        and (r["standalone_total"], r["agotw"], r["cbs_national"], r["international_other"])
        == (1, 1, 0, 0)
    )
    vm = _vm(app)
    ids = [f["id"] for f in nfl_fixture_raw["lookups"]["franchises"]]
    fid = ids[row["franchise"]]
    k = [r["franchise"] for r in vm["rows"]].index(fid)
    _emit(app, "plotly_click", k)
    app.wait_for_function("window.__nflTestHooks.getViewModel('special').selected !== null")
    cells = app.eval_on_selector_all(
        "#nfl-view-special .nfl-breakdown tbody tr[data-season='2026'] > *",
        "els => els.map(e => e.textContent)",
    )
    assert cells[:2] == ["2026", str(row["special"] + row["international_other"])]
    assert cells[2:7] == [str(row[k]) for k in SEGMENT_KEYS[:5]]
    assert cells[7] == f"{row['agotw']} · n/a"
    assert cells[8] == f"{row['cbs_national']} · n/a"
    # An earlier season carries a real rate.
    older = next(r for r in sp if r["season"] == 2025 and r["franchise"] == row["franchise"])
    fox, cbs = _denoms(nfl_fixture_raw, 2025, 2025)
    cells = app.eval_on_selector_all(
        "#nfl-view-special .nfl-breakdown tbody tr[data-season='2025'] > *",
        "els => els.map(e => e.textContent)",
    )
    assert cells[7] == _rate(older["agotw"], fox)
    assert cells[8] == _rate(older["cbs_national"], cbs)
    assert cells[1] == str(older["special"] + older["international_other"])


def test_hidden_table_one_row_per_bar(app: Page) -> None:
    vm = _vm(app)
    rows = app.locator("#nfl-view-special div.visually-hidden table tbody tr")
    assert rows.count() == len(vm["rows"])
    first = rows.first.locator("td").all_inner_texts()
    r0 = vm["rows"][0]
    assert first == [*(str(r0["counts"][k]) for k in SEGMENT_KEYS), str(r0["total"])]
    rows.first.locator("button").focus()
    app.keyboard.press("Enter")
    app.wait_for_function("window.__nflTestHooks.getViewModel('special').selected !== null")


def test_mobile_tap_selects_and_shows_hover_lines(
    mobile: Page, nfl_fixture_raw: dict[str, Any]
) -> None:
    vm = _vm(mobile)
    assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth")
    bar = mobile.locator(f"{GD} .barlayer .trace .point path").first
    bar.scroll_into_view_if_needed()
    box = bar.bounding_box()
    assert box
    mobile.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    mobile.wait_for_function("window.__nflTestHooks.getViewModel('special').selected !== null")
    ids = [f["id"] for f in nfl_fixture_raw["lookups"]["franchises"]]
    f = ids.index(vm["rows"][0]["franchise"])
    lines = mobile.eval_on_selector_all(
        "#nfl-view-special .nfl-breakdown-lines p", "els => els.map(e => e.textContent)"
    )
    assert lines == _hover(nfl_fixture_raw, f, 2024, 2026)[1:-1]
    assert mobile.evaluate("document.getElementById('chart-tooltip')?.hidden ?? true") is True


def test_x_ticks_are_round_steps(app: Page) -> None:
    _vm(app)
    steps = app.evaluate(
        """async () => {
          const m = await import('/sports/nfl/views/team-bars.js');
          return [136, 10, 3, 60, 200].map((n) => [n, m.niceStep(n)]);
        }"""
    )
    by_max = dict(steps)
    assert by_max[136] in (20, 25)
    for _, step in steps:
        assert step in (1, 2, 5, 10, 20, 25, 50, 100, 250, 200)
    ticks = app.evaluate(
        f"[...document.querySelectorAll('{GD} .xtick text')].map((t) => Number(t.textContent.replace(/,/g, '')))"
    )
    dtick = app.evaluate(f"document.querySelector('{GD}')._fullLayout.xaxis.dtick")
    assert ticks
    assert all(t % dtick == 0 for t in ticks), (ticks, dtick)
    assert not {17, 34, 51} & set(ticks)


def test_tab_change_drops_the_team_selection(app: Page) -> None:
    """JS-WR-03: a team selection belongs to this view; another tab never shows it stale."""
    _set(app, {"seasons": [2024, 2024]})
    _vm(app)
    _emit(app, "plotly_click", 0)
    app.wait_for_function("window.__nflTestHooks.getViewModel('special').selected !== null")
    assert app.evaluate("window.__nflTestHooks.getTableIndexes().length") > 0
    _set(app, {"view": "scatter", "seasons": [2024, 2026]})
    assert app.evaluate("window.__nflTestHooks.getState().selection") is None
    assert app.evaluate("window.__nflTestHooks.getTableIndexes()") == []
    assert app.locator("#nfl-clear-selection").is_hidden()
    _set(app, {"view": "special"})
    assert app.inner_text("#nfl-chart-subtitle") == "Pick a team bar to see its seasons and games."
    # A patch that changes the view and sets a selection keeps that selection.
    sel = {"kind": "test", "key": "t", "label": "Test", "games": [0, 1]}
    _set(app, {"view": "fox", "selection": sel})
    assert app.evaluate("window.__nflTestHooks.getState().selection") == sel


def test_keyboard_picks_a_team_from_the_visible_on_focus_table(app: Page) -> None:
    """JS-WR-04: the data table shows while focused, and Enter keeps focus on the row."""
    _vm(app)
    wrap = app.locator("#nfl-view-special div.nfl-data-table")
    first = wrap.locator("tbody button").first
    key = first.get_attribute("data-key")
    box = wrap.bounding_box()
    assert box is not None and box["width"] <= 1
    first.focus()
    box = wrap.bounding_box()
    assert box is not None and box["width"] > 100 and box["height"] > 20
    app.keyboard.press("Enter")
    app.wait_for_function("window.__nflTestHooks.getViewModel('special').selected !== null")
    assert _vm(app)["selected"] == key
    assert app.evaluate("document.activeElement.dataset.key") == key


def test_chart_container_hugs_the_plot_for_six_teams(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    """No blank band under the team bars: the container follows the figure height."""
    open_nfl_app(nfl_guarded_page, "?sport=nfl&view=special")
    nfl_guarded_page.wait_for_selector("#nfl-view-special .nfl-chart .js-plotly-plot")
    got = nfl_guarded_page.evaluate(
        """() => {
          const gd = document.querySelector('#nfl-view-special .nfl-chart .js-plotly-plot');
          const box = gd.parentElement.getBoundingClientRect();
          return { gap: box.bottom - gd.getBoundingClientRect().bottom,
                   rows: gd.data[0].y.length };
        }"""
    )
    assert got["rows"] == 6
    assert got["gap"] <= 4


@pytest.mark.parametrize("width", (360, 390, 1440))
def test_end_markers_stay_inside_the_plot(mobile: Page, width: int) -> None:
    """WR-08: the marker headroom accounts for the automargined team-name column, so the
    longest bar's end marker is not clipped at the plot's right edge."""
    mobile.set_viewport_size({"width": width, "height": 844})
    mobile.wait_for_timeout(300)
    _vm(mobile)
    over = mobile.evaluate(
        f"""() => {{
          const gd = document.querySelector('{GD}');
          const xa = gd._fullLayout.xaxis;
          return (gd.layout.shapes || [])
            .filter((s) => s.name === 'end-marker')
            .map((s) => xa.l2p(s.xanchor) + s.x1 - xa._length);
        }}"""
    )
    assert over, "no end markers drawn"
    assert max(over) <= 0.5, over
