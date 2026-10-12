"""999.5-11: the CFB | NFL switch, sport resolution, state handoff and request separation."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page, Route

pytestmark = pytest.mark.e2e


def _track(page: Page) -> list[str]:
    urls: list[str] = []
    page.on("request", lambda r: urls.append(r.url))
    return urls


def _count(urls: list[str], name: str) -> int:
    return sum(1 for u in urls if name in u.split("?")[0])


def _click(page: Page, sport: str) -> None:
    page.click(f'#sport-switch button[data-sport="{sport}"]')


def _pressed(page: Page, sport: str) -> str | None:
    return page.get_attribute(f'#sport-switch button[data-sport="{sport}"]', "aria-pressed")


def test_cfb_load_never_requests_nfl_data(
    nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None]
) -> None:
    urls = _track(nfl_guarded_page)
    open_flagon_cfb(nfl_guarded_page)
    assert _count(urls, "nfl-data.json") == 0
    assert nfl_guarded_page.evaluate("location.search") == ""
    assert _pressed(nfl_guarded_page, "cfb") == "true"


def test_click_nfl_mounts_and_sets_url_title(
    nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    urls = _track(page)
    open_flagon_cfb(page)
    _click(page, "nfl")
    page.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.ready === true")
    assert _pressed(page, "nfl") == "true"
    assert _pressed(page, "cfb") == "false"
    assert page.inner_text("#sport-status") == "Showing NFL games."
    assert "NFL" in page.title()
    assert page.evaluate("location.search") == "?sport=nfl"
    assert _count(urls, "nfl-data.json") == 1


def test_direct_nfl_never_requests_site_data(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    urls = _track(page)
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    open_nfl_app(page)
    assert _count(urls, "nfl-data.json") == 1
    assert _count(urls, "site-data.json") == 0
    assert _pressed(page, "nfl") == "true"
    assert errors == []


def test_cfb_state_round_trip(nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None]) -> None:
    page = nfl_guarded_page
    open_flagon_cfb(page)
    page.evaluate("window.__testHooks.setState({ view: 'bars' })")
    state = page.evaluate("window.__testHooks.getState()")
    search = page.evaluate("location.search")
    assert "view=bars" in search
    _click(page, "nfl")
    page.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.ready === true")
    _click(page, "cfb")
    page.wait_for_function("location.search === " + repr(search))
    assert page.evaluate("window.__testHooks.getState()") == state
    assert "NFL" not in page.title()
    assert page.evaluate("document.body.dataset.sport") == "cfb"


def test_nfl_state_kept_across_cfb_detour(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    open_nfl_app(page)
    page.evaluate("window.__nflTestHooks.setState({ view: 'fox' })")
    _click(page, "cfb")
    page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    assert "sport=nfl" not in page.evaluate("location.search")
    _click(page, "nfl")
    page.wait_for_function("location.search.includes('sport=nfl')")
    assert page.evaluate("window.__nflTestHooks.getState().view") == "fox"
    assert "view=fox" in page.evaluate("location.search")


def test_flag_off_ignores_sport_param(guarded_page: Page, site_url: str) -> None:
    page = guarded_page
    urls = _track(page)
    page.goto(f"{site_url}/index.html?sport=nfl")
    page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    assert page.evaluate("location.search") == ""
    assert page.locator("#sport-switch").count() == 0
    assert _count(urls, "nfl-data.json") == 0
    page.goto(f"{site_url}/index.html?sport=nfl&view=bars")
    page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    assert page.evaluate("location.search") == "?view=bars"


def _bar_height(page: Page) -> float:
    return float(page.evaluate("document.getElementById('topbar').getBoundingClientRect().height"))


def test_mobile_switch_size_and_topbar_height(
    nfl_mobile_page: Page,
    open_flagon_cfb: Callable[..., None],
    browser: object,
    site_url: str,
) -> None:
    page = nfl_mobile_page
    open_flagon_cfb(page)
    for sport in ("cfb", "nfl"):
        box = page.locator(f'#sport-switch button[data-sport="{sport}"]').bounding_box()
        assert box is not None
        assert box["height"] >= 44
        assert box["width"] >= 44
    on_height = _bar_height(page)
    ctx = browser.new_context(  # type: ignore[attr-defined]
        viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True
    )
    try:
        off = ctx.new_page()
        off.goto(f"{site_url}/index.html")
        off.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
        assert abs(_bar_height(off) - on_height) <= 1
    finally:
        ctx.close()


_RECT = "document.querySelector('%s').getBoundingClientRect().%s"


def _assert_layout_stable(page: Page, open_cfb: Callable[..., None]) -> None:
    """Top bar, toolbar height and chart top do not move when the sport changes (SITE-20)."""
    open_cfb(page)
    bar = _bar_height(page)
    cfb_toolbar = page.evaluate(_RECT % ("#toolbar", "height"))
    cfb_chart_top = page.evaluate(_RECT % ("#chart-area", "top"))
    _click(page, "nfl")
    page.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.ready === true")
    assert abs(_bar_height(page) - bar) <= 1
    assert abs(page.evaluate(_RECT % ("#nfl-toolbar", "height")) - cfb_toolbar) <= 1
    bar_bottom = page.evaluate(_RECT % ("#nfl-selection-bar", "bottom"))
    assert abs(page.evaluate(_RECT % ("#nfl-chart-area", "top")) - bar_bottom) <= 1
    assert abs(page.evaluate(_RECT % ("#nfl-chart-area", "top")) - cfb_chart_top) <= 1
    assert page.evaluate(_RECT % ("#chart-area", "height")) == 0


def test_switching_keeps_topbar_toolbar_and_chart_top(
    nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None]
) -> None:
    _assert_layout_stable(nfl_guarded_page, open_flagon_cfb)


def test_switching_keeps_layout_on_mobile(
    nfl_mobile_page: Page, open_flagon_cfb: Callable[..., None]
) -> None:
    _assert_layout_stable(nfl_mobile_page, open_flagon_cfb)


def test_cfb_starts_cleanly_after_opening_on_nfl_url(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    """Open on an NFL query with NFL-only params, then switch to CFB (startCfb decodes it)."""
    page = nfl_guarded_page
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    nfl_query = (
        "sport=nfl&view=fox&team=f-gulls&people=p00&cat=agotw&seasons=2025-2025&m=excitement"
    )
    open_nfl_app(page, "?" + nfl_query)
    _click(page, "cfb")
    page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    search = page.evaluate("location.search")
    params = ("sport=", "team=", "people=", "cat=", "seasons=", "fseason=", "m=", "adj=", "ay=")
    for param in params:
        assert param not in search, search
    state = page.evaluate("window.__testHooks.getState()")
    assert "f-gulls" not in str(state)
    assert "p00" not in str(state)
    assert page.locator("#chart").is_visible()
    assert errors == []


def test_nfl_load_error_then_cfb_still_loads(
    nfl_guarded_page: Page, nfl_site_url: str, open_flagon_cfb: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    page.route("**/nfl-data.json*", lambda route: route.fulfill(status=500, body="no"))
    open_flagon_cfb(page)
    _click(page, "nfl")
    page.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.failed === true")
    assert _pressed(page, "nfl") == "true"
    _click(page, "cfb")
    assert _pressed(page, "cfb") == "true"
    assert page.evaluate("window.__testHooks.ready") is True
    assert page.locator("#chart").is_visible()


def _wait_nfl_ready(page: Page) -> None:
    page.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.ready === true")


def _settle(page: Page) -> None:
    """Let CFB's 150 ms resize debounce run out, so a stray CFB render would have fired."""
    page.wait_for_timeout(400)


def _open_nfl_from_cfb(
    page: Page, open_flagon_cfb: Callable[..., None], query: str
) -> tuple[str, str]:
    """Open CFB at `query`, switch to NFL and change its state; returns (cfb_search, nfl_search)."""
    open_flagon_cfb(page, query)
    cfb_search = page.evaluate("location.search")
    _click(page, "nfl")
    _wait_nfl_ready(page)
    page.evaluate("window.__nflTestHooks.setState({ view: 'fox', metric: 'excitement' })")
    nfl_search = page.evaluate("location.search")
    assert nfl_search.startswith("?sport=nfl") and "view=fox" in nfl_search
    return cfb_search, nfl_search


def test_cfb_listeners_never_rewrite_the_nfl_url(
    nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None]
) -> None:
    """JS-CR-01: CFB's media and resize listeners stay quiet while NFL is shown.

    CFB is left on Butterfly, whose resize handler re-renders at any width.
    """
    page = nfl_guarded_page
    cfb_search, nfl_search = _open_nfl_from_cfb(page, open_flagon_cfb, "?view=butterfly")
    nfl_state = page.evaluate("window.__nflTestHooks.getState()")
    page.emulate_media(color_scheme="dark")
    _settle(page)
    assert page.evaluate("location.search") == nfl_search
    page.set_viewport_size({"width": 600, "height": 800})  # across 640px
    _settle(page)
    assert page.evaluate("location.search") == nfl_search
    page.set_viewport_size({"width": 1100, "height": 800})  # back across, then a plain resize
    _settle(page)
    page.set_viewport_size({"width": 1000, "height": 800})
    _settle(page)
    assert page.evaluate("location.search") == nfl_search
    assert page.evaluate("window.__nflTestHooks.getState()") == nfl_state
    assert page.evaluate("document.body.dataset.sport") == "nfl"
    _click(page, "cfb")
    page.wait_for_function("location.search === " + repr(cfb_search))
    assert page.evaluate("window.__testHooks.getState().view") == "butterfly"


def test_cfb_scatter_stays_quiet_under_nfl_on_a_theme_change(
    nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None]
) -> None:
    """JS-CR-01 with CFB left on its scatter: an OS light/dark flip under NFL keeps
    the NFL URL and state, and CFB comes back as it was left."""
    page = nfl_guarded_page
    cfb_search, nfl_search = _open_nfl_from_cfb(page, open_flagon_cfb, "")
    nfl_state = page.evaluate("window.__nflTestHooks.getState()")
    page.emulate_media(color_scheme="dark")
    _settle(page)
    assert page.evaluate("location.search") == nfl_search
    page.emulate_media(color_scheme="light")
    _settle(page)
    assert page.evaluate("location.search") == nfl_search
    assert page.evaluate("window.__nflTestHooks.getState()") == nfl_state
    _click(page, "cfb")
    page.wait_for_function("location.search === " + repr(cfb_search))
    assert page.locator("#chart").is_visible()


def test_cfb_url_params_never_leak_into_nfl(
    nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None], open_nfl_app: Callable[..., None]
) -> None:
    """JS-CR-02: a CFB link's shared params (seasons, people, y, dots) stay on the CFB side."""
    page = nfl_guarded_page
    open_nfl_app(page)
    default_state = page.evaluate("window.__nflTestHooks.getState()")
    open_flagon_cfb(page, "?seasons=2025-2025&people=p00&y=excitement&dots=hide")
    _click(page, "nfl")
    _wait_nfl_ready(page)
    assert page.evaluate("location.search") == "?sport=nfl"
    assert page.evaluate("window.__nflTestHooks.getState()") == default_state


def test_switching_back_during_the_nfl_import_keeps_cfb(
    nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None]
) -> None:
    """JS-WR-01: a CFB click while the NFL module loads wins; NFL never mounts behind it."""
    page = nfl_guarded_page
    open_flagon_cfb(page)
    cfb_search = page.evaluate("location.search")
    credit = page.inner_text("#site-footer .credit-line")
    held: list[Route] = []
    page.route("**/sports/nfl/index.js", lambda route: held.append(route))
    urls = _track(page)
    with page.expect_request("**/sports/nfl/index.js"):
        _click(page, "nfl")
    _click(page, "cfb")
    page.wait_for_function("document.body.dataset.sport === 'cfb'")
    assert len(held) == 1
    page.unroute("**/sports/nfl/index.js")
    held[0].continue_()
    page.wait_for_load_state("networkidle")
    _settle(page)
    assert page.evaluate("location.search") == cfb_search
    assert page.inner_text("#site-footer .credit-line") == credit
    assert _count(urls, "nfl-data.json") == 0
    assert _pressed(page, "cfb") == "true"
    # A later NFL click still mounts normally.
    _click(page, "nfl")
    _wait_nfl_ready(page)
    assert page.evaluate("location.search") == "?sport=nfl"


def _open_with_failed_nfl(page: Page, nfl_site_url: str, opened_on: str) -> str:
    """Open the page so the NFL import runs (and fails); returns the expected NFL query."""
    if opened_on == "nfl":
        page.goto(f"{nfl_site_url}/index.html?sport=nfl&view=fox")
        expected = "?sport=nfl&view=fox"
    else:
        page.goto(f"{nfl_site_url}/index.html")
        page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
        _click(page, "nfl")
        expected = "?sport=nfl"
    page.wait_for_selector("#sport-load-error", state="visible")
    return expected


@pytest.mark.parametrize("opened_on", ["cfb", "nfl"])
@pytest.mark.parametrize("module", ["index.js", "state.js", "views/scatter.js"])
def test_nfl_module_failure_offers_a_reload_that_keeps_nfl(
    nfl_guarded_page: Page, nfl_site_url: str, opened_on: str, module: str
) -> None:
    """JS-WR-02, iter-2 WR-03 and IN-02: any failed NFL module, the entry or one it
    imports, shows a note with a Reload button in NFL's place, never a blank page.
    The URL stays NFL (a reload or a shared link opens NFL), and the reload's
    fresh document mounts NFL once the module loads."""
    page = nfl_guarded_page
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    pattern = f"**/sports/nfl/{module}"
    page.route(pattern, lambda route: route.abort())
    expected = _open_with_failed_nfl(page, nfl_site_url, opened_on)
    banner = page.locator("#sport-load-error")
    assert banner.get_attribute("role") == "alert"
    reload = banner.get_by_role("button", name="Reload page")
    assert reload.is_visible()
    assert page.evaluate("document.body.dataset.sport") == "nfl"
    assert _pressed(page, "nfl") == "true"
    assert page.evaluate("location.search") == expected
    _settle(page)
    assert page.evaluate("location.search") == expected
    assert errors == []
    page.unroute(pattern)
    with page.expect_navigation():
        reload.click()
    _wait_nfl_ready(page)
    search = page.evaluate("location.search")
    assert search.startswith("?sport=nfl")
    if opened_on == "nfl":
        assert page.evaluate("window.__nflTestHooks.getState().view") == "fox"
    assert page.locator("#sport-load-error").count() == 0
    assert errors == []


def test_the_failure_note_leaves_with_nfl_and_cfb_keeps_its_url(
    nfl_guarded_page: Page, nfl_site_url: str
) -> None:
    """IN-01: the note belongs to NFL's place only. Going back to CFB removes it
    and restores CFB's URL; it never sits in the CFB chart area."""
    page = nfl_guarded_page
    page.route("**/sports/nfl/state.js", lambda route: route.abort())
    page.goto(f"{nfl_site_url}/index.html?view=butterfly")
    page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    cfb_search = page.evaluate("location.search")
    _click(page, "nfl")
    page.wait_for_selector("#sport-load-error", state="visible")
    _click(page, "cfb")
    page.wait_for_function("location.search === " + repr(cfb_search))
    assert page.locator("#sport-load-error").count() == 0
    assert page.locator("#chart-area .error-banner:not([hidden])").count() == 0
    assert _pressed(page, "cfb") == "true"
