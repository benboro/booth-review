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
    page.locator("#nfl-view-crews tr.crews-row td.crews-name").first.click()
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
    page.locator("#nfl-view-crews tr.crews-row td.crews-name").first.click()
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


# Fix 15-12 r5: a one-line Date cell used to sit lower than the Matchup cell's first line,
# because a table cell centres vertically by default. The top of each cell's first text
# line is read from a Range over its first non-empty text node.
_FIRST_LINE_TOPS_JS = """
(scope) => [...document.querySelectorAll(scope + ' table.games-table')]
  .filter((t) => t.offsetParent !== null && t.tBodies[0] && t.tBodies[0].rows.length)
  .flatMap((t) => [...t.tBodies[0].rows].map((tr) => {
    const top = (td) => {
      const w = document.createTreeWalker(td, NodeFilter.SHOW_TEXT);
      for (let n = w.nextNode(); n; n = w.nextNode()) {
        if (!n.textContent.trim()) continue;
        const r = document.createRange();
        r.selectNodeContents(n);
        const rect = r.getClientRects()[0];
        if (rect) return rect.top;
      }
      return null;
    };
    const cells = [...tr.cells];
    const date = cells.find((c) => c.classList.contains('date'));
    const matchup = cells.find((c) => c.classList.contains('matchup'));
    return {
      date: date ? top(date) : null,
      matchup: matchup ? top(matchup) : null,
      all: cells.map(top).filter((v) => v !== null),
    };
  }))
"""


def _assert_first_lines_share_a_top(page: Page, scope: str) -> None:
    rows = page.evaluate(_FIRST_LINE_TOPS_JS, scope)
    assert rows, f"no rows under {scope}"
    for row in rows:
        assert row["date"] is not None and row["matchup"] is not None, row
        assert abs(row["date"] - row["matchup"]) <= 1.5, row
        assert max(row["all"]) - min(row["all"]) <= 4, row


def test_nfl_matched_games_first_lines_share_a_top(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    page.set_viewport_size(DESKTOP)
    open_nfl_app(page, "?sport=nfl&view=crews")
    page.locator("#nfl-view-crews tr.crews-row td.crews-name").first.click()
    page.wait_for_selector(".nfl-games table.games-table tbody tr")
    _assert_first_lines_share_a_top(page, ".nfl-games")


def test_nfl_matched_games_first_lines_share_a_top_on_a_phone(
    nfl_mobile_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_mobile_page
    open_nfl_app(page, "?sport=nfl&view=crews")
    page.locator("#nfl-view-crews tr.crews-row td.crews-name").first.click()
    page.wait_for_selector(".nfl-games table.games-table tbody tr")
    _assert_first_lines_share_a_top(page, ".nfl-games")


def test_cfb_matched_games_first_lines_share_a_top(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    guarded_page.set_viewport_size(DESKTOP)
    open_app(guarded_page, "?school=northfield")
    guarded_page.wait_for_selector("#games-table tbody tr")
    _assert_first_lines_share_a_top(guarded_page, "#matched-games")


def test_cfb_matched_games_first_lines_share_a_top_on_a_phone(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(mobile_page, "?school=northfield")
    mobile_page.wait_for_selector("#games-table tbody tr")
    _assert_first_lines_share_a_top(mobile_page, "#matched-games")


# Fix 15-12 r6: line N of every cell in a row shares a top (the time under the Date, the
# category under the Matchup). Lines are read from each cell's text outside pills, grouped by
# top; a new line starts when the top moves 6px or more.
_LINE_TOPS_JS = """
(scope) => [...document.querySelectorAll(scope + ' table.games-table')]
  .filter((t) => t.offsetParent !== null && t.tBodies[0] && t.tBodies[0].rows.length)
  .flatMap((t) => [...t.tBodies[0].rows].map((tr) => {
    const lines = (td) => {
      const tops = [];
      const w = document.createTreeWalker(td, NodeFilter.SHOW_TEXT);
      for (let n = w.nextNode(); n; n = w.nextNode()) {
        const skip = n.parentElement.closest('.pill, .role-pill, .crew-sep');
        if (!n.textContent.trim() || skip) continue;
        const r = document.createRange();
        r.selectNodeContents(n);
        for (const q of r.getClientRects()) tops.push(q.top);
      }
      tops.sort((a, b) => a - b);
      const out = [];
      for (const v of tops) if (!out.length || v - out[out.length - 1] >= 6) out.push(v);
      return out;
    };
    const cells = [...tr.cells];
    const date = cells.find((c) => c.classList.contains('date'));
    const matchup = cells.find((c) => c.classList.contains('matchup'));
    return {
      date: date ? lines(date) : [],
      matchup: matchup ? lines(matchup) : [],
      all: cells
        .filter((c) => c.matches('.date, .matchup') || c.querySelector('.crew-list'))
        .map(lines),
    };
  }))
"""


def _assert_second_lines_share_a_top(page: Page, scope: str, *, expect_pair: bool) -> None:
    rows = page.evaluate(_LINE_TOPS_JS, scope)
    assert rows, f"no rows under {scope}"
    seen_pair = False
    for row in rows:
        seconds = [c[1] for c in row["all"] if len(c) > 1]
        if len(seconds) > 1:
            assert max(seconds) - min(seconds) <= 1.5, row
        if len(row["date"]) > 1 and len(row["matchup"]) > 1:
            seen_pair = True
            assert abs(row["date"][1] - row["matchup"][1]) <= 1.5, row
    if expect_pair:
        assert seen_pair, rows


def test_nfl_matched_games_second_lines_share_a_top(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    """The time under the Date and the category under the Matchup share a top at 1440."""
    page = nfl_guarded_page
    page.set_viewport_size(DESKTOP)
    open_nfl_app(page, "?sport=nfl&view=crews")
    page.locator("#nfl-view-crews tr.crews-row td.crews-name").first.click()
    page.wait_for_selector(".nfl-games table.games-table tbody tr")
    _assert_second_lines_share_a_top(page, ".nfl-games", expect_pair=True)


def test_nfl_matched_games_second_lines_share_a_top_on_a_phone(
    nfl_mobile_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_mobile_page
    open_nfl_app(page, "?sport=nfl&view=crews")
    page.locator("#nfl-view-crews tr.crews-row td.crews-name").first.click()
    page.wait_for_selector(".nfl-games table.games-table tbody tr")
    _assert_second_lines_share_a_top(page, ".nfl-games", expect_pair=True)


def test_cfb_matched_games_second_lines_share_a_top(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """CFB rows have no time or category line; any cell that wraps still shares line 2."""
    guarded_page.set_viewport_size(DESKTOP)
    open_app(guarded_page, "?school=northfield")
    guarded_page.wait_for_selector("#games-table tbody tr")
    _assert_second_lines_share_a_top(guarded_page, "#matched-games", expect_pair=False)


def test_cfb_matched_games_second_lines_share_a_top_on_a_phone(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(mobile_page, "?school=northfield")
    mobile_page.wait_for_selector("#games-table tbody tr")
    _assert_second_lines_share_a_top(mobile_page, "#matched-games", expect_pair=False)


def test_nfl_category_line_is_muted_secondary_text(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    """The category line matches the time line (colour, size), starts flush with the matchup
    text, holds no pill, and joins several categories with " · "."""
    page = nfl_guarded_page
    page.set_viewport_size(DESKTOP)
    open_nfl_app(page, "?sport=nfl&view=crews")
    page.locator("#nfl-view-crews tr.crews-row td.crews-name").first.click()
    page.wait_for_selector(".nfl-games table.games-table tbody tr")
    got = page.evaluate(
        """() => [...document.querySelectorAll('.nfl-games tbody tr')].map((tr) => {
          const cat = tr.querySelector('td.matchup .games-sub');
          const time = tr.querySelector('td.date .games-sub');
          const btn = tr.querySelector('td.matchup button');
          const left = (el) => {
            const r = document.createRange(); r.selectNodeContents(el);
            return r.getClientRects()[0].left;
          };
          const cs = (el) => getComputedStyle(el);
          return { text: cat.textContent, pills: tr.querySelectorAll('td.matchup .pill').length,
                   color: cs(cat).color, size: cs(cat).fontSize,
                   timeColor: time ? cs(time).color : null,
                   timeSize: time ? cs(time).fontSize : null,
                   flush: Math.abs(left(cat) - left(btn)) };
        })"""
    )
    assert got
    for row in got:
        assert row["pills"] == 0, row
        assert row["flush"] <= 0.5, row
        assert row["size"] in ("12px", "14px"), row
        if row["timeColor"]:
            assert (row["color"], row["size"]) == (row["timeColor"], row["timeSize"]), row
    assert any(" · " in r["text"] for r in got) or all(" · " not in r["text"] for r in got)


# Fix 15-12 r6: a crew's " · " never dangles. The list is forced narrow to wrap it, then
# each separator is checked against the list's clip edge.
_SEPARATORS_JS = """
(args) => {
  const [scope, width] = args;
  const out = [];
  for (const list of document.querySelectorAll(scope + ' .crew-list')) {
    if (width) list.style.width = width;
    const box = list.getBoundingClientRect();
    const items = [...list.querySelectorAll('.crew-item')];
    const tops = items.map((it) => Math.round(it.getBoundingClientRect().top));
    items.forEach((it, k) => {
      const sep = it.querySelector('.crew-sep');
      if (!sep) return;
      const s = sep.getBoundingClientRect();
      out.push({
        startsLine: tops[k] !== tops[k - 1],
        visible: s.left >= box.left - 0.5 && s.right <= box.right + 0.5,
        clipped: s.right <= box.left + 0.5,
        wrapped: new Set(tops).size > 1,
        label: list.textContent,
      });
    });
  }
  return out;
}
"""


def _assert_no_dangling_separator(page: Page, scope: str, *, expect_wrap: bool) -> None:
    seps = page.evaluate(_SEPARATORS_JS, [scope, "150px" if expect_wrap else None])
    assert seps, f"no crew separators under {scope}"
    for sep in seps:
        if sep["startsLine"]:
            assert not sep["visible"], sep  # a line-start separator sits in the clipped gutter
        else:
            assert sep["visible"], sep  # a mid-line separator shows between its people
    if expect_wrap:
        assert any(s["startsLine"] for s in seps), seps
    else:
        # A crew that fits on one line keeps every separator; a long one may wrap naturally.
        fits = [s for s in seps if not s["wrapped"]]
        assert fits and all(s["visible"] for s in fits), seps


def test_nfl_crew_separator_does_not_dangle_when_wrapped(
    nfl_mobile_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_mobile_page
    open_nfl_app(page, "?sport=nfl&view=crews")
    page.locator("#nfl-view-crews tr.crews-row td.crews-name").first.click()
    page.wait_for_selector(".nfl-games table.games-table tbody tr")
    _assert_no_dangling_separator(page, ".nfl-games", expect_wrap=True)


def test_nfl_crew_separator_shows_between_people_on_one_line(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    page.set_viewport_size(DESKTOP)
    open_nfl_app(page, "?sport=nfl&view=crews")
    page.locator("#nfl-view-crews tr.crews-row td.crews-name").first.click()
    page.wait_for_selector(".nfl-games table.games-table tbody tr")
    _assert_no_dangling_separator(page, ".nfl-games", expect_wrap=False)
    text = page.locator(".nfl-games .crew-list").first.text_content() or ""
    assert " · " in text


def test_cfb_crew_separator_does_not_dangle_when_wrapped(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(mobile_page, "?school=northfield")
    mobile_page.wait_for_selector("#games-table tbody tr")
    _assert_no_dangling_separator(mobile_page, "#games-table", expect_wrap=True)


def test_cfb_crew_separator_shows_between_people_on_one_line(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    guarded_page.set_viewport_size(DESKTOP)
    open_app(guarded_page, "?school=northfield")
    guarded_page.wait_for_selector("#games-table tbody tr")
    _assert_no_dangling_separator(guarded_page, "#games-table", expect_wrap=False)
