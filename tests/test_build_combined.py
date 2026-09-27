"""Tests for build/combined.py: RR composite_of/carrier_network detection
(already applied by build.telecasts), the alt-cast/outlier candidate review
file, the pointer-only decision table's validation, and apply_combined's
telecasts/telecast_flags update (D-08, D-09, D-06).
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from booth_review.build.combined import (
    COMBINED_COLUMNS,
    MIN_NETWORK_SEASON_TELECASTS,
    OUTLIER_FACTOR,
    REVIEW_COMBINED_COLUMNS,
    CombinedCandidate,
    CombinedDecision,
    apply_combined,
    find_combined_candidates,
    load_combined_figures,
    main,
)
from booth_review.build.tables import assemble_tables
from booth_review.config import DataPaths
from booth_review.errors import ReferenceTableError
from booth_review.reference import write_reference_csv


def _telecast_row(
    *,
    telecast_id: str,
    game_id: int = 1,
    season: int = 2025,
    network_id: str | None = "net-a",
    feed_type: str = "main",
    rated: bool = True,
    rr_telecast_ids: list[str] | None = None,
    combined_feeds: int | None = None,
    headline_value: float | None = 1_000_000.0,
    plotted: bool = True,
) -> dict[str, object]:
    return {
        "telecast_id": telecast_id,
        "game_id": game_id,
        "season": season,
        "date_et": date(2025, 9, 6),
        "network_id": network_id,
        "feed_type": feed_type,
        "rated": rated,
        "rr_telecast_ids": rr_telecast_ids
        if rr_telecast_ids is not None
        else ["cfb-a-b-2025-09-06"],
        "combined_feeds": combined_feeds,
        "headline_value": headline_value,
        "plotted": plotted,
    }


def _telecasts_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows)


def _links_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(schema={"season": pl.Int64, "game_id": pl.Int64, "feed_kind": pl.Utf8})
    return pl.DataFrame(rows)


def _alt_link(game_id: int, feed_kind: str = "alt") -> dict[str, object]:
    return {"season": 2025, "game_id": game_id, "feed_kind": feed_kind}


def _empty_viewership() -> pl.DataFrame:
    return pl.DataFrame()


# -- load_combined_figures: the pointer-only decision table's validation ------------------


def test_load_combined_figures_reads_a_valid_row(tmp_path: Path) -> None:
    write_reference_csv(
        tmp_path / "combined_figures.csv",
        COMBINED_COLUMNS,
        [
            {
                "rr_telecast_id": "cfb-a-b-2025-09-06",
                "decision": "combined",
                "feeds": "3",
                "reason": "megacast",
            }
        ],
    )
    decisions = load_combined_figures(tmp_path)

    assert decisions["cfb-a-b-2025-09-06"] == CombinedDecision(
        rr_telecast_id="cfb-a-b-2025-09-06", decision="combined", feeds=3, reason="megacast"
    )


def test_load_combined_figures_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_combined_figures(tmp_path) == {}


def test_load_combined_figures_rejects_bad_rr_telecast_id(tmp_path: Path) -> None:
    write_reference_csv(
        tmp_path / "combined_figures.csv",
        COMBINED_COLUMNS,
        [{"rr_telecast_id": "not-an-rr-id", "decision": "single", "feeds": "", "reason": "other"}],
    )
    with pytest.raises(ReferenceTableError):
        load_combined_figures(tmp_path)


def test_load_combined_figures_rejects_bad_decision(tmp_path: Path) -> None:
    write_reference_csv(
        tmp_path / "combined_figures.csv",
        COMBINED_COLUMNS,
        [
            {
                "rr_telecast_id": "cfb-a-b-2025-09-06",
                "decision": "maybe",
                "feeds": "",
                "reason": "other",
            }
        ],
    )
    with pytest.raises(ReferenceTableError):
        load_combined_figures(tmp_path)


def test_load_combined_figures_rejects_bad_reason(tmp_path: Path) -> None:
    write_reference_csv(
        tmp_path / "combined_figures.csv",
        COMBINED_COLUMNS,
        [
            {
                "rr_telecast_id": "cfb-a-b-2025-09-06",
                "decision": "single",
                "feeds": "",
                "reason": "nope",
            }
        ],
    )
    with pytest.raises(ReferenceTableError):
        load_combined_figures(tmp_path)


def test_load_combined_figures_rejects_combined_with_feeds_below_two(tmp_path: Path) -> None:
    write_reference_csv(
        tmp_path / "combined_figures.csv",
        COMBINED_COLUMNS,
        [
            {
                "rr_telecast_id": "cfb-a-b-2025-09-06",
                "decision": "combined",
                "feeds": "1",
                "reason": "other",
            }
        ],
    )
    with pytest.raises(ReferenceTableError):
        load_combined_figures(tmp_path)


def test_load_combined_figures_rejects_duplicate_rr_telecast_id(tmp_path: Path) -> None:
    write_reference_csv(
        tmp_path / "combined_figures.csv",
        COMBINED_COLUMNS,
        [
            {
                "rr_telecast_id": "cfb-a-b-2025-09-06",
                "decision": "single",
                "feeds": "",
                "reason": "other",
            },
            {
                "rr_telecast_id": "cfb-a-b-2025-09-06",
                "decision": "single",
                "feeds": "",
                "reason": "other",
            },
        ],
    )
    with pytest.raises(ReferenceTableError):
        load_combined_figures(tmp_path)


def test_load_combined_figures_clears_feeds_for_a_single_decision(tmp_path: Path) -> None:
    write_reference_csv(
        tmp_path / "combined_figures.csv",
        COMBINED_COLUMNS,
        [
            {
                "rr_telecast_id": "cfb-a-b-2025-09-06",
                "decision": "single",
                "feeds": "5",
                "reason": "other",
            }
        ],
    )
    decisions = load_combined_figures(tmp_path)

    assert decisions["cfb-a-b-2025-09-06"].feeds is None


# -- find_combined_candidates ------------------------------------------------------------


def test_rr_field_combined_telecast_is_never_a_candidate() -> None:
    telecasts = _telecasts_frame([_telecast_row(telecast_id="t1", combined_feeds=2)])

    candidates = find_combined_candidates(telecasts, _empty_viewership(), _links_frame([]))

    assert candidates == []


def test_telecast_with_no_rr_record_is_never_a_candidate() -> None:
    telecasts = _telecasts_frame([_telecast_row(telecast_id="t1", rr_telecast_ids=[])])
    links = _links_frame([_alt_link(game_id=1)])

    candidates = find_combined_candidates(telecasts, _empty_viewership(), links)

    assert candidates == []


def test_alt_listed_candidate_proposes_combined_with_the_right_feed_count() -> None:
    telecasts = _telecasts_frame([_telecast_row(telecast_id="t1", game_id=1)])
    links = _links_frame(
        [_alt_link(game_id=1, feed_kind="alt"), _alt_link(game_id=1, feed_kind="spanish")]
    )

    candidates = find_combined_candidates(telecasts, _empty_viewership(), links)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.reasons == ("alt_listed",)
    assert candidate.alt_feed_count == 2
    assert candidate.proposed == "combined"
    assert candidate.proposed_feeds == 3


def test_outlier_only_candidate_proposes_single() -> None:
    rows = [
        _telecast_row(
            telecast_id=f"low-{i}",
            game_id=100 + i,
            headline_value=1_000_000.0,
            rr_telecast_ids=[f"cfb-low-{i}"],
        )
        for i in range(MIN_NETWORK_SEASON_TELECASTS)
    ]
    rows.append(
        _telecast_row(
            telecast_id="outlier",
            game_id=999,
            headline_value=OUTLIER_FACTOR * 1_000_000.0 + 1.0,
            rr_telecast_ids=["cfb-outlier"],
        )
    )
    telecasts = _telecasts_frame(rows)

    candidates = find_combined_candidates(telecasts, _empty_viewership(), _links_frame([]))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.telecast_id == "outlier"
    assert candidate.reasons == ("outlier",)
    assert candidate.proposed == "single"
    assert candidate.proposed_feeds is None


def test_outlier_check_skipped_below_the_minimum_network_season_sample() -> None:
    rows = [
        _telecast_row(
            telecast_id=f"low-{i}",
            game_id=100 + i,
            headline_value=1_000_000.0,
            rr_telecast_ids=[f"cfb-low-{i}"],
        )
        for i in range(MIN_NETWORK_SEASON_TELECASTS - 2)
    ]
    rows.append(
        _telecast_row(
            telecast_id="outlier",
            game_id=999,
            headline_value=OUTLIER_FACTOR * 1_000_000.0 + 1.0,
            rr_telecast_ids=["cfb-outlier"],
        )
    )
    telecasts = _telecasts_frame(rows)

    candidates = find_combined_candidates(telecasts, _empty_viewership(), _links_frame([]))

    assert candidates == []


def test_alt_listed_and_outlier_reasons_combine_on_one_candidate() -> None:
    rows = [
        _telecast_row(
            telecast_id=f"low-{i}",
            game_id=100 + i,
            headline_value=1_000_000.0,
            rr_telecast_ids=[f"cfb-low-{i}"],
        )
        for i in range(MIN_NETWORK_SEASON_TELECASTS)
    ]
    rows.append(
        _telecast_row(
            telecast_id="both",
            game_id=999,
            headline_value=OUTLIER_FACTOR * 1_000_000.0 + 1.0,
            rr_telecast_ids=["cfb-both"],
        )
    )
    telecasts = _telecasts_frame(rows)
    links = _links_frame([_alt_link(game_id=999)])

    candidates = find_combined_candidates(telecasts, _empty_viewership(), links)

    both = next(c for c in candidates if c.telecast_id == "both")
    assert set(both.reasons) == {"alt_listed", "outlier"}
    assert both.proposed == "combined"


# -- apply_combined -----------------------------------------------------------------------


def test_apply_combined_sets_feeds_for_a_combined_decision() -> None:
    telecasts = _telecasts_frame([_telecast_row(telecast_id="t1", game_id=1)])
    telecast_flags = pl.DataFrame(
        schema={"telecast_id": pl.Utf8, "flag_id": pl.Utf8, "kind": pl.Utf8}
    )
    candidate = CombinedCandidate(
        rr_telecast_id="cfb-a-b-2025-09-06",
        telecast_id="t1",
        season=2025,
        date_et=date(2025, 9, 6),
        network_id="net-a",
        reasons=("alt_listed",),
        alt_feed_count=1,
        headline_value=1_000_000.0,
        network_median=None,
        proposed="combined",
        proposed_feeds=2,
    )
    decisions = {
        "cfb-a-b-2025-09-06": CombinedDecision("cfb-a-b-2025-09-06", "combined", 2, "megacast")
    }

    new_telecasts, new_flags = apply_combined(telecasts, telecast_flags, [candidate], decisions)

    assert new_telecasts.filter(pl.col("telecast_id") == "t1")["combined_feeds"].item() == 2
    flag_rows = new_flags.filter(pl.col("telecast_id") == "t1")
    assert flag_rows["flag_id"].to_list() == ["combined"]
    assert flag_rows["kind"].to_list() == ["combined"]


def test_apply_combined_clears_feeds_for_a_single_decision() -> None:
    telecasts = _telecasts_frame([_telecast_row(telecast_id="t1", game_id=1, combined_feeds=None)])
    telecast_flags = pl.DataFrame(
        schema={"telecast_id": pl.Utf8, "flag_id": pl.Utf8, "kind": pl.Utf8}
    )
    candidate = CombinedCandidate(
        rr_telecast_id="cfb-a-b-2025-09-06",
        telecast_id="t1",
        season=2025,
        date_et=date(2025, 9, 6),
        network_id="net-a",
        reasons=("outlier",),
        alt_feed_count=0,
        headline_value=1_000_000.0,
        network_median=200_000.0,
        proposed="single",
        proposed_feeds=None,
    )
    decisions = {
        "cfb-a-b-2025-09-06": CombinedDecision("cfb-a-b-2025-09-06", "single", None, "other")
    }

    new_telecasts, new_flags = apply_combined(telecasts, telecast_flags, [candidate], decisions)

    assert new_telecasts.filter(pl.col("telecast_id") == "t1")["combined_feeds"].item() is None
    assert new_flags.height == 0


def test_apply_combined_never_duplicates_an_existing_combined_flag() -> None:
    telecasts = _telecasts_frame([_telecast_row(telecast_id="t1", game_id=1)])
    telecast_flags = pl.DataFrame(
        [{"telecast_id": "t1", "flag_id": "combined", "kind": "combined"}]
    )
    candidate = CombinedCandidate(
        rr_telecast_id="cfb-a-b-2025-09-06",
        telecast_id="t1",
        season=2025,
        date_et=date(2025, 9, 6),
        network_id="net-a",
        reasons=("alt_listed",),
        alt_feed_count=1,
        headline_value=1_000_000.0,
        network_median=None,
        proposed="combined",
        proposed_feeds=2,
    )
    decisions = {
        "cfb-a-b-2025-09-06": CombinedDecision("cfb-a-b-2025-09-06", "combined", 2, "megacast")
    }

    _new_telecasts, new_flags = apply_combined(telecasts, telecast_flags, [candidate], decisions)

    assert new_flags.height == 1


def test_apply_combined_leaves_undecided_candidates_untouched() -> None:
    telecasts = _telecasts_frame([_telecast_row(telecast_id="t1", game_id=1, combined_feeds=None)])
    telecast_flags = pl.DataFrame(
        schema={"telecast_id": pl.Utf8, "flag_id": pl.Utf8, "kind": pl.Utf8}
    )
    candidate = CombinedCandidate(
        rr_telecast_id="cfb-a-b-2025-09-06",
        telecast_id="t1",
        season=2025,
        date_et=date(2025, 9, 6),
        network_id="net-a",
        reasons=("alt_listed",),
        alt_feed_count=1,
        headline_value=1_000_000.0,
        network_median=None,
        proposed="combined",
        proposed_feeds=2,
    )

    new_telecasts, new_flags = apply_combined(telecasts, telecast_flags, [candidate], {})

    assert new_telecasts.filter(pl.col("telecast_id") == "t1")["combined_feeds"].item() is None
    assert new_flags.height == 0


# -- Integration: a real assemble_tables run over the shared build fixtures --------------


@pytest.fixture
def vault_reference(build_reference: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    extended = tmp_path / "reference_ext"
    shutil.copytree(build_reference, extended)
    with (extended / "networks.csv").open("a", encoding="utf-8", newline="") as fh:
        fh.write("ECN,ecn,Example Cable Network,family-ecn,cable,main,,,\n")
        fh.write("ECN2,ecn2,Example Cable Network 2,family-ecn,cable,main,,,\n")
        fh.write("ESPN,espn,ESPN,family-espn,cable,main,,,\n")
        fh.write("ESPN2,espn2,ESPN2,family-espn,cable,main,,,\n")
        fh.write("ESPNU,espnu,ESPNU,family-espn,cable,main,,,\n")
        fh.write("ESPN Deportes,espn-deportes,ESPN Deportes,family-espn,cable,spanish,,,\n")
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(extended))
    return extended


def test_assemble_tables_applies_the_fixture_combined_decision(
    build_vault: DataPaths, vault_reference: Path
) -> None:
    tables = assemble_tables(build_vault, vault_reference, seasons=[2025])

    decided = tables.telecasts.filter(
        pl.col("rr_telecast_ids").list.contains("cfb-thornfield-ravenwood-2026-01-19")
    )
    assert decided.height == 1
    assert decided["combined_feeds"].item() == 3

    flags = tables.telecast_flags.filter(pl.col("telecast_id") == decided["telecast_id"].item())
    assert "combined" in flags["flag_id"].to_list()

    assert tables.review_rows["review_combined"][0] == REVIEW_COMBINED_COLUMNS


def test_main_writes_only_review_combined_csv_and_prints_counts(
    build_vault: DataPaths,
    vault_reference: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main([])

    captured = capsys.readouterr()
    assert "combined candidates by reason" in captured.out
    assert "decisions" in captured.out
    assert (build_vault.interim / "review_combined.csv").is_file()
    assert not (build_vault.processed / "telecasts.parquet").is_file()


# -- WR-09: proposals never reach the public table; decisions match any merged RR id ---------


def test_apply_combined_matches_a_decision_keyed_on_a_merged_records_other_id() -> None:
    telecasts = _telecasts_frame([_telecast_row(telecast_id="t1", game_id=1)])
    telecast_flags = pl.DataFrame(
        schema={"telecast_id": pl.Utf8, "flag_id": pl.Utf8, "kind": pl.Utf8}
    )
    candidate = CombinedCandidate(
        rr_telecast_id="cfb-a-b-2025-09-06",
        telecast_id="t1",
        season=2025,
        date_et=date(2025, 9, 6),
        network_id="net-a",
        reasons=("alt_listed",),
        alt_feed_count=1,
        headline_value=1_000_000.0,
        network_median=None,
        proposed="combined",
        proposed_feeds=2,
        rr_telecast_ids=("cfb-a-b-2025-09-06", "cfb-a-b-2025-09-06-dup"),
    )
    decisions = {
        "cfb-a-b-2025-09-06-dup": CombinedDecision(
            "cfb-a-b-2025-09-06-dup", "combined", 2, "megacast"
        )
    }

    new_telecasts, _ = apply_combined(telecasts, telecast_flags, [candidate], decisions)

    assert new_telecasts.filter(pl.col("telecast_id") == "t1")["combined_feeds"].item() == 2


def test_orphan_decisions_are_counted() -> None:
    from booth_review.build.combined import orphan_decision_count

    candidate = CombinedCandidate(
        rr_telecast_id="cfb-a-b-2025-09-06",
        telecast_id="t1",
        season=2025,
        date_et=date(2025, 9, 6),
        network_id="net-a",
        reasons=("alt_listed",),
        alt_feed_count=1,
        headline_value=1_000_000.0,
        network_median=None,
        proposed="combined",
        proposed_feeds=2,
        rr_telecast_ids=("cfb-a-b-2025-09-06",),
    )
    decisions = {
        "cfb-a-b-2025-09-06": CombinedDecision("cfb-a-b-2025-09-06", "single", None, "other"),
        "cfb-gone-2025-09-13": CombinedDecision("cfb-gone-2025-09-13", "single", None, "other"),
    }
    assert orphan_decision_count([candidate], decisions) == 1


def test_main_never_writes_proposals_into_the_public_combined_table(
    build_vault: DataPaths,
    vault_reference: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    table = vault_reference / "combined_figures.csv"
    # Keep only the header, so every alt_listed candidate is undecided and
    # would have been pre-filled before WR-09.
    header = table.read_text(encoding="utf-8").splitlines()[0]
    table.write_text(header + "\n", encoding="utf-8")
    before = table.read_bytes()

    main([])

    assert table.read_bytes() == before
    out = capsys.readouterr().out
    assert "awaiting confirmation" in out
