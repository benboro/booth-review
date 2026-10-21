"""Phase 11 performance probe on a synthetic worst case (synthetic data only).

About 200 fictional venues and about 6000 games (about 30% unrated, seasons 2014-2026,
a few venues with 40+ games). Measures, as p95 of 20 runs after 2 warm-ups:

- the venue model (`buildVenueModel` over every game),
- the splat field + raster (`paintSplat` timings, PNG encode excluded),
- end to end: `setState({seasons})` to the `mapSplatRenders` increment.

Each runs on a desktop profile (cell 3, no throttle) and a phone profile (cell 4, 4x CPU
throttle through CDP). Prints `PERF step=<name> profile=<desktop|phone> p95=<ms>
budget=<ms>`; only soft limits at 2x the UI-SPEC budget are asserted, so CI noise does not
flake. The 1x comparison lives in the plan SUMMARY.
"""

from __future__ import annotations

import copy
import random
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

RUNS = 20
WARMUPS = 2
N_VENUES = 200
N_RATED = 4200
N_UNRATED = 1800
SEED = 20261020
STATES = ["TX", "CA", "FL", "OH", "GA", "AL", "MI", "PA", "NC", "TN", "OK", "WA", "NE", "IA"]

# step -> (desktop budget, phone budget) in ms (UI-SPEC performance budget, 1x)
BUDGET = {
    "model": (15.0, 60.0),
    "field_raster": (60.0, 200.0),
    "end_to_end": (150.0, 400.0),
}
SOFT = {k: (d * 2, p * 2) for k, (d, p) in BUDGET.items()}


def _stretch(cols: dict[str, list[Any]], n: int) -> dict[str, list[Any]]:
    """Replicates every column to n rows by cycling the source rows."""
    size = len(next(iter(cols.values())))
    return {k: [v[i % size] for i in range(n)] for k, v in cols.items()}


def synthetic_raw(fixture_raw: dict[str, Any]) -> dict[str, Any]:
    rng = random.Random(SEED)
    raw = copy.deepcopy(fixture_raw)
    venues = []
    for i in range(N_VENUES):
        hawaii = i < 2
        venues.append(
            {
                "name": f"Testfield {i:03d}",
                "city": f"Town {i:03d}",
                "state": "HI" if hawaii else rng.choice(STATES),
                "country": "US",
                "lat": round(rng.uniform(19.5, 22.0) if hawaii else rng.uniform(25, 49), 4),
                "lon": round(rng.uniform(-158.5, -155.5) if hawaii else rng.uniform(-124, -67), 4),
            }
        )
    raw["lookups"]["venues"] = venues
    n_networks = len(raw["lookups"]["networks"])
    # Skewed round-robin: the first 5 venues take every 4th game, the rest share the others.
    heavy = list(range(5))

    def place(g: int) -> int:
        return heavy[(g // 4) % 5] if g % 4 == 0 else (g % (N_VENUES - 5)) + 5

    rated = _stretch(raw["telecasts"], N_RATED)
    unrated = _stretch(raw["telecasts_unrated"], N_UNRATED)
    for table, count in ((rated, N_RATED), (unrated, N_UNRATED)):
        table["season"] = [2014 + (g * 7) % 13 for g in range(count)]
        table["place"] = [place(g) for g in range(count)]
        table["network"] = [g % n_networks for g in range(count)]
    # Distinct viewers so the percentile floor sorts a real spread.
    rated["viewers"] = [round(rng.uniform(0.4, 12.0), 3) * 1_000_000 for _ in range(N_RATED)]
    raw["telecasts"] = rated
    raw["telecasts_unrated"] = unrated
    return raw


_STATS = """
const p95 = (xs) => { const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.ceil(s.length * 0.95) - 1)]; };
"""


def _throttle(page: Page, rate: int) -> Any:
    session = page.context.new_cdp_session(page)
    session.send("Emulation.setCPUThrottlingRate", {"rate": rate})
    return session


def _open_map(page: Page, site_url: str, raw: dict[str, Any]) -> None:
    page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    page.goto(f"{site_url}/index.html?view=map")
    page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    page.wait_for_function("window.__testHooks.mapSplatRenders >= 1", timeout=60_000)


def _model_p95(page: Page) -> float:
    return float(
        page.evaluate(
            "async ([runs, warm]) => {"
            + _STATS
            + """
          const M = await import('./modules/map-venues.js');
          const G = await import('./modules/map-geo.js');
          const D = window.__testHooks.data;
          const placements = G.placeVenues(D.lookups.venues);
          const passing = [];
          for (let g = 0; g < D.t.place.length; g++) if (D.t.place[g] != null) passing.push(g);
          const times = [];
          for (let i = 0; i < runs + warm; i++) {
            const t0 = performance.now();
            M.buildVenueModel(D, passing, placements);
            const dt = performance.now() - t0;
            if (i >= warm) times.push(dt);
          }
          return p95(times);
        }""",
            [RUNS, WARMUPS],
        )
    )


def _field_raster_p95(page: Page, cell: int) -> float:
    return float(
        page.evaluate(
            "async ([runs, warm, cell]) => {"
            + _STATS
            + """
          const M = await import('./modules/map-venues.js');
          const G = await import('./modules/map-geo.js');
          const S = await import('./modules/map-splat.js');
          const { US_STATES } = await import('./vendor/us-states-albers.js');
          const D = window.__testHooks.data;
          const placements = G.placeVenues(D.lookups.venues);
          const passing = [];
          for (let g = 0; g < D.t.place.length; g++) if (D.t.place[g] != null) passing.push(g);
          const venueModel = M.buildVenueModel(D, passing, placements);
          const times = [];
          for (let i = 0; i < runs + warm; i++) {
            const { timings } = await S.paintSplat({
              venueModel, states: US_STATES, theme: 'light', cell });
            if (i >= warm) times.push(timings.field + timings.raster);
          }
          return p95(times);
        }""",
            [RUNS, WARMUPS, cell],
        )
    )


def _end_to_end_p95(page: Page) -> float:
    total, sync, fig = page.evaluate(
        "async ([runs, warm]) => {"
        + _STATS
        + """
          const hooks = window.__testHooks;
          const tick = () => new Promise((r) => setTimeout(r, 0));
          const times = [], syncs = [], figs = [];
          for (let i = 0; i < runs + warm; i++) {
            const before = hooks.mapSplatRenders;
            const figBefore = hooks.mapRenders;
            let fig = null;
            const lo = 2014 + ((i + 1) % 6);
            const t0 = performance.now();
            hooks.setState({ seasons: [lo, 2026] });
            const sync = performance.now() - t0;
            while (hooks.mapSplatRenders === before) {
              if (performance.now() - t0 > 20000) throw new Error('splat never applied');
              if (fig === null && hooks.mapRenders !== figBefore) fig = performance.now() - t0;
              await tick();
            }
            const dt = performance.now() - t0;
            if (i >= warm) { times.push(dt); syncs.push(sync); figs.push(fig ?? dt); }
            await tick();
          }
          return [p95(times), p95(syncs), p95(figs)];
        }""",
        [RUNS, WARMUPS],
    )
    print(f"PERF detail=setState_sync p95={sync:.1f} figure_drawn p95={fig:.1f}")
    return float(total)


_OVER: list[str] = []


def _report(step: str, profile: str, p95: float) -> None:
    idx = 0 if profile == "desktop" else 1
    print(f"PERF step={step} profile={profile} p95={p95:.1f} budget={BUDGET[step][idx]:.0f}")
    if p95 > SOFT[step][idx]:
        _OVER.append(f"{step}/{profile} p95 {p95:.1f}ms over soft {SOFT[step][idx]}")


def test_perf_desktop(guarded_page: Page, site_url: str, fixture_raw: dict[str, Any]) -> None:
    raw = synthetic_raw(fixture_raw)
    _open_map(guarded_page, site_url, raw)
    n = guarded_page.evaluate("window.__testHooks.nGames")
    print(f"PERF games={n} venues={N_VENUES}")
    assert n >= 5000
    guarded_page.evaluate("window.__testHooks.setState({seasons: [2014, 2026]})")
    _report("model", "desktop", _model_p95(guarded_page))
    _report("field_raster", "desktop", _field_raster_p95(guarded_page, 3))
    _report("end_to_end", "desktop", _end_to_end_p95(guarded_page))
    assert not _OVER, _OVER


def test_perf_phone_throttled(
    mobile_page: Page, site_url: str, fixture_raw: dict[str, Any]
) -> None:
    raw = synthetic_raw(fixture_raw)
    _open_map(mobile_page, site_url, raw)
    mobile_page.evaluate("window.__testHooks.setState({seasons: [2014, 2026]})")
    session = _throttle(mobile_page, 4)
    try:
        _report("model", "phone", _model_p95(mobile_page))
        _report("field_raster", "phone", _field_raster_p95(mobile_page, 4))
        _report("end_to_end", "phone", _end_to_end_p95(mobile_page))
        assert not _OVER, _OVER
    finally:
        session.send("Emulation.setCPUThrottlingRate", {"rate": 1})
