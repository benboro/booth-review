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

SEGMENT_LABELS = [
    "Standalone slot",
    "AGOTW",
    "CBS national",
    "International (not standalone)",
]
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
                "standalone": 0,
                "agotw": 0,
                "cbs_national": 0,
                "international_other": 0,
                "international": 0,
                "flexed": 0,
                "special": 0,
                "slots": {},
            },
        )
        a["standalone"] += r["standalone_total"]
        a["agotw"] += r["agotw"]
        a["cbs_national"] += r["cbs_national"]
        a["international_other"] += r["international_other"]
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
    standalone = f"Standalone: {a['standalone']}" + (f" ({slots})" if slots else "")
    return [
        f"{name}, {lo}" if lo == hi else f"{name}, {lo}–{hi}",
        f"Special games: {a['standalone'] + a['agotw'] + a['cbs_national'] + a['international_other']}",
        standalone,
        f"AGOTW: {a['agotw']} · {_rate(a['agotw'], fox)}",
        f"CBS national: {a['cbs_national']} · {_rate(a['cbs_national'], cbs)}",
        f"International (not standalone): {a['international_other']}",
        f"International, any slot: {a['international']}. Standalone international games count under Standalone.",
        f"Flexed: {a['flexed']}",
        "Click to see seasons and games.",
    ]


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
        total = (
            a["standalone"] + a["agotw"] + a["cbs_national"] + a["international_other"] if a else 0
        )
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
    chips = app.eval_on_selector_all(
        "#nfl-view-special .nfl-legend-row button",
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
        assert row["counts"] == {
            "standalone": a["standalone"],
            "agotw": a["agotw"],
            "cbs_national": a["cbs_national"],
            "international_other": a["international_other"],
        }
        # D-24: special = standalone + agotw + cbs_national; each game counted once.
        assert a["special"] == a["standalone"] + a["agotw"] + a["cbs_national"]
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
    assert lines[3].endswith("· n/a") and lines[4].endswith("· n/a")
    assert "0 of" not in lines[3] and "(0%)" not in "".join(lines)


def test_legend_chip_hides_segment(app: Page) -> None:
    _vm(app)
    app.click("#nfl-view-special .nfl-legend-row button[data-segment=agotw]")
    app.wait_for_function(
        "window.__nflTestHooks.getViewModel('special').hiddenSegments.includes('agotw')"
    )
    pressed = app.get_attribute(
        "#nfl-view-special .nfl-legend-row button[data-segment=agotw]", "aria-pressed"
    )
    assert pressed == "false"
    visible = app.evaluate(f"document.querySelector('{GD}').data.map(t => t.visible)")
    assert visible == [True, False, True, True]
    app.click("#nfl-view-special .nfl-legend-row button[data-segment=agotw]")
    app.wait_for_function(
        "window.__nflTestHooks.getViewModel('special').hiddenSegments.length === 0"
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
    assert row["segmentFaded"] == {
        "standalone": True,
        "agotw": False,
        "cbs_national": True,
        "international_other": True,
    }
    ops = app.evaluate(f"document.querySelector('{GD}').data.map(t => t.marker.opacity[0])")
    assert ops == [0.4, 1, 0.4, 0.4]


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
    assert cells[:3] == ["2026", "2", "1"]
    assert cells[3] == f"{row['agotw']} · n/a"
    assert cells[4] == f"{row['cbs_national']} · n/a"
    # An earlier season carries a real rate.
    older = next(r for r in sp if r["season"] == 2025 and r["franchise"] == row["franchise"])
    fox, cbs = _denoms(nfl_fixture_raw, 2025, 2025)
    cells = app.eval_on_selector_all(
        "#nfl-view-special .nfl-breakdown tbody tr[data-season='2025'] > *",
        "els => els.map(e => e.textContent)",
    )
    assert cells[3] == _rate(older["agotw"], fox)
    assert cells[4] == _rate(older["cbs_national"], cbs)
    assert cells[1] == str(older["special"] + older["international_other"])


def test_hidden_table_one_row_per_bar(app: Page) -> None:
    vm = _vm(app)
    rows = app.locator("#nfl-view-special div.visually-hidden table tbody tr")
    assert rows.count() == len(vm["rows"])
    first = rows.first.locator("td").all_inner_texts()
    r0 = vm["rows"][0]
    assert first == [
        str(r0["counts"]["standalone"]),
        str(r0["counts"]["agotw"]),
        str(r0["counts"]["cbs_national"]),
        str(r0["counts"]["international_other"]),
        str(r0["total"]),
    ]
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
