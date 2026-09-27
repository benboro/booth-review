"""Tests for build/telecasts.py: matching, primary-network resolution,
duplicate-record merge (JOIN-05), listing attachment/crew (JOIN-03), and the
outlet union (JOIN-06).

Two styles of fixture are used, matching test_build_games.py's own pattern:

- The shared `build_vault` + `build_reference` fixtures (D-07 synthetic
  vault), extended with a handful of network rows (`vault_networks` below)
  the shared RR/506 fixtures' own outlet text (ECN, ESPN, ...) needs but
  `build_reference`'s own networks.csv (Net A..G, the CFBD-media side of the
  hover union) doesn't cover -- used for the duplicate-merge truth the
  fixture corpus was purpose-built for (JOIN-05) and cross-module
  determinism/consistency checks.
- Hand-built CfbdGame/Listing506/RRRecord/NetworkTable/TeamResolver objects
  (no reference CSVs at all) for the more surgical per-rule tests, the same
  pattern test_build_games.py uses for behaviors its own shared fixture
  doesn't exercise.
"""

from __future__ import annotations

import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from booth_review.build.games import build_games_frame
from booth_review.build.sources import SeasonSources, load_all_sources
from booth_review.build.telecasts import (
    TELECASTS_SCHEMA,
    TelecastBuild,
    build_telecasts,
)
from booth_review.config import DataPaths
from booth_review.resolve.games import GameIndex
from booth_review.resolve.names import to_et_date
from booth_review.resolve.networks import NetworkRow, NetworkTable
from booth_review.resolve.overrides import GameOverride, load_game_overrides
from booth_review.resolve.teams import TeamResolver, load_team_crosswalk
from booth_review.sources.cfbd.parser import CfbdGame
from booth_review.sources.ratingsref.parser import RRClaim, RRRecord, RRTelecast
from booth_review.sources.sports506.parser import Listing506

# -- Shared-fixture wiring (build_vault + build_reference, extended) ------------------------


@pytest.fixture
def vault_reference(build_reference: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`build_reference`'s fixture dir, plus the ECN/ESPN network rows the
    shared spike RR/506 fixtures' own outlet text needs (D-07, invented).
    `build_reference`'s own networks.csv only covers the CFBD-media side
    (Net A..G); it was never meant to cover the RR/506 spike fixtures too.
    """
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


def _wire(
    paths: DataPaths, reference_dir: Path
) -> tuple[
    list[SeasonSources],
    pl.DataFrame,
    TeamResolver,
    GameIndex,
    dict[tuple[str, int, str], GameOverride],
    NetworkTable,
    dict[int, str],
    dict[int, list[str]],
]:
    from booth_review.resolve.networks import load_networks, load_primary_overrides

    sources = load_all_sources(paths, seasons=[2025])
    games_frame = build_games_frame(sources)
    crosswalk = load_team_crosswalk(reference_dir)
    resolver = TeamResolver({s.season: s.games for s in sources}, crosswalk)
    index = GameIndex([g for s in sources for g in s.games])
    overrides = load_game_overrides(reference_dir)
    networks = load_networks(reference_dir)
    primary_overrides = load_primary_overrides(reference_dir)

    media_by_game: dict[int, list[str]] = {}
    for season_sources in sources:
        for media in season_sources.media:
            if media.outlet:
                media_by_game.setdefault(media.id, []).append(media.outlet)

    return (
        sources,
        games_frame,
        resolver,
        index,
        overrides,
        networks,
        primary_overrides,
        media_by_game,
    )


def _build(paths: DataPaths, reference_dir: Path) -> TelecastBuild:
    sources, games_frame, resolver, index, overrides, networks, primary_overrides, media_by_game = (
        _wire(paths, reference_dir)
    )
    return build_telecasts(
        sources, games_frame, resolver, index, overrides, networks, primary_overrides, media_by_game
    )


# -- JOIN-05: duplicate RR record merge -------------------------------------------------------


def test_duplicate_rr_records_merge_into_one_telecast(
    build_vault: DataPaths, vault_reference: Path
) -> None:
    result = _build(build_vault, vault_reference)

    row = result.telecasts.filter(result.telecasts["game_id"] == 500001).row(0, named=True)
    assert row["duplicate_merges"] == 1
    assert len(row["rr_record_urls"]) == 2
    assert row["rated"] is True


def test_rematch_stays_a_separate_telecast(build_vault: DataPaths, vault_reference: Path) -> None:
    result = _build(build_vault, vault_reference)

    ids = result.telecasts.filter(result.telecasts["game_id"] == 500002)["telecast_id"].to_list()
    assert len(ids) == 1
    row = result.telecasts.filter(result.telecasts["game_id"] == 500002).row(0, named=True)
    assert row["duplicate_merges"] == 0
    assert len(row["rr_record_urls"]) == 1


def test_telecast_id_is_unique_across_the_frame(
    build_vault: DataPaths, vault_reference: Path
) -> None:
    result = _build(build_vault, vault_reference)

    ids = result.telecasts["telecast_id"].to_list()
    assert len(ids) == len(set(ids))


def test_two_builds_from_the_same_sources_are_equal(
    build_vault: DataPaths, vault_reference: Path
) -> None:
    sources, games_frame, resolver, index, overrides, networks, primary_overrides, media_by_game = (
        _wire(build_vault, vault_reference)
    )

    build_a = build_telecasts(
        sources, games_frame, resolver, index, overrides, networks, primary_overrides, media_by_game
    )
    build_b = build_telecasts(
        sources, games_frame, resolver, index, overrides, networks, primary_overrides, media_by_game
    )

    assert build_a.telecasts.equals(build_b.telecasts)
    assert build_a.listing_links.equals(build_b.listing_links)


def test_telecasts_frame_has_exactly_the_schema_columns_and_dtypes(
    build_vault: DataPaths, vault_reference: Path
) -> None:
    result = _build(build_vault, vault_reference)

    assert result.telecasts.columns == list(TELECASTS_SCHEMA.keys())
    for column, dtype in TELECASTS_SCHEMA.items():
        assert result.telecasts.schema[column] == dtype


def test_no_fill_null_in_telecasts_module() -> None:
    text = Path("src/booth_review/build/telecasts.py").read_text(encoding="utf-8")
    assert "fill_null" not in text


# -- Hand-built scenarios: primary network, overrides, attachment, outlets -------------------


def _game(**overrides: object) -> CfbdGame:
    defaults: dict[str, object] = {
        "id": 1,
        "season": 2099,
        "week": 5,
        "season_type": "regular",
        "start_date": datetime(2099, 10, 4, 16, 0, tzinfo=UTC),
        "start_time_tbd": False,
        "completed": True,
        "neutral_site": False,
        "conference_game": True,
        "venue": "Test Field",
        "home_id": 1,
        "home_team": "Home Team",
        "home_classification": "fbs",
        "home_conference": "Test Conference",
        "home_points": 20,
        "away_id": 2,
        "away_team": "Away Team",
        "away_classification": "fbs",
        "away_conference": "Test Conference",
        "away_points": 17,
        "excitement_index": None,
        "notes": None,
    }
    defaults.update(overrides)
    return CfbdGame(**defaults)  # type: ignore[arg-type]


def _listing(**overrides: object) -> Listing506:
    defaults: dict[str, object] = {
        "season": 2099,
        "week_label": "5",
        "source_row_index": 0,
        "date_et": to_et_date(datetime(2099, 10, 4, 16, 0, tzinfo=UTC)),
        "kickoff_et": None,
        "away_raw": "Away Team",
        "away_rank": None,
        "home_raw": "Home Team",
        "home_rank": None,
        "neutral": False,
        "network_raw": None,
        "crew_raw": None,
        "crew_names": (),
        "feed_kind": "main",
        "game_label": None,
    }
    defaults.update(overrides)
    return Listing506(**defaults)  # type: ignore[arg-type]


def _rr_record(
    *,
    record_id: str = "cfb-away-home-2099-10-04",
    event_date: date = date(2099, 10, 4),
    networks: list[str] | None = None,
    teams: list[str] | None = None,
    composite_of: list[str] | None = None,
) -> RRRecord:
    telecast = RRTelecast(
        id=record_id,
        event_date=event_date,
        networks=networks if networks is not None else ["Net Alpha"],
        teams=teams if teams is not None else ["cfb-away", "cfb-home"],
        kind="game",
        tier=2,
    )
    claim = RRClaim(
        metric_type="avg_audience",
        status="final",
        value=1_000_000,
        unit="viewers",
        publisher="Example Sports PR",
        source_url="https://example.org/press/1",
        first_published="2099-10-06",
        confidence=1.0,
        composite_of=composite_of,
    )
    return RRRecord(telecast=telecast, claims=[claim])


def _network_table(rows: list[NetworkRow]) -> NetworkTable:
    return NetworkTable(rows)


def _network_row(
    variant: str, network_id: str, *, tier: str = "cable", feed_type: str = "main"
) -> NetworkRow:
    return NetworkRow(
        variant=variant,
        network_id=network_id,
        display_name=network_id,
        family=network_id,
        tier=tier,  # type: ignore[arg-type]
        feed_type=feed_type,  # type: ignore[arg-type]
        season_from=None,
        season_to=None,
        priority=None,
    )


def _resolver(games: list[CfbdGame]) -> TeamResolver:
    return TeamResolver({2099: games}, [])


def _index(games: list[CfbdGame]) -> GameIndex:
    return GameIndex(games)


def _run(
    *,
    games: list[CfbdGame],
    records: list[RRRecord],
    listings: list[Listing506],
    network_rows: list[NetworkRow],
    overrides: dict[tuple[str, int, str], GameOverride] | None = None,
    primary_overrides: dict[int, str] | None = None,
    media_by_game: dict[int, list[str]] | None = None,
) -> TelecastBuild:
    sources = [
        SeasonSources(
            season=2099,
            games=games,
            listings=listings,
            rr_records=records,
            rr_parse_errors=0,
            media=[],
            lines=[],
            rankings=[],
            wp_pregame=[],
        )
    ]
    games_frame = pl.DataFrame({"game_id": [g.id for g in games]}, schema={"game_id": pl.Int64()})

    return build_telecasts(
        sources,
        games_frame,
        _resolver(games),
        _index(games),
        overrides or {},
        _network_table(network_rows),
        primary_overrides or {},
        media_by_game or {},
    )


def test_primary_network_comes_from_rr_record_when_it_maps() -> None:
    game = _game()
    record = _rr_record(networks=["Net Alpha"])
    listing = _listing(network_raw="Net Bravo")
    rows = [_network_row("Net Alpha", "alpha"), _network_row("Net Bravo", "bravo")]

    result = _run(games=[game], records=[record], listings=[listing], network_rows=rows)

    telecast = result.telecasts.row(0, named=True)
    assert telecast["network_id"] == "alpha"


def test_primary_network_falls_back_to_first_main_listing_when_rr_unmapped() -> None:
    game = _game()
    record = _rr_record(networks=["Unmapped Network"])
    listing = _listing(network_raw="Net Bravo")
    rows = [_network_row("Net Bravo", "bravo")]

    result = _run(games=[game], records=[record], listings=[listing], network_rows=rows)

    # The RR record's own primary is unmapped (network_id None), so its
    # group key is (None, "main") -- a separate telecast from the listing's
    # own unrated fallback telecast (bravo). Both are produced; the RR one
    # carries the record, the listing one is unrated.
    ids = result.telecasts["network_id"].to_list()
    assert "bravo" in ids


def test_per_game_primary_override_wins_for_main_feed() -> None:
    game = _game(id=42)
    record = _rr_record(networks=["Net Alpha"])
    rows = [_network_row("Net Alpha", "alpha"), _network_row("Net Override", "override-net")]

    result = _run(
        games=[game],
        records=[record],
        listings=[],
        network_rows=rows,
        primary_overrides={42: "override-net"},
    )

    telecast = result.telecasts.row(0, named=True)
    assert telecast["network_id"] == "override-net"
    assert telecast["telecast_id"] == "42-override-net"


def test_alt_feed_record_produces_an_alt_feed_type_telecast() -> None:
    game = _game()
    record = _rr_record(networks=["Net Alpha (alt-cast)"])
    rows = [_network_row("Net Alpha", "alpha")]

    result = _run(games=[game], records=[record], listings=[], network_rows=rows)

    telecast = result.telecasts.row(0, named=True)
    assert telecast["feed_type"] == "alt"
    assert telecast["network_id"] == "alpha"


def test_spanish_feed_record_produces_a_spanish_feed_type_telecast() -> None:
    game = _game()
    record = _rr_record(networks=["Net Alpha (spanish)"])
    rows = [_network_row("Net Alpha", "alpha")]

    result = _run(games=[game], records=[record], listings=[], network_rows=rows)

    telecast = result.telecasts.row(0, named=True)
    assert telecast["feed_type"] == "spanish"


def test_matching_main_listing_attaches_without_mismatch() -> None:
    game = _game()
    record = _rr_record(networks=["Net Alpha"])
    listing = _listing(network_raw="Net Alpha", crew_names=("Pat Example", "Jordan Sample"))
    rows = [_network_row("Net Alpha", "alpha")]

    result = _run(games=[game], records=[record], listings=[listing], network_rows=rows)

    telecast = result.telecasts.row(0, named=True)
    assert telecast["crew_matched"] is True
    assert telecast["crew_network_mismatch"] is False
    assert telecast["s506_pointer"] is not None


def test_single_leftover_listing_attaches_with_crew_network_mismatch() -> None:
    game = _game()
    record = _rr_record(networks=["Net Alpha"])
    listing = _listing(network_raw="Net Bravo", crew_names=("Pat Example", "Jordan Sample"))
    rows = [_network_row("Net Alpha", "alpha"), _network_row("Net Bravo", "bravo")]

    result = _run(games=[game], records=[record], listings=[listing], network_rows=rows)

    telecast = result.telecasts.filter(result.telecasts["network_id"] == "alpha").row(0, named=True)
    assert telecast["crew_matched"] is True
    assert telecast["crew_network_mismatch"] is True


def test_crew_matched_false_when_only_crew_name_is_a_placeholder() -> None:
    game = _game()
    record = _rr_record(networks=["Net Alpha"])
    listing = _listing(network_raw="Net Alpha", crew_names=("TBA",))
    rows = [_network_row("Net Alpha", "alpha")]

    result = _run(games=[game], records=[record], listings=[listing], network_rows=rows)

    telecast = result.telecasts.row(0, named=True)
    assert telecast["crew_matched"] is False


def test_unattached_main_listing_becomes_its_own_unrated_telecast() -> None:
    game = _game()
    listing = _listing(network_raw="Net Bravo", crew_names=("Pat Example",))
    rows = [_network_row("Net Bravo", "bravo")]

    result = _run(games=[game], records=[], listings=[listing], network_rows=rows)

    assert result.telecasts.height == 1
    telecast = result.telecasts.row(0, named=True)
    assert telecast["rated"] is False
    assert telecast["network_id"] == "bravo"
    assert telecast["crew_matched"] is True


def test_outlets_union_is_deduped_with_primary_first() -> None:
    game = _game(id=7)
    record = _rr_record(networks=["Net Alpha"])
    listing = _listing(network_raw="Net Alpha, Net Bravo", crew_names=("Pat Example",))
    rows = [
        _network_row("Net Alpha", "alpha"),
        _network_row("Net Bravo", "bravo"),
        _network_row("Net Charlie", "charlie"),
    ]

    result = _run(
        games=[game],
        records=[record],
        listings=[listing],
        network_rows=rows,
        media_by_game={7: ["Net Charlie", "Net Alpha"]},
    )

    telecast = result.telecasts.row(0, named=True)
    assert telecast["outlets"] == ["alpha", "bravo", "charlie"]


def test_listing_links_has_one_row_per_matched_listing_with_feed_kind() -> None:
    game = _game()
    record = _rr_record(networks=["Net Alpha"])
    main_listing = _listing(network_raw="Net Alpha", crew_names=("Pat Example",), feed_kind="main")
    alt_listing = _listing(
        network_raw="Net Alpha",
        crew_names=("Robin Post",),
        feed_kind="alt",
        source_row_index=1,
    )
    rows = [_network_row("Net Alpha", "alpha", feed_type="main")]

    result = _run(
        games=[game], records=[record], listings=[main_listing, alt_listing], network_rows=rows
    )

    assert result.listing_links.height == 2
    feed_kinds = set(result.listing_links["feed_kind"].to_list())
    assert feed_kinds == {"main", "alt"}
    assert result.listing_links["telecast_id"].null_count() == 0


def test_combined_feeds_reflects_composite_of_claim() -> None:
    game = _game()
    record = _rr_record(networks=["Net Alpha"], composite_of=["cfb-a", "cfb-b"])
    rows = [_network_row("Net Alpha", "alpha")]

    result = _run(games=[game], records=[record], listings=[], network_rows=rows)

    telecast = result.telecasts.row(0, named=True)
    assert telecast["combined_feeds"] == 2


def test_headline_columns_start_null_for_task_2_to_fill() -> None:
    game = _game()
    record = _rr_record(networks=["Net Alpha"])
    rows = [_network_row("Net Alpha", "alpha")]

    result = _run(games=[game], records=[record], listings=[], network_rows=rows)

    telecast = result.telecasts.row(0, named=True)
    assert telecast["headline_claim_id"] is None
    assert telecast["plotted"] is False
    assert telecast["era_id"] is None
    assert telecast["model_break"] is None


def test_excluded_record_is_counted_and_produces_no_telecast() -> None:
    game = _game(id=10)
    record = _rr_record(record_id="cfb-away-home-2099-10-04")
    override_key = ("ratingsref", 2099, "cfb-away-home-2099-10-04")
    override = GameOverride(
        source="ratingsref",
        season=2099,
        pointer="cfb-away-home-2099-10-04",
        action="exclude",
        cfbd_game_id=None,
        reason="not-a-game",
    )

    result = _run(
        games=[game],
        records=[record],
        listings=[],
        network_rows=[],
        overrides={override_key: override},
    )

    assert result.telecasts.height == 0
    assert result.counts[2099]["rr_excluded"] == 1


def test_out_of_scope_record_is_counted_and_produces_no_telecast() -> None:
    game = _game(id=11)
    record = _rr_record()

    sources = [
        SeasonSources(
            season=2099,
            games=[game],
            listings=[],
            rr_records=[record],
            rr_parse_errors=0,
            media=[],
            lines=[],
            rankings=[],
            wp_pregame=[],
        )
    ]

    empty_frame = pl.DataFrame({"game_id": []}, schema={"game_id": pl.Int64()})

    result = build_telecasts(
        sources,
        empty_frame,
        _resolver([game]),
        _index([game]),
        {},
        _network_table([]),
        {},
        {},
    )

    assert result.telecasts.height == 0
    assert result.counts[2099]["rr_out_of_scope"] == 1


def test_unmatched_record_is_counted_and_written_to_review() -> None:
    game = _game(id=12, home_team="Somewhere Else", away_team="Another Place")
    record = _rr_record(teams=["cfb-away", "cfb-home"])

    result = _run(games=[game], records=[record], listings=[], network_rows=[])

    assert result.counts[2099]["rr_unmatched"] == 1
    assert any(row.source == "ratingsref" for row in result.unmatched_rows)
