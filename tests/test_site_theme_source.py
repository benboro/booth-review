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
        str(p.relative_to(SITE)) for p in _site_files() if "prefers-color-scheme" in p.read_text()
    ]
    assert offenders == []


def test_theme_module_shape() -> None:
    text = (SITE / "modules" / "theme.js").read_text()
    assert "export function currentTheme" in text
    assert "export function onThemeChange" in text
    assert "matchMedia" not in text


def test_readers_use_theme_module() -> None:
    for rel in READERS:
        text = (SITE / rel).read_text()
        assert re.search(r"from '[./]*(?:modules/)?theme\.js'", text), rel
    pill = (SITE / "modules" / "pill.js").read_text()
    assert "export { currentTheme } from './theme.js';" in pill


def test_css_dark_placeholder_and_light_color_scheme() -> None:
    css = (SITE / "style.css").read_text()
    assert '[data-theme="dark"]' in css
    root = re.search(r":root\s*\{(.*?)\n\}", css, re.S)
    assert root is not None
    assert "color-scheme: light" in root.group(1)


def test_index_html_is_statically_light() -> None:
    html = (SITE / "index.html").read_text()
    assert html.count('data-theme="light"') == 1, "13-01 writes data-theme on the html element"
