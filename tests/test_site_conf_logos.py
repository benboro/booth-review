"""Lint, manifest, era and logo-map checks for the conference logos (Phase 28, D-09..D-18).

The SVGs under site/logos/conf/ are third-party marks that ship to every visitor, so
each one is held to the same lint as the network logos, recorded in its own manifest
with a SHA-256 and the user's approval, and cross-checked against
site/modules/conf-logos.js. These tests read only the public files under site/.
"""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from itertools import pairwise
from pathlib import Path

from test_site_logos import lint_svg

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
