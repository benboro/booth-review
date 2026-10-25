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
    assert got["keys"] == ["description", "layout", "sizes", "visible"]


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
def test_size_labels_never_overlap(guarded_page: Page, site_url: str, n_max: int) -> None:
    """Each size step renders one legible label: no label boxes meet, and the circles clear them."""
    got = _run(
        guarded_page,
        site_url,
        f"""
        const root = document.createElement('div');
        root.className = 'map-key';
        root.style.cssText = 'position:fixed;left:20px;top:20px';
        document.body.appendChild(root);
        K.renderMapKey(root, K.buildMapKey(model({n_max}), {{ phone: false }}),
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


_INLINE = """() => {
  const root = document.getElementById('map-key');
  const box = (r) => ({ left: r.left, right: r.right, top: r.top, bottom: r.bottom });
  return {
    text: root.textContent,
    nested: root.querySelectorAll('.map-key-sizes, svg polyline').length,
    refGames: window.__testHooks.getMapModel().refGames,
    items: Array.from(root.querySelectorAll('.map-key-item')).map((it) => ({
      circle: box(it.querySelector('svg circle').getBoundingClientRect()),
      d: it.querySelector('svg').getBoundingClientRect().width,
      label: box(it.querySelector('.map-key-label').getBoundingClientRect()),
      text: it.querySelector('.map-key-label').textContent,
    })),
  };
}"""


def _check_inline(got: dict[str, Any], expected: list[tuple[int, float]]) -> None:
    items = got["items"]
    assert got["nested"] == 0  # no nesting, no leaders
    assert [int(i["text"].split()[0]) for i in items] == [g for g, _ in expected]
    assert items[-1]["text"].endswith(("game", "games"))
    for item, (_, diameter) in zip(items, expected, strict=True):
        assert abs(item["d"] - max(round(diameter + 0.49), 1)) <= 1  # svg is ceil(diameter)
        c, lab = item["circle"], item["label"]
        assert 0 <= lab["left"] - c["right"] <= 8, (c, lab)
        assert c["top"] < lab["bottom"] and c["bottom"] > lab["top"], (c, lab)
    lefts = [i["circle"]["left"] for i in items]
    assert lefts == sorted(lefts)  # largest first, left to right
    diameters = [i["d"] for i in items]
    assert diameters == sorted(diameters, reverse=True)


def _expected(page: Page, ref: int, games: list[int]) -> list[tuple[int, float]]:
    sizes = page.evaluate(
        """async ([games, ref]) => { const V = await import('./modules/map-venues.js');
          return games.map((g) => V.venueDotSize(g, ref).phone); }""",
        [games, ref],
    )
    return list(zip(games, sizes, strict=True))


def test_phone_key_is_an_inline_row(mobile_page: Page, open_app: Any) -> None:
    open_app(mobile_page, "?view=map")
    mobile_page.wait_for_function("() => window.__testHooks.mapRenders >= 1")
    got = mobile_page.evaluate(_INLINE)
    assert got["text"].startswith("Dot size")
    games = [int(i["text"].split()[0]) for i in got["items"]]
    assert len(games) >= 2
    _check_inline(got, _expected(mobile_page, got["refGames"], games))


def test_phone_key_rescales_under_a_narrow_filter(mobile_page: Page, open_app: Any) -> None:
    open_app(mobile_page, "?view=map")
    mobile_page.wait_for_function("() => window.__testHooks.mapRenders >= 1")
    before = mobile_page.evaluate(_INLINE)
    n = mobile_page.evaluate("() => window.__testHooks.mapRenders")
    mobile_page.evaluate("() => window.__testHooks.setState({ seasons: [2019, 2019] })")
    mobile_page.wait_for_function("(n) => window.__testHooks.mapRenders > n", arg=n)
    got = mobile_page.evaluate(_INLINE)
    assert got["refGames"] < before["refGames"]
    games = [int(i["text"].split()[0]) for i in got["items"]]
    _check_inline(got, _expected(mobile_page, got["refGames"], games))
    assert got["items"][0]["d"] == 10  # the busiest filtered venue draws at the phone max


def test_desktop_key_stays_nested(guarded_page: Page, open_app: Any) -> None:
    guarded_page.set_viewport_size({"width": 1440, "height": 900})
    open_app(guarded_page, "?view=map")
    guarded_page.wait_for_function("() => window.__testHooks.mapRenders >= 1")
    got = guarded_page.evaluate(
        """() => {
          const root = document.getElementById('map-key');
          const cs = Array.from(root.querySelectorAll('.map-key-sizes svg circle'))
            .map((c) => c.getBoundingClientRect());
          return { items: root.querySelectorAll('.map-key-item').length,
                   leaders: root.querySelectorAll('svg polyline').length,
                   bottoms: cs.map((r) => Math.round(r.bottom * 10) / 10),
                   centers: cs.map((r) => Math.round((r.left + r.right) / 2 * 10) / 10) };
        }"""
    )
    assert got["items"] == 0
    assert got["leaders"] == len(got["bottoms"]) >= 2
    assert len(set(got["bottoms"])) == 1 and len(set(got["centers"])) == 1
