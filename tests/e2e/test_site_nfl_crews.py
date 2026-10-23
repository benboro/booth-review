"""Phase 8 plan 08: the NFL Crews tab (network picker, booth table, booth chart).

Synthetic nfl-data fixture only; no vault rows. Expected values are recomputed
from the fixture's `booths` block so the view is checked against the source.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

VIEW = "#nfl-view-crews"
TOOLS = "#nfl-chart-tools [data-tools-for='crews']"  # view tools sit in the module header (13-13)
GD = f"{VIEW} .nfl-chart > div"
HEADS = ["Booth", "Games", "Avg viewers*", "Avg margin", "Excitement"]


def _open(page: Page, open_nfl_app: Callable[..., None], query: str = "") -> None:
    open_nfl_app(page, "?sport=nfl&view=crews" + query)
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews') !== null")


def _vm(page: Page) -> dict[str, Any]:
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').drawn === true")
    return page.evaluate("window.__nflTestHooks.getViewModel('crews')")  # type: ignore[no-any-return]


def _vm_any(page: Page) -> dict[str, Any]:
    return page.evaluate("window.__nflTestHooks.getViewModel('crews')")  # type: ignore[no-any-return]


def _set(page: Page, patch: dict[str, Any]) -> None:
    page.evaluate("p => window.__nflTestHooks.setState(p)", patch)


def _state(page: Page) -> dict[str, Any]:
    return page.evaluate("window.__nflTestHooks.getState()")  # type: ignore[no-any-return]


def _group_index(raw: dict[str, Any], gid: str) -> int:
    return next(i for i, g in enumerate(raw["lookups"]["network_groups"]) if g["id"] == gid)


def _rows(raw: dict[str, Any], gid: str, season: int) -> list[dict[str, Any]]:
    b = raw["booths"]
    gi = _group_index(raw, gid)
    out = [
        {k: b[k][i] for k in b}
        for i in range(len(b["season"]))
        if b["season"][i] == season and b["network_group"][i] == gi
    ]
    return sorted(out, key=lambda r: r["rank"])


def _seasons(raw: dict[str, Any], gid: str) -> list[int]:
    b = raw["booths"]
    gi = _group_index(raw, gid)
    return sorted(
        {b["season"][i] for i in range(len(b["season"])) if b["network_group"][i] == gi},
        reverse=True,
    )


def _headers(page: Page) -> list[str]:
    return [t.strip() for t in page.locator(f"{VIEW} .nfl-booth-table thead th").all_inner_texts()]


def _emit(page: Page, event: str, k: int) -> None:
    page.evaluate(
        """([ev, k, sel]) => {
          const gd = document.querySelector(sel);
          gd.emit(ev, { points: [{ customdata: k }], event: { clientX: 300, clientY: 200 } });
        }""",
        [event, k, GD],
    )


def _tooltip(page: Page) -> list[str]:
    page.wait_for_function("!document.getElementById('chart-tooltip').hidden")
    return page.evaluate(  # type: ignore[no-any-return]
        "Array.from(document.getElementById('chart-tooltip').children).map(c => c.textContent)"
    )


def _pick_network(page: Page, name: str) -> None:
    """Pick through the UI: segmented buttons, or the popover listbox."""
    seg = page.locator(f"{VIEW} .nfl-crews-network .segmented button", has_text=name)
    if seg.count():
        seg.first.click()
        return
    page.locator(f"{VIEW} .filter-trigger").click()
    page.locator(f"{VIEW} [role=listbox] [role=option]", has_text=name).first.click()


def _lead_label(r: dict[str, Any]) -> str:
    return "Lead" if r["rank"] == 1 and r["rank_source"] != "games" else f"#{r['rank']}"


# ------------------------------------------------------------------ table


def test_default_opens_fox_booth_table(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    vm = _vm(nfl_guarded_page)
    default = nfl_fixture_raw["freshness"]["crews_default_season"]
    assert vm["network"] == "fox"
    assert vm["season"] == default
    assert _headers(nfl_guarded_page) == [
        "Booth",
        "Games",
        "AGOTW",
        "Avg viewers*",
        "Avg margin",
        "Excitement",
    ]
    rows = _rows(nfl_fixture_raw, "fox", default)
    assert len(vm["rows"]) == len(rows)
    first = nfl_guarded_page.locator(f"{VIEW} .nfl-booth-table tbody tr").first
    assert first.locator(".booth-rank").inner_text() == "Lead"
    people = nfl_fixture_raw["lookups"]["people"]
    text = first.locator(".booth-row-btn").inner_text()
    assert people[rows[0]["pbp_person"]]["name"] in text
    assert people[rows[0]["analyst_person"]]["name"] in text
    assert first.locator(".role-pill").count() == 2
    assert [r["rankLabel"] for r in vm["rows"]][:2] == ["Lead", "#2"]


def test_network_picker_lists_groups_and_writes_url(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    ids = [n["id"] for n in vm["networks"]]
    groups = [g["id"] for g in nfl_fixture_raw["lookups"]["network_groups"]]
    assert ids == [g for g in groups if g in ids]  # lookup order
    assert "nbc" in ids
    assert "espn_abc" in ids
    _pick_network(page, "NBC")
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').network === 'nbc'")
    assert "net=nbc" in page.url
    assert _headers(page)[2] == "SNF"
    vm = _vm(page)
    published = vm["coverage"]["fromLineup"]
    text = page.locator(f"{VIEW} .nfl-coverage").inner_text()
    assert text.startswith(
        f"Crew listed for {vm['coverage']['withCrew']} of {vm['coverage']['total']} games."
    )
    if published:
        assert f"{published} from published lineup." in text
    else:
        assert "from published lineup" not in text


def test_single_booth_network_and_flagship_headers(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    _set(page, {"network": "nbc", "cseason": 2025})
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').network === 'nbc'")
    vm = _vm(page)
    assert len(vm["rows"]) == len(_rows(nfl_fixture_raw, "nbc", 2025)) == 1
    _set(page, {"network": "netflix", "cseason": 2025})
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').network === 'netflix'")
    _vm(page)
    assert _headers(page) == HEADS
    _set(page, {"network": "espn_abc", "cseason": 2025})
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').network === 'espn_abc'")
    _vm(page)
    assert _headers(page)[2] == "MNF"
    _set(page, {"network": "prime", "cseason": 2025})
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').network === 'prime'")
    _vm(page)
    assert _headers(page)[2] == "TNF"
    _set(page, {"network": "cbs", "cseason": 2025})
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').network === 'cbs'")
    _vm(page)
    assert _headers(page)[2] == "Late national"


def test_crewless_network_says_no_crews_listed(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    _set(page, {"network": "nfln", "cseason": 2025})
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').network === 'nfln'")
    note = page.locator(f"{VIEW} .season-empty-note")
    note.wait_for(state="visible")
    assert note.locator(".season-empty-title").inner_text() == "No crews listed."
    assert "506 does not list a crew" in note.locator(".season-empty-hint").inner_text()
    assert page.locator(f"{VIEW} .nfl-booth-table-wrap").is_hidden()


def test_newest_fox_season_has_zero_game_published_row(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    newest = _seasons(nfl_fixture_raw, "fox")[0]
    _open(page, open_nfl_app, f"&cseason={newest}")
    vm = _vm(page)
    assert vm["season"] == newest
    rows = _rows(nfl_fixture_raw, "fox", newest)
    zero = [i for i, r in enumerate(rows) if r["games"] == 0]
    assert zero
    cells = (
        page.locator(f"{VIEW} .nfl-booth-table tbody tr")
        .nth(zero[0])
        .locator("td")
        .all_inner_texts()
    )
    assert cells[0] == "0"
    assert cells[-3:] == ["—", "—", "—"]
    assert (
        page.locator(f"{VIEW} .nfl-published-note").inner_text()
        == "Booth order from a published lineup."
    )


def test_games_ranked_season_never_says_lead(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    """D-23: CBS 2024 has no known lead; its booths are #1, #2 and none is styled as the lead."""
    page = nfl_guarded_page
    rows = _rows(nfl_fixture_raw, "cbs", 2024)
    assert rows
    assert all(r["rank_source"] == "games" for r in rows)
    _open(page, open_nfl_app, "&net=cbs&cseason=2024")
    vm = _vm(page)
    assert vm["network"] == "cbs"
    assert vm["season"] == 2024
    labels = page.locator(f"{VIEW} .nfl-booth-table .booth-rank").all_inner_texts()
    assert labels == [f"#{i + 1}" for i in range(len(rows))]
    assert "Lead" not in page.locator(f"{VIEW} .nfl-booth-table").inner_text()
    assert [r["rankSource"] for r in vm["rows"]] == ["games"] * len(rows)
    # Chart ticks follow the table: no "Lead" tick either.
    ticks = page.evaluate(f"document.querySelector('{GD}').layout.yaxis.ticktext")
    assert ticks == labels
    # A neighbouring override season of the same network keeps Lead.
    _set(page, {"cseason": 2025})
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').season === 2025")
    vm = _vm(page)
    assert vm["rows"][0]["rankLabel"] == "Lead"
    assert vm["rows"][0]["rankSource"] == "override"


def test_stepper_moves_seasons_and_old_param_works(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    seasons = _seasons(nfl_fixture_raw, "fox")
    _open(page, open_nfl_app, f"&cseason={seasons[0]}")
    _vm(page)
    nxt = page.get_by_role("button", name="Next season")
    prv = page.get_by_role("button", name="Previous season")
    assert nxt.is_disabled()
    prv.click()
    page.wait_for_function(f"window.__nflTestHooks.getViewModel('crews').season === {seasons[1]}")
    # The default season is left out of the URL; any other is written.
    assert ("cseason=" in page.url) == (
        seasons[1] != nfl_fixture_raw["freshness"]["crews_default_season"]
    )
    assert page.locator(f"{VIEW} .season-value").inner_text() == str(seasons[1])
    for _ in range(len(seasons) - 2):
        prv.click()
    page.wait_for_function(f"window.__nflTestHooks.getViewModel('crews').season === {seasons[-1]}")
    assert prv.is_disabled()
    assert prv.get_attribute("aria-disabled") == "true"
    assert f"cseason={seasons[-1]}" in page.url
    _open(page, open_nfl_app, f"&fseason={seasons[-1]}")
    assert _vm(page)["season"] == seasons[-1]


def test_row_click_lists_games_and_second_click_clears(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    rows = _rows(nfl_fixture_raw, "fox", vm["season"])
    btn = page.locator(f"{VIEW} .booth-row-btn").first
    btn.click()
    page.wait_for_function("window.__nflTestHooks.getState().selection !== null")
    got = page.evaluate("window.__nflTestHooks.getTableIndexes()")
    assert sorted(got) == sorted(rows[0]["game_list"])
    assert btn.get_attribute("aria-pressed") == "true"
    btn.click()
    page.wait_for_function("window.__nflTestHooks.getState().selection === null")
    assert page.evaluate("window.__nflTestHooks.getTableIndexes()") != got or not got


def test_chart_mark_click_matches_row_click(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    rows = _rows(nfl_fixture_raw, "fox", vm["season"])
    _emit(page, "plotly_click", 0)
    page.wait_for_function("window.__nflTestHooks.getState().selection !== null")
    assert sorted(page.evaluate("window.__nflTestHooks.getTableIndexes()")) == sorted(
        rows[0]["game_list"]
    )


def test_low_n_picked_and_no_legend(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    low = [r for r in vm["rows"] if r["lowN"]]
    assert low
    assert page.locator(f"{VIEW} .low-n-tag").first.inner_text() == "low n"
    assert page.locator(f"{VIEW} tr[data-low-n=true]").count() == len(low)
    assert page.locator(f"{VIEW} .legend-chips").count() == 0
    key = vm["rows"][0]["key"]
    _set(page, {"booths": [key]})
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').rows[0].picked === true")
    assert page.locator(f"{VIEW} tr[data-picked=true]").count() == 1


# ------------------------------------------------------------------ chart


def test_measure_switch_and_axis_titles(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    assert vm["chart"]["metric"] == "margin"
    assert vm["chart"]["adjusted"] is False
    title = lambda: page.evaluate(f"document.querySelector('{GD}').layout.xaxis.title.text")  # noqa: E731
    assert title() == "Avg final margin (points)"
    page.get_by_role("button", name="Excitement", exact=True).click()
    page.wait_for_function(
        "window.__nflTestHooks.getViewModel('crews').chart.metric === 'excitement'"
    )
    assert title() == "Excitement"
    page.get_by_role("button", name="Avg viewers").click()
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').chart.metric === 'viewers'")
    assert title() == "Avg viewers"
    assert "is-concealed" in page.locator(f"{TOOLS} [aria-label='Raw or adjusted']").get_attribute(
        "class"
    )


def test_adjusted_whiskers_caption_and_spread_wording(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    # Raw: the word never appears anywhere in the view, and no GEI-style in controls or headers.
    assert "spread" not in page.locator(VIEW).inner_text().lower()
    page.get_by_role("button", name="Adjusted").click()
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').chart.adjusted === true")
    vm = _vm(page)
    assert any(p["err"] > 0 for p in vm["chart"]["points"])
    has_whiskers = page.evaluate(
        f"document.querySelector('{GD}').data.some(t => t.error_x && t.error_x.visible)"
    )
    assert has_whiskers
    caption = page.locator(f"{VIEW} .nfl-captions").inner_text()
    assert "1.4 pts closer" in caption
    assert "plus or minus 1.96 standard errors" in caption
    assert page.evaluate(f"document.querySelector('{GD}').layout.xaxis.title.text") == (
        "Final margin vs. what the spread predicted (points)"
    )
    page.get_by_role("button", name="Excitement", exact=True).click()
    page.wait_for_function(
        "window.__nflTestHooks.getViewModel('crews').chart.metric === 'excitement'"
    )
    assert page.evaluate(f"document.querySelector('{GD}').layout.xaxis.title.text") == (
        "Excitement vs. what the spread predicted"
    )
    # Outside the Adjusted caption and chart text, the view never uses the word.
    outside = page.locator(
        f"{VIEW} .nfl-booth-table, {VIEW} .nfl-coverage, {VIEW} .chart-controls"
    ).all_inner_texts()
    assert all("spread" not in t.lower() for t in outside)
    # Hover: plain language, no number labelled as a spread.
    k = next(i for i, p in enumerate(vm["chart"]["points"]) if p["x"] is not None)
    page.get_by_role("button", name="Avg margin").click()
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').chart.metric === 'margin'")
    vm = _vm(page)
    k = next(i for i, p in enumerate(vm["chart"]["points"]) if p["x"] is not None)
    _emit(page, "plotly_hover", k)
    lines = _tooltip(page)
    joined = " ".join(lines)
    assert "than the spread predicted" in joined or "as the spread predicted" in joined
    assert any(line.startswith("±1.96 standard errors:") for line in lines)
    assert "spread:" not in joined.lower()
    assert "line:" not in joined.lower()


def test_avg_viewers_scope_caption_footnote_and_rated_counts(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    # The table footnote and each row's rated-game count are always visible.
    foot = page.locator(f"{VIEW} .nfl-viewers-footnote").inner_text()
    assert "window-level" in foot
    assert "unrated" in foot
    assert "\u2014" not in foot
    rows = _rows(nfl_fixture_raw, "fox", vm["season"])
    cells = page.locator(f"{VIEW} .nfl-booth-table tbody tr .rated-n").all_inner_texts()
    want = [
        f"{r['raw_n_viewers']} rated {'game' if r['raw_n_viewers'] == 1 else 'games'}" for r in rows
    ]
    assert cells == want
    assert [r["ratedGames"] for r in vm["rows"]] == [r["raw_n_viewers"] for r in rows]
    # The caption and hover appear only for the Avg viewers measure.
    assert "window-level" not in page.locator(f"{VIEW} .nfl-captions").inner_text()
    page.get_by_role("button", name="Avg viewers").click()
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews').chart.metric === 'viewers'")
    caption = page.locator(f"{VIEW} .nfl-captions").inner_text()
    assert "window-level" in caption
    assert "unrated" in caption
    vm = _vm(page)
    k = next(i for i, p in enumerate(vm["chart"]["points"]) if p["x"] is not None)
    _emit(page, "plotly_hover", k)
    assert any(" rated game" in line for line in _tooltip(page))


def test_raw_hover_and_excitement_caption_link(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    k = next(i for i, p in enumerate(vm["chart"]["points"]) if p["x"] is not None)
    _emit(page, "plotly_hover", k)
    lines = _tooltip(page)
    assert any(line.startswith("Avg margin:") and line.endswith("pts") for line in lines)
    assert "spread" not in " ".join(lines).lower()
    page.get_by_role("button", name="Excitement", exact=True).click()
    page.wait_for_function(
        "window.__nflTestHooks.getViewModel('crews').chart.metric === 'excitement'"
    )
    link = page.locator(f"{VIEW} .nfl-captions a")
    assert link.get_attribute("href") == "methodology.html#nfl-gei-style-excitement"
    assert "GEI-style" in page.locator(f"{VIEW} .nfl-captions").inner_text()
    chrome = page.locator(
        f"{VIEW} .chart-controls, {VIEW} .nfl-booth-table thead"
    ).all_inner_texts()
    assert all("GEI-style" not in t for t in chrome)
    assert "GEI-style" not in page.evaluate(
        f"document.querySelector('{GD}').layout.xaxis.title.text"
    )


def test_no_console_errors(page: Page, nfl_site_url: str) -> None:
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{nfl_site_url}/index.html?sport=nfl&view=crews")
    page.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.ready === true")
    _vm(page)
    page.get_by_role("button", name="Adjusted").click()
    page.get_by_role("button", name="Previous season").click()
    assert errors == []


_PLOT_GAP_JS = """(sel) => {
  const gd = document.querySelector(sel);
  const box = gd.parentElement.getBoundingClientRect();
  const paper = gd.getBoundingClientRect();
  return { gap: box.bottom - paper.bottom };
}"""


def test_chart_container_hugs_the_plot_for_three_booths(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    """No blank band under the booth chart: the container follows the figure height."""
    _open(nfl_guarded_page, open_nfl_app)
    _vm(nfl_guarded_page)
    assert nfl_guarded_page.locator(f"{VIEW} .nfl-booth-table tbody tr").count() == 3
    got = nfl_guarded_page.evaluate(_PLOT_GAP_JS, GD)
    assert got["gap"] <= 4


def test_phone_booth_table_shows_games_and_unclipped_low_n(
    nfl_mobile_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_mobile_page
    _open(page, open_nfl_app)
    _vm(page)
    width = page.evaluate("window.innerWidth")
    games = page.locator(f"{VIEW} .nfl-booth-table thead th", has_text="Games")
    box = games.bounding_box()
    assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= width
    # The low-n tag sits under the names and is fully inside the viewport.
    tag = page.locator(f"{VIEW} .nfl-booth-table .low-n-tag").first
    tbox = tag.bounding_box()
    assert tbox is not None and tbox["x"] + tbox["width"] <= width
    names = page.locator(f"{VIEW} .nfl-booth-table .booth-names").first.bounding_box()
    assert names is not None
    assert page.locator(f"{VIEW} .nfl-booth-table .booth-names .name-with-roles").count() >= 2


_CELL_JS = """(sel) => { const el = document.querySelector(sel); const cs = getComputedStyle(el);
  return { position: cs.position, bg: cs.backgroundColor }; }"""


def test_desktop_booth_column_has_no_pin_or_fill(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    """UI-SPEC phone contract: the sticky identity column and its fill exist at <=480px only."""
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    for sel in (f"{VIEW} tbody th.booth-col", f"{VIEW} thead th.booth-col"):
        got = page.evaluate(_CELL_JS, sel)
        assert got["position"] != "sticky", sel
        assert got["bg"] == "rgba(0, 0, 0, 0)", sel


def test_phone_booth_column_is_pinned_with_a_fill(
    nfl_mobile_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_mobile_page
    _open(page, open_nfl_app)
    _vm(page)
    got = page.evaluate(_CELL_JS, f"{VIEW} tbody th.booth-col")
    assert got["position"] == "sticky"
    assert got["bg"] != "rgba(0, 0, 0, 0)"


def test_low_n_is_a_styled_tag(nfl_guarded_page: Page, open_nfl_app: Callable[..., None]) -> None:
    """low n is a dashed pill like the role tags, not bare trailing text."""
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    got = page.evaluate(
        """() => { const cs = getComputedStyle(document.querySelector('#nfl-view-crews .low-n-tag, .nfl-booth-table .low-n-tag'));
          const rp = getComputedStyle(document.querySelector('.nfl-booth-table .role-pill'));
          return { style: cs.borderTopStyle, width: cs.borderTopWidth, radius: cs.borderTopLeftRadius,
                   height: cs.height, pillHeight: rp.height, pillRadius: rp.borderTopLeftRadius }; }"""
    )
    assert got["style"] == "dashed"
    assert got["width"] == "1px"
    assert got["radius"] == got["pillRadius"]
    assert got["height"] == got["pillHeight"]
