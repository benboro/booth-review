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
          lines: q('svg polyline'),
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


@pytest.mark.parametrize("n_max", [1, 2, 5, 20])
@pytest.mark.parametrize("phone", [False, True])
def test_size_labels_never_overlap(
    guarded_page: Page, site_url: str, n_max: int, phone: bool
) -> None:
    """Each size step renders one legible label: no label boxes meet, and the circles clear them."""
    got = _run(
        guarded_page,
        site_url,
        f"""
        const root = document.createElement('div');
        root.className = 'map-key';
        root.style.cssText = 'position:fixed;left:20px;top:20px';
        document.body.appendChild(root);
        K.renderMapKey(root, K.buildMapKey(model({n_max}), {{ phone: {str(phone).lower()}, colorsOn: true }}),
                       {{ theme: 'light' }});
        const box = (r) => ({{ left: r.left, right: r.right, top: r.top, bottom: r.bottom }});
        const labels = Array.from(root.querySelectorAll('.map-key-label')).map((n) => box(n.getBoundingClientRect()));
        const svg = root.querySelector('.map-key-sizes svg').getBoundingClientRect();
        const sizes = root.querySelector('.map-key-sizes').getBoundingClientRect();
        const heading = root.querySelector('.map-key-strength .map-key-heading').getBoundingClientRect();
        const res = {{ labels, svg: box(svg), sizes: box(sizes), heading: box(heading),
                      leaders: root.querySelectorAll('svg polyline').length,
                      circles: root.querySelectorAll('svg circle').length }};
        root.remove();
        return res;
        """,
    )
    labels = got["labels"]
    assert len(labels) == got["circles"] >= 1
    for i, a in enumerate(labels):
        for b in labels[i + 1 :]:
            assert not (a["top"] < b["bottom"] and a["bottom"] > b["top"]), (a, b)
        assert a["left"] >= got["svg"]["right"] - 1  # clear of every circle and leader
        assert a["top"] >= got["sizes"]["top"] - 0.5 and a["bottom"] <= got["sizes"]["bottom"] + 0.5
    assert got["sizes"]["bottom"] <= got["heading"]["top"]  # the next block starts below
    assert got["leaders"] == (0 if got["circles"] == 1 else got["circles"])
