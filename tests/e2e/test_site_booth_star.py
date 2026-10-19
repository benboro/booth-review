"""D-09/D-10 lead-booth stars (Phase 10, plan 10-08), proven on the synthetic booth overlay.

Overlay A games (merged index): 5 (fox, rated), 8 (disney, rated), 14 (disney, unrated).
B: 9, 13. Other: 4. Conference lead: 15.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

LEAD_RATED = {5, 8}
LEAD_UNRATED = {14}
NEVER_STAR = {9, 13, 4, 15}

_TRACES_JS = """
() => {
  const gd = document.getElementById('chart');
  return gd.data.map((t) => ({
    meta: String(t.meta),
    n: (t.x || []).length,
    customdata: Array.from(t.customdata || []),
    symbol: t.marker && (Array.isArray(t.marker.symbol)
      ? t.marker.symbol.slice() : t.marker.symbol),
    lineWidth: t.marker && t.marker.line && t.marker.line.width,
    color: t.marker && t.marker.color,
    size: t.marker && t.marker.size,
    yaxis: t.yaxis || 'y',
  }));
}
"""

_KEY_JS = """
() => {
  const el = document.getElementById('lead-key');
  const r = el.getBoundingClientRect();
  return {
    off: el.classList.contains('is-off'),
    hidden: el.hidden,
    visibility: getComputedStyle(el).visibility,
    box: [r.x, r.y, r.width, r.height].map((v) => Math.round(v * 10) / 10),
    name: el.getAttribute('aria-label'),
    text: el.textContent.trim(),
  };
}
"""


def _open(
    page: Page,
    serve_booths: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
    query: str = "",
    *,
    booths: bool = True,
) -> list[dict]:
    if booths:
        serve_booths(page)
    open_app(page, query)
    page.wait_for_timeout(150)
    return page.evaluate(_TRACES_JS)


def _by_prefix(traces: list[dict], prefix: str) -> list[dict]:
    return [t for t in traces if t["meta"].startswith(prefix)]


def _points(traces: list[dict], prefix: str) -> set[int]:
    return {i for t in _by_prefix(traces, prefix) for i in t["customdata"]}


def _lead_points(traces: list[dict]) -> set[int]:
    return (
        _points(traces, "lead:")
        | _points(traces, "unrated-lead-filled:")
        | _points(traces, "unrated-lead:")
    )


def test_default_view_draws_a_games_as_stars(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    traces = _open(guarded_page, serve_booths, open_app)
    assert _points(traces, "lead:") == LEAD_RATED
    assert _points(traces, "unrated-lead:") == LEAD_UNRATED
    assert not _points(traces, "unrated-lead-filled:")
    assert _points(traces, "family:") & (LEAD_RATED | LEAD_UNRATED) == set()
    assert _points(traces, "unrated-active:") & LEAD_UNRATED == set()
    for t in traces:
        if t["meta"].startswith(("lead:", "unrated-lead")):
            assert t["symbol"] == "star", t["meta"]
            assert t["lineWidth"] == 0, t["meta"]
        assert "star-open" not in json.dumps(t["symbol"])


def test_hollow_star_is_a_surface_star_over_a_family_halo(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    traces = _open(guarded_page, serve_booths, open_app)
    by_meta = {t["meta"]: t for t in traces}
    halo = by_meta["unrated-lead-halo:disney"]
    hollow = by_meta["unrated-lead:disney"]
    filled = by_meta["lead:disney"]
    assert halo["n"] == hollow["n"] == 1
    assert halo["size"] > hollow["size"] == filled["size"]
    assert halo["color"] == filled["color"] != hollow["color"]
    assert halo["customdata"] == []  # the halo never takes hover or click
    order = [t["meta"] for t in traces]
    assert order.index("unrated-lead-halo:disney") < order.index("unrated-lead:disney")


def test_stars_on_every_channel_of_the_family(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    traces = _open(guarded_page, serve_booths, open_app)
    # 8 is net-a (disney) and 5 is net-b (fox): each sits in its own family's lead trace.
    by_meta = {t["meta"]: t for t in traces}
    assert by_meta["lead:disney"]["customdata"] == [8]
    assert by_meta["lead:fox"]["customdata"] == [5]
    assert by_meta["lead:fox"]["color"] != by_meta["lead:disney"]["color"]


def test_excitement_mode_draws_unrated_a_game_filled(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    traces = _open(guarded_page, serve_booths, open_app, "?y=excitement")
    assert not _points(traces, "unrated-lead:")
    assert 14 in _points(traces, "unrated-lead-filled:") | _points(traces, "lead:")


def test_failed_filter_keeps_a_faded_circle(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    traces = _open(guarded_page, serve_booths, open_app, "?networks=net-b&dots=fade")
    assert 8 not in _lead_points(traces)
    assert 5 in _lead_points(traces)
    inert = next(t for t in _by_prefix(traces, "inert:") if t["meta"].endswith("disney"))
    assert inert["n"] >= 1
    assert inert["symbol"] in (None, "circle")  # unset means the default circle
    assert inert["size"] == 6
    assert not any(t["symbol"] == "star" and t["meta"].startswith("inert") for t in traces)


def test_hide_mode_drops_the_game_entirely(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    traces = _open(guarded_page, serve_booths, open_app, "?networks=net-b&dots=hide")
    assert 8 not in _lead_points(traces)
    assert 5 in _lead_points(traces)


def test_school_filter_keeps_only_passing_a_games_as_stars(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    base = _lead_points(_open(guarded_page, serve_booths, open_app))
    traces = _open(guarded_page, serve_booths, open_app, "?school=northfield")
    stars = _lead_points(traces)
    assert stars <= base
    for t in traces:
        if t["meta"].startswith("inert"):
            assert t["symbol"] in (None, "circle")


def test_one_announcer_highlight_uses_star_for_a_games(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    traces = _open(guarded_page, serve_booths, open_app, "?people=dale-harlow")
    highlight = next(t for t in traces if t["meta"] == "highlight")
    unrated = next(t for t in traces if t["meta"] == "highlight-unrated")
    pairs: dict[int, str] = {}
    for tr in (highlight, unrated):
        symbols = tr["symbol"] if isinstance(tr["symbol"], list) else [tr["symbol"]] * tr["n"]
        pairs.update(dict(zip(tr["customdata"], symbols, strict=True)))
    assert pairs[8] == "star"
    others = {i: s for i, s in pairs.items() if i not in LEAD_RATED | LEAD_UNRATED}
    assert others, "person 0 should have untiered games"
    assert set(others.values()) == {"circle"}
    # Their A game is drawn once, by the highlight overlay, never also as a lead star.
    assert 8 not in _lead_points(traces)


def test_compare_mode_has_no_lead_stars_and_keeps_person_shapes(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    traces = _open(
        guarded_page, serve_booths, open_app, "?people=dale-harlow,pat-rowan&mode=compare"
    )
    for t in traces:
        if t["meta"].startswith(("lead:", "unrated-lead", "unrated-lead-filled")):
            assert t["n"] == 0, t["meta"]
    highlight = next(t for t in traces if t["meta"] == "highlight")
    symbols = set(highlight["symbol"])
    assert symbols & {"square", "diamond", "triangle-up", "star", "circle"}
    assert "circle" in symbols or len(symbols) >= 1


def test_b_other_and_conference_lead_never_get_a_star(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    traces = _open(guarded_page, serve_booths, open_app)
    assert _lead_points(traces) & NEVER_STAR == set()
    assert _points(traces, "family:") | _points(traces, "unrated-active:") >= {9, 13, 4, 15}


@pytest.mark.parametrize(
    "query",
    [
        "?networks=net-b",
        "?networks=net-b&dots=hide",
        "?people=dale-harlow",
        "?people=dale-harlow,pat-rowan&mode=compare",
        "?y=excitement",
        "?axis=date",
    ],
)
def test_trace_count_is_constant(
    guarded_page: Page, serve_booths: Callable, open_app: Callable, query: str
) -> None:
    default = _open(guarded_page, serve_booths, open_app)
    other = _open(guarded_page, serve_booths, open_app, query)

    # The pre-existing compare halo trace appears only when a non-circle highlight exists;
    # the new lead traces are always present.
    def count(traces: list[dict]) -> int:
        return len([t for t in traces if t["meta"] != "highlight-halo"])

    assert count(other) == count(default)
    lead_metas = lambda ts: [t["meta"] for t in ts if "lead" in t["meta"]]  # noqa: E731
    assert lead_metas(other) == lead_metas(default)


def test_key_shows_with_lead_stars_and_hides_in_compare_without_shifting(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    _open(guarded_page, serve_booths, open_app)
    shown = guarded_page.evaluate(_KEY_JS)
    assert shown["visibility"] == "visible"
    assert "Lead booth" in shown["text"]
    assert shown["name"] == "Called by the lead booth for its network family"
    _open(guarded_page, serve_booths, open_app, "?people=dale-harlow,pat-rowan&mode=compare")
    compare = guarded_page.evaluate(_KEY_JS)
    assert compare["visibility"] == "hidden"
    assert compare["box"] == shown["box"]


def test_key_is_hidden_without_booth_data(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    _open(guarded_page, serve_booths, open_app, booths=False)
    plain = guarded_page.evaluate(_KEY_JS)
    assert plain["visibility"] == "hidden"
    assert plain["box"][3] > 0  # the space stays reserved


def test_map_tab_draws_no_star(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    serve_booths(guarded_page)
    open_app(guarded_page, "?view=map")
    guarded_page.wait_for_function(
        "document.getElementById('map-chart') && document.getElementById('map-chart').data"
    )
    assert guarded_page.evaluate(_KEY_JS)["hidden"] is True
    symbols = guarded_page.evaluate(
        """() => {
          const gd = document.getElementById('map-chart');
          const out = [];
          for (const t of (gd && gd.data) || []) {
            const s = t.marker && t.marker.symbol;
            if (s) out.push(...(Array.isArray(s) ? s : [s]));
          }
          return out;
        }"""
    )
    assert "star" not in symbols


def test_rated_lead_star_has_a_surface_casing_drawn_beneath_it(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    traces = _open(guarded_page, serve_booths, open_app)
    by_meta = {t["meta"]: t for t in traces}
    order = [t["meta"] for t in traces]
    surface = by_meta["unrated-lead:disney"]["color"]
    for family, game in (("disney", 8), ("fox", 5)):
        casing, star = by_meta[f"lead-halo:{family}"], by_meta[f"lead:{family}"]
        assert star["customdata"] == [game]
        assert casing["n"] == star["n"] == 1
        assert casing["customdata"] == []  # the casing never takes hover or click
        assert casing["symbol"] == star["symbol"] == "star"
        assert casing["lineWidth"] == star["lineWidth"] == 0
        assert casing["color"] == surface != star["color"]
        assert (casing["size"], star["size"]) == (18, 14)
        assert order.index(f"lead-halo:{family}") < order.index(f"lead:{family}")
    # The stars and their casings are drawn above every plain dot trace.
    last_dot = max(i for i, m in enumerate(order) if m.startswith(("family:", "unrated-active:")))
    assert min(order.index(f"lead-halo:{f}") for f in ("disney", "fox")) > last_dot


def test_one_announcer_highlight_keeps_the_unrated_lead_star_hollow(
    guarded_page: Page, serve_booths: Callable, open_app: Callable
) -> None:
    default = {t["meta"]: t for t in _open(guarded_page, serve_booths, open_app)}
    surface = default["unrated-lead:disney"]["color"]
    traces = _open(guarded_page, serve_booths, open_app, "?people=casey-lund")
    order = [t["meta"] for t in traces]
    unrated = next(t for t in traces if t["meta"] == "highlight-unrated")
    hole = next(t for t in traces if t["meta"] == "highlight-unrated-hole")
    halo = next(t for t in traces if t["meta"] == "highlight-halo-unrated")
    at = unrated["customdata"].index(14)
    assert unrated["symbol"][at] == "star"
    # Fill, not just symbol: the star is family colored, with a smaller surface star on top.
    assert unrated["color"][at] == default["lead:disney"]["color"] != surface
    assert hole["n"] == 1
    assert hole["color"] == surface
    assert hole["symbol"] == "star"
    assert hole["lineWidth"] == 0
    assert hole["size"][0] < unrated["size"][at]
    assert hole["customdata"] == []
    assert halo["n"] >= 1  # the accent highlight halo is still drawn
    assert order.index("highlight-unrated-hole") == order.index("highlight-unrated") + 1
