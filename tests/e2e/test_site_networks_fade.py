"""SITE-65 (04.16 D-15..D-18): Networks obeys the Fade/Hide switch like every other
filter. In Fade the games on switched-off networks are drawn as faded, inert dots; in
Hide they are not drawn. Counts, facets, the summary, Bars and Butterfly never depend on
the switch. Synthetic fixture only."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from conftest import FIXTURE_GAMES
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

OpenApp = Callable[[Page, str], None]

FADE = '#dots-toggle [data-dots="fade"]'
HIDE = '#dots-toggle [data-dots="hide"]'

_TRACES_JS = (
    "() => document.getElementById('chart').data.map((t) =>"
    " ({meta: String(t.meta), x: t.x, customdata: t.customdata ?? null,"
    " size: t.marker?.size}))"
)


def _traces(page: Page) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = page.evaluate(_TRACES_JS)
    return result


def _view(page: Page) -> dict[str, Any]:
    result: dict[str, Any] = page.evaluate("() => window.__testHooks.getView()")
    return result


def _active_indices(page: Page) -> list[int]:
    return sorted(
        cd
        for t in _traces(page)
        if t["meta"].startswith(("family:", "unrated-active:"))
        for cd in (t["customdata"] or [])
        if cd is not None and cd < 12
    )


def _inert_total(page: Page) -> int:
    return sum(len(t["x"]) for t in _traces(page) if t["meta"].startswith("inert:"))


def _pill(page: Page, family: str) -> Any:
    return page.locator(f"#legend-chips button[data-family='{family}']")


def _route_checkbox(page: Page) -> None:
    page.click("#trigger-networks")
    page.wait_for_function("document.getElementById('pop-networks').matches(':popover-open')")
    page.uncheck("input[data-family-checkbox='fox']")
    page.wait_for_function("location.search.includes('networks=')")
    page.keyboard.press("Escape")


def _route_pill(page: Page) -> None:
    _pill(page, "fox").click()
    page.wait_for_function("location.search.includes('networks=')")


def _route_double_click(page: Page) -> None:
    _pill(page, "fox").dblclick()
    page.wait_for_function("window.__testHooks.getState().networks?.length === 1")


def _route_only(page: Page) -> None:
    page.click("#trigger-networks")
    page.wait_for_function("document.getElementById('pop-networks').matches(':popover-open')")
    page.locator(".check-item:has(input[data-family-checkbox='fox']) .only-btn").click()
    page.wait_for_function("window.__testHooks.getState().networks?.length === 1")
    page.keyboard.press("Escape")


ROUTES = [
    pytest.param(_route_checkbox, 15, id="checkbox"),
    pytest.param(_route_pill, 15, id="pill-click"),
    pytest.param(_route_double_click, 5, id="pill-double-click"),
    pytest.param(_route_only, 5, id="only-button"),
]


@pytest.mark.parametrize(("route", "passing"), ROUTES)
def test_each_networks_route_fades_in_fade_and_hides_in_hide(
    guarded_page: Page,
    open_app: OpenApp,
    route: Callable[[Page], None],
    passing: int,
) -> None:
    open_app(guarded_page, "")
    route(guarded_page)

    view = _view(guarded_page)
    assert view["visibleCount"] == FIXTURE_GAMES
    assert view["passingCount"] == passing
    active = _active_indices(guarded_page)
    passing_rated = set(view["passesFilters"])
    assert set(active) <= passing_rated
    rated_passing = [i for i in view["passesFilters"] if i < 12]
    assert active == sorted(rated_passing)
    assert _inert_total(guarded_page) == 12 - len(rated_passing)
    assert _inert_total(guarded_page) > 0

    guarded_page.click(HIDE)
    guarded_page.wait_for_function(
        "window.__testHooks.getView().visibleCount === window.__testHooks.getView().passingCount"
    )
    assert _inert_total(guarded_page) == 0

    guarded_page.click(FADE)
    guarded_page.wait_for_function(
        "window.__testHooks.getView().visibleCount === window.__testHooks.getView().n"
        " || window.__testHooks.getView().visibleCount === " + str(FIXTURE_GAMES)
    )
    assert _inert_total(guarded_page) == 12 - len(rated_passing)


def _family_sizes(page: Page) -> set[float]:
    return {t["size"] for t in _traces(page) if t["meta"].startswith("family:")}


def test_networks_only_size_follows_fade_and_hide(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, "?networks=net-b")
    assert _view(guarded_page)["enlargeDots"] is True
    assert _family_sizes(guarded_page) == {10}

    guarded_page.click(HIDE)
    guarded_page.wait_for_function("window.__testHooks.getView().enlargeDots === false")
    assert _family_sizes(guarded_page) == {6}

    guarded_page.click(FADE)
    guarded_page.wait_for_function("window.__testHooks.getView().enlargeDots === true")
    assert _family_sizes(guarded_page) == {10}

    for query in (
        "?networks=net-a,net-b,net-c,net-d",
        "?networks=net-a,net-b,net-c,net-d&dots=hide",
    ):
        open_app(guarded_page, query)
        assert _view(guarded_page)["enlargeDots"] is False
        assert _family_sizes(guarded_page) == {6}


_SNAPSHOT_JS = """
() => {
  const v = window.__testHooks.getView();
  return {
    passingCount: v.passingCount,
    passesFilters: Array.from(v.passesFilters),
    facets: JSON.stringify(v.facets),
    count: document.getElementById('summary-count').textContent,
    detail: document.getElementById('summary-detail').textContent,
    bars: JSON.stringify(window.__testHooks.getBarsModel()),
  };
}
"""


def _snapshot(page: Page, patch: dict[str, Any]) -> dict[str, Any]:
    page.evaluate(f"window.__testHooks.setState({json.dumps(patch)})")
    page.wait_for_function("(d) => window.__testHooks.getState().dots === d", arg=patch["dots"])
    result: dict[str, Any] = page.evaluate(_SNAPSHOT_JS)
    return result


@pytest.mark.parametrize("view", ["bars", "butterfly"])
@pytest.mark.parametrize("with_school", [False, True])
def test_fade_hide_never_changes_counts_facets_summary_or_bars(
    guarded_page: Page, open_app: OpenApp, view: str, with_school: bool
) -> None:
    open_app(guarded_page, "?school=northfield,lakeview" if view == "butterfly" else "")
    base: dict[str, Any] = {"networks": ["net-a", "net-b"], "view": view}
    if with_school:
        slug = guarded_page.evaluate("window.__testHooks.data.teamSlugs[0]")
        base["school"] = ["northfield", "lakeview"] if view == "butterfly" else [slug]
    elif view == "butterfly":
        base["school"] = ["northfield", "lakeview"]
    fade = _snapshot(guarded_page, {**base, "dots": "fade"})
    hide = _snapshot(guarded_page, {**base, "dots": "hide"})
    assert fade == hide
    single = _snapshot(guarded_page, {**base, "networks": ["net-b"], "dots": "fade"})
    single_hide = _snapshot(guarded_page, {**base, "networks": ["net-b"], "dots": "hide"})
    assert single == single_hide


def test_faded_off_network_dots_are_inert(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, "?networks=net-a")
    inert = guarded_page.evaluate(
        "() => document.getElementById('chart')._fullData"
        ".filter((t) => /^(unrated-)?inert:/.test(String(t.meta)))"
        ".map((t) => ({meta: String(t.meta), hoverinfo: t.hoverinfo, cd: t.customdata ?? null}))"
    )
    assert inert
    for t in inert:
        assert t["hoverinfo"] == "skip", t["meta"]
        assert t["cd"] is None, t["meta"]
