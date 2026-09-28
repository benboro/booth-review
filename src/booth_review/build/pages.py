"""Render dist/site's `methodology.html` and `coverage.html`, plus the
shared page chrome (footer credit line, freshness stamps) every page uses
(D-13). Reads `docs/methodology.md`, `docs/known-gaps.md`, and a validated
`SiteData` -- never the CFBD API key, and never any file under data/vault.

The assemble/write split mirrors `build.site_data`: `render_methodology`
and `render_coverage` are pure "build the HTML string" functions;
`write_pages` is the only function that touches the filesystem, via
`transport.cache.atomic_write_bytes` like every other write in this
project. Output lives in `dist/site/` until Phase 5 deploys it.
"""

from __future__ import annotations

import html
import posixpath
import re
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import markdown

from booth_review.errors import SiteBuildError
from booth_review.transport.cache import atomic_write_bytes

if TYPE_CHECKING:
    from booth_review.contract.models import Freshness, SiteData

CREDIT_LINE_TEXT = (
    "Viewership: RatingsReference.com (CC BY 4.0), modified: filtered and "
    "joined with crew and game data · Crews: 506 Sports · "
    "Data provided by CollegeFootballData.com"
)

NAV: tuple[tuple[str, str], ...] = (
    ("Chart", "index.html"),
    ("Methodology", "methodology.html"),
    ("Coverage", "coverage.html"),
)

_CSP = (
    "default-src 'self'; script-src 'none'; style-src 'self'; img-src 'self'; "
    "object-src 'none'; base-uri 'none'; form-action 'none'"
)

_INCLUDE_MARKER = "<!-- include: known-gaps.md -->"
_ATX_HEADING_RE = re.compile(r"^(#{1,6})(\s.*)$")
_FENCE_RE = re.compile(r"^```")
_MD_HREF_RE = re.compile(r'href="([^"#?]+\.md)(#[^"]*)?"')

_GITHUB_BLOB_BASE = "https://github.com/benboro/booth-review/blob/main/"
_EN_DASH = "\N{EN DASH}"


def freshness_stamps(freshness: Freshness) -> tuple[str, str]:
    """The two footer freshness lines (UI-SPEC Copywriting Contract)."""
    crews = (
        f"Crews and scores through Week {freshness.crews_through_week}"
        if freshness.crews_through_week
        else "Crews and scores: not yet available this season"
    )
    viewership = (
        f"Viewership through Week {freshness.viewership_through_week}"
        if freshness.viewership_through_week
        else "Viewership: not yet available this season"
    )
    return crews, viewership


def footer_html(freshness: Freshness) -> str:
    """The `<footer>` body every page shares: Chart/Methodology/Coverage
    nav, both freshness stamps, and the verbatim D-16 credit line.
    """
    crews_stamp, viewership_stamp = freshness_stamps(freshness)
    nav_html = " · ".join(f'<a href="{href}">{html.escape(label)}</a>' for label, href in NAV)
    credit_html = (
        'Viewership: <a href="https://ratingsreference.com" '
        'rel="noopener noreferrer">RatingsReference.com</a> '
        '(<a href="https://creativecommons.org/licenses/by/4.0/" '
        'rel="noopener noreferrer">CC BY 4.0</a>), modified: filtered and '
        "joined with crew and game data · Crews: "
        '<a href="https://506sports.com" rel="noopener noreferrer">506 Sports</a> '
        "· Data provided by "
        '<a href="https://collegefootballdata.com" '
        'rel="noopener noreferrer">CollegeFootballData.com</a>'
    )
    freshness_line = f"{html.escape(crews_stamp)} · {html.escape(viewership_stamp)}"
    return (
        f'<nav aria-label="Site">{nav_html}</nav>'
        f'<p class="freshness">{freshness_line}</p>'
        f'<p class="credit-line">{credit_html}</p>'
    )


def page_html(title: str, body_html: str, freshness: Freshness) -> str:
    """Wrap `body_html` in a full HTML5 document: CSP meta (script-src
    'none' -- these pages never carry a `<script>`), the site stylesheet,
    a header link back to the chart, and the shared footer.
    """
    footer = footer_html(freshness)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{_CSP}">\n'
        f"<title>{html.escape(title)}</title>\n"
        '<link rel="stylesheet" href="style.css">\n'
        "</head>\n"
        "<body>\n"
        '<header><a href="index.html">booth-review</a></header>\n'
        f'<main class="page">{body_html}</main>\n'
        f'<footer class="site-footer">{footer}</footer>\n'
        "</body>\n"
        "</html>\n"
    )


def _demote_headings(text: str) -> str:
    """Demote every ATX heading by one level (`## X` -> `### X`), leaving
    fenced code blocks untouched.
    """
    in_fence = False
    out: list[str] = []
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        match = None if in_fence else _ATX_HEADING_RE.match(line)
        if match:
            out.append(f"#{match.group(1)}{match.group(2)}")
        else:
            out.append(line)
    return "\n".join(out)


def _known_gaps_body(text: str) -> str:
    """`docs/known-gaps.md` with its own `# ` title dropped and every
    remaining heading demoted by one level, ready to splice under
    methodology.md's own "## Known gaps" heading.
    """
    lines = text.splitlines()
    if lines and lines[0].startswith("#"):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    return _demote_headings("\n".join(lines))


def _rewrite_relative_md_links(rendered_html: str) -> str:
    """Point the rendered methodology's relative `.md` links somewhere that
    exists on the site (WR-08).

    Each relative href is resolved against `docs/` (where methodology.md
    lives), keeping any `#fragment`: `known-gaps.md` becomes an in-page
    anchor (its content is spliced in, not a separate page) -- `#known-gaps`,
    or the fragment itself for `known-gaps.md#x`; any other in-repo `.md`
    file points at its own GitHub blob, subdirectories included
    (`sources/506.md` -> `.../blob/main/docs/sources/506.md`). Absolute URLs
    (any scheme or host) and paths that climb out of the repo are left
    untouched.
    """

    def _replace(match: re.Match[str]) -> str:
        href, fragment = match.group(1), match.group(2) or ""
        parts = urlsplit(href)
        if parts.scheme or parts.netloc:
            return match.group(0)
        repo_path = posixpath.normpath(
            href.lstrip("/") if href.startswith("/") else posixpath.join("docs", href)
        )
        if repo_path == ".." or repo_path.startswith("../"):
            return match.group(0)
        if repo_path == "docs/known-gaps.md":
            return f'href="{fragment or "#known-gaps"}"'
        return f'href="{_GITHUB_BLOB_BASE}{repo_path}{fragment}"'

    return _MD_HREF_RE.sub(_replace, rendered_html)


def render_methodology(docs_dir: Path, site: SiteData) -> str:
    """Render `docs/methodology.md` to HTML, with `docs/known-gaps.md`
    spliced in at its include marker (D-13). Raises SiteBuildError --
    naming the missing file or marker only, never file content -- when
    either doc is missing or the marker is absent.
    """
    methodology_path = docs_dir / "methodology.md"
    if not methodology_path.is_file():
        raise SiteBuildError("docs/methodology.md not found")
    methodology_text = methodology_path.read_text(encoding="utf-8")
    if _INCLUDE_MARKER not in methodology_text:
        raise SiteBuildError("docs/methodology.md: known-gaps include marker missing")

    known_gaps_path = docs_dir / "known-gaps.md"
    if not known_gaps_path.is_file():
        raise SiteBuildError("docs/known-gaps.md not found")
    known_gaps_text = known_gaps_path.read_text(encoding="utf-8")

    combined = methodology_text.replace(_INCLUDE_MARKER, _known_gaps_body(known_gaps_text))
    renderer = markdown.Markdown(extensions=["tables", "toc"])
    body_html = _rewrite_relative_md_links(renderer.convert(combined))
    return page_html("Methodology · booth-review", body_html, site.freshness)


def _pct(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else _EN_DASH


def render_coverage(site: SiteData) -> str:
    """Render `coverage.html`: a season x network completeness table, then
    a season-level match/data-quality table, both from `site.coverage`
    (D-13/SITE-16). Every network name is html-escaped.
    """
    networks = site.lookups.networks
    coverage = site.coverage
    seasons = sorted({row.season for row in coverage})
    network_indices = sorted(
        {row.network for row in coverage if row.network is not None},
        key=lambda idx: (networks[idx].family, networks[idx].name),
    )

    counts_by_key: dict[tuple[int, int], int] = {
        (row.network, row.season): row.rated_telecasts
        for row in coverage
        if row.network is not None
    }
    totals_by_season: dict[int, int] = {
        row.season: row.rated_telecasts for row in coverage if row.network is None
    }

    header_cells = "".join(f'<th scope="col">{season}</th>' for season in seasons)
    body_rows: list[str] = []
    for idx in network_indices:
        name = html.escape(networks[idx].name)
        cells = "".join(
            f"<td>{counts_by_key.get((idx, season), _EN_DASH)}</td>" for season in seasons
        )
        body_rows.append(f'<tr><th scope="row">{name}</th>{cells}</tr>')
    total_cells = "".join(
        f"<td>{totals_by_season.get(season, _EN_DASH)}</td>" for season in seasons
    )
    body_rows.append(f'<tr><th scope="row">Total</th>{total_cells}</tr>')

    coverage_table = (
        '<div class="table-scroll"><table class="coverage-table">'
        f'<thead><tr><th scope="col">Network</th>{header_cells}</tr></thead>'
        f"<tbody>{''.join(body_rows)}</tbody></table></div>"
    )

    all_rows = sorted((row for row in coverage if row.network is None), key=lambda r: r.season)
    quality_rows = "".join(
        "<tr>"
        f"<td>{row.season}</td>"
        f"<td>{row.rated_telecasts}</td>"
        f"<td>{row.matched_game}</td>"
        f"<td>{row.matched_crew}</td>"
        f"<td>{_pct(row.match_rate)}</td>"
        f"<td>{row.excitement_present}</td>"
        f"<td>{row.pregame_present}</td>"
        f"<td>{row.duplicate_merges}</td>"
        f"<td>{row.combined_figures}</td>"
        "</tr>"
        for row in all_rows
    )
    quality_table = (
        '<div class="table-scroll"><table class="coverage-quality-table">'
        "<thead><tr>"
        '<th scope="col">Season</th>'
        '<th scope="col">Rated telecasts</th>'
        '<th scope="col">Matched to a game</th>'
        '<th scope="col">Matched with crew</th>'
        '<th scope="col">Match rate</th>'
        '<th scope="col">Excitement present</th>'
        '<th scope="col">Pre-game present</th>'
        '<th scope="col">Duplicate merges</th>'
        '<th scope="col">Combined figures</th>'
        "</tr></thead>"
        f"<tbody>{quality_rows}</tbody></table></div>"
    )

    total_rated = sum(totals_by_season.values())
    intro = (
        f"<p>{total_rated} rated telecasts across {len(seasons)} season(s) and "
        f"{len(network_indices)} network(s) (counts only). See "
        '<a href="methodology.html#known-gaps">the methodology page\'s known '
        'gaps section</a> for what "rated" does and does not include.</p>'
    )

    body = (
        "<h1>Coverage</h1>"
        f"{intro}"
        "<h2>Telecasts by network and season</h2>"
        f"{coverage_table}"
        "<h2>Match and data quality by season</h2>"
        f"{quality_table}"
    )
    return page_html("Coverage · booth-review", body, site.freshness)


def write_pages(out_dir: Path, site: SiteData, docs_dir: Path) -> list[str]:
    """Render and atomically write `methodology.html` and `coverage.html`
    under `out_dir`. Returns their out_dir-relative paths.
    """
    atomic_write_bytes(
        out_dir / "methodology.html", render_methodology(docs_dir, site).encode("utf-8")
    )
    atomic_write_bytes(out_dir / "coverage.html", render_coverage(site).encode("utf-8"))
    return ["methodology.html", "coverage.html"]
