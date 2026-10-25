"""Source guard for SHELL-01/SHELL-02: light everywhere, one theme hook."""

from __future__ import annotations

import re
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
READERS = ("app.js", "sports/nfl/index.js", "sports/mlb/index.js")


def _site_files() -> list[Path]:
    return [
        p
        for p in SITE.rglob("*")
        if p.is_file()
        and p.suffix in {".css", ".js", ".html"}
        and "vendor" not in p.relative_to(SITE).parts
    ]


def test_no_os_colour_scheme_reads() -> None:
    offenders = [
        str(p.relative_to(SITE))
        for p in _site_files()
        if "prefers-color-scheme" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_theme_module_shape() -> None:
    text = (SITE / "modules" / "theme.js").read_text(encoding="utf-8")
    assert "export function currentTheme" in text
    assert "export function onThemeChange" in text
    assert "matchMedia" not in text


def test_readers_use_theme_module() -> None:
    for rel in READERS:
        text = (SITE / rel).read_text(encoding="utf-8")
        assert re.search(r"from '[./]*(?:modules/)?theme\.js'", text), rel
    pill = (SITE / "modules" / "pill.js").read_text(encoding="utf-8")
    assert "export { currentTheme } from './theme.js';" in pill


def test_css_dark_placeholder_and_light_color_scheme() -> None:
    css = (SITE / "style.css").read_text(encoding="utf-8")
    assert '[data-theme="dark"]' in css
    root = re.search(r":root\s*\{(.*?)\n\}", css, re.S)
    assert root is not None
    assert "color-scheme: light" in root.group(1)


def test_index_html_is_statically_light() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert html.count('data-theme="light"') == 1, "13-01 writes data-theme on the html element"


def test_theme_init_shape() -> None:
    text = (SITE / "theme-init.js").read_text(encoding="utf-8")
    assert "'bl-theme'" in text
    assert "Switch to dark theme" in text
    assert "Switch to light theme" in text
    assert "matchMedia" not in text
    for line in text.splitlines():
        if "localStorage" in line:
            assert "try {" in line, line


def test_theme_init_reapplies_the_theme_on_a_bfcache_restore() -> None:
    # Review 6a: a page restored from the back/forward cache keeps its old data-theme, so a
    # toggle on another page would not show; pageshow with persisted re-reads the stored theme.
    text = (SITE / "theme-init.js").read_text(encoding="utf-8")
    assert "window.addEventListener('pageshow', function (e) {" in text
    assert "if (e.persisted) apply(stored());" in text


def test_theme_init_is_the_only_writer() -> None:
    offenders = [
        str(p.relative_to(SITE))
        for p in _site_files()
        if p.suffix == ".js"
        and p.name != "theme-init.js"
        and re.search(
            r"setAttribute\('data-theme'|dataset\.theme\s*=(?!=)",
            p.read_text(encoding="utf-8"),
        )
    ]
    assert offenders == []


def test_index_loads_theme_init_before_stylesheet() -> None:
    lines = (SITE / "index.html").read_text(encoding="utf-8").splitlines()
    tag = '<script src="theme-init.js"></script>'
    assert lines.count(tag) == 1
    i = lines.index(tag)
    assert lines[i + 1] == '<link rel="stylesheet" href="style.css">'
    assert any(line.startswith('<meta name="color-scheme"') for line in lines[:i])


def test_index_has_one_toggle() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert html.count('id="theme-toggle"') == 1
    button = re.search(r"<button[^>]*id=\"theme-toggle\"[^>]*>", html)
    assert button is not None
    tag = button.group(0)
    for needle in (
        'type="button"',
        " hidden",
        'aria-label="Switch to dark theme"',
        'title="Switch to dark theme"',
    ):
        assert needle in tag, needle
    assert "aria-pressed" not in tag
    assert "style=" not in tag
