"""Crews table keyboard model, expanded row, game list, modal hand-off and phone layout (14-08).

Runs on the synthetic crews dataset (tests/e2e/crews_fixture.py). Expected values come from
its CASE_* constants: CASE_BIG is a 20-game crew (two game pages) whose pbp also worked 3
games with a second analyst; CASE_FILL_IN has one fill-in game in the regular crew's row.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from typing import Any

import pytest
from crews_fixture import CASE_BIG, CASE_FILL_IN
from playwright.sync_api import Locator, Page, expect

pytestmark = pytest.mark.e2e

BIG_CREW = "Big Pbp and Big Ana"
BIG_PBP = "Big Pbp"


@pytest.fixture
def app(
    guarded_page: Page,
    serve_crews: Callable[[Page], None],
    open_app: Callable[[Page, str], None],
) -> Page:
    serve_crews(guarded_page)
    open_app(guarded_page, "?view=crews")
    return guarded_page


def _rows(page: Page) -> Locator:
    return page.locator("#crews-panel tbody > tr.crews-row")


def _row(page: Page, name: str) -> Locator:
    exact = re.compile(rf"^{re.escape(name)}(?: ?with .*)?$")
    return _rows(page).filter(has=page.locator(".crews-name", has_text=exact))


def _sub(page: Page, name: str) -> Locator:
    return _row(page, name).locator("xpath=following-sibling::tr[1]")


def _games(page: Page, name: str) -> Locator:
    return _sub(page, name).locator("tr.crews-game")


def _status(page: Page) -> Locator:
    return page.locator("#crews-panel > .crews-status")


def _state(page: Page) -> dict[str, Any]:
    out: dict[str, Any] = page.evaluate("() => window.__testHooks.getState()")
    return out


def _focused_key(page: Page) -> str | None:
    out: str | None = page.evaluate(
        "() => document.activeElement && document.activeElement.dataset.rowKey || null"
    )
    return out


def _key_of(row: Locator) -> str:
    key = row.get_attribute("data-row-key")
    assert key
    return key


def _focus(row: Locator) -> None:
    row.focus()
    expect(row).to_be_focused()


def _expand(page: Page, name: str) -> Locator:
    row = _row(page, name)
    row.locator("button.crews-chevron").click()
    expect(row).to_have_attribute("aria-expanded", "true")
    return _sub(page, name)


# -- roving rows and the key map (V14-5) -----


def test_rows_are_one_roving_tab_stop(app: Page) -> None:
    stops = app.locator("#crews-panel tbody > tr.crews-row[tabindex='0']")
    expect(stops).to_have_count(1)
    _focus(_rows(app).nth(3))
    expect(app.locator("#crews-panel tbody > tr.crews-row[tabindex='0']")).to_have_count(1)
    expect(_rows(app).nth(3)).to_have_attribute("tabindex", "0")
    expect(_rows(app).nth(0)).to_have_attribute("tabindex", "-1")


def test_arrow_keys_home_end_and_pages_move_focus(app: Page) -> None:
    rows = _rows(app)
    _focus(rows.nth(0))
    app.keyboard.press("ArrowDown")
    expect(rows.nth(1)).to_be_focused()
    app.keyboard.press("ArrowDown")
    app.keyboard.press("ArrowUp")
    expect(rows.nth(1)).to_be_focused()
    app.keyboard.press("PageDown")
    expect(rows.nth(11)).to_be_focused()
    app.keyboard.press("PageUp")
    expect(rows.nth(1)).to_be_focused()
    app.keyboard.press("PageUp")
    expect(rows.nth(0)).to_be_focused()
    app.keyboard.press("End")
    expect(rows.nth(24)).to_be_focused()
    app.keyboard.press("PageDown")
    expect(rows.nth(24)).to_be_focused()
    app.keyboard.press("Home")
    expect(rows.nth(0)).to_be_focused()
    app.keyboard.press("ArrowUp")
    expect(rows.nth(0)).to_be_focused()


def test_arrows_skip_the_game_rows_of_an_open_row(app: Page) -> None:
    rows = _rows(app)
    first = rows.nth(0)
    first.locator("button.crews-chevron").click()
    expect(_sub(app, first.locator(".crews-name").inner_text())).to_be_visible()
    _focus(first)
    app.keyboard.press("ArrowDown")
    expect(rows.nth(1)).to_be_focused()
    app.keyboard.press("ArrowUp")
    expect(first).to_be_focused()


def test_enter_and_space_toggle_the_pick(app: Page) -> None:
    row = _row(app, BIG_CREW)
    _focus(row)
    app.keyboard.press("Enter")
    expect(_row(app, BIG_CREW)).to_have_attribute("aria-pressed", "true")
    assert _state(app)["crew"]
    expect(_row(app, BIG_CREW)).to_be_focused()
    app.keyboard.press("Enter")
    expect(_row(app, BIG_CREW)).to_have_attribute("aria-pressed", "false")
    assert not _state(app)["crew"]
    app.keyboard.press("Space")
    expect(_row(app, BIG_CREW)).to_have_attribute("aria-pressed", "true")
    app.keyboard.press("Space")
    expect(_row(app, BIG_CREW)).to_have_attribute("aria-pressed", "false")


def test_right_and_left_expand_and_collapse(app: Page) -> None:
    row = _row(app, BIG_CREW)
    _focus(row)
    app.keyboard.press("ArrowLeft")
    expect(row).to_have_attribute("aria-expanded", "false")
    app.keyboard.press("ArrowRight")
    expect(row).to_have_attribute("aria-expanded", "true")
    expect(_sub(app, BIG_CREW)).to_have_class(re.compile("crews-expanded"))
    app.keyboard.press("ArrowRight")
    expect(app.locator("#crews-panel tr.crews-expanded")).to_have_count(1)
    expect(row).to_be_focused()
    app.keyboard.press("ArrowLeft")
    expect(row).to_have_attribute("aria-expanded", "false")
    expect(app.locator("#crews-panel tr.crews-expanded")).to_have_count(0)
    assert not _state(app)["crew"]


def test_escape_inside_an_open_row_collapses_it_and_focuses_the_row(app: Page) -> None:
    _expand(app, BIG_CREW)
    _games(app, BIG_CREW).first.focus()
    app.keyboard.press("Escape")
    expect(_row(app, BIG_CREW)).to_have_attribute("aria-expanded", "false")
    expect(_row(app, BIG_CREW)).to_be_focused()
    # On a collapsed row Escape does nothing.
    app.keyboard.press("Escape")
    expect(_row(app, BIG_CREW)).to_be_focused()


def test_chevron_toggles_by_click_enter_and_space_and_never_picks(app: Page) -> None:
    row = _row(app, BIG_CREW)
    chevron = row.locator("button.crews-chevron")
    expect(chevron).to_have_attribute("aria-label", "Show games")
    chevron.click()
    expect(chevron).to_have_attribute("aria-label", "Hide games")
    expect(row).to_have_attribute("aria-expanded", "true")
    chevron.focus()
    app.keyboard.press("Enter")
    expect(row).to_have_attribute("aria-expanded", "false")
    expect(chevron).to_have_attribute("aria-label", "Show games")
    app.keyboard.press("Space")
    expect(row).to_have_attribute("aria-expanded", "true")
    app.keyboard.press("Space")
    expect(row).to_have_attribute("aria-expanded", "false")
    assert not _state(app)["crew"]
    expect(row).to_have_attribute("aria-pressed", "false")


def test_header_buttons_sort_on_enter_and_space_and_keep_focus(app: Page) -> None:
    head = app.locator("#crews-panel thead button[data-sort-key='exc']")
    head.focus()
    app.keyboard.press("Enter")
    expect(app.locator("#crews-panel thead th.crews-col-exc")).to_have_attribute(
        "aria-sort", "descending"
    )
    expect(app.locator("#crews-panel thead button[data-sort-key='exc']")).to_be_focused()
    app.keyboard.press("Space")
    expect(app.locator("#crews-panel thead th.crews-col-exc")).to_have_attribute(
        "aria-sort", "ascending"
    )
    expect(app.locator("#crews-panel thead button[data-sort-key='exc']")).to_be_focused()


def test_focus_survives_a_rerender(app: Page) -> None:
    row = _rows(app).nth(5)
    key = _key_of(row)
    _focus(row)
    app.keyboard.press("Enter")
    expect(app.locator("#crews-panel tbody > tr.crews-row:focus")).to_have_count(1)
    assert _focused_key(app) == key


# -- the module status seat -----


def test_status_seat_is_a_polite_hidden_region_kept_across_renders(app: Page) -> None:
    seat = _status(app)
    expect(seat).to_have_attribute("role", "status")
    expect(seat).to_have_attribute("aria-live", "polite")
    expect(seat).to_have_class(re.compile("visually-hidden"))
    app.evaluate(
        "() => { document.querySelector('#crews-panel > .crews-status').dataset.mark = '1'; }"
    )
    app.locator("#crews-panel thead button[data-sort-key='network']").click()
    expect(app.locator("#crews-panel > .crews-status[data-mark='1']")).to_have_count(1)


def test_sort_and_mode_changes_are_announced(app: Page) -> None:
    total = app.evaluate(
        """async () => {
          const G = await import('./modules/crew-groups.js');
          const h = window.__testHooks;
          return G.buildCrewRows(h.data, h.getView(), { mode: 'crew', perSeason: false }).totalRows;
        }"""
    )
    app.locator("#crews-panel thead button[data-sort-key='exc']").click()
    expect(_status(app)).to_have_text(
        f"Crews sorted by Avg excitement, descending, 25 of {total} rows shown."
    )
    app.locator("#crews-panel thead button[data-sort-key='exc']").click()
    expect(_status(app)).to_have_text(
        f"Crews sorted by Avg excitement, ascending, 25 of {total} rows shown."
    )
    app.locator("#crews-panel .crews-mode button[data-cmode='pbp']").click()
    expect(_status(app)).to_contain_text("Crews sorted by Avg excitement, ascending, 25 of ")


def test_view_more_is_announced(app: Page) -> None:
    app.locator("#crews-panel .crews-more").click()
    text = _status(app).inner_text()
    match = re.fullmatch(r"25 more rows shown, (\d+) left\.", text)
    assert match, text
    expect(app.locator("#crews-panel .crews-more")).to_have_text(
        re.compile(rf"View \d+ more \({match.group(1)} left\)")
    )


# -- expanded row and game list -----


def test_game_list_is_newest_first_ten_at_a_time(app: Page) -> None:
    sub = _expand(app, BIG_CREW)
    games = _games(app, BIG_CREW)
    expect(games).to_have_count(10)
    dates = [d.strip() for d in sub.locator("tr.crews-game td.crews-game-date").all_inner_texts()]
    assert dates == sorted(dates, reverse=True)
    for d in dates:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)
    more = sub.locator("button.crews-games-more")
    expect(more).to_have_text("View 10 more (10 left)")
    more.click()
    expect(games).to_have_count(20)
    expect(games.nth(10)).to_be_focused()
    expect(sub.locator("button.crews-games-more")).to_have_count(0)
    all_dates = [d.strip() for d in sub.locator("td.crews-game-date").all_inner_texts()]
    assert all_dates == sorted(all_dates, reverse=True)
    assert CASE_BIG["games"] == len(all_dates)


def test_game_list_view_more_names_a_short_remainder(app: Page) -> None:
    _expand(app, BIG_CREW)
    _sub(app, BIG_CREW).locator("button.crews-games-more").click()
    expect(_games(app, BIG_CREW)).to_have_count(20)
    # A 5-game crew shows everything and no button.
    sub = _expand(app, "Trio Pbp, Trio A1 and Trio A2")
    expect(sub.locator("tr.crews-game")).to_have_count(5)
    expect(sub.locator("button.crews-games-more")).to_have_count(0)


def test_expansion_survives_a_pick_and_resets_with_a_sort(app: Page) -> None:
    _expand(app, BIG_CREW)
    _row(app, BIG_CREW).click()
    expect(_row(app, BIG_CREW)).to_have_attribute("aria-pressed", "true")
    expect(_row(app, BIG_CREW)).to_have_attribute("aria-expanded", "true")
    expect(_games(app, BIG_CREW)).to_have_count(10)
    app.locator("#crews-panel thead button[data-sort-key='exc']").click()
    expect(app.locator("#crews-panel tr.crews-expanded")).to_have_count(0)


def test_opening_one_row_does_not_change_another_rows_height(app: Page) -> None:
    other = _rows(app).nth(4)
    before = other.bounding_box()
    assert before
    _expand(app, BIG_CREW)
    after = _rows(app).nth(4).bounding_box()
    assert after
    assert before["height"] == after["height"]


def test_sub_row_spans_every_column(app: Page) -> None:
    sub = _expand(app, BIG_CREW)
    cols = app.locator("#crews-panel .crews-table > thead th").count()
    expect(sub.locator("> td")).to_have_attribute("colspan", str(cols))


def test_fill_in_tag_marks_the_fill_in_game_in_crew_mode(app: Page) -> None:
    name = "Fill Pbp and Fill Ana"
    _expand(app, name)
    tags = _sub(app, name).locator("tr.crews-game .crews-tag")
    expect(tags).to_have_count(CASE_FILL_IN["fill_in_games"])
    expect(tags).to_have_text("fill-in")
    expect(tags).to_have_attribute("title", "The regular analyst was absent")


def test_person_mode_lists_partners_by_count_and_the_crew_column(app: Page) -> None:
    app.locator("#crews-panel .crews-mode button[data-cmode='pbp']").click()
    row = _row(app, BIG_PBP)
    row.locator("button.crews-chevron").click()
    sub = _sub(app, BIG_PBP)
    expect(sub.locator(".crews-worked-label")).to_have_text("Worked with")
    expect(sub.locator(".crews-worked")).to_have_text(
        f"Big Ana ({CASE_BIG['games']}), Big Ana2 ({CASE_BIG['other_games']})"
    )
    heads = [h.strip() for h in sub.locator("thead th").all_inner_texts()]
    assert heads == ["Date", "Matchup", "Network", "Crew", "Viewers"]
    crews = {c.strip() for c in sub.locator("td.crews-game-crew").all_inner_texts()}
    assert crews == {"Big Ana", "Big Ana2"} or crews <= {"Big Ana", "Big Ana2"}
    assert sub.locator("tr.crews-game .crews-tag").count() == 0


def test_crew_mode_has_no_worked_with_and_no_crew_column(app: Page) -> None:
    sub = _expand(app, BIG_CREW)
    expect(sub.locator(".crews-worked-label")).to_have_count(0)
    heads = [h.strip() for h in sub.locator("thead th").all_inner_texts()]
    assert heads == ["Date", "Matchup", "Network", "Viewers"]


def test_unrated_games_say_none_rated_and_rated_ones_show_a_figure(app: Page) -> None:
    sub = _expand(app, BIG_CREW)
    cells = [c.strip() for c in sub.locator("td.crews-game-viewers").all_inner_texts()]
    assert "none rated" in cells
    assert any(re.fullmatch(r"[\d.]+(MM|K)", c) for c in cells)


def test_second_source_figure_keeps_the_publisher_link(
    guarded_page: Page,
    fixture_raw: dict[str, Any],
    open_app: Callable[[Page, str], None],
) -> None:
    from crews_fixture import build_crews_raw

    raw = build_crews_raw(copy.deepcopy(fixture_raw))
    # Every rated telecast of the first big-crew game becomes a Sports Media Watch figure.
    t = raw["telecasts"]
    people = raw["lookups"]["people"]
    big = next(k for k, p in enumerate(people) if p["id"] == "big-pbp")
    target = next(i for i in range(len(t["crew"])) if any(c["person"] == big for c in t["crew"][i]))
    t["figure_source"] = ["rr"] * len(t["crew"])
    t["figure_source"][target] = "smw"
    t["source_url"][target] = "https://example.com/smw/season"
    raw["lookups"]["publishers"] = ["Sports Media Watch", *raw["lookups"]["publishers"][1:]]
    guarded_page.route("**/site-data.json*", lambda route: route.fulfill(json=copy.deepcopy(raw)))
    open_app(guarded_page, "?view=crews")
    _row(guarded_page, BIG_CREW).locator("button.crews-chevron").click()
    sub = _sub(guarded_page, BIG_CREW)
    sub.locator("button.crews-games-more").click()
    link = sub.locator("a.crews-source")
    expect(link).to_have_count(1)
    expect(link).to_have_attribute("href", "https://example.com/smw/season")
    expect(link).to_have_attribute("rel", "noopener noreferrer")
    # Following the link does not open the detail modal.
    guarded_page.evaluate(
        "() => document.querySelector('a.crews-source')"
        ".addEventListener('click', (e) => e.preventDefault())"
    )
    link.click()
    expect(guarded_page.locator("#detail-panel")).not_to_have_attribute("open", "")


# -- modal hand-off (RT-28) -----


def test_enter_on_a_game_opens_the_detail_modal_and_close_returns_focus(app: Page) -> None:
    _expand(app, BIG_CREW)
    game = _games(app, BIG_CREW).nth(2)
    game.focus()
    app.keyboard.press("Enter")
    expect(app.locator("#detail-panel")).to_have_attribute("open", "")
    expect(app.locator("#panel-body")).not_to_be_empty()
    app.keyboard.press("Escape")
    expect(app.locator("#detail-panel")).not_to_have_attribute("open", "")
    expect(_games(app, BIG_CREW).nth(2)).to_be_focused()


def test_space_and_click_open_the_modal_and_enter_close_does_not_reopen(app: Page) -> None:
    _expand(app, BIG_CREW)
    game = _games(app, BIG_CREW).nth(0)
    game.focus()
    app.keyboard.press("Space")
    expect(app.locator("#detail-panel")).to_have_attribute("open", "")
    app.locator("#panel-close").focus()
    app.keyboard.press("Enter")
    expect(app.locator("#detail-panel")).not_to_have_attribute("open", "")
    expect(_games(app, BIG_CREW).nth(0)).to_be_focused()
    app.wait_for_timeout(150)
    expect(app.locator("#detail-panel")).not_to_have_attribute("open", "")
    _games(app, BIG_CREW).nth(1).click()
    expect(app.locator("#detail-panel")).to_have_attribute("open", "")


def test_modal_shows_the_clicked_game(app: Page) -> None:
    _expand(app, BIG_CREW)
    game = _games(app, BIG_CREW).nth(0)
    matchup = game.locator("td.crews-game-matchup").inner_text().strip()
    game.click()
    away, home = matchup.split(" at ")
    expect(app.locator("#panel-title")).to_have_text(
        re.compile(rf"^{re.escape(away)} \d+ at {re.escape(home)} \d+$")
    )


# -- phone -----


def test_phone_sub_row_stays_in_view_and_game_items_are_stacked(app: Page) -> None:
    app.set_viewport_size({"width": 390, "height": 900})
    sub = _expand(app, BIG_CREW)
    wrap = app.locator("#crews-panel .crews-table-wrap")
    scroll_w = wrap.evaluate("el => [el.scrollWidth, el.clientWidth]")
    assert scroll_w[0] > scroll_w[1], "the table scrolls sideways"
    inner = sub.locator(".crews-expanded-inner")
    wrap.evaluate("el => { el.scrollLeft = el.scrollWidth; }")
    box = inner.bounding_box()
    wrap_box = wrap.bounding_box()
    assert box and wrap_box
    assert box["x"] >= wrap_box["x"] - 1
    assert box["x"] + box["width"] <= wrap_box["x"] + wrap_box["width"] + 1
    # Chevron and name cells stay pinned while the table is scrolled.
    chev_x = _row(app, BIG_CREW).locator("td.crews-chevron-cell").bounding_box()
    name_x = _row(app, BIG_CREW).locator("td.crews-name").bounding_box()
    assert chev_x and name_x
    assert abs(chev_x["x"] - wrap_box["x"]) <= 2
    assert abs(name_x["x"] - (wrap_box["x"] + 44)) <= 2
    game = _games(app, BIG_CREW).first
    gbox = game.bounding_box()
    assert gbox and gbox["height"] >= 44
    matchup = game.locator("td.crews-game-matchup").bounding_box()
    date = game.locator("td.crews-game-date").bounding_box()
    viewers = game.locator("td.crews-game-viewers").bounding_box()
    assert matchup and date and viewers
    assert date["y"] > matchup["y"], "line 2 sits under the matchup"
    assert abs(viewers["y"] - date["y"]) <= 2, "viewers is on line 2 with the date"
    size = game.locator("td.crews-game-matchup").evaluate("el => getComputedStyle(el).fontSize")
    meta = game.locator("td.crews-game-date").evaluate("el => getComputedStyle(el).fontSize")
    assert (size, meta) == ("14px", "12px")


def test_phone_chevron_is_44px(app: Page) -> None:
    app.set_viewport_size({"width": 390, "height": 900})
    box = _rows(app).first.locator("button.crews-chevron").bounding_box()
    assert box
    assert box["width"] == 44
    assert box["height"] == 44


def test_desktop_sub_row_uses_the_surface_fill_and_rules(app: Page) -> None:
    sub = _expand(app, BIG_CREW)
    style = sub.locator("> td").evaluate(
        """el => {
          const s = getComputedStyle(el);
          const root = getComputedStyle(document.documentElement);
          return [s.backgroundColor, root.getPropertyValue('--surface').trim(),
                  s.borderTopWidth, s.borderBottomWidth];
        }"""
    )
    assert style[2] == "1px"
    assert style[3] == "1px"
    probe = app.evaluate(
        """(v) => {
          const d = document.createElement('div'); d.style.color = v;
          document.body.append(d);
          const c = getComputedStyle(d).color; d.remove(); return c;
        }""",
        style[1],
    )
    assert style[0] == probe
    inner = sub.locator(".crews-expanded-inner").evaluate("el => getComputedStyle(el).paddingTop")
    assert inner == "16px"
