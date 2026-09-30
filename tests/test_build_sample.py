"""Tests for build/sample.py: the JOIN-08 stratified sample of 50 plotted
telecasts (D-08 precedent). In-memory-frame behavior tests plus one real run
against build_vault's own raw fixture through run_build(..., commit=False)
then sample_from_vault, matching test_build_coverage.py's own real-fixture
pattern.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from booth_review.build.games import GAMES_SCHEMA
from booth_review.build.pipeline import run_build
from booth_review.build.sample import (
    SAMPLE_COLUMNS,
    SampleRow,
    _season_allocation,
    sample_from_vault,
    stratified_sample,
    write_sample,
)
from booth_review.build.tables import PEOPLE_SCHEMA, TELECAST_PEOPLE_SCHEMA
from booth_review.build.telecasts import TELECASTS_SCHEMA
from booth_review.config import DataPaths
from booth_review.reference import reference_dir

_SPIKE_FIXTURES = Path(__file__).parent / "fixtures" / "spike"
_BUILD_FIXTURES = Path(__file__).parent / "fixtures" / "build"
_REFERENCE_FIXTURES = Path(__file__).parent / "fixtures" / "reference"


# -- in-memory frame builders (mirrors test_build_coverage.py's own shape) -----------------


def _game_row(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "game_id": 1,
        "season": 2024,
        "week": 1,
        "season_type": "regular",
        "start_utc": None,
        "date_et": date(2024, 9, 6),
        "kickoff_et": "2024-09-06T20:00:00-04:00",
        "neutral_site": False,
        "conference_game": False,
        "home_id": 100,
        "home_team": "Example State",
        "home_classification": "fbs",
        "home_conference": "Example Conference",
        "home_points": 20,
        "away_id": 200,
        "away_team": "Sample Tech",
        "away_classification": "fbs",
        "away_conference": "Sample Conference",
        "away_points": 10,
        "excitement": 5.0,
        "closing_spread": -3.0,
        "spread_provider": "consensus",
        "pregame_x": -3.0,
        "home_win_prob": 0.65,
        "home_rank": 5,
        "away_rank": None,
        "rank_poll": "AP Top 25",
    }
    defaults.update(overrides)
    return defaults


def _games_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=GAMES_SCHEMA)


def _telecast_row(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "telecast_id": "1-net-a",
        "game_id": 1,
        "season": 2024,
        "date_et": date(2024, 9, 6),
        "network_id": "net-a",
        "feed_type": "main",
        "outlets": ["net-a"],
        "rated": True,
        "rr_telecast_ids": [],
        "rr_record_urls": ["https://ratingsreference.com/telecast/cfb-example-2024-09-06"],
        "duplicate_merges": 0,
        "rr_match_confidence": "exact",
        "s506_match_confidence": "exact",
        "match_confidence": "exact",
        "s506_pointer": "1:0",
        "s506_week": "1",
        "s506_url": "https://506sports.com/ncaaf.php?yr=2024&wk=1",
        "kickoff_et": "2024-09-06T20:00:00",
        "crew_matched": True,
        "crew_network_mismatch": False,
        "combined_feeds": None,
        "plotted": True,
        "headline_claim_id": "claim-1",
        "headline_value": 1_000_000.0,
        "headline_publisher": "Pub1",
        "headline_source_url": "https://example.com/story",
        "measurement_type": "nielsen",
        "era_id": "era-a",
        "rr_current_check": "agree",
        "model_break": False,
    }
    defaults.update(overrides)
    return defaults


def _telecasts_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=TELECASTS_SCHEMA)


def _people_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=PEOPLE_SCHEMA)


def _telecast_people_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=TELECAST_PEOPLE_SCHEMA)


def _people_row(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "person_id": "pat-example",
        "canonical_name": "Pat Example",
        "variants": ["Pat Example"],
        "usual_role": "pbp",
        "registered": True,
    }
    defaults.update(overrides)
    return defaults


def _telecast_people_row(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "telecast_id": "1-net-a",
        "person_id": "pat-example",
        "role": "pbp",
        "feed_type": "main",
        "crew_position": 0,
        "s506_pointer": "1:0",
        "source": "registered",
    }
    defaults.update(overrides)
    return defaults


def _make_season_telecasts(
    season: int, network_counts: dict[str, int], *, game_offset: int, non_exact: int = 0
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """`non_exact` telecasts (from the front of the flattened list) get a
    "date-shift" match_confidence instead of "exact"."""
    games: list[dict[str, object]] = []
    telecasts: list[dict[str, object]] = []
    game_id = game_offset
    flat_index = 0
    for network_id, count in network_counts.items():
        for _i in range(count):
            game_id += 1
            games.append(_game_row(game_id=game_id, season=season))
            confidence = "date-shift" if flat_index < non_exact else "exact"
            telecasts.append(
                _telecast_row(
                    telecast_id=f"{game_id}-{network_id}",
                    game_id=game_id,
                    season=season,
                    network_id=network_id,
                    match_confidence=confidence,
                    rr_record_urls=[f"https://ratingsreference.com/telecast/cfb-g{game_id}"],
                )
            )
            flat_index += 1
    return games, telecasts


# -- _season_allocation ----------------------------------------------------------------


def test_season_allocation_gives_at_least_two_per_season() -> None:
    counts = {2020: 5, 2021: 500, 2022: 5}
    alloc = _season_allocation(counts, 20)
    assert alloc[2020] >= 2
    assert alloc[2022] >= 2
    assert sum(alloc.values()) == 20


def test_season_allocation_is_proportional_to_season_size() -> None:
    counts = {2020: 100, 2021: 300}
    alloc = _season_allocation(counts, 20)
    # 2021 has 3x the telecasts of 2020, so it should get noticeably more.
    assert alloc[2021] > alloc[2020]
    assert sum(alloc.values()) == 20


def test_season_allocation_never_exceeds_available() -> None:
    counts = {2020: 1, 2021: 100}
    alloc = _season_allocation(counts, 20)
    assert alloc[2020] == 1  # only 1 telecast exists that season
    assert sum(alloc.values()) == 20


def test_season_allocation_caps_size_to_total() -> None:
    counts = {2020: 2, 2021: 3}
    alloc = _season_allocation(counts, 50)
    assert alloc == {2020: 2, 2021: 3}


# -- stratified_sample -------------------------------------------------------------------


def test_stratified_sample_draws_only_plotted_telecasts() -> None:
    games, telecasts = _make_season_telecasts(2024, {"net-a": 3}, game_offset=0)
    telecasts.append(_telecast_row(telecast_id="99-net-a", game_id=99, season=2024, plotted=False))
    games.append(_game_row(game_id=99, season=2024))

    result = stratified_sample(
        _telecasts_frame(telecasts),
        _telecast_people_frame([]),
        _people_frame([]),
        _games_frame(games),
        size=2,
        seed=1,
    )
    assert all(row.telecast_id != "99-net-a" for row in result)


def test_stratified_sample_leaves_out_crews_from_crew_overrides() -> None:
    games, telecasts = _make_season_telecasts(2024, {"net-a": 3}, game_offset=0)
    telecasts.append(
        _telecast_row(telecast_id="97-net-a", game_id=97, season=2024, crew_patched=True)
    )
    telecasts.append(_telecast_row(telecast_id="98-net-a", game_id=98, season=2024))
    games += [_game_row(game_id=97, season=2024), _game_row(game_id=98, season=2024)]
    telecast_people = [
        # A correction/differs override: 506 listed a crew, the override replaced it.
        _telecast_people_row(telecast_id="98-net-a", s506_pointer=None, source="crew_override"),
        # An alt-feed row alone never excludes a telecast.
        _telecast_people_row(
            telecast_id="1-net-a", feed_type="alt", s506_pointer=None, source="crew_override"
        ),
    ]

    result = stratified_sample(
        _telecasts_frame(telecasts),
        _telecast_people_frame(telecast_people),
        _people_frame([]),
        _games_frame(games),
        size=10,
        seed=1,
    )
    drawn = {row.telecast_id for row in result}
    assert drawn.isdisjoint({"97-net-a", "98-net-a"})
    assert len(drawn) == 3
    assert "1-net-a" in drawn


def test_stratified_sample_allocates_at_least_two_per_season() -> None:
    games_a, telecasts_a = _make_season_telecasts(2020, {"net-a": 2}, game_offset=0)
    games_b, telecasts_b = _make_season_telecasts(2021, {"net-a": 20}, game_offset=100)
    result = stratified_sample(
        _telecasts_frame(telecasts_a + telecasts_b),
        _telecast_people_frame([]),
        _people_frame([]),
        _games_frame(games_a + games_b),
        size=10,
        seed=1,
    )
    by_season: dict[int, int] = {}
    for row in result:
        by_season[row.season] = by_season.get(row.season, 0) + 1
    assert by_season[2020] >= 2
    assert len(result) == 10


def test_stratified_sample_round_robins_across_networks_in_a_season() -> None:
    games, telecasts = _make_season_telecasts(
        2024, {"net-a": 6, "net-b": 6, "net-c": 6}, game_offset=0
    )
    result = stratified_sample(
        _telecasts_frame(telecasts),
        _telecast_people_frame([]),
        _people_frame([]),
        _games_frame(games),
        size=9,
        seed=1,
    )
    by_network: dict[str, int] = {}
    for row in result:
        by_network[row.network_id or ""] = by_network.get(row.network_id or "", 0) + 1
    # Evenly split across the 3 equally-sized networks, never bunched on one.
    assert by_network == {"net-a": 3, "net-b": 3, "net-c": 3}


def test_stratified_sample_includes_minimum_non_exact_rows() -> None:
    games, telecasts = _make_season_telecasts(2024, {"net-a": 40}, game_offset=0, non_exact=15)
    result = stratified_sample(
        _telecasts_frame(telecasts),
        _telecast_people_frame([]),
        _people_frame([]),
        _games_frame(games),
        size=10,
        seed=1,
    )
    non_exact_count = sum(1 for row in result if row.match_confidence != "exact")
    assert non_exact_count >= min(10, 15)


def test_stratified_sample_non_exact_floor_is_capped_by_availability() -> None:
    games, telecasts = _make_season_telecasts(2024, {"net-a": 40}, game_offset=0, non_exact=3)
    result = stratified_sample(
        _telecasts_frame(telecasts),
        _telecast_people_frame([]),
        _people_frame([]),
        _games_frame(games),
        size=10,
        seed=1,
    )
    non_exact_count = sum(1 for row in result if row.match_confidence != "exact")
    assert non_exact_count == 3  # only 3 exist at all; can't reach 10


def test_stratified_sample_is_deterministic_for_the_same_seed() -> None:
    games, telecasts = _make_season_telecasts(2024, {"net-a": 20, "net-b": 20}, game_offset=0)
    kwargs = dict(
        telecasts=_telecasts_frame(telecasts),
        telecast_people=_telecast_people_frame([]),
        people=_people_frame([]),
        games=_games_frame(games),
        size=10,
        seed=42,
    )
    first = [row.telecast_id for row in stratified_sample(**kwargs)]
    second = [row.telecast_id for row in stratified_sample(**kwargs)]
    assert first == second


def test_stratified_sample_differs_for_a_different_seed() -> None:
    games, telecasts = _make_season_telecasts(2024, {"net-a": 30, "net-b": 30}, game_offset=0)
    common = dict(
        telecasts=_telecasts_frame(telecasts),
        telecast_people=_telecast_people_frame([]),
        people=_people_frame([]),
        games=_games_frame(games),
        size=10,
    )
    seed_a = [row.telecast_id for row in stratified_sample(**common, seed=1)]
    seed_b = [row.telecast_id for row in stratified_sample(**common, seed=2)]
    assert seed_a != seed_b


def test_stratified_sample_matchup_text_neutral_vs_home_away() -> None:
    games = [
        _game_row(game_id=1, season=2024, neutral_site=False),
        _game_row(game_id=2, season=2024, neutral_site=True),
    ]
    telecasts = [
        _telecast_row(telecast_id="1-net-a", game_id=1, season=2024, network_id="net-a"),
        _telecast_row(telecast_id="2-net-a", game_id=2, season=2024, network_id="net-a"),
    ]
    result = stratified_sample(
        _telecasts_frame(telecasts),
        _telecast_people_frame([]),
        _people_frame([]),
        _games_frame(games),
        size=2,
        seed=1,
    )
    by_id = {row.telecast_id: row for row in result}
    assert by_id["1-net-a"].matchup == "Sample Tech @ Example State"
    assert by_id["2-net-a"].matchup == "Sample Tech vs Example State"


def test_stratified_sample_crew_is_main_feed_only_ordered_by_position() -> None:
    games = [_game_row(game_id=1, season=2024)]
    telecasts = [_telecast_row(telecast_id="1-net-a", game_id=1, season=2024, network_id="net-a")]
    people = [
        _people_row(person_id="pbp-person", canonical_name="Robin PBP"),
        _people_row(person_id="analyst-person", canonical_name="Drew Analyst"),
        _people_row(person_id="alt-person", canonical_name="Alt Feed Person"),
    ]
    telecast_people = [
        _telecast_people_row(
            telecast_id="1-net-a",
            person_id="analyst-person",
            role="analyst",
            feed_type="main",
            crew_position=1,
        ),
        _telecast_people_row(
            telecast_id="1-net-a",
            person_id="pbp-person",
            role="pbp",
            feed_type="main",
            crew_position=0,
        ),
        _telecast_people_row(
            telecast_id="1-net-a",
            person_id="alt-person",
            role="unknown",
            feed_type="alt",
            crew_position=0,
        ),
    ]
    result = stratified_sample(
        _telecasts_frame(telecasts),
        _telecast_people_frame(telecast_people),
        _people_frame(people),
        _games_frame(games),
        size=1,
        seed=1,
    )
    assert result[0].crew == "Robin PBP (pbp); Drew Analyst (analyst)"


# -- write_sample -------------------------------------------------------------------------


def test_write_sample_writes_sample_columns_with_pending_status(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    (paths.vault / "interim").mkdir(parents=True)
    rows = [
        SampleRow(
            telecast_id="1-net-a",
            season=2024,
            date_et="2024-09-06",
            kickoff_et="2024-09-06T20:00:00",
            matchup="Sample Tech @ Example State",
            network_id="net-a",
            crew="Robin PBP (pbp)",
            headline_viewers=1_000_000,
            publisher="Pub1",
            rr_record_urls="https://ratingsreference.com/telecast/cfb-example",
            s506_url="https://506sports.com/ncaaf.php?yr=2024&wk=1",
            match_confidence="exact",
            crew_network_mismatch=False,
        )
    ]
    rel_path = write_sample(paths, rows)
    assert rel_path == "interim/join08_sample.csv"
    written = (paths.vault / rel_path).read_text(encoding="utf-8")
    header, first_row, *_ = written.splitlines()
    assert header == ",".join(SAMPLE_COLUMNS)
    assert first_row.startswith("1,2024,")
    assert first_row.endswith(",pending,")


# -- real-fixture run: run_build -> sample_from_vault --------------------------------------


def _seed_build_raw(paths: DataPaths) -> None:
    """The exact raw-file layout conftest.py's `build_vault` fixture seeds,
    reused here (as a real git working copy) since `run_build` requires one.
    """
    games_dir = paths.raw / "cfbd" / "games"
    games_dir.mkdir(parents=True, exist_ok=True)
    (games_dir / "2025.json").write_bytes((_SPIKE_FIXTURES / "cfbd_games_2025.json").read_bytes())

    for endpoint in ("lines", "rankings", "media", "wp_pregame", "teams_fbs"):
        endpoint_dir = paths.raw / "cfbd" / endpoint
        endpoint_dir.mkdir(parents=True, exist_ok=True)
        (endpoint_dir / "2025.json").write_bytes(
            (_BUILD_FIXTURES / "cfbd" / f"{endpoint}_2025.json").read_bytes()
        )

    sports506_dir = paths.raw / "sports506" / "2025"
    sports506_dir.mkdir(parents=True, exist_ok=True)
    (sports506_dir / "wk-01.html").write_bytes((_SPIKE_FIXTURES / "506_wk-01.html").read_bytes())
    (sports506_dir / "wk-B.html").write_bytes((_SPIKE_FIXTURES / "506_wk-B.html").read_bytes())

    rr_dir = paths.raw / "ratingsref" / "telecast" / "2025"
    rr_dir.mkdir(parents=True, exist_ok=True)
    for record_path in sorted((_SPIKE_FIXTURES / "rr_records").glob("*.json")):
        (rr_dir / record_path.name).write_bytes(record_path.read_bytes())

    subprocess.run(["git", "-C", str(paths.vault), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(paths.vault), "commit", "-q", "-m", "test: seed raw fixture"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(paths.vault), "push", "-q", "origin", "main"],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def sample_git_vault(
    git_vault: DataPaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> DataPaths:
    """A real git vault seeded with build_vault's 2025 raw fixture, plus the
    same ECN/ESPN network-row extension test_cli_build.py's `build_git_vault`
    uses (this plan's files_modified is limited to this test file, so the
    fixture is duplicated locally rather than imported across test modules).
    """
    _seed_build_raw(git_vault)

    extended = tmp_path / "reference_ext"
    shutil.copytree(_REFERENCE_FIXTURES, extended)
    with (extended / "networks.csv").open("a", encoding="utf-8", newline="") as fh:
        fh.write("ECN,ecn,Example Cable Network,family-ecn,cable,main,,,\n")
        fh.write("ECN2,ecn2,Example Cable Network 2,family-ecn,cable,main,,,\n")
        fh.write("ESPN,espn,ESPN,family-espn,cable,main,,,\n")
        fh.write("ESPN2,espn2,ESPN2,family-espn,cable,main,,,\n")
        fh.write("ESPNU,espnu,ESPNU,family-espn,cable,main,,,\n")
        fh.write("ESPN Deportes,espn-deportes,ESPN Deportes,family-espn,cable,spanish,,,\n")
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(extended))

    return git_vault


def test_sample_from_vault_after_a_real_build(sample_git_vault: DataPaths) -> None:
    outcome = run_build(sample_git_vault, reference_dir(), commit=False, accept_baseline=False)
    assert outcome.blocked is False

    rows = sample_from_vault(sample_git_vault, size=5, seed=2026)
    assert 0 < len(rows) <= 5

    rel_path = write_sample(sample_git_vault, rows)
    assert (sample_git_vault.vault / rel_path).is_file()


# -- WR-17: --size is honored and the non-exact top-up never empties a season ----------------


def test_season_allocation_honors_a_size_smaller_than_two_per_season() -> None:
    counts = {season: 50 for season in range(2014, 2027)}
    alloc = _season_allocation(counts, 10)
    assert sum(alloc.values()) == 10


def test_season_allocation_non_positive_size_is_empty() -> None:
    counts = {2020: 5, 2021: 5}
    assert sum(_season_allocation(counts, -3).values()) == 0
    assert sum(_season_allocation(counts, 0).values()) == 0


def test_non_exact_top_up_never_empties_another_season() -> None:
    games_a, telecasts_a = _make_season_telecasts(2020, {"net-a": 2}, game_offset=0)
    games_b, telecasts_b = _make_season_telecasts(
        2021, {"net-a": 12}, game_offset=100, non_exact=12
    )
    result = stratified_sample(
        _telecasts_frame(telecasts_a + telecasts_b),
        _telecast_people_frame([]),
        _people_frame([]),
        _games_frame(games_a + games_b),
        size=4,
        seed=1,
    )
    seasons = [row.season for row in result]
    assert seasons.count(2020) == 2
    assert len(result) == 4


def test_main_rejects_a_non_positive_size(build_vault: DataPaths) -> None:
    from booth_review.build.sample import main

    with pytest.raises(SystemExit) as excinfo:
        main(["--size", "0"])
    assert excinfo.value.code == 2
