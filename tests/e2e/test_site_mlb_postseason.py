"""09-19: the MLB postseason booths grid on the synthetic MLB fixture.

Fixture seasons: 2014 (50% crews listed), 2019 (100%), 2025 (100%), 2026 (50%, excitement pending).
Cells: 2014 wild card AL (no crew), 2014 World Series (Wikipedia crew, 12.0M), 2019 division
AL (two games), 2019 LCS NL (5.5M, window-level), 2025 wild card NL, 2025 World Series, 2026 LCS AL,
2026 division NL.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from playwright.sync_api import Page, Route

pytestmark = pytest.mark.e2e

HOOKS = "window.__mlbTestHooks"
VIEW = "#mlb-view-postseason"


@pytest.fixture
def post(mlb_guarded_page: Page, open_mlb_app: Callable[..., None]) -> Page:
    open_mlb_app(mlb_guarded_page, "?sport=mlb&view=postseason")
    return mlb_guarded_page


def test_grid_rows_and_columns(post: Page) -> None:
    seasons = post.eval_on_selector_all(
        f"{VIEW} tbody th .mlb-season", "els => els.map(e => e.textContent)"
    )
    assert seasons == ["2026", "2025", "2019", "2014"]
    heads = post.eval_on_selector_all(
        f"{VIEW} .mlb-grid thead th", "els => els.map(e => e.innerText)"
    )
    assert heads == [
        "Season",
        "Wild Card",
        "Division Series",
        "League Championship Series",
        "World Series",
    ]
    assert post.locator(f"{VIEW} .mlb-grid th[scope='row']").count() == 4


def test_coverage_per_season_and_low_tone(post: Page) -> None:
    cov = post.eval_on_selector_all(
        f"{VIEW} .mlb-grid .mlb-season-coverage", "els => els.map(e => e.textContent)"
    )
    # Counts come from the builder's season table; 2019 has one postseason game that
    # sits in no cell, so its denominator is larger than its cells'.
    assert cov == [
        "Crews listed for 1 of 2 postseason games (50%)",
        "Crews listed for 2 of 2 postseason games (100%)",
        "Crews listed for 3 of 4 postseason games (75%)",
        "Crews listed for 1 of 2 postseason games (50%)",
    ]
    low = post.eval_on_selector_all(
        f"{VIEW} .mlb-grid .mlb-season-coverage[data-low='true']", "els => els.length"
    )
    assert low == 3


def test_wikipedia_outlets_are_credited_per_season(post: Page) -> None:
    links = post.eval_on_selector_all(
        f"{VIEW} .mlb-grid .mlb-season-credit",
        "els => els.map(e => [e.textContent, e.getAttribute('href'), e.getAttribute('rel')])",
    )
    assert [t for t, _, _ in links] == [
        "Outlets: Wikipedia 2019 postseason (CC BY-SA 4.0) ↗",
        "Outlets: Wikipedia 2014 postseason (CC BY-SA 4.0) ↗",
    ]
    assert [h for _, h, _ in links] == [
        "https://example.org/wiki/2019_Invented_Series",
        "https://example.org/wiki/2014_Invented_Series",
    ]
    assert all("noopener" in (r or "") for _, _, r in links)


def _cell_marks(page: Page, cell: str) -> list[dict[str, str | None]]:
    return page.eval_on_selector_all(  # type: ignore[no-any-return]
        f"{VIEW} button[data-cell='{cell}'] .mlb-cell-head .net-mark",
        """els => els.map(m => ({
          alt: m.querySelector('img')?.getAttribute('alt') ?? null,
          title: m.querySelector('img')?.getAttribute('title') ?? null,
          name: m.querySelector('.net-name')?.textContent ?? null,
        }))""",
    )


def test_a_split_cell_shows_every_outlet(post: Page) -> None:
    """SHELL-05: each outlet is a logo by id with alt/title = name, in the lookup order."""
    marks = _cell_marks(post, "2025-wild_card-NL")
    assert marks == [
        {"alt": "ESPN", "title": "ESPN", "name": None},
        {"alt": "TBS", "title": "TBS", "name": None},
    ]
    assert post.locator(f"{VIEW} .mlb-cell-head .pill").count() == 0
    # A logo stands alone: no family dot beside it (brief §5).
    cell = post.locator(f"{VIEW} button[data-cell='2025-wild_card-NL'] .mlb-cell-head")
    assert cell.locator(".net-dot").count() == 0


def test_outlet_without_a_logo_falls_back_to_dot_and_name(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    def handler(route: Route) -> None:
        resp = route.fetch()
        data = json.loads(resp.text())
        data["lookups"]["networks"][1].update({"id": "mlbn", "name": "MLB Network"})
        route.fulfill(response=resp, body=json.dumps(data))

    mlb_guarded_page.route("**/mlb-data.json", handler)
    open_mlb_app(mlb_guarded_page, "?sport=mlb&view=postseason")
    assert _cell_marks(mlb_guarded_page, "2014-world_series-all") == [
        {"alt": None, "title": None, "name": "MLB Network"}
    ]
    head = f"{VIEW} button[data-cell='2014-world_series-all'] .mlb-cell-head"
    assert mlb_guarded_page.locator(f"{head} .net-dot").count() == 1


def test_crew_not_listed_and_al_nl_split(post: Page) -> None:
    wc = post.locator(f"{VIEW} button[data-cell='2014-wild_card-AL']")
    assert "crew not listed" in wc.inner_text()
    assert "AL" in wc.inner_text()
    div = post.locator(f"{VIEW} tr[data-season='2019'] td[data-round='division'] button")
    assert div.count() == 1
    lcs = post.locator(f"{VIEW} tr[data-season='2019'] td[data-round='lcs'] button")
    assert "NL" in lcs.inner_text()
    ws = post.locator(f"{VIEW} button[data-cell='2014-world_series-all']")
    assert "AL" not in ws.inner_text().split()
    assert (
        post.locator(f"{VIEW} tr[data-season='2014'] td[data-round='division']")
        .inner_text()
        .endswith("—")
    )


def test_wikipedia_crew_excitement_and_viewers(post: Page) -> None:
    ws = post.locator(f"{VIEW} button[data-cell='2014-world_series-all']").inner_text()
    assert "Gus Penn" in ws
    assert "Hana Voss" in ws
    assert _cell_marks(post, "2014-world_series-all") == [
        {"alt": "Fox", "title": "Fox", "name": None}
    ]
    assert "Excitement 2.40 (1 game)" in ws
    assert "Avg 12.0M viewers, 1 of 1 games rated" in ws
    two = post.locator(f"{VIEW} button[data-cell='2019-division-AL']").inner_text()
    assert "2 games" in two
    assert "Excitement 1.25 (2 games)" in two
    assert "viewers" not in two


def test_2026_excitement_pending_and_no_stakes(post: Page) -> None:
    cell = post.locator(f"{VIEW} button[data-cell='2026-lcs-AL']").inner_text()
    assert "pending Retrosheet 2026" in cell
    assert "stakes" not in post.inner_text(VIEW).lower()


def test_a_historic_cell_without_excitement_is_not_called_pending(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    def handler(route: Route) -> None:
        resp = route.fetch()
        data = json.loads(resp.text())
        p = data["postseason"]
        k = next(i for i, s in enumerate(p["season"]) if s == 2019 and p["round"][i] == "division")
        p["mean_excitement"][k] = None
        p["excitement_n"][k] = 0
        route.fulfill(response=resp, body=json.dumps(data))

    mlb_guarded_page.route("**/mlb-data.json", handler)
    open_mlb_app(mlb_guarded_page, "?sport=mlb&view=postseason")
    old = mlb_guarded_page.locator(f"{VIEW} button[data-cell='2019-division-AL']").inner_text()
    assert "no excitement figure" in old and "pending" not in old
    # Quality is still pending (Apple booths), and 2026 is past Retrosheet's coverage.
    new = mlb_guarded_page.locator(f"{VIEW} button[data-cell='2026-lcs-AL']").inner_text()
    assert "pending Retrosheet 2026" in new


def test_cell_click_lists_games_and_deep_link(
    post: Page, open_mlb_app: Callable[..., None]
) -> None:
    post.click(f"{VIEW} button[data-cell='2019-division-AL']")
    assert post.evaluate(f"{HOOKS}.getTableIndexes()") == [9, 8]
    assert "cell=2019-division-AL" in post.url
    assert post.locator(f"{VIEW} .mlb-grid button[aria-pressed='true']").count() == 1
    post.click(f"{VIEW} button[data-cell='2019-division-AL']")
    assert post.evaluate(f"{HOOKS}.getTableIndexes()") == []
    open_mlb_app(post, "?sport=mlb&view=postseason&cell=2014-world_series-all")
    assert post.evaluate(f"{HOOKS}.getTableIndexes()") == [7]
    assert (
        post.locator(
            f"{VIEW} button[data-cell='2014-world_series-all'][aria-pressed='true']"
        ).count()
        == 1
    )


def test_unknown_cell_param_is_ignored(post: Page, open_mlb_app: Callable[..., None]) -> None:
    open_mlb_app(post, "?sport=mlb&view=postseason&cell=1999-division-AL")
    assert post.evaluate(f"{HOOKS}.getTableIndexes()") == []
    assert post.evaluate(f"{HOOKS}.getState().cell") is None


def test_phone_twin_has_a_merged_pinned_column_and_booths(
    mlb_mobile_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """13-14: 480px and under swaps the grid for one row per season, round and league."""
    page = mlb_mobile_page
    open_mlb_app(page, "?sport=mlb&view=postseason")
    assert page.locator(f"{VIEW} .mlb-grid").is_hidden()
    twin = page.locator(f"{VIEW} .mlb-phone-grid")
    assert twin.is_visible()
    assert twin.locator("thead th").all_inner_texts() == ["Season and round", "Booths"]
    first = twin.locator("tbody th.mlb-merged-col").first
    assert first.evaluate("e => e.getBoundingClientRect().width") == 96
    assert first.evaluate("e => getComputedStyle(e).position") == "sticky"
    lines = first.locator(".mlb-merged-line").all_inner_texts()
    assert lines[0].endswith(("Wild Card", "LCS", "Division Series", "World Series"))
    old = twin.locator("tbody tr[data-season='2014'] th.mlb-merged-col").first
    assert old.locator(".mlb-merged-line").all_inner_texts() == ["2014 Wild Card", "AL"]
    assert twin.locator("td.mlb-booths-col").first.evaluate("e => e.offsetWidth") >= 200
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.locator(f"{VIEW} button[data-phone-cell='2014-world_series-all']").tap()
    assert page.evaluate(f"{HOOKS}.getTableIndexes()") == [7]


def test_phone_lists_each_season_credit_and_coverage(
    mlb_mobile_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """RT-13 per season at 480px and under: the season list under the phone twin carries the
    visible Wikipedia credit, the coverage line and its low marker the hidden grid holds."""
    page = mlb_mobile_page
    open_mlb_app(page, "?sport=mlb&view=postseason")
    twin = page.locator(f"{VIEW} .mlb-phone-season-notes")
    assert twin.locator("li .mlb-season").all_inner_texts() == ["2026", "2025", "2019", "2014"]
    credits = twin.locator(".mlb-season-credit")
    assert credits.count() == 2
    assert all(credits.nth(i).is_visible() for i in range(2))
    assert [credits.nth(i).get_attribute("href") for i in range(2)] == [
        "https://example.org/wiki/2019_Invented_Series",
        "https://example.org/wiki/2014_Invented_Series",
    ]
    cov = twin.locator(".mlb-season-coverage")
    assert cov.count() == 4
    assert all(cov.nth(i).is_visible() for i in range(4))
    assert twin.locator(".mlb-season-coverage[data-low='true']").count() == 3


def test_phone_booths_cell_caps_lines_with_plus_n_more(
    mlb_mobile_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """13-14: a cell with more booths than the line budget ends in '+N more'."""

    def handler(route: Route) -> None:
        resp = route.fetch()
        data = json.loads(resp.text())
        p = data["postseason"]
        k = next(i for i, s in enumerate(p["season"]) if s == 2019 and p["round"][i] == "division")
        # Five crews with no person in common, so five booth lines (U3 groups shared people).
        p["booths"][k] = [[8, 7], [6, None], [2, 3], [0, 1], [4, 5]]
        route.fulfill(response=resp, body=json.dumps(data))

    mlb_mobile_page.route("**/mlb-data.json", handler)
    open_mlb_app(mlb_mobile_page, "?sport=mlb&view=postseason")
    cell = mlb_mobile_page.locator(f"{VIEW} button[data-phone-cell='2019-division-AL']")
    assert cell.locator(".mlb-cell-booth").count() == 3
    assert cell.locator(".mlb-booth-more").inner_text() == "+2 more"


def test_phone_twin_has_no_scroll_box_or_cue(
    mlb_mobile_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """N1 on phones: the page scrolls, the twin header sticks to the viewport, no inner scroller."""
    page = mlb_mobile_page
    open_mlb_app(page, "?sport=mlb&view=postseason")
    scrolling = page.evaluate(
        """() => {
          const bad = [];
          let n = document.querySelector('#mlb-view-postseason .mlb-phone-grid');
          while (n && n !== document.documentElement) {
            const o = getComputedStyle(n).overflowY;
            if (o !== 'visible') bad.push(n.className + ':' + o);
            n = n.parentElement;
          }
          return bad;
        }"""
    )
    assert scrolling == []
    pos = page.eval_on_selector(
        f"{VIEW} .mlb-phone-grid thead th", "e => getComputedStyle(e).position"
    )
    assert pos == "sticky"
    top = page.eval_on_selector(f"{VIEW} .mlb-phone-grid thead th", "e => getComputedStyle(e).top")
    assert top == "0px"
    assert page.locator(f"{VIEW} .mlb-phone-wrap.table-scroll").count() == 0


def test_desktop_grid_is_a_scroll_box_with_a_frozen_header(post: Page) -> None:
    post.set_viewport_size({"width": 1440, "height": 900})
    post.reload()
    post.wait_for_function("window.__mlbTestHooks && window.__mlbTestHooks.ready === true")
    wrap = post.locator(f"{VIEW} .mlb-grid-wrap")
    info = wrap.evaluate(
        "e => ({o: getComputedStyle(e).overflowY, m: parseFloat(getComputedStyle(e).maxHeight)})"
    )
    assert info["o"] == "auto" and info["m"] <= 640
    # Make the grid taller than the box so it scrolls, then check the header stays put.
    post.evaluate(
        "() => { const b = document.querySelector('#mlb-view-postseason .mlb-grid tbody');"
        "for (const tr of [...b.rows]) b.append(tr.cloneNode(true)); "
        "for (const tr of [...b.rows]) b.append(tr.cloneNode(true)); }"
    )
    before = post.evaluate("document.documentElement.scrollHeight")
    wrap.evaluate("e => { e.scrollTop = 400; }")
    box_top = wrap.evaluate("e => e.getBoundingClientRect().top")
    head_top = post.eval_on_selector(
        f"{VIEW} .mlb-grid thead th", "e => e.getBoundingClientRect().top"
    )
    assert abs(head_top - box_top) < 1
    assert post.evaluate("document.documentElement.scrollHeight") == before
    assert wrap.get_attribute("tabindex") == "0"


def test_lcs_head_is_short_below_1280_with_a_title(post: Page) -> None:
    post.set_viewport_size({"width": 1100, "height": 800})
    head = post.locator(f"{VIEW} .mlb-grid thead th[title]")
    assert head.inner_text() == "LCS"
    assert head.get_attribute("title") == "League Championship Series"


def test_every_round_head_keeps_a_label_below_1280(post: Page) -> None:
    post.set_viewport_size({"width": 1100, "height": 800})
    heads = post.eval_on_selector_all(
        f"{VIEW} .mlb-grid thead th", "els => els.map(e => e.innerText.trim())"
    )
    # Only LCS switches to its short form; every other round keeps its full name.
    assert heads == ["Season", "Wild Card", "Division Series", "LCS", "World Series"]


def test_season_cell_selects_the_whole_season(post: Page) -> None:
    btn = post.locator(f"{VIEW} .mlb-grid button[data-season-cell='season-2019']")
    btn.click()
    assert post.evaluate(f"{HOOKS}.getState().cell") == "season-2019"
    assert len(post.evaluate(f"{HOOKS}.getTableIndexes()")) == 3
    assert btn.get_attribute("aria-pressed") == "true"
    post.click(f"{VIEW} button[data-cell='2019-division-AL']")
    assert post.evaluate(f"{HOOKS}.getState().cell") == "2019-division-AL"
    post.click(f"{VIEW} .mlb-grid button[data-season-cell='season-2014']")
    post.click(f"{VIEW} .mlb-grid button[data-season-cell='season-2014']")
    assert post.evaluate(f"{HOOKS}.getState().cell") is None


def test_credit_link_never_selects_and_keeps_href_and_rel(post: Page) -> None:
    post.route("https://example.org/**", lambda route: route.fulfill(status=204))
    link = post.locator(f"{VIEW} .mlb-grid .mlb-season-credit").first
    href = link.get_attribute("href")
    assert link.is_visible()
    post.evaluate(
        "() => document.querySelectorAll('a.mlb-season-credit')"
        ".forEach((a) => a.addEventListener('click', (e) => e.preventDefault()))"
    )
    link.click()
    assert post.evaluate(f"{HOOKS}.getState().cell") is None
    assert link.get_attribute("href") == href
    assert "noopener" in (link.get_attribute("rel") or "")
    assert link.inner_text().startswith("Outlets: Wikipedia")


def test_picked_cell_and_season_show_fill_and_one_ink_marker(post: Page) -> None:
    marker = """row => [...row.querySelectorAll('*')].filter(
      e => /inset/.test(getComputedStyle(e).boxShadow)
        && getComputedStyle(e).boxShadow.includes('2px 0px 0px 0px')).length"""
    post.click(f"{VIEW} button[data-cell='2019-division-AL']")
    cell = post.locator(f"{VIEW} .mlb-grid tr[data-season='2019']")
    assert cell.evaluate(marker) == 1
    fill = post.eval_on_selector(
        f"{VIEW} button[data-cell='2019-division-AL']", "e => getComputedStyle(e).backgroundColor"
    )
    assert fill != "rgba(0, 0, 0, 0)"
    post.click(f"{VIEW} .mlb-grid button[data-season-cell='season-2019']")
    assert cell.evaluate(marker) == 1
    assert (
        post.eval_on_selector(
            f"{VIEW} .mlb-grid tr[data-season='2019'] th",
            "e => getComputedStyle(e).backgroundColor",
        )
        == fill
    )
    assert post.evaluate(
        f"[...document.querySelectorAll('{VIEW} .mlb-cell-btn')]"
        ".every(e => getComputedStyle(e).borderInlineStartWidth === '0px')"
    )


def test_desktop_has_separate_columns_and_no_phone_twin(post: Page) -> None:
    assert post.locator(f"{VIEW} .mlb-grid").is_visible()
    assert post.locator(f"{VIEW} .mlb-phone-grid").is_hidden()
    assert post.locator(f"{VIEW} .mlb-phone-season-notes").is_hidden()
    heads = post.eval_on_selector_all(
        f"{VIEW} .mlb-grid thead th", "els => els.map(e => e.innerText)"
    )
    assert heads == [
        "Season",
        "Wild Card",
        "Division Series",
        "League Championship Series",
        "World Series",
    ]


def test_season_with_no_cells_selects_and_shows_the_empty_state(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """F15: a season in the season table with no round cells is still a working Season button."""
    page = mlb_guarded_page

    def handler(route: Route) -> None:
        resp = route.fetch()
        data = json.loads(resp.text())
        s = data["postseason_seasons"]
        s["season"].append(2027)
        s["coverage_num"].append(0)
        s["coverage_den"].append(0)
        route.fulfill(response=resp, body=json.dumps(data))

    page.route("**/mlb-data.json", handler)
    open_mlb_app(page, "?sport=mlb&view=postseason")
    btn = page.locator(f"{VIEW} .mlb-grid button[data-season-cell='season-2027']")
    btn.click()
    assert page.evaluate(f"{HOOKS}.getState().cell") == "season-2027"
    assert btn.get_attribute("aria-pressed") == "true"
    assert page.evaluate(f"{HOOKS}.getTableIndexes()") == []
    assert page.inner_text(f"{VIEW} .mlb-grid-status") == "Selected 2027 postseason, 0 games."
    matched = page.inner_text("#mlb-matched-games")
    assert "No matching games" in matched
    assert "No games are listed for 2027 postseason." in matched
    assert "cell=season-2027" in page.url


# U2: stacked role pills (a wrapped booth line, the panel crew, a wrapped Matched games crew)
# never touch. Pills are grouped into lines by their top; the gap is the next line's top
# minus the line above's bottom.
_STACKED_PILL_GAPS_JS = """
([scope, width]) => {
  const out = [];
  for (const box of document.querySelectorAll(scope)) {
    if (width) box.style.width = width;
    const rects = [...box.querySelectorAll('.role-pill')]
      .map((p) => p.getBoundingClientRect())
      .filter((r) => r.height > 0)
      .sort((a, b) => a.top - b.top);
    const lines = [];
    for (const r of rects) {
      const line = lines[lines.length - 1];
      if (line && r.top < line.top + 6) line.bottom = Math.max(line.bottom, r.bottom);
      else lines.push({ top: r.top, bottom: r.bottom });
    }
    for (let k = 1; k < lines.length; k += 1) out.push(lines[k].top - lines[k - 1].bottom);
  }
  return out;
}
"""


def _stacked_pill_gaps(page: Page, scope: str, width: str | None = None) -> list[float]:
    return page.evaluate(_STACKED_PILL_GAPS_JS, [scope, width])


def test_stacked_role_pills_keep_a_vertical_gap(post: Page) -> None:
    # A narrow booth line wraps its PBP and Analyst onto separate lines.
    gaps = _stacked_pill_gaps(post, f"{VIEW} .mlb-grid .mlb-cell-booths", "110px")
    assert gaps, "no wrapped booth line in the grid"
    assert min(gaps) > 0, gaps
    # The panel crew stacks one person per line.
    post.evaluate(f"{HOOKS}.openGame(1)")
    post.wait_for_selector("#mlb-detail-panel[open]")
    gaps = _stacked_pill_gaps(post, "#mlb-detail-panel .crew-box")
    assert gaps, "no stacked crew in the panel"
    assert min(gaps) > 0, gaps
    post.evaluate(f"{HOOKS}.closePanel()")
    # A wrapped Matched games crew cell.
    post.evaluate(f"{HOOKS}.setState({{ cell: 'season-2026' }})")
    gaps = _stacked_pill_gaps(post, "#mlb-matched-games .crew-list", "110px")
    assert gaps, "no wrapped crew in Matched games"
    assert min(gaps) > 0, gaps


_GROUP_JS = """
async (pairs) => {
  const P = await import('./sports/mlb/views/postseason.js');
  return P.groupBooths(pairs).map((g) => ({
    pbps: g.pbps.map((e) => [e.person, e.roles]),
    analysts: g.analysts.map((e) => [e.person, e.roles]),
  }));
}
"""


def test_group_booths_lists_each_person_once(post: Page) -> None:
    """U3: crews that share any person form one booth line; each person appears once."""
    group = lambda pairs: post.evaluate(_GROUP_JS, pairs)  # noqa: E731
    # Three play-by-play voices beside one analyst (a fill-in in the same series) make one
    # line; a crew with nobody in common stays its own line.
    assert group([[10, 20], [11, 20], [12, 20], [13, 21]]) == [
        {"pbps": [[10, ["pbp"]], [11, ["pbp"]], [12, ["pbp"]]], "analysts": [[20, ["analyst"]]]},
        {"pbps": [[13, ["pbp"]]], "analysts": [[21, ["analyst"]]]},
    ]
    # Shared people chain: A/X, B/X, B/Y join through X then B, in first-seen order.
    assert group([[1, 9], [5, 6], [2, 9], [2, 8]]) == [
        {"pbps": [[1, ["pbp"]], [2, ["pbp"]]], "analysts": [[9, ["analyst"]], [8, ["analyst"]]]},
        {"pbps": [[5, ["pbp"]]], "analysts": [[6, ["analyst"]]]},
    ]
    # A person in both roles is listed once, with both pills; a crew with no analyst groups too.
    assert group([[1, 2], [2, 3], [4, None], [4, None]]) == [
        {"pbps": [[1, ["pbp"]], [2, ["pbp", "analyst"]]], "analysts": [[3, ["analyst"]]]},
        {"pbps": [[4, ["pbp"]]], "analysts": []},
    ]
    assert group([]) == []


def test_cell_groups_crews_that_share_an_analyst(
    mlb_guarded_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """U3: the rendered cell lists the shared analyst once; the games keep their own crews."""

    def handler(route: Route) -> None:
        resp = route.fetch()
        data = json.loads(resp.text())
        p = data["postseason"]
        k = next(i for i, s in enumerate(p["season"]) if s == 2019 and p["round"][i] == "division")
        p["booths"][k] = [[0, 7], [2, 7], [4, 7], [5, 6]]
        route.fulfill(response=resp, body=json.dumps(data))

    page = mlb_guarded_page
    page.route("**/mlb-data.json", handler)
    open_mlb_app(page, "?sport=mlb&view=postseason")
    cell = page.locator(f"{VIEW} .mlb-grid button[data-cell='2019-division-AL']")
    lines = cell.locator(".mlb-cell-booth")
    assert lines.count() == 2
    people = page.evaluate(
        """(sel) => [...document.querySelectorAll(sel + ' .mlb-cell-booth')].map((line) =>
          [...line.querySelectorAll('.name-with-roles')].map((n) => [
            n.querySelector('.booth-name').textContent,
            [...n.querySelectorAll('.role-pill')].map((r) => r.dataset.role),
          ]))""",
        f"{VIEW} .mlb-grid button[data-cell='2019-division-AL']",
    )
    names = [name for line in people for name, _ in line]
    assert len(names) == len(set(names)) == 6
    assert [roles for _, roles in people[0]] == [["pbp"], ["pbp"], ["pbp"], ["analyst"]]
    assert [roles for _, roles in people[1]] == [["pbp"], ["analyst"]]
    assert lines.first.inner_text().count(" / ") == 1
    # Each game's panel still shows that game's own crew from the data, not the grouped line.
    page.evaluate(f"{HOOKS}.setState({{ cell: '2019-division-AL' }})")
    games = page.evaluate(f"{HOOKS}.getTableIndexes()")
    assert games
    want = page.evaluate(
        """async (games) => {
          const raw = await (await fetch('mlb-data.json')).json();
          const name = (m) => raw.lookups.people[m.person].name;
          return games.map((g) => (raw.games.crew[g] || []).map(name));
        }""",
        games,
    )
    for g, names in zip(games, want, strict=True):
        page.evaluate(f"{HOOKS}.openGame({g})")
        page.wait_for_selector("#mlb-detail-panel[open]")
        shown = page.eval_on_selector_all(
            "#mlb-detail-panel .crew-box .crew-name", "els => els.map((e) => e.textContent)"
        )
        assert shown == names, g
        page.evaluate(f"{HOOKS}.closePanel()")
