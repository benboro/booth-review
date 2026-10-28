"""Guards for the Phase 26 copy sweep: no middle dots in site code or built pages (except the
three kept crew-pair uses), and no HTML-string DOM writes in the view code."""

from __future__ import annotations

import json
import re
from pathlib import Path

from booth_review.build.pages import footer_html, write_pages
from booth_review.contract.models import validate_site_data

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE = REPO_ROOT / "site"
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "contract" / "site-data.fixture.json"

DOT = "·"
# The five spellings of the middle dot: the character, two JS escapes, two HTML entities.
DOT_FORMS = (DOT, "\\u00b7", "\\u00B7", "&middot;", "&#183;")

# The only sanctioned dots (the owner kept the crew pair, "Fowler · Herbstreit"): file and the
# exact code substring.
ALLOWLIST = (
    ("site/modules/pill.js", "sep.textContent = ' " + DOT + " ';"),
    ("site/modules/weekend.js", "text: `${pbp} " + DOT + " ${analyst}`"),
    ("site/modules/weekend-view.js", ".replace(/ " + DOT + " /g, ' and ')"),
)

BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
HTML_WRITE = re.compile(r"\binnerHTML\b|\bouterHTML\s*=|\binsertAdjacentHTML\b")


def _blank(match: re.Match[str]) -> str:
    """Replace a comment with nothing but its newlines so line numbers stay true."""
    return "\n" * match.group(0).count("\n")


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Numbered code lines of a site file: block comments, HTML comments and whole-line `//`
    comments removed."""
    text = path.read_text(encoding="utf-8")
    text = BLOCK_COMMENT.sub(_blank, text)
    if path.suffix == ".html":
        text = HTML_COMMENT.sub(_blank, text)
    lines = text.splitlines()
    if path.suffix == ".js":
        lines = ["" if line.lstrip().startswith("//") else line for line in lines]
    return list(enumerate(lines, start=1))


def _site_files(*suffixes: str, under: tuple[str, ...] = ()) -> list[Path]:
    found = []
    for path in sorted(SITE.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes or "vendor" in path.parts:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        if under and not any(rel.startswith(prefix) for prefix in under):
            continue
        found.append(path)
    return found


def _is_allowed(rel: str, line: str) -> bool:
    return any(rel == file and snippet in line for file, snippet in ALLOWLIST)


def test_allowlist_has_exactly_three_entries() -> None:
    assert len(ALLOWLIST) == 3


def test_no_middle_dot_in_site_code() -> None:
    offenders: list[str] = []
    for path in _site_files(".js", ".html", ".css"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        for number, line in _code_lines(path):
            if any(form in line for form in DOT_FORMS) and not _is_allowed(rel, line):
                offenders.append(f"{rel}:{number}:{line.strip()}")
    assert not offenders, "\n".join(offenders)


def test_each_allowlisted_dot_is_still_there_exactly_once() -> None:
    for rel, snippet in ALLOWLIST:
        hits = [number for number, line in _code_lines(REPO_ROOT / rel) if snippet in line]
        assert len(hits) == 1, f"{rel}: {snippet!r} found {len(hits)} times"


def test_no_middle_dot_in_built_static_pages(tmp_path: Path) -> None:
    site = validate_site_data(json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))
    written = write_pages(tmp_path, site, REPO_ROOT / "docs", nfl=True, mlb=True)
    outputs = {name: (tmp_path / name).read_text(encoding="utf-8") for name in written}
    outputs["footer"] = footer_html(site.freshness)
    offenders = [
        f"{name}: {form!r}" for name, text in outputs.items() for form in DOT_FORMS if form in text
    ]
    assert not offenders, offenders


def test_no_html_string_writes_in_view_code() -> None:
    offenders: list[str] = []
    for path in _site_files(".js", under=("site/modules/", "site/sports/")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        offenders.extend(
            f"{rel}:{number}:{line.strip()}"
            for number, line in _code_lines(path)
            if HTML_WRITE.search(line)
        )
    assert not offenders, "\n".join(offenders)
