"""Phase 11 D-02: venue hover card, synthetic cards only."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

CREDIT = (
    "Viewers add up published figures from Ratings Reference and other outlets; "
    "the games table (click the dot) credits each game's source."
)

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
    footnotes: [...el.querySelectorAll('.tooltip-footnote:not(.tooltip-credit)')]
      .map((n) => n.textContent),
    credits: [...el.querySelectorAll('.tooltip-credit')].map((n) => n.textContent),
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
        "hasViewers": True,
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


def test_credit_note_follows_has_viewers(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    with_viewers = _show(guarded_page, _card())
    assert with_viewers["credits"] == [CREDIT]
    rows = [{"family": "fox", "label": "FOX", "games": 3, "viewers": None}]
    without = _show(guarded_page, _card(rows=rows, hasViewers=False))
    assert without["credits"] == []
    assert without["rows"] == [["FOX", "3", "-"]]


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


def test_unrated_and_rated_venues_show_dash_and_credit_note(
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
    assert any(CREDIT in t for t in texts)


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
