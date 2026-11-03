"""Lint, manifest, era and logo-map checks for the conference logos (Phase 28, D-09..D-18).

The SVGs under site/logos/conf/ are third-party marks that ship to every visitor, so
each one is held to the same lint as the network logos, recorded in its own manifest
with a SHA-256 and the user's approval, and cross-checked against
site/modules/conf-logos.js. These tests read only the public files under site/.
"""

from __future__ import annotations

import csv
import hashlib
import re
from collections import defaultdict
from itertools import pairwise
from pathlib import Path

from test_site_logos import _view_box, lint_svg

REPO_ROOT = Path(__file__).resolve().parents[1]
CONF_DIR = REPO_ROOT / "site" / "logos" / "conf"
CONF_MANIFEST = CONF_DIR / "manifest.csv"
CONF_JS = REPO_ROOT / "site" / "modules" / "conf-logos.js"

HEADER = (
    "conference,seasons_from,seasons_to,file,source_file,source_url,retrieved,licence,"
    "mark,render_box,edit,check,approved,sha256,dark_sha256"
)
MULTI_ERA = {"SEC", "Conference USA", "Pac-12"}
FBS_CONFERENCES = {
    "ACC",
    "American Athletic",
    "Big 12",
    "Big Ten",
    "Conference USA",
    "Mid-American",
    "Mountain West",
    "Pac-12",
    "SEC",
    "Sun Belt",
}
FIRST_SEASON = 2014


def conf_files() -> list[Path]:
    return sorted(CONF_DIR.glob("*.svg"))


def conf_rows() -> list[dict[str, str]]:
    with CONF_MANIFEST.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _eras_by_conference() -> dict[str, list[dict[str, str]]]:
    eras: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in conf_rows():
        eras[row["conference"]].append(row)
    for rows in eras.values():
        rows.sort(key=lambda r: int(r["seasons_from"]))
    return eras


def test_conf_logos_lint_clean_and_have_no_text() -> None:
    files = conf_files()
    assert files
    for path in files:
        data = path.read_bytes()
        assert lint_svg(data) == [], path.name
        assert b"<text" not in data, path.name


def test_never_ships_rejected_or_unused_files() -> None:
    names = [p.name for p in conf_files()]
    assert not [n for n in names if "west-coast" in n or "logotyp" in n]


def test_conf_manifest_header() -> None:
    first = CONF_MANIFEST.read_text(encoding="utf-8").splitlines()[0]
    assert first == HEADER


def test_conf_manifest_matches_files() -> None:
    rows = conf_rows()
    files = {p.name: p for p in conf_files()}
    assert sorted(r["file"] for r in rows) == sorted(files)
    for row in rows:
        assert row["check"] == "pass", row["file"]
        for field in ("source_url", "licence", "approved", "retrieved"):
            assert row[field].strip(), (row["file"], field)
        assert "PROPOSED" not in row["source_url"], row["file"]
        assert row["sha256"] == hashlib.sha256(files[row["file"]].read_bytes()).hexdigest(), row[
            "file"
        ]


def test_eras_are_contiguous_and_start_in_2014() -> None:
    for conference, rows in _eras_by_conference().items():
        assert int(rows[0]["seasons_from"]) == FIRST_SEASON, conference
        for earlier, later in pairwise(rows):
            assert earlier["seasons_to"], conference
            assert int(earlier["seasons_to"]) + 1 == int(later["seasons_from"]), conference
        assert rows[-1]["seasons_to"] == "", conference


def test_only_ruled_conferences_have_more_than_one_logo() -> None:
    # D-10: any other conference needs the user's ruling before it gains a second era.
    multi = {c for c, rows in _eras_by_conference().items() if len(rows) > 1}
    assert multi == MULTI_ERA


_ENTRY = (
    r"\{\s*file:\s*'logos/conf/([^']+)'\s*,\s*width:\s*(\d+)\s*,\s*height:\s*(\d+)\s*,"
    r"\s*scale:\s*(\d+\.\d\d)\s*,\s*darkFile:\s*'logos/dark/conf/([^']+)'\s*\}"
)
SCALE_MIN, SCALE_MAX = 0.55, 1.25


def _js_consts() -> dict[str, tuple[str, int, int, str]]:
    """Map each named entry in conf-logos.js to (file, width, height, dark_file)."""
    text = CONF_JS.read_text(encoding="utf-8")
    return {
        m.group(1): (m.group(2), int(m.group(3)), int(m.group(4)), m.group(6))
        for m in re.finditer(r"const (\w+) = " + _ENTRY, text)
    }


def _js_scales() -> dict[str, float]:
    """Map each logo file in conf-logos.js to its area scale."""
    text = CONF_JS.read_text(encoding="utf-8")
    return {m.group(1): float(m.group(4)) for m in re.finditer(_ENTRY, text)}


def _js_eras() -> dict[str, list[tuple[int, str]]]:
    """Map each conference in ERAS to its [(first season, const name), ...]."""
    text = CONF_JS.read_text(encoding="utf-8")
    body = text.split("const ERAS = new Map([", 1)[1].split("]);", 1)[0]
    eras: dict[str, list[tuple[int, str]]] = {}
    for m in re.finditer(
        r"\[\s*'([^']+)'\s*,\s*\[((?:\s*\[\s*\d+\s*,\s*\w+\s*\]\s*,?)+)\]\s*\]", body
    ):
        eras[m.group(1)] = [
            (int(e.group(1)), e.group(2))
            for e in re.finditer(r"\[\s*(\d+)\s*,\s*(\w+)\s*\]", m.group(2))
        ]
    return eras


def test_conf_js_entries_match_files_and_sizes() -> None:
    consts = _js_consts()
    files = sorted(p.name for p in conf_files())
    assert sorted(f for f, *_ in consts.values()) == files
    for name, (file, width, height, dark_file) in consts.items():
        assert dark_file == file, name
        assert height == 20, name
        vb_w, vb_h = _view_box(CONF_DIR / file)
        assert abs(width - round(height * vb_w / vb_h)) <= 1, name


def test_every_logo_has_a_clamped_area_scale() -> None:
    scales = _js_scales()
    assert sorted(scales) == sorted(p.name for p in conf_files())
    for file, scale in scales.items():
        assert SCALE_MIN <= scale <= SCALE_MAX, file


def test_area_scale_shrinks_wordmarks_and_grows_shields() -> None:
    # The wide wordmarks carry the most ink per unit of height, so they draw smallest; the
    # shields grow. The rule itself (equal opaque area) is checked in the browser by
    # tests/e2e/test_site_conf_logo_marks.py.
    scales = _js_scales()
    for file in (
        "atlantic-coast-conference.svg",
        "big-ten-conference.svg",
        "conference-usa-2013-2023.svg",
        "conference-usa-2023-present.svg",
    ):
        assert scales[file] < 1, file
    for file in (
        "mid-american-conference.svg",
        "mountain-west-conference.svg",
        "pac-12-conference-before-2026.svg",
        "pac-12-conference-2026-present-official-site.svg",
    ):
        assert scales[file] > 1, file


def test_area_scale_reaches_the_drawn_logo() -> None:
    js = CONF_JS.read_text(encoding="utf-8")
    assert "img.style.setProperty('--cf-scale', String(entry.scale));" in js
    css = (REPO_ROOT / "site" / "style.css").read_text(encoding="utf-8")
    assert "height: calc(var(--cf-h) * var(--cf-scale, 1));" in css
    assert "margin-block: calc(var(--cf-h) * (1 - var(--cf-scale, 1)) / 2);" in css


def test_conf_js_eras_match_manifest() -> None:
    consts = _js_consts()
    js_eras = _js_eras()
    manifest = _eras_by_conference()
    assert set(js_eras) == set(manifest) == FBS_CONFERENCES
    used = [const for eras in js_eras.values() for _, const in eras]
    assert sorted(used) == sorted(consts)
    for conference, rows in manifest.items():
        js = js_eras[conference]
        assert [s for s, _ in js] == [int(r["seasons_from"]) for r in rows], conference
        assert [consts[c][0] for _, c in js] == [r["file"] for r in rows], conference


def test_conf_js_uses_map_and_never_builds_html() -> None:
    js = CONF_JS.read_text(encoding="utf-8")
    assert "new Map(" in js
    assert "ERAS.has(" in js
    assert "ERAS[" not in js
    assert "D-10" in js
    for banned in ("innerHTML", "insertAdjacentHTML", "outerHTML"):
        assert banned not in js


def test_build_logo_names_match_the_eras_keys() -> None:
    """The build's copy of the ERAS keys (for its no-logo warning) matches conf-logos.js."""
    from booth_review.build.conf_logos import CONFERENCE_LOGO_NAMES

    assert set(_js_eras()) == CONFERENCE_LOGO_NAMES
