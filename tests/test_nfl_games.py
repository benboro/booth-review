"""NFL per-game frame on synthetic inputs: schedule fields, network, crew, labels."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest
from nfl_game_helpers import (
    NOW,
    game_row,
    listing_for,
    make_inputs,
    make_ref,
    rr_record,
)

from booth_review.nfl.games import NFL_GAME_COLUMNS, NFL_GAME_SCHEMA, assemble_nfl_games
from booth_review.nfl.winprob import PBP_COLUMNS


def build(tmp_path: Path, rows, *, include_playoffs: bool = False, now=NOW, **kw):
    ref_kw = {k: kw.pop(k) for k in ("stadiums", "overrides") if k in kw}
    ref = make_ref(tmp_path, **ref_kw)
    return assemble_nfl_games(
        make_inputs(rows, **kw), ref, include_playoffs=include_playoffs, now=now
    )


def one(table, game_id: str) -> dict[str, object]:
    return table.frame.filter(pl.col("game_id") == game_id).row(0, named=True)


def test_columns_order_and_dtypes(tmp_path: Path) -> None:
    table = build(tmp_path, [game_row("a", 1, 2, "2015-09-13")])
    assert table.frame.columns == list(NFL_GAME_COLUMNS)
    assert dict(table.frame.schema) == dict(NFL_GAME_SCHEMA)
    for key in ("teams", "stadiums", "networks", "listings", "rr", "changes", "crew_names"):
        assert key in table.reviews
    assert "late_national" in table.reviews
    assert "acceptance" in table.reviews
    assert "people" not in table.reviews  # review_nfl_people.csv belongs to `nfl people`
    assert table.counts["games"] == 1


def test_empty_input_keeps_schema(tmp_path: Path) -> None:
    table = build(tmp_path, [])
    assert table.frame.height == 0
    assert table.frame.columns == list(NFL_GAME_COLUMNS)


def test_schedule_fields_and_margin(tmp_path: Path) -> None:
    row = game_row(
        "a",
        1,
        2,
        "2015-09-13",
        "20:20",
        weekday="Sunday",
        home_score="24",
        away_score="17",
        spread_line="-3.5",
    )
    table = build(tmp_path, [row])
    got = one(table, "a")
    assert got["kickoff_time_et"] == "20:20"
    assert got["game_date"].isoformat() == "2015-09-13"
    assert got["final_margin"] == 7
    assert got["pregame_spread"] == -3.5
    assert got["home_franchise_id"] == "team-02"
    assert got["away_display_name"] == "Display 01"
    assert got["kickoff_utc"] == datetime(2015, 9, 14, 0, 20, tzinfo=UTC)
    assert got["alt_cast_broadcasts"] == []


def test_unplayed_scores_stay_null(tmp_path: Path) -> None:
    got = one(build(tmp_path, [game_row("a", 1, 2, "2015-09-13")]), "a")
    assert got["final_margin"] is None
    assert got["pregame_spread"] is None


def test_unmapped_team_is_null_with_review(tmp_path: Path) -> None:
    row = game_row("a", 1, 2, "2015-09-13")
    row["away_team"] = "ZZZ"
    table = build(tmp_path, [row])
    got = one(table, "a")
    assert got["away_franchise_id"] is None
    assert got["home_franchise_id"] == "team-02"
    assert table.counts["unresolved_teams"] == 1
    assert table.reviews["teams"][0]["reason"] == "unresolved-team"


def test_international_from_stadium_table(tmp_path: Path) -> None:
    rows = [
        game_row("a", 1, 2, "2015-10-25", "09:30", stadium_id="FAKE01"),
        game_row("b", 3, 4, "2015-10-25", "13:00"),
    ]
    table = build(tmp_path, rows)
    assert one(table, "a")["is_international"] is True
    assert one(table, "a")["slot_name"] == "International"
    assert one(table, "b")["is_international"] is False


def test_unknown_neutral_stadium_is_null_with_review(tmp_path: Path) -> None:
    rows = [game_row("a", 1, 2, "2015-10-25", "13:00", stadium_id="NEW99", location="Neutral")]
    table = build(tmp_path, rows)
    assert one(table, "a")["is_international"] is None
    assert table.counts["unknown_stadiums"] == 1
    assert table.reviews["stadiums"][0]["reason"] == "unknown-stadium"


def test_intl_city_without_stadium_row_is_unknown(tmp_path: Path) -> None:
    rows = [game_row("a", 1, 2, "2015-10-25", "13:00", stadium_id="NEW98")]
    table = build(tmp_path, rows, listings=[listing_for(1, 2, week=1, intl_city="Somewhere")])
    assert one(table, "a")["is_international"] is None


def test_stadium_override_beats_the_home_teams_own_stadium_id(tmp_path: Path) -> None:
    # nflverse files some overseas games under the home team's US stadium id (HOME1).
    rows = [
        game_row("a", 1, 2, "2015-10-25", "09:30", stadium_id="HOME1", location="Neutral"),
        game_row("b", 3, 2, "2015-11-01", "13:00", stadium_id="HOME1"),
    ]
    ref = replace(
        make_ref(tmp_path, stadiums={"FAKE01": "GB", "HOME1": "US"}),
        stadium_overrides={"a": "FAKE01"},
    )
    table = assemble_nfl_games(make_inputs(rows), ref, include_playoffs=False, now=NOW)
    assert one(table, "a")["stadium_id"] == "FAKE01"
    assert one(table, "a")["is_international"] is True
    assert one(table, "a")["slot_name"] == "International"
    assert one(table, "b")["stadium_id"] == "HOME1"
    assert one(table, "b")["is_international"] is False
    assert table.counts["unknown_stadiums"] == 0


def test_network_from_506_with_crew(tmp_path: Path) -> None:
    rows = [game_row("a", 1, 2, "2015-09-13")]
    lst = listing_for(1, 2, "CBS", crew=["Ana Fixture", "Bo Fixture", "Nobody Known"])
    table = build(tmp_path, rows, listings=[lst])
    got = one(table, "a")
    assert (got["network_id"], got["network_source"]) == ("cbs", "506")
    assert got["crew_names"] == ["Ana Fixture", "Bo Fixture", "Nobody Known"]
    assert got["pbp_person_id"] == "ana-fixture"
    assert got["analyst_person_id"] == "bo-fixture"
    assert got["sideline_person_ids"] == []
    assert table.counts["unresolved_crew_names"] == 1
    assert table.reviews["crew_names"][0]["reason"] == "unresolved-crew-name"
    assert "Nobody" not in str(table.reviews["crew_names"])


def test_rr_supplies_standalone_network(tmp_path: Path) -> None:
    rows = [game_row("a", 1, 2, "2015-09-20", "20:30")]
    rec = rr_record("nfl-team-01-team-02-2015-09-20", "2015-09-20", 1, 2, ["NBC"])
    got = one(build(tmp_path, rows, rr=[rec]), "a")
    assert (got["network_id"], got["network_source"]) == ("nbc", "rr")
    assert got["rr_network_ids"] == ["nbc"]
    assert got["rr_network_id"] == "nbc"


def test_rr_alone_never_trusted_for_sunday_afternoon(tmp_path: Path) -> None:
    rows = [game_row("a", 1, 2, "2015-09-20", "13:00"), game_row("b", 3, 4, "2015-09-20", "13:00")]
    rec = rr_record("nfl-team-01-team-02-2015-09-20", "2015-09-20", 1, 2, ["CBS"])
    table = build(tmp_path, rows, rr=[rec])
    got = one(table, "a")
    assert got["network_id"] is None
    assert got["rr_network_ids"] == ["cbs"]
    assert table.counts["rr_regional_only"] == 1
    assert table.reviews["networks"][0]["reason"] == "rr-regional-only"


def test_network_disagreement_keeps_506(tmp_path: Path) -> None:
    rows = [game_row("a", 1, 2, "2015-09-20", "20:30")]
    rec = rr_record("nfl-team-01-team-02-2015-09-20", "2015-09-20", 1, 2, ["NBC"])
    table = build(tmp_path, rows, rr=[rec], listings=[listing_for(1, 2, "CBS")])
    got = one(table, "a")
    assert (got["network_id"], got["network_source"]) == ("cbs", "506")
    assert table.counts["network_disagree"] == 1
    assert table.reviews["networks"][0]["reason"] == "network-disagree"


def test_2014_tnf_simulcast_keeps_both_networks(tmp_path: Path) -> None:
    rows = [game_row("a", 1, 2, "2014-10-02", "20:25", season=2014, weekday="Thursday", week=5)]
    rec = rr_record("nfl-team-01-team-02-2014-10-02", "2014-10-02", 1, 2, ["CBS", "NFL Network"])
    table = build(tmp_path, rows, rr=[rec], rr_season=2014)
    got = one(table, "a")
    assert got["rr_network_ids"] == ["cbs", "nfln"]
    assert got["rr_network_id"] is None
    assert got["network_id"] is None
    assert got["network_source"] == "rr-multi"
    assert table.counts["rr_multi_network_games"] == 1
    assert [r["reason"] for r in table.reviews["networks"]] == ["rr-multi-network"]


def test_2015_mnf_espn_abc_simulcast(tmp_path: Path) -> None:
    rows = [game_row("a", 1, 2, "2015-10-12", "20:30", weekday="Monday", week=5)]
    rec = rr_record("nfl-team-01-team-02-2015-10-12", "2015-10-12", 1, 2, ["ESPN", "ABC"])
    table = build(tmp_path, rows, rr=[rec])
    got = one(table, "a")
    assert got["rr_network_ids"] == ["abc", "espn"]
    assert got["rr_network_id"] is None
    assert got["network_source"] == "rr-multi"
    assert got["may_combine_feeds"] is True
    assert table.counts["rr_multi_network_games"] == 1


def test_single_network_sunday_night_2014(tmp_path: Path) -> None:
    rows = [game_row("a", 1, 2, "2014-10-05", "20:30", season=2014, week=5)]
    rec = rr_record("nfl-team-01-team-02-2014-10-05", "2014-10-05", 1, 2, ["NBC"])
    got = one(build(tmp_path, rows, rr=[rec], rr_season=2014), "a")
    assert got["rr_network_ids"] == ["nbc"]
    assert got["rr_network_id"] == "nbc"
    assert got["network_id"] == "nbc"
    assert got["network_source"] == "rr"


def test_no_rr_gives_empty_network_set(tmp_path: Path) -> None:
    got = one(build(tmp_path, [game_row("a", 1, 2, "2015-09-13")]), "a")
    assert got["rr_network_ids"] == []
    assert got["rr_network_id"] is None
    assert got["network_source"] is None


def test_playoffs_toggle_and_standalone_sees_playoffs(tmp_path: Path) -> None:
    rows = [
        game_row("reg", 1, 2, "2016-01-03", "20:20", season=2015, week=17),
        game_row("wc", 3, 4, "2016-01-03", "22:00", season=2015, week=18, game_type="WC"),
    ]
    off = build(tmp_path, rows, include_playoffs=False)
    assert off.frame["game_id"].to_list() == ["reg"]
    assert one(off, "reg")["is_standalone"] is False
    on = build(tmp_path, rows, include_playoffs=True)
    assert sorted(on.frame["game_id"].to_list()) == ["reg", "wc"]
    assert one(on, "wc")["game_type"] == "WC"


def test_current_season_only_includes_played_games(tmp_path: Path) -> None:
    rows = [
        game_row("w1", 1, 2, "2026-09-13", "13:00", season=2026, week=1),
        game_row("w2", 3, 4, "2026-09-20", "13:00", season=2026, week=2),
    ]
    now = datetime(2026, 9, 20, 16, 0, tzinfo=UTC)  # w2 kickoff 17:00 UTC
    table = build(tmp_path, rows, now=now)
    assert table.frame["game_id"].to_list() == ["w1"]
    assert table.through_week == {2026: 1}
    later = build(tmp_path, rows, now=datetime(2026, 9, 20, 23, 0, tzinfo=UTC))
    assert later.through_week == {2026: 2}
    assert sorted(later.frame["game_id"].to_list()) == ["w1", "w2"]


def test_through_week_none_before_first_week_finishes(tmp_path: Path) -> None:
    rows = [game_row("w1", 1, 2, "2026-09-13", "13:00", season=2026, week=1)]
    table = build(tmp_path, rows, now=datetime(2026, 8, 1, tzinfo=UTC))
    assert table.frame.height == 0
    assert table.through_week == {2026: None}


def test_naive_now_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        build(tmp_path, [], now=datetime(2030, 1, 1))  # noqa: DTZ001


def test_missing_pbp_season_counted_with_null_metrics(tmp_path: Path) -> None:
    table = build(tmp_path, [game_row("a", 1, 2, "2015-09-13")])
    got = one(table, "a")
    assert got["excitement_score"] is None
    assert got["wp_volatility"] is None
    assert got["wp_plays"] is None
    assert table.counts["pbp_missing_seasons"] == 1


def test_pbp_metrics_joined_by_game_id(tmp_path: Path) -> None:
    plays = []
    for i in range(30):
        plays.append(
            {
                "game_id": "a",
                "play_id": float(i + 1),
                "qtr": 4 if i == 29 else 1,
                "quarter_seconds_remaining": 0.0 if i == 29 else 600.0,
                "game_seconds_remaining": float(3600 - i * 100),
                "home_wp": 0.5 + (0.01 * i if i % 2 else -0.01 * i),
                "home_wp_post": 0.9,
            }
        )
    path = tmp_path / "pbp.parquet"
    pl.DataFrame(plays).select(PBP_COLUMNS).write_parquet(path)
    table = build(tmp_path, [game_row("a", 1, 2, "2015-09-13")], pbp={2015: path})
    got = one(table, "a")
    assert got["wp_plays"] == 30
    assert got["excitement_score"] is not None
    assert got["wp_volatility"] is not None
    assert table.counts["pbp_missing_seasons"] == 0


def test_viewership_scope_and_attribution(tmp_path: Path) -> None:
    rows = [
        game_row("a", 1, 2, "2015-09-13", "13:00"),
        game_row("b", 3, 4, "2015-09-14", "20:30", weekday="Monday"),
    ]
    recs = [
        rr_record("nfl-team-01-team-02-2015-09-13", "2015-09-13", 1, 2, ["CBS"]),
        rr_record("nfl-team-03-team-04-2015-09-14", "2015-09-14", 3, 4, ["ESPN"]),
    ]
    table = build(tmp_path, rows, rr=recs)
    a, b = one(table, "a"), one(table, "b")
    assert a["viewership_scope"] == "window"
    assert b["viewership_scope"] == "game"
    assert a["viewership"] == 5_000_000
    assert a["rr_record_url"].endswith("nfl-team-01-team-02-2015-09-13")
    assert a["rr_source_url"] == "https://example.com/figure"
    assert a["era_id"] is not None
    assert b["may_combine_feeds"] is True
    assert a["may_combine_feeds"] is False


def test_unmatched_viewership_stays_null_but_scope_set(tmp_path: Path) -> None:
    got = one(build(tmp_path, [game_row("a", 1, 2, "2015-09-13", "13:00")]), "a")
    assert got["viewership"] is None
    assert got["viewership_scope"] == "window"
    assert got["rr_record_url"] is None


def test_monday_doubleheader_both_combine(tmp_path: Path) -> None:
    rows = [
        game_row("a", 1, 2, "2015-10-12", "19:15", weekday="Monday", week=5),
        game_row("b", 3, 4, "2015-10-12", "20:15", weekday="Monday", week=5),
    ]
    table = build(tmp_path, rows)
    assert one(table, "a")["may_combine_feeds"] is True
    assert one(table, "b")["may_combine_feeds"] is True
    assert one(table, "a")["is_standalone"] is False
    assert one(table, "a")["slot_name"] == "MNF"


def test_multiple_rr_records_review(tmp_path: Path) -> None:
    rows = [game_row("a", 1, 2, "2015-09-20", "20:30")]
    recs = [
        rr_record("nfl-team-01-team-02-2015-09-20", "2015-09-20", 1, 2, ["NBC"], value=1.0),
        rr_record(
            "nfl-sunday-night-team-01-team-02-2015-09-20", "2015-09-20", 1, 2, ["NBC"], value=2.0
        ),
    ]
    table = build(tmp_path, rows, rr=recs)
    assert [r["reason"] for r in table.reviews["rr"]] == ["multiple-records"]
    got = one(table, "a")
    assert got["rr_telecast_id"] == "nfl-sunday-night-team-01-team-02-2015-09-20"
