"""Tests for spike/join.py's D-06 outputs: build_join_rows, write_outputs,
finalize, and the `booth-review spike join` CLI. Matching (match_506,
match_rr, resolve_crew) and headline selection (HEADLINE_RULE,
select_headline) were promoted to booth_review.resolve in Phase 3 and are
tested in tests/test_resolve_games.py and tests/test_resolve_headline.py.

All fixtures are either constructed directly in this file or loaded from
tests/fixtures/spike/ (invented teams, people, and figures only; D-07).
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from booth_review.cli import main
from booth_review.config import DataPaths
from booth_review.errors import ParseError
from booth_review.resolve.headline import HEADLINE_RULE
from booth_review.sources.cfbd.parser import parse_games
from booth_review.spike.join import (
    JoinFileMissingError,
    JoinRow,
    ReviewIncompleteError,
    build_join_rows,
    finalize,
    load_rr_sitemap_entries,
    write_outputs,
)
from booth_review.spike.selection import Selection, build_candidates, select_games

FIXTURES = Path(__file__).parent / "fixtures" / "spike"


# -- join.build_join_rows / write_outputs / finalize / CLI ------------------------------

_JOIN_ROW_COLUMNS = [
    "cfbd_game_id",
    "categories",
    "cfbd_matchup",
    "cfbd_start_et",
    "s506_week",
    "s506_row_index",
    "s506_row",
    "s506_confidence",
    "rr_record_urls",
    "rr_headline_value",
    "rr_headline_publisher",
    "rr_headline_source_url",
    "rr_claim_count",
    "rr_confidence",
    "resolved_crew",
    "match_confidence",
    "doubtful",
    "notes",
    "review_status",
    "review_note",
]


def _seed_full_vault(paths: DataPaths) -> None:
    """Seed a tmp vault with the full synthetic 30-game/22-sitemap-entry
    fixture set plus a handful of real 506/RR records, so build_join_rows
    can run a realistic full pass (used by both Task 2 unit tests and the
    CLI smoke test).
    """
    games_dir = paths.raw / "cfbd" / "games"
    games_dir.mkdir(parents=True, exist_ok=True)
    (games_dir / "2025.json").write_bytes((FIXTURES / "cfbd_games_2025.json").read_bytes())

    sitemap_dir = paths.raw / "ratingsref" / "sitemap"
    sitemap_dir.mkdir(parents=True, exist_ok=True)
    (sitemap_dir / "2026-09-25.xml").write_bytes((FIXTURES / "rr_sitemap.xml").read_bytes())

    rr_dir = paths.raw / "ratingsref" / "telecast" / "2025"
    rr_dir.mkdir(parents=True, exist_ok=True)
    for record_path in sorted((FIXTURES / "rr_records").glob("*.json")):
        (rr_dir / record_path.name).write_bytes(record_path.read_bytes())

    sports506_dir = paths.raw / "sports506" / "2025"
    sports506_dir.mkdir(parents=True, exist_ok=True)
    (sports506_dir / "wk-01.html").write_bytes((FIXTURES / "506_wk-01.html").read_bytes())
    (sports506_dir / "wk-B.html").write_bytes((FIXTURES / "506_wk-B.html").read_bytes())


def _selections_for_full_vault(paths: DataPaths) -> list[Selection]:
    games = parse_games((paths.raw / "cfbd" / "games" / "2025.json").read_bytes())
    rr_entries = load_rr_sitemap_entries(paths)
    candidates = build_candidates(games, rr_entries)
    return select_games(candidates)


def test_build_join_rows_returns_20_rows_with_exact_csv_columns(vault_paths: DataPaths) -> None:
    _seed_full_vault(vault_paths)
    selections = _selections_for_full_vault(vault_paths)
    rows = build_join_rows(vault_paths, selections)
    assert len(rows) == 20

    write_outputs(vault_paths, rows, selections)
    with (vault_paths.spike / "join.csv").open(newline="", encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    assert header == _JOIN_ROW_COLUMNS


def test_build_join_rows_every_row_starts_pending(vault_paths: DataPaths) -> None:
    _seed_full_vault(vault_paths)
    selections = _selections_for_full_vault(vault_paths)
    rows = build_join_rows(vault_paths, selections)
    assert all(row.review_status == "pending" for row in rows)
    assert all(row.review_note == "" for row in rows)


def test_build_join_rows_exact_match_on_both_sources_is_not_doubtful(
    vault_paths: DataPaths,
) -> None:
    _seed_full_vault(vault_paths)
    selections = _selections_for_full_vault(vault_paths)
    rows = build_join_rows(vault_paths, selections)
    by_id = {row.cfbd_game_id: row for row in rows}

    # 500005 (Ironpeak @ Foxhollow) has an exact 506 listing and a single
    # exact RR record on the same network (ECN), so it should be confident.
    row = by_id[500005]
    assert row.match_confidence == "exact"
    assert row.doubtful is False


def test_build_join_rows_match_confidence_is_weaker_of_the_two_sources(
    vault_paths: DataPaths,
) -> None:
    _seed_full_vault(vault_paths)
    selections = _selections_for_full_vault(vault_paths)
    rows = build_join_rows(vault_paths, selections)

    # match_confidence must equal whichever of s506_confidence/rr_confidence
    # is weaker (exact strongest, none weakest), for every selected row -
    # most of the 20 have no cached 506/RR data at all, so both sides land
    # on "none" together; the handful with fixture data exercise the mix.
    for row in rows:
        s506, rr = row.s506_confidence, row.rr_confidence
        rank = {"exact": 0, "date-shift": 1, "partial": 2, "ambiguous": 3, "none": 4}
        assert rank[row.match_confidence] == max(rank[s506], rank[rr])


def test_build_join_rows_doubtful_when_two_or_more_rr_records(vault_paths: DataPaths) -> None:
    _seed_full_vault(vault_paths)
    selections = _selections_for_full_vault(vault_paths)
    rows = build_join_rows(vault_paths, selections)
    by_id = {row.cfbd_game_id: row for row in rows}

    # 500001 (Lakeview @ Northfield) has two duplicate RR records.
    row = by_id[500001]
    assert row.rr_confidence == "exact"
    assert row.doubtful is True


def test_build_join_rows_cfp_game_resolves_main_feed_and_notes_alt_spanish(
    vault_paths: DataPaths,
) -> None:
    _seed_full_vault(vault_paths)
    selections = _selections_for_full_vault(vault_paths)
    rows = build_join_rows(vault_paths, selections)
    by_id = {row.cfbd_game_id: row for row in rows}

    row = by_id[500007]
    assert row.resolved_crew == "Chris Fielding, Jordan Sample, Casey Vale"
    assert "alt" in row.notes
    assert "spanish" in row.notes


def test_build_join_rows_raises_parse_error_for_unknown_cfbd_game_id(
    vault_paths: DataPaths,
) -> None:
    """WR-02: a stale selection.csv referencing a cfbd_game_id no longer in
    games/2025.json must raise BoothReviewError's ParseError, not a bare
    KeyError."""
    _seed_full_vault(vault_paths)
    selections = [Selection(cfbd_game_id=999_999_999, categories=("rematch",))]

    with pytest.raises(ParseError, match="999999999"):
        build_join_rows(vault_paths, selections)


def test_write_outputs_summary_flags_doubtful_rows(vault_paths: DataPaths) -> None:
    _seed_full_vault(vault_paths)
    selections = _selections_for_full_vault(vault_paths)
    rows = build_join_rows(vault_paths, selections)
    write_outputs(vault_paths, rows, selections)

    summary = (vault_paths.spike / "summary.md").read_text(encoding="utf-8")
    assert "CHECK" in summary
    assert summary.count("\n| ") >= 20


def test_write_outputs_report_pending_review_with_provisional_rate(
    vault_paths: DataPaths,
) -> None:
    _seed_full_vault(vault_paths)
    selections = _selections_for_full_vault(vault_paths)
    rows = build_join_rows(vault_paths, selections)
    write_outputs(vault_paths, rows, selections)

    report = (vault_paths.spike / "report.md").read_text(encoding="utf-8")
    assert "Join rate: PENDING REVIEW" in report
    assert "Provisional automatic rate" in report
    assert HEADLINE_RULE in report
    assert "Seed:" in report
    assert "Name-matching problems" in report


# -- CSV-injection hardening (WR-04) -------------------------------------------------------


def test_write_then_finalize_round_trips_a_notes_field_starting_with_equals(
    vault_paths: DataPaths,
) -> None:
    """join.csv is explicitly reviewer-facing (a human is told to open it in
    a spreadsheet); a notes value that happens to start with a
    formula-injection character must be escaped in the raw CSV on write and
    recovered exactly by --finalize's report."""
    dangerous_notes = "=cmd; network mismatch: 506=ESPN RR=['FOX']"
    row = JoinRow(
        cfbd_game_id=900555,
        categories="rematch",
        cfbd_matchup="Example @ Sample",
        cfbd_start_et="2025-09-13T12:00:00-04:00",
        s506_week="",
        s506_row_index="",
        s506_row="",
        s506_confidence="none",
        rr_record_urls="",
        rr_headline_value="",
        rr_headline_publisher="",
        rr_headline_source_url="",
        rr_claim_count=0,
        rr_confidence="none",
        resolved_crew="",
        match_confidence="none",
        doubtful=True,
        notes=dangerous_notes,
        review_status="pending",
        review_note="",
    )
    write_outputs(vault_paths, [row], [])

    join_path = vault_paths.spike / "join.csv"
    raw_csv = join_path.read_text(encoding="utf-8")
    assert f"'{dangerous_notes}" in raw_csv  # escaped in the file a human might open

    with join_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["review_status"] = "confirmed"
    with join_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_JOIN_ROW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    finalize(vault_paths)
    report = (vault_paths.spike / "report.md").read_text(encoding="utf-8")
    assert dangerous_notes in report  # recovered without the escape marker


# -- join.finalize ------------------------------------------------------------------------


def _write_join_csv(path: Path, statuses: list[str], *, match_confidences: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(_JOIN_ROW_COLUMNS)
        for i, (status, conf) in enumerate(zip(statuses, match_confidences, strict=True)):
            writer.writerow(
                [
                    900000 + i,
                    "filler",
                    "Example A @ Example B",
                    "2025-09-13T12:00:00-04:00",
                    "3",
                    "0",
                    "Example A @ Example B | ECN | Pat Example",
                    conf,
                    "",
                    "",
                    "",
                    "",
                    0,
                    "none",
                    "Pat Example",
                    conf,
                    False,
                    "",
                    status,
                    "",
                ]
            )


def test_finalize_85_percent_passes(vault_paths: DataPaths) -> None:
    statuses = ["confirmed"] * 17 + ["corrected"] * 2 + ["rejected"] * 1
    _write_join_csv(vault_paths.spike / "join.csv", statuses, match_confidences=["exact"] * 20)
    result = finalize(vault_paths)
    assert result["confirmed"] == 17
    assert result["join_rate"] == pytest.approx(0.85)
    assert result["passed"] is True

    report = (vault_paths.spike / "report.md").read_text(encoding="utf-8")
    assert "D-09 exit rule (80%): PASS" in report


def test_finalize_75_percent_fails(vault_paths: DataPaths) -> None:
    statuses = ["confirmed"] * 15 + ["corrected"] * 3 + ["rejected"] * 2
    _write_join_csv(vault_paths.spike / "join.csv", statuses, match_confidences=["exact"] * 20)
    result = finalize(vault_paths)
    assert result["join_rate"] == pytest.approx(0.75)
    assert result["passed"] is False

    report = (vault_paths.spike / "report.md").read_text(encoding="utf-8")
    assert "D-09 exit rule (80%): FAIL" in report


def test_finalize_raises_when_a_row_is_still_pending(vault_paths: DataPaths) -> None:
    statuses = ["confirmed"] * 19 + ["pending"]
    _write_join_csv(vault_paths.spike / "join.csv", statuses, match_confidences=["exact"] * 20)
    with pytest.raises(ReviewIncompleteError):
        finalize(vault_paths)


def test_finalize_raises_join_file_missing_error_when_join_csv_absent(
    vault_paths: DataPaths,
) -> None:
    """WR-02: running --finalize before `spike join` has ever produced
    join.csv must raise a BoothReviewError, not a bare FileNotFoundError."""
    assert not (vault_paths.spike / "join.csv").exists()
    with pytest.raises(JoinFileMissingError):
        finalize(vault_paths)


def test_finalize_raises_parse_error_for_hand_edited_join_csv_missing_a_column(
    vault_paths: DataPaths,
) -> None:
    """WR-02: a hand-edited join.csv missing an expected column must raise
    ParseError, not a bare KeyError."""
    join_path = vault_paths.spike / "join.csv"
    join_path.parent.mkdir(parents=True, exist_ok=True)
    columns = [c for c in _JOIN_ROW_COLUMNS if c != "review_note"]
    with join_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        writer.writerow(
            [
                900000,
                "filler",
                "Example A @ Example B",
                "2025-09-13T12:00:00-04:00",
                "3",
                "0",
                "Example A @ Example B | ECN | Pat Example",
                "exact",
                "",
                "",
                "",
                "",
                0,
                "none",
                "Pat Example",
                "exact",
                False,
                "",
                "confirmed",
            ]
        )

    with pytest.raises(ParseError, match="review_note"):
        finalize(vault_paths)


# -- CLI: booth-review spike join ----------------------------------------------------------


def test_cli_spike_join_no_commit_writes_all_outputs_and_sends_no_request(
    git_vault, monkeypatch
) -> None:
    monkeypatch.setattr(
        "booth_review.runtime.make_client",
        lambda: (_ for _ in ()).throw(AssertionError("no client should be built")),
    )
    _seed_full_vault(git_vault)

    exit_code = main(["spike", "join", "--no-commit"])
    assert exit_code == 0
    assert (git_vault.spike / "selection.csv").is_file()
    assert (git_vault.spike / "join.csv").is_file()
    assert (git_vault.spike / "summary.md").is_file()
    assert (git_vault.spike / "report.md").is_file()


def test_cli_spike_join_rerun_reuses_selection_csv(git_vault, monkeypatch) -> None:
    monkeypatch.setattr(
        "booth_review.runtime.make_client",
        lambda: (_ for _ in ()).throw(AssertionError("no client should be built")),
    )
    _seed_full_vault(git_vault)

    main(["spike", "join", "--no-commit"])
    first = (git_vault.spike / "selection.csv").read_bytes()
    main(["spike", "join", "--no-commit"])
    second = (git_vault.spike / "selection.csv").read_bytes()
    assert first == second


def test_cli_spike_join_reselect_rebuilds_selection(git_vault, monkeypatch) -> None:
    monkeypatch.setattr(
        "booth_review.runtime.make_client",
        lambda: (_ for _ in ()).throw(AssertionError("no client should be built")),
    )
    _seed_full_vault(git_vault)

    main(["spike", "join", "--no-commit"])
    exit_code = main(["spike", "join", "--reselect", "--no-commit"])
    assert exit_code == 0
    assert (git_vault.spike / "selection.csv").is_file()


def test_cli_spike_join_finalize_after_review(git_vault, monkeypatch) -> None:
    monkeypatch.setattr(
        "booth_review.runtime.make_client",
        lambda: (_ for _ in ()).throw(AssertionError("no client should be built")),
    )
    _seed_full_vault(git_vault)
    main(["spike", "join", "--no-commit"])

    join_path = git_vault.spike / "join.csv"
    with join_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        row["review_status"] = "confirmed"
    with join_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_JOIN_ROW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    exit_code = main(["spike", "join", "--finalize", "--no-commit"])
    assert exit_code == 0
    report = (git_vault.spike / "report.md").read_text(encoding="utf-8")
    assert "D-09 exit rule (80%): PASS" in report
