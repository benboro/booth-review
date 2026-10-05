"""SITE-47 (04.10 D-13..D-15): with any filter active, filter-passing dots draw at
the announcer-selected size (10px); filtered-out dots and the unfiltered chart stay
6px; fade tiers, trace count and the hover ring follow."""

from __future__ import annotations

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


def test_hide_mode_uses_the_same_sizes(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, HIDE)
    assert {t["size"] for t in _family(guarded_page)} == {10}
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
    for query in ("", FILTER, HIDE, PERSON, BOTH):
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
    for query in (FILTER, BOTH, HIDE):
        open_app(guarded_page, query)
        fam = _family(guarded_page)
        assert {t["line"]["width"] for t in fam} == {1}, query
        assert {t["line"]["color"] for t in fam} == {"#000000"}, query
        assert {t["line"]["width"] for t in _inert(guarded_page)} == {0}, query


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
# dots (out-of-range seasons are already off the axis); sizing reads sizeFilterActive.
# Fixture facts: northfield has games in 2025; 2025-2026 keeps one dale-harlow game.
DATE_SEASONS = "?axis=date&seasons=2025-2026"
DATE_SCHOOL = "?axis=date&seasons=2025-2026&school=northfield"
DATE_PERSON_SEASONS = "?axis=date&seasons=2025-2026&people=dale-harlow"
DATE_PERSON = "?axis=date&people=dale-harlow"


@pytest.mark.parametrize(
    ("query", "filter_active", "size_active"),
    [
        (DATE_SEASONS, True, False),
        (DATE_SEASONS + "&dots=hide", True, False),
        (DATE_SEASONS + "&slot=noon,afternoon", True, True),
        ("?axis=date&slot=noon,afternoon", True, True),
        ("?seasons=2025-2026", True, True),
        ("?axis=excitement&seasons=2025-2026", True, True),
        ("", False, False),
        ("?axis=date", False, False),
    ],
)
def test_size_filter_flag_matrix(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    query: str,
    filter_active: bool,
    size_active: bool,
) -> None:
    open_app(guarded_page, query)
    view = guarded_page.evaluate(
        "() => ({f: window.__testHooks.getView().filterActive,"
        " s: window.__testHooks.getView().sizeFilterActive})"
    )
    assert view == {"f": filter_active, "s": size_active}


def test_date_seasons_only_summary_still_reads_n_of_m(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, DATE_SEASONS)
    summary = guarded_page.evaluate("() => window.__testHooks.getView().summary")
    total = guarded_page.evaluate("() => window.__testHooks.data.n")
    assert summary["kind"] == "matches"
    assert summary["of"] == total
    assert f"of {total}" in guarded_page.inner_text("#summary")


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
