"""04.6 SITE-38, D-28 (supersedes D-19): role pills only on hover or tap, never
on the Plotly Bars and Butterfly chart. Row labels and in-segment text stay
bare names; the bar/segment tooltip title carries the pill(s).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

OpenApp = Callable[[Page, str], None]

SCHOOL = "?school=northfield&view=bars"
STACKED = SCHOOL + "&by=network"
BAR_VIEW = "?school=northfield&networks=net-a&view=bars"
FLY_VIEW = "?school=northfield,lakeview&people=kris-venn,pat-rowan&view=butterfly"
FLY_NETWORK = FLY_VIEW + "&by=network"

_ROLE_RE = re.compile(r"(·\s*(PBP|Analyst|Other|Sideline))|\b(PBP|Analyst)\b|PBP/Analyst")

_CHART_TEXT_JS = """() => {
  const gd = document.getElementById('bars-chart');
  const rowCount = gd.__barsRowCount;
  const annos = gd.layout.annotations;
  return {
    rowCount,
    labels: annos.slice(0, rowCount).map((a) => a.text),
    names: annos.map((a) => a.name ?? null),
    total: annos.length,
    segText: gd.data.flatMap((t) => (Array.isArray(t.text) ? t.text : [])).filter(Boolean),
  };
}"""


def _has_role_text(s: str) -> bool:
    return _ROLE_RE.search(s) is not None


def _chart_text(page: Page) -> dict[str, Any]:
    page.wait_for_function("document.getElementById('bars-chart')?.__barsRowCount > 0")
    return page.evaluate(_CHART_TEXT_JS)  # type: ignore[no-any-return]


def _bar_boxes(page: Page) -> list[dict[str, float]]:
    return page.evaluate(  # type: ignore[no-any-return]
        """() => Array.from(document.querySelectorAll(
            '#bars-chart .trace.bars .point path'))
            .map(p => { const r = p.getBoundingClientRect();
              return {x: r.x, y: r.y, w: r.width, h: r.height}; })
            .filter(b => b.w > 0 && b.h > 0)"""
    )


def _hover(page: Page, index: int) -> None:
    page.mouse.move(2, 2)
    box = _bar_boxes(page)[index]
    page.mouse.move(box["x"] + box["w"] / 2, box["y"] + box["h"] / 2, steps=4)
    page.wait_for_selector("#chart-tooltip:not([hidden])")


def _title(page: Page) -> dict[str, Any]:
    """The tooltip title's own text and its pills as (data-role, text)."""
    return page.evaluate(  # type: ignore[no-any-return]
        """() => {
          const t = document.querySelector('#chart-tooltip .tooltip-title');
          const own = Array.from(t.childNodes).filter((n) => n.nodeType === 3)
            .map((n) => n.textContent).join('');
          const pills = Array.from(t.querySelectorAll('.role-pill'))
            .map((p) => [p.dataset.role, p.textContent]);
          return {own, pills};
        }"""
    )


def _find_bar_titled(page: Page, name: str) -> int:
    """Index of the first drawn bar whose hover title is `name` (bare)."""
    for i in range(len(_bar_boxes(page))):
        _hover(page, i)
        if _title(page)["own"] == name:
            return i
    raise AssertionError(f"no bar titled {name!r}")


# ------------------------------------------------------------- chart text

CHART_QUERIES = [SCHOOL, BAR_VIEW, STACKED, FLY_VIEW, FLY_NETWORK]


@pytest.mark.parametrize("query", CHART_QUERIES)
@pytest.mark.parametrize("page_fixture", ["guarded_page", "mobile_page"])
def test_row_labels_are_bare_names(
    page_fixture: str, query: str, open_app: OpenApp, request: pytest.FixtureRequest
) -> None:
    page: Page = request.getfixturevalue(page_fixture)
    open_app(page, query)
    out = _chart_text(page)
    assert out["labels"]
    assert not any(_has_role_text(label) for label in out["labels"]), out["labels"]
    assert "role-pill" not in out["names"]
    if query == SCHOOL:
        assert "Dale Harlow" in out["labels"]
        assert "Dale Harlow Jr." in out["labels"]


@pytest.mark.parametrize("query", [STACKED, FLY_NETWORK])
def test_segment_text_is_name_and_count(guarded_page: Page, open_app: OpenApp, query: str) -> None:
    open_app(guarded_page, query)
    out = _chart_text(guarded_page)
    assert out["segText"]
    for text in out["segText"]:
        assert re.match(r"^.+ \d+$", text), text
        assert not _has_role_text(text), text


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide"], indirect=True)
def test_bar_labels_survive_fonts(guarded_page: Page, open_app: OpenApp, font_setting: str) -> None:
    open_app(guarded_page, SCHOOL)
    out = _chart_text(guarded_page)
    assert not any(_has_role_text(label) for label in out["labels"])
    assert len(out["labels"]) == out["rowCount"]


def test_bar_chart_module_has_no_pill_code() -> None:
    source = Path("site/modules/bar-chart.js").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith(("//", "*", "/*"))
    )
    for token in (
        "role-pill",
        "roundRolePills",
        "plotly_afterplot",
        "ROLE_PILL_TEXT",
        "pillStart",
        "makeRolePill",
    ):
        assert token not in code, token


# ---------------------------------------------------------------- tooltip


def test_segment_hover_shows_role_pill(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, STACKED)
    idx = _find_bar_titled(guarded_page, "Dale Harlow")
    _hover(guarded_page, idx)
    title = _title(guarded_page)
    assert title["pills"] == [["pbp", "PBP"]]
    rows = guarded_page.evaluate("window.__testHooks.getBarsModel().rows.map(r => r.label)")
    if "Robin Teague" in rows:
        idx = _find_bar_titled(guarded_page, "Robin Teague")
        _hover(guarded_page, idx)
        assert _title(guarded_page)["pills"] == [["unknown", "Sideline"]]


def test_butterfly_hover_shows_role_pill(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, FLY_VIEW)
    roles = guarded_page.evaluate(
        """() => Object.fromEntries(window.__testHooks.getBarsModel().rows
            .map((r) => [r.label, r.roles]))"""
    )
    text = {"pbp": "PBP", "analyst": "Analyst", "unknown": "Sideline"}
    _hover(guarded_page, 0)
    title = _title(guarded_page)
    assert title["own"] in roles
    assert not _has_role_text(title["own"])
    assert title["pills"] == [[r, text[r]] for r in roles[title["own"]]]


def test_tap_shows_role_pill_on_phone(mobile_page: Page, open_app: OpenApp) -> None:
    open_app(mobile_page, SCHOOL)
    box = _bar_boxes(mobile_page)[0]
    mobile_page.touchscreen.tap(box["x"] + box["w"] / 2, box["y"] + box["h"] / 2)
    mobile_page.wait_for_selector("#chart-tooltip:not([hidden])")
    title = _title(mobile_page)
    assert title["own"] == "Dale Harlow"
    assert title["pills"] == [["pbp", "PBP"]]


def test_both_roles_tooltip_has_two_pills_in_order(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, SCHOOL)
    out = guarded_page.evaluate(
        """async () => {
          const C = await import('./modules/bar-copy.js');
          const B = await import('./modules/bars.js');
          const T = await import('./modules/tooltip.js');
          const model = structuredClone(window.__testHooks.getBarsModel());
          const rows = model.rows;
          rows[0].roles = B.orderedRoles(['analyst', 'pbp']);
          const lines = C.tooltipLines(model, rows, {r: 0, s: -1, side: null});
          T.showTextTooltip(lines, {borderColor: '#888', clientX: 50, clientY: 50});
          const t = document.querySelector('#chart-tooltip .tooltip-title');
          const own = Array.from(t.childNodes).filter((n) => n.nodeType === 3)
            .map((n) => n.textContent).join('');
          return {
            own,
            name: rows[0].label,
            pills: Array.from(t.querySelectorAll('.role-pill')).map((p) => p.textContent),
          };
        }"""
    )
    assert out["pills"] == ["PBP", "Analyst"]
    assert out["own"] == out["name"]
    assert not _has_role_text(out["own"])


def test_name_label_still_drills(guarded_page: Page, open_app: OpenApp) -> None:
    open_app(guarded_page, SCHOOL)
    page = guarded_page
    first = page.evaluate(
        """() => {
          const gd = document.getElementById('bars-chart');
          const a = gd.layout.annotations[0];
          return {text: a.text, capture: a.captureevents,
                  rowCount: gd.__barsRowCount,
                  firstNonRow: gd.layout.annotations.findIndex((x) => x.name === 'total')};
        }"""
    )
    assert first["text"] == "Dale Harlow"
    assert first["capture"] is True
    if first["firstNonRow"] >= 0:
        assert first["firstNonRow"] == first["rowCount"]
    page.locator("#bars-chart g.annotation-text-g", has_text="Dale Harlow").first.click()
    page.wait_for_function("window.__testHooks.getState().people.length === 1")
    assert "people=dale-harlow" in page.url
