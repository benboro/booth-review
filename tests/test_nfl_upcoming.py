"""Upcoming NFL games: unscheduled rows kept, current week, network basis, 506 crews."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from nfl_game_helpers import game_row, listing_for, make_inputs, make_ref
from nfl_join_helpers import schedule_csv

from booth_review.errors import ReferenceTableError
from booth_review.nfl.inputs import NflInputs
from booth_review.nfl.reference import NflBoothRank
from booth_review.nfl.schedule import ET, UpcomingNflGame, parse_schedules, parse_upcoming
from booth_review.nfl.upcoming import assemble_upcoming, current_nfl_week, load_slot_networks
from booth_review.sources.wikipedia.parser import ChangesResult, ScheduleChange

SLOT_CSV = (
    "season,slot,network_id,source_url\n"
    "2026,TNF,prime,https://en.wikipedia.org/wiki/2026_NFL_season\n"
    "2026,SNF,nbc,https://en.wikipedia.org/wiki/2026_NFL_season\n"
    "2026,MNF,espn,https://en.wikipedia.org/wiki/2026_NFL_season\n"
)
EARLY = datetime(2026, 8, 1, tzinfo=UTC)


def _row(gid: str, away: int, home: int, day: str, time: str, weekday: str, week: int = 8, **o):
    return game_row(gid, away, home, day, time, season=2026, week=week, weekday=weekday, **o)


def _build(tmp_path: Path, rows, *, now=EARLY, slot_csv: str | None = SLOT_CSV, **kw):
    inputs = make_inputs(rows, **{k: v for k, v in kw.items() if k == "listings"})
    ups, unplaced = parse_upcoming(schedule_csv(rows), seasons=[2026])
    inputs = replace(inputs, upcoming=tuple(ups), upcoming_unplaced=unplaced)
    if "changes" in kw:
        inputs = replace(inputs, changes=kw["changes"])
    ref = make_ref(
        tmp_path, stadiums={"S1": "US", "FAKE01": "GB"}, booth_ranks=kw.get("booth_ranks")
    )
    if slot_csv is not None:
        (tmp_path / "ref" / "nfl_slot_networks.csv").write_text(slot_csv)
    return assemble_upcoming(inputs, ref, now=now, reference_directory=tmp_path / "ref")


def _by_id(frame):
    return {r["game_id"]: r for r in frame.iter_rows(named=True)}


# -- parse_upcoming -----------------------------------------------------------------


def test_parse_upcoming_keeps_tbd_kickoff() -> None:
    rows = [_row("a", 1, 2, "2026-11-01", "TBD", "Sunday")]
    games, unplaced = parse_upcoming(schedule_csv(rows))
    assert unplaced == 0
    assert games[0].kickoff_et is None
    assert games[0].gameday is not None


def test_parse_upcoming_keeps_unset_day_and_time() -> None:
    rows = [_row("a", 1, 2, "NA", "NA", "Sunday")]
    games, _ = parse_upcoming(schedule_csv(rows))
    assert games[0].gameday is None
    assert games[0].kickoff_et is None


def test_parse_upcoming_counts_unplaced_week() -> None:
    rows = [_row("a", 1, 2, "2026-11-01", "13:00", "Sunday", week=1, **{})]
    rows.append({**_row("b", 3, 4, "NA", "NA", "Sunday"), "week": "NA"})
    games, unplaced = parse_upcoming(schedule_csv(rows))
    assert [g.game_id for g in games] == ["a"]
    assert unplaced == 1


def test_parse_schedules_unchanged_for_same_csv() -> None:
    rows = [
        _row("a", 1, 2, "2026-11-01", "13:00", "Sunday"),
        _row("b", 3, 4, "2026-11-01", "TBD", "Sunday"),
    ]
    assert [g.game_id for g in parse_schedules(schedule_csv(rows))] == ["a"]


def test_parse_upcoming_malformed_date_names_column_not_value() -> None:
    from booth_review.errors import ParseError

    with pytest.raises(ParseError) as err:
        parse_upcoming(schedule_csv([_row("a", 1, 2, "not-a-day", "13:00", "Sunday")]))
    assert "not-a-day" not in str(err.value)


# -- current week -------------------------------------------------------------------


def _wk(week: int, day: str, time: str = "13:00") -> UpcomingNflGame:
    kickoff = datetime.fromisoformat(f"{day}T{time}").replace(tzinfo=ET)
    return UpcomingNflGame(
        f"g{week}{day}", 2026, "REG", week, kickoff.date(), kickoff, "A", "B", "", ""
    )


def test_current_week_switches_after_mnf_plus_four_hours() -> None:
    games = [_wk(w, f"2026-09-{7 * w:02d}") for w in range(1, 4)]
    games.append(_wk(4, "2026-09-28", "20:15"))
    games.append(_wk(5, "2026-10-05"))
    mnf_end = games[3].kickoff_et + timedelta(hours=4)  # type: ignore[operator]
    assert current_nfl_week(games, mnf_end - timedelta(minutes=1)) == 4
    assert current_nfl_week(games, mnf_end) == 5


def test_current_week_capped_and_none() -> None:
    games = [_wk(1, "2026-09-13"), _wk(2, "2026-09-20")]
    assert current_nfl_week(games, datetime(2027, 1, 1, tzinfo=UTC)) == 2
    assert current_nfl_week([], EARLY) is None


def test_unscheduled_game_keeps_its_week_open() -> None:
    tbd = UpcomingNflGame("t", 2026, "REG", 3, None, None, "A", "B", "", "")
    assert current_nfl_week([_wk(3, "2026-09-27"), tbd], datetime(2027, 1, 1, tzinfo=UTC)) == 3


# -- assembly -----------------------------------------------------------------------


def test_only_unplayed_games_up_to_current_week(tmp_path: Path) -> None:
    rows = [
        _row("played", 1, 2, "2026-10-18", "13:00", "Sunday", week=7),
        _row("open", 3, 4, "2026-10-25", "13:00", "Sunday", week=8),
        _row("later", 5, 6, "2026-11-01", "13:00", "Sunday", week=9),
    ]
    now = datetime(2026, 10, 25, 12, tzinfo=ET)
    frame, counts = _build(tmp_path, rows, now=now)
    assert frame["game_id"].to_list() == ["open"]
    assert counts["upcoming_games"] == 1


def test_tbd_kickoff_is_kept_without_network(tmp_path: Path) -> None:
    rows = [_row("a", 1, 2, "2026-10-25", "TBD", "Sunday")]
    frame, counts = _build(tmp_path, rows)
    row = frame.row(0, named=True)
    assert row["kickoff_utc"] is None and row["network_id"] is None
    assert row["slot_name"] is None
    assert counts["upcoming_network_tba"] == 1


def test_unplaced_rows_are_counted(tmp_path: Path) -> None:
    rows = [_row("a", 1, 2, "2026-10-25", "13:00", "Sunday")]
    rows.append({**_row("b", 3, 4, "NA", "NA", "Sunday"), "week": "NA"})
    _, counts = _build(tmp_path, rows)
    assert counts["upcoming_unplaced"] == 1


@pytest.mark.parametrize(
    ("day", "time", "weekday", "network"),
    [
        ("2026-10-22", "20:15", "Thursday", "prime"),
        ("2026-10-25", "20:20", "Sunday", "nbc"),
        ("2026-10-26", "20:15", "Monday", "espn"),
    ],
)
def test_plain_primetime_slot_gets_slot_network(tmp_path, day, time, weekday, network) -> None:
    frame, counts = _build(tmp_path, [_row("a", 1, 2, day, time, weekday)])
    row = frame.row(0, named=True)
    assert (row["network_id"], row["network_basis"]) == (network, "slot")
    assert counts["upcoming_slot_basis"] == 1


@pytest.mark.parametrize(
    ("label", "day", "time", "weekday", "week", "extra"),
    [
        ("sunday-afternoon", "2026-10-25", "13:00", "Sunday", 8, {}),
        ("thanksgiving", "2026-11-26", "20:20", "Thursday", 12, {}),
        ("black-friday", "2026-11-27", "15:00", "Friday", 12, {}),
        ("christmas", "2026-12-25", "20:15", "Friday", 16, {}),
        ("wednesday", "2026-10-21", "20:15", "Wednesday", 8, {}),
        ("saturday", "2026-12-19", "20:15", "Saturday", 15, {}),
        ("week-18", "2027-01-10", "20:20", "Sunday", 18, {}),
        ("week-1-opener", "2026-09-10", "20:20", "Thursday", 1, {}),
        ("international", "2026-10-25", "20:20", "Sunday", 8, {"stadium_id": "FAKE01"}),
        (
            "neutral-unknown-site",
            "2026-10-25",
            "20:20",
            "Sunday",
            8,
            {"location": "Neutral", "stadium_id": "UNK"},
        ),
    ],
)
def test_slot_rule_exclusions(tmp_path, label, day, time, weekday, week, extra) -> None:
    frame, counts = _build(tmp_path, [_row(label, 1, 2, day, time, weekday, week=week, **extra)])
    row = frame.row(0, named=True)
    assert row["network_id"] is None and row["network_basis"] is None, label
    assert counts["upcoming_slot_basis"] == 0


def test_scheduling_change_excludes_slot(tmp_path: Path) -> None:
    change = ScheduleChange(2026, 8, "Team 01", "Team 02", None, None, None, None, None, "h")
    rows = [_row("a", 1, 2, "2026-10-25", "20:20", "Sunday")]
    frame, _ = _build(tmp_path, rows, changes={2026: ChangesResult((change,), (), 0, True)})
    assert frame.row(0, named=True)["network_id"] is None


def test_506_listing_overrides_slot_network_and_gives_crew_rank(tmp_path: Path) -> None:
    rows = [_row("a", 1, 2, "2026-10-26", "20:15", "Monday")]
    lst = listing_for(1, 2, "NBC", season=2026, week=8, crew=("Ana Fixture", "Bo Fixture"))
    ranks = {("nbc", 2026): (NflBoothRank("nbc", 2026, 2, "ana-fixture", "bo-fixture", "u"),)}
    frame, _ = _build(tmp_path, rows, listings=[lst], booth_ranks=ranks)
    row = frame.row(0, named=True)
    assert (row["network_id"], row["network_basis"]) == ("nbc", "506")
    assert row["pbp_person_id"] == "ana-fixture"
    assert row["crew_source"] == "506"
    assert row["crew_source_url"] == "https://506sports.com/nfl.php?yr=2026&wk=8"
    assert row["booth_rank"] == 2


def test_crew_without_published_rank_has_none(tmp_path: Path) -> None:
    rows = [_row("a", 1, 2, "2026-10-25", "13:00", "Sunday")]
    lst = listing_for(1, 2, "FOX", season=2026, week=8, crew=("Ana Fixture",))
    frame, _ = _build(tmp_path, rows, listings=[lst])
    row = frame.row(0, named=True)
    assert row["crew_source"] == "506" and row["booth_rank"] is None


def test_no_crew_no_rank_and_never_a_published_lineup(tmp_path: Path) -> None:
    rows = [_row("a", 1, 2, "2026-10-25", "13:00", "Sunday")]
    ranks = {("fox", 2026): (NflBoothRank("fox", 2026, 1, "ana-fixture", "bo-fixture", "u"),)}
    lst = listing_for(1, 2, "FOX", season=2026, week=8)
    frame, _ = _build(tmp_path, rows, listings=[lst], booth_ranks=ranks)
    row = frame.row(0, named=True)
    assert row["crew_source"] is None and row["pbp_person_id"] is None
    assert row["booth_rank"] is None


def test_missing_slot_season_counts_and_does_not_crash(tmp_path: Path) -> None:
    csv = "season,slot,network_id,source_url\n2025,SNF,nbc,https://example.com/x\n"
    frame, counts = _build(
        tmp_path, [_row("a", 1, 2, "2026-10-25", "20:20", "Sunday")], slot_csv=csv
    )
    assert frame.row(0, named=True)["network_id"] is None
    assert counts["upcoming_slot_table_missing"] == 1


def test_neutral_flag_follows_location(tmp_path: Path) -> None:
    rows = [_row("a", 1, 2, "2026-10-25", "13:00", "Sunday", location="Neutral")]
    frame, _ = _build(tmp_path, rows)
    assert frame.row(0, named=True)["is_neutral"] is True


def test_rows_are_sorted_with_nulls_last(tmp_path: Path) -> None:
    rows = [
        _row("tbd", 1, 2, "2026-10-25", "TBD", "Sunday"),
        _row("late", 3, 4, "2026-10-25", "16:25", "Sunday"),
        _row("early", 5, 6, "2026-10-25", "13:00", "Sunday"),
    ]
    frame, _ = _build(tmp_path, rows)
    assert frame["game_id"].to_list() == ["early", "late", "tbd"]


def test_assemble_rejects_naive_now(tmp_path: Path) -> None:
    inputs = make_inputs([])
    ref = make_ref(tmp_path)
    with pytest.raises(ValueError, match="timezone-aware"):
        assemble_upcoming(
            inputs, ref, now=datetime.fromisoformat("2026-01-01"), reference_directory=tmp_path
        )


# -- slot table loader --------------------------------------------------------------


def test_shipped_slot_table_loads() -> None:
    table = load_slot_networks(Path(__file__).parent.parent / "data" / "reference")
    assert table == {(2026, "TNF"): "prime", (2026, "SNF"): "nbc", (2026, "MNF"): "espn"}


@pytest.mark.parametrize(
    "line", ["2026,XYZ,nbc,https://x", "2026,SNF,nope,https://x", "2026,SNF,nbc,http://x"]
)
def test_slot_table_rejects_bad_rows(tmp_path: Path, line: str) -> None:
    (tmp_path / "nfl_slot_networks.csv").write_text(f"season,slot,network_id,source_url\n{line}\n")
    with pytest.raises(ReferenceTableError):
        load_slot_networks(tmp_path)


def test_missing_slot_file_is_empty(tmp_path: Path) -> None:
    assert load_slot_networks(tmp_path) == {}


def test_inputs_dataclass_defaults() -> None:
    assert NflInputs.__dataclass_fields__["upcoming"].default == ()


# -- weekend stamps -----------------------------------------------------------------


def _entry(path: str, fetched_at: str, sha: str, saved_at: str | None = None):
    from booth_review.transport.cache import ManifestEntry

    return ManifestEntry(
        url=f"https://example.com/{path}",
        source="nfl_nflverse",
        season=2026,
        kind="x",
        fetched_at=fetched_at,
        status=200,
        etag=None,
        last_modified=None,
        sha256=sha,
        path=path,
        bytes=1,
        final_url="",
        saved_at=saved_at,
    )


def test_weekend_frame_stamps_schedule_change_and_506_save(tmp_path: Path) -> None:
    from booth_review.config import DataPaths
    from booth_review.nfl.layout import NFLVERSE_SCHEDULES_PATH, nfl_506_path
    from booth_review.nfl.upcoming import weekend_frame
    from booth_review.transport.cache import Manifest

    paths = DataPaths(tmp_path / "vault")
    manifest = Manifest(paths.manifest)
    manifest.append(_entry(NFLVERSE_SCHEDULES_PATH, "2026-10-01T10:00:00Z", "a"))
    manifest.append(_entry(NFLVERSE_SCHEDULES_PATH, "2026-10-02T10:00:00Z", "a"))  # unchanged
    manifest.append(_entry(NFLVERSE_SCHEDULES_PATH, "2026-10-09T21:30:00Z", "b"))
    manifest.append(
        _entry(nfl_506_path(2026, 8), "2026-10-12T00:00:00Z", "c", "2026-10-06T02:14:00Z")
    )
    rows = [_row("a", 1, 2, "2026-10-25", "13:00", "Sunday")]
    ups, _ = parse_upcoming(schedule_csv(rows), seasons=[2026])
    inputs = replace(make_inputs(rows), upcoming=tuple(ups))
    frame, upcoming_week = weekend_frame(paths, inputs, frame_of(ups), now=EARLY)
    assert upcoming_week == 8
    row = frame.row(0, named=True)
    assert row["week"] == 8
    assert row["schedule_updated_at"] == "2026-10-09T21:30:00Z"
    assert row["crews_506_saved_at"] == "2026-10-06T02:14:00Z"


def frame_of(ups):
    import polars as pl

    from booth_review.nfl.upcoming import UPCOMING_SCHEMA

    return pl.DataFrame({k: [None] * len(ups) for k in UPCOMING_SCHEMA}, schema=UPCOMING_SCHEMA)


def test_weekend_frame_without_page_or_manifest_has_null_stamps(tmp_path: Path) -> None:
    from booth_review.config import DataPaths
    from booth_review.nfl.upcoming import weekend_frame

    rows = [_row("a", 1, 2, "2026-10-25", "13:00", "Sunday")]
    ups, _ = parse_upcoming(schedule_csv(rows), seasons=[2026])
    inputs = replace(make_inputs(rows), upcoming=tuple(ups))
    frame, _ = weekend_frame(DataPaths(tmp_path / "vault"), inputs, frame_of(ups), now=EARLY)
    row = frame.row(0, named=True)
    assert row["schedule_updated_at"] is None and row["crews_506_saved_at"] is None


def test_weekend_frame_is_empty_without_upcoming_games(tmp_path: Path) -> None:
    from booth_review.config import DataPaths
    from booth_review.nfl.upcoming import weekend_frame

    rows = [_row("a", 1, 2, "2026-10-25", "13:00", "Sunday")]
    ups, _ = parse_upcoming(schedule_csv(rows), seasons=[2026])
    inputs = replace(make_inputs(rows), upcoming=tuple(ups))
    frame, week = weekend_frame(DataPaths(tmp_path / "vault"), inputs, frame_of([]), now=EARLY)
    assert frame.height == 0 and week is None


# -- pipeline -----------------------------------------------------------------------


def test_build_writes_upcoming_tables_and_ships_the_block(
    git_vault, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    import shutil

    import polars as pl
    from test_nfl_pipeline import REFERENCE, _seed

    import booth_review.nfl.pipeline as nfl_pipeline

    ref = tmp_path / "nfl_ref"
    shutil.copytree(REFERENCE, ref)
    _seed(git_vault, rr=["NFL Network"])
    outcome = nfl_pipeline.run_nfl_build(
        git_vault,
        ref,
        seasons=[2014],
        include_playoffs=False,
        check_acceptance=False,
        commit=False,
        site_data=True,
        now=datetime(2014, 9, 5, 12, tzinfo=UTC),
    )
    assert outcome.counts["upcoming_games"] == 2
    assert outcome.counts["upcoming_slot_table_missing"] == 1
    assert "processed/nfl_upcoming.parquet" in outcome.written
    assert "processed/nfl_weekend.parquet" in outcome.written
    upcoming = pl.read_parquet(git_vault.processed / "nfl_upcoming.parquet")
    assert upcoming.height == 2
    weekend = pl.read_parquet(git_vault.processed / "nfl_weekend.parquet")
    assert weekend["week"].to_list() == [1]
    site = json.loads((git_vault.processed / "nfl-data.json").read_text())
    assert len(site["upcoming"]["season"]) == 2
    assert site["freshness"]["weekend"]["week"] == 1
