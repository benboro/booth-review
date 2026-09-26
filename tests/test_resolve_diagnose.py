"""Tests for resolve/diagnose.py against a synthetic vault built from
tests/fixtures/spike (D-07: no real vault content in a test fixture) plus
the synthetic reference tables under tests/fixtures/reference/.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from booth_review.config import DataPaths
from booth_review.resolve.diagnose import (
    UNMATCHED_COLUMNS,
    UNRESOLVED_TEAM_COLUMNS,
    main,
    run_match_diagnostic,
    write_team_review,
)

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

    # 8 listings in wk-1.html + 4 in wk-B.html + 1 in the injected wk-2.html.
    assert diagnostic.listings_total == 13
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
