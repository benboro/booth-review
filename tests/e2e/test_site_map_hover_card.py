"""Phase 11 D-02: venue hover card, synthetic cards only."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from conftest import weekend_map_raw
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

CREDIT_FRAGMENT = "add up published figures"

_FMT_JS = """
async (values) => {
  const f = await import('./modules/format.js');
  return values.map((v) => f.formatAudienceShort(v));
}
"""

_PIE_JS = """
async ([slices, theme]) => {
  const t = await import('./modules/tooltip.js');
  const p = await import('./modules/palette.js');
  const svg = t.venuePieSvg(slices, theme);
  return {
    viewBox: svg.getAttribute('viewBox'),
    width: svg.getAttribute('width'),
    height: svg.getAttribute('height'),
    aria: svg.getAttribute('aria-hidden'),
    pageBg: p.PAGE_BG[theme],
    colors: p.MAP_FAMILY_COLORS[theme],
    kids: [...svg.children].map((c) => ({
      tag: c.tagName.toLowerCase(),
      attrs: Object.fromEntries([...c.attributes].map((a) => [a.name, a.value])),
    })),
  };
}
"""

_CARD_JS = """
async ([card, opts]) => {
  const t = await import('./modules/tooltip.js');
  const p = await import('./modules/palette.js');
  t.showVenueTooltip(card, opts);
  const el = document.getElementById('chart-tooltip');
  const box = el.getBoundingClientRect();
  return {
    hidden: el.hidden,
    title: el.querySelector('strong.tooltip-title').textContent,
    bold: el.querySelectorAll('b').length,
    heads: [...el.querySelectorAll('thead th')].map((h) => h.textContent),
    rows: [...el.querySelectorAll('tbody tr')].map((r) =>
      [...r.children].map((c) => c.textContent)),
    swatches: [...el.querySelectorAll('.tooltip-swatch')].map((s) => s.style.backgroundColor),
    footnotes: [...el.querySelectorAll('.tooltip-footnote')]
      .map((n) => n.textContent),
    text: el.textContent,
    lastText: el.lastElementChild.textContent,
    lastClass: el.lastElementChild.className,
    hasPie: el.querySelector('.tooltip-venue-body svg') !== null,
    border: el.style.borderColor,
    leaderColor: p.MAP_FAMILY_COLORS[opts.theme][card.leader],
    right: box.right,
    width: box.width,
  };
}
"""


def _card(**over: Any) -> dict[str, Any]:
    card: dict[str, Any] = {
        "title": "Riverbend Field · Fairview, KS",
        "leader": "fox",
        "slices": [{"family": "fox", "games": 3}, {"family": "cbs", "games": 1}],
        "rows": [
            {"family": "fox", "label": "FOX", "games": 3, "viewers": 50630000},
            {"family": "cbs", "label": "CBS", "games": 1, "viewers": None},
        ],
        "hasMissingViewers": True,
        "subjectLines": [{"text": "Best game: A vs B", "kind": "body"}],
    }
    card.update(over)
    return card


def _show(page: Page, card: dict[str, Any], **opts: Any) -> dict[str, Any]:
    full = {"theme": "light", "clientX": 100, "clientY": 100, "hint": "Click to list these games"}
    full.update(opts)
    result: dict[str, Any] = page.evaluate(_CARD_JS, [card, full])
    return result


def test_audience_short(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    open_app(guarded_page, "")
    values = [950, 900000, 12500, 999960, 1000000, 50630000, 3000000]
    out = guarded_page.evaluate(_FMT_JS, values)
    assert out == ["950", "900K", "12.5K", "1MM", "1MM", "50.6MM", "3MM"]


def test_pie_single_slice_is_circle(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    r = guarded_page.evaluate(_PIE_JS, [[{"family": "fox", "games": 5}], "light"])
    assert (r["viewBox"], r["width"], r["height"], r["aria"]) == ("0 0 48 48", "48", "48", "true")
    assert len(r["kids"]) == 1
    kid = r["kids"][0]
    assert kid["tag"] == "circle"
    assert kid["attrs"]["r"] == "22"
    assert kid["attrs"]["fill"] == r["colors"]["fox"]
    assert "stroke" not in kid["attrs"]


def test_pie_slices_clockwise_from_noon(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    slices = [
        {"family": "fox", "games": 6},
        {"family": "cbs", "games": 3},
        {"family": "nbc", "games": 1},
    ]
    r = guarded_page.evaluate(_PIE_JS, [slices, "dark"])
    assert [k["tag"] for k in r["kids"]] == ["path"] * 3
    first = r["kids"][0]["attrs"]
    assert first["d"].startswith("M24 24 L24 2 A22 22 0 1 1 ")
    assert r["kids"][1]["attrs"]["d"].split("A22 22 0 ")[1].startswith("0 1 ")
    for kid, s in zip(r["kids"], slices, strict=True):
        assert kid["attrs"]["stroke"] == r["pageBg"]
        assert kid["attrs"]["stroke-width"] == "1"
        assert kid["attrs"]["fill"] == r["colors"][s["family"]]


def test_card_renders_table_and_text_only(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    r = _show(guarded_page, _card(title="<b>Riverbend</b> · Fairview, KS"))
    assert r["hidden"] is False
    assert r["title"] == "<b>Riverbend</b> · Fairview, KS"
    assert r["bold"] == 0
    assert r["hasPie"] is True
    assert r["heads"] == ["", "Games", "Viewers"]
    assert r["rows"] == [["FOX", "3", "50.6MM"], ["CBS", "1", "-"]]
    assert r["footnotes"] == ["- no viewer figure listed"]
    assert r["lastText"] == "Click to list these games"
    assert "tooltip-hint" in r["lastClass"]
    assert r["border"] == guarded_page.evaluate(
        "(c) => { const d = document.createElement('div'); d.style.borderColor = c;"
        " return d.style.borderColor; }",
        r["leaderColor"],
    )


def test_card_other_row_uses_neutral_swatch(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    rows = [
        {"family": "fox", "label": "FOX", "games": 2, "viewers": 900000},
        {"family": None, "label": "Other", "games": 1, "viewers": 12500},
    ]
    r = _show(guarded_page, _card(rows=rows, hasMissingViewers=False))
    assert r["rows"] == [["FOX", "2", "900K"], ["Other", "1", "12.5K"]]
    assert r["footnotes"] == []
    assert r["swatches"][1] == "rgb(179, 170, 156)"


def test_card_has_no_credit_sentence(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Phase 17.1 D-07a: per-game credits live in the games table, not the hover card."""
    open_app(guarded_page, "")
    with_viewers = _show(guarded_page, _card())
    assert CREDIT_FRAGMENT not in with_viewers["text"]
    assert with_viewers["footnotes"] == ["- no viewer figure listed"]
    rows = [{"family": "fox", "label": "FOX", "games": 3, "viewers": None}]
    without = _show(guarded_page, _card(rows=rows))
    assert CREDIT_FRAGMENT not in without["text"]
    assert without["rows"] == [["FOX", "3", "-"]]


_PARTIAL_JS = """
async () => {
  const M = await import('./modules/map-model.js');
  const P = await import('./modules/palette.js');
  const NF = P.FAMILY_ORDER.length;
  const counts = Array(NF).fill(0), rated = Array(NF).fill(0), viewers = Array(NF).fill(0);
  // fox: 4 games, 1 rated; cbs: 2 games, all rated; nbc: 1 game, none rated
  counts[P.FAMILY_ORDER.indexOf('fox')] = 4; rated[P.FAMILY_ORDER.indexOf('fox')] = 1;
  viewers[P.FAMILY_ORDER.indexOf('fox')] = 3100000;
  counts[P.FAMILY_ORDER.indexOf('cbs')] = 2; rated[P.FAMILY_ORDER.indexOf('cbs')] = 2;
  viewers[P.FAMILY_ORDER.indexOf('cbs')] = 5000000;
  counts[P.FAMILY_ORDER.indexOf('nbc')] = 1;
  const fake = {venueModel: {byKey: new Map([['x', {
    index: 0, leader: 'fox', counts, viewers, ratedCounts: rated,
  }]])}, subjects: [], subjectVenueGames: []};
  const data = {lookups: {venues: [{name: 'Riverbend Field', city: 'Fairview', state: 'KS'}]}};
  const card = M.venueCard(data, fake, 'x');
  return {rows: card.rows.map((r) => [r.label, r.partial]), partial: card.hasPartialViewers};
}
"""


def test_card_flags_rows_whose_viewers_cover_only_some_games(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    got = guarded_page.evaluate(_PARTIAL_JS)
    assert got["rows"] == [["FOX/FS1/BTN", True], ["CBS/CBSSN", False], ["NBC/Peacock", False]]
    assert got["partial"] is True


def test_card_marks_partial_rows_and_explains_the_mark(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    rows = [
        {"family": "fox", "label": "FOX", "games": 12, "viewers": 3100000, "partial": True},
        {"family": "cbs", "label": "CBS", "games": 1, "viewers": 900000, "partial": False},
    ]
    r = _show(guarded_page, _card(rows=rows, hasMissingViewers=False, hasPartialViewers=True))
    assert r["rows"] == [["FOX", "12", "3.1MM*"], ["CBS", "1", "900K"]]
    assert r["footnotes"] == ["* Viewers cover rated games only"]
    assert r["width"] <= 296
    clean = _show(guarded_page, _card(rows=rows, hasMissingViewers=False))
    assert clean["footnotes"] == []


def test_card_stays_on_phone_screen(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(mobile_page, "")
    r = _show(mobile_page, _card(), clientX=380, clientY=300)
    assert r["right"] <= 390
    assert r["width"] <= 296


# ---------------------------------------------------------------- live Map hover

OpenApp = Callable[[Page, str], None]

_RING_JS = """() => {
  const gd = document.getElementById('map-chart');
  const t = gd.data.find((d) => d.name === 'venue-dots');
  return {width: t.marker.line.width, color: t.marker.line.color};
}"""


def _open_map(page: Page, open_app: OpenApp, query: str = "?view=map") -> None:
    open_app(page, query)
    page.wait_for_function("() => window.__testHooks.mapRenders >= 1")
    page.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")


def _pixel(page: Page, x: float, y: float) -> tuple[float, float]:
    px, py = page.evaluate(
        """([x, y]) => {
          const gd = document.getElementById('map-chart');
          const r = gd.getBoundingClientRect();
          const fl = gd._fullLayout;
          return [r.left + fl.xaxis._offset + fl.xaxis.l2p(x),
                  r.top + fl.yaxis._offset + fl.yaxis.l2p(y)];
        }""",
        [x, y],
    )
    return px, py


def _hover(page: Page, x: float, y: float) -> None:
    # The framed module sits below the fold at 900px; bring the map on screen first.
    page.evaluate("() => document.getElementById('map-chart').scrollIntoView({block: 'center'})")
    page.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
    px, py = _pixel(page, x, y)
    page.mouse.move(px - 60, py - 60)
    page.mouse.move(px, py, steps=5)
    page.wait_for_timeout(250)


def _tooltip(page: Page) -> dict[str, Any] | None:
    result: dict[str, Any] | None = page.evaluate(
        """() => { const el = document.getElementById('chart-tooltip');
          if (!el || el.hidden) return null;
          return {kind: el.dataset.kind, text: el.textContent,
                  title: el.querySelector('strong.tooltip-title')?.textContent,
                  pie: el.querySelector('.tooltip-venue-body svg') !== null,
                  hint: el.lastElementChild.textContent,
                  rows: [...el.querySelectorAll('tbody tr')].map((r) =>
                    [...r.children].map((c) => c.textContent))}; }"""
    )
    return result


def _model(page: Page) -> dict[str, Any]:
    model: dict[str, Any] = page.evaluate("() => window.__testHooks.getMapModel()")
    return model


def _base_dots(page: Page) -> list[dict[str, Any]]:
    return [d for d in _model(page)["venueDots"] if d["tier"] == "base"]


def test_desktop_hover_shows_card_and_hover_ring(guarded_page: Page, open_app: OpenApp) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    _open_map(guarded_page, open_app)
    dots = _model(guarded_page)["venueDots"]
    # Hover the largest dot; the model orders dots by score so index 0 is the top one.
    _hover(guarded_page, dots[0]["x"], dots[0]["y"])
    tip = _tooltip(guarded_page)
    assert tip is not None
    assert tip["kind"] == "venue"
    assert tip["title"]
    assert tip["pie"] is True
    assert tip["hint"] == "Click to list these games"
    ring = guarded_page.evaluate(_RING_JS)
    bg = guarded_page.evaluate("async () => (await import('./modules/palette.js')).PAGE_BG.light")
    assert ring["width"][0] == 2
    assert ring["color"][0] == bg
    assert all(w == 1 for w in ring["width"][1:])
    guarded_page.mouse.move(5, 5, steps=4)
    guarded_page.wait_for_timeout(250)
    assert _tooltip(guarded_page) is None
    assert all(w == 1 for w in guarded_page.evaluate(_RING_JS)["width"])


def test_hovering_a_faded_dot_shows_no_card(guarded_page: Page, open_app: OpenApp) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    _open_map(guarded_page, open_app, "?view=map&school=boulder-pass")
    faded = _model(guarded_page)["venueFaded"]
    assert faded
    _hover(guarded_page, faded[0]["x"], faded[0]["y"])
    assert _tooltip(guarded_page) is None


def test_hovering_an_edge_marker_shows_its_card(guarded_page: Page, open_app: OpenApp) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    _open_map(guarded_page, open_app)
    nassau = next(m for m in _model(guarded_page)["markers"] if m["label"] == "Nassau")
    _hover(guarded_page, nassau["x"], nassau["y"])
    tip = _tooltip(guarded_page)
    assert tip is not None
    assert tip["title"] == "Nassau"
    assert tip["pie"] is True


def test_unrated_and_rated_venues_show_dash_and_no_credit_sentence(
    guarded_page: Page, open_app: OpenApp, serve_map_venues: Callable[[Page], None]
) -> None:
    serve_map_venues(guarded_page)
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    _open_map(guarded_page, open_app)
    texts: list[str] = []
    for dot in _model(guarded_page)["venueDots"]:
        _hover(guarded_page, dot["x"], dot["y"])
        tip = _tooltip(guarded_page)
        if tip:
            texts.append(tip["text"])
    assert any("- no viewer figure listed" in t for t in texts)
    assert not any(CREDIT_FRAGMENT in t for t in texts)


def test_click_lists_games_with_source_credits(guarded_page: Page, open_app: OpenApp) -> None:
    """D-07a: attribution stays reachable from the map; a dot click fills the games table."""
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    _open_map(guarded_page, open_app)
    dot = _model(guarded_page)["venueDots"][0]
    _hover(guarded_page, dot["x"], dot["y"])
    px, py = _pixel(guarded_page, dot["x"], dot["y"])
    guarded_page.mouse.click(px, py)
    guarded_page.wait_for_function(f"() => location.search.includes('venue={dot['key']}')")
    rows = guarded_page.locator("#matched-games tbody tr")
    assert rows.count() > 0
    assert guarded_page.locator("#matched-games tbody tr a[href^='http']").count() > 0


def test_phone_first_tap_shows_card_second_tap_filters(
    mobile_page: Page, open_app: OpenApp
) -> None:
    mobile_page.set_viewport_size({"width": 360, "height": 800})
    _open_map(mobile_page, open_app)
    mobile_page.evaluate("() => document.getElementById('map-chart').scrollIntoView()")
    dot = _model(mobile_page)["venueDots"][0]
    px, py = _pixel(mobile_page, dot["x"], dot["y"])
    mobile_page.touchscreen.tap(px, py)
    mobile_page.wait_for_function(
        "() => { const e = document.getElementById('chart-tooltip'); return e && !e.hidden; }"
    )
    tip = _tooltip(mobile_page)
    assert tip is not None
    assert tip["kind"] == "venue"
    assert tip["hint"] == "Tap again to list these games"
    mobile_page.wait_for_timeout(450)
    mobile_page.touchscreen.tap(px, py)
    mobile_page.wait_for_function("() => document.getElementById('chart-tooltip').hidden")
    mobile_page.wait_for_function("() => location.search.includes('venue=')")


def test_phone_background_tap_clears_the_card_and_rearms_the_first_tap(
    mobile_page: Page, open_app: OpenApp
) -> None:
    """UI-SPEC: a tap elsewhere on the map clears only the card. dot, background, same dot
    shows the card again (first tap) and does not filter."""
    mobile_page.set_viewport_size({"width": 360, "height": 800})
    _open_map(mobile_page, open_app)
    mobile_page.evaluate("() => document.getElementById('map-chart').scrollIntoView()")
    model = _model(mobile_page)
    dot = model["venueDots"][0]
    px, py = _pixel(mobile_page, dot["x"], dot["y"])
    # The plot point farthest from every dot and edge marker is a safe background tap.
    spots = [(d["x"], d["y"]) for d in model["venueDots"] + model["venueFaded"] + model["markers"]]
    best = max(
        ((x, y) for x in range(40, 940, 30) for y in range(60, 560, 30)),
        key=lambda c: min((c[0] - sx) ** 2 + (c[1] - sy) ** 2 for sx, sy in spots),
    )
    bx, by = _pixel(mobile_page, *best)
    card_open = (
        "() => { const e = document.getElementById('chart-tooltip'); return e && !e.hidden; }"
    )

    mobile_page.touchscreen.tap(px, py)
    mobile_page.wait_for_function(card_open)
    mobile_page.wait_for_timeout(450)
    mobile_page.touchscreen.tap(bx, by)
    mobile_page.wait_for_function("() => document.getElementById('chart-tooltip').hidden")
    assert "venue=" not in mobile_page.evaluate("() => location.search")
    mobile_page.wait_for_timeout(450)
    mobile_page.touchscreen.tap(px, py)
    mobile_page.wait_for_function(card_open)
    tip = _tooltip(mobile_page)
    assert tip is not None
    assert tip["hint"] == "Tap again to list these games"
    mobile_page.wait_for_timeout(450)
    assert "venue=" not in mobile_page.evaluate("() => location.search")


def test_phone_late_compatibility_click_does_not_filter(
    mobile_page: Page, open_app: OpenApp
) -> None:
    """One tap reaches Plotly twice (touchstart, then the compatibility mousedown). On a slow
    runner the second is handled more than the old 350 ms debounce later; it must still not
    count as a second tap. A real main-thread stall after the first click reproduces that."""
    mobile_page.set_viewport_size({"width": 360, "height": 800})
    _open_map(mobile_page, open_app)
    mobile_page.evaluate("() => document.getElementById('map-chart').scrollIntoView()")
    dot = _model(mobile_page)["venueDots"][0]
    px, py = _pixel(mobile_page, dot["x"], dot["y"])
    mobile_page.evaluate(
        """() => {
          const gd = document.getElementById('map-chart');
          let armed = true;
          gd.on('plotly_click', () => {
            if (!armed) return;
            armed = false;
            const t = performance.now();
            while (performance.now() - t < 450) { /* stall the renderer */ }
          });
        }"""
    )
    mobile_page.touchscreen.tap(px, py)
    # No wait for the card first: the stalled renderer would hide a late filter's effect from it.
    mobile_page.wait_for_timeout(900)
    assert "venue=" not in mobile_page.evaluate("() => location.search")
    tip = _tooltip(mobile_page)
    assert tip is not None
    assert tip["hint"] == "Tap again to list these games"


def _phone_dot(page: Page, open_app: OpenApp) -> tuple[float, float]:
    page.set_viewport_size({"width": 360, "height": 800})
    _open_map(page, open_app)
    page.evaluate("() => document.getElementById('map-chart').scrollIntoView()")
    dot = _model(page)["venueDots"][0]
    return _pixel(page, dot["x"], dot["y"])


_COUNT_CLICKS = """() => { window.__mapClicks = [];
  document.getElementById('map-chart').on('plotly_click',
    (e) => window.__mapClicks.push(e.event && e.event.type)); }"""


def test_phone_tap_reaches_plotly_once(mobile_page: Page, open_app: OpenApp) -> None:
    """The touch pointerdown is cancelled, so the browser sends no compatibility mouse click:
    one tap is one plotly_click, and no queue order or delay can make it count twice."""
    px, py = _phone_dot(mobile_page, open_app)
    mobile_page.evaluate(_COUNT_CLICKS)
    mobile_page.touchscreen.tap(px, py)
    mobile_page.wait_for_function("() => window.__mapClicks.length > 0")
    mobile_page.wait_for_timeout(600)
    assert mobile_page.evaluate("() => window.__mapClicks") == ["touchstart"]


_REPLAY_CLICK = """([x, y]) => {
  const gd = document.getElementById('map-chart');
  const first = window.__firstClick;
  gd.emit('plotly_click', { points: first.points,
    event: { type: 'touchstart', changedTouches: [{ clientX: x, clientY: y }] } });
}"""


@pytest.mark.parametrize("on_dot", [False, True], ids=["background", "dot"])
def test_phone_stale_plotly_point_is_judged_by_the_touch(
    mobile_page: Page, open_app: OpenApp, on_dot: bool
) -> None:
    """Plotly skips its hover pass for a touch within 50 ms of the last and then clicks the
    previous point, so a quick background tap reported the dot tapped before it and filtered
    (the CI flake on PR #84). Replaying that click deterministically: with the touch on the
    background it must not filter; with the touch on the dot it is the second tap and does."""
    px, py = _phone_dot(mobile_page, open_app)
    box = mobile_page.locator("#map-chart").bounding_box()
    assert box is not None
    mobile_page.evaluate(
        """() => document.getElementById('map-chart').on('plotly_click', (e) => {
             window.__firstClick ??= e; })"""
    )
    mobile_page.touchscreen.tap(px, py)
    mobile_page.wait_for_function("() => window.__firstClick != null")
    at = [px, py] if on_dot else [box["x"] + 8, box["y"] + 8]
    mobile_page.evaluate(_REPLAY_CLICK, at)
    search = mobile_page.evaluate("() => location.search")
    assert ("venue=" in search) is on_dot


@pytest.mark.parametrize("offset", [7, 24], ids=["overlapping", "beside"])
def test_phone_stale_point_next_to_the_tapped_venue_goes_to_the_venue_touched(
    mobile_page: Page, open_app: OpenApp, offset: float
) -> None:
    """A quick tap on venue B beside venue A can come back as Plotly's stale A point. The
    tap belongs to B, the venue under the finger: it opens B's card, and the next tap on B
    lists B's games, never A's. Covers hit targets that overlap (7 px) and that touch (24 px)."""
    mobile_page.set_viewport_size({"width": 360, "height": 800})
    _open_map(mobile_page, open_app)
    dots = _model(mobile_page)["venueDots"]
    a, b = dots[0], dots[1]
    moved = _shrink(mobile_page, b["key"], mobile=True, near=a["key"], offset=offset)
    mobile_page.evaluate("() => document.getElementById('map-chart').scrollIntoView()")
    ax, ay = _pixel(mobile_page, a["x"], a["y"])
    bx, by = _pixel(mobile_page, moved["x"], moved["y"])
    mobile_page.evaluate(
        """() => document.getElementById('map-chart').on('plotly_click', (e) => {
             window.__firstClick ??= e; })"""
    )
    mobile_page.touchscreen.tap(ax, ay)
    mobile_page.wait_for_function("() => window.__firstClick != null")
    assert mobile_page.evaluate("() => window.__firstClick.points[0].customdata") == a["key"]
    mobile_page.evaluate(_REPLAY_CLICK, [bx, by])
    assert "venue=" not in mobile_page.evaluate("() => location.search")
    tip = _tooltip(mobile_page)
    assert tip is not None
    assert tip["hint"] == "Tap again to list these games"
    mobile_page.evaluate(_REPLAY_CLICK, [bx, by])
    search = mobile_page.evaluate("() => location.search")
    assert f"venue={b['key']}" in search, search


def test_phone_tap_inside_the_background_wait_rearms_first(
    mobile_page: Page, open_app: OpenApp
) -> None:
    """Tapping the dot again before the background tap's check has run must find the card
    cleared and show it again, not filter."""
    px, py = _phone_dot(mobile_page, open_app)
    box = mobile_page.locator("#map-chart").bounding_box()
    assert box is not None
    mobile_page.touchscreen.tap(px, py)
    mobile_page.wait_for_function(
        "() => { const e = document.getElementById('chart-tooltip'); return e && !e.hidden; }"
    )
    mobile_page.touchscreen.tap(box["x"] + 8, box["y"] + 8)
    mobile_page.wait_for_timeout(70)
    mobile_page.touchscreen.tap(px, py)
    mobile_page.wait_for_timeout(400)
    assert "venue=" not in mobile_page.evaluate("() => location.search")
    tip = _tooltip(mobile_page)
    assert tip is not None
    assert tip["hint"] == "Tap again to list these games"


def test_phone_mouse_click_right_after_a_tap_counts(mobile_page: Page, open_app: OpenApp) -> None:
    """A mouse paired with a phone is not held back by any time window: a finger tap shows
    the card, and a mouse click on the same dot straight after lists its games."""
    px, py = _phone_dot(mobile_page, open_app)
    mobile_page.touchscreen.tap(px, py)
    mobile_page.wait_for_function(
        "() => { const e = document.getElementById('chart-tooltip'); return e && !e.hidden; }"
    )
    assert "venue=" not in mobile_page.evaluate("() => location.search")
    mobile_page.mouse.click(px, py)
    mobile_page.wait_for_function("() => location.search.includes('venue=')")


def test_phone_two_quick_mouse_clicks_list_the_games(mobile_page: Page, open_app: OpenApp) -> None:
    """Two real mouse clicks on a phone, back to back, are the card then the list."""
    px, py = _phone_dot(mobile_page, open_app)
    mobile_page.evaluate(_COUNT_CLICKS)
    mobile_page.mouse.click(px, py)
    mobile_page.mouse.click(px, py)
    mobile_page.wait_for_function("() => location.search.includes('venue=')")
    assert mobile_page.evaluate("() => window.__mapClicks") == ["mousedown", "mousedown"]


# -- Phase 17.1 D-16: an invisible 12px hit target under every small dot ----------------------

_SHRINK_JS = """async ([key, size, mobile, near, offsetPx]) => {
  // Re-draws the live map with one real venue shrunk to `size` px (a 1-game dot); when `near`
  // names another venue, that dot's centre is moved under the large one so the circles overlap.
  const C = await import('./modules/map-chart.js');
  const G = await import('./vendor/us-states-albers.js');
  const gd = document.getElementById('map-chart');
  const model = structuredClone(window.__testHooks.getMapModel());
  const small = model.venueDots.find((d) => d.key === key);
  small.size = {desktop: size, phone: size};
  if (near) {
    const big = model.venueDots.find((d) => d.key === near);
    const unit = gd._fullLayout.xaxis.l2p(1) - gd._fullLayout.xaxis.l2p(0);
    small.x = big.x + offsetPx / unit;
    small.y = big.y;
  }
  const env = {theme: 'light', mobile, splat: false};
  await C.renderMap(gd, C.buildMapFigure(model, G.US_STATES, env));
  return {x: small.x, y: small.y};
}"""


def _shrink(
    page: Page, key: str, *, mobile: bool = False, near: str | None = None, offset: float = 0
) -> dict[str, float]:
    result: dict[str, float] = page.evaluate(_SHRINK_JS, [key, 3.3, mobile, near, offset])
    page.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
    return result


def _hover_title(page: Page, x: float, y: float) -> str | None:
    _hover(page, x, y)
    tip = _tooltip(page)
    return tip["title"] if tip else None


def test_small_dot_hover_target_reaches_5px_from_its_centre(
    guarded_page: Page, open_app: OpenApp
) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    _open_map(guarded_page, open_app)
    dot = _model(guarded_page)["venueDots"][-1]
    expected = _hover_title(guarded_page, dot["x"], dot["y"])
    assert expected
    guarded_page.mouse.move(5, 5, steps=3)
    _shrink(guarded_page, dot["key"])
    px, py = _pixel(guarded_page, dot["x"], dot["y"])
    guarded_page.mouse.move(px + 5 - 60, py - 60)
    guarded_page.mouse.move(px + 5, py, steps=5)
    guarded_page.wait_for_timeout(250)
    tip = _tooltip(guarded_page)
    assert tip is not None and tip["title"] == expected
    # Far outside the 12px target nothing opens.
    guarded_page.mouse.move(px + 40, py + 40, steps=4)
    guarded_page.wait_for_timeout(250)
    assert _tooltip(guarded_page) is None


def test_small_dot_click_5px_from_its_centre_lists_its_games(
    guarded_page: Page, open_app: OpenApp
) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    _open_map(guarded_page, open_app)
    dot = _model(guarded_page)["venueDots"][-1]
    _shrink(guarded_page, dot["key"])
    guarded_page.evaluate("() => document.getElementById('map-chart').scrollIntoView()")
    px, py = _pixel(guarded_page, dot["x"], dot["y"])
    guarded_page.mouse.move(px - 40, py)
    guarded_page.mouse.move(px + 5, py, steps=4)
    guarded_page.mouse.click(px + 5, py)
    guarded_page.wait_for_function(f"() => location.search.includes('venue={dot['key']}')")


def test_small_dot_on_top_of_a_large_neighbour_wins_at_its_own_centre(
    guarded_page: Page, open_app: OpenApp
) -> None:
    guarded_page.set_viewport_size({"width": 1280, "height": 900})
    _open_map(guarded_page, open_app)
    dots = _model(guarded_page)["venueDots"]
    big, small = dots[0], dots[-1]
    big_title = _hover_title(guarded_page, big["x"], big["y"])
    small_title = _hover_title(guarded_page, small["x"], small["y"])
    assert big_title and small_title and big_title != small_title
    guarded_page.mouse.move(5, 5, steps=3)
    # The 3.3px dot sits 10px from the 28px dot's centre, drawn inside it.
    spot = _shrink(guarded_page, small["key"], near=big["key"], offset=10)
    assert _hover_title(guarded_page, spot["x"], spot["y"]) == small_title
    assert _hover_title(guarded_page, big["x"], big["y"]) == big_title


def test_phone_tap_5px_off_a_small_dot_opens_its_card(mobile_page: Page, open_app: OpenApp) -> None:
    mobile_page.set_viewport_size({"width": 390, "height": 800})
    _open_map(mobile_page, open_app)
    dot = _model(mobile_page)["venueDots"][-1]
    _shrink(mobile_page, dot["key"], mobile=True)
    mobile_page.evaluate("() => document.getElementById('map-chart').scrollIntoView()")
    px, py = _pixel(mobile_page, dot["x"], dot["y"])
    mobile_page.touchscreen.tap(px + 5, py)
    mobile_page.wait_for_function(
        "() => { const e = document.getElementById('chart-tooltip'); return e && !e.hidden; }"
    )
    tip = _tooltip(mobile_page)
    assert tip is not None and tip["kind"] == "venue"


def test_hit_trace_draws_nothing_visible(guarded_page: Page, open_app: OpenApp) -> None:
    _open_map(guarded_page, open_app)
    got = guarded_page.evaluate(
        """() => {
          const gd = document.getElementById('map-chart');
          const n = gd.data.find((t) => t.name === 'venue-hits').x.length;
          const fills = [...gd.querySelectorAll('.scatterlayer g.trace')]
            .map((g) => [...g.querySelectorAll('path.point')]
              .map((p) => {
                const st = getComputedStyle(p);
                return st.fillOpacity === '0' || st.fill === 'none' ? 'clear' : st.fill;
              }));
          return {n, twins: fills.filter((f) => f.length === n)};
        }"""
    )
    transparent = [f for f in got["twins"] if all(c == "clear" for c in f)]
    assert transparent, got


# ---------------------------------------------------------------- Phase 28 game card marks

_GAME_CARD_JS = """
async ([card, opts]) => {
  const t = await import('./modules/tooltip.js');
  t.showGameTooltip(card, opts);
  const el = document.getElementById('chart-tooltip');
  const textBox = (node) => {
    if (!node) return null;
    const r = document.createRange();
    r.selectNodeContents(node);
    const b = r.getBoundingClientRect();
    return {left: b.left, right: b.right, top: b.top, bottom: b.bottom};
  };
  const box = (node) => {
    if (!node) return null;
    const b = node.getBoundingClientRect();
    return {left: b.left, right: b.right, top: b.top, bottom: b.bottom};
  };
  const line = el.querySelector('.cf-card-line');
  return {
    rkHas: el.classList.contains('rk-has'),
    badges: el.querySelectorAll('.rk-badge').length,
    role: el.querySelector('.rk-badge svg')?.getAttribute('role') ?? null,
    label: el.querySelector('.rk-badge svg')?.getAttribute('aria-label') ?? null,
    kids: [...el.children].map((c) => c.className),
    line: line ? [...line.childNodes].map((n) => (n.nodeType === 3
      ? {text: n.textContent}
      : {tag: n.tagName.toLowerCase(), cls: n.className, alt: n.getAttribute('alt'),
         src: n.getAttribute('src'), text: n.textContent})) : null,
    lineImgs: line ? [...line.querySelectorAll('img')].map((i) => {
      const b = i.getBoundingClientRect();
      const cs = getComputedStyle(i);
      return {w: b.width, h: b.height, scale: Number(i.style.getPropertyValue('--cf-scale')),
              box: b.height + parseFloat(cs.marginTop) + parseFloat(cs.marginBottom)};
    }) : [],
    lineH: line ? line.getBoundingClientRect().height : null,
    cardH: el.getBoundingClientRect().height,
    matchup: el.querySelector('.tooltip-game-matchup').textContent,
    booth: el.querySelector('.tooltip-game-booth').textContent,
    width: el.getBoundingClientRect().width,
    badge: box(el.querySelector('.rk-badge')),
    matchupText: textBox(el.querySelector('.tooltip-game-matchup')),
    boothText: textBox(el.querySelector('.tooltip-game-booth')),
    bold: el.querySelectorAll('b').length,
  };
}
"""

_OTHER_TIP_JS = """
async (which) => {
  const t = await import('./modules/tooltip.js');
  const opts = {theme: 'light', clientX: 100, clientY: 100};
  if (which === 'venue') {
    t.showVenueTooltip({title: 'V', leader: 'fox', slices: [{family: 'fox', games: 1}],
      rows: [{family: 'fox', label: 'FOX', games: 1, viewers: 1000000}],
      hasMissingViewers: false, subjectLines: []}, {...opts, hint: 'h'});
  } else if (which === 'text') {
    t.showTextTooltip([{text: 'Title', kind: 'title'}], {...opts, borderColor: '#000'});
  } else {
    t.showTooltip(window.__testHooks.data, 0, {...opts, axis: 'spread', selected: new Set()});
  }
  const el = document.getElementById('chart-tooltip');
  return {rkHas: el.classList.contains('rk-has'), badges: el.querySelectorAll('.rk-badge').length,
    padRight: getComputedStyle(el).paddingRight};
}
"""


def _game_card(**over: Any) -> dict[str, Any]:
    card: dict[str, Any] = {
        "matchup": "#20 Ironpeak @ #5 Stonebridge",
        "booth": {"star": True, "text": "Pat Rowan · Sam Delgado", "weight": 600},
        "kickoff": "7:30 pm ET, Alpha Sports",
        "venue": "Stonebridge Stadium, Pasadena, CA",
        "family": "disney",
        "ranked": False,
        "conf": {"away": "SEC", "home": "Pac-12", "season": 2019},
    }
    card.update(over)
    return card


def _show_game(page: Page, card: dict[str, Any], **opts: Any) -> dict[str, Any]:
    full: dict[str, Any] = {"theme": "light", "clientX": 200, "clientY": 200}
    full.update(opts)
    result: dict[str, Any] = page.evaluate(_GAME_CARD_JS, [card, full])
    return result


def _desk(page: Page, open_app: OpenApp) -> Page:
    page.set_viewport_size({"width": 1440, "height": 900})
    open_app(page, "")
    return page


def test_game_card_badge_only_for_a_ranked_card(guarded_page: Page, open_app: OpenApp) -> None:
    page = _desk(guarded_page, open_app)
    r = _show_game(page, _game_card(ranked=True))
    assert r["rkHas"] is True
    assert r["badges"] == 1
    assert r["role"] == "img"
    assert r["label"] == "Both teams ranked"
    plain = _show_game(page, _game_card(ranked=False))
    assert plain["rkHas"] is False
    assert plain["badges"] == 0


def test_game_card_badge_clears_the_text_boxes(guarded_page: Page, open_app: OpenApp) -> None:
    page = _desk(guarded_page, open_app)
    long = "#20 Ironpeak Polytechnic Institute @ #5 Stonebridge State University"
    r = _show_game(page, _game_card(ranked=True, matchup=long))
    assert r["width"] <= 320
    b = r["badge"]
    assert abs((b["bottom"] - b["top"]) - 25.5) < 0.6
    for text in (r["matchupText"], r["boothText"]):
        overlap_x = text["left"] < b["right"] and b["left"] < text["right"]
        overlap_y = text["top"] < b["bottom"] and b["top"] < text["bottom"]
        assert not (overlap_x and overlap_y)


@pytest.mark.parametrize("which", ["venue", "text", "chart"])
def test_other_tooltips_drop_the_ranked_padding(
    guarded_page: Page, open_app: OpenApp, which: str
) -> None:
    page = _desk(guarded_page, open_app)
    assert _show_game(page, _game_card(ranked=True))["rkHas"] is True
    r = page.evaluate(_OTHER_TIP_JS, which)
    assert r["rkHas"] is False
    assert r["badges"] == 0
    assert r["padRight"] != "43.5px"


def test_game_card_conference_line_is_last_with_era_logos(
    guarded_page: Page, open_app: OpenApp
) -> None:
    page = _desk(guarded_page, open_app)
    r = _show_game(page, _game_card())
    assert r["kids"][-1] == "cf-card-line"
    assert r["kids"][-2] == "tooltip-game-venue"
    line = r["line"]
    assert [n.get("tag") for n in line] == ["img", "span", "img"]
    assert line[0]["alt"] == "SEC"
    assert line[0]["src"].endswith("southeastern-conference-before-2024.svg")
    assert line[1] == {"tag": "span", "cls": "cf-sep", "alt": None, "src": None, "text": "vs."}
    assert line[2]["alt"] == "Pac-12"
    assert line[2]["src"].endswith("pac-12-conference-before-2026.svg")
    # Sized by area: 16px nominal times the scale (SEC 2019 1.13, Pac-12 shield 1.25), in a
    # 16px margin box, at most 48px wide.
    assert [img["scale"] for img in r["lineImgs"]] == [1.13, 1.25]
    for img in r["lineImgs"]:
        assert abs(img["h"] - 16 * img["scale"]) < 0.6
        assert img["box"] == pytest.approx(16, abs=0.01)
        assert img["w"] <= 48
    assert r["matchup"] == "#20 Ironpeak @ #5 Stonebridge"
    assert r["booth"] == "★Pat Rowan · Sam Delgado"


def test_game_card_phone_keeps_open_game_last(mobile_page: Page, open_app: OpenApp) -> None:
    open_app(mobile_page, "")
    r = _show_game(mobile_page, _game_card(ranked=True), phone=True)
    assert r["kids"][-1] == "tt-open-game"
    assert r["kids"][-2] == "cf-card-line"
    assert r["kids"][-3] == "tooltip-game-venue"


def test_game_card_area_sized_logos_never_change_the_line_height(
    guarded_page: Page, open_app: OpenApp
) -> None:
    """D-05: the conference line is as tall with grown shields or shrunk wordmarks as with
    text only, so the card never changes height."""
    page = _desk(guarded_page, open_app)
    text = _show_game(page, _game_card(conf={"away": "Big Sky", "home": "Southland"}))
    assert text["lineImgs"] == []
    for conf in (
        {"away": "Pac-12", "home": "Mountain West", "season": 2026},
        {"away": "Conference USA", "home": "Big Ten", "season": 2019},
    ):
        logos = _show_game(page, _game_card(conf=conf))
        assert len(logos["lineImgs"]) == 2
        assert logos["lineH"] == pytest.approx(text["lineH"], abs=0.01), conf
        assert logos["cardH"] == pytest.approx(text["cardH"], abs=0.01), conf


def test_game_card_same_conference_and_text_fallbacks(
    guarded_page: Page, open_app: OpenApp
) -> None:
    page = _desk(guarded_page, open_app)
    same = _show_game(page, _game_card(conf={"away": "SEC", "home": "SEC", "season": 2026}))
    assert [n.get("tag") for n in same["line"]] == ["img"]
    assert same["line"][0]["src"].endswith("southeastern-conference-2024-present.svg")
    mixed = _show_game(page, _game_card(conf={"away": "Big Sky", "home": "SEC", "season": 2026}))
    assert mixed["line"][0] == {"text": "Big Sky"}
    assert mixed["line"][1]["text"] == "vs."
    assert mixed["line"][2]["alt"] == "SEC"
    none = _show_game(page, _game_card(conf={"away": None, "home": None, "season": 2026}))
    assert none["line"] is None
    assert "cf-card-line" not in none["kids"]
    absent = _show_game(page, _game_card(conf=None))
    assert absent["line"] is None
    one = _show_game(page, _game_card(conf={"away": None, "home": "SEC", "season": 2026}))
    assert one["line"][0] == {"text": "Not recorded"}
    assert one["line"][2]["alt"] == "SEC"


def test_game_card_long_text_fallback_stays_within_320(
    guarded_page: Page, open_app: OpenApp
) -> None:
    page = _desk(guarded_page, open_app)
    conf = {"away": "Southwestern Athletic Conference East", "home": "ACC", "season": 2026}
    r = _show_game(page, _game_card(ranked=True, conf=conf))
    assert r["width"] <= 320
    two = _show_game(page, _game_card(conf={"away": "Conference USA", "home": "ACC"}))
    assert two["width"] <= 320


def test_game_card_hostile_conference_name_is_literal_text(
    guarded_page: Page, open_app: OpenApp
) -> None:
    page = _desk(guarded_page, open_app)
    hostile = "<img src=x onerror=alert(1)><b>x</b>"
    r = _show_game(page, _game_card(conf={"away": hostile, "home": "SEC", "season": 2026}))
    assert r["line"][0] == {"text": hostile}
    assert r["bold"] == 0
    assert (
        page.evaluate("() => document.querySelectorAll('#chart-tooltip img[src=\"x\"]').length")
        == 0
    )


# ---------------------------------------------------------------- Phase 28 live weekend map

_PRIME = "cfb:scheduled:5"

_WK_READY = """() => {
  const gd = document.querySelector('.wk-map-box');
  return !!(gd && gd._fullLayout && gd.data && gd.data.some((t) => t.name === 'venue-hits'));
}"""

_WK_POINT = """(key) => {
  const gd = document.querySelector('.wk-map-box');
  gd.scrollIntoView({ block: 'center' });
  const t = gd.data.find((d) => d.name === 'venue-hits');
  const i = t.customdata.indexOf(key);
  const r = gd.getBoundingClientRect();
  const xa = gd._fullLayout.xaxis;
  const ya = gd._fullLayout.yaxis;
  return { x: r.left + xa._offset + xa.c2p(t.x[i]), y: r.top + ya._offset + ya.c2p(t.y[i]) };
}"""

_WK_HOVERTEXT = """(key) => {
  const gd = document.querySelector('.wk-map-box');
  for (const t of gd.data) {
    const i = (t.customdata || []).indexOf(key);
    if (i >= 0 && t.hovertext) return t.hovertext[i];
  }
  return null;
}"""


def _open_weekend_map(page: Page, open_app: OpenApp, raw: dict[str, Any]) -> None:
    page.set_viewport_size({"width": 1440, "height": 900})
    page.clock.set_fixed_time("2026-10-03T09:00:00-04:00")
    page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    open_app(page, "?view=weekend&wview=map")
    page.wait_for_function(_WK_READY, timeout=15000)
    page.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
    page.wait_for_timeout(400)


def _ranked_raw(fixture_raw: dict[str, Any], *, ranks: bool, confs: bool) -> dict[str, Any]:
    raw = weekend_map_raw(fixture_raw)
    names = [c["name"] for c in raw["lookups"]["conferences"]]
    sched = raw["telecasts_scheduled"]
    if ranks:
        sched["away_rank"][5] = 20
        sched["home_rank"][5] = 5
    if confs:
        sched["away_conference"][5] = names.index("SEC")
        sched["home_conference"][5] = names.index("Pac-12")
    return raw


def test_live_weekend_map_card_shows_badge_and_conference_line(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    page = guarded_page
    _open_weekend_map(page, open_app, _ranked_raw(fixture_raw, ranks=True, confs=True))
    at = page.evaluate(_WK_POINT, _PRIME)
    page.mouse.move(at["x"] + 40, at["y"] + 40)
    page.mouse.move(at["x"], at["y"], steps=6)
    page.wait_for_selector("#chart-tooltip[data-kind='game']:not([hidden])", timeout=5000)
    page.wait_for_timeout(250)
    tip = page.locator("#chart-tooltip")
    assert "rk-has" in (tip.get_attribute("class") or "")
    assert tip.locator(".rk-badge svg[role='img']").count() == 1
    line = tip.locator(".cf-card-line")
    assert line.count() == 1
    alts = line.locator("img.cf-logo").evaluate_all("(ns) => ns.map((n) => n.alt)")
    assert alts == ["SEC", "Pac-12"]
    srcs = line.locator("img.cf-logo").evaluate_all("(ns) => ns.map((n) => n.getAttribute('src'))")
    assert srcs[0].endswith("southeastern-conference-2024-present.svg")
    assert srcs[1].endswith("pac-12-conference-2026-present-official-site.svg")
    hovertext = page.evaluate(_WK_HOVERTEXT, _PRIME)
    assert hovertext is not None
    assert "ranked" not in hovertext
    assert "SEC" not in hovertext
    assert "Pac-12" not in hovertext


def test_live_weekend_map_hovertext_ignores_conferences(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    page = guarded_page
    _open_weekend_map(page, open_app, _ranked_raw(fixture_raw, ranks=True, confs=False))
    before = page.evaluate(_WK_HOVERTEXT, _PRIME)
    _open_weekend_map(page, open_app, _ranked_raw(fixture_raw, ranks=True, confs=True))
    after = page.evaluate(_WK_HOVERTEXT, _PRIME)
    assert before is not None
    assert before == after
