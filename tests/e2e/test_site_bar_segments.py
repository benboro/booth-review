"""Bars and Butterfly keep each segment together (04.13 notes-2 #2, #4; WR-02).

Every stacked bar is built from three layers, found here by axis rather than by
trace index: pieces on the base axes (`x`, `x2`), one transparent segment overlay
per segment rank on `x3`/`x4` (separators, hover, click), and part-text traces on
`x5`/`x6` (the segment label, on its wider part). Builder tests use synthetic
models built in the page; `rendered` tests open the real app with Plotly.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_ENV = {"theme": "light", "mobile": False, "revision": 1, "width": 1280}
_THEMES = ["light", "dark"]
_TRANSPARENT = "rgba(0,0,0,0)"

_BUILD_JS = """
async ([fn, model, rows, env]) => {
  const F = await import('./modules/bar-chart.js');
  const build = fn === 'bars' ? F.buildBarFigure : F.buildButterflyFigure;
  return build(model, rows, env);
}
"""

_PALETTE_JS = """
async ([theme, family, shadeCount, tones]) => {
  const P = await import('./modules/palette.js');
  const bg = P.PAGE_BG[theme];
  return {
    bg,
    shades: family ? P.channelShades(family, theme, shadeCount) : null,
    tone: (family == null) ? P.barTones({ family: null }, theme) : null,
    readable: tones.map((list) => P.readableTextOnAll(list)),
    blend: tones.map((list) => list.map((t) => P.mixHex(t, bg, 0.25))),
  };
}
"""


def _seg(key: str, count: int, rated: int, channels: list[dict[str, Any]] | None = None) -> dict:
    seg: dict[str, Any] = {"key": key, "label": key, "count": count, "rated": rated, "target": None}
    if channels is not None:
        seg["channels"] = channels
    return seg


def _chan(cid: str, count: int, rated: int, shade: int) -> dict[str, Any]:
    return {"id": cid, "name": cid, "count": count, "rated": rated, "shade": shade}


def _plain_segments(rated_all: bool = False, none_rated: bool = False) -> list[dict]:
    segs = [_seg("A", 3, 1), _seg("B", 2, 2), _seg("C", 1, 0)]
    for s in segs:
        if rated_all:
            s["rated"] = s["count"]
        if none_rated:
            s["rated"] = 0
    return segs


def _family_segments(rated_all: bool = False, none_rated: bool = False) -> list[dict]:
    a = _seg("A", 5, 3, [_chan("c0", 3, 1, 0), _chan("c1", 2, 2, 1)])
    b = _seg("B", 1, 0, [_chan("c0", 1, 0, 0)])
    for s in (a, b):
        for c in s["channels"]:
            if rated_all:
                c["rated"] = c["count"]
            if none_rated:
                c["rated"] = 0
        s["rated"] = sum(c["rated"] for c in s["channels"])
    return [a, b]


def _bars_figure(page: Page, site_url: str, kind: str, env: dict | None = None, **kw: bool) -> Any:
    segs = (_family_segments if kind == "family" else _plain_segments)(**kw)
    row = {
        "key": "r0",
        "label": "Row",
        "family": "disney" if kind == "family" else None,
        "shadeCount": 2,
        "total": sum(s["count"] for s in segs),
        "target": None,
        "segments": segs,
    }
    model = {"mode": "stacked", "rowKind": kind}
    page.goto(f"{site_url}/")
    return page.evaluate(_BUILD_JS, ["bars", model, [row], env or _ENV])


def _butterfly_figure(page: Page, site_url: str, kind: str) -> Any:
    segs = (_family_segments if kind == "family" else _plain_segments)()
    side = {
        "total": sum(s["count"] for s in segs),
        "rated": sum(s["rated"] for s in segs),
        "segments": segs,
    }
    row = {
        "key": "r0",
        "label": "Row",
        "family": "disney" if kind == "family" else None,
        "shadeCount": 2,
        "target": None,
        "total": side["total"],
        "sides": [side, side],
    }
    model = {"mode": "stacked", "rowKind": kind, "sides": [{"name": "L"}, {"name": "R"}]}
    page.goto(f"{site_url}/")
    return page.evaluate(_BUILD_JS, ["butterfly", model, [row], _ENV])


def _on(figure: dict, axis: str) -> list[dict]:
    return [t for t in figure["traces"] if t["xaxis"] == axis]


def _piece_walk(figure: dict, axis: str) -> list[tuple[int, str, str, float]]:
    """(width, fill, border color, border width) of each piece for row 0, in order."""
    out = []
    for t in _on(figure, axis):
        line = t["marker"]["line"]
        out.append((t["x"][0], t["marker"]["color"][0], line["color"][0], line["width"][0]))
    return out


def _rgba(tone: str) -> str:
    n = int(tone.lstrip("#"), 16)
    return f"rgba({n >> 16 & 255},{n >> 8 & 255},{n & 255},0.25)"


# --------------------------------------------------------------------------
# Simple bars: the solid rated part has the same border as the unrated part
# --------------------------------------------------------------------------


def test_simple_bars_rated_part_is_bordered_like_the_unrated_part(
    guarded_page: Page, site_url: str
) -> None:
    rows = [
        {"key": "a", "label": "A", "family": None, "total": 4, "rated": 3, "target": None},
        {"key": "b", "label": "B", "family": None, "total": 2, "rated": 0, "target": None},
        {"key": "c", "label": "C", "family": None, "total": 2, "rated": 2, "target": None},
    ]
    guarded_page.goto(f"{site_url}/")
    fig = guarded_page.evaluate(_BUILD_JS, ["bars", {"mode": "simple"}, rows, _ENV])
    rated, unrated = fig["traces"]
    for i, row in enumerate(rows):
        tone = rated["marker"]["color"][i]
        assert rated["marker"]["line"]["color"][i] == tone
        assert unrated["marker"]["line"]["color"][i] == tone
        assert unrated["marker"]["color"][i] == _rgba(tone)
        for trace, width in ((rated, row["rated"]), (unrated, row["total"] - row["rated"])):
            assert trace["marker"]["line"]["width"][i] == (1.5 if width > 0 else 0)


def test_simple_butterfly_rated_part_is_bordered_like_the_unrated_part(
    guarded_page: Page, site_url: str
) -> None:
    sides = [{"total": 4, "rated": 3}, {"total": 2, "rated": 0}]
    row = {"key": "a", "label": "A", "family": None, "total": 4, "target": None, "sides": sides}
    model = {"mode": "simple", "sides": [{"name": "L"}, {"name": "R"}]}
    guarded_page.goto(f"{site_url}/")
    fig = guarded_page.evaluate(_BUILD_JS, ["butterfly", model, [row], _ENV])
    assert len(fig["traces"]) == 4
    for t in fig["traces"][::2]:
        tone = t["marker"]["color"][0]
        assert t["marker"]["line"]["color"][0] == tone
    for t, w in zip(fig["traces"], (3, 1, 0, 2), strict=True):
        assert t["x"][0] == w
        assert t["marker"]["line"]["width"][0] == (1.5 if w > 0 else 0)


# --------------------------------------------------------------------------
# Pieces: one segment's pieces are contiguous, rated then unrated
# --------------------------------------------------------------------------


def test_plain_stack_pieces_group_by_segment(guarded_page: Page, site_url: str) -> None:
    fig = _bars_figure(guarded_page, site_url, "plain")
    walk = _piece_walk(fig, "x")
    assert [w[0] for w in walk] == [1, 2, 2, 0, 0, 1]  # A r/u, B r/u, C r/u
    tones = {"A": "#7C3AED", "B": "#B793F5", "C": "#7C3AED"}
    for (width, fill, border, line), (seg, rated) in zip(
        walk, [(s, r) for s in "ABC" for r in (True, False)], strict=True
    ):
        assert border == tones[seg]
        assert fill == (tones[seg] if rated else _rgba(tones[seg]))
        assert line == (1.5 if width > 0 else 0)


def test_family_stack_pieces_group_by_segment(guarded_page: Page, site_url: str) -> None:
    fig = _bars_figure(guarded_page, site_url, "family")
    walk = _piece_walk(fig, "x")
    # A rated c0, c1; A unrated c0, c1; B rated c0; B unrated c0
    assert [w[0] for w in walk] == [1, 2, 2, 0, 0, 1]
    pal = guarded_page.evaluate(_PALETTE_JS, ["light", "disney", 2, []])
    shades = pal["shades"]
    shade_of_piece = [0, 1, 0, 1, 0, 0]
    for i, (width, fill, border, line) in enumerate(walk):
        tone = shades[shade_of_piece[i]]
        assert border == tone
        assert fill == (tone if i in (0, 1, 4) else _rgba(tone))
        assert line == (1.5 if width > 0 else 0)


@pytest.mark.parametrize("kind", ["plain", "family"])
def test_butterfly_halves_use_the_same_layers(guarded_page: Page, site_url: str, kind: str) -> None:
    fig = _butterfly_figure(guarded_page, site_url, kind)
    for base, over, text in (("x", "x3", "x5"), ("x2", "x4", "x6")):
        assert len(_on(fig, base)) == 6
        assert len(_on(fig, over)) == 2 + (kind == "plain")
        assert len(_on(fig, text)) == 2 * (2 + (kind == "plain"))
    left = [t["x"][0] for t in _on(fig, "x")]
    right = [t["x"][0] for t in _on(fig, "x2")]
    assert left == right == [1, 2, 2, 0, 0, 1]
    layout = fig["layout"]
    for axis, base in (
        ("xaxis3", "xaxis"),
        ("xaxis4", "xaxis2"),
        ("xaxis5", "xaxis"),
        ("xaxis6", "xaxis2"),
    ):
        assert layout[axis]["overlaying"] == "x" + ("2" if base == "xaxis2" else "")
        assert layout[axis]["range"] == layout[base]["range"]
        assert layout[axis]["visible"] is False


# --------------------------------------------------------------------------
# Segment overlays carry separators, hover and click; nothing else does
# --------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["plain", "family"])
def test_segment_overlays_carry_separators_and_customdata(
    guarded_page: Page, site_url: str, kind: str
) -> None:
    fig = _bars_figure(guarded_page, site_url, kind)
    counts = [3, 2, 1] if kind == "plain" else [5, 1]
    overlays = _on(fig, "x3")
    assert [t["x"][0] for t in overlays] == counts
    for k, t in enumerate(overlays):
        assert t["marker"]["color"] == _TRANSPARENT
        assert t["marker"]["line"] == {"width": 3, "color": "#FFFFFF"}  # D-28
        assert t["customdata"][0] == {"r": 0, "s": k, "side": None}
        assert t["hoverinfo"] == "none"
        assert not any(t.get("text", []))
    for axis in ("x", "x5"):
        for t in _on(fig, axis):
            assert t["hoverinfo"] == "skip"
            assert "customdata" not in t
    assert fig["layout"]["xaxis3"]["overlaying"] == "x"
    assert fig["layout"]["xaxis5"]["overlaying"] == "x"
    order = [t["xaxis"] for t in fig["traces"]]
    assert order == sorted(order, key=lambda a: ("x", "x3", "x5").index(a))  # layers in order


# --------------------------------------------------------------------------
# Labels sit on the wider part, in a color readable on that part (WR-02)
# --------------------------------------------------------------------------


def _expected_text(
    page: Page, kind: str, theme: str, parts: list[tuple[str, int, int, list[int]]]
) -> list[tuple[str, str]]:
    """Per segment: (text, text color) for the wider part, '' when unreadable."""
    shades = page.evaluate(_PALETTE_JS, [theme, "disney" if kind == "family" else None, 2, []])
    base = shades["tone"]
    out = []
    for i, (label, rated, unrated, chans) in enumerate(parts):
        tones = (
            [shades["shades"][c] for c in chans]
            if kind == "family"
            else [base["a"] if i % 2 == 0 else base["b"]]
        )
        on_rated = rated >= unrated
        pal = page.evaluate(_PALETTE_JS, [theme, None, 0, [tones]])
        fills = tones if on_rated else pal["blend"][0]
        color = page.evaluate(_PALETTE_JS, [theme, None, 0, [fills]])["readable"][0]
        out.append((f"{label} {rated + unrated}" if color else "", color or "#000000"))
    return out


@pytest.mark.parametrize("theme", _THEMES)
@pytest.mark.parametrize("kind", ["plain", "family"])
def test_part_text_sits_on_the_wider_part(
    guarded_page: Page, site_url: str, kind: str, theme: str
) -> None:
    fig = _bars_figure(guarded_page, site_url, kind, {**_ENV, "theme": theme})
    text = _on(fig, "x5")
    if kind == "plain":
        parts = [("A", 1, 2, [0]), ("B", 2, 0, [0]), ("C", 0, 1, [0])]
        wider = ["unrated", "rated", "unrated"]
    else:
        parts = [("A", 3, 2, [0, 1]), ("B", 0, 1, [0])]
        wider = ["rated", "unrated"]
    assert len(text) == 2 * len(parts)
    expected = _expected_text(guarded_page, kind, theme, parts)
    for k, (side, (want, color)) in enumerate(zip(wider, expected, strict=True)):
        rated_t, unrated_t = text[2 * k], text[2 * k + 1]
        assert rated_t["x"][0] == parts[k][1] and unrated_t["x"][0] == parts[k][2]
        for t in (rated_t, unrated_t):
            assert t["marker"]["color"] == _TRANSPARENT
            assert t["marker"]["line"]["width"] == 0
        shown, hidden = (rated_t, unrated_t) if side == "rated" else (unrated_t, rated_t)
        assert shown["text"][0] == want
        assert hidden["text"][0] == ""
        if want:
            assert shown["textfont"]["color"][0] == color


def test_part_text_ties_go_to_the_rated_part(guarded_page: Page, site_url: str) -> None:
    seg = _seg("T", 4, 2)
    row = {"key": "r", "label": "R", "family": None, "total": 4, "target": None, "segments": [seg]}
    model = {"mode": "stacked", "rowKind": "person"}
    guarded_page.goto(f"{site_url}/")
    fig = guarded_page.evaluate(_BUILD_JS, ["bars", model, [row], _ENV])
    rated_t, unrated_t = _on(fig, "x5")
    want = _expected_text(guarded_page, "plain", "light", [("T", 2, 2, [0])])[0][0]
    assert rated_t["text"][0] == want
    assert unrated_t["text"][0] == ""


# --------------------------------------------------------------------------
# Zero-count pieces paint no border; trace count ignores the rating split
# --------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["plain", "family"])
def test_zero_count_pieces_have_no_border(guarded_page: Page, site_url: str, kind: str) -> None:
    fig = _bars_figure(guarded_page, site_url, kind)
    pieces = _on(fig, "x")
    assert any(t["x"][0] == 0 for t in pieces)
    for t in pieces:
        for value, width in zip(t["x"], t["marker"]["line"]["width"], strict=True):
            assert width == (1.5 if value > 0 else 0)


@pytest.mark.parametrize("kind", ["plain", "family"])
def test_trace_count_ignores_the_rating_split(guarded_page: Page, site_url: str, kind: str) -> None:
    counts = [
        len(_bars_figure(guarded_page, site_url, kind, **opts)["traces"])
        for opts in ({}, {"rated_all": True}, {"none_rated": True})
    ]
    assert counts[0] == counts[1] == counts[2]


# --------------------------------------------------------------------------
# Rendered: one segment's drawn pieces are contiguous; parts are equally thick
# --------------------------------------------------------------------------

_RENDER_JS = """
async ([partial, fn, env]) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const B = await import('./modules/bars.js');
  const F = await import('./modules/bar-chart.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const state = Object.assign(S.defaultState(data), partial);
  const model = B[fn](data, S.computeView(data, state), state);
  const rows = B.visibleRows(model.rows, false);
  const build = fn === 'barsModel' ? F.buildBarFigure : F.buildButterflyFigure;
  const figure = build(model, rows, env);
  document.getElementById('test-bars')?.remove();
  const gd = document.createElement('div');
  gd.id = 'test-bars';
  gd.style.cssText = `width:${env.width}px;position:relative;`;
  document.body.appendChild(gd);
  await F.renderBars(gd, figure);
  const full = gd._fullLayout;
  const gdRect = gd.getBoundingClientRect();
  const all = Array.from(gd.querySelectorAll('.bars .point path')).map((el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return { l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width, h: r.height,
             fill: cs.fill, fo: Number(cs.fillOpacity), stroke: cs.stroke,
             sw: Number.parseFloat(cs.strokeWidth) || 0 };
  });
  return {
    paths: all.filter((p) => p.w > 0.5),
    thin: all.filter((p) => p.w <= 0.5),
    rows: JSON.parse(JSON.stringify(rows)),
    centers: rows.map((_, i) => gdRect.top + full._size.t + full.yaxis.d2p(i)),
    spine: full.xaxis2
      ? gdRect.left + (full.xaxis._offset + full.xaxis._length + full.xaxis2._offset) / 2
      : 0,
  };
}
"""

_FAM_BARS = {"school": ["northfield"], "by": "network"}
_FAM_FLY = {"school": ["northfield", "lakeview"], "by": "network"}
_CONF_BARS = {"people": ["kris-venn"], "by": "conference"}
_CONF_FLY = {"people": ["kris-venn", "pat-rowan"], "by": "conference"}


def _render(
    page: Page,
    open_app: Callable[[Page, str], None],
    raw: dict | None,
    partial: dict,
    fn: str,
    theme: str,
    width: int,
) -> dict[str, Any]:
    if raw is not None:
        page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    page.emulate_media(color_scheme=theme)  # type: ignore[arg-type]
    open_app(page, "")
    env = {"theme": theme, "mobile": width < 600, "revision": 1, "width": width}
    return page.evaluate(_RENDER_JS, [partial, fn, env])  # type: ignore[no-any-return]


def _piece_count(seg: dict[str, Any]) -> int:
    parts = seg.get("channels") or [seg]
    return sum((p["rated"] > 0) + (p["count"] - p["rated"] > 0) for p in parts if p["count"] > 0)


@pytest.mark.parametrize("theme", _THEMES)
@pytest.mark.parametrize("width", [1280, 360])
@pytest.mark.parametrize(
    ("partial", "fn", "multi"),
    [
        (_FAM_BARS, "barsModel", True),
        (_FAM_FLY, "butterflyModel", True),
        (_CONF_BARS, "barsModel", False),
        (_CONF_FLY, "butterflyModel", False),
    ],
)
def test_rendered_segment_pieces_are_contiguous(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    request: pytest.FixtureRequest,
    theme: str,
    width: int,
    partial: dict,
    fn: str,
    multi: bool,
) -> None:
    raw = request.getfixturevalue("multichannel") if multi else None
    out = _render(guarded_page, open_app, raw, partial, fn, theme, width)
    groups: dict[tuple[int, int], dict[str, list[dict]]] = {}
    for p in out["paths"]:
        yc = (p["t"] + p["b"]) / 2
        row = min(range(len(out["centers"])), key=lambda i: abs(out["centers"][i] - yc))
        side = 0 if fn == "barsModel" or (p["l"] + p["r"]) / 2 < out["spine"] else 1
        kind = "piece" if p["fo"] > 0 else ("overlay" if p["sw"] > 0 else "text")
        groups.setdefault((row, side), {"piece": [], "overlay": [], "text": []})[kind].append(p)
    checked = 0
    for (row, side), g in groups.items():
        src = out["rows"][row] if fn == "barsModel" else out["rows"][row]["sides"][side]
        segs = [s for s in src["segments"] if s["count"] > 0]
        rev = fn == "butterflyModel" and side == 0
        order = (lambda p: -p["l"]) if rev else (lambda p: p["l"])
        pieces = sorted(g["piece"], key=order)
        overlays = sorted(g["overlay"], key=order)
        assert len(overlays) == len(segs)
        cursor = 0
        for seg, over in zip(segs, overlays, strict=True):
            n = _piece_count(seg)
            mine = pieces[cursor : cursor + n]
            cursor += n
            assert len(mine) == n
            for p in mine:
                assert over["l"] - 1 <= p["l"] and p["r"] <= over["r"] + 1, (row, side, seg["key"])
            checked += 1
        assert cursor == len(pieces)
    assert checked
    # Zero-width pieces never paint a border (a 1.5px sliver at the segment start).
    assert all(p["sw"] == 0 or p["stroke"] == "none" for p in out["thin"] if p["fo"] > 0)


@pytest.mark.parametrize("width", [1280, 360])
@pytest.mark.parametrize("theme", _THEMES)
@pytest.mark.parametrize(
    ("partial", "fn"),
    [
        ({"school": ["northfield"]}, "barsModel"),
        ({"school": ["northfield", "lakeview"]}, "butterflyModel"),
    ],
)
def test_rendered_rated_and_unrated_parts_are_equally_thick(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    theme: str,
    width: int,
    partial: dict,
    fn: str,
) -> None:
    out = _render(guarded_page, open_app, None, partial, fn, theme, width)
    solid = [p for p in out["paths"] if p["fo"] > 0.9]
    hollow = [p for p in out["paths"] if 0 < p["fo"] < 0.5]
    assert solid and hollow
    for p in solid:
        assert p["sw"] == pytest.approx(1.5, abs=0.01)
        assert p["stroke"] == p["fill"]  # border in its own color
    for p in hollow:
        assert p["sw"] == pytest.approx(1.5, abs=0.01)
    assert abs(max(p["h"] for p in solid) - max(p["h"] for p in hollow)) <= 0.5
