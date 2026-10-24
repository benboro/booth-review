"""Tests for build/pages.py: footer/freshness chrome and the Markdown-
rendered methodology and coverage pages (D-13).

Uses the synthetic contract fixture (tests/fixtures/contract/) and this
repo's own committed docs/ directory for the happy-path methodology
render; tmp_path docs dirs cover the missing-file/marker error cases.
Never reads data/vault.
"""

from __future__ import annotations

import copy
import html
import json
import re
from pathlib import Path

import pytest

from booth_review.build.pages import (
    CREDIT_LINE_TEXT,
    NAV,
    footer_html,
    freshness_stamps,
    render_coverage,
    render_methodology,
    write_pages,
)
from booth_review.contract.models import Freshness, validate_site_data
from booth_review.errors import SiteBuildError

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "contract" / "site-data.fixture.json"


def _load_fixture() -> dict[str, object]:
    data: dict[str, object] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return data


def _fixture_site():  # type: ignore[no-untyped-def]
    return validate_site_data(_load_fixture())


def _strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


def test_freshness_stamps_with_weeks() -> None:
    freshness = Freshness(season=2026, crews_through_week="5", viewership_through_week="4")
    assert freshness_stamps(freshness) == (
        "Crews and scores through Week 5",
        "Viewership through Week 4",
    )


def test_freshness_stamps_with_none() -> None:
    freshness = Freshness(season=2026)
    assert freshness_stamps(freshness) == (
        "Crews and scores: not yet available this season",
        "Viewership: not yet available this season",
    )


def test_footer_html_has_credit_line_once_and_nav_and_credit_links() -> None:
    freshness = Freshness(season=2026, crews_through_week="5", viewership_through_week="4")
    footer = footer_html(freshness)

    plain = _strip_tags(footer)
    assert plain.count(CREDIT_LINE_TEXT) == 1

    for _label, href in NAV:
        assert f'href="{href}"' in footer

    for href in (
        "https://ratingsreference.com",
        "https://creativecommons.org/licenses/by/4.0/",
        "https://506sports.com",
        "https://collegefootballdata.com",
    ):
        assert f'href="{href}"' in footer

    assert plain.count("Network logos are trademarks of their owners, shown only to identify") == 1
    assert plain.count("they are not covered by this site's MIT license.") == 1
    assert plain.count("used under the SIL Open Font License 1.1.") == 1
    assert footer.count('class="trademark-line"') == 1
    assert footer.count('class="type-line"') == 1
    for href in (
        "fonts/OFL-crimson-text.txt",
        "fonts/OFL-roboto.txt",
        "fonts/OFL-roboto-condensed.txt",
    ):
        assert f'href="{href}"' in footer


def test_render_methodology_includes_known_gaps_demoted_and_no_marker() -> None:
    result = render_methodology(REPO_ROOT / "docs", _fixture_site())

    assert 'id="the-2025-excitement-break"' in result
    assert 'id="the-y-axis-viewers-excitement-points-or-margin"' in result
    assert 'id="known-gaps"' in result
    assert "include: known-gaps.md" not in result
    assert 'href="#known-gaps"' in result
    assert 'href="known-gaps.md"' not in result
    assert "<h3" in result
    assert "<table" in result
    assert "<script" not in result
    assert "script-src 'none'" in result
    assert 'href="style.css"' in result


def test_render_methodology_explains_caps_points_margin_and_bands() -> None:
    result = render_methodology(REPO_ROOT / "docs", _fixture_site())

    assert 'id="the-y-axis-viewers-excitement-points-or-margin"' in result
    for phrase in (
        "12+",
        "120+",
        "70+",
        "Hover or tap the dot to see its real number",
        "No final score",
        "a faint gold band covers each season's bowl games and playoff games",
    ):
        assert phrase in result
    assert "about 23" not in result
    assert "end of their own season's block" not in result


def test_render_methodology_explains_how_filters_display() -> None:
    result = render_methodology(REPO_ROOT / "docs", _fixture_site())

    assert 'id="how-filters-display"' in result
    assert "always hides" not in result
    assert "works the same way" in result
    assert "4 or more keep them at normal size even though" in result
    assert "Head-to-head" in result
    assert "fades the games it excludes" in result
    # The per-season counts are facet counts: every filter but the season range.
    assert "except the season range itself" in result
    for phrase in (
        "Named games.",
        "grouped by franchise",
        "latest name",
        "first regular-season meeting",
        "conference-championship",
        "or a named game",
    ):
        assert phrase in result
    assert "stand out against them" in result
    assert "1 to 3 network families" in result
    assert "With a filter active, the games that pass it are drawn like rated dots" not in result


def test_render_methodology_explains_the_spread_axis() -> None:
    result = render_methodology(REPO_ROOT / "docs", _fixture_site())

    assert "The x-axis: spread, excitement, and date" in result
    assert "offseason" in result
    assert "kickoff time" in result
    assert "favorite won" in result
    assert "underdog won" in result
    assert "before kickoff" in result
    assert "tied" in result
    assert "Pre-game" not in result
    assert "Result vs spread" not in result
    assert "negative absolute value" not in result
    # The chart draws the zero line solid (chart.js `dash: 'solid'`).
    assert "dashed" not in result


def test_render_coverage_header_reads_spread() -> None:
    result = render_coverage(_fixture_site())

    assert '<th scope="col">Spread</th>' in result
    assert "Pre-game present" not in result


def test_render_methodology_raises_without_marker(tmp_path: Path) -> None:
    (tmp_path / "methodology.md").write_text(
        "# Methodology\n\nNo include marker on this page.\n", encoding="utf-8"
    )
    (tmp_path / "known-gaps.md").write_text("# Known Gaps\n\n## Scope\n\ntext\n", encoding="utf-8")

    with pytest.raises(SiteBuildError):
        render_methodology(tmp_path, _fixture_site())


def test_render_methodology_raises_when_missing(tmp_path: Path) -> None:
    with pytest.raises(SiteBuildError):
        render_methodology(tmp_path, _fixture_site())


def test_render_coverage_says_rated_only_and_links_known_gaps() -> None:
    result = render_coverage(_fixture_site())
    assert "These counts cover rated games only;" in result
    assert result.count('href="methodology.html#known-gaps"') == 1


def test_render_coverage_table_structure() -> None:
    site = _fixture_site()
    result = render_coverage(site)

    assert "<table" in result
    assert "Total" in result
    for season in sorted({row.season for row in site.coverage}):
        assert f'<th scope="col">{season}</th>' in result
    assert "<script" not in result
    assert "script-src 'none'" in result
    assert 'href="style.css"' in result


def test_render_coverage_has_hand_confirmed_column() -> None:
    """D-13, AUDIT-04: the patched-crew count sits right after 'Matched with crew'."""
    payload = copy.deepcopy(_load_fixture())
    coverage = payload["coverage"]
    assert isinstance(coverage, list)
    all_row = next(r for r in coverage if r["season"] == 2026 and r["network"] is None)
    all_row.update(rated_telecasts=4, matched_game=4, matched_crew=4, matched_crew_patched=3)
    result = render_coverage(validate_site_data(payload))

    assert (
        '<th scope="col">Matched with crew</th><th scope="col">Of which hand-confirmed</th>'
        in result
    )
    # Season, rated, matched to a game, matched with crew, then the patched count.
    assert "<tr><td>2026</td><td>4</td><td>4</td><td>4</td><td>3</td>" in result


def test_render_coverage_has_espn_press_room_backup_column() -> None:
    """04.19 D-13: the backup-crew count sits right after the hand-confirmed
    count, read from matched_crew_backup and never folded into it."""
    payload = copy.deepcopy(_load_fixture())
    coverage = payload["coverage"]
    assert isinstance(coverage, list)
    all_row = next(r for r in coverage if r["season"] == 2026 and r["network"] is None)
    all_row.update(
        rated_telecasts=5,
        matched_game=5,
        matched_crew=5,
        matched_crew_patched=2,
        matched_crew_backup=1,
    )
    result = render_coverage(validate_site_data(payload))

    assert (
        '<th scope="col">Of which hand-confirmed</th>'
        '<th scope="col">Of which ESPN backup</th>'
        '<th scope="col">Match rate</th>' in result
    )
    # Season, rated, matched to a game, matched with crew, hand-confirmed, backup.
    assert "<tr><td>2026</td><td>5</td><td>5</td><td>5</td><td>2</td><td>1</td>" in result


def test_render_coverage_backup_column_reads_zero_when_no_backup() -> None:
    """A season with no ESPN Press Room crews still shows the column, as 0."""
    site = _fixture_site()
    result = render_coverage(site)
    row = next(r for r in site.coverage if r.network is None and r.matched_crew_backup == 0)
    assert (
        f"<td>{row.matched_crew}</td><td>{row.matched_crew_patched}</td><td>0</td>"
        f"<td>{_pct_text(row.match_rate)}</td>"
    ) in result


def _pct_text(value: float | None) -> str:
    return f"{value * 100:.1f}%" if value is not None else chr(0x2013)  # en dash


def test_render_coverage_escapes_network_name() -> None:
    mutated_payload = copy.deepcopy(_load_fixture())
    mutated_payload["lookups"]["networks"][0]["name"] = "<script>x</script>"  # type: ignore[index]
    mutated_site = validate_site_data(mutated_payload)

    result = render_coverage(mutated_site)

    assert "<script>x</script>" not in result
    assert html.escape("<script>x</script>") in result


def test_write_pages_writes_both_files(tmp_path: Path) -> None:
    site = _fixture_site()
    written = write_pages(tmp_path, site, REPO_ROOT / "docs")

    assert written == ["methodology.html", "coverage.html"]
    for name in written:
        assert (tmp_path / name).is_file()
        assert "data/vault" not in (tmp_path / name).read_text(encoding="utf-8")


_METHODOLOGY_MD = REPO_ROOT / "docs" / "methodology.md"

# Tooltip-only facts moved to the detail panel in 628784b (chart.js
# `hoverText`): the time slot, the era/measurement label, and the flags.
_NOT_IN_HOVER_RE = re.compile(r"\bslots?\b|\beras?\b|Adobe|\bflags?\b", re.IGNORECASE)


def test_methodology_never_promises_panel_only_facts_in_the_hover() -> None:
    """WR-06: the tooltip shows only the matchup/score, date/kickoff,
    networks, crew and viewers, so no sentence of the public methodology
    that mentions the hover may send readers there for the time slot, the
    measurement era/label, or a flag."""
    text = re.sub(r"\s+", " ", _METHODOLOGY_MD.read_text(encoding="utf-8"))
    sentences = re.split(r"(?<=[.!?])\s+", text)
    offending = [
        s
        for s in sentences
        if re.search(r"\bhover\b", s, re.IGNORECASE) and _NOT_IN_HOVER_RE.search(s)
    ]
    assert offending == []


def test_methodology_describes_the_slim_tooltip() -> None:
    """WR-06: the page says what the tooltip does show, and that the rest
    lives in the detail panel."""
    text = re.sub(r"\s+", " ", _METHODOLOGY_MD.read_text(encoding="utf-8"))
    assert (
        "A dot's tooltip is kept short: the matchup and final score, the date and "
        "kickoff time, the named game (the bowl, rivalry, or playoff round, with "
        "its icon) on its own line, the networks, the crew, and the viewer count." in text
    )
    assert "Click or tap the dot to open its detail panel" in text


_BLOB = "https://github.com/benboro/booth-review/blob/main/"


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("known-gaps.md", "#known-gaps"),
        ("known-gaps.md#scope", "#scope"),
        ("sources/506.md", f"{_BLOB}docs/sources/506.md"),
        ("PLAN.md#build-phases", f"{_BLOB}docs/PLAN.md#build-phases"),
        ("../AGENTS.md", f"{_BLOB}AGENTS.md"),
        ("/README.md", f"{_BLOB}README.md"),
        ("https://example.com/README.md", "https://example.com/README.md"),
        ("//example.com/notes.md", "//example.com/notes.md"),
        ("../../outside.md", "../../outside.md"),
    ],
)
def test_render_methodology_resolves_md_links_against_docs(
    tmp_path: Path, href: str, expected: str
) -> None:
    """WR-08: relative `.md` links resolve against docs/ (subdirectories and
    `..` kept, `#fragment` kept), known-gaps.md links become in-page anchors,
    and absolute URLs or paths outside the repo are never rewritten."""
    (tmp_path / "methodology.md").write_text(
        f"# Methodology\n\nSee [the link]({href}).\n\n<!-- include: known-gaps.md -->\n",
        encoding="utf-8",
    )
    (tmp_path / "known-gaps.md").write_text("# Known Gaps\n\n## Scope\n\ntext\n", encoding="utf-8")

    result = render_methodology(tmp_path, _fixture_site())

    assert f'<a href="{expected}">the link</a>' in result


# --- NFL methodology blocks (phase 999.5, D-10/D-18/D-25) -------------------

# sha256 of render_methodology(docs, CFB fixture site) recorded before any NFL
# text existed. The flag-off page must stay byte-identical (D-25).
# Re-pinned at 04.19 Plan 09: cause list item 3 reworded (D-21), the only change.
# Re-pinned at 04.19 Plan 30: Sports Media Watch source order, gate and credit text
# (methodology) and the 2021-24 counts (known gaps); no NFL text changed.
# Re-pinned at 04.19 Plan 36: The TV Ratings Guide and Awful Announcing route, gate
# and credit text (methodology) and the Wave B 2021-24 counts (known gaps); no NFL
# text changed.
# Re-pinned at 04.19 Plan 44: ESPN Press Room hand-save route, gate line, crew backup
# order and credit text (methodology) and its crew and figure counts (known gaps); no
# NFL text changed.
# Re-pinned at 11 Plan 06: the map section rewrite (venue dots, hover card, network
# colors); no NFL text changed.
# Re-pinned at 11 review fixes: one sentence on announcer picks rescaling the map's dots
# and coloring; no NFL text changed.
# Re-pinned at Phase 13 Plan 01: footer RT-23/RT-24 lines, data-theme and color-scheme,
# new header with theme slot, site name.
# Re-pinned at Phase 14 Plan 09: new Crews section.
# Re-pinned at Phase 14 Plan 10: Crews opens on Per season (one methodology sentence).
# Re-pinned at Phase 14 Plan 10 (checkpoint): one Crews sentence on whole-season Nielsen bands.
# Re-pinned at Phase 14 Plan 11: Crews panel fixes (shipped-modal and null-cited-analyst
# fill-in rule, unknown-role marks on no-PBP rows); no NFL text changed.
# Re-pinned at Phase 15 Plan 05: CFB Crews regular-analyst exception (P14-FU-3);
# NFL text changes are inside the nfl fences.
_METHODOLOGY_FLAG_OFF_SHA256 = "b78919a2ae89ca846586e63166040e363f66398a7008bc81dc2f4000d2290dd8"

_NFL_ANCHORS = (
    "nfl-special-games",
    "nfl-doubleheader-weeks-and-rates",
    "nfl-crews-and-the-lead-booth",
    "nfl-published-lineups",
    "nfl-viewership-by-category",
    "nfl-window-level-viewership",
    "nfl-the-spread-adjustment",
    "nfl-low-n",
    "nfl-gei-style-excitement",
    "nfl-games-with-no-public-rating",
    "nfl-measurement-eras",
)
_CFB_ANCHORS = (
    "games-with-no-public-rating",
    "measurement-eras",
    "the-2025-excitement-break",
    "the-y-axis-viewers-excitement-points-or-margin",
)
_DOCS = REPO_ROOT / "docs"


def test_methodology_flag_off_digest_is_pinned() -> None:
    import hashlib

    rendered = render_methodology(_DOCS, _fixture_site())
    assert hashlib.sha256(rendered.encode("utf-8")).hexdigest() == _METHODOLOGY_FLAG_OFF_SHA256


def test_methodology_states_the_backend_modal_exception() -> None:
    rendered = " ".join(render_methodology(_DOCS, _fixture_site()).split())
    assert "as an <code>other</code> booth" in rendered
    assert "for a voice with no shipped booth assignment" in rendered


def test_methodology_nfl_crews_pool_exactly() -> None:
    rendered = " ".join(render_methodology(_DOCS, _fixture_site(), nfl=True).split())
    assert "never pooled across seasons, because" not in rendered
    assert "Pooling is exact" in rendered


def test_known_gaps_regional_gap_links_the_window_section() -> None:
    rendered = " ".join(render_methodology(_DOCS, _fixture_site(), nfl=True).split())
    assert "regional Sunday-afternoon games have no published figure" in rendered
    assert re.search(r'href="[^"]*#nfl-window-level-viewership"', rendered)


def _temp_docs(
    tmp_path: Path, methodology: str, known_gaps: str = "# Known gaps\n\nBody.\n"
) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "methodology.md").write_text(methodology, encoding="utf-8")
    (docs / "known-gaps.md").write_text(known_gaps, encoding="utf-8")
    return docs


_BLOCK_DOC = (
    "# Methodology\n\nCFB text.\n\n<!-- nfl:start -->\n\n## NFL: Only here\n\nNFLSECRET.\n\n"
    "<!-- nfl:end -->\n\nTail.\n\n<!-- include: known-gaps.md -->\n"
)


def test_nfl_blocks_stripped_when_flag_off_and_kept_when_on(tmp_path: Path) -> None:
    docs = _temp_docs(tmp_path, _BLOCK_DOC)
    site = _fixture_site()
    off = render_methodology(docs, site)
    on = render_methodology(docs, site, nfl=True)
    assert "NFLSECRET" not in off
    assert "nfl:start" not in off
    assert "nfl:end" not in off
    assert "NFLSECRET" in on
    assert "nfl:start" not in on
    assert "nfl:end" not in on


_GAPS_WITH_NFL = (
    "# Known gaps\n\nBody.\n\n<!-- nfl:start -->\n\n## NFL gap\n\nGAPSECRET.\n\n<!-- nfl:end -->\n"
)
_PLAIN_DOC = "# M\n\n<!-- include: known-gaps.md -->\n"


def test_known_gaps_nfl_block_follows_flag(tmp_path: Path) -> None:
    docs = _temp_docs(tmp_path, _PLAIN_DOC, _GAPS_WITH_NFL)
    site = _fixture_site()
    off = render_methodology(docs, site)
    on = render_methodology(docs, site, nfl=True)
    assert "GAPSECRET" not in off
    assert "nfl:" not in off
    assert "GAPSECRET" in on
    assert "nfl:" not in on


def test_known_gaps_unbalanced_nfl_marker_raises(tmp_path: Path) -> None:
    docs = _temp_docs(tmp_path, _PLAIN_DOC, "# Known gaps\n\n<!-- nfl:start -->\nx\n")
    with pytest.raises(SiteBuildError, match="unbalanced NFL marker"):
        render_methodology(docs, _fixture_site())


@pytest.mark.parametrize(
    "bad",
    [
        "<!-- nfl:start -->\nx\n",
        "x\n<!-- nfl:end -->\n",
        "<!-- nfl:start -->\n<!-- nfl:start -->\nx\n<!-- nfl:end -->\n<!-- nfl:end -->\n",
    ],
)
def test_unbalanced_nfl_markers_raise(tmp_path: Path, bad: str) -> None:
    docs = _temp_docs(tmp_path, "# M\n\n" + bad + "\n<!-- include: known-gaps.md -->\n")
    with pytest.raises(SiteBuildError, match="unbalanced NFL marker"):
        render_methodology(docs, _fixture_site())


def test_write_pages_nfl_flag(tmp_path: Path) -> None:
    site = _fixture_site()
    off_dir = tmp_path / "off"
    off_dir.mkdir()
    on_dir = tmp_path / "on"
    on_dir.mkdir()
    write_pages(off_dir, site, _DOCS)
    write_pages(on_dir, site, _DOCS, nfl=True)
    assert 'id="nfl-special-games"' not in (off_dir / "methodology.html").read_text("utf-8")
    assert 'id="nfl-special-games"' in (on_dir / "methodology.html").read_text("utf-8")


def test_methodology_nfl_anchors_exist_with_flag_on() -> None:
    rendered = render_methodology(_DOCS, _fixture_site(), nfl=True)
    for anchor in _NFL_ANCHORS:
        assert f'id="{anchor}"' in rendered, anchor


@pytest.mark.parametrize("nfl", [True, False])
def test_methodology_cfb_anchors_unchanged(nfl: bool) -> None:
    rendered = render_methodology(_DOCS, _fixture_site(), nfl=nfl)
    for anchor in _CFB_ANCHORS:
        assert f'id="{anchor}"' in rendered, anchor


def test_methodology_nfl_text_absent_with_flag_off() -> None:
    assert "NFL:" not in render_methodology(_DOCS, _fixture_site())


def test_methodology_nfl_never_ranks_crews() -> None:
    text = (_DOCS / "methodology.md").read_text(encoding="utf-8")
    blocks = re.findall(r"<!-- nfl:start -->(.*?)<!-- nfl:end -->", text, flags=re.S)
    assert len(blocks) == 2
    gaps = (_DOCS / "known-gaps.md").read_text(encoding="utf-8")
    gap_blocks = re.findall(r"<!-- nfl:start -->(.*?)<!-- nfl:end -->", gaps, flags=re.S)
    assert len(gap_blocks) == 1
    joined = " ".join(blocks + gap_blocks).lower()
    for phrase in ("best booth", "worst", "better crew"):
        assert phrase not in joined
