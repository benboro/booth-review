"""Guard the phone/desktop breakpoint: 480px and under is phone, 481px and up is desktop."""

import re
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
SUFFIXES = {".css", ".js", ".html"}
# Max-widths other than the phone breakpoint, each with a reason.
_NARROW = "narrow-phone refinement nested inside the 480px phone range"
ALLOWED_MAX_WIDTHS: dict[str, str] = {
    "359": _NARROW,
    "360": _NARROW,
    "374": _NARROW,
    "420": _NARROW,
    "1279": "desktop-narrow switch of the MLB postseason LCS round head (16-UI-SPEC)",
}


def _site_files() -> list[Path]:
    return [
        p
        for p in SITE.rglob("*")
        if p.is_file() and p.suffix in SUFFIXES and "vendor" not in p.relative_to(SITE).parts
    ]


_OLD_BREAKPOINT = re.compile(r"(?:max|min)-width:\s*64[01](?:px)?\b")


def test_no_640_or_641_breakpoints_remain() -> None:
    # Only width queries count: a 640px size (e.g. a scroll box's max-height) is not a breakpoint.
    bad = [
        f"{p.relative_to(SITE)}: {m.group(0)}"
        for p in _site_files()
        for m in _OLD_BREAKPOINT.finditer(p.read_text(encoding="utf-8"))
    ]
    assert not bad, bad


def test_css_max_width_media_rules_use_480() -> None:
    css = (SITE / "style.css").read_text(encoding="utf-8")
    widths = re.findall(r"@media[^{]*?max-width:\s*(\d+)px", css)
    assert widths, "expected phone media rules in style.css"
    bad = [w for w in widths if w != "480" and w not in ALLOWED_MAX_WIDTHS]
    assert not bad, bad


def test_css_min_width_boundary_is_481() -> None:
    css = (SITE / "style.css").read_text(encoding="utf-8")
    assert "(min-width: 481px)" in css


def test_breakpoints_module_exports_phone_query() -> None:
    text = (SITE / "modules" / "breakpoints.js").read_text(encoding="utf-8")
    assert "export const PHONE_QUERY = '(max-width: 480px)';" in text


def test_js_max_width_reads_use_phone_query() -> None:
    offenders = []
    for p in _site_files():
        if p.suffix != ".js" or p.name == "breakpoints.js":
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if "matchMedia" in line and "max-width" in line:
                if p.name == "toolbar-fit.js" and "'(max-width: 480px)'" in line:
                    continue
                offenders.append(f"{p.relative_to(SITE)}: {line.strip()}")
    assert not offenders, offenders


def test_phone_query_consumers_import_it() -> None:
    for rel in (
        "app.js",
        "modules/filters.js",
        "sports/nfl/filters.js",
        "sports/nfl/index.js",
        "sports/mlb/index.js",
    ):
        text = (SITE / rel).read_text(encoding="utf-8")
        assert "import { PHONE_QUERY }" in text, rel
