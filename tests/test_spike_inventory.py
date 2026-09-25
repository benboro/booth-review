"""Tests for the RR/CFBD/rank-prefix inventory and `booth-review spike inventory`
(SPIKE-03 outside the 506 third, which 01-10's test_inventory_506.py already covers).

All fixtures here are synthetic (invented teams/schools/networks), copied or built
from the same fixture set plans 01-06 and 01-10 use. No real 506/RR/CFBD row
appears in this file (D-07).
"""

from __future__ import annotations

import json
from pathlib import Path

from booth_review.cli import main
from booth_review.config import DataPaths
from booth_review.spike.inventory import (
    build_cfbd_inventory,
    build_rr_inventory,
    compare_rank_prefixes,
    run_inventory,
    write_interim,
)

FIXTURES_RR = Path(__file__).parent / "fixtures" / "ratingsref"
FIXTURES_CFBD = Path(__file__).parent / "fixtures" / "cfbd"
FIXTURES_506 = Path(__file__).parent / "fixtures" / "sports506"


def _seed_rr_records(paths: DataPaths, *, season: int = 2025, count: int = 2) -> list[str]:
    """Copy tests/fixtures/ratingsref/record_synthetic.json `count` times into the
    tmp vault, each under a distinct invented telecast id.
    """
    template = json.loads((FIXTURES_RR / "record_synthetic.json").read_text())
    season_dir = paths.raw / "ratingsref" / "telecast" / str(season)
    season_dir.mkdir(parents=True, exist_ok=True)
    ids: list[str] = []
    for i in range(count):
        record = json.loads(json.dumps(template))
        telecast_id = f"cfb-example-team-a-example-team-b-2025-09-{13 + i:02d}"
        record["telecast"]["id"] = telecast_id
        (season_dir / f"{telecast_id}.json").write_text(json.dumps(record), encoding="utf-8")
        ids.append(telecast_id)
    return ids


def _seed_broken_rr_record(paths: DataPaths, *, season: int = 2025) -> str:
    """A record missing telecast.id: parse_record raises ParseError naming the
    field (test_parser_ratingsref.py's own contract for this case).
    """
    season_dir = paths.raw / "ratingsref" / "telecast" / str(season)
    season_dir.mkdir(parents=True, exist_ok=True)
    broken_id = "cfb-example-broken-record-2025-09-20"
    (season_dir / f"{broken_id}.json").write_text(
        json.dumps({"telecast": {"event_date": "2025-09-20"}}),
        encoding="utf-8",
    )
    return broken_id


def _seed_cfbd_season(paths: DataPaths, *, season: int = 2025) -> None:
    cfbd_dir = paths.raw / "cfbd"
    for kind in ("games", "media", "lines", "wp_pregame", "rankings"):
        (cfbd_dir / kind).mkdir(parents=True, exist_ok=True)
        content = (FIXTURES_CFBD / f"{kind}.json").read_text()
        (cfbd_dir / kind / f"{season}.json").write_text(content, encoding="utf-8")
    ledger_dir = paths.ledger
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_lines = [
        {
            "event": "call",
            "endpoint": "/games",
            "params": {},
            "called_at": "2026-09-25T00:00:00Z",
            "month": "2026-09",
            "status": 200,
            "call_limit_remaining_header": 900,
            "info_remaining_calls": None,
            "info_reset_at": None,
            "counted_against_quota": True,
            "discrepancy": False,
            "tag": None,
        },
        {
            "event": "call",
            "endpoint": "/info",
            "params": {},
            "called_at": "2026-09-25T00:05:00Z",
            "month": "2026-09",
            "status": 200,
            "call_limit_remaining_header": 899,
            "info_remaining_calls": 899,
            "info_reset_at": "2026-10-01T00:00:00.000Z",
            "counted_against_quota": False,
            "discrepancy": True,
            "tag": None,
        },
    ]
    with (ledger_dir / "cfbd_ledger.jsonl").open("w", encoding="utf-8") as fh:
        for line in ledger_lines:
            fh.write(json.dumps(line))
            fh.write("\n")


def _seed_506_week(paths: DataPaths, *, season: int = 2025) -> None:
    season_dir = paths.raw / "sports506" / str(season)
    season_dir.mkdir(parents=True, exist_ok=True)
    (season_dir / "wk-05.html").write_bytes((FIXTURES_506 / "week_synthetic.html").read_bytes())


_RANKINGS_WEEK5 = [
    {
        "season": 2025,
        "seasonType": "regular",
        "week": 5,
        "polls": [
            {
                "poll": "AP Top 25",
                "ranks": [
                    {"rank": 12, "school": "Northfield State", "conference": "Example Conf"},
                    {"rank": 9, "school": "Prairie State", "conference": "Example Conf"},
                ],
            }
        ],
    }
]


def _seed_rank_prefix_rankings(paths: DataPaths, *, season: int = 2025) -> None:
    rankings_dir = paths.raw / "cfbd" / "rankings"
    rankings_dir.mkdir(parents=True, exist_ok=True)
    (rankings_dir / f"{season}.json").write_text(json.dumps(_RANKINGS_WEEK5), encoding="utf-8")


# -- build_rr_inventory -----------------------------------------------------------------


def test_build_rr_inventory_counts_records_and_claim_vocabulary(vault_paths: DataPaths) -> None:
    _seed_rr_records(vault_paths, count=2)
    inv = build_rr_inventory(vault_paths, seasons=[2025])
    assert inv["records"] == 2
    assert inv["parse_failures"] == 0
    # Every copy has 2 avg_audience claims (final + preliminary) and 1 peak_audience
    # claim (final): status counts are claim-level, so final=4, preliminary=2.
    assert inv["status_counts"] == {"final": 4, "preliminary": 2}
    assert inv["metric_type_counts"] == {"avg_audience": 4, "peak_audience": 2}
    assert inv["records_with_multiple_avg_audience"] == 2


def test_build_rr_inventory_lists_unknown_extra_claim_keys(vault_paths: DataPaths) -> None:
    _seed_rr_records(vault_paths, count=2)
    inv = build_rr_inventory(vault_paths, seasons=[2025])
    assert "figure_type" in inv["extra_claim_keys"]
    assert inv["extra_claim_keys"]["figure_type"]["count"] == 2


def test_build_rr_inventory_records_parse_failures_without_stopping(
    vault_paths: DataPaths,
) -> None:
    _seed_rr_records(vault_paths, count=2)
    broken_id = _seed_broken_rr_record(vault_paths)
    inv = build_rr_inventory(vault_paths, seasons=[2025])
    assert inv["records"] == 2
    assert inv["parse_failures"] == 1
    assert broken_id in inv["parse_failure_ids"]


# -- build_cfbd_inventory ---------------------------------------------------------------


def test_build_cfbd_inventory_reports_startdate_and_week_numbering(
    vault_paths: DataPaths,
) -> None:
    _seed_cfbd_season(vault_paths)
    inv = build_cfbd_inventory(vault_paths, season=2025)
    assert inv["start_date_formats"] == {"Z": 4}
    assert inv["weeks_by_season_type"]["regular"] == [1]
    assert inv["weeks_by_season_type"]["postseason"] == [20]


def test_build_cfbd_inventory_reports_classification_and_media_fill_rate(
    vault_paths: DataPaths,
) -> None:
    _seed_cfbd_season(vault_paths)
    inv = build_cfbd_inventory(vault_paths, season=2025)
    assert inv["classification_counts"]["fbs"] == 7
    assert inv["classification_counts"]["fcs"] == 1
    # fixtures/cfbd/games.json has 3 FBS games in week 1 + 1 FBS postseason game;
    # fixtures/cfbd/media.json has one "tv" row (game 401520001) and one "web" row.
    assert inv["media_fill_rate"]["fbs_with_tv"] == 1


def test_build_cfbd_inventory_reports_poll_names_and_line_providers(
    vault_paths: DataPaths,
) -> None:
    _seed_cfbd_season(vault_paths)
    inv = build_cfbd_inventory(vault_paths, season=2025)
    assert "Example Top 25" in inv["poll_names"]
    assert inv["poll_names"]["Example Top 25"]["weeks"] == [5]
    assert inv["line_providers"] == {"ExampleBook": 1}


def test_build_cfbd_inventory_reports_ledger_facts(vault_paths: DataPaths) -> None:
    _seed_cfbd_season(vault_paths)
    inv = build_cfbd_inventory(vault_paths, season=2025)
    assert inv["ledger"]["discrepancy_count"] == 1
    assert inv["ledger"]["reset_at_values"] == {"2026-10-01T00:00:00.000Z": 1}


def test_build_cfbd_inventory_excitement_null_rate_by_season(vault_paths: DataPaths) -> None:
    _seed_cfbd_season(vault_paths, season=2025)
    inv = build_cfbd_inventory(vault_paths, season=2025)
    # fixtures/cfbd/games.json has 4 games, 1 with excitementIndex null.
    assert inv["excitement_null_rate_by_season"]["2025"] == {"total": 4, "nulls": 1, "pct": 25.0}


# -- compare_rank_prefixes --------------------------------------------------------------


def test_compare_rank_prefixes_counts_matches_and_mismatches(vault_paths: DataPaths) -> None:
    _seed_506_week(vault_paths)
    _seed_rank_prefix_rankings(vault_paths)
    result = compare_rank_prefixes(vault_paths, season=2025)
    week5 = result["by_week"]["5"]
    # Northfield State: 506 rank 12, AP rank 12 -> match.
    # Prairie State: 506 rank 4, AP rank 9 -> checked but mismatched rank.
    assert week5["total_ranked"] == 2
    assert week5["ap_checked"] == 2
    assert week5["ap_matches"] == 1
    assert week5["skipped_name_mismatch"] == 0


def test_compare_rank_prefixes_skips_unmatched_names(vault_paths: DataPaths) -> None:
    _seed_506_week(vault_paths)
    rankings = json.loads(json.dumps(_RANKINGS_WEEK5))
    del rankings[0]["polls"][0]["ranks"][1]  # drop Prairie State from the poll
    (vault_paths.raw / "cfbd" / "rankings").mkdir(parents=True, exist_ok=True)
    (vault_paths.raw / "cfbd" / "rankings" / "2025.json").write_text(
        json.dumps(rankings), encoding="utf-8"
    )
    result = compare_rank_prefixes(vault_paths, season=2025)
    week5 = result["by_week"]["5"]
    assert week5["ap_checked"] == 1
    assert week5["skipped_name_mismatch"] == 1


# -- write_interim -----------------------------------------------------------------------


def test_write_interim_writes_three_csvs_overwriting_previous(vault_paths: DataPaths) -> None:
    _seed_506_week(vault_paths)
    _seed_rr_records(vault_paths, count=1)
    _seed_cfbd_season(vault_paths)

    (vault_paths.interim / "sports506_listings_2025.csv").parent.mkdir(parents=True, exist_ok=True)
    (vault_paths.interim / "sports506_listings_2025.csv").write_text("stale", encoding="utf-8")

    counts = write_interim(vault_paths, season=2025)
    assert counts["sports506_listings"] == 4  # week_synthetic.html has 4 rows
    assert counts["ratingsref_claims"] == 3  # one record, 3 claims
    assert counts["cfbd_games"] == 4

    for name in (
        "sports506_listings_2025.csv",
        "ratingsref_claims_2025.csv",
        "cfbd_games_2025.csv",
    ):
        path = vault_paths.interim / name
        assert path.is_file()
    assert "stale" not in (vault_paths.interim / "sports506_listings_2025.csv").read_text(
        encoding="utf-8"
    )


# -- run_inventory / CLI -----------------------------------------------------------------


def test_run_inventory_writes_all_reports_and_interim(vault_paths: DataPaths) -> None:
    _seed_506_week(vault_paths)
    _seed_rr_records(vault_paths, count=1)
    _seed_cfbd_season(vault_paths)

    run_inventory(vault_paths, commit=False)

    for name in ("inventory-ratingsref.md", "inventory-ratingsref.json", "inventory-cfbd.md"):
        assert (vault_paths.spike / name).is_file()

    inv_506_md = (vault_paths.spike / "inventory-506.md").read_text(encoding="utf-8")
    assert "Filled in by plan 01-11" not in inv_506_md

    for name in (
        "sports506_listings_2025.csv",
        "ratingsref_claims_2025.csv",
        "cfbd_games_2025.csv",
    ):
        assert (vault_paths.interim / name).is_file()


def test_cli_spike_inventory_no_commit_sends_no_request(git_vault, monkeypatch) -> None:
    monkeypatch.setattr(
        "booth_review.runtime.make_client",
        lambda: (_ for _ in ()).throw(AssertionError("no client should be built")),
    )
    _seed_506_week(git_vault)
    _seed_rr_records(git_vault, count=1)
    _seed_cfbd_season(git_vault)

    exit_code = main(["spike", "inventory", "--no-commit"])
    assert exit_code == 0
    assert (git_vault.spike / "inventory-ratingsref.md").is_file()
    assert (git_vault.spike / "inventory-cfbd.md").is_file()
    assert (git_vault.spike / "inventory-506.md").is_file()
