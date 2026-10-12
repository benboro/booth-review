"""Phase 8 plan 09: the NFL Viewership tab (category lines, legend, residuals, booth highlight).

Synthetic nfl-data fixture only; no vault rows. Expected values are recomputed
from the fixture's `viewership` block so the view is checked against the source.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

VIEW = "#nfl-view-viewership"
GD = f"{VIEW} .nfl-chart > div"
CHIPS = f"{VIEW} .legend-chips button[data-category]"

_CLICKS = """
([cat, details]) => {
  for (const detail of details) {
    const b = document.querySelector(
      `#nfl-view-viewership .legend-chips button[data-category='${cat}']`);
    b.dispatchEvent(new MouseEvent('click', {bubbles: true, detail}));
  }
}
"""


def _open(page: Page, open_nfl_app: Callable[..., None], query: str = "") -> None:
    open_nfl_app(page, "?sport=nfl&view=viewership" + query)
    page.wait_for_function("window.__nflTestHooks.getViewModel('viewership') !== null")


def _vm(page: Page) -> dict[str, Any]:
    page.wait_for_function("window.__nflTestHooks.getViewModel('viewership').drawn === true")
    return page.evaluate("window.__nflTestHooks.getViewModel('viewership')")  # type: ignore[no-any-return]


def _set(page: Page, patch: dict[str, Any]) -> None:
    page.evaluate("p => window.__nflTestHooks.setState(p)", patch)


def _state(page: Page) -> dict[str, Any]:
    return page.evaluate("window.__nflTestHooks.getState()")  # type: ignore[no-any-return]


def _cats(raw: dict[str, Any]) -> list[dict[str, Any]]:
    return raw["lookups"]["view_categories"]  # type: ignore[no-any-return]


def _points(raw: dict[str, Any], ci: int) -> list[int]:
    v = raw["viewership"]
    return [k for k in range(len(v["season"])) if v["category"][k] == ci]


def _present_ids(raw: dict[str, Any]) -> list[str]:
    cats = _cats(raw)
    return [c["id"] for ci, c in enumerate(cats) if _points(raw, ci)]


def _shown(page: Page) -> list[str]:
    return page.eval_on_selector_all(  # type: ignore[no-any-return]
        CHIPS,
        "els => els.filter(e => e.getAttribute('aria-pressed') === 'true')"
        ".map(e => e.dataset.category)",
    )


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


def _k_of(vm: dict[str, Any], cat: str, season: int) -> int:
    k = 0
    for c in vm["categories"]:
        for p in c["points"]:
            if c["id"] == cat and p["season"] == season:
                return k
            k += 1
    raise AssertionError((cat, season))


def _trace(page: Page, name: str) -> dict[str, Any]:
    return page.evaluate(  # type: ignore[no-any-return]
        """([sel, name]) => {
          const t = document.querySelector(sel).data.find(d => d.name === name);
          return { dash: t.line.dash || null, symbol: t.marker.symbol, y: t.y,
                   opacity: t.marker.opacity, error: t.error_y ? t.error_y.array : null };
        }""",
        [GD, name],
    )


def _double(page: Page, cat: str) -> None:
    page.evaluate(_CLICKS, [cat, [1, 2]])


# ------------------------------------------------------------------ lines


def test_one_line_per_category_in_range(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    cats = _cats(nfl_fixture_raw)
    v = nfl_fixture_raw["viewership"]
    ids = _present_ids(nfl_fixture_raw)
    assert sorted(c["id"] for c in vm["categories"]) == sorted(ids)
    # The Fox AGOTW line is drawn last (on top).
    assert vm["categories"][-1]["id"] == "agotw"
    for c in vm["categories"]:
        ci = next(i for i, x in enumerate(cats) if x["id"] == c["id"])
        ks = _points(nfl_fixture_raw, ci)
        assert [p["season"] for p in c["points"]] == [v["season"][k] for k in ks]
        assert [p["y"] for p in c["points"]] == [v["mean_viewers"][k] for k in ks]
    assert page.locator(CHIPS).count() == len(ids)
    assert vm["bands"]


def test_window_level_lines_dashed_and_labeled(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    assert _trace(page, "Fox AGOTW")["dash"] == "dash"
    assert _trace(page, "CBS late national")["dash"] == "dash"
    assert _trace(page, "SNF")["dash"] is None
    for cat in ("agotw", "cbs_national"):
        assert "window-level" in (
            page.locator(f"{CHIPS}[data-category={cat}]").get_attribute("title") or ""
        )
    assert "window-level" not in (
        page.locator(f"{CHIPS}[data-category=snf]").get_attribute("title") or ""
    )
    assert "Dashed lines are window-level" in page.locator(f"{VIEW} .nfl-captions").inner_text()


def test_era_note_links_methodology(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    link = page.locator(f"{VIEW} .nfl-captions a", has_text="methodology")
    assert (link.get_attribute("href") or "").endswith("methodology.html#measurement-eras")


def test_residual_mode_whiskers_caption_and_gap(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    assert "Residuals compare" not in page.locator(f"{VIEW} .nfl-captions").inner_text()
    page.locator(f"{VIEW} .segmented button", has_text="Residual given game quality").click()
    page.wait_for_function("window.__nflTestHooks.getViewModel('viewership').viewY === 'resid'")
    vm = _vm(page)
    assert (
        "Residuals compare seasons within one category, not categories with each other."
        in page.locator(f"{VIEW} .nfl-captions").inner_text()
    )
    assert _state(page)["viewY"] == "resid"
    cats = _cats(nfl_fixture_raw)
    v = nfl_fixture_raw["viewership"]
    agotw = next(c for c in vm["categories"] if c["id"] == "agotw")
    ks = _points(nfl_fixture_raw, 0)
    assert [p["y"] for p in agotw["points"]] == [v["viewership_resid"][k] for k in ks]
    assert agotw["points"][0]["err"] == pytest.approx(1.96 * v["viewership_se"][ks[0]])
    # Null residual stays a gap, never 0, with no whisker.
    ci = next(i for i, c in enumerate(cats) if c["id"] == "christmas")
    xmas = next(c for c in vm["categories"] if c["id"] == "christmas")
    assert any(v["viewership_resid"][k] is None for k in _points(nfl_fixture_raw, ci))
    nulls = [p for p in xmas["points"] if p["y"] is None]
    assert nulls and all(p["err"] is None for p in nulls)
    tr = _trace(page, "Christmas")
    assert None in tr["y"] and 0 not in tr["y"]
    assert tr["error"] is not None


def test_low_n_hollow_and_hover_says_low_n(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    agotw = next(c for c in vm["categories"] if c["id"] == "agotw")
    low = next(p for p in agotw["points"] if p["lowN"])
    assert any(not p["lowN"] for p in agotw["points"])
    tr = _trace(page, "Fox AGOTW")
    idx = [p["season"] for p in agotw["points"]].index(low["season"])
    assert tr["symbol"][idx].endswith("-open")
    assert any(not sym.endswith("-open") for sym in tr["symbol"])
    _emit(page, "plotly_hover", _k_of(vm, "agotw", low["season"]))
    lines = _tooltip(page)
    assert "Fox AGOTW · window-level" in lines[0]
    assert any("low n: Few games, so treat with care." in t for t in lines)


def test_hover_lists_crews(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    v = nfl_fixture_raw["viewership"]
    g = nfl_fixture_raw["games"]
    people = nfl_fixture_raw["lookups"]["people"]
    k0 = _points(nfl_fixture_raw, 0)[1]  # Fox AGOTW 2025, five games
    counts: dict[str, int] = {}
    for gi in v["game_list"][k0]:
        crew = g["crew"][gi] or []
        pbp = next((m for m in crew if m["role"] == "pbp"), None)
        an = next((m for m in crew if m["role"] == "analyst"), None)
        label = " / ".join(people[m["person"]]["name"] for m in (pbp, an) if m)
        if label:
            counts[label] = counts.get(label, 0) + 1
    labels = sorted(counts, key=lambda s: (-counts[s], s))
    _emit(page, "plotly_hover", _k_of(vm, "agotw", v["season"][k0]))
    lines = _tooltip(page)
    assert "Crews:" in lines
    shown = lines[lines.index("Crews:") + 1 :]
    for label in labels[:3]:
        assert label in shown
    if len(labels) > 3:
        assert f"and {len(labels) - 3} more" in shown
    else:
        assert not any(t.startswith("and ") for t in shown)


# ------------------------------------------------------------------ legend and picker


def test_chip_click_toggles_and_picker_in_sync(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    ids = _present_ids(nfl_fixture_raw)
    page.locator(f"{CHIPS}[data-category=snf]").click()
    page.wait_for_function("window.__nflTestHooks.getState().hiddenCategories.includes('snf')")
    assert "snf" not in _shown(page)
    vm = _vm(page)
    assert "snf" not in [c["id"] for c in vm["categories"]]
    page.locator(f"{VIEW} .filter-trigger").click()
    box = page.locator(f"{VIEW} .nfl-viewership-picklist input[value=snf]")
    assert not box.is_checked()
    # Picker unchecks another, chips follow.
    page.locator(f"{VIEW} .nfl-viewership-picklist input[value=mnf]").uncheck()
    page.wait_for_function("window.__nflTestHooks.getState().hiddenCategories.includes('mnf')")
    assert "mnf" not in _shown(page)
    box.check()
    page.wait_for_function("!window.__nflTestHooks.getState().hiddenCategories.includes('snf')")
    assert sorted(_shown(page)) == sorted(i for i in ids if i != "mnf")
    page.locator(f"{VIEW} .nfl-viewership-popover .group-reset").click()
    page.wait_for_function("window.__nflTestHooks.getState().hiddenCategories.length === 0")
    assert sorted(_shown(page)) == sorted(ids)


def test_picker_search_and_only(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    page.locator(f"{VIEW} .filter-trigger").click()
    page.locator(f"{VIEW} .nfl-viewership-popover input[type=search]").fill("zzz")
    assert page.locator(f"{VIEW} .nfl-viewership-popover .helper").is_visible()
    page.locator(f"{VIEW} .nfl-viewership-popover input[type=search]").fill("thanks")
    rows = page.locator(f"{VIEW} .nfl-viewership-picklist .check-item:visible")
    assert rows.count() == 1
    rows.first.locator(".only-btn").click()
    page.wait_for_function(
        "window.__nflTestHooks.getViewModel('viewership').categories.length === 1"
    )
    assert _shown(page) == ["thanksgiving"]
    assert rows.first.locator(".only-btn").inner_text() == "All"
    rows.first.locator(".only-btn").click()
    page.wait_for_function("window.__nflTestHooks.getState().hiddenCategories.length === 0")
    assert sorted(_shown(page)) == sorted(_present_ids(nfl_fixture_raw))


def test_double_click_shows_only_then_restores(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    ids = _present_ids(nfl_fixture_raw)
    _double(page, "snf")
    page.wait_for_function(
        "window.__nflTestHooks.getViewModel('viewership').categories.length === 1"
    )
    assert _shown(page) == ["snf"]
    assert "show all" in (page.locator(f"{CHIPS}[data-category=snf]").get_attribute("title") or "")
    _double(page, "snf")
    page.wait_for_function("window.__nflTestHooks.getState().hiddenCategories.length === 0")
    assert sorted(_shown(page)) == sorted(ids)


def test_keyboard_enter_never_triggers_only(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    chip = page.locator(f"{CHIPS}[data-category=snf]")
    chip.focus()
    page.keyboard.press("Enter")
    page.wait_for_function("window.__nflTestHooks.getState().hiddenCategories.includes('snf')")
    page.locator(f"{CHIPS}[data-category=snf]").focus()
    page.keyboard.press("Enter")
    page.wait_for_function("window.__nflTestHooks.getState().hiddenCategories.length === 0")
    assert sorted(_shown(page)) == sorted(_present_ids(nfl_fixture_raw))


def test_all_hidden_shows_empty_state(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    _set(page, {"hiddenCategories": _present_ids(nfl_fixture_raw)})
    note = page.locator(f"{VIEW} .season-empty-note")
    note.wait_for(state="visible")
    assert "No categories shown." in note.inner_text()
    assert "Turn on a category above." in note.inner_text()


# ------------------------------------------------------------------ click, note, booths


def test_point_click_fills_games_table(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    v = nfl_fixture_raw["viewership"]
    k0 = _points(nfl_fixture_raw, 0)[1]
    _emit(page, "plotly_click", _k_of(vm, "agotw", v["season"][k0]))
    page.wait_for_function("window.__nflTestHooks.getState().selection !== null")
    assert sorted(page.evaluate("window.__nflTestHooks.getTableIndexes()")) == sorted(
        v["game_list"][k0]
    )


def test_info_note_opens_and_closes_on_escape(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    btn = page.locator(f"{VIEW} .band-info")
    assert btn.get_attribute("aria-label") == "About these lines"
    note = page.locator(f"{VIEW} .band-note")
    assert note.is_hidden()
    btn.click()
    assert note.is_visible()
    assert "Window-level figure." in note.inner_text()
    assert "Lines with few games are faded and marked low n." in note.inner_text()
    page.keyboard.press("Escape")
    assert note.is_hidden()


def test_booth_highlight_keeps_values(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    before = _vm(page)
    assert all(not p["highlighted"] for c in before["categories"] for p in c["points"])
    key = page.evaluate("window.__nflTestHooks.getBoothCatalog()[0].key")
    _set(page, {"booths": [key]})
    page.wait_for_function(
        "window.__nflTestHooks.getViewModel('viewership').categories"
        ".some(c => c.points.some(p => p.highlighted))"
    )
    after = _vm(page)
    for b, a in zip(before["categories"], after["categories"], strict=True):
        assert [p["y"] for p in b["points"]] == [p["y"] for p in a["points"]]
        assert [p["season"] for p in b["points"]] == [p["season"] for p in a["points"]]
    assert any(p["highlighted"] for c in after["categories"] for p in c["points"])
    tr = _trace(page, "Fox AGOTW")
    assert set(tr["opacity"]) <= {1, 0.15}


def test_no_console_errors(nfl_guarded_page: Page, open_nfl_app: Callable[..., None]) -> None:
    page = nfl_guarded_page
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    _open(page, open_nfl_app)
    _vm(page)
    page.locator(f"{VIEW} .segmented button", has_text="Residual").click()
    _vm(page)
    assert errors == []
