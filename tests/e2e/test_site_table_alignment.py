"""Professional table alignment (design brief §5), on every visible data table.

A numeric column (its body cells carry `num`) has right-aligned, tabular, unwrapped
cells and a right-aligned head; a text column keeps left-aligned cells and head; a
placeholder in a numeric column takes the numbers' alignment; numeric columns are
sized to their content; dates stay on one line at 1440px. Also checks that the NFL
and MLB "N rated of M games" line uses the CFB count's serif. Synthetic fixtures only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

DESKTOP = {"width": 1440, "height": 900}

# Per visible `.games-table` (inside `scope`), one record per column: the head's
# alignment, whether every body cell in the column is `num`, the body cells'
# alignments and white-space, and how many lines each `num` cell's text takes.
_COLUMNS_JS = """
(scope) => [...document.querySelectorAll(scope + ' table.games-table')]
  .filter((t) => t.offsetParent !== null && t.tBodies[0] && t.tBodies[0].rows.length)
  .map((t) => {
    const heads = [...t.tHead.rows[0].cells];
    return heads.map((th, c) => {
      const cells = [...t.tBodies[0].rows].map((r) => r.cells[c]).filter(Boolean);
      const lines = (el) => {
        const r = document.createRange();
        r.selectNodeContents(el.firstChild ?? el);
        return new Set([...r.getClientRects()].map((x) => Math.round(x.top))).size;
      };
      return {
        head: th.textContent.trim(),
        headAlign: getComputedStyle(th).textAlign,
        numeric: cells.length > 0 && cells.every((td) => td.classList.contains('num')),
        anyNum: cells.some((td) => td.classList.contains('num')),
        aligns: [...new Set(cells.map((td) => getComputedStyle(td).textAlign))],
        nums: [...new Set(cells.filter((td) => td.classList.contains('num'))
          .map((td) => getComputedStyle(td).fontVariantNumeric))],
        firstLines: Math.max(0, ...cells.filter((td) => td.classList.contains('num')).map(lines)),
        dateLines: Math.max(0, ...cells.filter((td) => td.classList.contains('date')).map(lines)),
      };
    });
  })
"""


def _columns(page: Page, scope: str) -> list[list[dict[str, Any]]]:
    tables = page.evaluate(_COLUMNS_JS, scope)
    assert tables, f"no visible data table under {scope}"
    return tables  # type: ignore[no-any-return]


def _assert_aligned(tables: list[list[dict[str, Any]]]) -> None:
    for columns in tables:
        assert any(c["numeric"] for c in columns), columns
        for col in columns:
            if col["numeric"]:
                assert col["headAlign"] == "right", col
                assert col["aligns"] == ["right"], col
                assert col["nums"] == ["tabular-nums"], col
            elif not col["anyNum"]:
                assert col["headAlign"] in ("left", "start"), col
                assert set(col["aligns"]) <= {"left", "start"}, col


def test_cfb_matched_games_heads_align_like_their_columns(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """The Viewers head sits right over right-aligned cells; Date (a text date), Matchup,
    Network, Crew and Source stay left. Viewers holds both figures and "No public rating"."""
    guarded_page.set_viewport_size(DESKTOP)
    open_app(guarded_page, "?school=northfield")
    guarded_page.wait_for_selector("#games-table tbody tr")
    (columns,) = _columns(guarded_page, "#matched-games")
    by_head = {c["head"].split()[0]: c for c in columns}
    assert by_head["Viewers"]["numeric"]
    for text_head in ("Date", "Matchup", "Network", "Crew", "Source"):
        assert not by_head[text_head]["anyNum"], text_head
    _assert_aligned([columns])


def test_cfb_dates_and_figures_stay_on_one_line_and_columns_fit_content(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Fix 2: every date (and every figure) is one line at 1440px, and the Viewers column is
    no wider than its widest cell plus padding (sized to content, not stretched)."""
    guarded_page.set_viewport_size(DESKTOP)
    open_app(guarded_page, "?school=northfield")
    guarded_page.wait_for_selector("#games-table tbody tr")
    (columns,) = _columns(guarded_page, "#matched-games")
    dates = [c for c in columns if c["head"].startswith("Date")]
    assert dates and dates[0]["dateLines"] == 1, dates
    for col in columns:
        if col["numeric"]:
            assert col["firstLines"] == 1, col
    slack = guarded_page.evaluate(
        """() => {
          const t = document.getElementById('games-table');
          const head = [...t.tHead.rows[0].cells];
          const c = head.findIndex((th) => th.textContent.includes('Viewers'));
          const body = [...t.tBodies[0].rows].map((r) => r.cells[c]);
          const cells = [head[c], ...body];
          const widest = Math.max(...cells.map((el) => {
            const r = document.createRange();
            r.selectNodeContents(el);
            return r.getBoundingClientRect().width;
          }));
          const cs = getComputedStyle(cells[1]);
          const pad = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight);
          return cells[1].getBoundingClientRect().width - widest - pad;
        }"""
    )
    assert slack < 2, f"Viewers column is {slack}px wider than its content"


def test_cfb_placeholder_takes_the_numbers_alignment(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """ "No public rating" and a figure share the Viewers column's right edge."""
    guarded_page.set_viewport_size(DESKTOP)
    open_app(guarded_page, "?school=northfield")
    guarded_page.wait_for_selector("#games-table tbody tr")
    edges = guarded_page.evaluate(
        """() => {
          const cells = [...document.querySelectorAll('#games-table tbody td.num:nth-child(5)')];
          return cells.map((td) => {
            const r = document.createRange();
            r.selectNodeContents(td);
            return { text: td.textContent, right: Math.round(r.getBoundingClientRect().right),
                     placeholder: td.classList.contains('no-rating') };
          });
        }"""
    )
    assert any(e["placeholder"] for e in edges) and any(not e["placeholder"] for e in edges), edges
    assert len({e["right"] for e in edges}) == 1, edges


def test_sort_glyph_does_not_move_a_right_aligned_head(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """The glyph sits left of a numeric head's label, so sorting never shifts the label."""
    guarded_page.set_viewport_size(DESKTOP)
    open_app(guarded_page, "?school=northfield")
    guarded_page.wait_for_selector("#games-table tbody tr")
    label_right = """() => {
      const b = document.querySelector('#games-table th button[data-sort="viewers"]');
      const r = document.createRange();
      r.selectNodeContents(b.firstChild);
      return Math.round(r.getBoundingClientRect().right);
    }"""
    before = guarded_page.evaluate(label_right)
    guarded_page.click('#games-table th button[data-sort="viewers"]')
    guarded_page.wait_for_function(
        "document.querySelector("
        "'#games-table th button[data-sort=\"viewers\"] .sort-glyph').textContent !== ''"
    )
    assert guarded_page.evaluate(label_right) == before


def test_cfb_crews_heads_align_right_over_numbers(
    guarded_page: Page,
    serve_crews: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> None:
    guarded_page.set_viewport_size(DESKTOP)
    serve_crews(guarded_page)
    open_app(guarded_page, "?view=crews")
    guarded_page.wait_for_selector("#crews-panel table.games-table tbody tr")
    _assert_aligned(_columns(guarded_page, "#crews-panel"))


def test_nfl_crews_and_matched_games_heads_align_like_their_columns(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    page.set_viewport_size(DESKTOP)
    open_nfl_app(page, "?sport=nfl&view=crews")
    page.wait_for_selector("#nfl-view-crews table.games-table tbody tr")
    _assert_aligned(_columns(page, "#nfl-view-crews"))
    page.locator("#nfl-view-crews .booth-row-btn").first.click()
    page.wait_for_selector(".nfl-games table.games-table tbody tr")
    _assert_aligned(_columns(page, ".nfl-games"))


def test_mlb_apple_and_matched_games_heads_align_like_their_columns(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    page.set_viewport_size(DESKTOP)
    open_mlb_app(page, "?sport=mlb&view=apple")
    page.wait_for_selector(".mlb-apple-table tbody tr")
    _assert_aligned(_columns(page, "#mlb-chart-area"))
    page.locator(".mlb-apple-table .booth-row-btn").first.click()
    page.wait_for_selector(".nfl-games table.games-table tbody tr")
    _assert_aligned(_columns(page, ".nfl-games"))


# Reads `sel`'s font and colour next to a probe styled as CFB's `.summary-count`, placed in
# the same selection bar, so both resolve against the same shared stylesheet.
_FONT_JS = """(sel) => {
  const el = document.querySelector(sel);
  const probe = document.createElement('span');
  probe.className = 'summary-count';
  probe.textContent = '1 rated of 2 games';
  el.parentElement.appendChild(probe);
  const pick = (n) => { const cs = getComputedStyle(n);
    return [cs.fontFamily, cs.fontSize, cs.fontWeight, cs.color]; };
  const out = { line: pick(el), cfb: pick(probe) };
  probe.remove();
  return out;
}"""


def test_nfl_count_line_matches_the_cfb_count(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    """Fix 3: the at-rest "N rated of M games" line uses the CFB count's serif style."""
    open_nfl_app(nfl_guarded_page, "?sport=nfl")
    nfl_guarded_page.wait_for_function(
        "/rated of/.test(document.getElementById('nfl-summary').textContent)"
    )
    got = nfl_guarded_page.evaluate(_FONT_JS, "#nfl-summary")
    assert "Crimson Text" in got["cfb"][0]
    assert got["line"] == got["cfb"]


def test_mlb_count_line_matches_the_cfb_count(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    open_mlb_app(mlb_guarded_page)
    mlb_guarded_page.wait_for_function(
        "/rated of/.test(document.getElementById('mlb-summary').textContent)"
    )
    got = mlb_guarded_page.evaluate(_FONT_JS, "#mlb-summary")
    assert "Crimson Text" in got["cfb"][0]
    assert got["line"] == got["cfb"]


_MATCHUP_LINES_JS = """(scope) => [...document.querySelectorAll(scope + ' td.matchup')]
  .map((td) => {
  const target = td.querySelector('button') ?? td;
  const r = document.createRange();
  r.selectNodeContents(target);
  return [target.textContent, new Set([...r.getClientRects()].map((x) => Math.round(x.top))).size];
})"""


def _assert_one_line_matchups(page: Page, scope: str) -> None:
    lines = page.evaluate(_MATCHUP_LINES_JS, scope)
    assert lines, f"no matchup cells under {scope}"
    assert all(n == 1 for _, n in lines), lines


def test_cfb_matchup_stays_on_one_line_at_1440(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """The matchup takes the spare width on desktop instead of wrapping beside an empty
    Crew column; on a phone it may still wrap."""
    guarded_page.set_viewport_size(DESKTOP)
    open_app(guarded_page, "?school=northfield")
    guarded_page.wait_for_selector("#games-table tbody tr")
    _assert_one_line_matchups(guarded_page, "#games-table")


def test_nfl_matchup_stays_on_one_line_at_1440(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    page.set_viewport_size(DESKTOP)
    open_nfl_app(page, "?sport=nfl&view=crews")
    page.locator("#nfl-view-crews .booth-row-btn").first.click()
    page.wait_for_selector(".nfl-games table.games-table tbody tr")
    _assert_one_line_matchups(page, ".nfl-games")


def test_mlb_matchup_stays_on_one_line_at_1440(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    page.set_viewport_size(DESKTOP)
    open_mlb_app(page, "?sport=mlb&view=apple")
    page.locator(".mlb-apple-table .booth-row-btn").first.click()
    page.wait_for_selector(".nfl-games table.games-table tbody tr")
    _assert_one_line_matchups(page, ".nfl-games")
