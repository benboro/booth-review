"""Tests for resolve/inputs.py: the raw-input loaders that generalize
spike/join.py's fixed-2025 loaders off any season/week set actually present
in the vault (JOIN-02..04).

Fixtures: tests/fixtures/spike/{cfbd_games_2025.json,506_wk-*.html,
rr_records/*.json} (invented teams, people, and figures only; D-07).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from booth_review.config import DataPaths
from booth_review.resolve.inputs import (
    load_506_listings,
    load_cfbd_games,
    load_rr_records,
    shown_outlet_crew,
    vault_seasons,
)
from booth_review.resolve.networks import NetworkTable, load_networks
from booth_review.sources.sports506.parser import CrewLine, Listing506

FIXTURES = Path(__file__).parent / "fixtures" / "spike"


def _seed_cfbd_games(paths: DataPaths, season: int) -> None:
    games_dir = paths.raw / "cfbd" / "games"
    games_dir.mkdir(parents=True, exist_ok=True)
    (games_dir / f"{season}.json").write_bytes((FIXTURES / "cfbd_games_2025.json").read_bytes())


def _seed_506_weeks(paths: DataPaths, season: int) -> None:
    season_dir = paths.raw / "sports506" / str(season)
    season_dir.mkdir(parents=True, exist_ok=True)
    (season_dir / "wk-01.html").write_bytes((FIXTURES / "506_wk-01.html").read_bytes())
    (season_dir / "wk-B.html").write_bytes((FIXTURES / "506_wk-B.html").read_bytes())


def _seed_rr_records(paths: DataPaths, season: int) -> None:
    fixtures = FIXTURES / "rr_records"
    season_dir = paths.raw / "ratingsref" / "telecast" / str(season)
    season_dir.mkdir(parents=True, exist_ok=True)
    for record_path in sorted(fixtures.glob("*.json")):
        (season_dir / record_path.name).write_bytes(record_path.read_bytes())


# -- inputs.vault_seasons ------------------------------------------------------------------


def test_vault_seasons_returns_sorted_seasons_with_a_cached_games_file(
    vault_paths: DataPaths,
) -> None:
    _seed_cfbd_games(vault_paths, 2015)
    _seed_cfbd_games(vault_paths, 2014)
    assert vault_seasons(vault_paths) == [2014, 2015]


def test_vault_seasons_excludes_seasons_before_2014(vault_paths: DataPaths) -> None:
    _seed_cfbd_games(vault_paths, 2013)
    _seed_cfbd_games(vault_paths, 2014)
    assert vault_seasons(vault_paths) == [2014]


def test_vault_seasons_empty_when_no_games_directory(vault_paths: DataPaths) -> None:
    assert vault_seasons(vault_paths) == []


# -- inputs.load_cfbd_games -----------------------------------------------------------------


def test_load_cfbd_games_parses_the_cached_file(vault_paths: DataPaths) -> None:
    _seed_cfbd_games(vault_paths, 2025)
    games = load_cfbd_games(vault_paths, 2025)
    assert len(games) > 0


def test_load_cfbd_games_returns_empty_list_when_file_missing(vault_paths: DataPaths) -> None:
    assert load_cfbd_games(vault_paths, 2025) == []


# -- inputs.load_506_listings ---------------------------------------------------------------


def test_load_506_listings_parses_every_week_file_in_week_order(vault_paths: DataPaths) -> None:
    _seed_506_weeks(vault_paths, 2025)
    listings = load_506_listings(vault_paths, 2025)
    labels_seen = [ln.week_label for ln in listings]
    # wk-01 rows must all come before wk-B rows (0..16 then B ordering).
    first_b_index = labels_seen.index("B")
    assert all(label != "B" for label in labels_seen[:first_b_index])
    assert len(listings) > 0


def test_load_506_listings_empty_when_no_season_directory(vault_paths: DataPaths) -> None:
    assert load_506_listings(vault_paths, 2025) == []


# -- inputs.load_rr_records -----------------------------------------------------------------


def test_load_rr_records_returns_every_record_with_zero_parse_errors(
    vault_paths: DataPaths,
) -> None:
    _seed_rr_records(vault_paths, 2025)
    records, parse_error_count = load_rr_records(vault_paths, 2025)
    assert len(records) == 8
    assert parse_error_count == 0


def test_load_rr_records_counts_unparseable_files_without_dropping_silently(
    vault_paths: DataPaths,
) -> None:
    _seed_rr_records(vault_paths, 2025)
    season_dir = vault_paths.raw / "ratingsref" / "telecast" / "2025"
    (season_dir / "cfb-broken-record-2025-01-01.json").write_bytes(b"{not valid json")

    records, parse_error_count = load_rr_records(vault_paths, 2025)
    assert len(records) == 8
    assert parse_error_count == 1


def test_load_rr_records_empty_when_no_season_directory(vault_paths: DataPaths) -> None:
    records, parse_error_count = load_rr_records(vault_paths, 2025)
    assert records == []
    assert parse_error_count == 0


# -- inputs.shown_outlet_crew --------------------------------------------------------------

_NETWORKS_CSV = (
    "variant,network_id,display_name,family,tier,feed_type,season_from,season_to,priority\n"
    "KXMP (Example City),local-affiliate,Local Affiliate,other,other,main,,,\n"
    "ECN+,example-conference-network,Example Conference Network,conference,conference,main,,,\n"
    "Example Network,example-network,Example Network,other,regional,main,,,\n"
    "Example Network Union Sports,example-network,Example Network,other,regional,main,,,\n"
)


def _networks(tmp_path: Path) -> NetworkTable:
    (tmp_path / "networks.csv").write_text(_NETWORKS_CSV)
    return load_networks(tmp_path)


def _listing(network_raw: str, lines: tuple[CrewLine, ...]) -> Listing506:
    return Listing506(
        season=2026,
        week_label="8",
        source_row_index=0,
        date_et=date(2026, 10, 17),
        kickoff_et=None,
        away_raw="Prairie State",
        away_rank=None,
        home_raw="Union City",
        home_rank=None,
        neutral=False,
        network_raw=network_raw,
        crew_raw="(not read)",
        crew_names=tuple(name for line in lines for name in line.names),
        feed_kind="main",
        game_label=None,
        crew_lines=lines,
    )


_LOCAL = CrewLine(outlet="KXMP", names=("Pat Example", "Jordan Sample"))
_CONFERENCE = CrewLine(outlet="ECN+", names=("Casey Demo", "Riley Mock"))


def test_shown_outlet_crew_keeps_the_crew_of_the_primary_network(tmp_path: Path) -> None:
    listing = _listing("KXMP (Example City) / ECN+", (_LOCAL, _CONFERENCE))
    picked = shown_outlet_crew(listing, _networks(tmp_path))
    assert picked.crew_names == ("Casey Demo", "Riley Mock")
    assert picked.crew_lines == listing.crew_lines


def test_shown_outlet_crew_matches_a_positional_outlet(tmp_path: Path) -> None:
    lines = (
        CrewLine(outlet="Example Network", names=("Pat Example", "Jordan Sample", "Avery Test")),
        CrewLine(outlet="Union Sports", names=("Casey Demo", "Riley Mock")),
    )
    picked = shown_outlet_crew(_listing("Example Network Union Sports", lines), _networks(tmp_path))
    assert picked.crew_names == ("Pat Example", "Jordan Sample", "Avery Test")


@pytest.mark.parametrize(
    ("network_raw", "lines"),
    [
        ("KXMP (Example City) / ECN+", (_LOCAL, CrewLine(outlet=None, names=("Casey Demo",)))),
        ("KXMP (Example City) / ECN+", (_LOCAL, CrewLine(outlet="ECN", names=("Casey Demo",)))),
        ("ECN+", (_CONFERENCE, CrewLine(outlet="ECN+", names=("Avery Test",)))),
        ("Unlisted Network", (_LOCAL, _CONFERENCE)),
    ],
    ids=["unknown-outlet", "no-line-matches", "two-lines-match", "unmapped-network"],
)
def test_shown_outlet_crew_keeps_every_name_when_no_single_line_matches(
    tmp_path: Path, network_raw: str, lines: tuple[CrewLine, ...]
) -> None:
    listing = _listing(network_raw, lines)
    assert shown_outlet_crew(listing, _networks(tmp_path)) == listing
