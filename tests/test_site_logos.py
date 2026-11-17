"""Lint, manifest and logo-map checks for the vendored network logos (SHELL-05).

The SVGs under site/logos/ are third-party marks that the site serves, so each one
is parsed and held to an allowlist (no script, no external references), recorded in
a public manifest with its SHA-256, and cross-checked against site/modules/logos.js.
"""

from __future__ import annotations

import csv
import hashlib
import itertools
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


def _logo_svg_files() -> list[Path]:
    return sorted(LOGO_DIR.glob("*.svg"))


def _logo_files() -> list[Path]:
    """Every network logo: the SVGs plus the Mountain West PNG (never recoloured)."""
    return sorted([*LOGO_DIR.glob("*.svg"), *LOGO_DIR.glob("*.png")])


def _dims(path: Path) -> tuple[float, float]:
    """Aspect source: an SVG's viewBox, or a PNG's IHDR width and height."""
    if path.suffix == ".png":
        data = path.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", path.name
        return float(int.from_bytes(data[16:20], "big")), float(int.from_bytes(data[20:24], "big"))
    return _view_box(path)


def _view_box(path: Path) -> tuple[float, float]:
    box = ET.fromstring(path.read_bytes()).attrib["viewBox"].replace(",", " ").split()
    return float(box[2]), float(box[3])


def _js_consts() -> dict[str, tuple[str, int, int, str, str]]:
    """Each named const logo object in logos.js -> (file, width, height, box, dark_file)."""
    return {
        m.group(1): (m.group(2), int(m.group(3)), int(m.group(4)), m.group(5), m.group(6))
        for m in re.finditer(r"const (\w+) = " + _JS_OBJ, LOGOS_JS.read_text(encoding="utf-8"))
    }


def _js_eras() -> dict[str, list[tuple[int, str]]]:
    """Each network id in logos.js's ERAS map -> [(first season, const name), ...]."""
    text = LOGOS_JS.read_text(encoding="utf-8")
    block = text.split("const ERAS = new Map([", 1)[1].split("]);", 1)[0]
    return {
        m.group(1): [(int(y), c) for y, c in re.findall(r"\[(\d{4}),\s*(\w+)\]", m.group(2))]
        for m in re.finditer(r"\['([^']+)',\s*\[(.*?)\]\],?\n", block)
    }


_JS_OBJ = (
    r"\{\s*file:\s*'logos/([^']+)'\s*,\s*width:\s*(\d+)\s*,"
    r"\s*height:\s*(\d+)\s*,\s*box:\s*'(wordmark|badge)'\s*,"
    r"\s*darkFile:\s*'logos/dark/([^']+)'\s*\}"
)


def _js_entries() -> dict[str, tuple[str, int, int, str, str]]:
    """Map each network id in logos.js's LOGOS map to (file, width, height, box, dark_file).

    Handles inline object entries and ids that share a named const object; for a network
    with eras this is its newest mark.
    """
    text = LOGOS_JS.read_text(encoding="utf-8").split("const ERAS = new Map([", 1)[0]
    consts = _js_consts()
    entries: dict[str, tuple[str, int, int, str, str]] = {}
    for m in re.finditer(r"\[\s*'([^']+)'\s*,\s*" + _JS_OBJ + r"\s*\]", text):
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
    files = _logo_svg_files()
    assert len(files) == 31
    for path in files:
        assert lint_svg(path.read_bytes()) == [], path.name


def test_network_png_is_small_rgba_and_alone() -> None:
    pngs = sorted(LOGO_DIR.glob("*.png"))
    assert [p.name for p in pngs] == ["mountain-west-network.png"]
    data = pngs[0].read_bytes()
    assert len(data) < MAX_BYTES
    assert data[25] == 6  # RGBA


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
        if row["file"].endswith(".png"):
            # The brand's own dark-background file sits in dark-src/ and ships unchanged.
            dark = LOGO_DIR / "dark-src" / row["file"]
            assert row["dark_sha256"] == hashlib.sha256(dark.read_bytes()).hexdigest()
            assert _dims(dark) == _dims(files[row["file"]]), row["file"]


def _file_entries() -> dict[str, tuple[str, int, int, str, str]]:
    """Every logo file logos.js draws -> its entry: LOGOS's entries plus every era's."""
    consts = _js_consts()
    by_file = {e[0]: e for e in _js_entries().values()}
    for eras in _js_eras().values():
        for _season, name in eras:
            by_file[consts[name][0]] = consts[name]
    return by_file


def test_logos_js_matches_files_and_sizes() -> None:
    entries = _js_entries()
    by_file = _file_entries()
    rows = _manifest_rows()
    files = {p.name for p in _logo_files()}
    assert set(by_file) == files
    expected_ids = {i for r in rows for i in r["network_ids"].split(";")}
    assert set(entries) == expected_ids
    for row in rows:
        file, width, height, box, dark_file = by_file[row["file"]]
        assert dark_file == file
        assert box == row["render_box"]
        # The Mountain West network PNG is drawn 24px high (its brand guide's minimum).
        assert height == (14 if box == "wordmark" else 24 if file.endswith(".png") else 20)
        vb_w, vb_h = _dims(LOGO_DIR / file)
        assert abs(width - round(height * vb_w / vb_h)) <= 1, file
        if not row["seasons_from"]:
            # One mark for every season: each id's LOGOS entry is this file.
            for net_id in row["network_ids"].split(";"):
                assert entries[net_id][0] == row["file"], net_id


def test_logo_eras_match_manifest_seasons() -> None:
    """A network with several marks lists each in the manifest with its season range, the
    ranges meet end to end, the newest is open-ended, and logos.js's ERAS and LOGOS agree."""
    consts = _js_consts()
    eras = _js_eras()
    entries = _js_entries()
    by_id: dict[str, list[dict[str, str]]] = {}
    for row in _manifest_rows():
        if row["seasons_from"]:
            for net_id in row["network_ids"].split(";"):
                by_id.setdefault(net_id, []).append(row)
        else:
            assert not row["seasons_to"], row["file"]
    assert set(by_id) == set(eras) == {"sec-network-plus"}
    for net_id, rows in by_id.items():
        rows.sort(key=lambda r: int(r["seasons_from"]))
        assert [(int(r["seasons_from"]), r["file"]) for r in rows] == [
            (season, consts[name][0]) for season, name in eras[net_id]
        ]
        for older, newer in itertools.pairwise(rows):
            assert int(older["seasons_to"]) + 1 == int(newer["seasons_from"]), net_id
        assert rows[-1]["seasons_to"] == ""
        assert entries[net_id][0] == rows[-1]["file"]


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
