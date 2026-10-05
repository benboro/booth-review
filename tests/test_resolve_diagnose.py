"""Tests for resolve/diagnose.py against a synthetic vault built from
tests/fixtures/spike (D-07: no real vault content in a test fixture) plus
the synthetic reference tables under tests/fixtures/reference/.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from booth_review.config import DataPaths
from booth_review.resolve.diagnose import (
    UNMATCHED_COLUMNS,
    UNRESOLVED_TEAM_COLUMNS,
    counts_as_unresolved,
    is_placeholder_team,
    main,
    run_match_diagnostic,
    track_unresolved,
    write_team_review,
)
from booth_review.resolve.teams import ResolvedTeam

SPIKE_FIXTURES = Path(__file__).parent / "fixtures" / "spike"
REFERENCE_FIXTURES = Path(__file__).parent / "fixtures" / "reference"

# A team name starting with "=" -- deliberately formula-shaped so the review
# CSVs' csv_safe protection (T-03-12) can be proven end to end. Never matches
# any team in cfbd_games_2025.json, so it stays unresolved and unmatched.
_INJECTION_WEEK_HTML = (
    b"<html><body><div id='content'><div class='inner'><article>"
    b"<h3>SATURDAY, SEPTEMBER 6</h3>"
    b"<div id='cgame'><div id='cmatchup'>=Cmd Raiders @ Ghost Fielders</div>"
    b"<div id='ctime'>1:00 PM</div><div id='cntwk'>ECN</div>"
    b"<div id='canncrs'>Pat Example, Jordan Sample</div></div>"
    b"</article></div></div></body></html>"
)


def _build_vault(paths: DataPaths) -> None:
    games_dir = paths.raw / "cfbd" / "games"
    games_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(SPIKE_FIXTURES / "cfbd_games_2025.json", games_dir / "2025.json")

    week_dir = paths.raw / "sports506" / "2025"
    week_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(SPIKE_FIXTURES / "506_wk-01.html", week_dir / "wk-1.html")
    shutil.copy(SPIKE_FIXTURES / "506_wk-B.html", week_dir / "wk-B.html")
    (week_dir / "wk-2.html").write_bytes(_INJECTION_WEEK_HTML)

    rr_dir = paths.raw / "ratingsref" / "telecast" / "2025"
    rr_dir.mkdir(parents=True, exist_ok=True)
    for record_path in (SPIKE_FIXTURES / "rr_records").glob("*.json"):
        shutil.copy(record_path, rr_dir / record_path.name)


def test_run_match_diagnostic_counts(vault_paths: DataPaths) -> None:
    _build_vault(vault_paths)
    diagnostic = run_match_diagnostic(vault_paths, REFERENCE_FIXTURES, seasons=[2025])

    # 8 listings in wk-1.html + 4 in wk-B.html + 1 in the injected wk-2.html,
    # minus the one the sports506 exclude override removes (counted the way
    # build.telecasts counts listings_total, WR-11).
    assert diagnostic.listings_total == 12
    # 8 RR records in the fixture corpus.
    assert diagnostic.rr_records == 8
    assert diagnostic.rr_parse_errors == 0
    # The sports506 exclude override (pointer "1:6") removes one otherwise-
    # matched listing from both the matched and unmatched buckets.
    assert diagnostic.listings_matched + diagnostic.listings_unmatched == 12
    assert diagnostic.rr_excluded == 0
    assert diagnostic.rr_unmatched >= 0


def test_write_team_review_headers_and_csv_safe(vault_paths: DataPaths) -> None:
    _build_vault(vault_paths)
    diagnostic = run_match_diagnostic(vault_paths, REFERENCE_FIXTURES, seasons=[2025])
    write_team_review(vault_paths, diagnostic)

    unresolved_path = vault_paths.interim / "review_unresolved_teams.csv"
    unmatched_path = vault_paths.interim / "review_unmatched.csv"
    assert unresolved_path.is_file()
    assert unmatched_path.is_file()

    unresolved_text = unresolved_path.read_text(encoding="utf-8")
    unmatched_text = unmatched_path.read_text(encoding="utf-8")

    assert unresolved_text.splitlines()[0] == ",".join(UNRESOLVED_TEAM_COLUMNS)
    assert unmatched_text.splitlines()[0] == ",".join(UNMATCHED_COLUMNS)

    # The injected "=Cmd Raiders" name is neutralized (csv_safe) in whichever
    # review file it lands in -- a bare, unescaped "=Cmd Raiders" cell (with
    # no leading csv_safe marker) never appears.
    assert ",=Cmd Raiders" not in unresolved_text
    assert ",=Cmd Raiders" not in unmatched_text
    assert "'=Cmd Raiders" in unresolved_text or "'=Cmd Raiders" in unmatched_text


def test_main_prints_no_team_name(
    vault_paths: DataPaths,
    capsys,  # type: ignore[no-untyped-def]
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    _build_vault(vault_paths)
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(REFERENCE_FIXTURES))
    exit_code = main(["--no-write"])
    assert exit_code == 0

    captured = capsys.readouterr()
    forbidden = (
        "Northfield",
        "Lakeview",
        "Cedarhollow",
        "Boulderpass",
        "Ravenwood",
        "Thornfield",
        "Cmd Raiders",
    )
    for name in forbidden:
        assert name not in captured.out

    assert "listings" in captured.out.lower()
    assert "%" in captured.out

    # --no-write must not write the review files.
    assert not (vault_paths.interim / "review_unresolved_teams.csv").is_file()
    assert not (vault_paths.interim / "review_unmatched.csv").is_file()


# -- WR-11: the review report and the build agree on JOIN-08 -----------------------------------


def test_main_reports_the_builds_own_join08_rate(
    vault_paths: DataPaths,
    capsys,  # type: ignore[no-untyped-def]
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    from booth_review.build.tables import assemble_tables

    _build_vault(vault_paths)
    # A placeholder-only crew: the build never counts it as a crew match, so
    # a report that did would disagree with the build.
    week_page = vault_paths.raw / "sports506" / "2025" / "wk-1.html"
    html = week_page.read_bytes()
    assert html.count(b'id="canncrs">Casey Vale<') == 1
    week_page.write_bytes(html.replace(b'id="canncrs">Casey Vale<', b'id="canncrs">TBA<'))
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(REFERENCE_FIXTURES))

    assert main(["--no-write"]) == 0
    out = capsys.readouterr().out

    totals = assemble_tables(vault_paths, REFERENCE_FIXTURES).diagnostics.totals
    denominator = totals["rr_records"] - totals["rr_excluded"] - totals["rr_out_of_scope"]
    expected = f"({totals['records_with_crew']}/{denominator})"
    crew_lines = [line for line in out.splitlines() if "plus-crew" in line]
    assert len(crew_lines) == 1
    assert expected in crew_lines[0]


# -- Which unresolved names need a crosswalk row --------------------------------

UNRESOLVED = ResolvedTeam(team_id=None, canonical=None, method="unresolved")


@pytest.mark.parametrize(
    "raw",
    [
        "Rose Bowl winner",
        "Fiesta Bowl winner (in Miami)",
        "Peach Bowl Winner (in Arlington TX)",
        "Loser of Game 3",
        "TBD",
        " tba ",
    ],
)
def test_placeholder_team_slots_are_not_crosswalk_candidates(raw: str) -> None:
    assert is_placeholder_team(raw)
    assert not counts_as_unresolved(raw, UNRESOLVED, by_override=False)


@pytest.mark.parametrize(
    "raw", ["Winston-Salem State", "Tbilisi Tech", "Rose-Hulman", "Wake Forest"]
)
def test_real_team_names_are_not_placeholders(raw: str) -> None:
    assert not is_placeholder_team(raw)
    assert counts_as_unresolved(raw, UNRESOLVED, by_override=False)


def test_override_matched_row_names_need_no_crosswalk_row() -> None:
    """A row game_overrides.csv already ties to a game is resolved by hand."""
    counts: dict[tuple[str, str], dict[str, int]] = {}
    track_unresolved(counts, "sports506", "Mystery U", 2024, UNRESOLVED, by_override=True)
    assert counts == {}
    track_unresolved(counts, "sports506", "Mystery U", 2024, UNRESOLVED, by_override=False)
    assert counts[("sports506", "Mystery U")]["count"] == 1


def test_resolved_names_are_never_counted() -> None:
    resolved = ResolvedTeam(team_id=1, canonical="Alpha", method="crosswalk")
    assert not counts_as_unresolved("Alpha", resolved, by_override=False)
