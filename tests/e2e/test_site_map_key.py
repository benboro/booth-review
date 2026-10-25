"""Phase 11: map-key.js model and DOM builder, synthetic venue models only."""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page

# ruff: noqa: E501  (inline JS fixtures)

pytestmark = pytest.mark.e2e

_MODEL = """
const model = (refGames) => ({ venues: [{ games: 1 }], refGames });
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
        const at = (n) => K.buildMapKey(model(n), { phone: false });
        const labels = (n) => at(n).sizes.map((s) => s.label);
        return {
          l73: labels(73), l60: labels(60), l99: labels(99), l150: labels(150),
          l3: labels(3), l1: labels(1),
          steps: Array.from(K.KEY_GAME_STEPS),
          desc: at(73).description,
          keys: Object.keys(at(73)).sort(),
        };
        """,
    )
    three = ["50 games", "20 games", "5 games"]
    assert got["l73"] == got["l60"] == got["l99"] == three
    assert got["l150"] == ["100 games", "50 games", "10 games"]
    assert got["l3"] == ["2 games", "1 game"]
    assert got["l1"] == ["1 game"]
    assert got["steps"] == [1, 2, 5, 10, 20, 50, 100, 200]
    assert got["desc"] == "Dot size is the number of games at the venue."
    assert got["keys"] == ["description", "sizes", "visible"]


def test_diameters_and_visibility(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const V = await import('./modules/map-venues.js');
        const d = K.buildMapKey(model(73), { phone: false });
        const p = K.buildMapKey(model(73), { phone: true });
        const bad = [undefined, {}, { refGames: 0 }, { refGames: NaN }].map((m) => K.buildMapKey(m).visible);
        return {
          dd: d.sizes.map((s) => s.diameter), pd: p.sizes.map((s) => s.diameter),
          games: d.sizes.map((s) => s.games),
          dExp: d.sizes.map((s) => V.venueDotSize(s.games, 73).desktop),
          pExp: p.sizes.map((s) => V.venueDotSize(s.games, 73).phone),
          bad,
        };
        """,
    )
    assert got["dd"] == got["dExp"] and got["pd"] == got["pExp"]
    assert got["dd"][0] <= 20 and got["pd"][0] <= 14
    assert got["dd"] == sorted(got["dd"], reverse=True)
    assert got["dd"][0] >= 1.5 * got["dd"][1]
    assert abs(got["dd"][-1] - 20 * (5 / 73) ** 0.5) < 1e-9  # no minimum size
    assert got["bad"] == [False] * 4


def test_key_rescales_with_the_filtered_reference(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const at = (n) => K.buildMapKey(model(n), { phone: false });
        const labels = (n) => at(n).sizes.map((s) => s.label);
        return {
          full: labels(73), narrow: labels(12), two: labels(2), one: labels(1),
          oneDiameter: at(1).sizes[0].diameter,
          empty: K.buildMapKey({ venues: [], refGames: 0 }).sizes,
          exact: at(10).sizes.map((s) => s.diameter),
        };
        """,
    )
    assert got["full"] == ["50 games", "20 games", "5 games"]
    assert got["narrow"] == ["10 games", "5 games", "1 game"]
    assert got["two"] == ["2 games", "1 game"]
    assert got["one"] == ["1 game"]
    assert got["oneDiameter"] == 20
    assert got["empty"] == []
    assert got["exact"][0] == 20  # a step equal to the reference draws at max


def test_render_dom(guarded_page: Page, site_url: str) -> None:
    got = _run(
        guarded_page,
        site_url,
        """
        const root = document.createElement('div');
        K.renderMapKey(root, K.buildMapKey(model(73), { phone: false }), { theme: 'light' });
        const q = (s) => root.querySelectorAll(s).length;
        const res = {
          headings: Array.from(root.querySelectorAll('.map-key-heading')).map((n) => n.textContent),
          circles: q('svg[aria-hidden="true"] circle'),
          lines: q('svg polyline'),
          labels: q('.map-key-label'),
          legacy: q('.map-key-strength, .map-key-swatch, .map-key-end'),
          aria: root.getAttribute('aria-description'),
          hidden: root.hidden,
        };
        K.renderMapKey(root, K.buildMapKey({ venues: [], refGames: 0 }, {}), { theme: 'light' });
        res.emptyHidden = root.hidden;
        return res;
        """,
    )
    assert got["headings"] == ["Dot size"]
    assert got["circles"] == 3 and got["lines"] == 3 and got["labels"] == 3
    assert got["legacy"] == 0
    assert got["aria"] == "Dot size is the number of games at the venue."
    assert got["hidden"] is False
    assert got["emptyHidden"] is True


@pytest.mark.parametrize("n_max", [1, 2, 5, 20, 73])
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
        K.renderMapKey(root, K.buildMapKey(model({n_max}), {{ phone: {str(phone).lower()} }}),
                       {{ theme: 'light' }});
        const box = (r) => ({{ left: r.left, right: r.right, top: r.top, bottom: r.bottom }});
        const labels = Array.from(root.querySelectorAll('.map-key-label')).map((n) => box(n.getBoundingClientRect()));
        const svg = root.querySelector('.map-key-sizes svg').getBoundingClientRect();
        const sizes = root.querySelector('.map-key-sizes').getBoundingClientRect();
        const res = {{ labels, svg: box(svg), sizes: box(sizes), leaders: root.querySelectorAll('svg polyline').length,
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
    assert got["leaders"] == (0 if got["circles"] == 1 else got["circles"])
