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
    open_app(guarded_page, "?view=crews")
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
