"""Playwright harness for the D-15 browser smoke tests.

Every module under `tests/e2e/` is collected only with `-m e2e` (the default
`uv run pytest` deselects them via `pyproject.toml`'s `addopts`). The harness
builds `dist/site` with `booth-review site --fixture` once per session,
serves it with a `python -m http.server` **subprocess** (never an in-process
thread: `pytest-socket`'s `--disable-socket` patches this process's own
`socket` module and would block an in-process server's `bind`/`accept`, but
has no visibility into a separate OS process -- RESEARCH Common Pitfall 1),
and wraps every test's `page` fixture with a route guard that aborts any
request leaving the site's own origin (D-15, SITE-19) and fails the test if
one was attempted. Every fixture here serves only the synthetic contract
fixture -- never real collected data (AGENTS.md: the vault is private and
never goes into fixtures or logs).

The suite runs in parallel with `uv run pytest -m e2e -n 4`. Each xdist
worker builds its own `site_dist` under its own `tmp_path_factory` basetemp
(about 0.5 s, so per-worker builds are cheaper than a cross-process lock) and
serves it from its own `http.server` subprocess on an OS-assigned port. Session
fixtures here must keep both properties: no fixed paths under `dist/` and no
fixed ports.
"""

from __future__ import annotations

import copy
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import zlib
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from crews_fixture import build_crews_raw
from nfl_crews_fixture import build_nfl_crews_raw
from playwright.sync_api import Browser, ConsoleMessage, Error, Page, Playwright, Route, expect

from booth_review.cli import main

# Fixture sizes (04.13-01): 12 rated telecasts plus 8 unrated games. Later plans import
# these (`from conftest import FIXTURE_GAMES`) instead of hand-writing denominators.
FIXTURE_RATED = 12
FIXTURE_UNRATED = 8
FIXTURE_GAMES = 20
# One unrated game (merged index 19, 2026, cause pending, no score) is unplayed: the data
# model carries it, but every view except This weekend leaves it out (v2.1 user rule).
FIXTURE_UNPLAYED = 1
FIXTURE_SHOWN = FIXTURE_GAMES - FIXTURE_UNPLAYED
FIXTURE_BAND = FIXTURE_UNRATED - FIXTURE_UNPLAYED

_PORT_RE = re.compile(r"port (\d+)")
_SERVER_START_TIMEOUT = 15.0


@pytest.fixture(scope="session", autouse=True)
def _chromium_available(playwright: Playwright) -> None:
    """Skip locally (fail in CI) when Chromium isn't installed (RESEARCH Pitfall 2)."""
    try:
        browser = playwright.chromium.launch()
        browser.close()
    except Error as exc:
        message = str(exc).lower()
        if "doesn't exist" in message or "does not exist" in message:
            if os.environ.get("CI"):
                pytest.fail(
                    "Chromium missing in CI: the e2e container image's Playwright tag "
                    "must match uv.lock"
                )
            pytest.skip("Chromium not installed; run `uv run playwright install chromium`")
        raise


@pytest.fixture(scope="session")
def site_dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build dist/site from the synthetic contract fixture (D-14/D-15).

    Per xdist worker: each worker's basetemp is its own.
    """
    out = tmp_path_factory.mktemp("site") / "site"
    returncode = main(["site", "--fixture", "--out", str(out)])
    assert returncode == 0, f"booth-review site --fixture exited {returncode}"
    return out


def _serve_directory(directory: Path) -> Iterator[str]:
    """Serve `directory` via a subprocess `python -m http.server` on an
    OS-assigned port (RESEARCH Pitfall 1); yields its base URL, then
    terminates the subprocess on teardown.

    A plain generator (not a fixture) so both `site_url` (the fixture build,
    below) and `test_site_realdata.py`'s own real-data build can each wrap it
    in their own fixture at whatever scope they need, without duplicating
    the subprocess/port-detection logic.
    """
    proc = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-m",
            "http.server",
            "0",
            "--bind",
            "127.0.0.1",
            "--directory",
            str(directory),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.stdout is not None
    lines: queue.Queue[str] = queue.Queue()

    def _pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line)

    reader = threading.Thread(target=_pump, daemon=True)
    reader.start()

    deadline = time.monotonic() + _SERVER_START_TIMEOUT
    port: int | None = None
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        try:
            line = lines.get(timeout=max(remaining, 0))
        except queue.Empty:
            break
        match = _PORT_RE.search(line)
        if match:
            port = int(match.group(1))
            break

    if port is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        raise RuntimeError("http.server did not report a port within 15 seconds")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="session")
def site_url(site_dist: Path) -> Iterator[str]:
    """Serve `site_dist` (the fixture build); yields its base URL."""
    yield from _serve_directory(site_dist)


@pytest.fixture(scope="session")
def fixture_raw(site_dist: Path) -> dict[str, Any]:
    """The built site-data.json, parsed (the same content the browser fetches)."""
    return json.loads((site_dist / "site-data.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture
def serve_round(fixture_raw: dict[str, Any]) -> Callable[[Page, str | None], None]:
    """Returns `serve(page, round_)`: makes `page` load the synthetic contract
    fixture with telecast 5's (the only CFP game's) `playoff_round` replaced by
    `round_`, so a test can see every CFP round without growing the shared
    fixture (whose 12-rated, 20-game counts many tests rely on). Call it before opening
    the app; a later route wins over the origin guard's catch-all.
    """

    def _serve(page: Page, round_: str | None) -> None:
        raw = copy.deepcopy(fixture_raw)
        raw["telecasts"]["playoff_round"][5] = round_
        page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))

    return _serve


@pytest.fixture
def serve_booths(fixture_raw: dict[str, Any]) -> Callable[[Page], None]:
    """Returns `serve(page)`: makes `page` load the synthetic contract fixture with the
    booth overlay applied (lookups.booths, telecasts.booth, telecasts_unrated.booth from
    tests/fixtures/contract/booth-overlay.json; scenarios are listed with the overlay,
    plan 10-03). Synthetic data only. Call it before opening the app; a later route wins
    over the origin guard's catch-all, as for `serve_round`.
    """
    overlay = json.loads(
        (
            Path(__file__).resolve().parents[1] / "fixtures" / "contract" / "booth-overlay.json"
        ).read_text(encoding="utf-8")
    )

    def _serve(page: Page) -> None:
        raw = copy.deepcopy(fixture_raw)
        raw["lookups"]["booths"] = overlay["booths"]
        raw["telecasts"]["booth"] = overlay["telecasts_booth"]
        raw["telecasts_unrated"]["booth"] = overlay["unrated_booth"]
        page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))

    return _serve


@pytest.fixture
def serve_crews(fixture_raw: dict[str, Any]) -> Callable[[Page], None]:
    """Returns `serve(page)`: makes `page` load the synthetic crews dataset
    (tests/e2e/crews_fixture.py `build_crews_raw`: 30+ crews and every Crews table case).
    Synthetic data only. Call it before opening the app; a later route wins over the
    origin guard's catch-all, as for `serve_booths`.
    """
    raw = build_crews_raw(fixture_raw)

    def _serve(page: Page) -> None:
        page.route("**/site-data.json*", lambda route: route.fulfill(json=copy.deepcopy(raw)))

    return _serve


@pytest.fixture
def serve_nfl_crews(nfl_fixture_raw: dict[str, Any]) -> Callable[[Page], None]:
    """Returns `serve(page)`: makes `page` load the synthetic NFL Crews dataset
    (tests/e2e/nfl_crews_fixture.py `build_nfl_crews_raw`: the built nfl-data.json plus
    more than 25 pooled pairs and every NFL Crews case). Synthetic data only. Call it
    before opening the app; a later route wins over the origin guard's catch-all, as for
    `serve_crews`.
    """
    raw = build_nfl_crews_raw(nfl_fixture_raw)

    def _serve(page: Page) -> None:
        page.route("**/nfl-data.json*", lambda route: route.fulfill(json=copy.deepcopy(raw)))

    return _serve


def multichannel_raw(
    fixture_raw: dict[str, Any], *, also_move_zero: bool = False
) -> dict[str, Any]:
    """Synthetic two-channel family: a copy of the contract fixture whose fifth
    network `net-e` (disney family, index 4; since 04.13-01 the fixture itself carries
    it, for its unrated games, so it is renamed here rather than appended) carries
    rated telecast 8 (and telecast 0 when `also_move_zero`). Keeps the 12-rated, 20-game fixture
    unchanged for other tests (AGENTS.md: tests use synthetic fixtures; never vault data).
    """
    raw = copy.deepcopy(fixture_raw)
    assert raw["lookups"]["networks"][4]["id"] == "net-e"
    raw["lookups"]["networks"][4] = {"id": "net-e", "name": "Echo Sports", "family": "disney"}
    raw["telecasts"]["network"][8] = 4
    if also_move_zero:
        raw["telecasts"]["network"][0] = 4
    return raw


def map_venues_raw(fixture_raw: dict[str, Any]) -> dict[str, Any]:
    """Synthetic venue cases for the Map tests (Phase 11); fictional fixture data only,
    no vault data.

    (a) Duplicate key: appends venue 9, the same name and city as venue 0 (Northfield
    Stadium, Lincoln) at a slightly different lat/lon, and moves rated telecast 11
    (was at venue 6) onto it. Keys are then venue 0 'northfield-stadium-lincoln' and
    venue 9 'northfield-stadium-lincoln-2'.
    (b) Splits, stated here so tests depend on them deliberately: rated venue 2 holds
    telecast 1 (net-b, fox) and telecast 8 (net-a, disney), an exact two-family even
    split, so the networks of telecasts 1 and 8 are pinned below; venue 8 (Nassau)
    holds only unrated games.
    """
    raw = copy.deepcopy(fixture_raw)
    venues = raw["lookups"]["venues"]
    twin = dict(venues[0])
    twin["lat"] = round(twin["lat"] + 0.01, 4)
    twin["lon"] = round(twin["lon"] + 0.01, 4)
    venues.append(twin)
    raw["telecasts"]["place"][11] = len(venues) - 1
    raw["telecasts"]["network"][1] = 1  # fox
    raw["telecasts"]["network"][8] = 0  # disney
    return raw


@pytest.fixture
def serve_map_venues(fixture_raw: dict[str, Any]) -> Callable[[Page], None]:
    """Returns `serve(page)`: loads the `map_venues_raw` synthetic fixture. Call it
    before opening the app.
    """

    def _serve(page: Page) -> None:
        raw = map_venues_raw(fixture_raw)
        page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))

    return _serve


WEEKEND_MAP_NOW = "2026-10-03T09:00:00-04:00"
# Saturday 2026-10-03 of the weekend-map fixture, by game key (the venue-hits customdata).
# Placed dots: t:11 (noon, Orlando), unrated 19 (prime, Pasadena, tier-a booth), 0 and 1 (noon,
# the same Lincoln venue), 3 (Time TBA, Ann Arbor), 5 (prime, Atlanta), 6 (afternoon, Boulder),
# 7 (prime, Pasadena), 10 (ESPN+, afternoon, Honolulu), 11 (late, Atlanta). Edge marker: 12 (noon,
# a GB venue). No venue: 2, 4, 8.
WEEKEND_MAP_PLACED_DOTS = 10
WEEKEND_MAP_MARKERS = 1
WEEKEND_MAP_NO_VENUE = 3


def weekend_map_raw(fixture_raw: dict[str, Any]) -> dict[str, Any]:
    """Synthetic CFB weekend for the Phase 24 map tests; fictional fixture data only, no vault
    data. A deep copy of the contract fixture (never edited) with real network ids, an ESPN+
    network, a tier-a disney booth on the pending game, a GB venue, and Saturday games spread
    over all four windows (see the constants above for the layout).
    """
    raw = copy.deepcopy(fixture_raw)
    nets = raw["lookups"]["networks"]
    for net, real in zip(nets, ["espn", "fox", "acc-network", "cbs", "peacock"], strict=True):
        net["id"] = real
    nets.append({"id": "espn-plus", "name": "ESPN+", "family": "disney"})
    venues = raw["lookups"]["venues"]
    venues.append(
        {
            "name": "Wembley Test Ground",
            "city": "London",
            "state": None,
            "country": "GB",
            "lat": 51.556,
            "lon": -0.2796,
        }
    )
    gb = len(venues) - 1
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
    sched = raw["telecasts_scheduled"]
    for index, place in {0: 0, 1: 0, 3: 1, 5: 3, 6: 2, 7: 5}.items():
        sched["place"][index] = place

    def add(date: str, kickoff: str | None, network: int | None, place: int | None) -> None:
        row: dict[str, Any] = {
            "season": 2026,
            "date": date,
            "kickoff": kickoff,
            "time_slot": "prime" if kickoff else None,
            "away_team": 0,
            "home_team": 1,
            "neutral": False,
            "away_rank": None,
            "home_rank": None,
            "network": network,
            "outlets": [],
            "crew": [],
            "crew_source_url": None,
            "crew_source_label": None,
            "home_conference": 0,
            "away_conference": 3,
            "place": place,
            "week": "5",
        }
        assert row.keys() == sched.keys()
        for key, value in row.items():
            sched[key].append(value)

    add("2026-10-02", "2026-10-02T20:00:00-04:00", 1, 0)  # 9: Friday
    add("2026-10-03", "2026-10-03T18:00:00-04:00", 5, 4)  # 10: ESPN+, Honolulu
    add("2026-10-03", "2026-10-03T22:30:00-04:00", 1, 3)  # 11: late, Atlanta
    add("2026-10-03", "2026-10-03T09:30:00-04:00", 0, gb)  # 12: noon, London
    return raw


@pytest.fixture
def serve_weekend_map(fixture_raw: dict[str, Any]) -> Callable[..., None]:
    """Returns `serve(page, now=WEEKEND_MAP_NOW)`: fixes the clock and loads the
    `weekend_map_raw` synthetic fixture. Call it before opening the app.
    """

    def _serve(page: Page, now: str = WEEKEND_MAP_NOW) -> None:
        raw = weekend_map_raw(fixture_raw)
        page.clock.set_fixed_time(now)
        page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))

    return _serve


def expand_family(page: Page, family: str) -> None:
    """Expands a Networks family so its channel rows show. Since 04.16 D-10 the
    families open collapsed, so channel-level tests expand first.
    """
    caret = page.locator(
        f"fieldset.family-group:has(input[data-family-checkbox='{family}']) .family-caret"
    )
    caret.click()
    page.wait_for_function(
        "(f) => document.querySelector(`.family-caret[data-family='${f}']`)"
        ".getAttribute('aria-expanded') === 'true'",
        arg=family,
    )


def click_mode_toggle(page: Page, toggle: str, mode: str) -> None:
    """Turns Compare or Called together on deterministically (SITE-59).

    A still-open Announcers popover can swallow the click as a light dismiss,
    so close it first; then click once and assert the pressed state before
    waiting for the URL, so a miss fails fast with the observed state.
    """
    if page.evaluate("document.getElementById('pop-announcers').matches(':popover-open')"):
        page.keyboard.press("Escape")
        page.wait_for_function(
            "!document.getElementById('pop-announcers').matches(':popover-open')"
        )
    button = page.locator(toggle)
    expect(button).to_be_enabled()
    expect(button).to_have_attribute("aria-pressed", "false")
    button.click()
    expect(button).to_have_attribute("aria-pressed", "true")
    page.wait_for_function("(m) => location.search.includes(m)", arg=mode, timeout=5000)


@pytest.fixture
def multichannel(fixture_raw: dict[str, Any]) -> dict[str, Any]:
    """The synthetic two-channel override (telecast 8 on `net-e`)."""
    return multichannel_raw(fixture_raw)


@pytest.fixture
def serve_multichannel(fixture_raw: dict[str, Any]) -> Callable[..., None]:
    """Returns `serve(page, also_move_zero=False)`: makes `page` load the
    synthetic two-channel fixture (see `multichannel_raw`). Call it before
    opening the app.
    """

    def _serve(page: Page, also_move_zero: bool = False) -> None:
        raw = multichannel_raw(fixture_raw, also_move_zero=also_move_zero)
        page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))

    return _serve


@pytest.fixture
def serve_bowl(fixture_raw: dict[str, Any]) -> Callable[..., None]:
    """Returns `serve(page, *, index, bowl, round_=None, neutral=None,
    bowls=None)`: loads the synthetic fixture with telecast `index`'s bowl
    (and optionally playoff_round, neutral, and lookups.bowls) replaced. Keeps
    the 12-rated, 20-game fixture unchanged for other tests. Replacement `bowls`
    entries must include `franchise` (an index into the fixture's `bowl_franchises`);
    the unrated block is copied through unchanged and references bowl index 2, so a
    replacement list should keep at least three entries once the client reads it.
    """

    def _serve(
        page: Page,
        *,
        index: int,
        bowl: int | None,
        round_: str | None = None,
        neutral: bool | None = None,
        bowls: list[dict[str, object]] | None = None,
    ) -> None:
        raw = copy.deepcopy(fixture_raw)
        raw["telecasts"]["bowl"][index] = bowl
        if round_ is not None:
            raw["telecasts"]["playoff_round"][index] = round_
        if neutral is not None:
            raw["telecasts"]["neutral"][index] = neutral
        if bowls is not None:
            raw["lookups"]["bowls"] = bowls
        page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))

    return _serve


@pytest.fixture
def serve_ny6(fixture_raw: dict[str, Any]) -> Callable[[Page, dict[str, str]], None]:
    """Returns `serve(page, renames)`: loads the synthetic fixture with bowl
    franchise slugs renamed (old slug -> New Year's Six slug), so a test can see
    the NY6 band. Keeps the shared 12-rated, 20-game fixture unchanged (RESEARCH Pitfall 6).
    Call it before opening the app.
    """

    def _serve(page: Page, renames: dict[str, str]) -> None:
        raw = copy.deepcopy(fixture_raw)
        franchises = raw["lookups"]["bowl_franchises"]
        known = {f["slug"] for f in franchises}
        for old in renames:
            assert old in known, old
        for f in franchises:
            f["slug"] = renames.get(f["slug"], f["slug"])
        page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))

    return _serve


def _install_guard(page: Page, site_url: str) -> tuple[list[str], list[str]]:
    """Wires `page` to abort and record any request leaving `site_url`'s
    origin (SITE-19), and to record any console error mentioning CSP.
    Returns the two lists it appends to, for the caller's own teardown.
    """
    off_origin: list[str] = []
    csp_errors: list[str] = []
    allowed_prefix = site_url + "/"

    def _route(route: Route) -> None:
        url = route.request.url
        if url.startswith(allowed_prefix) or url.startswith("data:") or url.startswith("blob:"):
            route.continue_()
        else:
            off_origin.append(url)
            route.abort()

    page.route("**/*", _route)

    def _on_console(msg: ConsoleMessage) -> None:
        if msg.type == "error" and "Content Security Policy" in msg.text:
            csp_errors.append(msg.text)

    page.on("console", _on_console)

    return off_origin, csp_errors


def _assert_guard_clean(off_origin: list[str], csp_errors: list[str]) -> None:
    if off_origin:
        hosts = sorted({urlsplit(url).hostname for url in off_origin})
        raise AssertionError(f"off-origin requests were made to: {hosts}")
    if csp_errors:
        raise AssertionError(f"Content-Security-Policy violations logged: {csp_errors}")


# CSS injected before the app loads, per font setting. The CI runner
# (ubuntu-latest) has no Noto Sans, so `system-ui` resolves to a wider face there
# than on a dev machine; `dejavu` stands in for it, and `wide` adds letter-spacing
# to catch any font-dependent sizing that happens to fit DejaVu. `narrow` tightens
# DejaVu below the toolbar's 116px cell floor, a stand-in for a narrow system font
# that is present on every runner.
_DEJAVU_ROOT = (
    ':root { --sans: "DejaVu Sans", sans-serif !important;'
    ' --serif: "DejaVu Sans", sans-serif !important;'
    ' --plot: "DejaVu Sans", sans-serif !important; }'
)
FONT_CSS: dict[str, str] = {
    "default": "",
    "dejavu": _DEJAVU_ROOT,
    "wide": (_DEJAVU_ROOT + " body, button, input { letter-spacing: 0.4px; }"),
    "narrow": (_DEJAVU_ROOT + " body, button, input { letter-spacing: -1px; }"),
}


def measure_gap(page: Page, upper_selector: str, lower_selector: str) -> float:
    """Vertical gap in px: the lower element's top minus the upper element's bottom."""
    return float(
        page.evaluate(
            """([upper, lower]) => {
              const a = document.querySelector(upper).getBoundingClientRect();
              const b = document.querySelector(lower).getBoundingClientRect();
              return b.top - a.bottom;
            }""",
            [upper_selector, lower_selector],
        )
    )


def element_height(page: Page, selector: str) -> float:
    """Rendered height in px of the first element matching `selector`."""
    return float(
        page.evaluate(
            "(sel) => document.querySelector(sel).getBoundingClientRect().height",
            selector,
        )
    )


def logo_images(page: Page, scope_selector: str) -> list[dict[str, Any]]:
    """Every `<img>` under `scope_selector` with its src, alt, title, rendered
    size and natural width, for logo size and attribution checks."""
    result: list[dict[str, Any]] = page.evaluate(
        """(scope) => [...document.querySelectorAll(scope + ' img')].map((img) => {
          const r = img.getBoundingClientRect();
          return {
            src: img.getAttribute('src'),
            alt: img.getAttribute('alt'),
            title: img.getAttribute('title'),
            width: r.width,
            height: r.height,
            naturalWidth: img.naturalWidth,
          };
        })""",
        scope_selector,
    )
    return result


@pytest.fixture
def font_setting(request: pytest.FixtureRequest) -> str:
    """The font stack the page renders in. Geometry tests parametrize this
    indirectly over several settings; everything else gets the local default.
    """
    return str(getattr(request, "param", "default"))


def _apply_font(page: Page, setting: str) -> None:
    """Force the page's font stack (no-op for `default`). The page's CSP blocks
    injected `<style>` elements, so the override is appended to the served
    `style.css` instead. Call after `_install_guard`: the last-registered
    matching route wins.
    """
    css = FONT_CSS[setting]
    if not css:
        return

    def _route(route: Route) -> None:
        response = route.fetch()
        route.fulfill(response=response, body=response.text() + "\n" + css)

    page.route("**/style.css*", _route)


@pytest.fixture
def guarded_page(page: Page, site_url: str, font_setting: str) -> Iterator[Page]:
    """`page`, wired to abort and record any request leaving `site_url`'s
    origin (SITE-19), and to record any console error mentioning CSP.
    Teardown fails the test if either list is non-empty.
    """
    off_origin, csp_errors = _install_guard(page, site_url)
    _apply_font(page, font_setting)
    yield page
    _assert_guard_clean(off_origin, csp_errors)


@pytest.fixture
def mobile_page(browser: Browser, site_url: str, font_setting: str) -> Iterator[Page]:
    """A guarded `page` from a fresh mobile context (390x844, touch, D-15/SITE-18)."""
    context = browser.new_context(
        viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True
    )
    page = context.new_page()
    off_origin, csp_errors = _install_guard(page, site_url)
    _apply_font(page, font_setting)
    try:
        yield page
    finally:
        context.close()
    _assert_guard_clean(off_origin, csp_errors)


@pytest.fixture
def open_app(site_url: str) -> Callable[[Page, str], None]:
    """Returns `open(page, query="")`: navigates to `index.html<query>` and
    waits for `app.js`'s bootstrap to finish (`window.__testHooks.ready`)."""

    def _open(page: Page, query: str = "") -> None:
        page.goto(f"{site_url}/index.html{query}")
        page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")

    return _open


# -- Flag-on (NFL) build: separate fixtures, the flag-off ones above stay untouched (D-25) ----


@pytest.fixture(scope="session")
def nfl_site_dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build dist/site with the NFL flag on from the synthetic fixtures."""
    out = tmp_path_factory.mktemp("nflsite") / "site"
    returncode = main(["site", "--fixture", "--nfl", "--out", str(out)])
    assert returncode == 0, f"booth-review site --fixture --nfl exited {returncode}"
    return out


@pytest.fixture(scope="session")
def nfl_site_url(nfl_site_dist: Path) -> Iterator[str]:
    """Serve `nfl_site_dist`; yields its base URL."""
    yield from _serve_directory(nfl_site_dist)


@pytest.fixture(scope="session")
def nfl_fixture_raw(nfl_site_dist: Path) -> dict[str, Any]:
    """The built nfl-data.json, parsed."""
    return json.loads((nfl_site_dist / "nfl-data.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture
def open_nfl_app(nfl_site_url: str) -> Callable[..., None]:
    """Returns `open(page, query="?sport=nfl")`: opens the flag-on site and
    waits for the NFL bootstrap (`window.__nflTestHooks.ready`)."""

    def _open(page: Page, query: str = "?sport=nfl") -> None:
        page.goto(f"{nfl_site_url}/index.html{query}")
        page.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.ready === true")

    return _open


@pytest.fixture
def open_flagon_cfb(nfl_site_url: str) -> Callable[..., None]:
    """Returns `open(page, query="")`: opens the flag-on site on the CFB view."""

    def _open(page: Page, query: str = "") -> None:
        page.goto(f"{nfl_site_url}/index.html{query}")
        page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")

    return _open


@pytest.fixture
def nfl_guarded_page(page: Page, nfl_site_url: str, font_setting: str) -> Iterator[Page]:
    """`guarded_page` for the flag-on site."""
    off_origin, csp_errors = _install_guard(page, nfl_site_url)
    _apply_font(page, font_setting)
    yield page
    _assert_guard_clean(off_origin, csp_errors)


@pytest.fixture
def nfl_mobile_page(browser: Browser, nfl_site_url: str, font_setting: str) -> Iterator[Page]:
    """`mobile_page` for the flag-on site."""
    context = browser.new_context(
        viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True
    )
    page = context.new_page()
    off_origin, csp_errors = _install_guard(page, nfl_site_url)
    _apply_font(page, font_setting)
    try:
        yield page
    finally:
        context.close()
    _assert_guard_clean(off_origin, csp_errors)


# -- Flag-on (MLB) build: the synthetic MLB fixture only (09-17) ----


@pytest.fixture(scope="session")
def mlb_site_dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build dist/site with the MLB flag on from the synthetic fixtures."""
    out = tmp_path_factory.mktemp("mlbsite") / "site"
    returncode = main(["site", "--fixture", "--mlb", "--out", str(out)])
    assert returncode == 0, f"booth-review site --fixture --mlb exited {returncode}"
    return out


@pytest.fixture(scope="session")
def mlb_site_url(mlb_site_dist: Path) -> Iterator[str]:
    """Serve `mlb_site_dist`; yields its base URL."""
    yield from _serve_directory(mlb_site_dist)


@pytest.fixture
def mlb_guarded_page(page: Page, mlb_site_url: str, font_setting: str) -> Iterator[Page]:
    """`guarded_page` for the MLB flag-on site."""
    off_origin, csp_errors = _install_guard(page, mlb_site_url)
    _apply_font(page, font_setting)
    yield page
    _assert_guard_clean(off_origin, csp_errors)


@pytest.fixture
def mlb_mobile_page(browser: Browser, mlb_site_url: str, font_setting: str) -> Iterator[Page]:
    """`mobile_page` for the MLB flag-on site."""
    context = browser.new_context(
        viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True
    )
    page = context.new_page()
    off_origin, csp_errors = _install_guard(page, mlb_site_url)
    _apply_font(page, font_setting)
    try:
        yield page
    finally:
        context.close()
    _assert_guard_clean(off_origin, csp_errors)


@pytest.fixture
def open_mlb_app(mlb_site_url: str) -> Callable[..., None]:
    """Returns `open(page, query="?sport=mlb")`: opens the MLB flag-on site and
    waits for the MLB bootstrap (`window.__mlbTestHooks.ready`)."""

    def _open(page: Page, query: str = "?sport=mlb") -> None:
        page.goto(f"{mlb_site_url}/index.html{query}")
        page.wait_for_function("window.__mlbTestHooks && window.__mlbTestHooks.ready === true")

    return _open


@pytest.fixture
def open_mlb_cfb(mlb_site_url: str) -> Callable[..., None]:
    """Returns `open(page, query="")`: opens the MLB flag-on site on the CFB view."""

    def _open(page: Page, query: str = "") -> None:
        page.goto(f"{mlb_site_url}/index.html{query}")
        page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")

    return _open


# -- Flag-on (NFL and MLB) build: both synthetic fixtures ----


@pytest.fixture(scope="session")
def both_site_dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build dist/site with the NFL and MLB flags on from the synthetic fixtures."""
    out = tmp_path_factory.mktemp("bothsite") / "site"
    returncode = main(["site", "--fixture", "--nfl", "--mlb", "--out", str(out)])
    assert returncode == 0, f"booth-review site --fixture --nfl --mlb exited {returncode}"
    return out


@pytest.fixture(scope="session")
def both_site_url(both_site_dist: Path) -> Iterator[str]:
    """Serve `both_site_dist`; yields its base URL."""
    yield from _serve_directory(both_site_dist)


@pytest.fixture
def both_guarded_page(page: Page, both_site_url: str, font_setting: str) -> Iterator[Page]:
    """`guarded_page` for the NFL and MLB flag-on site."""
    off_origin, csp_errors = _install_guard(page, both_site_url)
    _apply_font(page, font_setting)
    yield page
    _assert_guard_clean(off_origin, csp_errors)


def _shard_spec() -> tuple[int, int] | None:
    """Reads `E2E_SHARD` ("<index>/<total>", 1-based), set only by CI's e2e matrix."""
    spec = os.environ.get("E2E_SHARD", "").strip()
    if not spec:
        return None
    index_text, _, total_text = spec.partition("/")
    index, total = int(index_text), int(total_text)
    if not 1 <= index <= total:
        raise pytest.UsageError(f"E2E_SHARD must be <index>/<total>, 1 <= index <= total: {spec!r}")
    return index, total


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Splits the e2e suite across CI shards by a stable hash of each test id.

    Every xdist worker computes the same split, so each shard runs a fixed,
    disjoint slice and together the shards run every test exactly once.
    """
    spec = _shard_spec()
    if spec is None:
        return
    index, total = spec
    keep: list[pytest.Item] = []
    drop: list[pytest.Item] = []
    for item in items:
        bucket = zlib.crc32(item.nodeid.encode("utf-8")) % total
        (keep if bucket == index - 1 else drop).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep
