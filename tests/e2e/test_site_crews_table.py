"""Crews table DOM (plan 14-07): render, cells, sort, picks, view more, notes and styles.

Runs on the synthetic crews dataset (tests/e2e/crews_fixture.py); no vault content. Expected
values are hand-computed from the CASE_* constants: for example the trio crew is "Trio Pbp,
Trio A1 and Trio A2" over 5 games, and the nopbp pair is two people with role `unknown` in
their only game, so each name carries the tag `unknown role`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest
from crews_fixture import CASE_MIXED_UNKNOWN, CASE_NO_PBP, CASE_PAST_CUT, CASE_TRIO
from playwright.sync_api import Locator, Page, expect

pytestmark = pytest.mark.e2e

_MODEL_JS = """
async ([mode, perSeason]) => {
  const G = await import('./modules/crew-groups.js');
  const h = window.__testHooks;
  const m = G.buildCrewRows(h.data, h.getView(), { mode, perSeason });
  return { totalRows: m.totalRows, leftOut: m.leftOut, rows: m.rows.map((r) => ({
    rowKey: r.rowKey, crewKey: r.crewKey, names: r.names, games: r.gamesCount,
    personSlug: r.personSlug || null, partnersMore: r.partnersMore || 0,
    partners: (r.partnersShown || []).map((p) => p.name),
    exc: r.exc, viewers: r.viewers })) };
}
"""


def _name(slug: str) -> str:
    return slug.replace("-", " ").title()


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


@pytest.fixture
def app(
    guarded_page: Page,
    serve_crews: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> Page:
    serve_crews(guarded_page)
    open_app(guarded_page, "?view=crews&perseason=0")
    return guarded_page


def _model(page: Page, mode: str = "crew", per_season: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = page.evaluate(_MODEL_JS, [mode, per_season])
    return out


def _state(page: Page) -> dict[str, Any]:
    out: dict[str, Any] = page.evaluate("() => window.__testHooks.getState()")
    return out


def _show_all(page: Page) -> None:
    more = page.locator("#crews-panel .crews-more")
    while more.count():
        more.click()


def _rows(page: Page) -> Locator:
    return page.locator("#crews-panel tbody tr.crews-row")


def _row(page: Page, name: str) -> Locator:
    return _rows(page).filter(has=page.locator(".crews-name", has_text=name))


def _header(page: Page, label: str) -> Locator:
    return page.locator("#crews-panel thead th").filter(has_text=label)


def _tags(row: Locator) -> list[str]:
    return [t.strip() for t in row.locator(".crews-name .crews-tag").all_inner_texts()]


def _bucket(cell: Locator) -> int:
    """0 = full-n figure, 1 = n < 8 flagged, 2 = blank."""
    cls = cell.get_attribute("class") or ""
    if "is-low-n" in cls:
        return 1
    if "is-blank" in cls or not cell.inner_text().strip():
        return 2
    return 0


# -- V14-3: Crew mode lists every crew ------------------------------------------------------


def test_crew_mode_is_default_and_lists_every_crew(app: Page) -> None:
    model = _model(app)
    assert model["totalRows"] > 25
    expect(app.locator("#crews-panel .crews-mode button[aria-pressed=true]")).to_have_text("Crew")
    expect(app.locator("#crews-panel .crews-mode")).to_have_attribute("aria-label", "Crews mode")
    heads = [t.strip() for t in app.locator("#crews-panel thead th").all_inner_texts()]
    assert [h.replace("↕", "").replace("↓", "").replace("↑", "").strip() for h in heads[1:]] == [
        "Crew",
        "Rank by season",
        "Network",
        "Games called",
        "Avg excitement",
        "Avg viewers (rated games)",
    ]
    _show_all(app)
    expect(_rows(app)).to_have_count(model["totalRows"])
    trio = _row(app, _name(CASE_TRIO["pbp"]))
    expect(trio).to_have_count(1)
    names = [CASE_TRIO["pbp"], *CASE_TRIO["analysts"]]
    expect(trio.locator(".crews-name")).to_contain_text(_join([_name(s) for s in names]))
    expect(trio.locator("td.num").first).to_have_text(str(CASE_TRIO["games"]))


def test_unknown_role_tags_follow_the_a2_copy(app: Page) -> None:
    _show_all(app)
    nopbp = _row(app, _name(CASE_NO_PBP["people"][0]))
    expect(nopbp).to_have_count(1)
    assert _tags(nopbp) == ["unknown role", "unknown role"]
    mixed = _row(app, _name(CASE_MIXED_UNKNOWN["x"]))
    expect(mixed).to_have_count(1)
    x = mixed.locator(".crews-person", has_text=_name(CASE_MIXED_UNKNOWN["x"]))
    y = mixed.locator(".crews-person", has_text=_name(CASE_MIXED_UNKNOWN["y"]))
    expect(x.locator(".crews-tag")).to_have_text(CASE_MIXED_UNKNOWN["tag_x"])
    expect(y.locator(".crews-tag")).to_have_text(CASE_MIXED_UNKNOWN["tag_y"])


# -- V14-4: person modes ----------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["pbp", "analyst"])
def test_person_modes_show_partners_and_no_rank(app: Page, mode: str) -> None:
    app.locator(f"#crews-panel .crews-mode button[data-cmode={mode}]").click()
    assert _state(app)["cmode"] == mode
    table = app.locator("#crews-panel table")
    text = table.inner_text()
    assert "Rank by season" not in text
    assert "Lead" not in text
    assert not re.search(r"\bNo\. \d", text)
    first = [t.strip() for t in app.locator("#crews-panel thead th").all_inner_texts()][1]
    assert first.replace("↕", "").strip() == ("PBP" if mode == "pbp" else "Analyst")
    model = _model(app, mode)
    _show_all(app)
    expect(_rows(app)).to_have_count(model["totalRows"])
    by_slug = {r["personSlug"]: r for r in model["rows"]}
    for row in _rows(app).all():
        slug = row.get_attribute("data-crew-key")
        spec = by_slug[slug]
        partners = row.locator(".crews-partners")
        if not spec["partners"]:
            expect(partners).to_have_count(0)
            continue
        extra = f" +{spec['partnersMore']}" if spec["partnersMore"] else ""
        expect(partners).to_have_text(f"with {', '.join(spec['partners'])}{extra}")
        assert len(spec["partners"]) <= 3
    if mode == "pbp":
        trio = _row(app, _name(CASE_TRIO["pbp"]))
        expect(trio.locator(".crews-partners")).to_have_text(
            f"with {_name(CASE_TRIO['analysts'][0])}, {_name(CASE_TRIO['analysts'][1])}"
        )


def test_partner_list_caps_at_three_names_and_adds_plus_n(app: Page) -> None:
    """A hand-built row with 10 partners: the cell prints 3 names and `+7`."""
    text = app.evaluate(
        """async () => {
          const C = await import('./modules/crews.js');
          const G = await import('./modules/crew-groups.js');
          const h = window.__testHooks;
          const m = G.buildCrewRows(h.data, h.getView(), { mode: 'pbp', perSeason: false });
          const row = { ...m.rows[0] };
          const p = (n) => ({ slug: 's' + n, name: 'Partner ' + n, games: 1 });
          row.partnersShown = [p(1), p(2), p(3)];
          row.partnersMore = 7;
          const box = document.createElement('div');
          C.renderCrewsPanel(box, { ...m, rows: [row], totalRows: 1 },
            { data: h.data, state: h.getState(), view: h.getView(), setState() {} });
          return box.querySelector('.crews-partners').textContent;
        }"""
    )
    assert text == "with Partner 1, Partner 2, Partner 3 +7"


# -- V14-5: sorting (mouse) -------------------------------------------------------------------


def _sort_label(page: Page, key: str) -> str:
    return str(
        page.locator(f"#crews-panel th:has(button[data-sort-key={key}])").get_attribute("aria-sort")
    )


def test_default_sort_is_games_descending(app: Page) -> None:
    assert _sort_label(app, "games") == "descending"
    for key in ("crew", "network", "exc", "viewers", "rank"):
        assert _sort_label(app, key) == "none"
    _show_all(app)
    games = [int(t) for t in app.locator("#crews-panel tbody tr td:nth-child(5)").all_inner_texts()]
    assert games == sorted(games, reverse=True)
    assert _state(app)["csort"] is None


def test_header_cycle_natural_reversed_default(app: Page) -> None:
    btn = app.locator("#crews-panel button[data-sort-key=viewers]")
    btn.click()
    assert _sort_label(app, "viewers") == "descending"
    assert _state(app)["csort"] == {"key": "viewers", "dir": "desc"}
    expect(app.locator("#crews-panel button[data-sort-key=viewers]")).to_be_focused()
    app.locator("#crews-panel button[data-sort-key=viewers]").click()
    assert _sort_label(app, "viewers") == "ascending"
    app.locator("#crews-panel button[data-sort-key=viewers]").click()
    assert _sort_label(app, "viewers") == "none"
    assert _sort_label(app, "games") == "descending"
    assert _state(app)["csort"] is None
    app.locator("#crews-panel button[data-sort-key=crew]").click()
    assert _sort_label(app, "crew") == "ascending"
    glyph = app.locator("#crews-panel button[data-sort-key=crew] .sort-glyph")
    expect(glyph).to_have_text("↑")


@pytest.mark.parametrize("key,col", [("viewers", 7), ("exc", 6)])
def test_metric_sort_buckets_full_n_then_flagged_then_blank(app: Page, key: str, col: int) -> None:
    btn = f"#crews-panel button[data-sort-key={key}]"
    for expected in ("descending", "ascending"):
        app.locator(btn).click()
        assert _sort_label(app, key) == expected
        _show_all(app)
        cells = app.locator(f"#crews-panel tbody tr td:nth-child({col})")
        buckets = [_bucket(cells.nth(i)) for i in range(cells.count())]
        assert buckets == sorted(buckets), (key, expected)
        assert 1 in buckets
        assert 2 in buckets
        if key == "viewers":
            assert 0 in buckets


# -- Small crews and blank cells --------------------------------------------------------------


def test_low_n_cells_are_marked_and_the_row_stays(app: Page) -> None:
    _show_all(app)
    low = _row(app, "Low Pbp")
    expect(low).to_have_count(1)
    viewers = low.locator("td.num").nth(2)
    expect(viewers).to_have_class(re.compile(r"is-low-n"))
    tag = viewers.locator(".crews-tag")
    expect(tag).to_have_text("n < 8")
    expect(tag).to_have_attribute("title", "Fewer than 8 games have this figure")
    expect(viewers.locator(".caption")).to_have_text("(3)")
    full = _row(app, "Full Pbp").locator("td.num").nth(2)
    expect(full.locator(".crews-tag")).to_have_count(0)
    expect(full.locator(".caption")).to_have_text("(9)")


def test_blank_cells_read_see_per_season_or_none_rated(app: Page) -> None:
    _show_all(app)
    era = _row(app, "Era Pbp").locator("td.num").nth(2)
    expect(era).to_contain_text("see Per season")
    expect(era).to_have_attribute("title", "Games span more than one Nielsen measurement era")
    brk = _row(app, "Brk Pbp").locator("td.num").nth(1)
    expect(brk).to_contain_text("see Per season")
    expect(brk).to_have_attribute("title", re.compile(r"both sides of the 2025 excitement model"))
    cut = _row(app, _name(CASE_PAST_CUT["pbp"]))
    expect(cut.locator("td.num").nth(2)).to_have_text("none rated")
    expect(cut.locator("td.num").nth(1)).to_have_text("")


# -- V14-6: view more -------------------------------------------------------------------------

_KEY_JS = """
async (slugs) => {
  const G = await import('./modules/crew-groups.js');
  for (const [key, crew] of G.crewIndex(window.__testHooks.data).crews) {
    const same = crew.people.length === slugs.length;
    if (same && slugs.every((s) => crew.people.includes(s))) return key;
  }
  return null;
}
"""


def _key(page: Page, slugs: list[str]) -> str:
    key = page.evaluate(_KEY_JS, slugs)
    assert key, slugs
    return str(key)


def _set(page: Page, patch: dict[str, Any]) -> None:
    page.evaluate("(patch) => window.__testHooks.setState(patch)", patch)


def test_opens_with_25_rows_and_view_more_adds_25(app: Page) -> None:
    total = _model(app)["totalRows"]
    assert total > 50
    expect(_rows(app)).to_have_count(25)
    more = app.locator("#crews-panel .crews-more")
    expect(more).to_have_text(f"View 25 more ({total - 25} left)")
    expect(app.locator("#crews-panel .crews-count")).to_have_text(f"Showing 25 of {total} rows.")
    more.click()
    expect(_rows(app)).to_have_count(50)
    expect(app.locator("#crews-panel .crews-count")).to_have_text(f"Showing 50 of {total} rows.")
    expect(_rows(app).nth(25)).to_be_focused()
    last = total - 50
    if last > 25:
        expect(more).to_have_text(f"View 25 more ({last} left)")
    _show_all(app)
    expect(_rows(app)).to_have_count(total)
    expect(more).to_have_count(0)


def test_last_page_button_names_the_remainder(app: Page) -> None:
    total = _model(app)["totalRows"]
    while total - _rows(app).count() > 25:
        app.locator("#crews-panel .crews-more").click()
    left = total - _rows(app).count()
    expect(app.locator("#crews-panel .crews-more")).to_have_text(f"View {left} more ({left} left)")


@pytest.mark.parametrize("change", ["sort", "mode", "perseason", "filter"])
def test_shown_count_resets_to_25(app: Page, change: str) -> None:
    app.locator("#crews-panel .crews-more").click()
    expect(_rows(app)).to_have_count(50)
    if change == "sort":
        app.locator("#crews-panel button[data-sort-key=crew]").click()
    elif change == "mode":
        app.locator("#crews-panel button[data-cmode=pbp]").click()
    elif change == "perseason":
        app.locator("#crews-panel input.crews-perseason").check()
    else:
        _set(app, {"networks": ["net-a", "net-b", "net-c", "net-f", "net-g"]})
    expect(_rows(app)).to_have_count(25)


def test_a_pick_past_the_cut_off_is_revealed(app: Page) -> None:
    total = _model(app)["totalRows"]
    key = _key(app, [CASE_PAST_CUT["pbp"], CASE_PAST_CUT["analyst"]])
    _set(app, {"crew": key})
    row = _rows(app).last
    expect(row).to_have_attribute("data-crew-key", key)
    expect(row).to_have_attribute("aria-pressed", "true")
    # The pick sorts last, so the table grows to hold it and the button is gone.
    expect(_rows(app)).to_have_count(total)
    expect(app.locator("#crews-panel .crews-more")).to_have_count(0)
    _set(app, {"crew": None})
    expect(_rows(app)).to_have_count(25)


# -- V14-7: filters, picks and the status seat ------------------------------------------------


def test_filters_recount_the_rows(app: Page) -> None:
    _set(app, {"booth": ["a"]})
    # Tier A holds one cited booth with a fill-in: 4 games, 1 row.
    expect(_rows(app)).to_have_count(1)
    expect(_rows(app).locator("td.num").first).to_have_text("4")
    assert _state(app)["booth"] == ["a"]
    _set(app, {"booth": [], "seasons": [2022, 2022]})
    # Only the two Nielsen-era crew games fall in 2022.
    expect(_rows(app)).to_have_count(1)
    expect(_rows(app).locator("td.num").first).to_have_text("2")
    _set(app, {"seasons": None, "networks": ["net-a"]})
    model = _model(app)
    _show_all(app)
    expect(_rows(app)).to_have_count(model["totalRows"])
    assert model["totalRows"] < _model_total_unfiltered(app)


def _model_total_unfiltered(page: Page) -> int:
    n: int = page.evaluate(
        """async () => {
          const G = await import('./modules/crew-groups.js');
          const S = await import('./modules/select.js');
          const h = window.__testHooks;
          const view = S.computeView(h.data, S.defaultState(h.data));
          return G.buildCrewRows(h.data, view, {}).totalRows;
        }"""
    )
    return n


def test_person_pick_highlights_rows_and_drops_none(app: Page) -> None:
    total = _model(app)["totalRows"]
    _set(app, {"people": [CASE_TRIO["pbp"]]})
    assert _model(app)["totalRows"] == total
    _show_all(app)
    expect(_rows(app)).to_have_count(total)
    highlighted = app.locator("#crews-panel tr.is-highlighted")
    expect(highlighted).to_have_count(1)
    expect(highlighted).to_contain_text(_name(CASE_TRIO["pbp"]))
    expect(app.locator("#crews-panel tr.is-picked")).to_have_count(0)
    # Compare with two people highlights both rows; Called together needs both on one row.
    _set(app, {"people": [CASE_TRIO["pbp"], "fill-pbp"], "compare": True})
    expect(app.locator("#crews-panel tr.is-highlighted")).to_have_count(2)
    _set(app, {"compare": False, "together": True})
    expect(app.locator("#crews-panel tr.is-highlighted")).to_have_count(0)
    expect(_rows(app)).to_have_count(total)


def test_crew_row_click_sets_crew_and_clears_people(app: Page) -> None:
    trio_names = [_name(s) for s in (CASE_TRIO["pbp"], *CASE_TRIO["analysts"])]
    _set(app, {"people": ["fill-pbp"]})
    _show_all(app)
    row = _row(app, _name(CASE_TRIO["pbp"]))
    row.click()
    state = _state(app)
    assert state["crew"] == _key(app, [CASE_TRIO["pbp"], *CASE_TRIO["analysts"]])
    assert state["people"] == []
    status = app.locator("#pick-status")
    expect(status).to_have_text(f"Crew pick set to {_join(trio_names)}. Announcers pick cleared.")
    expect(row).to_have_attribute("aria-pressed", "true")
    expect(row).to_have_class(re.compile(r"is-picked"))
    row.click()
    assert _state(app)["crew"] is None
    expect(status).to_have_text("Crew pick cleared.")
    expect(row).to_have_attribute("aria-pressed", "false")


def test_person_row_click_sets_announcers_and_clears_crew(app: Page) -> None:
    key = _key(app, [CASE_TRIO["pbp"], *CASE_TRIO["analysts"]])
    _set(app, {"crew": key})
    app.locator("#crews-panel button[data-cmode=pbp]").click()
    assert _state(app)["crew"] == key
    _show_all(app)
    row = _row(app, _name(CASE_TRIO["pbp"]))
    row.click()
    state = _state(app)
    assert state["people"] == [CASE_TRIO["pbp"]]
    assert state["crew"] is None
    expect(app.locator("#pick-status")).to_have_text(
        f"Announcers pick set to {_name(CASE_TRIO['pbp'])}. Crew pick cleared."
    )
    expect(row).to_have_class(re.compile(r"is-picked"))
    row.click()
    assert _state(app)["people"] == []


def test_crew_pick_never_filters_or_touches_booth(app: Page) -> None:
    _set(app, {"booth": []})
    total = _model(app)["totalRows"]
    _show_all(app)
    _row(app, _name(CASE_TRIO["pbp"])).click()
    assert _state(app)["booth"] == []
    assert _model(app)["totalRows"] == total
    expect(_rows(app)).to_have_count(total)


def test_chevron_click_sets_no_pick(app: Page) -> None:
    _rows(app).first.locator("button.crews-chevron").click()
    state = _state(app)
    assert state["crew"] is None
    assert state["people"] == []
    expect(_rows(app).first).to_have_attribute("aria-pressed", "false")


def test_per_season_marks_every_row_of_the_picked_crew(app: Page) -> None:
    app.locator("#crews-panel input.crews-perseason").check()
    _show_all(app)
    full = _row(app, "Full Pbp")
    expect(full).to_have_count(3)  # seasons 2023, 2024 and 2025
    full.first.click()
    expect(
        _row(app, "Full Pbp").locator("xpath=self::tr[contains(@class,'is-picked')]")
    ).to_have_count(3)
    expect(app.locator("#crews-panel tr.is-picked")).to_have_count(3)


# -- Notes, credits and the empty state ----------------------------------------------------------

_CREDITS = [
    "Data provided by CollegeFootballData.com",
    "Viewership figures: Ratings Reference and the second sources credited in each game's "
    "detail panel.",
    "Booth order from network press releases, cited per season in "
    "data/reference/cfb_booth_ranks.csv.",
]


def _captions(page: Page) -> list[str]:
    return [
        re.sub(r"\s+", " ", c).strip()
        for c in page.locator("#crews-panel p.caption").all_inner_texts()
    ]


def test_notes_and_credits_in_order(app: Page) -> None:
    total = _model(app)["totalRows"]
    assert _captions(app) == [
        f"Showing 25 of {total} rows.",
        "1 telecasts list no crew and are not in this table.",
        "Avg viewers (rated games) mostly reflects which games a crew was assigned.",
        "Crews with a member of unknown role are kept and marked.",
        *_CREDITS,
    ]
    link = app.locator("#crews-panel").get_by_role("link", name=_CREDITS[0])
    expect(link).to_have_attribute("href", "https://collegefootballdata.com")


@pytest.mark.parametrize(
    "mode,left_out",
    [
        ("pbp", "4 telecasts with no resolved play-by-play voice are not in this mode."),
        ("analyst", "3 telecasts with no resolved analyst are not in this mode."),
    ],
)
def test_person_mode_notes(app: Page, mode: str, left_out: str) -> None:
    app.locator(f"#crews-panel button[data-cmode={mode}]").click()
    caps = _captions(app)
    assert left_out in caps
    assert "Crews with a member of unknown role are kept and marked." not in caps
    assert caps[-3:] == _CREDITS
    assert any(c.startswith("Avg viewers (rated games) mostly") for c in caps)


def test_left_out_note_is_hidden_at_zero(app: Page) -> None:
    _set(app, {"booth": ["a"]})
    assert not any("telecasts" in c for c in _captions(app))


def test_empty_filters_show_the_empty_state_with_tools(app: Page) -> None:
    _set(app, {"booth": ["other"]})
    panel = app.locator("#crews-panel")
    expect(panel.locator(".season-empty-title")).to_have_text("No games match these filters")
    expect(panel.locator(".season-empty-hint")).to_have_text(
        "Clear all filters, or widen the Seasons range."
    )
    expect(panel.locator("table")).to_have_count(0)
    expect(panel.locator(".crews-mode")).to_be_visible()
    expect(panel.locator("input.crews-perseason")).to_be_visible()
    assert _captions(app)[-3:] == _CREDITS


def test_excitement_caption_follows_the_seasons_range(app: Page) -> None:
    caption = app.locator("#excitement-caption")
    expect(caption).to_be_visible()
    _set(app, {"seasons": [2022, 2024]})
    expect(caption).to_be_hidden()
    _set(app, {"seasons": [2024, 2025]})
    expect(caption).to_be_visible()


# -- Styles (UI-SPEC Spacing, Typography, Color, Phone) -----------------------------------------

_PROBE_JS = """
(prop) => {
  const probe = document.createElement('span');
  probe.style[prop.css] = prop.value;
  document.body.append(probe);
  const out = getComputedStyle(probe)[prop.css];
  probe.remove();
  return out;
}
"""


def _resolved(page: Page, css: str, value: str) -> str:
    out: str = page.evaluate(_PROBE_JS, {"css": css, "value": value})
    return out


def _style(page: Page, selector: str, prop: str) -> str:
    out: str = page.evaluate(
        "([s, p]) => getComputedStyle(document.querySelector(s))[p]", [selector, prop]
    )
    return out


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 900)])
def test_crews_table_computed_styles(app: Page, width: int, height: int) -> None:
    app.set_viewport_size({"width": width, "height": height})
    phone = width <= 480
    muted = _resolved(app, "color", "var(--muted)")
    soft = _resolved(app, "backgroundColor", "var(--accent-soft)")
    assert _style(app, "#crews-panel table", "tableLayout") == "fixed"
    assert _style(app, "#crews-panel tbody td.num", "textAlign") in ("right", "end")
    assert "tabular-nums" in _style(app, "#crews-panel tbody td.num", "fontVariantNumeric")
    assert _style(app, "#crews-panel th.num", "textAlign") in ("right", "end")
    # Low-n cells are muted.
    assert _style(app, "#crews-panel td.is-low-n", "color") == muted
    # The pick and a person highlight share the accent-soft fill.
    key = _key(app, [CASE_TRIO["pbp"], *CASE_TRIO["analysts"]])
    _set(app, {"crew": key})
    assert _style(app, "#crews-panel tr.is-picked", "backgroundColor") == soft
    _set(app, {"crew": None, "people": [CASE_TRIO["pbp"]]})
    assert _style(app, "#crews-panel tr.is-highlighted", "backgroundColor") == soft
    # "View more": 32px on a desktop, 44px on a phone.
    more_h = app.locator("#crews-panel .crews-more").bounding_box()
    assert more_h is not None
    assert round(more_h["height"]) == (44 if phone else 32)
    # Sticky identity columns on a phone only.
    chevron_pos = _style(app, "#crews-panel tbody td.crews-chevron-cell", "position")
    name_pos = _style(app, "#crews-panel tbody td.crews-name", "position")
    assert (chevron_pos, name_pos) == (("sticky", "sticky") if phone else ("static", "static"))
    # Tag type: 12px with a 3px radius.
    tag = "#crews-panel td.is-low-n .crews-tag"
    assert _style(app, tag, "fontSize") == "12px"
    assert _style(app, tag, "borderTopLeftRadius") == "3px"


@pytest.mark.parametrize("mode", ["pbp", "analyst"])
def test_partner_list_is_muted_by_colour_only(app: Page, mode: str) -> None:
    app.locator(f"#crews-panel button[data-cmode={mode}]").click()
    muted = _resolved(app, "color", "var(--muted)")
    sel = "#crews-panel tbody tr:has(.crews-partners)"
    partner = f"{sel} .crews-partners"
    name = f"{sel} .crews-person-name"
    assert _style(app, partner, "color") == muted
    assert _style(app, partner, "color") != _style(app, name, "color")
    assert _style(app, partner, "fontSize") == _style(app, name, "fontSize")
    assert _style(app, partner, "fontWeight") == _style(app, name, "fontWeight")


def test_phone_table_scrolls_inside_its_wrapper(app: Page) -> None:
    app.set_viewport_size({"width": 390, "height": 844})
    out = app.evaluate(
        """() => {
          const wrap = document.querySelector('#crews-panel .crews-table-wrap');
          return {
            wrapScroll: wrap.scrollWidth, wrapClient: wrap.clientWidth,
            page: document.documentElement.scrollWidth,
            // One line of content is about 20px tall; a wrapped figure is 36px or more.
            numWrap: [...document.querySelectorAll(
              '#crews-panel td.num:not(.is-low-n):not(.is-blank)')]
              .filter((td) => {
                const r = document.createRange();
                r.selectNodeContents(td);
                return r.getBoundingClientRect().height > 28;
              }).length,
          };
        }"""
    )
    assert out["wrapScroll"] > out["wrapClient"]
    assert out["page"] <= 390
    assert out["numWrap"] == 0


def test_pinned_columns_have_an_opaque_fill_on_phones_only(app: Page) -> None:
    js = """() => {
      const td = document.querySelector('#crews-panel tbody td.crews-name');
      const cs = getComputedStyle(td);
      return { position: cs.position, bg: cs.backgroundColor }; }"""
    desktop = app.evaluate(js)
    assert desktop["position"] != "sticky"
    assert desktop["bg"] == "rgba(0, 0, 0, 0)"
    app.set_viewport_size({"width": 390, "height": 844})
    phone = app.evaluate(js)
    assert phone["position"] == "sticky"
    assert phone["bg"] != "rgba(0, 0, 0, 0)"


# -- 14-10 checkpoint (2026-10-23): Crews opens on Per season -------------------------------


def _season_head(page: Page) -> Locator:
    return page.locator("#crews-panel thead th").filter(has_text=re.compile(r"^\s*Season"))


def test_crews_opens_on_per_season_and_pooled_is_one_click_away(
    guarded_page: Page,
    serve_crews: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> None:
    serve_crews(guarded_page)
    open_app(guarded_page, "?view=crews")
    box = guarded_page.locator("#crews-panel input.crews-perseason")
    expect(box).to_be_checked()
    expect(_season_head(guarded_page)).to_have_count(1)
    assert "perseason" not in guarded_page.url
    box.uncheck()
    expect(_season_head(guarded_page)).to_have_count(0)
    assert "perseason=0" in guarded_page.url
    box.check()
    expect(_season_head(guarded_page)).to_have_count(1)
    assert "perseason" not in guarded_page.url


def test_a_single_season_range_shows_the_toggle_off_and_disabled(
    guarded_page: Page,
    serve_crews: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> None:
    serve_crews(guarded_page)
    open_app(guarded_page, "?view=crews")
    season = guarded_page.evaluate("() => window.__testHooks.data.seasons[0]")
    open_app(guarded_page, f"?view=crews&seasons={season}-{season}")
    box = guarded_page.locator("#crews-panel input.crews-perseason")
    expect(box).to_be_disabled()
    expect(box).not_to_be_checked()
    expect(_season_head(guarded_page)).to_have_count(0)
    assert "perseason" not in guarded_page.url


# -- 14-10: viewer figures in table columns carry a fixed one decimal -----------------------


def test_table_formatter_always_has_one_decimal_and_the_shared_one_is_untouched(app: Page) -> None:
    values = [523_412, 12_000, 2_000_000, 50_640_000, 999_960, 1_049_999, 950]
    out = app.evaluate(
        """async (vs) => {
          const f = await import('./modules/format.js');
          return [vs.map((v) => f.formatAudienceTable(v)), vs.map((v) => f.formatAudienceShort(v))];
        }""",
        values,
    )
    assert out[0] == ["523.4K", "12.0K", "2.0MM", "50.6MM", "1.0MM", "1.0MM", "950"]
    assert out[1] == ["523.4K", "12K", "2MM", "50.6MM", "1MM", "1MM", "950"]


def test_viewer_cells_and_game_list_figures_show_one_decimal(app: Page) -> None:
    pattern = re.compile(r"^\d+\.\d(K|MM)$")
    figures = app.locator("#crews-panel tbody td.num .crews-figure")
    texts = figures.all_inner_texts()
    viewer_texts = [t for t in texts if t.endswith(("K", "MM"))]
    assert viewer_texts, "no viewer figures rendered"
    assert all(pattern.match(t) for t in viewer_texts), viewer_texts
    _rows(app).first.locator(".crews-chevron").click()
    games = app.locator("#crews-panel .crews-game .crews-figure").all_inner_texts()
    assert games and all(pattern.match(t) for t in games), games
