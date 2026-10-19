"""Phase 10 Crews tab (plan 10-09, D-13..D-15), proven on the synthetic booth overlay.

Merged indices: rated 0..11, then unrated 12..19. Booth games and their fixture values
(excitement, |home spread|, both teams ranked, rated):

    booth 4 (ESPN/ABC 2026, A):   idx 8   5.5   6.5  no   rated
    booth 6 (FOX 2026, B):        idx 9   6.1   0.5  no   rated
    booth 3 (ESPN/ABC 2025, Other): idx 4 8.4   1.0  yes  rated
    booth 5 (FOX 2025, A):        idx 5   9.6  14.0  no   rated
    booth 2 (ESPN/ABC 2021, A):   idx 14  4.2   6.0  no   unrated
    booth 0 (ESPN/ABC 2021, B):   idx 13  5.5   3.5  no   unrated
    booth 1 (ESPN/ABC 2021, conference lead): idx 15  7.1  2.5  no  unrated

Every booth has one game, so each median is that game's value. Groups run seasons
descending then FAMILY_ORDER; rows run tier A, B, conference lead, Other.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_MODEL_JS = """
async ([partial, opts]) => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const C = await import('./modules/crews.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const state = Object.assign(S.defaultState(data), partial);
  const view = S.computeView(data, state);
  const model = C.buildCrewsModel(data, view, opts || undefined);
  return {
    state: model.state,
    lowN: model.lowN,
    groups: model.groups.map((g) => ({
      heading: g.heading,
      rows: g.rows.map((r) => ({
        booth: r.booth, tier: r.tier, chip: r.chip, pbp: r.pbp, analyst: r.analyst,
        games: r.games, exc: r.medianExcitement, spread: r.medianSpread,
        ranked: r.rankedShare, rated: r.ratedShare, lowN: r.lowN,
      })),
    })),
  };
}
"""

_ORDER_UNDER_RATED_FLIP_JS = """
async () => {
  const D = await import('./modules/data.js');
  const S = await import('./modules/select.js');
  const C = await import('./modules/crews.js');
  const raw = await (await fetch('site-data.json')).json();
  const data = D.prepareData(raw);
  const view = S.computeView(data, S.defaultState(data));
  const order = (m) => m.groups.map((g) => [g.heading, g.rows.map((r) => r.booth)]);
  const before = order(C.buildCrewsModel(data, view));
  for (let i = 0; i < data.rated.length; i += 1) data.rated[i] = 1 - data.rated[i];
  const after = order(C.buildCrewsModel(data, view));
  return { before, after };
}
"""

HEADINGS = [
    "ESPN/ABC, 2026",
    "FOX, 2026",
    "ESPN/ABC, 2025",
    "FOX, 2025",
    "ESPN/ABC, 2021",
]


def _open(
    page: Page,
    serve_booths: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
    query: str = "?view=crews",
) -> None:
    serve_booths(page)
    open_app(page, query)


def _model(page: Page, partial: dict[str, Any] | None = None, opts: Any = None) -> dict[str, Any]:
    open_app_done = page.evaluate("() => window.__testHooks.ready")
    assert open_app_done
    return page.evaluate(_MODEL_JS, [partial or {}, opts])  # type: ignore[no-any-return]


def test_model_groups_rows_and_hand_computed_values(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    _open(guarded_page, serve_booths, open_app)
    model = _model(guarded_page)
    assert model["state"] == "rows"
    assert [g["heading"] for g in model["groups"]] == HEADINGS
    rows = {r["booth"]: r for g in model["groups"] for r in g["rows"]}
    assert len(rows) == 7
    expected = {
        4: ("a", 5.5, 6.5, 0, 1),
        6: ("b", 6.1, 0.5, 0, 1),
        3: ("other", 8.4, 1.0, 1, 1),
        5: ("a", 9.6, 14.0, 0, 1),
        2: ("a", 4.2, 6.0, 0, 0),
        0: ("b", 5.5, 3.5, 0, 0),
        1: ("conf", 7.1, 2.5, 0, 0),
    }
    for booth, (tier, exc, spread, ranked, rated) in expected.items():
        row = rows[booth]
        assert row["tier"] == tier
        assert row["games"] == 1
        assert row["exc"] == pytest.approx(exc)
        assert row["spread"] == pytest.approx(spread)
        assert row["ranked"] == ranked
        assert row["rated"] == rated
    # 2021 group: A, then B, then the conference lead
    assert [r["booth"] for r in model["groups"][4]["rows"]] == [2, 0, 1]
    assert rows[1]["chip"] == "Lead Conference Network"
    assert rows[2]["chip"] == "Lead"
    assert rows[0]["chip"] == "No. 2"
    assert rows[3]["chip"] == ""
    assert rows[4]["pbp"] == "Dale Harlow"
    assert rows[4]["analyst"] == "Dale Harlow Jr."


def test_low_n_default_and_off(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    _open(guarded_page, serve_booths, open_app)
    default = _model(guarded_page)
    assert default["lowN"] == 8
    assert all(r["lowN"] for g in default["groups"] for r in g["rows"])
    off = _model(guarded_page, opts={"lowN": 0})
    assert not any(r["lowN"] for g in off["groups"] for r in g["rows"])

    assert guarded_page.locator("#crews-panel .low-n-tag").count() == 7
    assert guarded_page.locator("#crews-panel tr[data-low-n='true']").count() == 7
    legend = guarded_page.locator("#crews-panel .crews-legend")
    assert legend.text_content() == "low n: fewer than 8 games, so medians move easily."
    # CREWS_LOW_N = 0 removes the tags and the legend in the DOM too
    guarded_page.evaluate(
        """async () => {
          const D = await import('./modules/data.js');
          const S = await import('./modules/select.js');
          const C = await import('./modules/crews.js');
          const raw = await (await fetch('site-data.json')).json();
          const data = D.prepareData(raw);
          const view = S.computeView(data, S.defaultState(data));
          const host = document.createElement('div');
          host.id = 'crews-off';
          document.body.append(host);
          C.renderCrewsPanel(host, C.buildCrewsModel(data, view, { lowN: 0 }));
        }"""
    )
    assert guarded_page.locator("#crews-off .low-n-tag").count() == 0
    assert guarded_page.locator("#crews-off .crews-legend").count() == 0
    assert guarded_page.locator("#crews-off tr[data-low-n]").count() == 0


def test_columns_and_no_viewers(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    _open(guarded_page, serve_booths, open_app)
    heads = guarded_page.locator("#crews-panel table").first.locator("th[scope=col]")
    assert heads.all_inner_texts() == [
        "Booth",
        "Games",
        "Median excitement",
        "Median spread (points)",
        "Ranked vs. ranked",
        "Rated",
    ]
    assert guarded_page.locator("#crews-panel h3").all_inner_texts() == HEADINGS
    text = guarded_page.locator("#crews-panel").inner_text().lower()
    assert not re.search(r"\bviewers\b", text)
    assert guarded_page.locator("#crews-panel button, #crews-panel a[download]").count() == 0
    first = guarded_page.locator("#crews-panel tbody tr").first.locator("td").all_inner_texts()
    assert first == ["1", "5.5", "6.5", "0%", "100%"]


def test_booth_filter_and_networks_filter(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    _open(guarded_page, serve_booths, open_app)
    only_a = _model(guarded_page, {"booth": ["a"]})
    assert [g["heading"] for g in only_a["groups"]] == [
        "ESPN/ABC, 2026",
        "FOX, 2025",
        "ESPN/ABC, 2021",
    ]
    assert [r["booth"] for g in only_a["groups"] for r in g["rows"]] == [4, 5, 2]
    no_fox = _model(guarded_page, {"networks": ["net-a", "net-c", "net-d", "net-e"]})
    assert not any("FOX" in g["heading"] for g in no_fox["groups"])
    assert len(no_fox["groups"]) == 3


def test_person_selection_is_ignored(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    _open(guarded_page, serve_booths, open_app)
    base = _model(guarded_page)
    picked = _model(guarded_page, {"people": ["kris-venn"]})
    assert picked == base
    hint = guarded_page.locator("#crews-panel .crews-hint").text_content()
    assert hint is not None
    assert "Selected announcers do not change this table." in hint


def test_empty_states(
    guarded_page: Page,
    serve_booths: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> None:
    # net-d carries no booth game, so this filter leaves no crew rows
    _open(guarded_page, serve_booths, open_app, "?view=crews&networks=net-d")
    assert _model(guarded_page, {"networks": ["net-d"]})["state"] == "no-match"
    title = guarded_page.locator("#crews-panel .season-empty-title")
    assert title.text_content() == "No booths match these filters"
    assert guarded_page.locator("#crews-panel table").count() == 0


def test_no_booth_order_state(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    open_app(guarded_page, "?view=crews")
    assert guarded_page.locator("#crews-panel .season-empty-title").text_content() == (
        "No booth order yet"
    )
    assert guarded_page.locator("#crews-panel table").count() == 0


def test_url_tab_click_keyboard_and_controls(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    _open(guarded_page, serve_booths, open_app, "")
    guarded_page.locator("#tab-crews").click()
    assert "view=crews" in guarded_page.url
    assert guarded_page.locator("#tab-crews").get_attribute("aria-selected") == "true"
    assert guarded_page.locator("#crews-panel").is_visible()
    assert not guarded_page.locator("#chart").is_visible()
    for sel in ("#scatter-controls", "#bar-controls"):
        assert (
            guarded_page.evaluate(
                "(s) => getComputedStyle(document.querySelector(s)).visibility", sel
            )
            == "hidden"
        )
    guarded_page.locator("#tab-scatter").click()
    assert "view=crews" not in guarded_page.url
    assert not guarded_page.locator("#crews-panel").is_visible()
    guarded_page.locator("#tab-scatter").focus()
    guarded_page.keyboard.press("End")
    assert guarded_page.evaluate("() => document.activeElement.id") == "tab-crews"
    guarded_page.keyboard.press("Enter")
    assert guarded_page.locator("#tab-crews").get_attribute("aria-selected") == "true"
    # ?view=crews loads selected
    _open(guarded_page, serve_booths, open_app)
    assert guarded_page.locator("#tab-crews").get_attribute("aria-selected") == "true"
    assert guarded_page.locator("#crews-panel").is_visible()


def test_unknown_view_falls_back_to_scatter(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    _open(guarded_page, serve_booths, open_app, "?view=crewz")
    assert guarded_page.locator("#tab-scatter").get_attribute("aria-selected") == "true"


def test_order_never_depends_on_rated(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    _open(guarded_page, serve_booths, open_app)
    out = guarded_page.evaluate(_ORDER_UNDER_RATED_FLIP_JS)
    assert out["before"] == out["after"]


def test_credits_and_no_innerhtml(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    _open(guarded_page, serve_booths, open_app)
    panel = guarded_page.locator("#crews-panel")
    link = panel.get_by_role("link", name="Data provided by CollegeFootballData.com")
    assert link.get_attribute("href") == "https://collegefootballdata.com"
    text = panel.inner_text()
    assert "Viewership figures: Ratings Reference" in text
    assert "data/reference/cfb_booth_ranks.csv" in text
    assert "Rated shows how many games have a viewership figure." in text
    src = guarded_page.evaluate("async () => (await fetch('modules/crews.js')).text()")
    assert "innerHTML" not in src


def test_phone_scrolls_inside_wrapper(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    guarded_page.set_viewport_size({"width": 390, "height": 844})
    _open(guarded_page, serve_booths, open_app)
    out = guarded_page.evaluate(
        """() => {
          const wrap = document.querySelector('#crews-panel .crews-table-wrap');
          return {
            wrapScroll: wrap.scrollWidth, wrapClient: wrap.clientWidth,
            page: document.documentElement.scrollWidth,
            numWrap: [...document.querySelectorAll('#crews-panel td.num')]
              .filter((td) => {
                const r = document.createRange();
                r.selectNodeContents(td);
                return r.getClientRects().length > 1;
              }).length,
          };
        }"""
    )
    assert out["wrapScroll"] > out["wrapClient"]
    assert out["page"] <= 390
    assert out["numWrap"] == 0


def test_new_model_caption_shows_only_when_a_group_is_2025_or_later(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    _open(guarded_page, serve_booths, open_app)
    caption = guarded_page.locator("#excitement-caption")
    assert caption.is_visible()
    assert "2025+ excitement uses CFBD's new win-probability model" in (
        caption.text_content() or ""
    )
    # Only the 2021 group left: no 2025+ excitement on the table, so no note.
    guarded_page.evaluate("() => window.__testHooks.setState({ seasons: [2021, 2021] })")
    assert [g.text_content() for g in guarded_page.locator("#crews-panel h3").all()] == [
        "ESPN/ABC, 2021"
    ]
    assert not caption.is_visible()
    guarded_page.evaluate("() => window.__testHooks.setState({ seasons: [2021, 2026] })")
    assert caption.is_visible()


def test_legend_chips_are_hidden_on_crews_and_networks_filter_still_applies(
    guarded_page: Page, serve_booths: Callable[[Page], None], open_app: Callable[[Page, str], None]
) -> None:
    _open(guarded_page, serve_booths, open_app, "")
    assert guarded_page.locator("#legend-row").is_visible()
    guarded_page.locator("#tab-crews").click()
    assert not guarded_page.locator("#legend-row").is_visible()
    assert guarded_page.locator("#legend-chips").is_hidden()
    no_fox = _model(guarded_page, {"networks": ["net-a", "net-c", "net-d", "net-e"]})
    assert len(no_fox["groups"]) == 3
    guarded_page.locator("#tab-scatter").click()
    assert guarded_page.locator("#legend-row").is_visible()
