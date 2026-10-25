# ruff: noqa: E501, RUF001  (embedded JS lines and the UI copy's typographic characters)
"""999.5-08: the NFL Matched games table and detail panel components.

Hand-built GameRow objects with invented names; no vault rows.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

PRELUDE = """
const F = await import('./sports/nfl/game-format.js');
const T = await import('./sports/nfl/table.js');
const PN = await import('./sports/nfl/panel.js');
const base = {
  i: 0, season: 2025, week: 1, date: '2025-09-07', kickoff: '2025-09-07T13:00:00-04:00',
  away: 'Harbor Gulls', home: 'Northfield Lanterns', awayShort: 'Gulls', homeShort: 'Lanterns',
  awayPoints: 24, homePoints: 27, slot: 'Sunday early', standalone: false, agotw: false,
  cbsNational: false, international: false, flexed: false, originalSlot: null,
  originalNetwork: null, changeUrl: null, network: 'Fox', networkFamily: 'fox',
  crewSource: null, crewSourceUrl: null,
  crew: [
    { name: 'Sam Sideline', role: 'unknown' },
    { name: 'Ann Analyst', role: 'analyst' },
    { name: 'Pat Pbp', role: 'pbp' },
  ],
  viewers: 12300000, scope: 'window', cause: null, era: 'Nielsen panel plus out-of-home',
  excitement: 7.26, rrUrl: 'https://example.com/rr/1', sourceUrl: 'https://example.com/src/1',
};
const mk = (o) => ({ ...base, ...o });
const host = document.createElement('div');
document.body.appendChild(host);
"""


@pytest.fixture
def run(nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None]) -> Callable[[str], Any]:
    open_flagon_cfb(nfl_guarded_page)

    def _run(body: str) -> Any:
        return nfl_guarded_page.evaluate("async () => {" + PRELUDE + body + "}")

    return _run


# ------------------------------------------------------------ game-format


def test_format_helpers(run: Callable[[str], Any]) -> None:
    got = run("""
      return {
        win: F.scoreText(base),
        away: F.scoreText(mk({ awayPoints: 30 })),
        tie: F.scoreText(mk({ awayPoints: 27 })),
        none: F.scoreText(mk({ homePoints: null })),
        snf: F.slotLabel('SNF'), other: F.slotLabel('Thanksgiving'),
        flags: F.flagLabels(mk({ flexed: true, agotw: true, standalone: true })),
        v: F.viewersText(base), nv: F.viewersText(mk({ viewers: null })),
        ko: F.kickoffText(base), long: F.dateLongText(base),
        cause: F.CAUSE_COPY.regional.panel,
      };
    """)
    assert got["win"] == "Lanterns 27, Gulls 24"
    assert got["away"] == "Gulls 30, Lanterns 27"
    assert got["tie"] == "Lanterns 27, Gulls 27 (tie)"
    assert got["none"] == "Not available"
    assert got["snf"] == "Sunday Night Football (SNF)"
    assert got["other"] == "Thanksgiving"
    assert got["flags"] == ["Solo slot", "Fox AGOTW", "Flexed"]
    assert got["v"] == "12.3MM"
    assert got["nv"] is None
    assert got["ko"] == "1:00 PM ET"
    assert got["long"] == "Sunday, Sep 7, 2025"
    assert got["cause"] == "Ratings Reference does not compile regional games"


# ------------------------------------------------------------------ table


def test_table_cells(run: Callable[[str], Any]) -> None:
    got = run("""
      const t = T.createGamesTable(host, { onOpen: () => {} });
      t.render([
        base,
        mk({ i: 1, date: '2025-09-14', kickoff: null, network: null, crew: [], viewers: null,
             scope: null, cause: 'pending', rrUrl: 'javascript:alert(1)', agotw: true, slot: 'SNF' }),
      ]);
      const rows = [...host.querySelectorAll('tbody tr')];
      const cells = (tr) => [...tr.children].map((td) => td.textContent);
      return {
        heading: host.querySelector('h2').textContent,
        summary: host.querySelector('.nfl-games-summary').textContent,
        heads: [...host.querySelectorAll('th')].map((th) => th.textContent.replace(/[▲▼]/g, '')),
        first: cells(rows[1]), second: cells(rows[0]),
        crewOrder: [...rows[1].querySelectorAll('.crew-name')].map((n) => n.textContent),
        link: rows[1].querySelector('td:last-child a')?.getAttribute('rel'),
        badLink: rows[0].querySelector('td:last-child a') !== null,
        tagged: rows[1].children[4].textContent.includes('from published lineup'),
        categoryText: rows[0].querySelector('td.matchup .games-sub').textContent,
        pills: rows[0].querySelectorAll('td.matchup .pill').length,
        text: host.textContent.toLowerCase(),
      };
    """)
    assert got["heading"] == "Matched games"
    assert got["summary"] == "2 games · 2025–2025 · 1 rated"
    assert got["heads"] == ["Date", "Matchup", "Score", "Network", "Crew", "Viewers", "Source"]
    # Default sort is date newest first, so the Sep 14 row (unrated) is first.
    second = got["second"]
    first = got["first"]
    assert "Sep 7, 2025" in first[0] and "1:00 PM ET" in first[0]
    assert "Harbor Gulls at Northfield Lanterns" in first[1]
    assert first[2] == "Lanterns 27, Gulls 24"
    assert first[3] == "Fox"
    assert got["crewOrder"] == ["Pat Pbp", "Ann Analyst", "Sam Sideline"]
    assert "12.3MM" in first[5] and "window-level" in first[5]
    assert first[6] == "Record ↗"
    assert got["link"] == "noopener noreferrer"
    assert second[3] == "Not recorded" and second[4] == "Not recorded"
    assert second[5] == "No rating"
    assert second[6] == "No record"
    assert got["badLink"] is False
    # Re-styled at Phase 15 Plan 12 r6: the category line is muted text joined by " · ", not pills.
    assert got["categoryText"] == "SNF · Fox AGOTW"
    assert got["pills"] == 0
    assert "spread" not in got["text"]


def test_table_sort(run: Callable[[str], Any]) -> None:
    got = run("""
      const t = T.createGamesTable(host, { onOpen: () => {} });
      t.render([
        mk({ i: 0, date: '2025-09-07', viewers: 5000000 }),
        mk({ i: 1, date: '2025-09-14', viewers: null, cause: 'none', scope: null }),
        mk({ i: 2, date: '2025-09-21', viewers: 9000000 }),
      ]);
      const col = () => [...host.querySelectorAll('tbody tr')].map((tr) => tr.children[5].textContent);
      const aria = () => host.querySelector('th button[data-sort="date"]').getAttribute('aria-sort');
      const out = { initial: col(), initialAria: aria() };
      host.querySelector('button[data-sort="viewers"]').click();
      out.byViewers = col();
      out.viewersAria = host.querySelector('button[data-sort="viewers"]').closest('th').getAttribute('aria-sort');
      host.querySelector('button[data-sort="viewers"]').click();
      out.byViewersAsc = col();
      host.querySelector('button[data-sort="date"]').click();
      out.dateDesc = col();
      host.querySelector('button[data-sort="date"]').click();
      out.dateAsc = col();
      out.sort = t.getSort();
      return out;
    """)
    assert got["initialAria"] == "descending"
    assert [c.split("M")[0] for c in got["initial"]] == ["9.0", "No rating", "5.0"]
    assert got["viewersAria"] == "descending"
    assert [c.split("M")[0] for c in got["byViewers"]] == ["9.0", "5.0", "No rating"]
    assert [c.split("M")[0] for c in got["byViewersAsc"]] == ["5.0", "9.0", "No rating"]
    assert [c.split("M")[0] for c in got["dateDesc"]] == ["9.0", "No rating", "5.0"]
    assert [c.split("M")[0] for c in got["dateAsc"]] == ["5.0", "No rating", "9.0"]
    assert got["sort"] == {"key": "date", "dir": "asc"}


def test_table_empty_states(run: Callable[[str], Any]) -> None:
    got = run("""
      const t = T.createGamesTable(host, { onOpen: () => {} });
      t.render([], { emptyKind: 'nothing' });
      const nothing = host.querySelector('.empty-state').textContent;
      const hidden = host.querySelector('table').hidden;
      t.render([], { emptyKind: 'filtered', selectionLabel: 'Northfield Lanterns' });
      return { nothing, hidden, filtered: host.querySelector('.empty-state').textContent };
    """)
    assert "Nothing selected" in got["nothing"]
    assert (
        "Pick a team, a booth, or a game from the chart to list matching games." in got["nothing"]
    )
    assert "You can also search announcers above." in got["nothing"]
    assert got["hidden"] is True
    assert "No games match the current filters for Northfield Lanterns." in got["filtered"]
    assert "Try widening the season range, or clear a filter." in got["filtered"]


def test_table_open_callback_and_xss(run: Callable[[str], Any]) -> None:
    got = run("""
      const calls = [];
      const t = T.createGamesTable(host, { onOpen: (i, b) => calls.push([i, b.tagName]) });
      t.render([mk({ i: 7, crew: [{ name: '<img src=x onerror=alert(1)>', role: 'pbp' }] })]);
      host.querySelector('.nfl-matchup-btn').click();
      return {
        calls,
        imgs: host.querySelectorAll('img').length,
        crew: host.querySelector('.crew-name').textContent,
      };
    """)
    assert got["calls"] == [[7, "BUTTON"]]
    assert got["imgs"] == 0
    assert got["crew"] == "<img src=x onerror=alert(1)>"


# ------------------------------------------------------------------ panel


def test_table_published_lineup_tag(run: Callable[[str], Any]) -> None:
    got = run("""
      const t = T.createGamesTable(host, { onOpen: () => {} });
      t.render([
        mk({ i: 0, date: '2025-09-07', crewSource: 'published_lineup', crewSourceUrl: 'https://example.com/lineup' }),
        mk({ i: 1, date: '2025-09-14' }),
      ]);
      const rows = [...host.querySelectorAll('tbody tr')];
      return rows.map((tr) => tr.children[4].textContent.includes('from published lineup'));
    """)
    assert got == [False, True]  # newest first: the Sep 14 row is untagged


def test_panel_cfb_layout(run: Callable[[str], Any]) -> None:
    got = run("""
      const p = PN.createDetailPanel(host, { methodologyHref: 'methodology.html' });
      const opener = document.createElement('button');
      host.appendChild(opener);
      opener.focus();
      p.open(mk({
        flexed: true, originalSlot: 'SNF', originalNetwork: 'NBC', slot: 'MNF', network: 'ESPN', networkId: 'espn',
        networkFamily: 'disney', changeUrl: 'https://example.com/wiki/change',
        crewSource: 'published_lineup', crewSourceUrl: 'https://example.com/lineup',
      }), opener);
      const d = document.getElementById('nfl-detail-panel');
      const out = {
        open: p.isOpen(), labelled: d.getAttribute('aria-labelledby'),
        title: document.getElementById('nfl-panel-title').textContent,
        closeLabel: d.querySelector('.panel-close').getAttribute('aria-label'),
        headings: [...d.querySelectorAll('h3')].map((h) => h.textContent),
        paras: [...d.querySelectorAll('.panel-body > p')].map((x) => x.textContent),
        mark: (() => {
          const m = d.querySelector('.panel-networks .net-mark');
          const img = m.querySelector('img');
          return { alt: img?.alt, title: img?.title, text: m.textContent, pills: d.querySelectorAll('.panel-networks .pill').length };
        })(),
        hrefs: [...d.querySelectorAll('.panel-links a')].map((a) => a.getAttribute('href')),
        wiki: [...d.querySelectorAll('.panel-body > p a')].map((a) => [a.textContent, a.getAttribute('href')]),
        crewBox: d.querySelectorAll('.crew-box .panel-crew li').length,
        rolePills: d.querySelectorAll('.crew-box .role-pill').length,
        boxText: d.querySelector('.crew-box').textContent,
        links: [...d.querySelectorAll('.panel-links li')].map((li) => li.textContent),
        anchors: [...d.querySelectorAll('a')].map((a) => [a.target, a.rel, a.textContent]),
        text: d.textContent.toLowerCase(),
        oldFields: d.querySelectorAll('.panel-field, .nfl-pill').length,
      };
      p.close();
      out.closed = p.isOpen();
      out.focusBack = document.activeElement === opener;
      return out;
    """)
    assert got["open"] is True
    assert got["labelled"] == "nfl-panel-title"
    assert got["title"] == "Harbor Gulls 24 at Northfield Lanterns 27"
    assert got["closeLabel"] == "Close details"
    assert got["headings"] == ["Crew", "Links"]
    paras = got["paras"]
    assert paras[0] == "Sunday, Sep 7, 2025 · 1:00 PM ET"
    assert paras[1] == "Network: "  # the logo carries the name as alt/title
    # SHELL-05: the espn id shows its logo (alt/title = name, no text), no pill.
    assert got["mark"] == {"alt": "ESPN", "title": "ESPN", "text": "", "pills": 0}
    # RT-11: the Wikipedia link's href is the row's changeUrl.
    assert got["wiki"] == [["Wikipedia (CC BY-SA 4.0)", "https://example.com/wiki/change"]]
    # RT-28: record and original-source hrefs, not only the link text.
    assert got["hrefs"] == [
        "https://example.com/rr/1",
        "https://example.com/src/1",
        "https://example.com/lineup",
    ]
    assert got["crewBox"] == 3 and got["rolePills"] >= 2
    assert "From published lineup." in got["boxText"]
    assert "Viewers: 12.3MM · Window-level figure (all Sunday afternoon games)." in paras
    assert "Measured under Nielsen panel plus out-of-home." in paras
    facts = next(x for x in paras if x.startswith("Slot:"))
    assert "Slot: Monday Night Football (MNF). Shares its window." in facts
    assert "Flexed from SNF on NBC." in facts and "Wikipedia (CC BY-SA 4.0)" in facts
    assert "Final score: Lanterns 27, Gulls 24." in facts
    assert "Excitement: 7.3 (GEI-style, not CFBD's index)." in facts
    assert got["links"] == [
        "View record on Ratings Reference ↗",
        "View original source ↗",
        "Crew source: published lineup ↗",
    ]
    assert len(got["anchors"]) == 4
    for target, rel, _text in got["anchors"]:
        assert target == "_blank" and rel == "noopener noreferrer"
    assert got["oldFields"] == 0
    assert "spread" not in got["text"] and "excitementindex" not in got["text"]
    assert got["closed"] is False
    assert got["focusBack"] is True


def test_table_network_cell_uses_marks(run: Callable[[str], Any]) -> None:
    got = run("""
      const t = T.createGamesTable(host, { onOpen: () => {} });
      t.render([
        mk({ i: 0, date: '2025-09-07', networkId: 'fox' }),
        mk({ i: 1, date: '2025-09-14', network: 'Invented Net', networkId: 'invented-net' }),
      ]);
      return [...host.querySelectorAll('tbody tr')].map((tr) => {
        const m = tr.children[3].querySelector('.net-mark');
        const img = m.querySelector('img');
        return { alt: img?.alt ?? null, title: img?.title ?? null, name: m.querySelector('.net-name')?.textContent ?? null, pills: tr.children[3].querySelectorAll('.pill').length };
      });
    """)
    # Newest first: the id with no logo falls back to dot plus name, the fox id shows its logo.
    assert got == [
        {"alt": None, "title": None, "name": "Invented Net", "pills": 0},
        {"alt": "Fox", "title": "Fox", "name": None, "pills": 0},
    ]


def test_panel_unrated_and_unsafe_links(run: Callable[[str], Any]) -> None:
    got = run("""
      const p = PN.createDetailPanel(host, {});
      p.open(mk({
        viewers: null, scope: null, cause: 'regional', era: null, excitement: null,
        kickoff: null, network: null, crew: [], rrUrl: 'javascript:alert(1)', sourceUrl: null,
        flexed: true, originalSlot: null, originalNetwork: null, changeUrl: 'javascript:1',
        standalone: true,
      }), null);
      const d = document.getElementById('nfl-detail-panel');
      return {
        paras: [...d.querySelectorAll('.panel-body > p')].map((x) => x.textContent),
        links: [...d.querySelectorAll('.panel-links li')].map((li) => li.textContent),
        anchors: d.querySelectorAll('a').length,
      };
    """)
    paras = got["paras"]
    assert paras[0] == "Sunday, Sep 7, 2025 · Kickoff time not recorded"
    assert "Network not recorded." in paras and "Crew not listed." in paras
    assert "Viewers: not available (Ratings Reference does not compile regional games)" in paras
    assert not any(x.startswith("Measured under") for x in paras)
    facts = next(x for x in paras if x.startswith("Slot:"))
    assert "Solo slot." in facts and "Excitement: not available." in facts
    # RT-11 plain sentence when changeUrl is unsafe/absent.
    assert "Source: Wikipedia (CC BY-SA 4.0)." in facts
    assert got["links"] == []
    assert got["anchors"] == 0


def test_panel_replaces_content_and_esc_closes(
    nfl_guarded_page: Page, open_flagon_cfb: Callable[..., None]
) -> None:
    open_flagon_cfb(nfl_guarded_page)
    nfl_guarded_page.evaluate(
        "async () => {"
        + PRELUDE
        + """
      window.__p = PN.createDetailPanel(host, {});
      window.__p.open(base, null);
      window.__p.open(mk({ away: 'Second Away', home: 'Second Home' }), null);
    }"""
    )
    assert nfl_guarded_page.locator("dialog#nfl-detail-panel").count() == 1
    assert (
        nfl_guarded_page.locator("#nfl-panel-title").inner_text()
        == "Second Away 24 at Second Home 27"
    )
    nfl_guarded_page.keyboard.press("Escape")
    assert nfl_guarded_page.evaluate("window.__p.isOpen()") is False


def test_panel_on_mobile(nfl_mobile_page: Page, open_flagon_cfb: Callable[..., None]) -> None:
    open_flagon_cfb(nfl_mobile_page)
    nfl_mobile_page.evaluate(
        "async () => {"
        + PRELUDE
        + """
      window.__p = PN.createDetailPanel(host, {});
      window.__p.open(base, null);
    }"""
    )
    assert nfl_mobile_page.evaluate("window.__p.isOpen()") is True
    assert nfl_mobile_page.locator("#nfl-panel-title").is_visible()
    nfl_mobile_page.locator("#nfl-detail-panel .panel-close").click()
    assert nfl_mobile_page.evaluate("window.__p.isOpen()") is False
