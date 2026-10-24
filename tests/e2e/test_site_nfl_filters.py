# ruff: noqa: E501  (embedded UI copy)
"""999.5-12: the NFL toolbar, its four filters, Clear all filters and the mobile sheet."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

TRIGGERS = ["Announcers", "Seasons", "Category", "Team"]
BAR = [*TRIGGERS, "Booths"]  # the fixed filter set (D-10): Booths on every view
CFB_ONLY = ["Networks", "Role", "Conference", "Bowls/Playoffs", "Kickoff", "School", "Game"]


@pytest.fixture
def app(nfl_guarded_page: Page, open_nfl_app: Callable[..., None]) -> Page:
    open_nfl_app(nfl_guarded_page)
    return nfl_guarded_page


@pytest.fixture
def mobile(nfl_mobile_page: Page, open_nfl_app: Callable[..., None]) -> Page:
    open_nfl_app(nfl_mobile_page)
    return nfl_mobile_page


def _search(page: Page) -> str:
    return page.evaluate("location.search")  # type: ignore[no-any-return]


def _open(page: Page, key: str) -> None:
    page.click(f"#nfl-trigger-{key}")
    page.wait_for_selector(f"#nfl-pop-{key}:popover-open")


def test_trigger_order_and_labels(app: Page) -> None:
    labels = app.eval_on_selector_all(
        "#nfl-toolbar > button",
        "els => els.filter(e => e.offsetParent !== null).map(e => e.textContent.trim())",
    )
    # Booths is last in the bar and Clear all filters has moved to the selection row (C1).
    assert labels == BAR
    assert app.locator("#nfl-toolbar #nfl-clear-filters").count() == 0
    # D-11: no spacer cells pad the bar out any more.
    assert app.locator(".nfl-toolbar-spacer").count() == 0
    text = app.inner_text("#nfl-toolbar")
    for label in CFB_ONLY:
        assert label not in text
    for key in ("announcers", "seasons", "category", "team"):
        assert app.get_attribute(f"#nfl-trigger-{key}", "aria-haspopup") == "dialog"
        assert app.get_attribute(f"#nfl-trigger-{key}", "aria-expanded") == "false"


def test_clear_all_filters_is_the_right_end_of_the_selection_row(app: Page) -> None:
    """C1: Clear all filters is the last item of the always-rendered NFL
    selection row, flush with its right edge."""
    assert app.locator("#nfl-selection-row > #nfl-clear-filters").count() == 1
    last = app.evaluate("document.querySelector('#nfl-selection-row').lastElementChild.id")
    assert last == "nfl-clear-filters"
    box = app.locator("#nfl-clear-filters").bounding_box()
    row = app.locator("#nfl-selection-row").bounding_box()
    assert box is not None and row is not None
    assert abs((box["x"] + box["width"]) - (row["x"] + row["width"])) <= 1


def test_changed_trigger_styling_follows_the_clean_load_predicate(app: Page) -> None:
    """SHELL-03 on the NFL bar: a control that differs from a clean load gets
    the accent border, --accent-soft fill and a 600 label; reverting it clears
    the state; the full summary is in title and aria-label."""
    assert app.locator("#nfl-toolbar .is-changed").count() == 0
    app.evaluate("window.__nflTestHooks.setState({ teams: ['f-gulls'] })")
    trigger = app.locator("#nfl-trigger-team")
    assert "is-changed" in (trigger.get_attribute("class") or "")
    style = trigger.evaluate(
        "el => { const s = getComputedStyle(el);"
        " return [s.borderTopColor, s.backgroundColor,"
        " getComputedStyle(el.querySelector('.filter-label')).fontWeight]; }"
    )
    assert style == ["rgb(27, 79, 92)", "rgb(227, 237, 239)", "600"]
    title = trigger.get_attribute("title") or ""
    assert title.startswith("Team") and title == trigger.get_attribute("aria-label")
    app.evaluate("window.__nflTestHooks.setState({ teams: [] })")
    assert app.locator("#nfl-toolbar .is-changed").count() == 0
    assert app.locator("#nfl-trigger-team .filter-value").inner_text() == ""


def test_announcers_search_pick_chip_and_remove(app: Page, nfl_site_dist: Path) -> None:
    cfb_people = json.loads((nfl_site_dist / "site-data.json").read_text(encoding="utf-8"))[
        "lookups"
    ]["people"]
    cfb_only = cfb_people[0]["name"]
    _open(app, "announcers")
    assert (
        app.get_attribute("#nfl-person-search-pop", "placeholder")
        == "Type a name, or pick from the list"
    )
    app.fill("#nfl-person-search-pop", "ada qu")
    visible = app.locator("#nfl-person-results-pop > li:visible")
    assert visible.locator(".option-name").all_inner_texts() == ["Ada Quill"]
    # CFB parity: each row shows the usual role pill and a game count.
    assert visible.locator(".option-role .role-pill").count() == 1
    assert visible.locator(".option-count").inner_text() == "(4)"
    app.fill("#nfl-person-search-pop", cfb_only)
    assert app.locator("#nfl-person-results-pop > li:visible").count() == 0
    app.fill("#nfl-person-search-pop", "ada")
    visible.first.click()
    assert "people=p00" in _search(app)
    chip = app.locator("#nfl-chips .chip")
    assert chip.count() == 1
    assert "Ada Quill" in chip.inner_text()
    assert app.get_attribute("#nfl-trigger-announcers", "data-active") == "true"
    app.click('#nfl-chips button[aria-label="Remove Ada Quill"]')
    assert _search(app) == "?sport=nfl"
    assert app.locator("#nfl-chips .chip").count() == 0


def test_no_compare_or_together_controls(app: Page) -> None:
    _open(app, "announcers")
    text = app.inner_text("#nfl-pop-announcers").lower()
    assert "compare" not in text
    assert "together" not in text


def test_seasons_range_writes_url(app: Page) -> None:
    _open(app, "seasons")
    app.select_option("#nfl-season-to-pop", "2025")
    assert _search(app) == "?sport=nfl&seasons=2024-2025"
    app.select_option("#nfl-season-to-pop", "2026")
    assert _search(app) == "?sport=nfl"
    app.select_option("#nfl-season-from-pop", "2026")
    assert "seasons=2026-2026" in _search(app)
    app.click("#nfl-pop-seasons .group-reset")
    assert _search(app) == "?sport=nfl"


def test_category_labels_and_url(app: Page) -> None:
    _open(app, "category")
    legends = app.locator("#nfl-pop-category legend").all_inner_texts()
    assert legends == ["Solo slots", "Other special games"]
    labels = app.locator("#nfl-pop-category .check-row .option-name").all_inner_texts()
    assert labels == [
        "Thursday night",
        "Sunday night",
        "Monday night",
        "Thanksgiving",
        "Christmas",
        "Black Friday",
        "Saturday",
        "International (solo slot)",
        "Other solo slot",
        "Fox AGOTW",
        "CBS late national",
        "International (any window)",
        "Flexed",
    ]
    app.check('#nfl-pop-category input[value="intl"]')
    assert _search(app) == "?sport=nfl&cat=intl"
    assert app.get_attribute("#nfl-trigger-category", "data-active") == "true"
    app.uncheck('#nfl-pop-category input[value="intl"]')
    assert _search(app) == "?sport=nfl"


def test_team_picks_write_url(app: Page) -> None:
    _open(app, "team")
    assert app.get_attribute("#nfl-team-search-pop", "placeholder") == "Search teams"
    app.fill("#nfl-team-search-pop", "gulls")
    assert app.locator("#nfl-pop-team .check-item:visible").count() == 1
    app.check('#nfl-pop-team input[value="f-gulls"]')
    assert "team=f-gulls" in _search(app)
    app.fill("#nfl-team-search-pop", "")
    app.check('#nfl-pop-team input[value="f-foxes"]')
    assert "team=f-foxes,f-gulls" in _search(app).replace("%2C", ",")


def test_clear_all_filters_resets_url(app: Page) -> None:
    app.evaluate(
        "window.__nflTestHooks.setState({ seasons: [2025, 2025], teams: ['f-gulls'], people: ['p00'], cats: ['agotw'] })"
    )
    assert _search(app) != "?sport=nfl"
    app.click("#nfl-clear-filters")
    assert _search(app) == "?sport=nfl"
    state = app.evaluate("window.__nflTestHooks.getState()")
    assert state["teams"] == [] and state["people"] == [] and state["cats"] == []


def test_keyboard_reaches_each_trigger_and_enter_opens(app: Page) -> None:
    app.focus("#nfl-trigger-announcers")
    for key in ("seasons", "category", "team", "booths"):
        app.keyboard.press("Tab")
        assert app.evaluate("document.activeElement.id") == f"nfl-trigger-{key}"
    app.keyboard.press("Enter")
    app.wait_for_selector("#nfl-pop-booths:popover-open")
    # aria-expanded follows the popover's toggle event, which fires after it opens.
    app.wait_for_selector('#nfl-trigger-booths[aria-expanded="true"]')
    app.keyboard.press("Escape")
    app.wait_for_selector("#nfl-pop-booths:not(:popover-open)", state="attached")
    app.wait_for_selector('#nfl-trigger-booths[aria-expanded="false"]')


def test_popover_markup_is_text_only(app: Page) -> None:
    _open(app, "announcers")
    app.fill("#nfl-person-search-pop", "<img src=x onerror=alert(1)>")
    assert app.locator("#nfl-pop-announcers img").count() == 0


def test_no_console_errors_through_filter_use(app: Page) -> None:
    errors: list[str] = []
    app.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    _open(app, "category")
    app.check('#nfl-pop-category input[value="agotw"]')
    app.click("#nfl-clear-filters")
    assert errors == []


# ---------------------------------------------------------------- mobile


def test_mobile_only_filters_button_visible(mobile: Page) -> None:
    visible = mobile.eval_on_selector_all(
        "#nfl-toolbar > button",
        "els => els.filter(e => e.offsetParent !== null).map(e => e.id)",
    )
    assert visible == ["nfl-filters-button"]
    assert mobile.inner_text("#nfl-filters-button") == "Filters"
    assert mobile.locator(".nfl-toolbar-spacer").count() == 0


def test_mobile_badge_counts_active_filters(mobile: Page) -> None:
    mobile.evaluate("window.__nflTestHooks.setState({ teams: ['f-gulls'], cats: ['agotw'] })")
    assert mobile.inner_text("#nfl-filters-button") == "Filters · 2 changed"
    chips = mobile.locator("#nfl-filter-chips li button")
    assert chips.count() == 2
    assert [t.split()[0] for t in chips.all_inner_texts()] == ["Category", "Team"]
    chip_style = chips.first.evaluate(
        "el => { const s = getComputedStyle(el); return [s.borderTopColor, s.backgroundColor]; }"
    )
    assert chip_style == ["rgb(27, 79, 92)", "rgb(227, 237, 239)"]
    assert (
        mobile.evaluate("getComputedStyle(document.querySelector('#nfl-filters-button')).color")
        == "rgb(27, 79, 92)"
    )
    mobile.click("#nfl-filters-button")
    mobile.wait_for_selector("#nfl-filters-sheet:popover-open")
    mobile.click("#nfl-filters-sheet .nfl-sheet-clear")
    assert mobile.inner_text("#nfl-filters-button") == "Filters"
    assert mobile.locator("#nfl-filter-chips li").count() == 0


def test_mobile_sheet_sections_url_and_close(mobile: Page) -> None:
    mobile.click("#nfl-filters-button")
    mobile.wait_for_selector("#nfl-filters-sheet:popover-open")
    # The popover's `toggle` event, which sets aria-expanded, fires after :popover-open holds.
    mobile.wait_for_function(
        "document.getElementById('nfl-filters-button').getAttribute('aria-expanded') === 'true'"
    )
    headings = mobile.locator("#nfl-filters-sheet .sheet-body h3:visible").all_inner_texts()
    assert headings == BAR  # Booths is a sheet row on every view (D-10)
    mobile.select_option("#nfl-season-to-sheet", "2025")
    assert _search(mobile) == "?sport=nfl&seasons=2024-2025"
    assert mobile.inner_text("#nfl-filters-button") == "Filters · 1 changed"
    assert mobile.inner_text("#nfl-filters-show-results") == "Show games"
    mobile.click("#nfl-filters-sheet .nfl-sheet-clear")
    assert _search(mobile) == "?sport=nfl"
    mobile.click("#nfl-filters-show-results")
    mobile.wait_for_selector("#nfl-filters-sheet:not(:popover-open)", state="attached")


def test_mobile_sheet_controls_are_44px(mobile: Page) -> None:
    mobile.click("#nfl-filters-button")
    mobile.wait_for_selector("#nfl-filters-sheet:popover-open")
    small = mobile.evaluate(
        """() => {
          const sel = '#nfl-filters-sheet .sheet-body input:not([type=checkbox]), #nfl-filters-sheet select,'
            + ' #nfl-filters-sheet .group-reset, #nfl-filters-sheet .check-row,'
            + ' #nfl-filters-sheet .nfl-sheet-clear, #nfl-filters-show-results';
          return [...document.querySelectorAll(sel)]
            .filter((e) => e.offsetParent !== null)
            .map((e) => [e.id || e.className, e.getBoundingClientRect().height])
            .filter(([, h]) => h < 43.5);
        }"""
    )
    assert small == []


def test_announcer_list_is_one_tab_stop_with_arrow_keys(app: Page) -> None:
    """JS-WR-05: a roving tabindex, not one tab stop per announcer; arrows move between options."""
    _open(app, "announcers")
    options = "#nfl-person-results-pop > li"
    assert app.locator(f"{options}[tabindex='0']").count() == 1
    names = app.locator(f"{options}:visible .option-name").all_inner_texts()
    assert len(names) >= 3

    def active() -> str | None:
        return app.evaluate(  # type: ignore[no-any-return]
            "document.activeElement.matches('li[role=option]')"
            " ? document.activeElement.querySelector('.option-name').textContent : document.activeElement.id"
        )

    app.focus("#nfl-person-search-pop")
    app.keyboard.press("ArrowDown")
    assert active() == names[0]
    app.keyboard.press("ArrowDown")
    assert active() == names[1]
    assert app.locator(f"{options}[tabindex='0'] .option-name").inner_text() == names[1]
    app.keyboard.press("End")
    assert active() == names[-1]
    app.keyboard.press("Home")
    assert active() == names[0]
    app.keyboard.press("ArrowUp")
    assert active() == "nfl-person-search-pop"
    # Tab from an option leaves the list in one step.
    app.keyboard.press("ArrowDown")
    app.keyboard.press("Tab")
    assert app.evaluate("document.activeElement.closest('#nfl-person-results-pop')") is None
    # aria-expanded follows whether any option is listed.
    assert app.get_attribute("#nfl-person-search-pop", "aria-expanded") == "true"
    app.fill("#nfl-person-search-pop", "zzzz no such announcer")
    assert app.get_attribute("#nfl-person-search-pop", "aria-expanded") == "false"
    app.fill("#nfl-person-search-pop", "ada")
    assert app.get_attribute("#nfl-person-search-pop", "aria-expanded") == "true"
    stop = app.locator(f"{options}[tabindex='0']")
    assert stop.count() == 1 and stop.is_visible()


# ------------------------------------------------------------------ Booths (08-09, D-10)


def _booths_app(page: Page, open_nfl_app: Callable[..., None], view: str, extra: str = "") -> None:
    open_nfl_app(page, f"?sport=nfl&view={view}{extra}")
    page.wait_for_function("window.__nflTestHooks.getViewModel('crews') !== null")


def _state(page: Page) -> dict:  # type: ignore[type-arg]
    return page.evaluate("window.__nflTestHooks.getState()")  # type: ignore[no-any-return]


def _booth_games(raw: dict, key: str) -> list[int]:  # type: ignore[type-arg]
    """Games a booth key selects: its pbp person calling on a network in its group."""
    group_id, person_id = key.split(":")
    lk = raw["lookups"]
    gi = next(i for i, g in enumerate(lk["network_groups"]) if g["id"] == group_id)
    pi = next(i for i, p in enumerate(lk["people"]) if p["id"] == person_id)
    members = set(lk["network_groups"][gi]["members"])
    g = raw["games"]
    return [
        i
        for i in range(len(g["season"]))
        if g["network"][i] in members
        and any(m["person"] == pi and m["role"] == "pbp" for m in (g["crew"][i] or []))
    ]


def test_booths_trigger_is_visible_and_enabled_on_every_view(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    """D-10: Booths is part of the fixed NFL filter set, on all four views."""
    page = nfl_guarded_page
    open_nfl_app(page, "?sport=nfl")
    for view in ("special", "scatter", "crews", "viewership"):
        page.evaluate("v => window.__nflTestHooks.setState({ view: v })", view)
        page.wait_for_function("v => window.__nflTestHooks.getState().view === v", arg=view)
        trigger = page.locator("#nfl-trigger-booths")
        assert trigger.is_visible(), view
        assert trigger.is_enabled(), view
        assert trigger.get_attribute("aria-disabled") in (None, "false"), view
        assert page.locator(".nfl-toolbar-spacer").count() == 0, view


def test_booth_pick_narrows_tables_and_changes_special_and_scatter(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    nfl_fixture_raw: dict,  # type: ignore[type-arg]
) -> None:
    """A booth pick narrows the matched games on Crews and Viewership, changes the Special
    games (matched overlay) and Scatter (fade) view models, and stays in state and the URL on
    all four views (D-04/D-05 picks intersect everywhere)."""
    page = nfl_guarded_page
    _booths_app(page, open_nfl_app, "crews")
    key = page.evaluate("window.__nflTestHooks.getBoothCatalog()[0].key")
    expected = sorted(_booth_games(nfl_fixture_raw, key))
    assert expected
    for view in ("crews", "viewership"):
        page.evaluate("v => window.__nflTestHooks.setState({ view: v, booths: [] })", view)
        page.evaluate("k => window.__nflTestHooks.setState({ booths: [k] })", key)
        page.wait_for_function("window.__nflTestHooks.getState().booths.length === 1")
        assert sorted(page.evaluate("window.__nflTestHooks.getTableIndexes()")) == expected, view
    for view in ("special", "scatter"):
        page.evaluate("v => window.__nflTestHooks.setState({ view: v, booths: [] })", view)
        page.wait_for_function("v => window.__nflTestHooks.getState().view === v", arg=view)
        before = page.evaluate("v => JSON.stringify(window.__nflTestHooks.getViewModel(v))", view)
        page.evaluate("k => window.__nflTestHooks.setState({ booths: [k] })", key)
        page.wait_for_function("window.__nflTestHooks.getState().booths.length === 1")
        after = page.evaluate("v => JSON.stringify(window.__nflTestHooks.getViewModel(v))", view)
        assert before not in ("null", "undefined"), view
        assert before != after, view
        assert "booths=" in _search(page), view


def test_booths_grouped_by_network_on_crews_and_category_on_viewership(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    nfl_fixture_raw: dict,  # type: ignore[type-arg]
) -> None:
    page = nfl_guarded_page
    _booths_app(page, open_nfl_app, "crews")
    _open(page, "booths")
    names = page.locator("#nfl-pop-booths .group-head .group-name").all_inner_texts()
    nets = [g["name"] for g in nfl_fixture_raw["lookups"]["network_groups"]]
    assert names and all(n in nets for n in names)
    assert page.locator("#nfl-pop-booths [role=listbox][aria-multiselectable=true]").count() == 1
    page.keyboard.press("Escape")
    page.evaluate("window.__nflTestHooks.setState({ view: 'viewership' })")
    page.wait_for_function("window.__nflTestHooks.getState().view === 'viewership'")
    _open(page, "booths")
    cats = [c["label"] for c in nfl_fixture_raw["lookups"]["view_categories"]]
    names = page.locator("#nfl-pop-booths .group-head .group-name").all_inner_texts()
    assert names and all(n in cats for n in names)


def test_booth_rows_show_role_pills_and_counts(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    nfl_fixture_raw: dict,  # type: ignore[type-arg]
) -> None:
    """Announcers parity: one line per person with its role pill, then the game count."""
    page = nfl_guarded_page
    _booths_app(page, open_nfl_app, "crews")
    _open(page, "booths")
    people = {p["id"]: p["name"] for p in nfl_fixture_raw["lookups"]["people"]}
    rows = page.locator("#nfl-booth-results-pop li[role=option]")
    assert rows.count() >= 2
    for k in range(rows.count()):
        row = rows.nth(k)
        key = row.get_attribute("data-booth")
        assert key
        lines = row.locator(".option-line")
        assert 1 <= lines.count() <= 2
        assert lines.first.locator(".option-name").inner_text() == people[key.split(":")[1]]
        roles = row.locator(".option-role .role-pill").evaluate_all(
            "ps => ps.map(p => p.dataset.role)"
        )
        assert roles == ["pbp", "analyst"][: lines.count()]
        count = row.locator(".option-count")
        assert count.get_attribute("aria-hidden") == "true"
        assert count.inner_text() == f"({len(_booth_games(nfl_fixture_raw, key))})"


def test_booths_search_narrows_and_empty(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    nfl_fixture_raw: dict,  # type: ignore[type-arg]
) -> None:
    page = nfl_guarded_page
    _booths_app(page, open_nfl_app, "crews")
    _open(page, "booths")
    total = page.locator("#nfl-booth-results-pop li[role=option]:visible").count()
    assert total >= 2
    first_row = page.locator("#nfl-booth-results-pop li[role=option]").first
    analyst = first_row.locator(".option-name").last.inner_text()
    page.fill("#nfl-booth-search-pop", analyst)
    narrowed = page.locator("#nfl-booth-results-pop li[role=option]:visible").count()
    assert 1 <= narrowed < total or total == narrowed
    for text in page.locator("#nfl-booth-results-pop li[role=option]:visible").all_inner_texts():
        assert analyst.lower() in text.lower()
    page.fill("#nfl-booth-search-pop", "zzzz")
    assert page.locator("#nfl-pop-booths .helper", has_text="No booths match.").is_visible()
    assert page.locator("#nfl-booth-results-pop li[role=option]:visible").count() == 0


def test_booth_group_head_inset_and_only_on_hover(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    """Group heads line up with the rows, and Only shows on head hover at the counts' edge."""
    page = nfl_guarded_page
    _booths_app(page, open_nfl_app, "crews")
    _open(page, "booths")
    head = page.locator("#nfl-pop-booths .group-head").first
    row = page.locator("#nfl-booth-results-pop li[role=option]").first
    name_box = head.locator(".group-name").bounding_box()
    check_box = row.locator(".option-check").bounding_box()
    assert name_box and check_box
    assert abs(name_box["x"] - check_box["x"]) <= 1
    assert head.locator(".group-name").evaluate("e => getComputedStyle(e).fontWeight") == "600"
    only = head.locator(".only-btn")
    page.mouse.move(0, 0)
    assert only.evaluate("e => getComputedStyle(e).opacity") == "0"
    head.hover()
    page.wait_for_function(
        "() => getComputedStyle(document.querySelector('#nfl-pop-booths .group-head .only-btn')).opacity === '1'"
    )
    edge = only.evaluate(
        "e => { const r = document.createRange(); r.selectNodeContents(e); return r.getBoundingClientRect().right; }"
    )
    count_box = row.locator(".option-count").bounding_box()
    assert count_box
    assert abs(edge - (count_box["x"] + count_box["width"])) <= 1


def test_booths_only_all_url_and_reload(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _booths_app(page, open_nfl_app, "crews")
    _open(page, "booths")
    head = page.locator("#nfl-pop-booths .group-head").first
    expected = page.evaluate(
        """() => {
          const lis = [...document.querySelectorAll('#nfl-booth-results-pop > li')];
          const keys = [];
          for (const li of lis.slice(1)) {
            if (li.classList.contains('group-head')) break;
            keys.push(li.dataset.booth);
          }
          return keys;
        }"""
    )
    head.locator(".only-btn").click()
    page.wait_for_function("window.__nflTestHooks.getState().booths.length > 0")
    assert sorted(_state(page)["booths"]) == sorted(expected)
    assert head.locator(".only-btn").inner_text() == "All"
    assert "booths=" in _search(page)
    page.reload()
    page.wait_for_function("window.__nflTestHooks && window.__nflTestHooks.ready === true")
    assert sorted(_state(page)["booths"]) == sorted(expected)
    _open(page, "booths")
    page.locator("#nfl-pop-booths .group-head .only-btn").first.click()
    page.wait_for_function("window.__nflTestHooks.getState().booths.length === 0")
    assert "booths=" not in _search(page)


def test_booths_pick_lists_games_on_viewership(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    nfl_fixture_raw: dict,  # type: ignore[type-arg]
) -> None:
    page = nfl_guarded_page
    _booths_app(page, open_nfl_app, "viewership")
    _open(page, "booths")
    page.locator("#nfl-booth-results-pop li[role=option]").first.click()
    page.wait_for_function("window.__nflTestHooks.getState().booths.length === 1")
    key = _state(page)["booths"][0]
    expected = _booth_games(nfl_fixture_raw, key)
    assert expected
    assert sorted(page.evaluate("window.__nflTestHooks.getTableIndexes()")) == sorted(expected)
    assert page.locator("#nfl-booth-results-pop li[aria-selected=true]").count() >= 1


def test_clear_all_filters_clears_booths(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _booths_app(page, open_nfl_app, "crews")
    key = page.evaluate("window.__nflTestHooks.getBoothCatalog()[0].key")
    page.evaluate("k => window.__nflTestHooks.setState({ booths: [k] })", key)
    assert page.get_attribute("#nfl-trigger-booths", "data-active") == "true"
    page.click("#nfl-clear-filters")
    page.wait_for_function("window.__nflTestHooks.getState().booths.length === 0")
    assert page.get_attribute("#nfl-trigger-booths", "data-active") == "false"
    assert "booths=" not in _search(page)


def test_booths_arrows_move_between_rows(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _booths_app(page, open_nfl_app, "crews")
    _open(page, "booths")
    page.focus("#nfl-booth-search-pop")
    page.keyboard.press("ArrowDown")
    first = page.evaluate("document.activeElement.dataset.booth")
    assert first
    page.keyboard.press("ArrowDown")
    second = page.evaluate("document.activeElement.dataset.booth")
    assert second and second != first
    page.keyboard.press("ArrowUp")
    assert page.evaluate("document.activeElement.dataset.booth") == first


def test_mobile_sheet_has_booths_section(
    nfl_mobile_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_mobile_page
    _booths_app(page, open_nfl_app, "crews")
    page.click("#nfl-filters-button")
    page.wait_for_selector("#nfl-filters-sheet:popover-open")
    headings = page.locator("#nfl-filters-sheet .sheet-body h3:visible").all_inner_texts()
    assert "Booths" in headings
    page.locator("#nfl-booth-results-sheet li[role=option]").first.click()
    page.wait_for_function("window.__nflTestHooks.getState().booths.length === 1")
    assert "booths=" in _search(page)


def test_team_alone_fills_the_table_like_cfb_school(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    """Phase 8 parity audit: a Team alone lists its games, as CFB's School does (D-12)."""
    open_nfl_app(nfl_guarded_page, "?sport=nfl&view=scatter&team=f-lanterns")
    rows = nfl_guarded_page.locator("#nfl-matched-games tbody tr")
    assert rows.count() > 0
    # CFB parity: the network is a family-colored pill and the row is a click target.
    assert rows.first.locator("td .pill").count() >= 1
    assert "row-link" in (rows.first.get_attribute("class") or "")
    rows.first.locator("td").nth(1).click(position={"x": 2, "y": 2})
    nfl_guarded_page.wait_for_selector("#nfl-detail-panel[open]")


def _clear_state(page: Page, selector: str) -> dict[str, str | None]:
    result: dict[str, str | None] = page.evaluate(
        "(s) => { const el = document.querySelector(s); const cs = getComputedStyle(el); "
        "return { aria: el.getAttribute('aria-disabled'), border: cs.borderTopColor }; }",
        selector,
    )
    return result


def test_clear_all_filters_is_disabled_until_a_filter_changes(app: Page) -> None:
    idle = _clear_state(app, "#nfl-clear-filters")
    assert idle["aria"] == "true"
    assert idle["border"] != "rgb(35, 32, 27)"  # not --ink
    app.evaluate("window.__nflTestHooks.setState({ cats: ['agotw'] })")
    live = _clear_state(app, "#nfl-clear-filters")
    assert live["aria"] == "false"
    assert live["border"] == "rgb(35, 32, 27)"
    app.click("#nfl-clear-filters")
    app.wait_for_function(
        "document.getElementById('nfl-clear-filters').getAttribute('aria-disabled') === 'true'"
    )


def test_disabled_clear_all_filters_is_a_no_op(app: Page) -> None:
    """While aria-disabled, Clear all filters does not touch the state or re-render."""
    assert _clear_state(app, "#nfl-clear-filters")["aria"] == "true"
    before = app.evaluate("window.__nflTestHooks.renderCount")
    # Playwright refuses to click an aria-disabled button; a script click still fires.
    app.evaluate("document.getElementById('nfl-clear-filters').click()")
    app.wait_for_timeout(100)
    assert app.evaluate("window.__nflTestHooks.renderCount") == before


def test_phone_clear_all_filters_is_disabled_until_a_filter_changes(mobile: Page) -> None:
    sheet_clear = ".nfl-filters-sheet .nfl-sheet-clear"
    idle = _clear_state(mobile, sheet_clear)
    assert idle["aria"] == "true"
    assert idle["border"] != "rgb(35, 32, 27)"
    mobile.evaluate("window.__nflTestHooks.setState({ cats: ['agotw'] })")
    live = _clear_state(mobile, sheet_clear)
    assert live["aria"] == "false"
    assert live["border"] == "rgb(35, 32, 27)"
