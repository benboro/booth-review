"""Phase 28 conference marks: conferenceLogoFor eras and conferenceMark's img or text
fallback, evaluated in the served site (D-09..D-14). Synthetic names only."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

HOSTILE = "<img src=x onerror=alert(1)>"

_LOOKUP_JS = """
async (cases) => {
  const m = await import('./modules/conf-logos.js');
  return cases.map(([name, season]) => {
    const logo = m.conferenceLogoFor(name, season);
    return logo ? logo.file : null;
  });
}
"""

_MARK_JS = """
async ([name, season]) => {
  const m = await import('./modules/conf-logos.js');
  const mark = m.conferenceMark(name, season);
  if (mark.nodeType === Node.TEXT_NODE) {
    const imgs = document.querySelectorAll('img[src="x"]').length;
    return { kind: 'text', data: mark.data, imgs };
  }
  document.body.append(mark);
  return {
    kind: mark.tagName.toLowerCase(),
    className: mark.className,
    alt: mark.alt,
    title: mark.title,
    cf: mark.dataset.cf,
    season: mark.dataset.season,
    width: mark.getAttribute('width'),
    height: mark.getAttribute('height'),
    src: mark.getAttribute('src'),
  };
}
"""

_SRC_JS = "() => [...document.querySelectorAll('img.cf-logo')].map((i) => i.getAttribute('src'))"


@pytest.fixture
def app_page(guarded_page: Page, open_app: Callable[[Page, str], None]) -> Page:
    guarded_page.set_viewport_size({"width": 1440, "height": 900})
    open_app(guarded_page, "")
    return guarded_page


def _set_theme(page: Page, theme: str) -> None:
    page.evaluate("(t) => { document.documentElement.dataset.theme = t; }", theme)


def _files(page: Page, cases: list[list[Any]]) -> list[str | None]:
    return page.evaluate(_LOOKUP_JS, cases)  # type: ignore[no-any-return]


def test_eras_follow_the_game_season(app_page: Page) -> None:
    got = _files(
        app_page,
        [
            ["SEC", 2023],
            ["SEC", 2024],
            ["SEC", 2014],
            ["Conference USA", 2022],
            ["Conference USA", 2023],
            ["Pac-12", 2025],
            ["Pac-12", 2026],
            ["Big Ten", 2014],
            ["Big Ten", 2026],
            ["SEC", None],
            ["Pac-12", None],
            ["SEC", 2010],
        ],
    )
    assert got == [
        "logos/conf/southeastern-conference-before-2024.svg",
        "logos/conf/southeastern-conference-2024-present.svg",
        "logos/conf/southeastern-conference-before-2024.svg",
        "logos/conf/conference-usa-2013-2023.svg",
        "logos/conf/conference-usa-2023-present.svg",
        "logos/conf/pac-12-conference-before-2026.svg",
        "logos/conf/pac-12-conference-2026-present-official-site.svg",
        "logos/conf/big-ten-conference.svg",
        "logos/conf/big-ten-conference.svg",
        "logos/conf/southeastern-conference-2024-present.svg",
        "logos/conf/pac-12-conference-2026-present-official-site.svg",
        "logos/conf/southeastern-conference-before-2024.svg",
    ]
    undefined_season = app_page.evaluate(
        "async () => (await import('./modules/conf-logos.js')).conferenceLogoFor('SEC').file"
    )
    assert undefined_season == "logos/conf/southeastern-conference-2024-present.svg"


def test_every_fbs_conference_has_a_logo(app_page: Page) -> None:
    names = [
        "American Athletic",
        "ACC",
        "Big 12",
        "Big Ten",
        "Conference USA",
        "Mid-American",
        "Mountain West",
        "Pac-12",
        "SEC",
        "Sun Belt",
    ]
    got = _files(app_page, [[n, 2025] for n in names])
    assert all(f and f.startswith("logos/conf/") for f in got), got


def test_names_without_a_logo_return_null(app_page: Page) -> None:
    got = _files(
        app_page,
        [
            ["Big Sky", 2025],
            ["FBS Independents", 2025],
            ["FCS Independents", 2025],
            ["__proto__", 2025],
            ["constructor", 2025],
            ["toString", 2025],
            [HOSTILE, 2025],
        ],
    )
    assert got == [None] * 7


def test_mark_is_an_img_with_name_and_size(app_page: Page) -> None:
    r = app_page.evaluate(_MARK_JS, ["SEC", 2019])
    assert r == {
        "kind": "img",
        "className": "cf-logo",
        "alt": "SEC",
        "title": "SEC",
        "cf": "SEC",
        "season": "2019",
        "width": "20",
        "height": "20",
        "src": "logos/conf/southeastern-conference-before-2024.svg",
    }


def test_mark_in_dark_theme_uses_the_dark_file(app_page: Page) -> None:
    _set_theme(app_page, "dark")
    r = app_page.evaluate(_MARK_JS, ["Conference USA", 2019])
    assert r["src"] == "logos/dark/conf/conference-usa-2013-2023.svg"
    assert r["width"] == "102" and r["height"] == "20"


def test_theme_change_swaps_every_logo(app_page: Page) -> None:
    _set_theme(app_page, "light")
    app_page.evaluate(_MARK_JS, ["SEC", 2019])
    app_page.evaluate(_MARK_JS, ["Pac-12", 2026])
    assert app_page.evaluate(_SRC_JS) == [
        "logos/conf/southeastern-conference-before-2024.svg",
        "logos/conf/pac-12-conference-2026-present-official-site.svg",
    ]
    _set_theme(app_page, "dark")
    app_page.wait_for_function(
        "() => [...document.querySelectorAll('img.cf-logo')]"
        ".every((i) => i.getAttribute('src').startsWith('logos/dark/conf/'))"
    )
    assert app_page.evaluate(_SRC_JS) == [
        "logos/dark/conf/southeastern-conference-before-2024.svg",
        "logos/dark/conf/pac-12-conference-2026-present-official-site.svg",
    ]
    _set_theme(app_page, "light")
    app_page.wait_for_function(
        "() => [...document.querySelectorAll('img.cf-logo')]"
        ".every((i) => i.getAttribute('src').startsWith('logos/conf/'))"
    )


def test_every_era_file_loads_in_both_themes(app_page: Page) -> None:
    sizes = app_page.evaluate(
        """
        async () => {
          const m = await import('./modules/conf-logos.js');
          const names = ['SEC', 'Pac-12', 'Conference USA', 'Big 12', 'Mid-American'];
          const files = new Set();
          for (const name of names) {
            for (const season of [2015, 2026]) {
              const logo = m.conferenceLogoFor(name, season);
              files.add(logo.file);
              files.add(logo.darkFile);
            }
          }
          const out = [];
          for (const file of files) {
            const img = new Image();
            img.src = file;
            await img.decode().catch(() => null);
            out.push([file, img.naturalWidth]);
          }
          return out;
        }
        """
    )
    assert len(sizes) == 16
    assert all(width > 0 for _, width in sizes), sizes


@pytest.mark.parametrize("name", ["Big Sky", "FBS Independents", "__proto__", HOSTILE])
def test_names_without_a_logo_come_back_as_text(app_page: Page, name: str) -> None:
    r = app_page.evaluate(_MARK_JS, [name, 2019])
    assert r == {"kind": "text", "data": name, "imgs": 0}
