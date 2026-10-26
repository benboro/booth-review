"""In-browser proof of the This weekend render (Phase 18, plan 09): the desktop timeline, its
cells, picks, control row, Now line and roving focus, then the Time TBA strip, the ESPN+ table,
the stamp and source lines and the empty states, then the phone list. The render modules
(`site/modules/weekend-view.js`, `weekend-list.js`) are mounted into a fresh div on the served
app page from synthetic WeekendGame literals built here, so the tests need no fixture data
beyond a served page and never touch vault data.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

SAT = "2026-10-31"
FRI = "2026-10-30"
# Saturday noon ET, before every kickoff in these tests unless a test sets its own clock.
NOW_MORNING = "2026-10-31T09:00:00-04:00"

_MOUNT = """async (arg) => {
  const V = await import('./modules/weekend-view.js');
  const L = arg.kind === 'list' ? await import('./modules/weekend-list.js') : null;
  document.documentElement.dataset.theme = arg.theme;
  const old = document.getElementById('wk-host');
  if (old) old.remove();
  const host = document.createElement('div');
  host.id = 'wk-host';
  if (arg.hostWidth) host.style.width = arg.hostWidth + 'px';
  document.body.append(host);
  const picked = arg.pass ? new Set(arg.pass) : null;
  const nets = arg.nets ? new Set(arg.nets) : null;
  window.__wk = { opened: [], days: [], weeks: [] };
  const opts = {
    width: arg.width,
    now: arg.liveClock ? () => new Date() : new Date(arg.now),
    passes: (g) => (picked ? picked.has(g.key) : null),
    networksPicked: (id) => (nets ? nets.has(id) : null),
    onDay: (d) => window.__wk.days.push(d),
    onWeek: (d) => window.__wk.weeks.push(d),
    onOpen: (g) => window.__wk.opened.push(g.key),
  };
  const weeks = [8, 9, 10].map((n) => ({ label: 'Week ' + n, number: n }));
  const model = Object.assign({
    sport: 'cfb', weekLabel: 'Week 9', weekNumber: 9, weeks, isLatestWeek: false,
    games: arg.games, day: arg.day, past: false, missing: false, freshness: null, links: {},
  }, arg.model || {});
  const fn = arg.kind === 'list' ? L.renderWeekendList : V.renderWeekend;
  window.__wk.inst = fn(host, model, opts);
  return true;
}"""


def _game(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "key": "g",
        "sport": "cfb",
        "block": "scheduled",
        "index": 0,
        "date": SAT,
        "kickoffMin": 720,
        "networkId": "fox",
        "networkName": "FOX",
        "family": "fox",
        "away": "Away",
        "home": "Home",
        "awayRank": None,
        "homeRank": None,
        "neutral": False,
        "pbp": None,
        "analyst": None,
        "boothRank": None,
        "lead": False,
        "crewKnown": False,
        "past": False,
    }
    base.update(kw)
    return base


def _known(**kw: Any) -> dict[str, Any]:
    base = {"pbp": "Joe Fowler", "analyst": "Pat Herbstreit", "crewKnown": True}
    base.update(kw)
    return _game(**base)


@pytest.fixture
def wk_page(guarded_page: Page, open_app: Callable[[Page, str], None]) -> Page:
    guarded_page.set_viewport_size({"width": 1440, "height": 900})
    open_app(guarded_page, "")
    return guarded_page


def _mount(
    page: Page,
    games: list[dict[str, Any]],
    *,
    theme: str = "light",
    width: int = 1440,
    now: str = NOW_MORNING,
    day: str | None = SAT,
    pass_keys: list[str] | None = None,
    nets: list[str] | None = None,
    model: dict[str, Any] | None = None,
    kind: str = "grid",
    host_width: int | None = None,
    live_clock: bool = False,
) -> None:
    page.evaluate(
        _MOUNT,
        {
            "games": games,
            "theme": theme,
            "width": width,
            "now": now,
            "day": day,
            "pass": pass_keys,
            "nets": nets,
            "model": model,
            "kind": kind,
            "hostWidth": host_width,
            "liveClock": live_clock,
        },
    )


def _cell(key: str) -> str:
    return f'#wk-host [data-wk-id="g:{key}"]'


def _palette(page: Page, theme: str, family: str) -> dict[str, str]:
    return page.evaluate(  # type: ignore[no-any-return]
        """async ([theme, family]) => {
          const P = await import('./modules/palette.js');
          const W = await import('./modules/weekend.js');
          const rgb = (hex) => {
            const n = parseInt(hex.slice(1), 16);
            return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
          };
          return {
            solid: rgb(P.FAMILY_COLORS[theme][family]),
            known: rgb(W.cellColors(family, theme, 'known').bg),
            tint: rgb(P.mixHex(P.FAMILY_COLORS[theme][family], P.PAGE_BG[theme], 0.18)),
            ink: rgb(P.INK[theme]),
          };
        }""",
        [theme, family],
    )


def _style(page: Page, selector: str, prop: str) -> str:
    return page.evaluate(  # type: ignore[no-any-return]
        "([s, p]) => getComputedStyle(document.querySelector(s))[p]", [selector, prop]
    )


# -- Task 1: grid -------------------------------------------------------------------------


def test_fox_stack_rows_heights_and_two_lines(wk_page: Page) -> None:
    games = [
        _known(key="a", boothRank=2, home="Alpha"),
        _known(key="b", boothRank=1, home="Bravo"),
        _known(key="c", home="Charlie"),
    ]
    _mount(wk_page, games)
    assert wk_page.locator("#wk-host .wk-row").count() == 1
    assert wk_page.evaluate("document.querySelector('#wk-host .wk-lane').offsetHeight") == 140
    for key in "abc":
        box = wk_page.locator(_cell(key)).bounding_box()
        assert box is not None
        assert box["height"] == 44
        assert wk_page.locator(f"{_cell(key)} .wk-line").count() == 2
    top = {k: wk_page.evaluate(f"document.querySelector('{_cell(k)}').offsetTop") for k in "abc"}
    assert top["b"] == 0
    assert top["a"] == 48
    assert top["c"] == 96


def test_axis_corner_ticks_and_cell_widths(wk_page: Page) -> None:
    _mount(wk_page, [_known(key="a"), _known(key="b", kickoffMin=930, home="Other")])
    assert wk_page.locator("#wk-host .wk-corner").inner_text() == "All times ET"
    ticks = wk_page.locator("#wk-host .wk-tick").all_inner_texts()
    assert ticks[:3] == ["12 pm", "1 pm", "2 pm"]
    pxh = float(
        wk_page.evaluate(
            "getComputedStyle(document.querySelector('#wk-host .wk-grid'))"
            ".getPropertyValue('--wk-pxh')"
        ).replace("px", "")
    )
    assert 80 <= pxh <= 120
    width = wk_page.evaluate(f"document.querySelector('{_cell('a')}').offsetWidth")
    assert width == round(210 * pxh / 60) - 2
    left_a = wk_page.evaluate(f"document.querySelector('{_cell('a')}').offsetLeft")
    left_b = wk_page.evaluate(f"document.querySelector('{_cell('b')}').offsetLeft")
    assert left_b - left_a == round(210 * pxh / 60)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_cell_colors_known_and_tba(wk_page: Page, theme: str) -> None:
    games = [
        _known(key="k", lead=True, boothRank=1, home="Known"),
        _game(key="t", home="Tba", boothRank=2),
    ]
    _mount(wk_page, games, theme=theme)
    pal = _palette(wk_page, theme, "fox")
    # Known fills are the family colour deepened for white text (user sign-off 2026-10-26).
    assert _style(wk_page, _cell("k"), "backgroundColor") == pal["known"]
    assert pal["known"] != pal["solid"]
    assert _style(wk_page, _cell("k"), "color") == "rgb(255, 255, 255)"
    assert _style(wk_page, _cell("t"), "backgroundColor") == pal["tint"]
    assert _style(wk_page, _cell("t"), "color") == pal["ink"]
    assert pal["solid"] in _style(wk_page, _cell("t"), "backgroundImage")
    assert "linear-gradient" not in _style(wk_page, _cell("k"), "backgroundImage")
    assert wk_page.locator(f"{_cell('t')} .wk-booth").inner_text() == "Crew TBA"
    assert _style(wk_page, f"{_cell('t')} .wk-booth", "fontWeight") == "400"
    assert _style(wk_page, f"{_cell('k')} .wk-booth", "fontWeight") == "600"
    # The lead star: aria-hidden glyph, accessible name carries "Lead booth".
    star = wk_page.locator(f"{_cell('k')} .wk-star")
    assert star.count() == 1
    assert star.get_attribute("aria-hidden") == "true"
    assert "Lead booth" in (wk_page.locator(_cell("k")).get_attribute("aria-label") or "")
    assert wk_page.locator(f"{_cell('t')} .wk-star").count() == 0


def test_cell_text_ranks_neutral_and_names(wk_page: Page) -> None:
    games = [
        _known(key="a", awayRank=20, homeRank=5, away="Florida", home="Georgia", lead=True),
        _known(key="n", neutral=True, away="Utah", home="Texas", kickoffMin=930),
        _game(key="p", pbp="Joe Fowler", home="Partial", kickoffMin=1140, crewKnown=True),
    ]
    _mount(wk_page, games)
    assert wk_page.locator(f"{_cell('a')} .wk-match").inner_text() == "#20 Florida @ #5 Georgia"
    assert wk_page.locator(f"{_cell('n')} .wk-match").inner_text() == "Utah vs Texas"
    assert wk_page.locator(f"{_cell('a')} .wk-time").inner_text() == "12:00"
    assert wk_page.locator(f"{_cell('a')} .wk-booth").inner_text() == "Fowler · Herbstreit"
    assert wk_page.locator(f"{_cell('p')} .wk-booth").inner_text() == "Fowler · Analyst TBA"
    label = wk_page.locator(_cell("a")).get_attribute("aria-label")
    assert label == ("12:00 pm, #20 Florida at #5 Georgia, FOX. Lead booth. Fowler and Herbstreit.")


def test_picks_fade_and_ring_without_shifting_layout(wk_page: Page) -> None:
    games = [_known(key="a", boothRank=1), _known(key="b", home="B"), _known(key="c", home="C")]
    _mount(wk_page, games)
    before = wk_page.evaluate("document.querySelector('#wk-host .wk-grid').offsetHeight")
    rects = [wk_page.locator(_cell(k)).bounding_box() for k in "abc"]
    _mount(wk_page, games, pass_keys=["a"])
    after = wk_page.evaluate("document.querySelector('#wk-host .wk-grid').offsetHeight")
    assert before == after
    assert [wk_page.locator(_cell(k)).bounding_box() for k in "abc"] == rects
    assert _style(wk_page, _cell("b"), "opacity") == "0.3"
    assert _style(wk_page, _cell("c"), "opacity") == "0.3"
    assert _style(wk_page, _cell("a"), "opacity") == "1"
    ring = _style(wk_page, _cell("a"), "boxShadow")
    assert "rgb(35, 32, 27)" in ring and "rgb(251, 249, 245)" in ring
    assert "inset" in ring
    # No pick active: nothing fades or rings.
    _mount(wk_page, games)
    assert _style(wk_page, _cell("b"), "opacity") == "1"
    assert _style(wk_page, _cell("a"), "boxShadow") == "none"


def test_ring_is_light_in_dark_theme(wk_page: Page) -> None:
    _mount(wk_page, [_known(key="a"), _known(key="b", home="B")], theme="dark", pass_keys=["a"])
    ring = _style(wk_page, _cell("a"), "boxShadow")
    assert "rgb(236, 231, 223)" in ring and "rgb(29, 27, 24)" in ring


def test_networks_pick_fades_whole_rows(wk_page: Page) -> None:
    games = [
        _known(key="f", networkId="fox", networkName="FOX", family="fox"),
        _known(key="a", networkId="abc", networkName="ABC", family="disney", home="A2"),
    ]
    _mount(wk_page, games, nets=["fox"])
    assert _style(wk_page, _cell("a"), "opacity") == "0.3"
    assert _style(wk_page, '#wk-host .wk-row[data-row="abc"] .wk-rowhead', "opacity") == "0.3"
    assert _style(wk_page, _cell("f"), "opacity") == "1"
    assert _style(wk_page, '#wk-host .wk-row[data-row="fox"] .wk-rowhead', "opacity") == "1"
    # Row order follows the site precedence: FOX above ABC.
    assert wk_page.locator("#wk-host .wk-row").evaluate_all("r => r.map(x => x.dataset.row)") == [
        "fox",
        "abc",
    ]


def test_roving_focus_keys(wk_page: Page) -> None:
    games = [
        _known(key="g1", boothRank=1, home="A"),
        _known(key="g2", home="B"),
        _known(key="g3", kickoffMin=960, home="C"),
    ]
    _mount(wk_page, games)
    stops = wk_page.locator("#wk-host .wk-cell[tabindex='0']")
    assert stops.count() == 1
    wk_page.locator(_cell("g1")).focus()

    def focused() -> str:
        return wk_page.evaluate(  # type: ignore[no-any-return]
            "document.activeElement.dataset.wkId"
        )

    wk_page.keyboard.press("ArrowRight")
    assert focused() == "g:g3"
    wk_page.keyboard.press("ArrowLeft")
    assert focused() == "g:g1"
    wk_page.keyboard.press("ArrowDown")
    assert focused() == "g:g2"
    wk_page.keyboard.press("ArrowUp")
    assert focused() == "g:g1"
    wk_page.keyboard.press("End")
    assert focused() == "g:g3"
    wk_page.keyboard.press("ArrowDown")
    assert focused() == "g:g2"
    wk_page.keyboard.press("Home")
    assert focused() == "g:g2"
    assert wk_page.locator("#wk-host .wk-cell[tabindex='0']").count() == 1
    wk_page.keyboard.press("Enter")
    assert wk_page.evaluate("window.__wk.opened") == ["g2"]


def test_stepper_labels_and_latest_week(wk_page: Page) -> None:
    _mount(wk_page, [_known(key="a")], model={"isLatestWeek": True, "weekLabel": "Week 10"})
    nxt = wk_page.locator("#wk-host .wk-step--next")
    prv = wk_page.locator("#wk-host .wk-step--prev")
    assert nxt.get_attribute("aria-disabled") == "true"
    assert nxt.get_attribute("title") == "Latest week"
    assert prv.get_attribute("aria-label") == "Previous week, Week 9"
    assert wk_page.locator("#wk-host .wk-week").inner_text() == "Week 10"
    nxt.click(force=True)
    assert wk_page.evaluate("window.__wk.weeks") == []
    prv.click()
    assert wk_page.evaluate("window.__wk.weeks") == [-1]
    _mount(wk_page, [_known(key="a")])
    nxt = wk_page.locator("#wk-host .wk-step--next")
    assert nxt.get_attribute("aria-label") == "Next week, Week 10"
    assert nxt.get_attribute("aria-disabled") is None
    nxt.click()
    assert wk_page.evaluate("window.__wk.weeks") == [1]
    box = wk_page.locator("#wk-host .wk-step--next").bounding_box()
    assert box is not None
    assert box["width"] == 32 and box["height"] == 32


def test_day_tabs_second_tablist_and_counts(wk_page: Page) -> None:
    games = [
        _known(key="s", home="S"),
        _known(key="f", date=FRI, kickoffMin=1200, home="F", networkId="fs1", family="fox"),
    ]
    _mount(wk_page, games)
    tabs = wk_page.locator("#wk-host [role=tablist][aria-label=Day] [role=tab]")
    assert tabs.all_inner_texts() == ["Fri. Oct. 30", "Sat. Oct. 31"]
    assert tabs.nth(1).get_attribute("aria-selected") == "true"
    assert tabs.nth(0).get_attribute("aria-selected") == "false"
    _mount(wk_page, games, pass_keys=["f"])
    tabs = wk_page.locator("#wk-host [role=tab]")
    assert tabs.all_inner_texts() == ["Fri. Oct. 30 (1)", "Sat. Oct. 31 (0)"]
    tabs.nth(0).click()
    assert wk_page.evaluate("window.__wk.days") == [FRI]
    assert wk_page.locator(_cell("f")).count() == 1
    assert wk_page.locator(_cell("s")).count() == 0
    # Roving arrows move focus and select; focus stays on the tab.
    wk_page.keyboard.press("ArrowRight")
    assert wk_page.evaluate("document.activeElement.dataset.wkId") == f"day:{SAT}"
    assert wk_page.locator(_cell("s")).count() == 1


def test_now_line_only_on_todays_et_day(wk_page: Page) -> None:
    games = [_known(key="a"), _known(key="f", date=FRI, kickoffMin=1200, home="F")]
    _mount(wk_page, games, now="2026-10-31T13:00:00-04:00")
    assert wk_page.locator("#wk-host .wk-now").count() == 1
    assert wk_page.locator("#wk-host .wk-now-label").inner_text() == "Now"
    assert _style(wk_page, "#wk-host .wk-now", "backgroundColor") == "rgb(27, 79, 92)"
    _mount(wk_page, games, now="2026-10-30T09:00:00-04:00", day=SAT)
    assert wk_page.locator("#wk-host .wk-now").count() == 0
    # Outside the axis range on the same day: no line.
    _mount(wk_page, games, now="2026-10-31T06:00:00-04:00")
    assert wk_page.locator("#wk-host .wk-now").count() == 0



def _intersects(a: dict[str, float], b: dict[str, float]) -> bool:
    return (
        a["x"] < b["x"] + b["width"]
        and b["x"] < a["x"] + a["width"]
        and a["y"] < b["y"] + b["height"]
        and b["y"] < a["y"] + a["height"]
    )


def test_now_label_flips_right_of_the_line_near_the_axis_start(wk_page: Page) -> None:
    # UI review fix 1: in the axis's first hour the label sits right of the line, clear of the
    # sticky "All times ET" corner; later in the day it stays on the line's left.
    games = [_known(key="a"), _known(key="b", kickoffMin=1170, home="Late")]
    wk_page.clock.install(time="2026-10-31T12:05:00-04:00")
    _mount(wk_page, games, live_clock=True)
    corner = wk_page.locator("#wk-host .wk-corner").bounding_box()
    label = wk_page.locator("#wk-host .wk-now-label").bounding_box()
    line = wk_page.locator("#wk-host .wk-now").bounding_box()
    assert corner is not None and label is not None and line is not None
    assert not _intersects(label, corner)
    assert label["x"] >= line["x"] + line["width"]
    assert not any(_intersects(label, t) for t in _shown_ticks(wk_page))
    wk_page.evaluate("window.__wk.inst.destroy()")
    for time in ("15:00", "15:20"):
        wk_page.clock.set_system_time(f"2026-10-31T{time}:00-04:00")
        _mount(wk_page, games, live_clock=True)
        label = wk_page.locator("#wk-host .wk-now-label").bounding_box()
        line = wk_page.locator("#wk-host .wk-now").bounding_box()
        assert label is not None and line is not None
        assert label["x"] + label["width"] <= line["x"]
        # A tick label the Now label would cover hides; its hairline still shows.
        assert not any(_intersects(label, t) for t in _shown_ticks(wk_page))
        wk_page.evaluate("window.__wk.inst.destroy()")


def _shown_ticks(page: Page) -> list[dict[str, float]]:
    return page.locator("#wk-host .wk-tick").evaluate_all(  # type: ignore[no-any-return]
        """ts => ts.filter((t) => getComputedStyle(t).visibility !== 'hidden').map((t) => {
          const r = t.getBoundingClientRect();
          return { x: r.x, y: r.y, width: r.width, height: r.height };
        })"""
    )


_ROOT = "document.querySelector('#wk-host .wk-root')"


def test_clock_tick_keeps_scroll_and_focus(wk_page: Page) -> None:
    # WR-02: the minute rebuild on today keeps both sideways scrolls and the focused cell.
    wk_page.clock.install(time="2026-10-31T13:00:00-04:00")
    days = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", FRI, SAT]
    games = [_known(key=f"d{n}", date=d, home=f"H{n}") for n, d in enumerate(days)]
    games.append(_known(key="late", kickoffMin=1380, home="Late"))
    _mount(wk_page, games, width=800, host_width=420, live_clock=True)
    before = wk_page.evaluate(
        """() => {
          const sc = document.querySelector('#wk-host .wk-scroll');
          const tabs = document.querySelector('#wk-host .wk-days');
          sc.scrollLeft = 200;
          tabs.scrollLeft = 30;
          document.querySelector('#wk-host [data-wk-id="g:late"]').focus({ preventScroll: true });
          window.__oldRoot = """
        + _ROOT
        + """;
          return { grid: sc.scrollLeft, tabs: tabs.scrollLeft };
        }"""
    )
    assert before["grid"] > 0 and before["tabs"] > 0
    wk_page.clock.run_for(60_000)
    assert not wk_page.evaluate("window.__oldRoot.isConnected")
    after = wk_page.evaluate(
        """() => ({
          grid: document.querySelector('#wk-host .wk-scroll').scrollLeft,
          tabs: document.querySelector('#wk-host .wk-days').scrollLeft,
          focus: document.activeElement?.dataset?.wkId ?? null,
        })"""
    )
    assert after == {**before, "focus": "g:late"}


def test_clock_tick_skips_rebuilds_that_change_nothing(wk_page: Page) -> None:
    # WR-02: a past week, or a day other than today whose cells cannot move, is left alone.
    wk_page.clock.install(time="2026-10-31T13:00:00-04:00")
    games = [_game(key="a"), _game(key="f", date=FRI, kickoffMin=1200, home="F")]
    for model, day in (({"past": True}, SAT), (None, FRI)):
        _mount(wk_page, games, day=day, model=model, live_clock=True)
        wk_page.evaluate(f"window.__oldRoot = {_ROOT}")
        wk_page.clock.run_for(180_000)
        assert wk_page.evaluate("window.__oldRoot.isConnected")
        wk_page.evaluate("window.__wk.inst.destroy()")


def test_theme_flip_recomputes_tints(wk_page: Page) -> None:
    _mount(wk_page, [_game(key="t")])
    light = _palette(wk_page, "light", "fox")
    dark = _palette(wk_page, "dark", "fox")
    assert light["tint"] != dark["tint"]
    assert _style(wk_page, _cell("t"), "backgroundColor") == light["tint"]
    wk_page.evaluate("document.documentElement.dataset.theme = 'dark'")
    wk_page.wait_for_function(
        "([s, v]) => getComputedStyle(document.querySelector(s)).backgroundColor === v",
        arg=[_cell("t"), dark["tint"]],
    )


def test_streaming_row_and_label(wk_page: Page) -> None:
    games = [
        _known(key="p", networkId="peacock", networkName="Peacock", family="nbc", home="P"),
        _known(key="f", home="F"),
    ]
    _mount(wk_page, games)
    rows = wk_page.locator("#wk-host .wk-row").evaluate_all("r => r.map(x => x.dataset.row)")
    assert rows == ["fox", "streaming"]
    assert wk_page.locator('#wk-host .wk-row[data-row="streaming"] .wk-rowname').inner_text() == (
        "Streaming"
    )
    assert wk_page.locator(f"{_cell('p')} .wk-tail").inner_text() == "Peacock"


# -- Task 2: strip, ESPN+ table, stamp, source line, empty states --------------------------


def _tba_games(n: int) -> list[dict[str, Any]]:
    out = []
    for k in range(n):
        if k % 2 == 0:
            out.append(_game(key=f"t{k}", kickoffMin=None, home=f"H{k}"))
        else:
            out.append(
                _game(key=f"t{k}", networkId=None, networkName=None, family="other", home=f"H{k}")
            )
    return out


def test_tba_strip_collapse_threshold_and_toggle(wk_page: Page) -> None:
    _mount(wk_page, [_known(key="a"), *_tba_games(7)])
    head = wk_page.locator("#wk-host .wk-tba-head")
    assert head.inner_text() == "Time or network to be announced (7)"
    assert head.get_attribute("aria-expanded") == "false"
    assert wk_page.locator("#wk-host .wk-tba-body").is_hidden()
    assert wk_page.locator("#wk-host .wk-tba-body > .wk-cell").count() == 7
    head.click()
    assert wk_page.locator("#wk-host .wk-tba-head").get_attribute("aria-expanded") == "true"
    assert wk_page.locator("#wk-host .wk-tba-body").is_visible()
    # Focus stays on the toggle across the rebuild.
    assert wk_page.evaluate("document.activeElement.dataset.wkId") == "strip"
    wk_page.locator("#wk-host .wk-tba-head").click()
    assert wk_page.locator("#wk-host .wk-tba-head").get_attribute("aria-expanded") == "false"
    _mount(wk_page, [_known(key="a"), *_tba_games(6)])
    assert wk_page.locator("#wk-host .wk-tba-head").get_attribute("aria-expanded") == "true"
    assert wk_page.locator("#wk-host .wk-tba-body > .wk-cell").count() == 6


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_tba_strip_cell_states(wk_page: Page, theme: str) -> None:
    _mount(wk_page, [_known(key="a"), *_tba_games(2)], theme=theme)
    pal = _palette(wk_page, theme, "fox")
    net_known = _cell("t0")
    net_unknown = _cell("t1")
    assert wk_page.locator(f"{net_known} .wk-time").inner_text() == "Time TBA"
    assert wk_page.locator(f"{net_known} .wk-tail").inner_text() == "FOX"
    assert _style(wk_page, net_known, "backgroundColor") == pal["tint"]
    assert wk_page.locator(f"{net_unknown} .wk-tail").inner_text() == "Network TBA"
    surface = {"light": "rgb(244, 240, 232)", "dark": "rgb(38, 35, 31)"}[theme]
    assert _style(wk_page, net_unknown, "backgroundColor") == surface
    assert _style(wk_page, net_unknown, "boxShadow") != "none"
    box = wk_page.locator(net_known).bounding_box()
    assert box is not None and box["height"] == 44 and box["width"] >= 280
    wk_page.locator(net_unknown).click()
    assert wk_page.evaluate("window.__wk.opened") == ["t1"]


def test_strip_cells_take_picks(wk_page: Page) -> None:
    _mount(wk_page, [_known(key="a"), *_tba_games(2)], pass_keys=["t0"])
    assert _style(wk_page, _cell("t1"), "opacity") == "0.3"
    assert "inset" in _style(wk_page, _cell("t0"), "boxShadow")


def _plus(**kw: Any) -> dict[str, Any]:
    base = {"networkId": "espn-plus", "networkName": "ESPN+", "family": "disney"}
    base.update(kw)
    return _game(**base)


def test_compact_table_rows_booths_and_keys(wk_page: Page) -> None:
    games = [
        _known(key="a"),
        _plus(key="p1", home="Plus One", pbp="Ann Caller", analyst="Bob Color", crewKnown=True),
        _plus(key="p2", home="Plus Two", kickoffMin=1140),
    ]
    _mount(wk_page, games)
    assert wk_page.locator("#wk-host .wk-compact-title").inner_text() == "ESPN+ and regional"
    assert _style(wk_page, "#wk-host .wk-compact-title", "fontFamily").startswith('"Crimson Text"')
    heads = wk_page.locator("#wk-host .wk-compact-table th").all_inner_texts()
    assert heads == ["Time", "Game", "Network", "Booth"]
    rows = wk_page.locator("#wk-host .wk-compact-table tbody tr")
    assert rows.count() == 2
    assert rows.nth(0).locator(".wk-c-booth").inner_text() == "Caller · Color"
    assert rows.nth(0).locator(".wk-c-time").inner_text() == "12:00 pm"
    assert rows.nth(1).locator(".wk-c-booth").inner_text() == "Crew TBA"
    assert rows.nth(0).get_attribute("role") == "button"
    # ESPN+ games never draw in the grid.
    assert wk_page.locator('#wk-host .wk-cell[data-wk-id="g:p1"]').count() == 0
    rows.nth(1).focus()
    wk_page.keyboard.press("Enter")
    assert wk_page.evaluate("window.__wk.opened") == ["p2"]
    wk_page.keyboard.press("Space")
    assert wk_page.evaluate("window.__wk.opened") == ["p2", "p2"]


def test_compact_table_picks_and_absent_cases(wk_page: Page) -> None:
    games = [
        _known(key="a"),
        _plus(key="p1", home="One", pbp="Ann Caller", analyst="Bob Color", crewKnown=True),
        _plus(key="p2", home="Two", kickoffMin=1140),
    ]
    _mount(wk_page, games, pass_keys=["p1"])
    matched = wk_page.locator("#wk-host .wk-crow.is-match")
    assert matched.count() == 1
    assert "inset" in _style(wk_page, "#wk-host .wk-crow.is-match td", "boxShadow")
    assert _style(wk_page, "#wk-host .wk-crow.is-match .wk-c-booth", "fontWeight") == "600"
    assert _style(wk_page, "#wk-host .wk-crow:not(.is-match)", "opacity") == "0.3"
    _mount(wk_page, [_known(key="a")])
    assert wk_page.locator("#wk-host .wk-compact").count() == 0
    assert wk_page.locator("#wk-host .wk-tba").count() == 0


def test_crew_not_listed_after_kickoff(wk_page: Page) -> None:
    games = [_game(key="a"), _plus(key="p")]
    _mount(wk_page, games, now="2026-10-31T20:00:00-04:00")
    assert wk_page.locator(f"{_cell('a')} .wk-booth").inner_text() == "Crew not listed"
    assert wk_page.locator("#wk-host .wk-c-booth").inner_text() == "Crew not listed"


def test_stamp_line_variants(wk_page: Page) -> None:
    games = [_known(key="a")]
    fresh = {
        "crews_506_saved_at": "2026-10-30T01:14:00Z",
        "crews_espnpr_saved_at": "2026-10-26T14:00:00Z",
        "espnpr_week": 9,
        "schedule_updated_at": "2026-10-30T22:00:00Z",
    }
    _mount(wk_page, games, model={"freshness": fresh})
    assert wk_page.locator("#wk-host .wk-stamp").inner_text() == (
        "Crews: 506 Sports saved Thu. Oct. 29, 9:14 pm ET · ESPN Press Room week 9 saved "
        "Mon. Oct. 26 · Schedule updated Fri. Oct. 30, 6:00 pm ET"
    )
    assert wk_page.locator("#wk-host .wk-stamp").get_attribute("aria-live") == "off"
    only_506 = {"crews_506_saved_at": fresh["crews_506_saved_at"]}
    _mount(wk_page, games, model={"freshness": only_506})
    assert wk_page.locator("#wk-host .wk-stamp").inner_text() == (
        "Crews: 506 Sports saved Thu. Oct. 29, 9:14 pm ET"
    )
    sched = {"schedule_updated_at": fresh["schedule_updated_at"]}
    _mount(wk_page, games, model={"freshness": sched})
    assert wk_page.locator("#wk-host .wk-stamp").inner_text() == (
        "Crews for this week are not posted yet. Games show Crew TBA until they are. "
        "Schedule updated Fri. Oct. 30, 6:00 pm ET"
    )
    _mount(wk_page, games, model={"freshness": fresh, "past": True})
    assert wk_page.locator("#wk-host .wk-stamp").inner_text() == (
        "Crews: 506 Sports and ESPN Press Room, as saved."
    )
    _mount(wk_page, games, model={"freshness": fresh, "past": True, "sport": "nfl"})
    assert wk_page.locator("#wk-host .wk-stamp").inner_text() == "Crews: 506 Sports, as saved."
    _mount(wk_page, games, model={"freshness": None})
    assert wk_page.locator("#wk-host .wk-stamp").inner_text().startswith("Crews for this week")


def test_zero_matches_replaces_stamp(wk_page: Page) -> None:
    _mount(wk_page, [_known(key="a"), _known(key="b", home="B")], pass_keys=["zzz"])
    assert wk_page.locator("#wk-host .wk-stamp").inner_text() == (
        "No games match your picks on Sat. Oct. 31. Try another day or clear a filter."
    )
    assert _style(wk_page, _cell("a"), "opacity") == "0.3"


def test_source_line_cfb_credits_and_links(wk_page: Page) -> None:
    _mount(wk_page, [_known(key="a")])
    line = wk_page.locator("#wk-host .wk-source")
    assert line.inner_text() == (
        "Schedule: CollegeFootballData.com · Crews: 506 Sports and ESPN Press Room · "
        "Networks: CollegeFootballData.com and 506 Sports"
    )
    anchors = wk_page.locator("#wk-host .wk-source a")
    assert anchors.count() == 5
    for i in range(5):
        assert anchors.nth(i).get_attribute("rel") == "noopener noreferrer"
    hrefs = anchors.evaluate_all("a => a.map(x => x.href)")
    assert hrefs[0] == "https://collegefootballdata.com/"
    assert hrefs[1] == "https://506sports.com/"


def test_source_line_nfl_has_no_cfbd_credit(wk_page: Page) -> None:
    games = [_known(key="a", sport="nfl", networkId="cbs", networkName="CBS", family="cbs")]
    _mount(wk_page, games, model={"sport": "nfl"})
    text = wk_page.locator("#wk-host .wk-source").inner_text()
    assert text == "Schedule: nflverse · Crews: 506 Sports"
    assert "CollegeFootballData" not in text and "Wikipedia" not in text
    _mount(
        wk_page,
        games,
        model={"sport": "nfl", "links": {"wikipedia": "https://en.wikipedia.org/wiki/Foo"}},
    )
    text = wk_page.locator("#wk-host .wk-source").inner_text()
    assert text.endswith("Networks: Wikipedia (CC BY-SA 4.0)")
    href = wk_page.locator("#wk-host .wk-source a", has_text="Wikipedia").get_attribute("href")
    assert href == "https://en.wikipedia.org/wiki/Foo"
    # An unsafe href never becomes a link.
    _mount(wk_page, games, model={"sport": "nfl", "links": {"wikipedia": "javascript:alert(1)"}})
    assert wk_page.locator("#wk-host .wk-source a", has_text="Wikipedia").count() == 0


def test_empty_week_and_missing_schedule(wk_page: Page) -> None:
    _mount(wk_page, [], day=None)
    assert wk_page.locator("#wk-host .wk-empty-title").inner_text() == "No games this weekend"
    assert wk_page.locator("#wk-host .wk-empty-body").inner_text() == (
        "The schedule has no games for Week 9 yet. Step back to a past week to see final crews."
    )
    assert wk_page.locator("#wk-host .wk-step--prev").count() == 1
    _mount(wk_page, [], day=None, model={"missing": True})
    err = wk_page.locator("#wk-host .wk-error")
    assert err.inner_text() == (
        "This build has no schedule for Week 9. Reload the page or step back to Week 8."
    )
    assert _style(wk_page, "#wk-host .wk-error", "color") == "rgb(179, 38, 30)"


# -- Task 3: phone list at 390px -----------------------------------------------------------


@pytest.fixture
def phone_page(guarded_page: Page, open_app: Callable[[Page, str], None]) -> Page:
    guarded_page.set_viewport_size({"width": 390, "height": 844})
    open_app(guarded_page, "")
    return guarded_page


def _mount_phone(page: Page, games: list[dict[str, Any]], **kw: Any) -> None:
    _mount(page, games, width=390, kind="list", **kw)


def _phone_games() -> list[dict[str, Any]]:
    return [
        _known(key="f2", boothRank=2, home="F2", kickoffMin=720),
        _known(key="f1", boothRank=1, home="F1", kickoffMin=720, lead=True),
        _known(
            key="a1", networkId="abc", networkName="ABC", family="disney", home="A1", kickoffMin=720
        ),
        _game(key="late", home="Late", kickoffMin=930, boothRank=1),
    ]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_phone_groups_order_and_item_shape(phone_page: Page, theme: str) -> None:
    _mount_phone(phone_page, _phone_games(), theme=theme)
    titles = phone_page.locator("#wk-host .wk-group-title").all_inner_texts()
    assert titles == ["12:00 pm", "3:30 pm"]
    order = (
        phone_page.locator("#wk-host .wk-group")
        .first.locator(".wk-item")
        .evaluate_all("i => i.map(x => x.dataset.wkId)")
    )
    assert order == ["g:f1", "g:f2", "g:a1"]  # FOX before ABC; rank 1 before rank 2
    pal = _palette(phone_page, theme, "fox")
    first = _cell("f1").replace("[data-wk-id", ".wk-item[data-wk-id")
    box = phone_page.locator(first).bounding_box()
    assert box is not None and box["height"] >= 56
    assert _style(phone_page, first, "borderLeftWidth") == "4px"
    assert _style(phone_page, first, "borderLeftColor") == pal["solid"]
    mark = phone_page.locator(f"{first} .wk-item-mark").bounding_box()
    assert mark is not None and mark["width"] == 56
    assert phone_page.locator(f"{first} .wk-item-l1").inner_text() == "Away @ Home".replace(
        "Home", "F1"
    )
    assert (
        phone_page.locator(f"{first} .wk-item-l2 .wk-booth").inner_text() == "Fowler · Herbstreit"
    )
    assert phone_page.locator(f"{first} .wk-star").count() == 1
    assert _style(phone_page, first, "backgroundColor") == "rgba(0, 0, 0, 0)"
    tba = phone_page.locator('#wk-host .wk-item[data-wk-id="g:late"] .wk-booth')
    assert tba.inner_text() == "Crew TBA"
    assert tba.evaluate("e => getComputedStyle(e).fontWeight") == "400"


def test_phone_has_no_axis_or_now_line(phone_page: Page) -> None:
    _mount_phone(phone_page, _phone_games(), now="2026-10-31T13:00:00-04:00")
    for sel in (".wk-axis", ".wk-now", ".wk-grid", ".wk-corner"):
        assert phone_page.locator(f"#wk-host {sel}").count() == 0


def test_phone_tba_and_espn_plus_groups_last(phone_page: Page) -> None:
    games = [*_phone_games(), _plus(key="p1", home="Plus"), *_tba_games(7)]
    _mount_phone(phone_page, games)
    classes = phone_page.locator("#wk-host .wk-group").evaluate_all("g => g.map(x => x.className)")
    assert [
        ("tba" if "wk-tba" in c else "compact" if "wk-compact" in c else "time") for c in classes
    ] == [
        "time",
        "time",
        "tba",
        "compact",
    ]
    head = phone_page.locator("#wk-host .wk-tba-head")
    assert head.inner_text() == "Time or network to be announced (7)"
    assert head.get_attribute("aria-expanded") == "false"
    head.click()
    assert phone_page.locator("#wk-host .wk-tba-head").get_attribute("aria-expanded") == "true"
    assert phone_page.locator("#wk-host .wk-tba-body > .wk-item").count() == 7
    assert phone_page.locator("#wk-host .wk-compact .wk-group-title").inner_text() == (
        "ESPN+ and regional"
    )
    assert phone_page.locator("#wk-host .wk-compact .wk-item").count() == 1


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_phone_picks_fade_and_ring(phone_page: Page, theme: str) -> None:
    _mount_phone(phone_page, _phone_games(), theme=theme, pass_keys=["f1"])
    sel = lambda k: f'#wk-host .wk-item[data-wk-id="g:{k}"]'  # noqa: E731
    assert _style(phone_page, sel("f2"), "opacity") == "0.3"
    assert _style(phone_page, sel("f1"), "opacity") == "1"
    ink = "rgb(35, 32, 27)" if theme == "light" else "rgb(236, 231, 223)"
    assert ink in _style(phone_page, sel("f1"), "boxShadow")
    phone_page.locator(sel("f2")).click()
    assert phone_page.evaluate("window.__wk.opened") == ["f2"]


def test_phone_stepper_on_its_own_line_with_44px_taps(phone_page: Page) -> None:
    _mount_phone(phone_page, _phone_games())
    tabs = phone_page.locator("#wk-host .wk-days").bounding_box()
    step = phone_page.locator("#wk-host .wk-stepper").bounding_box()
    nxt = phone_page.locator("#wk-host .wk-step--next").bounding_box()
    assert tabs is not None and step is not None and nxt is not None
    assert step["y"] >= tabs["y"] + tabs["height"]
    assert nxt["width"] >= 44 and nxt["height"] >= 44
    assert step["x"] + step["width"] <= 390


def test_phone_nfl_cbs_window_rank_one_first(phone_page: Page) -> None:
    games = [
        _known(
            key=f"c{k}",
            sport="nfl",
            networkId="cbs",
            networkName="CBS",
            family="cbs",
            kickoffMin=780,
            boothRank=r,
            home=f"H{k}",
        )
        for k, r in enumerate([3, 1, 2])
    ]
    _mount_phone(phone_page, games, model={"sport": "nfl"})
    order = phone_page.locator("#wk-host .wk-item").evaluate_all("i => i.map(x => x.dataset.wkId)")
    assert order == ["g:c1", "g:c2", "g:c0"]
    assert phone_page.locator("#wk-host .wk-group-title").inner_text() == "1:00 pm"
