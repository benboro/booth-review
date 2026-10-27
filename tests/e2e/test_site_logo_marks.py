"""SHELL-05 / V6: network logos in the CFB table, tooltip and detail panel.

The contract fixture's networks (net-a ... net-e) have no vendored logo, so the
tests serve a copy whose ids are renamed to ids the logo map knows (espn, a 14px
wordmark; abc, a 20px badge), keeping net-c and net-d as the no-logo fallback.
Synthetic data only; the page guard fails any request that leaves the origin.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from typing import Any

import pytest
from conftest import element_height, logo_images
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

OpenApp = Callable[[Page, str], None]

# Fixture network index -> logo id. Index 2 (net-c) and 3 (net-d) keep no logo.
_RENAMES = {0: "espn", 1: "abc"}

_SHOW_TOOLTIP_JS = """
async (i) => {
  const { showTooltip } = await import(new URL('./modules/tooltip.js', location.href).href);
  const data = window.__testHooks.data;
  showTooltip(data, i, { axis: 'spread', theme: 'light', clientX: 200, clientY: 200,
                         selected: new Set() });
}
"""


_QUERY = "?school=northfield"  # telecasts 0, 4 and 8 (Northfield); the games table needs a pick


def _with_logo_ids(fixture_raw: dict[str, Any], *, renamed: bool = True) -> dict[str, Any]:
    raw = copy.deepcopy(fixture_raw)
    # Northfield's three games: net-a (espn), net-b (abc) and net-c (no logo).
    raw["telecasts"]["network"][4] = 1
    raw["telecasts"]["network"][8] = 2
    if renamed:
        for index, logo_id in _RENAMES.items():
            raw["lookups"]["networks"][index]["id"] = logo_id
    return raw


def _serve(page: Page, raw: dict[str, Any]) -> None:
    page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))


def _check_logo_attrs(page: Page, scope: str, names: set[str]) -> list[dict[str, Any]]:
    """Every logo under `scope`: alt == title == a known network name, explicit
    size attributes equal to the rendered size, same-origin /logos/ src, loaded."""
    images = logo_images(page, scope)
    assert images, f"no logos under {scope}"
    attrs = page.evaluate(
        """(scope) => [...document.querySelectorAll(scope + ' img')].map((img) => ({
          width: img.getAttribute('width'), height: img.getAttribute('height'),
          resolved: new URL(img.currentSrc || img.src, location.href).pathname,
          origin: new URL(img.currentSrc || img.src, location.href).origin === location.origin,
        }))""",
        scope,
    )
    for img, attr in zip(images, attrs, strict=True):
        assert img["alt"] in names
        assert img["title"] == img["alt"]
        assert attr["width"] is not None
        assert attr["height"] is not None
        assert abs(float(attr["width"]) - img["width"]) < 0.5
        assert abs(float(attr["height"]) - img["height"]) < 0.5
        assert attr["origin"] is True
        assert re.fullmatch(r"/logos/[a-z0-9-]+\.svg", attr["resolved"]) or attr[
            "resolved"
        ].startswith("/logos/")
        assert (img["src"] or "").startswith("logos/")
        assert img["naturalWidth"] > 0
    return images


def test_table_logos_have_alt_title_size_and_same_origin_src(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    _serve(guarded_page, _with_logo_ids(fixture_raw))
    open_app(guarded_page, _QUERY)
    names = {"Alpha Sports", "Beta Network"}
    images = _check_logo_attrs(guarded_page, "#games-table tbody", names)
    # LOGO-LINKS render boxes: 14px wordmarks, 20px badges, width from the viewBox, no cap.
    by_name = {img["alt"]: img for img in images}
    assert by_name["Alpha Sports"]["height"] == pytest.approx(14, abs=0.5)
    assert by_name["Alpha Sports"]["width"] == pytest.approx(57, abs=0.5)
    assert by_name["Beta Network"]["height"] == pytest.approx(20, abs=0.5)
    assert by_name["Beta Network"]["width"] == pytest.approx(20, abs=0.5)


def test_network_without_a_logo_shows_dot_and_name(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    _serve(guarded_page, _with_logo_ids(fixture_raw))
    open_app(guarded_page, _QUERY)
    # Telecast 2 is on net-c (Conference Network), which has no vendored logo.
    fallback = guarded_page.locator(
        "#games-table tbody tr .net-mark:has(.net-name:text-is('Conference Network'))"
    ).first
    assert fallback.locator("img").count() == 0
    assert fallback.locator("span.net-dot").count() == 1
    assert fallback.locator("span.net-name").text_content() == "Conference Network"
    dot_color = fallback.locator(".net-dot").evaluate(
        "(el) => getComputedStyle(el).backgroundColor"
    )
    assert dot_color not in ("", "rgba(0, 0, 0, 0)")


def test_a_logo_stands_alone_with_no_family_dot(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """Brief §5: a network with a logo shows the logo alone in the table and the panel; the
    family dot appears only in the dot-and-name fallback."""
    _serve(guarded_page, _with_logo_ids(fixture_raw))
    open_app(guarded_page, _QUERY)
    marks = guarded_page.eval_on_selector_all(
        "#games-table tbody .net-mark",
        "els => els.map(m => ({ logo: !!m.querySelector('img'),"
        " dots: m.querySelectorAll('.net-dot').length }))",
    )
    assert {m["logo"] for m in marks} == {True, False}
    for mark in marks:
        assert mark["dots"] == (0 if mark["logo"] else 1), marks
    guarded_page.evaluate("window.__testHooks.openPanel(0)")  # telecast 0 is on espn
    panel = guarded_page.locator("#panel-body .panel-networks .net-mark").first
    assert panel.locator("img").count() == 1
    assert panel.locator(".net-dot").count() == 0


def test_table_family_dots_follow_a_theme_change(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """SHELL-02: flipping data-theme repaints the family dots already in the games table,
    not only the active chart."""
    _serve(guarded_page, _with_logo_ids(fixture_raw))
    open_app(guarded_page, _QUERY)
    guarded_page.wait_for_selector("#games-table tbody tr .net-dot[data-family]")
    # Paint a probe dot with each theme's colour, so the comparison is computed-to-computed.
    snapshot_js = """async () => {
      const url = new URL('./modules/palette.js', location.href).href;
      const { FAMILY_COLORS } = await import(url);
      const theme = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
      const probe = document.createElement('span');
      document.body.appendChild(probe);
      const out = [...document.querySelectorAll('#games-table .net-dot')].map((el) => {
        probe.style.background = FAMILY_COLORS[theme][el.dataset.family];
        return [getComputedStyle(el).backgroundColor, getComputedStyle(probe).backgroundColor];
      });
      probe.remove();
      return out;
    }"""
    light = guarded_page.evaluate(snapshot_js)
    assert light and all(got == want for got, want in light)
    guarded_page.evaluate("document.documentElement.dataset.theme = 'dark'")
    guarded_page.wait_for_timeout(50)  # MutationObserver callbacks run as a microtask
    dark = guarded_page.evaluate(snapshot_js)
    assert len(dark) == len(light)
    assert all(got == want for got, want in dark)
    assert any(d[0] != li[0] for d, li in zip(dark, light, strict=True)), "no dot changed"


def test_badge_row_is_no_taller_than_a_fallback_only_row(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """Reserved-space rule: the first row (telecast 0, net-a) with a 20px badge
    logo is the same height as the same row rendered as dot-and-name fallback."""
    row = "#games-table tbody tr:first-child"

    def first_row_height(renamed: bool, logo_id: str) -> float:
        raw = _with_logo_ids(fixture_raw, renamed=False)
        for telecast in (4, 8):
            raw["telecasts"]["network"][telecast] = 0  # every Northfield row is net-a
        if renamed:
            raw["lookups"]["networks"][0]["id"] = logo_id
        _serve(guarded_page, raw)
        open_app(guarded_page, _QUERY)
        guarded_page.wait_for_selector(row)
        return element_height(guarded_page, row)

    fallback = first_row_height(False, "")
    badge = first_row_height(True, "abc")
    assert guarded_page.locator(f"{row} img.net-logo--badge").count() == 1
    assert badge <= fallback + 0.5
    wordmark = first_row_height(True, "espn")
    assert guarded_page.locator(f"{row} img.net-logo").count() == 1
    assert wordmark <= fallback + 0.5


def test_tooltip_networks_are_logos_without_a_dot_and_border_is_the_family(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    _serve(guarded_page, _with_logo_ids(fixture_raw))
    open_app(guarded_page, "")
    guarded_page.evaluate(_SHOW_TOOLTIP_JS, 0)
    row = guarded_page.locator("#chart-tooltip .tooltip-networks")
    assert row.locator("img.net-logo").count() == 1
    assert row.locator(".net-dot").count() == 0
    images = _check_logo_attrs(guarded_page, "#chart-tooltip .tooltip-networks", {"Alpha Sports"})
    assert images[0]["alt"] == "Alpha Sports"
    family = guarded_page.evaluate(
        """async () => {
          const p = await import(new URL('./modules/palette.js', location.href).href);
          const d = document.createElement('div');
          d.style.borderColor = p.FAMILY_COLORS.light.disney;
          return d.style.borderColor;
        }"""
    )
    border = guarded_page.locator("#chart-tooltip").evaluate(
        "(el) => getComputedStyle(el).borderTopColor"
    )
    assert border == family
    assert "Click for details" not in guarded_page.inner_text("#chart-tooltip")


def test_tooltip_fallback_network_shows_name_with_no_dot(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    _serve(guarded_page, _with_logo_ids(fixture_raw))
    open_app(guarded_page, "")
    guarded_page.evaluate(_SHOW_TOOLTIP_JS, 2)
    row = guarded_page.locator("#chart-tooltip .tooltip-networks")
    assert row.locator("img").count() == 0
    assert row.locator(".net-name").text_content() == "Conference Network"


def test_panel_network_and_also_on_lines_use_marks(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    raw = _with_logo_ids(fixture_raw)
    raw["telecasts"]["outlets"][0] = [0, 1, 2]  # primary net-a, also on net-b and net-c
    _serve(guarded_page, raw)
    open_app(guarded_page, "")
    guarded_page.evaluate("window.__testHooks.openPanel(0)")
    line = guarded_page.locator("#panel-body .panel-networks")
    text = re.sub(r"\s+", " ", line.inner_text())
    assert text.startswith("Network: ")
    assert "; also on: " in text
    assert line.locator(".net-mark").count() == 3
    assert line.locator(".pill").count() == 0
    _check_logo_attrs(guarded_page, "#panel-body .panel-networks", {"Alpha Sports", "Beta Network"})
    assert line.locator(".net-mark:has(.net-name)").count() == 1
    assert line.locator(".net-mark .net-name").text_content() == "Conference Network"


@pytest.mark.parametrize(
    ("ids", "outlets", "want"),
    [
        # An ESPN game also streamed on ESPN+, listed streaming-first in the data.
        ({0: "espn", 4: "espn-plus"}, [4, 0], ["espn", "espn-plus"]),
        # NBC simulcast on Peacock, and CBS on Paramount+ (no Paramount+ logo: its name shows).
        ({0: "nbc", 4: "peacock"}, [4, 0], ["nbc", "peacock"]),
        ({0: "cbs", 4: "paramount-plus"}, [4, 0], ["cbs", "paramount-plus"]),
        # Several outlets after the primary follow NETWORK_PRECEDENCE: ABC, ESPN2, then ESPN+.
        (
            {0: "espn", 1: "espn2", 2: "abc", 4: "espn-plus"},
            [4, 1, 0, 2],
            ["espn", "abc", "espn2", "espn-plus"],
        ),
    ],
)
def test_tooltip_shows_every_outlet_in_network_precedence(
    guarded_page: Page,
    open_app: OpenApp,
    fixture_raw: dict[str, Any],
    ids: dict[int, str],
    outlets: list[int],
    want: list[str],
) -> None:
    """User report 2026-10-24: a game on ESPN and ESPN+ must show both logos. The tooltip
    shows the primary network first, then every other outlet in NETWORK_PRECEDENCE, the
    same order as the panel's "Also on" list; a network with a vendored logo shows it."""
    raw = copy.deepcopy(fixture_raw)
    for index, logo_id in ids.items():
        raw["lookups"]["networks"][index]["id"] = logo_id
    raw["telecasts"]["network"][0] = 0
    raw["telecasts"]["outlets"][0] = outlets
    _serve(guarded_page, raw)
    open_app(guarded_page, "")
    guarded_page.evaluate(_SHOW_TOOLTIP_JS, 0)
    row = "#chart-tooltip .tooltip-networks .net-mark"
    shown = guarded_page.evaluate(
        """(sel) => [...document.querySelectorAll(sel)].map((m) => {
          const img = m.querySelector('img');
          return img ? img.getAttribute('src') : 'name:' + m.textContent;
        })""",
        row,
    )
    logos = guarded_page.evaluate(
        "async () => (await import(new URL('./modules/logos.js', location.href).href))"
        ".logoFor('paramount-plus')"
    )
    assert logos is None  # no vendored Paramount+ mark: it falls back to its name
    names = {n["id"]: n["name"] for n in raw["lookups"]["networks"]}
    expected = [f"logos/{i}.svg" if i != "paramount-plus" else f"name:{names[i]}" for i in want]
    assert shown == expected


def test_footer_carries_the_logo_trademark_line(guarded_page: Page, open_app: OpenApp) -> None:
    """RT-23: the trademark line shown wherever logos render."""
    open_app(guarded_page, "")
    line = re.sub(r"\s+", " ", guarded_page.locator("footer p.trademark-line").inner_text()).strip()
    assert line == (
        "Network logos are trademarks of their owners, shown only to identify each network. "
        "Their use does not imply endorsement, and they are not covered by this site's MIT license."
    )


_LOGO_STATE_JS = """() => [...document.querySelectorAll('img.net-logo')].map((img) => ({
  src: new URL(img.getAttribute('src'), location.href).pathname,
  width: img.getAttribute('width'), height: img.getAttribute('height'),
  alt: img.alt, title: img.title,
  filter: getComputedStyle(img).filter,
  chrome: [img, img.parentElement, img.closest('td')].filter(Boolean).map(
    (el) => getComputedStyle(el).backgroundColor),
}))"""


def test_logos_swap_to_dark_files_on_a_live_theme_flip(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """D-09: flipping data-theme swaps every img.net-logo between logos/<name>.svg and
    logos/dark/<name>.svg, with size, alt and title untouched, and no filter or plate."""
    _serve(guarded_page, _with_logo_ids(fixture_raw))
    open_app(guarded_page, _QUERY)
    guarded_page.wait_for_selector("#games-table tbody img.net-logo")
    light = guarded_page.evaluate(_LOGO_STATE_JS)
    assert light
    assert all(re.fullmatch(r"/logos/[a-z0-9-]+\.svg", s["src"]) for s in light)
    guarded_page.evaluate("document.documentElement.dataset.theme = 'dark'")
    guarded_page.wait_for_function(
        "[...document.querySelectorAll('img.net-logo')].every(i => i.src.includes('/logos/dark/'))"
    )
    dark = guarded_page.evaluate(_LOGO_STATE_JS)
    assert len(dark) == len(light)
    for before, after in zip(light, dark, strict=True):
        assert after["src"] == before["src"].replace("/logos/", "/logos/dark/")
        for key in ("width", "height", "alt", "title"):
            assert after[key] == before[key]
        assert after["filter"] == "none"
        assert all(c in {"rgba(0, 0, 0, 0)", "transparent"} for c in after["chrome"][:2])
    assert guarded_page.evaluate(
        "[...document.querySelectorAll('img.net-logo')].every(i => i.naturalWidth > 0)"
    )
    guarded_page.evaluate("document.documentElement.dataset.theme = 'light'")
    guarded_page.wait_for_function(
        "[...document.querySelectorAll('img.net-logo')].every(i => !i.src.includes('/dark/'))"
    )
    assert guarded_page.evaluate(_LOGO_STATE_JS) == light


def test_first_mark_logo_still_arms_the_theme_watcher(
    guarded_page: Page, open_app: OpenApp, fixture_raw: dict[str, Any]
) -> None:
    """RESEARCH Pitfall 5: with every network a logo (no family dot built), the swap still runs."""
    raw = _with_logo_ids(fixture_raw)
    raw["lookups"]["networks"][2]["id"] = "fox"
    raw["lookups"]["networks"][3]["id"] = "nbc"
    _serve(guarded_page, raw)
    open_app(guarded_page, _QUERY)
    guarded_page.wait_for_selector("#games-table tbody img.net-logo")
    assert guarded_page.locator("#games-table .net-dot").count() == 0
    guarded_page.evaluate("document.documentElement.dataset.theme = 'dark'")
    guarded_page.wait_for_function(
        "[...document.querySelectorAll('img.net-logo')].every(i => i.src.includes('/logos/dark/'))"
    )
