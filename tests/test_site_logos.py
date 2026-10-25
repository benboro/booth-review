"""Lint, manifest and logo-map checks for the vendored network logos (SHELL-05).

The SVGs under site/logos/ are third-party marks that the site serves, so each one
is parsed and held to an allowlist (no script, no external references), recorded in
a public manifest with its SHA-256, and cross-checked against site/modules/logos.js.
"""

from __future__ import annotations

import csv
import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LOGO_DIR = REPO_ROOT / "site" / "logos"
MANIFEST = LOGO_DIR / "manifest.csv"
LOGOS_JS = REPO_ROOT / "site" / "modules" / "logos.js"
NETWORK_JS = REPO_ROOT / "site" / "modules" / "network.js"

MAX_BYTES = 24 * 1024
BANNED_ELEMENTS = {"script", "foreignObject", "image"}
EXTERNAL = re.compile(r"(?:https?:)?//", re.I)
URL_SCHEME = re.compile(r"url\(\s*['\"]?\s*(?:https?:|//)", re.I)
NS_SVG = "http://www.w3.org/2000/svg"


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def lint_svg(data: bytes) -> list[str]:
    """Return a list of problems found in one SVG (empty means it passes)."""
    problems: list[str] = []
    if len(data) >= MAX_BYTES:
        problems.append("24 KB or larger")
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        return [*problems, "DOCTYPE or ENTITY declaration"]
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        return [*problems, f"not parseable: {exc}"]
    if _local(root.tag) != "svg":
        problems.append("root is not svg")
    if "viewBox" not in root.attrib:
        problems.append("missing viewBox")
    for el in root.iter():
        name = _local(el.tag)
        if name in BANNED_ELEMENTS:
            problems.append(f"<{name}> element")
        if name == "style" and el.text and ("@import" in el.text or URL_SCHEME.search(el.text)):
            problems.append("style @import or external url()")
        for attr, value in el.attrib.items():
            aname = _local(attr)
            if aname.lower().startswith("on"):
                problems.append(f"{aname} handler")
            if "javascript:" in value.lower():
                problems.append("javascript: value")
            if URL_SCHEME.search(value):
                problems.append("external url()")
            if (
                aname == "href"
                and not value.startswith("#")
                and (name == "use" or EXTERNAL.match(value))
            ):
                problems.append(f"external {name} href")
    return problems


def _manifest_rows() -> list[dict[str, str]]:
    with MANIFEST.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _logo_files() -> list[Path]:
    return sorted(LOGO_DIR.glob("*.svg"))


def _view_box(path: Path) -> tuple[float, float]:
    box = ET.fromstring(path.read_bytes()).attrib["viewBox"].replace(",", " ").split()
    return float(box[2]), float(box[3])


def _js_entries() -> dict[str, tuple[str, int, int, str, str]]:
    """Map each network id in logos.js to (file, width, height, box, dark_file).

    Handles inline object entries and ids that share a named const object.
    """
    text = LOGOS_JS.read_text(encoding="utf-8")
    obj = (
        r"\{\s*file:\s*'logos/([^']+)'\s*,\s*width:\s*(\d+)\s*,"
        r"\s*height:\s*(\d+)\s*,\s*box:\s*'(wordmark|badge)'\s*,"
        r"\s*darkFile:\s*'logos/dark/([^']+)'\s*\}"
    )
    consts = {
        m.group(1): (m.group(2), int(m.group(3)), int(m.group(4)), m.group(5), m.group(6))
        for m in re.finditer(r"const (\w+) = " + obj, text)
    }
    entries: dict[str, tuple[str, int, int, str, str]] = {}
    for m in re.finditer(r"\[\s*'([^']+)'\s*,\s*" + obj + r"\s*\]", text):
        entries[m.group(1)] = (m.group(2), int(m.group(3)), int(m.group(4)), m.group(5), m.group(6))
    for m in re.finditer(r"\[\s*'([^']+)'\s*,\s*(\w+)\s*\]", text):
        entries[m.group(1)] = consts[m.group(2)]
    return entries


GOOD = f'<svg xmlns="{NS_SVG}" viewBox="0 0 10 10"><path d="M0 0h10v10z"/></svg>'


def test_clean_svg_passes() -> None:
    assert lint_svg(GOOD.encode()) == []


@pytest.mark.parametrize(
    "bad",
    [
        f'<svg xmlns="{NS_SVG}" viewBox="0 0 1 1"><script>alert(1)</script></svg>',
        f'<svg xmlns="{NS_SVG}" viewBox="0 0 1 1" onload="x()"></svg>',
        f'<svg xmlns="{NS_SVG}" viewBox="0 0 1 1"><foreignObject/></svg>',
        f'<svg xmlns="{NS_SVG}" viewBox="0 0 1 1"><image href="a.png"/></svg>',
        f'<svg xmlns="{NS_SVG}" viewBox="0 0 1 1"><use href="http://x/a.svg#b"/></svg>',
        f'<svg xmlns="{NS_SVG}" viewBox="0 0 1 1"><use href="a.svg#b"/></svg>',
        f'<svg xmlns="{NS_SVG}" viewBox="0 0 1 1"><style>@import "x.css";</style></svg>',
        f'<svg xmlns="{NS_SVG}" viewBox="0 0 1 1"><style>a{{fill:url(https://x/y)}}</style></svg>',
        f'<svg xmlns="{NS_SVG}" viewBox="0 0 1 1"><path fill="url(https://x/y)"/></svg>',
        f'<svg xmlns="{NS_SVG}" viewBox="0 0 1 1"><a href="javascript:alert(1)"/></svg>',
        f'<svg xmlns="{NS_SVG}" viewBox="0 0 1 1"><a href="https://x"/></svg>',
        f'<!DOCTYPE svg [<!ENTITY a "b">]><svg xmlns="{NS_SVG}" viewBox="0 0 1 1"/>',
        f'<svg xmlns="{NS_SVG}"><path d="M0 0"/></svg>',
    ],
)
def test_lint_rejects(bad: str) -> None:
    assert lint_svg(bad.encode()) != []


def test_lint_rejects_oversize() -> None:
    padded = GOOD.replace("</svg>", "<!--" + "x" * MAX_BYTES + "--></svg>")
    assert any("24 KB" in p for p in lint_svg(padded.encode()))


def test_xmlns_alone_is_not_a_problem() -> None:
    xlink = "http://www.w3.org/1999/xlink"
    svg = f'<svg xmlns="{NS_SVG}" xmlns:xlink="{xlink}" viewBox="0 0 1 1"/>'
    assert lint_svg(svg.encode()) == []


def test_vendored_logos_lint_clean() -> None:
    files = _logo_files()
    assert len(files) == 24
    for path in files:
        assert lint_svg(path.read_bytes()) == [], path.name


def test_manifest_matches_files() -> None:
    rows = _manifest_rows()
    files = {p.name: p for p in _logo_files()}
    assert sorted(r["file"] for r in rows) == sorted(files)
    for row in rows:
        assert row["check"] == "pass", row["file"]
        for field in ("source_url", "licence", "approved", "retrieved"):
            assert row[field].strip(), (row["file"], field)
        assert row["render_box"] in {"wordmark", "badge"}
        assert row["sha256"] == hashlib.sha256(files[row["file"]].read_bytes()).hexdigest(), row[
            "file"
        ]


def test_logos_js_matches_files_and_sizes() -> None:
    entries = _js_entries()
    rows = _manifest_rows()
    files = {p.name for p in _logo_files()}
    assert {f for f, *_ in entries.values()} == files
    expected_ids = {i for r in rows for i in r["network_ids"].split(";")}
    assert set(entries) == expected_ids
    for row in rows:
        for net_id in row["network_ids"].split(";"):
            file, width, height, box, dark_file = entries[net_id]
            assert file == row["file"]
            assert dark_file == file
            assert box == row["render_box"]
            assert height == (14 if box == "wordmark" else 20)
            vb_w, vb_h = _view_box(LOGO_DIR / file)
            assert abs(width - round(height * vb_w / vb_h)) <= 1, net_id


def test_logos_js_uses_map_and_builder_avoids_bracket_lookup() -> None:
    js = LOGOS_JS.read_text(encoding="utf-8")
    assert "new Map(" in js
    assert "LOGOS.has(" in js
    builder = NETWORK_JS.read_text(encoding="utf-8")
    assert "LOGOS[" not in builder
    assert re.search(r"logoFor\(", builder)
    for banned in ("innerHTML", "insertAdjacentHTML", "outerHTML"):
        assert banned not in builder
        assert banned not in js
