"""Hover outlines the whole bar group like the scatter ring (04.13 notes-2 #4).

Hovering (or first-tapping) any piece of a bar segment draws one outline around
that segment's whole group in Bars and Butterfly, simple and stacked. The outline
is a DOM overlay (`#bars-hover-outline`) in the scatter hover ring's tokens, so
it adds no trace and never moves the layout.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

OpenApp = Callable[[Page, str], None]

SLACK = 4.0
THEMES = ["light", "dark"]
QUERIES = [
    "?school=northfield&view=bars",
    "?school=northfield&view=bars&by=network",
    "?people=kris-venn&view=bars",
    "?people=kris-venn&view=bars&by=conference",
    "?school=northfield,lakeview&view=butterfly",
    "?school=northfield,lakeview&view=butterfly&by=network",
]

_GROUPS_JS = """
() => {
  const gd = document.getElementById('bars-chart');
  const full = gd._fullLayout;
  const top = gd.getBoundingClientRect().top + full._size.t;
  const left = gd.getBoundingClientRect().left;
  const spine = full.xaxis2
    ? left + (full.xaxis._offset + full.xaxis._length + full.xaxis2._offset) / 2 : 0;
  const rows = full.yaxis._categories.length;
  const paths = Array.from(gd.querySelectorAll('.bars .point path')).map((el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return { l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width,
             fo: Number(cs.fillOpacity), sw: Number.parseFloat(cs.strokeWidth) || 0 };
  }).filter((p) => p.w > 0.5);
  const centers = Array.from({ length: rows }, (_, i) => top + full.yaxis.d2p(i));
  const out = new Map();
  const add = (p, kind) => {
    const yc = (p.t + p.b) / 2;
    const row = centers.reduce((best, c, i) =>
      Math.abs(c - yc) < Math.abs(centers[best] - yc) ? i : best, 0);
    const side = spine === 0 ? 0 : ((p.l + p.r) / 2 < spine ? 0 : 1);
    return { row, side, kind };
  };
  const overlays = paths.filter((p) => p.fo === 0 && p.sw > 0);
  const pieces = paths.filter((p) => p.fo > 0);
  const groups = [];
  if (overlays.length) {
    for (const o of overlays) {
      const g = add(o);
      groups.push({ ...g, rect: { l: o.l, r: o.r, t: o.t, b: o.b },
        pieces: pieces.filter((p) => add(p).row === g.row && add(p).side === g.side
          && p.l >= o.l - 1 && p.r <= o.r + 1) });
    }
  } else {
    for (const p of pieces) {
      const g = add(p);
      const key = g.row + '/' + g.side;
      if (!out.has(key)) {
        out.set(key, { ...g, rect: { l: p.l, r: p.r, t: p.t, b: p.b }, pieces: [] });
      }
      const e = out.get(key);
      e.rect = { l: Math.min(e.rect.l, p.l), r: Math.max(e.rect.r, p.r),
                 t: Math.min(e.rect.t, p.t), b: Math.max(e.rect.b, p.b) };
      e.pieces.push(p);
    }
    groups.push(...out.values());
  }
  return groups;
}
"""

_OUTLINE_JS = """
() => {
  const el = document.getElementById('bars-hover-outline');
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { hidden: el.hidden, l: r.left, r: r.right, t: r.top, b: r.bottom };
}
"""


def _groups(page: Page) -> list[dict[str, Any]]:
    page.wait_for_function("document.querySelectorAll('#bars-chart .bars .point path').length > 0")
    return page.evaluate(_GROUPS_JS)  # type: ignore[no-any-return]


def _outline(page: Page) -> dict[str, Any] | None:
    return page.evaluate(_OUTLINE_JS)  # type: ignore[no-any-return]


def _center(p: dict[str, float]) -> tuple[float, float]:
    return (p["l"] + p["r"]) / 2, (p["t"] + p["b"]) / 2


def _hover(page: Page, p: dict[str, float]) -> None:
    page.mouse.move(2, 2)
    x, y = _center(p)
    page.mouse.move(x, y, steps=4)
    page.wait_for_selector("#bars-hover-outline:not([hidden])")


def _picks(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """First, last, and the group with the most pieces (distinct, when possible)."""
    chosen = [groups[0], groups[-1], max(groups, key=lambda g: len(g["pieces"]))]
    seen: list[dict[str, Any]] = []
    for g in chosen:
        if g not in seen:
            seen.append(g)
    return seen


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("query", QUERIES)
def test_hover_outlines_the_whole_segment(
    guarded_page: Page, open_app: OpenApp, query: str, theme: str
) -> None:
    page = guarded_page
    page.emulate_media(color_scheme=theme)  # type: ignore[arg-type]
    open_app(page, query)
    groups = _groups(page)
    assert groups
    for g in _picks(groups):
        assert g["pieces"], g
        _hover(page, g["pieces"][0])
        box = _outline(page)
        assert box is not None
        assert not box["hidden"]
        r = g["rect"]
        # Encloses the drawn segment (a little padding is fine) ...
        assert r["l"] - SLACK <= box["l"] <= r["l"] + 1, (g, box)
        assert r["r"] - 1 <= box["r"] <= r["r"] + SLACK, (g, box)
        assert r["t"] - SLACK <= box["t"] <= r["t"] + 1, (g, box)
        assert r["b"] - 1 <= box["b"] <= r["b"] + SLACK, (g, box)


@pytest.mark.parametrize("query", QUERIES)
def test_any_piece_of_a_segment_gives_the_same_outline(
    guarded_page: Page, open_app: OpenApp, query: str
) -> None:
    page = guarded_page
    open_app(page, query)
    groups = [g for g in _groups(page) if len(g["pieces"]) >= 2]
    if not groups:
        pytest.skip("no multi-piece segment in this view")
    g = groups[0]
    rects = []
    for piece in g["pieces"]:
        _hover(page, piece)
        rects.append(_outline(page))
    first = rects[0]
    assert first is not None
    for box in rects[1:]:
        assert box is not None
        for k in ("l", "r", "t", "b"):
            assert box[k] == pytest.approx(first[k], abs=1.0)


@pytest.mark.parametrize("theme", THEMES)
def test_outline_uses_the_scatter_ring_tokens(
    guarded_page: Page, open_app: OpenApp, theme: str
) -> None:
    page = guarded_page
    page.emulate_media(color_scheme=theme)  # type: ignore[arg-type]
    open_app(page, QUERIES[0])
    _hover(page, _groups(page)[0]["pieces"][0])
    got = page.evaluate(
        """async () => {
          const H = await import('./modules/hover-ring.js');
          const ring = H.ensureHoverRingEl();
          ring.hidden = false;
          const pick = (el) => {
            const cs = getComputedStyle(el);
            return { color: cs.borderTopColor, width: cs.borderTopWidth,
                     style: cs.borderTopStyle, shadow: cs.boxShadow,
                     position: cs.position, events: cs.pointerEvents };
          };
          const out = pick(document.getElementById('bars-hover-outline'));
          const ref = pick(ring);
          ring.hidden = true;
          return { out, ref };
        }"""
    )
    for k in ("color", "width", "style", "shadow", "position", "events"):
        assert got["out"][k] == got["ref"][k], k


def test_hover_adds_no_trace_and_sits_outside_plotly(guarded_page: Page, open_app: OpenApp) -> None:
    page = guarded_page
    open_app(page, QUERIES[1])
    before = page.evaluate("document.getElementById('bars-chart').data.length")
    _hover(page, _groups(page)[0]["pieces"][0])
    assert page.evaluate("document.getElementById('bars-chart').data.length") == before
    assert page.evaluate(
        "!document.getElementById('bars-chart').contains("
        "document.getElementById('bars-hover-outline'))"
    )


def test_unhover_hides_the_outline(guarded_page: Page, open_app: OpenApp) -> None:
    page = guarded_page
    open_app(page, QUERIES[0])
    _hover(page, _groups(page)[0]["pieces"][0])
    page.mouse.move(2, 2, steps=4)
    page.wait_for_selector("#bars-hover-outline", state="hidden", timeout=3000)


def test_rerender_hides_the_outline(guarded_page: Page, open_app: OpenApp) -> None:
    page = guarded_page
    open_app(page, QUERIES[1])
    _hover(page, _groups(page)[0]["pieces"][0])
    page.evaluate("window.__testHooks.setState({ by: 'announcer' })")
    page.wait_for_selector("#bars-hover-outline", state="hidden", timeout=3000)


def test_phone_first_tap_outlines_and_outside_tap_clears(
    mobile_page: Page, open_app: OpenApp
) -> None:
    page = mobile_page
    open_app(page, QUERIES[0])
    g = _groups(page)[0]
    x, y = _center(g["pieces"][0])
    page.touchscreen.tap(x, y)
    page.wait_for_selector("#chart-tooltip:not([hidden])")
    box = _outline(page)
    assert box is not None
    assert not box["hidden"]
    r = g["rect"]
    assert r["l"] - SLACK <= box["l"] <= r["l"] + 1
    assert r["r"] - 1 <= box["r"] <= r["r"] + SLACK
    page.touchscreen.tap(195, 5)
    page.wait_for_selector("#bars-hover-outline", state="hidden", timeout=3000)
    page.wait_for_selector("#chart-tooltip", state="hidden", timeout=3000)


def test_segment_span_is_pure(guarded_page: Page, open_app: OpenApp) -> None:
    page = guarded_page
    open_app(page, "")
    got = page.evaluate(
        """async () => {
          const { segmentSpan } = await import('./modules/bar-outline.js');
          const stacked = [{ segments: [{ count: 3 }, { count: 2 }, { count: 1 }], total: 6 }];
          const fly = [{ sides: [
            { total: 4, segments: [{ count: 1 }, { count: 3 }] },
            { total: 7, segments: [] },
          ] }];
          return [
            segmentSpan([{ total: 5 }], { r: 0, s: -1, side: null }),
            segmentSpan(stacked, { r: 0, s: 1, side: null }),
            segmentSpan(fly, { r: 0, s: 1, side: 0 }),
            segmentSpan(fly, { r: 0, s: -1, side: 1 }),
          ];
        }"""
    )
    assert got == [[0, 5], [3, 5], [1, 4], [0, 7]]
