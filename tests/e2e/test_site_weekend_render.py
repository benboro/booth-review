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
    now: new Date(arg.now),
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
        },
    )


def _cell(key: str) -> str:
    return f'#wk-host [data-wk-id="g:{key}"]'


def _palette(page: Page, theme: str, family: str) -> dict[str, str]:
    return page.evaluate(  # type: ignore[no-any-return]
        """async ([theme, family]) => {
          const P = await import('./modules/palette.js');
          const rgb = (hex) => {
            const n = parseInt(hex.slice(1), 16);
            return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
          };
          return {
            solid: rgb(P.FAMILY_COLORS[theme][family]),
            text: rgb(P.PILL_TEXT_COLOR[theme][family]),
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
    top = {
        k: wk_page.evaluate(f"document.querySelector('{_cell(k)}').offsetTop") for k in "abc"
    }
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
    assert 88 <= pxh <= 120
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
    assert _style(wk_page, _cell("k"), "backgroundColor") == pal["solid"]
    assert _style(wk_page, _cell("k"), "color") == pal["text"]
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
    assert label == (
        "12:00 pm, #20 Florida at #5 Georgia, FOX. Lead booth. Fowler and Herbstreit."
    )


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
