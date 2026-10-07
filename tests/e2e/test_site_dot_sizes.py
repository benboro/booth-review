"""SITE-60/SITE-61 (04.16 D-01..D-09, amending 04.10 D-13..D-15): passing dots draw at
10px with the black outline only when a faded dot is actually drawn (or Networks alone
holds 1-3 families); otherwise every dot is 6px. Fade tiers, trace count and the hover
ring follow the drawn size."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page
from test_site_chart import _RING_VISIBLE, _assert_ring_on, _hover_dot, _ring_box

pytestmark = pytest.mark.e2e

FILTER = "?slot=noon,afternoon"
PERSON = "?people=dale-harlow"
BOTH = "?people=dale-harlow&slot=noon,afternoon"
HIDE = "?slot=noon,afternoon&dots=hide"


def _info(page: Page) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = page.evaluate(
        "() => document.getElementById('chart').data.map(t => ({meta: String(t.meta),"
        " size: t.marker.size, opacity: t.marker.opacity, hoverinfo: t.hoverinfo,"
        " line: t.marker.line,"
        " n: (t.x || []).length}))"
    )
    return result


def _family(page: Page) -> list[dict[str, Any]]:
    return [t for t in _info(page) if t["meta"].startswith("family:")]


def _inert(page: Page) -> list[dict[str, Any]]:
    return [t for t in _info(page) if t["meta"].startswith("inert:")]


def test_no_filter_every_dot_is_six(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    assert guarded_page.evaluate("() => window.__testHooks.getView().filterActive") is False
    assert {t["size"] for t in _family(guarded_page) + _inert(guarded_page)} == {6}


def test_filter_passing_dots_are_ten_and_inert_stay_six(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, FILTER)
    assert guarded_page.evaluate("() => window.__testHooks.getView().filterActive") is True
    fam, inert = _family(guarded_page), _inert(guarded_page)
    assert fam
    assert {t["size"] for t in fam} == {10}
    assert {t["size"] for t in inert} == {6}
    # Tiers are unchanged: one opacity per kind, the active tier above the inert tier.
    assert len({t["opacity"] for t in fam}) == 1
    assert len({t["opacity"] for t in inert}) == 1
    assert fam[0]["opacity"] > inert[0]["opacity"]


@pytest.mark.parametrize("query", [HIDE, "?school=northfield&dots=hide"])
def test_hide_mode_keeps_normal_size(
    guarded_page: Page, open_app: Callable[[Page, str], None], query: str
) -> None:
    open_app(guarded_page, query)
    fam = _family(guarded_page)
    assert {t["size"] for t in fam} == {6}
    assert {t["line"]["width"] for t in fam} == {0}
    assert sum(t["n"] for t in _inert(guarded_page)) == 0


def test_person_without_filter_keeps_six(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, PERSON)
    fam = _family(guarded_page)
    assert {t["size"] for t in fam} == {6}
    highlight = [t for t in _info(guarded_page) if t["meta"] == "highlight"]
    assert highlight
    sizes = {
        s for t in highlight for s in (t["size"] if isinstance(t["size"], list) else [t["size"]])
    }
    assert sizes.issubset({10, 12, 15})


def test_person_with_filter_exercises_all_three_tiers(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, BOTH)
    info = _info(guarded_page)
    fam = [t for t in info if t["meta"].startswith("family:")]
    inert = [t for t in info if t["meta"].startswith("inert:")]
    highlight = [t for t in info if t["meta"] == "highlight"]
    assert sum(t["n"] for t in fam) >= 1
    assert sum(t["n"] for t in highlight) >= 1
    assert {t["size"] for t in fam} == {10}
    assert {t["hoverinfo"] for t in fam} == {"skip"}
    assert {t["size"] for t in inert} == {6}
    assert fam[0]["opacity"] < 1
    sizes = {
        s for t in highlight for s in (t["size"] if isinstance(t["size"], list) else [t["size"]])
    }
    assert sizes.issubset({10, 12, 15})


def test_trace_count_is_constant_across_states(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    counts = []
    for query in (
        "",
        FILTER,
        HIDE,
        PERSON,
        BOTH,
        "?school=northfield&dots=hide",
        "?networks=net-b",
        "?networks=net-a,net-b,net-c,net-d",
    ):
        open_app(guarded_page, query)
        counts.append(guarded_page.evaluate("() => document.getElementById('chart').data.length"))
    assert len(set(counts)) == 1, counts


def test_hover_ring_grows_four_pixels_with_the_dot(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    _hover_dot(guarded_page, 0)
    guarded_page.wait_for_selector(_RING_VISIBLE, timeout=3000)
    small = _ring_box(guarded_page)["width"]

    open_app(guarded_page, FILTER)
    point = _hover_dot(guarded_page, 0)
    guarded_page.wait_for_selector(_RING_VISIBLE, timeout=3000)
    big = _assert_ring_on(guarded_page, 0, point)["width"]
    assert abs(big - (small + 4)) <= 0.5, (small, big)


def test_enlarged_dots_get_a_black_outline_only_when_filtered(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    assert {t["line"]["width"] for t in _family(guarded_page)} == {0}
    for query in (FILTER, BOTH):
        open_app(guarded_page, query)
        fam = _family(guarded_page)
        assert {t["line"]["width"] for t in fam} == {1}, query
        assert {t["line"]["color"] for t in fam} == {"#000000"}, query
        assert {t["line"]["width"] for t in _inert(guarded_page)} == {0}, query
    open_app(guarded_page, HIDE)
    assert {t["line"]["width"] for t in _family(guarded_page)} == {0}


def test_highlight_keeps_accent_border(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, BOTH)
    accent = guarded_page.evaluate(
        "() => document.getElementById('chart').data"
        ".find(t => t.meta === 'highlight').marker.line.color"
    )
    assert accent in ("#111827", "#E5E7EB")


# SITE-50 (04.12 D-05..D-07): on the Date axis a seasons-only filter must not enlarge
# dots (out-of-range seasons are already off the axis); 04.16 D-03 keeps that carve-out
# and sizing reads enlargeDots (a drawn faded dot, or Networks alone with 1-3 families).
# Fixture facts: northfield has games in 2025; 2025-2026 keeps one dale-harlow game.
DATE_SEASONS = "?axis=date&seasons=2025-2026"
DATE_SCHOOL = "?axis=date&seasons=2025-2026&school=northfield"
DATE_PERSON_SEASONS = "?axis=date&seasons=2025-2026&people=dale-harlow"
DATE_PERSON = "?axis=date&people=dale-harlow"


# (query, filterActive, enlargeDots); the UI-SPEC outcome table, one row per case.
MATRIX = [
    ("", False, False),
    ("?axis=date", False, False),
    (DATE_SEASONS, True, False),
    (DATE_SEASONS + "&dots=hide", True, False),
    (DATE_SEASONS + "&slot=noon,afternoon", True, True),
    ("?axis=date&slot=noon,afternoon", True, True),
    ("?seasons=2025-2026", True, True),
    ("?axis=excitement&seasons=2025-2026", True, True),
    ("?slot=noon,afternoon&dots=hide", True, False),
    ("?school=northfield", True, True),
    ("?school=northfield&dots=hide", True, False),
    ("?game=summit-bowl", True, True),
    ("?networks=net-b", True, True),
    ("?networks=net-b,net-c,net-d", True, True),
    ("?networks=net-a,net-e,net-b,net-c", True, True),
    ("?networks=net-a,net-b,net-c,net-d", True, False),
    ("?networks=net-b&slot=afternoon,prime", True, False),
    ("?networks=net-b&slot=prime", True, True),
    (DATE_SEASONS + "&networks=net-b", True, True),
    (DATE_SEASONS + "&networks=net-a,net-b,net-c,net-d", True, False),
    ("?seasons=2025-2026&networks=net-a,net-b,net-c,net-d", True, True),
    ("?people=dale-harlow", False, False),
    ("?slot=noon,afternoon,prime,late", True, True),
]


@pytest.mark.parametrize(("query", "filter_active", "enlarge"), MATRIX)
def test_enlarge_flag_matrix(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    query: str,
    filter_active: bool,
    enlarge: bool,
) -> None:
    open_app(guarded_page, query)
    view = guarded_page.evaluate(
        "() => ({f: window.__testHooks.getView().filterActive,"
        " e: window.__testHooks.getView().enlargeDots})"
    )
    assert view == {"f": filter_active, "e": enlarge}


@pytest.mark.parametrize(("query", "filter_active", "enlarge"), MATRIX)
def test_family_traces_follow_the_flag(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    query: str,
    filter_active: bool,
    enlarge: bool,
) -> None:
    open_app(guarded_page, query)
    fam = _family(guarded_page)
    assert fam
    assert {t["size"] for t in fam} == {10 if enlarge else 6}, query
    assert {t["line"]["width"] for t in fam} == {1 if enlarge else 0}, query
    if enlarge:
        assert {t["line"]["color"] for t in fam} == {"#000000"}, query
    assert {t["size"] for t in _inert(guarded_page)} <= {6}, query
    assert {t["line"]["width"] for t in _inert(guarded_page)} <= {0}, query


def test_drawn_faded_counts_faded_dots(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "?school=northfield")
    assert guarded_page.evaluate("() => window.__testHooks.getView().drawnFaded") > 0
    open_app(guarded_page, "?school=northfield&dots=hide")
    assert guarded_page.evaluate("() => window.__testHooks.getView().drawnFaded") == 0
    open_app(guarded_page, "")
    assert guarded_page.evaluate("() => window.__testHooks.getView().drawnFaded") == 0


def _serve(page: Page, raw: dict[str, Any]) -> None:
    page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))


def test_every_slot_checked_with_no_null_slot_fades_nothing(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    raw = copy.deepcopy(fixture_raw)
    raw["telecasts"]["time_slot"][3] = "late"
    _serve(guarded_page, raw)
    open_app(guarded_page, "?slot=noon,afternoon,prime,late")
    view = guarded_page.evaluate(
        "() => ({e: window.__testHooks.getView().enlargeDots,"
        " f: window.__testHooks.getView().drawnFaded})"
    )
    assert view == {"e": False, "f": 0}
    assert {t["size"] for t in _family(guarded_page)} == {6}


@pytest.mark.parametrize(
    ("query", "enlarge"),
    [
        # Other off, four of five families on: the "Networks · 31" screenshot case.
        ("?networks=net-a,net-e,net-b,net-c,net-f", False),
        ("?networks=net-a,net-b,net-f", True),
    ],
)
def test_five_family_networks_only(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
    query: str,
    enlarge: bool,
) -> None:
    raw = copy.deepcopy(fixture_raw)
    raw["lookups"]["networks"].append({"id": "net-f", "name": "Fifth Channel", "family": "cbs"})
    raw["telecasts"]["network"][11] = len(raw["lookups"]["networks"]) - 1
    _serve(guarded_page, raw)
    open_app(guarded_page, query)
    assert guarded_page.evaluate("() => window.__testHooks.getView().enlargeDots") is enlarge
    fam = _family(guarded_page)
    assert {t["size"] for t in fam} == {10 if enlarge else 6}
    assert {t["line"]["width"] for t in fam} == {1 if enlarge else 0}


def test_date_seasons_only_summary_still_reads_n_of_m(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, DATE_SEASONS)
    summary = guarded_page.evaluate("() => window.__testHooks.getView().summary")
    total = guarded_page.evaluate("() => window.__testHooks.data.n")
    assert summary["kind"] == "matches"
    # 04.13 D-07: the summary counts games (rated + unrated); `of` became `count`/`rated`
    # 2025-2026 keeps 11 of the 20 fixture games, 8 of them rated (04.13 D-07: counts are games)
    assert (summary["count"], summary["rated"]) == (11, 8)
    assert total == 20
    assert "8 rated of 11 games" in guarded_page.inner_text("#summary")


@pytest.mark.parametrize("dots", ["", "&dots=hide"])
def test_date_seasons_only_dots_stay_six(
    guarded_page: Page, open_app: Callable[[Page, str], None], dots: str
) -> None:
    open_app(guarded_page, DATE_SEASONS + dots)
    fam = _family(guarded_page)
    assert fam
    assert {t["size"] for t in fam} == {6}
    assert {t["line"]["width"] for t in fam} == {0}
    assert {t["size"] for t in _inert(guarded_page)} <= {6}


def test_date_seasons_plus_school_dots_are_ten(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, DATE_SCHOOL)
    fam = _family(guarded_page)
    assert sum(t["n"] for t in fam) > 0
    assert {t["size"] for t in fam} == {10}
    assert {t["line"]["width"] for t in fam} == {1}


@pytest.mark.parametrize("query", ["?seasons=2025-2026", "?axis=excitement&seasons=2025-2026"])
def test_spread_and_excitement_seasons_only_dots_are_ten(
    guarded_page: Page, open_app: Callable[[Page, str], None], query: str
) -> None:
    open_app(guarded_page, query)
    fam = _family(guarded_page)
    assert fam
    assert {t["size"] for t in fam} == {10}
    assert {t["line"]["width"] for t in fam} == {1}


def test_date_announcer_with_seasons_only_others_stay_six(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, DATE_PERSON)
    base_opacity = {t["opacity"] for t in _family(guarded_page)}
    open_app(guarded_page, DATE_PERSON_SEASONS)
    fam = _family(guarded_page)
    assert sum(t["n"] for t in fam) > 0
    assert {t["size"] for t in fam} == {6}
    assert {t["line"]["width"] for t in fam} == {0}
    assert {t["opacity"] for t in fam} == base_opacity
    assert {t["hoverinfo"] for t in fam} == {"skip"}
    highlight = [t for t in _info(guarded_page) if t["meta"] == "highlight"]
    assert highlight
    sizes = {
        s for t in highlight for s in (t["size"] if isinstance(t["size"], list) else [t["size"]])
    }
    assert sizes
    assert sizes <= {10, 12, 15}


def test_date_to_spread_with_seasons_grows_dots(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, DATE_SCHOOL)
    expected_traces = len(_info(guarded_page))
    open_app(guarded_page, DATE_SEASONS)
    assert len(_info(guarded_page)) == expected_traces
    assert {t["size"] for t in _family(guarded_page)} == {6}
    guarded_page.evaluate("() => window.__testHooks.setState({axis: 'spread'})")
    guarded_page.wait_for_function(
        "() => document.getElementById('chart').data.some("
        "t => String(t.meta).startsWith('family:') && t.marker.size === 10)"
    )
    assert {t["size"] for t in _family(guarded_page)} == {10}
    assert len(_info(guarded_page)) == expected_traces


def _sizes(trace: dict[str, Any]) -> set[int]:
    size = trace["size"]
    return set(size) if isinstance(size, list) else {size}


def test_person_tiers_follow_the_switch(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """04.16 D-08/D-09: the selected person's games keep their shapes and outline; the
    others follow the enlarge switch at the same reduced opacity."""
    open_app(guarded_page, BOTH)
    on = _info(guarded_page)
    open_app(guarded_page, "?people=dale-harlow&school=northfield&dots=hide")
    off = _info(guarded_page)
    on_fam = [t for t in on if t["meta"].startswith("family:")]
    off_fam = [t for t in off if t["meta"].startswith("family:")]
    assert {t["size"] for t in on_fam} == {10}
    assert {t["line"]["width"] for t in on_fam} == {1}
    assert {t["size"] for t in off_fam} == {6}
    assert {t["line"]["width"] for t in off_fam} == {0}
    tier = guarded_page.evaluate(
        "async () => (await import('./modules/chart.js')).DOT_OPACITY.activeUnderPerson"
    )
    assert {t["opacity"] for t in on_fam} == {tier}
    assert {t["opacity"] for t in off_fam} == {tier}
    colors = []
    for info in (on, off):
        highlight = [t for t in info if t["meta"] == "highlight"]
        assert highlight
        assert all(_sizes(t) <= {10, 12, 15} for t in highlight)
        colors.append({t["line"]["color"] for t in highlight})
    assert colors[0] == colors[1]


_WAIT_TWO_FRAMES = "() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"


def _relayout(page: Page, js: str) -> None:
    page.evaluate(
        "async (js) => { const gd = document.getElementById('chart');"
        " const L = gd._fullLayout; const f = new Function('gd', 'L', js);"
        " await window.Plotly.relayout(gd, f(gd, L)); }",
        js,
    )


@pytest.mark.parametrize("query", ["?school=northfield", "?networks=net-a,net-b,net-c,net-d"])
def test_zoom_and_pan_never_change_sizes(
    guarded_page: Page, open_app: Callable[[Page, str], None], query: str
) -> None:
    """04.16 D-02: the faded count is over the whole plot, so zooming never resizes."""

    def snapshot() -> tuple[Any, ...]:
        view = guarded_page.evaluate(
            "() => ({e: window.__testHooks.getView().enlargeDots,"
            " d: window.__testHooks.getView().drawnFaded})"
        )
        return (view["e"], view["d"], sorted((t["meta"], t["size"]) for t in _family(guarded_page)))

    open_app(guarded_page, query)
    first = snapshot()
    narrow = (
        "const x = L.xaxis.range, y = L.yaxis.range;"
        " const cx = (x[0] + x[1]) / 2, cy = (y[0] + y[1]) / 2;"
        " const hx = (x[1] - x[0]) / 4, hy = (y[1] - y[0]) / 4;"
        " return {'xaxis.range': [cx - hx, cx + hx], 'yaxis.range': [cy - hy, cy + hy]};"
    )
    pan = (
        "const x = L.xaxis.range, y = L.yaxis.range;"
        " const dx = (x[1] - x[0]) / 8, dy = (y[1] - y[0]) / 8;"
        " return {'xaxis.range': [x[0] + dx, x[1] + dx], 'yaxis.range': [y[0] + dy, y[1] + dy]};"
    )
    reset = "return {'xaxis.autorange': true, 'yaxis.autorange': true};"
    for step in (narrow, pan, reset):
        _relayout(guarded_page, step)
        # plotly_relayout handlers run before the relayout promise resolves; two frames
        # then flush any re-render they queue, so a regression cannot slip past a sleep.
        guarded_page.evaluate(_WAIT_TWO_FRAMES)
        assert snapshot() == first, query


def test_band_passing_markers_follow_the_switch(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    def band(page: Page) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = page.evaluate(
            "() => document.getElementById('chart').data.filter(t =>"
            " String(t.meta).startsWith('unrated-')).map(t => ({meta: String(t.meta),"
            " n: (t.x || []).length, size: t.marker.size, color: t.marker.color,"
            " line: t.marker.line}))"
        )
        return out

    open_app(guarded_page, "?school=northfield")
    traces = band(guarded_page)
    active = [t for t in traces if t["meta"].startswith("unrated-active:") and t["n"]]
    assert active
    family_color = {
        t["meta"].split(":")[1]: t["line"]["color"]
        for t in traces
        if t["meta"].startswith("unrated-inert:")
    }
    ring_fill = next(t["color"] for t in traces if t["meta"].startswith("unrated-inert:"))
    for t in active:
        assert t["size"] == 10
        assert t["line"]["width"] == 1
        assert t["color"] != ring_fill, t
        assert t["color"] == family_color[t["meta"].split(":")[1]], t

    open_app(guarded_page, "?school=northfield&dots=hide")
    rings = [t for t in band(guarded_page) if t["meta"].startswith("unrated-active:") and t["n"]]
    assert rings
    for t in rings:
        assert t["size"] == 6
        assert t["color"] == ring_fill, t

    open_app(guarded_page, "?school=northfield&dots=hide&y=excitement")
    filled = [t for t in band(guarded_page) if t["meta"].startswith("unrated-active:") and t["n"]]
    for t in filled:
        assert t["size"] == 6
        assert t["line"]["width"] == 0
        assert t["color"] != ring_fill, t
