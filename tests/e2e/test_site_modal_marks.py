"""Phase 28 (28-04): the ranked badge and conference logos in the CFB game modal and the
Matched games table.

The synthetic contract fixture's conferences are Big Ten (0), FBS Independents (1), Missouri
Valley (2), Mountain West (3), Pac-12 (4) and SEC (5). Telecast 0 is a 2019 SEC vs. Pac-12 game
with no ranks; telecast 4 is a 2025 Big Ten vs. SEC game with both teams ranked. Each test
serves an in-memory copy of the fixture (never the shared file); no vault data.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

OpenApp = Callable[[Page, str], None]

_QUERY = "?school=northfield"  # telecasts 0, 4 and 8 fill the Matched games table


def _serve(page: Page, raw: dict[str, Any]) -> None:
    page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))


def _mutated(fixture_raw: dict[str, Any], **columns: dict[int, Any]) -> dict[str, Any]:
    """A deep copy of the fixture with `telecasts[column][i] = value` for each pair given."""
    raw = copy.deepcopy(fixture_raw)
    for column, changes in columns.items():
        for i, value in changes.items():
            raw["telecasts"][column][i] = value
    return raw


def _open_panel(page: Page, i: int) -> None:
    page.evaluate(f"window.__testHooks.openPanel({i})")
    page.wait_for_selector("#detail-panel[open]")


def _conference_parts(page: Page) -> list[dict[str, str]]:
    """The Conference line's parts in order: logos (alt, title, src) and text runs."""
    result: list[dict[str, str]] = page.evaluate(
        """() => {
          const line = document.querySelector('#panel-body .panel-conferences .cf-line');
          return [...line.childNodes].map((n) => {
            if (n.nodeType === Node.TEXT_NODE) return { kind: 'text', text: n.textContent };
            if (n.matches('img.cf-logo')) {
              return { kind: 'logo', alt: n.alt, title: n.title, src: n.getAttribute('src') };
            }
            return { kind: n.className, text: n.textContent };
          });
        }"""
    )
    return result


# ------------------------------------------------------------------ modal title


def test_modal_title_badge_for_a_both_ranked_game(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """D-01, D-02, D-04: the badge ends the title, is aria-hidden, the ranks stay superscript,
    and the title's aria-label gains '. Both teams ranked.'"""
    _serve(guarded_page, _mutated(fixture_raw, away_rank={0: 7}, home_rank={0: 12}))
    open_app(guarded_page, "")
    _open_panel(guarded_page, 0)
    title = guarded_page.locator("#panel-title")
    assert title.locator(".rk-badge").count() == 1
    # The badge ends the title, glued to its last word so it never wraps alone.
    assert guarded_page.evaluate(
        """() => {
          const glue = document.querySelector('#panel-title').lastChild;
          return glue.classList.contains('rk-glue')
            && glue.lastChild.classList.contains('rk-badge');
        }"""
    )
    assert title.text_content() == "7Lakeview 20 at 12Northfield 27"
    assert title.locator(".rk-badge svg").get_attribute("aria-hidden") == "true"
    assert title.locator("sup.title-rank").count() == 2
    label = title.get_attribute("aria-label") or ""
    assert label == "#7 Lakeview 20 at #12 Northfield 27. Both teams ranked."


def test_modal_title_label_adds_no_second_full_stop(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """WR-02: an unscored matchup whose last team name ends in a full stop gains the sentence
    after one space, never '..'."""
    raw = _mutated(
        fixture_raw,
        away_rank={0: 7},
        home_rank={0: 12},
        away_points={0: None},
        home_points={0: None},
    )
    home = raw["telecasts"]["home_team"][0]
    raw["lookups"]["teams"][home]["name"] = "Northfield St."
    _serve(guarded_page, raw)
    open_app(guarded_page, "")
    _open_panel(guarded_page, 0)
    label = guarded_page.get_attribute("#panel-title", "aria-label")
    assert label == "#7 Lakeview at #12 Northfield St. Both teams ranked."


def test_modal_title_has_no_badge_when_one_team_is_ranked(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    _serve(guarded_page, _mutated(fixture_raw, away_rank={0: 7}))
    open_app(guarded_page, "")
    _open_panel(guarded_page, 0)
    title = guarded_page.locator("#panel-title")
    assert title.locator(".rk-badge").count() == 0
    assert "ranked" not in (title.get_attribute("aria-label") or "")


def _title_height(page: Page, open_app: OpenApp, raw: dict[str, Any]) -> float:
    page.unroute("**/site-data.json*")
    _serve(page, raw)
    open_app(page, "")
    _open_panel(page, 0)
    return float(
        page.evaluate("document.querySelector('#panel-title').getBoundingClientRect().height")
    )


def _assert_title_height_unchanged(
    page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    ranked = _title_height(
        page, open_app, _mutated(fixture_raw, away_rank={0: 7}, home_rank={0: 12})
    )
    assert page.locator("#panel-title .rk-badge").count() == 1
    one = _title_height(page, open_app, _mutated(fixture_raw, away_rank={0: 7}))
    assert page.locator("#panel-title .rk-badge").count() == 0
    assert ranked == pytest.approx(one, abs=0.01)


def test_modal_title_badge_does_not_change_the_title_height(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """D-05: the 26px inline badge leaves the title exactly as tall."""
    _assert_title_height_unchanged(guarded_page, open_app, fixture_raw)


def test_phone_modal_title_badge_never_sits_alone_on_a_line(
    mobile_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """At the phone width the title may wrap; the badge stays on the line of the title's last
    word (a no-wrap span), centred where the sketch put it (5px below the baseline)."""
    page = mobile_page
    _serve(page, _mutated(fixture_raw, away_rank={0: 7}, home_rank={0: 12}))
    open_app(page, "")
    _open_panel(page, 0)
    got = page.evaluate(
        """() => {
          const glue = document.querySelector('#panel-title .rk-glue');
          const range = document.createRange();
          range.selectNodeContents(glue.firstChild);
          const word = range.getBoundingClientRect();
          const badge = glue.querySelector('.rk-badge').getBoundingClientRect();
          return { word: glue.firstChild.textContent, wordTop: word.top, wordBottom: word.bottom,
                   badgeTop: badge.top, badgeBottom: badge.bottom,
                   gap: badge.left - word.right };
        }"""
    )
    assert got["word"] == "27"
    assert got["badgeTop"] < got["wordBottom"]
    assert got["badgeBottom"] > got["wordTop"]
    assert got["gap"] == pytest.approx(10, abs=0.5)


# ------------------------------------------------------------------ Conference line


def test_conference_line_shows_both_logos_in_order(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """D-12, D-13: 'Conference: [SEC] vs. [Pac-12]' for telecast 0, 2019 logos."""
    _serve(guarded_page, copy.deepcopy(fixture_raw))
    open_app(guarded_page, "")
    _open_panel(guarded_page, 0)
    line = guarded_page.locator("#panel-body .panel-conferences")
    assert line.inner_text().startswith("Conference:")
    parts = _conference_parts(guarded_page)
    assert [p["kind"] for p in parts] == ["logo", "cf-sep", "logo"]
    assert [p["alt"] for p in parts if p["kind"] == "logo"] == ["SEC", "Pac-12"]
    assert [p["title"] for p in parts if p["kind"] == "logo"] == ["SEC", "Pac-12"]
    assert parts[1]["text"] == "vs."
    assert parts[0]["src"] == "logos/conf/southeastern-conference-before-2024.svg"
    assert parts[2]["src"] == "logos/conf/pac-12-conference-before-2026.svg"
    heights = guarded_page.eval_on_selector_all(
        "#panel-body .panel-conferences img.cf-logo",
        "els => els.map((e) => e.getBoundingClientRect().height)",
    )
    # Sized by area: 20px nominal times each file's scale (SEC 2019 1.13, Pac-12 shield 1.25).
    assert heights == [pytest.approx(22.6, abs=0.01), pytest.approx(25, abs=0.01)]
    assert guarded_page.evaluate(
        "[...document.querySelectorAll('#panel-body img.cf-logo')]"
        ".every((img) => img.complete && img.naturalWidth > 0)"
    )


def test_same_conference_game_shows_one_logo(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """D-13: both teams in the SEC: one logo, no separator."""
    _serve(guarded_page, _mutated(fixture_raw, away_conference={0: 5}, home_conference={0: 5}))
    open_app(guarded_page, "")
    _open_panel(guarded_page, 0)
    parts = _conference_parts(guarded_page)
    assert parts == [
        {
            "kind": "logo",
            "alt": "SEC",
            "title": "SEC",
            "src": "logos/conf/southeastern-conference-before-2024.svg",
        }
    ]
    assert guarded_page.locator("#panel-body .panel-conferences .cf-sep").count() == 0


def test_conference_without_a_logo_reads_as_text(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """D-11: Missouri Valley (FCS) and FBS Independents have no logo: their names show as text."""
    _serve(guarded_page, _mutated(fixture_raw, away_conference={0: 2}, home_conference={0: 1}))
    open_app(guarded_page, "")
    _open_panel(guarded_page, 0)
    parts = _conference_parts(guarded_page)
    assert parts == [
        {"kind": "text", "text": "Missouri Valley"},
        {"kind": "cf-sep", "text": "vs."},
        {"kind": "text", "text": "FBS Independents"},
    ]
    text = re.sub(r"\s+", " ", guarded_page.locator("#panel-body .panel-conferences").inner_text())
    assert text == "Conference: Missouri Valley vs. FBS Independents"


def test_a_side_without_a_conference_reads_not_recorded(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    _serve(guarded_page, _mutated(fixture_raw, home_conference={0: None}))
    open_app(guarded_page, "")
    _open_panel(guarded_page, 0)
    parts = _conference_parts(guarded_page)
    assert [p["kind"] for p in parts] == ["logo", "cf-sep", "text"]
    assert parts[0]["alt"] == "SEC"
    assert parts[2]["text"] == "Not recorded"


def test_conference_logo_follows_the_game_season(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """D-09: the same SEC game in 2024 shows the 2024-present file."""
    _serve(guarded_page, _mutated(fixture_raw, season={0: 2024}))
    open_app(guarded_page, "")
    _open_panel(guarded_page, 0)
    sec = _conference_parts(guarded_page)[0]
    assert sec["alt"] == "SEC"
    assert sec["src"].endswith("southeastern-conference-2024-present.svg")


def test_conference_logos_use_dark_files_in_dark_theme(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """D-14: in dark theme the modal logos come from logos/dark/conf/; a live flip swaps them."""
    _serve(guarded_page, copy.deepcopy(fixture_raw))
    open_app(guarded_page, "")
    guarded_page.evaluate("document.documentElement.dataset.theme = 'dark'")
    _open_panel(guarded_page, 0)
    srcs = guarded_page.eval_on_selector_all(
        "#panel-body .panel-conferences img.cf-logo", "els => els.map((e) => e.src)"
    )
    assert len(srcs) == 2
    assert all("/logos/dark/conf/" in s for s in srcs)
    guarded_page.evaluate("document.documentElement.dataset.theme = 'light'")
    guarded_page.wait_for_function(
        "[...document.querySelectorAll('#panel-body img.cf-logo')]"
        ".every((i) => i.src.includes('/logos/conf/') && !i.src.includes('/dark/'))"
    )


def test_wide_conference_logo_is_capped_without_squashing(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """UI-SPEC: modal logos are 20px high and at most 64px wide; a wider wordmark (C-USA 2019,
    102px at 20px high) is fitted inside the box rather than stretched."""
    raw = copy.deepcopy(fixture_raw)
    raw["lookups"]["conferences"][4]["name"] = "Conference USA"
    _serve(guarded_page, raw)
    open_app(guarded_page, "")
    _open_panel(guarded_page, 0)
    box = guarded_page.evaluate(
        """() => {
          const img = [...document.querySelectorAll('#panel-body .panel-conferences img.cf-logo')]
            .find((e) => e.alt === 'Conference USA');
          const r = img.getBoundingClientRect();
          return { w: r.width, h: r.height, fit: getComputedStyle(img).objectFit };
        }"""
    )
    assert box["w"] <= 64.01
    assert box["h"] == pytest.approx(11, abs=0.01)  # 20px x the 0.55 area scale
    assert box["fit"] == "contain"


_LINE_H_JS = """() => {
  const line = document.querySelector('#panel-body .panel-conferences');
  const marks = [...line.querySelectorAll('img.cf-logo')].map((i) => {
    const cs = getComputedStyle(i);
    return i.getBoundingClientRect().height + parseFloat(cs.marginTop)
      + parseFloat(cs.marginBottom);
  });
  return { line: line.getBoundingClientRect().height, marks,
           title: document.querySelector('#panel-title').getBoundingClientRect().height };
}"""


def test_area_sized_logos_never_change_the_conference_line_height(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """D-05: grown shields and shrunk wordmarks keep a 20px margin box, so the Conference line
    is as tall with logos as with text only."""
    _serve(guarded_page, copy.deepcopy(fixture_raw))
    open_app(guarded_page, "")
    _open_panel(guarded_page, 0)
    logos = guarded_page.evaluate(_LINE_H_JS)
    assert logos["marks"] == [pytest.approx(20, abs=0.01)] * 2
    _serve(guarded_page, _mutated(fixture_raw, away_conference={0: 2}, home_conference={0: 1}))
    open_app(guarded_page, "")
    _open_panel(guarded_page, 0)
    text = guarded_page.evaluate(_LINE_H_JS)
    assert text["marks"] == []
    assert logos["line"] == pytest.approx(text["line"], abs=0.01)
    assert logos["title"] == pytest.approx(text["title"], abs=0.01)


def test_conference_and_network_lines_centre_and_keep_their_spaces(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """Sketch 008: both lines are flex rows centred on the text, and 'Network: ', '; also on: '
    and ' vs. ' keep visible space before the next mark."""
    raw = copy.deepcopy(fixture_raw)
    raw["lookups"]["networks"][0]["id"] = "espn"
    raw["lookups"]["networks"][1]["id"] = "abc"
    raw["telecasts"]["outlets"][0] = [0, 1]
    _serve(guarded_page, raw)
    open_app(guarded_page, "")
    _open_panel(guarded_page, 0)
    got = guarded_page.evaluate(
        """() => {
          const cs = (sel) => getComputedStyle(document.querySelector(sel));
          const runs = [
            ...document.querySelectorAll('#panel-body .panel-networks .panel-mark-text'),
          ];
          const gapAfter = (el) => {
            // The run's glyphs end where its trimmed text ends; the gap is from there to the
            // next mark, so a dropped trailing space shows as a gap near 0.
            const next = el.nextElementSibling;
            const range = document.createRange();
            const text = el.firstChild;
            range.setStart(text, 0);
            range.setEnd(text, text.textContent.trimEnd().length);
            const inkEnd = range.getBoundingClientRect().right;
            return next.getBoundingClientRect().left - inkEnd;
          };
          const sep = document.querySelector('#panel-body .panel-conferences .cf-sep');
          const sepRect = sep.getBoundingClientRect();
          const logos = [...document.querySelectorAll('#panel-body .panel-conferences img.cf-logo')]
            .map((e) => e.getBoundingClientRect());
          const label = document.querySelector('#panel-body .panel-conferences .panel-mark-text');
          return {
            netDisplay: cs('#panel-body .panel-networks').display,
            netAlign: cs('#panel-body .panel-networks').alignItems,
            confDisplay: cs('#panel-body .panel-conferences').display,
            confAlign: cs('#panel-body .panel-conferences').alignItems,
            runs: runs.map((r) => r.textContent),
            gaps: runs.map(gapAfter),
            labelGap: gapAfter(label),
            sepBefore: sepRect.left - logos[0].right,
            sepAfter: logos[1].left - sepRect.right,
          };
        }"""
    )
    assert got["netDisplay"] == "flex"
    assert got["netAlign"] == "center"
    assert got["confDisplay"] == "flex"
    assert got["confAlign"] == "center"
    assert got["runs"] == ["Network: ", "; also on: "]
    assert all(g >= 3 for g in got["gaps"]), got
    assert got["labelGap"] >= 3, got
    assert got["sepBefore"] >= 3, got
    assert got["sepAfter"] >= 3, got


def test_hostile_conference_name_stays_literal_text(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """T-28-14: a hostile conference name misses the logo map and lands as plain text."""
    raw = copy.deepcopy(fixture_raw)
    payload = '<img src=x onerror="window.__xssConf=1">'
    raw["lookups"]["conferences"][5]["name"] = payload
    _serve(guarded_page, raw)
    open_app(guarded_page, "")
    _open_panel(guarded_page, 0)
    assert guarded_page.evaluate("window.__xssConf") is None
    parts = _conference_parts(guarded_page)
    assert parts[0] == {"kind": "text", "text": payload}
    assert guarded_page.locator("#panel-body .panel-conferences img").count() == 1


# ------------------------------------------------------------------ Matched games


def _badge_row_index(page: Page) -> int:
    index: int = page.evaluate(
        "[...document.querySelectorAll('#games-table tbody tr')]"
        ".findIndex((tr) => tr.querySelector('td.matchup .rk-badge'))"
    )
    return index


def _row_height(page: Page, index: int) -> float:
    return float(
        page.evaluate(
            "(k) => document.querySelectorAll('#games-table tbody tr')[k]"
            ".getBoundingClientRect().height",
            index,
        )
    )


def test_matched_games_badge_for_a_both_ranked_game(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """D-01, D-04: telecast 4 (both ranked) ends its matchup cell with one badge that keeps
    role img and its own label; the other rows have none."""
    _serve(guarded_page, copy.deepcopy(fixture_raw))
    open_app(guarded_page, _QUERY)
    guarded_page.wait_for_selector("#games-table tbody tr")
    assert guarded_page.locator("#games-table tbody .rk-badge").count() == 1
    cell = guarded_page.locator("#games-table tbody td.matchup:has(.rk-badge)")
    assert cell.locator(".rk-badge").count() == 1
    svg = cell.locator(".rk-badge svg")
    assert svg.get_attribute("role") == "img"
    assert svg.get_attribute("aria-label") == "Both teams ranked"
    assert svg.get_attribute("aria-hidden") is None
    assert guarded_page.evaluate(
        "document.querySelector('#games-table td.matchup:has(.rk-badge)')"
        ".lastElementChild.classList.contains('rk-badge')"
    )
    text = cell.inner_text()
    assert text.startswith("#5 ")
    assert "#3 " in text
    row_label = guarded_page.evaluate(
        "document.querySelector('#games-table td.matchup:has(.rk-badge)')"
        ".closest('tr').getAttribute('aria-label')"
    )
    assert row_label.startswith("Details for ")
    assert "ranked" not in row_label


def test_matched_games_badge_does_not_change_the_row_height(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """D-05: the same row with the home rank removed (no badge) is exactly as tall."""
    _serve(guarded_page, copy.deepcopy(fixture_raw))
    open_app(guarded_page, _QUERY)
    guarded_page.wait_for_selector("#games-table tbody tr")
    index = _badge_row_index(guarded_page)
    assert index >= 0
    with_badge = _row_height(guarded_page, index)
    guarded_page.unroute("**/site-data.json*")
    _serve(guarded_page, _mutated(fixture_raw, home_rank={4: None}))
    open_app(guarded_page, _QUERY)
    guarded_page.wait_for_selector("#games-table tbody tr")
    assert guarded_page.locator("#games-table tbody .rk-badge").count() == 0
    assert _row_height(guarded_page, index) == pytest.approx(with_badge, abs=0.01)


# ------------------------------------------------------------------ NFL and MLB


def test_nfl_modal_and_table_show_no_marks(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    open_nfl_app(page)
    page.evaluate("window.__nflTestHooks.setState({ teams: ['f-gulls'] })")
    page.evaluate("window.__nflTestHooks.openGame(0)")
    page.wait_for_function("document.getElementById('nfl-detail-panel').open")
    assert page.locator(".rk-badge").count() == 0
    assert page.locator("img.cf-logo").count() == 0


def test_mlb_modal_and_table_show_no_marks(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_guarded_page
    open_mlb_app(page)
    page.evaluate("window.__mlbTestHooks.setState({ cell: '2014-wild_card-AL' })")
    assert page.locator("#mlb-matched-games tbody tr").count() > 0
    page.evaluate("window.__mlbTestHooks.openGame(6)")
    page.wait_for_selector("#mlb-detail-panel[open]")
    assert page.locator(".rk-badge").count() == 0
    assert page.locator("img.cf-logo").count() == 0
