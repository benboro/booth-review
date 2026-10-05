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
