"""Phase 11: map-key.js model and DOM builder, synthetic venue models only."""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page

# ruff: noqa: E501  (inline JS fixtures)

pytestmark = pytest.mark.e2e

_MODEL = """
const model = (nMax, median = 4e6) => ({
  venues: [{ score: 1 }],
  maxScore: nMax * (median / 1e6) ** 0.35,
  medianRatedViewers: median,
});
"""


def _run(page: Page, site_url: str, body: str) -> Any:
    page.goto(f"{site_url}/index.html")
    page.wait_for_function("window.__testHooks && window.__testHooks.ready === true")
    return page.evaluate(
        "async () => { const K = await import('./modules/map-key.js');" + _MODEL + body + "}"
    )


def test_labels_are_easy_counts(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const at = (n) => K.buildMapKey(model(n), { phone: false, colorsOn: true });
        return {
          twenty: at(20).sizes.map((s) => s.label),
          one: at(1).sizes.map((s) => s.label),
          steps: Array.from(K.KEY_GAME_STEPS),
          desc: at(20).description,
        };
        """,
    )
    assert got["twenty"] == ["20 games", "5 games", "1 game"]
    assert got["one"] == ["1 game"]
    assert got["steps"] == [1, 2, 5, 10, 20, 50]
    assert got["desc"] == "Dot size blends the number of games with their audience."


def test_diameters_and_visibility(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const d = K.buildMapKey(model(20), { phone: false, colorsOn: true });
        const p = K.buildMapKey(model(20), { phone: true, colorsOn: true });
        const empty = K.buildMapKey({ venues: [], maxScore: 0, medianRatedViewers: 1e6 },
                                    { phone: false, colorsOn: true });
        const zero = K.buildMapKey({ venues: [{}], maxScore: 0, medianRatedViewers: 1e6 },
                                   { phone: false, colorsOn: true });
        return {
          dd: d.sizes.map((s) => s.diameter), pd: p.sizes.map((s) => s.diameter),
          empty: empty.visible, zero: zero.visible,
        };
        """,
    )
    assert got["dd"][0] <= 16 and got["pd"][0] <= 12
    assert got["dd"] == sorted(got["dd"], reverse=True)
    assert got["dd"][0] > got["dd"][-1]
    assert got["empty"] is False and got["zero"] is False


def test_render_dom(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const root = document.createElement('div');
        const on = K.buildMapKey(model(20), { phone: false, colorsOn: true });
        K.renderMapKey(root, on, { theme: 'light' });
        const q = (s) => root.querySelectorAll(s).length;
        const res = {
          headings: Array.from(root.querySelectorAll('.map-key-heading')).map((n) => n.textContent),
          circles: q('svg[aria-hidden="true"] circle'),
          lines: q('svg line'),
          labels: q('.map-key-label'),
          swatches: Array.from(root.querySelectorAll('.map-key-swatch')).map((n) => n.style.opacity),
          ends: Array.from(root.querySelectorAll('.map-key-end')).map((n) => n.textContent),
          aria: root.getAttribute('aria-description'),
          hidden: root.hidden,
        };
        const off = K.buildMapKey(model(20), { phone: false, colorsOn: false });
        K.renderMapKey(root, off, { theme: 'dark' });
        res.offStrength = q('.map-key-strength');
        res.offHeadings = Array.from(root.querySelectorAll('.map-key-heading')).map((n) => n.textContent);
        K.renderMapKey(root, K.buildMapKey({ venues: [], maxScore: 0, medianRatedViewers: 1 }, {}), { theme: 'light' });
        res.emptyHidden = root.hidden;
        return res;
        """,
    )
    assert got["headings"] == ["Dot size", "Color strength"]
    assert got["circles"] == 3 and got["lines"] == 3 and got["labels"] == 3
    assert got["swatches"] == ["0.15", "0.5", "0.88"]
    assert got["ends"] == ["Few games or split networks", "Many games, one network"]
    assert got["aria"] == "Dot size blends the number of games with their audience."
    assert got["hidden"] is False
    assert got["offStrength"] == 0 and got["offHeadings"] == ["Dot size"]
    assert got["emptyHidden"] is True
