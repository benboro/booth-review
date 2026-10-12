# ruff: noqa: E501, RUF001  (embedded JS lines and the UI copy's typographic characters)
"""999.5-14: NFL view 2, Fox crews (one-season dot chart with Raw/Adjusted).

Synthetic nfl-data fixture only; no vault rows. Expected values are recomputed
from the fixture's `fox_booths` block so the view is checked against the source.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, Route

pytestmark = pytest.mark.e2e

GD = "#nfl-view-fox .nfl-chart > div"
MINUS = "−"
FIELDS = {
    "margin": ("raw_mean_abs_margin", "adj_margin_resid", "adj_margin_se"),
    "excitement": ("raw_mean_excitement", "adj_excitement_resid", "adj_excitement_se"),
    "volatility": ("raw_mean_volatility", "adj_volatility_resid", "adj_volatility_se"),
}
RAW_TITLES = {
    "margin": "Mean final margin (points)",
    "excitement": "Mean GEI-style excitement",
    "volatility": "Mean WP volatility",
}
ADJ_TITLES = {
    "margin": "Final margin vs. expected for the matchup (points)",
    "excitement": "GEI-style excitement vs. expected for the matchup",
    "volatility": "WP volatility vs. expected for the matchup",
}


def _open(page: Page, open_nfl_app: Callable[..., None], query: str = "") -> None:
    open_nfl_app(page, "?sport=nfl&view=fox" + query)


def _vm(page: Page) -> dict[str, Any]:
    page.wait_for_function("window.__nflTestHooks.getViewModel('fox').drawn === true")
    return page.evaluate("window.__nflTestHooks.getViewModel('fox')")  # type: ignore[no-any-return]


def _set(page: Page, patch: dict[str, Any]) -> None:
    page.evaluate("p => window.__nflTestHooks.setState(p)", patch)


def _rows(raw: dict[str, Any], season: int) -> list[dict[str, Any]]:
    b = raw["fox_booths"]
    out = [{k: b[k][i] for k in b} for i in range(len(b["season"])) if b["season"][i] == season]
    order = {"lead": 0, "other": 1, "others_pooled": 2}
    return sorted(out, key=lambda r: (order[r["group"]], r["rank"] or 0))


def _name(raw: dict[str, Any], idx: int | None) -> str | None:
    return None if idx is None else raw["lookups"]["people"][idx]["name"]


def _booth(raw: dict[str, Any], r: dict[str, Any]) -> str:
    if r["group"] == "others_pooled":
        return "Others (pooled)"
    return " / ".join(
        n for n in (_name(raw, r["pbp_person"]), _name(raw, r["analyst_person"])) if n
    )


def _label(raw: dict[str, Any], r: dict[str, Any]) -> str:
    if r["group"] == "others_pooled":
        base = "Others (pooled)"
    else:
        role = "Lead" if r["group"] == "lead" else f"Fox #{r['rank']}"
        base = f"{role} · {_booth(raw, r)}"
    return base + (" (low n)" if r["low_n"] else "")


def _fmt(metric: str, x: float, signed: bool) -> str:
    s = f"{abs(x):.{1 if metric == 'margin' else 2}f}"
    if x < 0 and float(s) != 0:
        return MINUS + s
    return "+" + s if signed and x > 0 and float(s) != 0 else s


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _annotation(r: dict[str, Any]) -> str:
    return f"{_plural(r['games'], 'game', 'games')} · {r['fill_in_games']} fill-in"


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


# --------------------------------------------------------------- task 1


def test_default_season_rows_and_labels(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    default = nfl_fixture_raw["freshness"]["fox_default_season"]
    vm = _vm(nfl_guarded_page)
    assert vm["season"] == default
    assert "fseason" not in nfl_guarded_page.url
    expected = _rows(nfl_fixture_raw, default)
    assert [r["label"] for r in vm["rows"]] == [_label(nfl_fixture_raw, r) for r in expected]
    labels = [r["label"] for r in vm["rows"]]
    assert labels[0].startswith("Lead · ")
    assert labels[1].startswith("Fox #2 · ")
    assert labels[2].startswith("Fox #3 · ")
    assert labels[-1] == "Others (pooled)"
    ticks = nfl_guarded_page.evaluate(f"document.querySelector('{GD}').layout.yaxis.ticktext")
    assert ticks == labels
    reversed_ = nfl_guarded_page.evaluate(
        f"(() => {{ const r = document.querySelector('{GD}')._fullLayout.yaxis.range; return r[0] > r[1]; }})()"
    )
    assert reversed_ is True


def test_raw_has_no_whiskers_and_values_match(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app)
    vm = _vm(nfl_guarded_page)
    assert vm["hasWhiskers"] is False
    assert vm["axisTitle"] == "Mean final margin (points)"
    expected = _rows(nfl_fixture_raw, vm["season"])
    assert [r["x"] for r in vm["rows"]] == [r["raw_mean_abs_margin"] for r in expected]
    traces = nfl_guarded_page.evaluate(
        f"document.querySelector('{GD}').data.map(t => 'error_x' in t && t.error_x && t.error_x.visible === true)"
    )
    assert not any(traces)
    shapes = nfl_guarded_page.evaluate(f"document.querySelector('{GD}').layout.shapes.length")
    assert shapes == 0
    title = nfl_guarded_page.evaluate(f"document.querySelector('{GD}').layout.xaxis.title.text")
    assert title == "Mean final margin (points)"


def test_adjusted_whiskers_zero_line_and_titles(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app, "&adj=1")
    vm = _vm(nfl_guarded_page)
    assert vm["hasWhiskers"] is True
    assert vm["axisTitle"] == ADJ_TITLES["margin"]
    expected = _rows(nfl_fixture_raw, vm["season"])
    for got, want in zip(vm["rows"], expected, strict=True):
        assert got["x"] == want["adj_margin_resid"]
        assert got["err"] == pytest.approx(1.96 * want["adj_margin_se"])
    err = nfl_guarded_page.evaluate(
        f"document.querySelector('{GD}').data.find(t => t.error_x).error_x"
    )
    assert err["type"] == "data" and err["visible"] is True
    assert err["array"] == pytest.approx([1.96 * r["adj_margin_se"] for r in expected])
    assert nfl_guarded_page.evaluate(f"document.querySelector('{GD}').layout.shapes.length") == 1
    texts = nfl_guarded_page.evaluate(
        f"document.querySelector('{GD}').layout.annotations.map(a => a.text)"
    )
    assert "Closer than expected" in texts and "Wider than expected" in texts


@pytest.mark.parametrize(
    ("metric", "left", "right"),
    [
        ("excitement", "Less exciting than expected", "More exciting than expected"),
        ("volatility", "Less volatile than expected", "More volatile than expected"),
    ],
)
def test_metric_switch_titles_and_values(
    nfl_guarded_page: Page,
    open_nfl_app: Callable[..., None],
    nfl_fixture_raw: dict[str, Any],
    metric: str,
    left: str,
    right: str,
) -> None:
    _open(nfl_guarded_page, open_nfl_app, f"&m={metric}")
    vm = _vm(nfl_guarded_page)
    assert vm["metric"] == metric and vm["axisTitle"] == RAW_TITLES[metric]
    expected = _rows(nfl_fixture_raw, vm["season"])
    assert [r["x"] for r in vm["rows"]] == [r[FIELDS[metric][0]] for r in expected]
    _set(nfl_guarded_page, {"adjusted": True})
    nfl_guarded_page.wait_for_function(
        "window.__nflTestHooks.getViewModel('fox').adjusted === true"
    )
    vm = _vm(nfl_guarded_page)
    assert vm["axisTitle"] == ADJ_TITLES[metric]
    assert [r["x"] for r in vm["rows"]] == [r[FIELDS[metric][1]] for r in expected]
    texts = nfl_guarded_page.evaluate(
        f"document.querySelector('{GD}').layout.annotations.map(a => a.text)"
    )
    assert left in texts and right in texts


def test_controls_toggle_state_through_the_ui(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    values = page.locator("#nfl-view-fox [aria-label='Values']")
    metric = page.locator("#nfl-view-fox [aria-label='Metric']")
    assert values.get_by_role("button", name="Raw").get_attribute("aria-pressed") == "true"
    values.get_by_role("button", name="Adjusted").click()
    page.wait_for_function("window.__nflTestHooks.getViewModel('fox').adjusted === true")
    assert "adj=1" in page.url
    assert values.get_by_role("button", name="Adjusted").get_attribute("aria-pressed") == "true"
    metric.get_by_role("button", name="WP volatility").click()
    page.wait_for_function("window.__nflTestHooks.getViewModel('fox').metric === 'volatility'")
    assert "m=volatility" in page.url


def test_low_n_row_is_hollow_and_labeled(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    _open(nfl_guarded_page, open_nfl_app, "&fseason=2024")
    vm = _vm(nfl_guarded_page)
    low = [r for r in vm["rows"] if r["lowN"]]
    assert len(low) == 1 and low[0]["label"].endswith(" (low n)")
    marker = nfl_guarded_page.evaluate(
        f"document.querySelector('{GD}').data.find(t => t.name === 'Booths').marker"
    )
    k = [r["lowN"] for r in vm["rows"]].index(True)
    assert marker["color"][k] == "rgba(0,0,0,0)"
    assert marker["opacity"][k] == 0.5
    assert marker["line"]["width"][k] == 2
    others = [i for i in range(len(vm["rows"])) if i != k]
    assert all(marker["opacity"][i] == 1 for i in others)


def test_stepper_moves_one_season_and_disables_at_ends(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    default = vm["season"]
    seasons = sorted({s for s in nfl_fixture_raw["fox_booths"]["season"]}, reverse=True)
    assert seasons[0] == default
    prev = page.get_by_role("button", name="Previous season")
    nxt = page.get_by_role("button", name="Next season")
    sel = page.locator("#nfl-view-fox select[aria-label='Season']")
    assert [o for o in sel.locator("option").all_inner_texts()] == [str(s) for s in seasons]
    assert nxt.is_disabled() and prev.is_enabled()
    prev.click()
    page.wait_for_function(f"window.__nflTestHooks.getViewModel('fox').season === {seasons[1]}")
    assert f"fseason={seasons[1]}" in page.url
    assert prev.is_disabled() and nxt.is_enabled()
    nxt.click()
    page.wait_for_function(f"window.__nflTestHooks.getViewModel('fox').season === {default}")
    assert "fseason" not in page.url
    sel.select_option(str(seasons[1]))
    page.wait_for_function(f"window.__nflTestHooks.getViewModel('fox').season === {seasons[1]}")
    # Seasons are never pooled: only that season's rows are drawn.
    got = _vm(page)["rows"]
    assert len(got) == len(_rows(nfl_fixture_raw, seasons[1]))


def test_seasons_filter_narrows_and_clamps_the_stepper(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    _set(page, {"seasons": [2024, 2024]})
    page.wait_for_function("window.__nflTestHooks.getViewModel('fox').season === 2024")
    sel = page.locator("#nfl-view-fox select[aria-label='Season']")
    assert sel.locator("option").all_inner_texts() == ["2024"]
    assert page.get_by_role("button", name="Previous season").is_disabled()
    assert page.get_by_role("button", name="Next season").is_disabled()


def test_view_text_never_names_the_spread(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app, "&adj=1")
    _vm(page)
    _emit(page, "plotly_hover", 0)
    tip = _tooltip(page)
    assert not any("spread" in t.lower() for t in tip)
    view_text = page.evaluate("document.getElementById('nfl-view-fox').textContent")
    hidden_titles = page.evaluate(
        f"JSON.stringify(document.querySelector('{GD}').layout) + JSON.stringify(document.querySelector('{GD}').data.map(t => t.name))"
    )
    # The methodology anchor is an href, not visible text.
    assert "spread" not in view_text.lower()
    assert "spread" not in hidden_titles.lower()


def test_plotly_renders_without_console_errors(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    _open(page, open_nfl_app, "&adj=1")
    _vm(page)
    assert page.locator(f"{GD} .errorbar").count() > 0
    assert errors == []


# --------------------------------------------------------------- task 2


def test_raw_hover_lines_exact(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    want = _rows(nfl_fixture_raw, vm["season"])[0]
    _emit(page, "plotly_hover", 0)
    assert _tooltip(page) == [
        _booth(nfl_fixture_raw, want),
        str(vm["season"]),
        f"Mean final margin: {_fmt('margin', want['raw_mean_abs_margin'], False)} points",
        _annotation(want),
        "Click to list games.",
    ]


def test_adjusted_hover_lines_with_minus_and_low_n(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app, "&adj=1")
    vm = _vm(page)
    rows = _rows(nfl_fixture_raw, vm["season"])
    k = next(i for i, r in enumerate(rows) if r["adj_margin_resid"] < 0)
    r = rows[k]
    half = 1.96 * r["adj_margin_se"]
    x = r["adj_margin_resid"]
    _emit(page, "plotly_hover", k)
    tip = _tooltip(page)
    assert tip == [
        _booth(nfl_fixture_raw, r),
        str(vm["season"]),
        f"Final margin vs. expected: {MINUS}{abs(x):.1f} points",
        f"±1.96 standard errors: {_fmt('margin', x - half, False)} to {_fmt('margin', x + half, False)}",
        _annotation(r),
        "Click to list games.",
    ]
    assert MINUS in tip[2]
    # A low-n row adds the threshold line, from the data.
    _set(page, {"fseason": 2024})
    page.wait_for_function("window.__nflTestHooks.getViewModel('fox').season === 2024")
    vm = _vm(page)
    k = [row["lowN"] for row in vm["rows"]].index(True)
    _emit(page, "plotly_hover", k)
    n = nfl_fixture_raw["constants"]["low_n_threshold"]
    assert f"Fewer than {n} games. Read with care." in _tooltip(page)


def test_click_row_fills_games_table_and_rings(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    lead = _rows(nfl_fixture_raw, vm["season"])[0]
    _emit(page, "plotly_click", 0)
    page.wait_for_function("window.__nflTestHooks.getViewModel('fox').rows[0].ring === true")
    got = page.evaluate("window.__nflTestHooks.getTableIndexes()")
    assert sorted(got) == sorted(lead["game_list"]) and len(got) == len(lead["game_list"])
    # Clicking the same row again clears the selection.
    page.wait_for_timeout(600)
    _emit(page, "plotly_click", 0)
    page.wait_for_function("window.__nflTestHooks.getViewModel('fox').rows[0].ring === false")
    assert page.evaluate("window.__nflTestHooks.getTableIndexes()") == []


def test_captions_and_links(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    caps = page.locator("#nfl-view-fox .nfl-captions")
    text = caps.inner_text()
    n = nfl_fixture_raw["constants"]["low_n_threshold"]
    assert "One season at a time. Seasons are not pooled." in text
    assert "Whiskers" not in text
    assert "Raw means. No error bars. Use Adjusted to compare booths." in text
    assert f"Hollow dots have fewer than {n} games." in text
    hrefs = caps.locator("a").evaluate_all("els => els.map(a => a.getAttribute('href'))")
    for anchor in (
        "nfl-fox-crews-and-the-lead-booth",
        "nfl-the-spread-adjustment",
        "nfl-low-n",
    ):
        assert any(h.endswith("#" + anchor) for h in hrefs)
    _set(page, {"adjusted": True})
    page.wait_for_function("window.__nflTestHooks.getViewModel('fox').adjusted === true")
    text = caps.inner_text()
    assert "Whiskers show ±1.96 standard errors." in text
    assert "Raw means" not in text
    assert "spread" not in text.lower()


def test_selected_announcer_rings_their_row(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    assert not any(r["ring"] for r in vm["rows"])
    rows = _rows(nfl_fixture_raw, vm["season"])
    person = rows[1]["pbp_person"]
    pid = nfl_fixture_raw["lookups"]["people"][person]["id"]
    _set(page, {"people": [pid]})
    page.wait_for_function("window.__nflTestHooks.getViewModel('fox').rows.some(r => r.ring)")
    ringed = [r["label"] for r in _vm(page)["rows"] if r["ring"]]
    holders = [
        _label(nfl_fixture_raw, r) for r in rows if person in (r["pbp_person"], r["analyst_person"])
    ]
    assert ringed == holders


def _no_fox_rows(route: Route) -> None:
    resp = route.fetch()
    raw = json.loads(resp.text())
    for col in raw["fox_booths"]:
        raw["fox_booths"][col] = []
    route.fulfill(response=resp, body=json.dumps(raw))


def test_season_without_rows_shows_the_empty_note(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    page.route("**/nfl-data.json", _no_fox_rows)
    _open(page, open_nfl_app)
    note = page.locator("#nfl-view-fox .season-empty-note")
    note.wait_for(state="visible")
    assert note.locator(".season-empty-title").inner_text() == "No Fox booth data for 2025."
    assert (
        note.locator(".season-empty-hint").inner_text() == "Pick another season with the stepper."
    )
    assert page.evaluate("window.__nflTestHooks.getViewModel('fox').drawn") is False


def test_hidden_table_has_one_row_per_booth(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    assert page.locator("#nfl-view-fox .visually-hidden tbody tr").count() == len(vm["rows"])
    # The wrapper, not the table, is visually hidden (no mobile overflow).
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_mobile_tap_selects_row_without_hover(
    nfl_mobile_page: Page, open_nfl_app: Callable[..., None], nfl_fixture_raw: dict[str, Any]
) -> None:
    page = nfl_mobile_page
    _open(page, open_nfl_app)
    vm = _vm(page)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    ticks = page.evaluate(f"document.querySelector('{GD}').layout.yaxis.ticktext")
    want = _rows(nfl_fixture_raw, vm["season"])[0]
    assert ticks[0].endswith(_annotation(want)) and "<br>" in ticks[0]
    _emit(page, "plotly_hover", 0)
    assert page.evaluate("document.getElementById('chart-tooltip')?.hidden ?? true") is True
    _emit(page, "plotly_click", 0)
    page.wait_for_function("window.__nflTestHooks.getViewModel('fox').rows[0].ring === true")


def _long_names(route: Route) -> None:
    resp = route.fetch()
    raw = json.loads(resp.text())
    for k, person in enumerate(raw["lookups"]["people"]):
        person["name"] = f"Longname-Surname{k:02d}"
    route.fulfill(response=resp, body=json.dumps(raw))


def test_long_labels_and_annotations_not_clipped_on_desktop(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    page = nfl_guarded_page
    page.set_viewport_size({"width": 1280, "height": 900})
    page.route("**/nfl-data.json", _long_names)
    _open(page, open_nfl_app)
    _vm(page)
    boxes = page.evaluate(
        """() => {
          const gd = document.querySelector('#nfl-view-fox .nfl-chart > div');
          const c = gd.getBoundingClientRect();
          const pick = (sel) => [...gd.querySelectorAll(sel)].map((n) => {
            const b = n.getBoundingClientRect();
            return { text: n.textContent, left: b.left - c.left, right: c.right - b.right };
          });
          return { ticks: pick('.yaxislayer-above .ytick text'), notes: pick('.annotation-text') };
        }"""
    )
    assert boxes["ticks"] and boxes["notes"]
    for b in boxes["ticks"] + boxes["notes"]:
        assert b["left"] >= -0.5, b
        assert b["right"] >= -0.5, b
    assert not any("…" in b["text"] for b in boxes["ticks"])
    assert any("fill-in" in b["text"] for b in boxes["notes"])


def test_keyboard_picks_a_booth_from_the_visible_on_focus_table(
    nfl_guarded_page: Page, open_nfl_app: Callable[..., None]
) -> None:
    """JS-WR-04: the data table shows while focused, and Enter keeps focus on the row."""
    page = nfl_guarded_page
    _open(page, open_nfl_app)
    _vm(page)
    wrap = page.locator("#nfl-view-fox div.nfl-data-table")
    first = wrap.locator("tbody button").first
    key = first.get_attribute("data-key")
    first.focus()
    box = wrap.bounding_box()
    assert box is not None and box["width"] > 100
    page.keyboard.press("Enter")
    page.wait_for_function("window.__nflTestHooks.getState().selection !== null")
    sel = page.evaluate("window.__nflTestHooks.getState().selection")
    assert sel["kind"] == "booth" and str(sel["key"]) == key
    assert page.evaluate("document.activeElement.dataset.key") == key
