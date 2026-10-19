"""Booth tiers through a full synthetic build (invented data only)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import polars as pl
from test_build_bowls_pipeline import _vault_with_sentinel_note
from test_build_pipeline_determinism import _write_manifest
from test_cfb_golden import _CFB_MANIFEST, _KNOWN_BOWLS

from booth_review.build.pipeline import run_build
from booth_review.config import DataPaths
from booth_review.contract.models import validate_site_data

COUNT_KEYS = (
    "tiered_telecasts",
    "a",
    "b",
    "other",
    "conference_lead",
    "fill_in",
    "no_pbp",
    "multi_pbp",
    "untiered_family_seasons",
    "untiered_review_rows",
)


def _reference(git_vault: DataPaths, tmp_path: Path) -> Path:
    """The synthetic reference with the ECN networks in fox and the ESPN ones in disney."""
    base = _vault_with_sentinel_note(git_vault, tmp_path, _KNOWN_BOWLS)
    target = tmp_path / "booth-build-reference"
    shutil.copytree(base, target)
    networks = target / "networks.csv"
    networks.write_text(
        networks.read_text().replace("family-ecn", "fox").replace("family-espn", "disney")
    )
    _write_manifest(git_vault, _CFB_MANIFEST)
    return target


def _site(git_vault: DataPaths) -> dict:
    return json.loads((git_vault.vault / "processed" / "site-data.json").read_text())


def _review(git_vault: DataPaths) -> pl.DataFrame:
    return pl.read_csv(git_vault.vault / "interim" / "review_cfb_booths_untiered.csv")


def test_no_cited_table_ships_no_booths_and_lists_family_seasons(
    git_vault: DataPaths, tmp_path: Path
) -> None:
    ref = _reference(git_vault, tmp_path)
    outcome = run_build(git_vault, ref, commit=False, accept_baseline=True)
    payload = _site(git_vault)
    validate_site_data(payload)
    assert payload["lookups"]["booths"] == []
    assert all(b is None for b in payload["telecasts"]["booth"])
    review = _review(git_vault)
    assert review.height > 0
    assert set(review["family"].to_list()) <= {"fox", "disney"}
    for key in COUNT_KEYS:
        assert isinstance(outcome.counts[f"cfb_booths_{key}"], int)
    assert outcome.counts["cfb_booths_tiered_telecasts"] == 0
    assert outcome.counts["cfb_booths_untiered_review_rows"] == review.height


def test_cited_booth_flows_to_site_data_and_leaves_review(
    git_vault: DataPaths, tmp_path: Path
) -> None:
    ref = _reference(git_vault, tmp_path)
    run_build(git_vault, ref, commit=False, accept_baseline=True)
    row = _review(git_vault).row(0, named=True)
    people = pl.read_parquet(git_vault.vault / "processed" / "people.parquet")
    names = dict(zip(people["person_id"], people["canonical_name"], strict=True))
    pbp = row["pbp_person_id"]
    analyst = row["analyst_person_id"]
    assert analyst is not None
    with (ref / "people.csv").open("a", encoding="utf-8", newline="") as fh:
        fh.write(f"{pbp},{names[pbp]},{names[pbp]},pbp,\n")
        fh.write(f"{analyst},{names[analyst]},{names[analyst]},analyst,\n")
    (ref / "cfb_booth_ranks.csv").write_text(
        "family,season,rank,pbp,analyst,scope,source_url\n"
        f"{row['family']},{row['season']},1,{names[pbp]},{names[analyst]},,"
        "https://example.com/lineup\n",
        encoding="utf-8",
    )
    outcome = run_build(git_vault, ref, commit=False, accept_baseline=True)
    payload = _site(git_vault)
    validate_site_data(payload)
    booths = payload["lookups"]["booths"]
    assert len(booths) == 1
    assert (booths[0]["tier"], booths[0]["rank"]) == ("a", 1)
    shipped = payload["telecasts"]["booth"] + payload["telecasts_unrated"]["booth"]
    assert any(b is not None for b in shipped)
    assert outcome.counts["cfb_booths_a"] >= 1
    remaining = _review(git_vault)
    assert not (
        (remaining["family"] == row["family"]) & (remaining["season"] == row["season"])
    ).any()
