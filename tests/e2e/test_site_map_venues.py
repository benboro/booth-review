"""Phase 11: map-venues.js and palette map constants, synthetic data only."""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


def _run(page: Page, site_url: str, body: str, module: str = "palette.js") -> Any:
    page.goto(f"{site_url}/index.html")
    page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    return page.evaluate(
        f"async () => {{ const M = await import('./modules/{module}');" + body + "}"
    )


# ---------------------------------------------------------------- palette / oklab


def test_oklab_round_trip_and_mix_endpoints(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const ch = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
        const close = (a, b) => ch(a).every((v, i) => Math.abs(v - ch(b)[i]) <= 1);
        const sets = [M.FAMILY_COLORS.light, M.FAMILY_COLORS.dark,
                      M.MAP_FAMILY_COLORS.light, M.MAP_FAMILY_COLORS.dark];
        let roundTrip = true;
        for (const set of sets) for (const h of Object.values(set)) {
          if (!close(M.oklabToHex(M.hexToOklab(h)), h)) roundTrip = false;
        }
        const a = '#0072B2', b = '#D55E00';
        return {
          whiteL: M.hexToOklab('#FFFFFF')[0],
          roundTrip,
          m0: close(M.mixOklab(a, b, 0), a),
          m1: close(M.mixOklab(a, b, 1), b),
          differs: M.mixOklab(a, b, 0.5).toUpperCase() !== M.mixHex(a, b, 0.5).toUpperCase(),
        };
        """,
    )
    assert abs(got["whiteL"] - 1) < 1e-3
    assert got["roundTrip"] and got["m0"] and got["m1"] and got["differs"]


def test_palette_map_constants(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const same = (t) => Object.keys(M.FAMILY_COLORS[t])
          .filter((k) => k !== 'conference')
          .every((k) => M.MAP_FAMILY_COLORS[t][k] === M.FAMILY_COLORS[t][k]);
        return {
          lc: M.MAP_FAMILY_COLORS.light.conference,
          dc: M.MAP_FAMILY_COLORS.dark.conference,
          same: same('light') && same('dark'),
          contrastL: M.contrastRatio(M.MAP_FAMILY_COLORS.light.conference, M.MAP_LAND.light),
          contrastD: M.contrastRatio(M.MAP_FAMILY_COLORS.dark.conference, M.MAP_LAND.dark),
          frozen: Object.isFrozen(M.MAP_SPLAT) && Object.isFrozen(M.MAP_VENUE_DOT),
          splat: M.MAP_SPLAT, dot: M.MAP_VENUE_DOT, neutral: M.MAP_DOT_NEUTRAL,
        };
        """,
    )
    assert got["lc"] == "#6A5BA0"
    assert got["dc"] == "#9A8CD0"
    assert got["same"] and got["frozen"]
    assert got["contrastL"] >= 5
    assert got["contrastD"] >= 5
    assert got["splat"]["viewersWeight"] == 0.35
    assert got["splat"]["unratedFallback"] == 150000
    assert got["dot"]["radiusMax"] == 8
    assert got["neutral"] == {"light": "#B3AA9C", "dark": "#7A7266"}
