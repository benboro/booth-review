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
    assert r["width"] <= 280
