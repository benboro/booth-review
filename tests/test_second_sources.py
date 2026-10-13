"""Tests for build/second_sources.py: matching, network hold, skips, duplicates,
season-top rows, exclusions, the RR agreement gate, adapter claims and the
rated flip. Teams and figures are invented (Silverlake, Northfield, ...)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from smw_helpers import PAGE, build_season

from booth_review.build.second_sources import (
    REVIEW_AGREEMENT,
    REVIEW_CONFLICTS,
    REVIEW_GATE,
    REVIEW_NETWORK,
    REVIEW_UNMATCHED,
    SECOND_SOURCE_REVIEW_NAMES,
    SecondSourceInputs,
    SecondSourceResult,
    apply_second_sources,
    load_gate_overrides,
    load_network_accepts,
    load_second_source_inputs,
)
from booth_review.config import DataPaths
from booth_review.errors import ReferenceTableError
from booth_review.resolve.games import GameIndex
from booth_review.resolve.networks import NetworkRow, NetworkTable
from booth_review.resolve.overrides import GameOverride
from booth_review.resolve.teams import TeamCrosswalkRow, TeamResolver
from booth_review.sources.cfbd.parser import CfbdGame
from booth_review.sources.ratingsref.parser import RRClaim, RRRecord, RRTelecast
from booth_review.sources.second_rows import SecondSourceRow
from booth_review.sources.smw.chart_order import parse_chart_order, write_chart_order_csv

SEASON = 2022
TEAMS = {1: "Silverlake", 2: "Northfield", 3: "Riverbend", 4: "Lakeshore", 5: "Hilltop"}


def _game(game_id: int, home: int, away: int, day: int = 1, **extra: object) -> CfbdGame:
    defaults: dict[str, Any] = {
        "id": game_id,
        "season": SEASON,
        "week": 5,
        "season_type": "regular",
        "start_date": datetime(SEASON, 10, day, 20, 0, tzinfo=UTC),
        "start_time_tbd": False,
        "completed": True,
        "neutral_site": False,
        "conference_game": True,
        "venue": "Test Field",
        "home_id": home,
        "home_team": TEAMS[home],
        "home_classification": "fbs",
        "home_conference": "Test Conference",
        "home_points": 20,
        "away_id": away,
        "away_team": TEAMS[away],
        "away_classification": "fbs",
        "away_conference": "Test Conference",
        "away_points": 17,
        "excitement_index": None,
        "notes": None,
    }
    defaults.update(extra)
    return CfbdGame(**defaults)


def _networks() -> NetworkTable:
    def row(variant: str, network_id: str) -> NetworkRow:
        return NetworkRow(
            variant=variant,
            network_id=network_id,
            display_name=network_id,
            family=network_id,
            tier="cable",
            feed_type="main",
            season_from=None,
            season_to=None,
            priority=None,
        )

    return NetworkTable([row("ABC", "abc"), row("ESPN2", "espn2"), row("ESPNU", "espnu")])


def _row(pointer: str, away: str, home: str, viewers: int | None = 1_000_000, **extra: Any) -> Any:
    fields: dict[str, Any] = {
        "source": "smw",
        "season": SEASON,
        "pointer": pointer,
        "date_et": date(SEASON, 10, 1),
        "away_raw": away,
        "home_raw": home,
        "network_raw": "ABC",
        "viewers": viewers,
        "kind": "figure",
        "chart_kind": "weekly",
        "rank": 3,
        "source_url": "https://www.sportsmediawatch.com/college-football-tv-ratings/2022-season/",
        "superseded": False,
    }
    fields.update(extra)
    return SecondSourceRow(**fields)


def _telecast(game_id: int, network: str = "abc", rated: bool = False, crew: bool = False) -> dict:
    return {
        "telecast_id": f"{game_id}-{network}",
        "game_id": game_id,
        "season": SEASON,
        "network_id": network,
        "feed_type": "main",
        "rated": rated,
        "crew_matched": crew,
    }


def _rr(value: float) -> RRRecord:
    return RRRecord(
        telecast=RRTelecast(
            id="cfb-x",
            event_date=date(SEASON, 10, 1),
            networks=["ABC"],
            teams=["a", "b"],
            kind="game",
            tier=2,
        ),
        claims=[
            RRClaim(
                metric_type="avg_audience",
                status="final",
                value=value,
                unit="viewers",
                first_published="2022-10-03",
                confidence=1.0,
            )
        ],
    )


class Harness:
    def __init__(self) -> None:
        self.games = [_game(100, home=2, away=1)]  # Silverlake at Northfield, 10/1
        self.telecasts = [_telecast(100)]
        self.records: dict[str, list[RRRecord]] = {}
        self.crosswalk: list[TeamCrosswalkRow] = []
        self.overrides: dict[tuple[str, int, str], GameOverride] = {}
        self.accepts: frozenset[tuple[str, int, str]] = frozenset()
        self.gate_overrides: dict[tuple[str, int], int] = {}
        self.known: dict[tuple[str, int], frozenset[str]] = {}
        self.fbs: set[int] | None = None
        self.season_counts: dict[int, dict[str, int]] = {SEASON: {"rated_telecasts": 5}}

    def alias(self, variant: str, *team_ids: int) -> None:
        for team_id in team_ids:
            self.crosswalk.append(
                TeamCrosswalkRow("smw", variant, TEAMS[team_id], team_id, None, None, "")
            )

    def run(self, rows: list[Any]) -> tuple[SecondSourceResult, pl.DataFrame]:
        frame = pl.DataFrame(
            self.telecasts,
            schema={
                "telecast_id": pl.Utf8,
                "game_id": pl.Int64,
                "season": pl.Int32,
                "network_id": pl.Utf8,
                "feed_type": pl.Utf8,
                "rated": pl.Boolean,
                "crew_matched": pl.Boolean,
            },
        )
        result = apply_second_sources(
            frame,
            self.records,
            SecondSourceInputs(rows=tuple(rows), known=self.known),
            resolver=TeamResolver({SEASON: self.games}, self.crosswalk),
            index=GameIndex(self.games),
            networks=_networks(),
            overrides=self.overrides,
            accepts=self.accepts,
            gate_overrides=self.gate_overrides,
            fbs_game_ids=self.fbs if self.fbs is not None else {g.id for g in self.games},
            season_counts=self.season_counts,
        )
        return result, frame


def _review(result: SecondSourceResult, name: str) -> list[dict[str, object]]:
    return result.review_rows[name][1]


def _gate(result: SecondSourceResult) -> Any:
    assert len(result.gates) == 1
    return result.gates[0]


# -- Exclusions ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "field"),
    [
        ("simulcast", "excluded_simulcast"),
        ("multi_feed", "excluded_multi_feed"),
        ("regional", "excluded_regional"),
        ("non_nielsen", "excluded_non_nielsen"),
        ("no_figure", "no_figure"),
    ],
)
def test_excluded_kinds_never_load(kind: str, field: str) -> None:
    h = Harness()
    result, _ = h.run([_row("w:1", "Silverlake", "Northfield", None, kind=kind)])
    assert result.claims_by_telecast == {}
    assert getattr(_gate(result), field) == 1
    assert _review(result, REVIEW_UNMATCHED) == []


def test_unknown_suffix_goes_to_unmatched_and_superseded_is_ignored() -> None:
    h = Harness()
    rows = [
        _row("w:1", "Silverlake", "Northfield", None, kind="unknown_suffix"),
        _row("w:2", "Silverlake", "Northfield", superseded=True),
    ]
    result, _ = h.run(rows)
    unmatched = _review(result, REVIEW_UNMATCHED)
    assert [r["reason"] for r in unmatched] == ["unknown_suffix"]
    assert result.claims_by_telecast == {}


# -- Matching --------------------------------------------------------------------------------


def test_exact_swapped_and_date_shift_match() -> None:
    h = Harness()
    rows = [
        _row("w:1", "Silverlake", "Northfield"),
        _row("w:2", "Northfield", "Silverlake", 2_000_000, network_raw="ABC"),
        _row("w:3", "Silverlake", "Northfield", 3_000_000, date_et=date(SEASON, 10, 2)),
    ]
    result, _ = h.run(rows)
    # all three land on one telecast; the highest-ranked (tie: latest pointer) wins
    assert list(result.claims_by_telecast) == ["100-abc"]
    assert _gate(result).matched == 3
    assert _review(result, REVIEW_UNMATCHED) == []


def test_date_off_by_two_is_unmatched_none() -> None:
    h = Harness()
    result, _ = h.run([_row("w:1", "Silverlake", "Northfield", date_et=date(SEASON, 10, 4))])
    (row,) = _review(result, REVIEW_UNMATCHED)
    assert (row["reason"], row["confidence"]) == ("none", "none")


def test_candidate_set_picks_the_team_that_plays() -> None:
    h = Harness()
    h.alias("MSU", 3, 4)
    # Lakeshore at Northfield; Riverbend plays elsewhere so the crosswalk id is valid
    h.games = [_game(100, home=2, away=4), _game(200, home=5, away=3, day=8)]
    result, _ = h.run([_row("w:1", "MSU", "Northfield")])
    assert list(result.claims_by_telecast) == ["100-abc"]


def test_candidate_set_both_play_is_ambiguous() -> None:
    h = Harness()
    h.alias("MSU", 3, 4)
    h.games = [_game(100, home=2, away=3), _game(101, home=2, away=4)]
    h.telecasts = [_telecast(100), _telecast(101)]
    result, _ = h.run([_row("w:1", "MSU", "Northfield")])
    (row,) = _review(result, REVIEW_UNMATCHED)
    assert (row["reason"], row["confidence"]) == ("ambiguous", "ambiguous")
    assert result.counts["ambiguous"] == 1
    assert result.claims_by_telecast == {}


def test_unresolved_team_and_missing_date() -> None:
    h = Harness()
    rows = [
        _row("w:1", "Nowhere State", "Northfield"),
        _row("w:2", "Silverlake", "Northfield", date_et=None),
    ]
    result, _ = h.run(rows)
    reasons = {r["pointer"]: r["reason"] for r in _review(result, REVIEW_UNMATCHED)}
    assert reasons == {"w:1": "unresolved_team", "w:2": "no_date"}
    (unresolved,) = result.unresolved_rows
    assert (unresolved.source, unresolved.raw_name, unresolved.occurrences) == (
        "smw",
        "Nowhere State",
        1,
    )


def test_override_exclude_and_match() -> None:
    h = Harness()

    def override(action: str, game_id: int | None) -> GameOverride:
        return GameOverride("smw", SEASON, "w:1", action, game_id, "other")  # type: ignore[arg-type]

    h.overrides = {("smw", SEASON, "w:1"): override("exclude", None)}
    result, _ = h.run([_row("w:1", "Silverlake", "Northfield")])
    assert result.claims_by_telecast == {}
    assert _review(result, REVIEW_UNMATCHED) == []

    h.overrides = {("smw", SEASON, "w:1"): override("match", 100)}
    result, _ = h.run([_row("w:1", "Totally Unknown", "Also Unknown")])
    assert list(result.claims_by_telecast) == ["100-abc"]


# -- Scope, no telecast, and no telecast creation -----------------------------------------------


def test_out_of_scope_and_no_telecast_counted_without_review_rows() -> None:
    h = Harness()
    h.fbs = set()
    result, frame = h.run([_row("w:1", "Silverlake", "Northfield")])
    assert _gate(result).out_of_scope == 1
    assert result.telecasts.height == frame.height

    h = Harness()
    h.telecasts = []
    result, frame = h.run([_row("w:1", "Silverlake", "Northfield")])
    assert _gate(result).no_telecast == 1
    assert result.telecasts.height == frame.height == 0
    assert all(not _review(result, name) for name in (REVIEW_UNMATCHED, REVIEW_NETWORK))


# -- Network hold ----------------------------------------------------------------------------


def test_network_clash_is_held_until_accepted() -> None:
    h = Harness()
    h.telecasts = [_telecast(100, "espnu")]
    row = _row("w:1", "Silverlake", "Northfield", network_raw="ESPN2")
    result, _ = h.run([row])
    assert result.claims_by_telecast == {}
    (held,) = _review(result, REVIEW_NETWORK)
    assert held["our_network_ids"] == "espnu"
    assert held["chart_network_id"] == "espn2"
    assert result.counts["held_network"] == 1

    h.accepts = frozenset({("smw", SEASON, "w:1")})
    result, _ = h.run([row])
    assert list(result.claims_by_telecast) == ["100-espnu"]
    assert _review(result, REVIEW_NETWORK) == []


def test_accept_does_not_release_a_game_with_two_main_telecasts() -> None:
    h = Harness()
    h.telecasts = [_telecast(100, "espnu"), _telecast(100, "abc")]
    h.accepts = frozenset({("smw", SEASON, "w:1")})
    row = _row("w:1", "Silverlake", "Northfield", network_raw="ESPN2")
    result, _ = h.run([row])
    assert result.claims_by_telecast == {}
    (held,) = _review(result, REVIEW_NETWORK)
    assert held["our_network_ids"] == "abc|espnu"


def test_unmapped_network_text_is_unmatched() -> None:
    h = Harness()
    result, _ = h.run([_row("w:1", "Silverlake", "Northfield", network_raw="Mystery Net")])
    (row,) = _review(result, REVIEW_UNMATCHED)
    assert row["reason"] == "unmapped_network"


# -- Duplicates and season-top ------------------------------------------------------------------


def test_duplicate_weekly_rows_keep_highest_rank() -> None:
    h = Harness()
    rows = [
        _row("a.png:1", "Silverlake", "Northfield", 1_000_000, rank=3),
        _row("b.png:1", "Silverlake", "Northfield", 1_200_000, rank=7),
    ]
    result, _ = h.run(rows)
    (claim,) = result.claims_by_telecast["100-abc"]
    assert claim.value == 1_200_000
    (conflict,) = _review(result, REVIEW_CONFLICTS)
    assert conflict["kind"] == "duplicate"
    assert (conflict["kept_pointer"], conflict["other_pointer"]) == ("b.png:1", "a.png:1")


def test_equal_duplicate_figures_list_no_conflict() -> None:
    h = Harness()
    rows = [
        _row("a.png:1", "Silverlake", "Northfield", rank=3),
        _row("b.png:1", "Silverlake", "Northfield", rank=7),
    ]
    result, _ = h.run(rows)
    assert _review(result, REVIEW_CONFLICTS) == []


def test_season_top_never_overrides_weekly() -> None:
    h = Harness()
    rows = [
        _row("a.png:1", "Silverlake", "Northfield", 1_000_000, rank=3),
        _row("top.png:2", "Silverlake", "Northfield", 1_100_000, rank=20, chart_kind="season_top"),
    ]
    result, _ = h.run(rows)
    (claim,) = result.claims_by_telecast["100-abc"]
    assert claim.value == 1_000_000
    (conflict,) = _review(result, REVIEW_CONFLICTS)
    assert conflict["kind"] == "season_top"


def test_season_top_fills_uncovered_telecast_and_matches_without_date() -> None:
    h = Harness()
    top = _row("top.png:2", "Silverlake", "Northfield", chart_kind="season_top", date_et=None)
    result, _ = h.run([top])
    assert list(result.claims_by_telecast) == ["100-abc"]

    # a second meeting of the pair that season makes a dateless row ambiguous
    h.games.append(_game(101, home=1, away=2, day=15))
    result, _ = h.run([top])
    assert result.claims_by_telecast == {}
    (row,) = _review(result, REVIEW_UNMATCHED)
    assert row["reason"] == "ambiguous"


# -- Agreement gate --------------------------------------------------------------------------


def _shared_harness(second: list[int]) -> tuple[Harness, list[Any]]:
    h = Harness()
    pairs = [(1, 2), (3, 4), (5, 1)]
    h.games = [_game(100 + i, home=a, away=b) for i, (a, b) in enumerate(pairs)]
    h.telecasts = [_telecast(100 + i) for i in range(len(pairs))]
    rows = []
    for i, ((a, b), value) in enumerate(zip(pairs, second, strict=True)):
        h.records[f"{100 + i}-abc"] = [_rr(1_000_000)]
        rows.append(_row(f"c.png:{i + 1}", TEAMS[b], TEAMS[a], value))
    return h, rows


def test_gate_unexplained_miss_withholds_the_season() -> None:
    h, rows = _shared_harness([1_020_000, 1_000_000, 1_050_000])
    result, _ = h.run(rows)
    gate = _gate(result)
    assert (gate.shared, gate.within_3pct, gate.unexplained, gate.status) == (3, 2, 1, "withheld")
    assert result.claims_by_telecast == {}
    assert result.counts["withheld_seasons"] == 1
    assert gate.loaded == 0
    statuses = {r["pointer"]: r["status"] for r in _review(result, REVIEW_AGREEMENT)}
    assert statuses["c.png:3"] == "miss_unexplained"
    (agreement,) = [r for r in _review(result, REVIEW_AGREEMENT) if r["pointer"] == "c.png:3"]
    assert agreement["pct_diff"] == 0.05


def test_gate_known_miss_is_logged_and_season_loads() -> None:
    h, rows = _shared_harness([1_020_000, 1_000_000, 1_050_000])
    h.known = {("smw", SEASON): frozenset({"c.png:3"})}
    result, _ = h.run(rows)
    gate = _gate(result)
    assert (gate.logged, gate.unexplained, gate.status, gate.loaded) == (1, 0, "passed", 3)
    assert len(result.claims_by_telecast) == 3


def test_gate_three_logged_misses_withhold_unless_overridden() -> None:
    h, rows = _shared_harness([1_100_000, 1_200_000, 1_300_000])
    h.known = {("smw", SEASON): frozenset({"c.png:1", "c.png:2", "c.png:3"})}
    result, _ = h.run(rows)
    assert (_gate(result).logged, _gate(result).status) == (3, "withheld")

    h.gate_overrides = {("smw", SEASON): 3}
    result, _ = h.run(rows)
    assert _gate(result).status == "passed"
    assert len(result.claims_by_telecast) == 3


def test_gate_override_never_releases_an_unexplained_miss() -> None:
    h, rows = _shared_harness([1_100_000, 1_000_000, 1_000_000])
    h.gate_overrides = {("smw", SEASON): 20}
    result, _ = h.run(rows)
    assert _gate(result).status == "withheld"
    assert result.claims_by_telecast == {}


def test_gate_stale_known_pointer_is_counted_not_failed() -> None:
    h, rows = _shared_harness([1_000_000, 1_000_000, 1_000_000])
    h.known = {("smw", SEASON): frozenset({"gone.png:9"})}
    result, _ = h.run(rows)
    gate = _gate(result)
    assert (gate.stale_known, gate.status) == (1, "passed")


def test_gate_no_shared_telecast_loads_figures() -> None:
    h = Harness()
    result, _ = h.run([_row("w:1", "Silverlake", "Northfield")])
    gate = _gate(result)
    assert (gate.status, gate.shared, gate.loaded) == ("no_shared", 0, 1)
    assert list(result.claims_by_telecast) == ["100-abc"]


def test_gate_exactly_three_percent_is_within() -> None:
    h = Harness()
    h.records["100-abc"] = [_rr(1_000_000)]
    result, _ = h.run([_row("w:1", "Silverlake", "Northfield", 1_030_000)])
    gate = _gate(result)
    assert (gate.within_3pct, gate.unexplained, gate.status) == (1, 0, "passed")
    h.records["100-abc"] = [_rr(1_000_000)]
    result, _ = h.run([_row("w:1", "Silverlake", "Northfield", 1_030_001)])
    assert _gate(result).status == "withheld"


# -- Claims and the flip ----------------------------------------------------------------------


def test_adapter_claim_shape() -> None:
    h = Harness()
    result, _ = h.run([_row("week5cfb.png:12", "Silverlake", "Northfield", 5_830_000)])
    (claim,) = result.claims_by_telecast["100-abc"]
    assert claim.model_extra is not None
    assert claim.model_extra["id"] == f"smw:{SEASON}:week5cfb.png:12"
    assert claim.model_extra["source"] == "smw"
    assert (claim.metric_type, claim.unit, claim.status) == ("avg_audience", "viewers", "final")
    assert claim.value == 5_830_000.0
    assert claim.publisher == "Sports Media Watch"
    assert claim.source_url == (
        "https://www.sportsmediawatch.com/college-football-tv-ratings/2022-season/"
    )
    assert claim.measured_by is None


def test_unrated_telecast_flips_and_counts() -> None:
    h = Harness()
    h.telecasts = [_telecast(100, crew=True)]
    before = {k: dict(v) for k, v in h.season_counts.items()}
    result, _ = h.run([_row("w:1", "Silverlake", "Northfield")])
    assert result.telecasts["rated"].to_list() == [True]
    bucket = result.season_counts[SEASON]
    assert bucket["rated_telecasts"] == 6
    assert bucket["rated_second_source"] == 1
    assert bucket["rated_with_crew"] == 1
    assert h.season_counts == before  # input not mutated


def test_rr_rated_telecast_gets_claim_but_no_count_change() -> None:
    h = Harness()
    h.telecasts = [_telecast(100, rated=True, crew=True)]
    h.records["100-abc"] = [_rr(1_000_000)]
    result, _ = h.run([_row("w:1", "Silverlake", "Northfield")])
    assert list(result.claims_by_telecast) == ["100-abc"]
    assert result.season_counts[SEASON]["rated_telecasts"] == 5
    assert result.season_counts[SEASON]["rated_second_source"] == 0
    assert "rated_with_crew" not in result.season_counts[SEASON]


def test_held_excluded_and_withheld_rows_flip_nothing() -> None:
    h = Harness()
    h.telecasts = [_telecast(100, "espnu")]
    result, _ = h.run([_row("w:1", "Silverlake", "Northfield", network_raw="ESPN2")])
    assert result.telecasts["rated"].to_list() == [False]
    assert result.season_counts[SEASON]["rated_second_source"] == 0


def test_result_has_every_review_table_with_columns() -> None:
    result, _ = Harness().run([])
    assert set(result.review_rows) == set(SECOND_SOURCE_REVIEW_NAMES)
    assert result.review_rows[REVIEW_GATE][0][-1] == "status"


# -- Reference tables and the vault loader -------------------------------------------------------


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_load_network_accepts(tmp_path: Path) -> None:
    assert load_network_accepts(tmp_path) == frozenset()
    _write(
        tmp_path / "second_source_network_accepts.csv",
        "source,season,pointer,reason\nsmw,2022,week5cfb.png:12,chart prints ESPN2\n",
    )
    assert load_network_accepts(tmp_path) == {("smw", 2022, "week5cfb.png:12")}


@pytest.mark.parametrize(
    "line",
    [
        "other,2022,p:1,why",
        "smw,twenty,p:1,why",
        "smw,2022,,why",
        "smw,2022,p:1,",
        f"smw,2022,p:1,{'x' * 81}",
    ],
)
def test_load_network_accepts_rejects_bad_rows(tmp_path: Path, line: str) -> None:
    _write(
        tmp_path / "second_source_network_accepts.csv",
        f"source,season,pointer,reason\n{line}\n",
    )
    with pytest.raises(ReferenceTableError, match="line 2"):
        load_network_accepts(tmp_path)


def test_load_network_accepts_rejects_duplicates(tmp_path: Path) -> None:
    _write(
        tmp_path / "second_source_network_accepts.csv",
        "source,season,pointer,reason\nsmw,2022,p:1,a\nsmw,2022,p:1,b\n",
    )
    with pytest.raises(ReferenceTableError, match="line 3"):
        load_network_accepts(tmp_path)


def test_load_gate_overrides(tmp_path: Path) -> None:
    assert load_gate_overrides(tmp_path) == {}
    path = tmp_path / "second_source_gate_overrides.csv"
    _write(path, "source,season,max_logged,reason\nsmw,2022,3,reviewed misses\n")
    assert load_gate_overrides(tmp_path) == {("smw", 2022): 3}
    for bad in ("smw,2022,2,r", "smw,2022,21,r", "smw,2022,x,r", "smw,2022,3,"):
        _write(path, f"source,season,max_logged,reason\n{bad}\n")
        with pytest.raises(ReferenceTableError, match="line 2"):
            load_gate_overrides(tmp_path)
    _write(path, "source,season,max_logged,reason\nsmw,2022,3,r\nsmw,2022,4,r\n")
    with pytest.raises(ReferenceTableError, match="line 3"):
        load_gate_overrides(tmp_path)


def test_load_second_source_inputs_reads_smw_season(tmp_path: Path) -> None:
    folder = build_season(tmp_path / "vault" / "raw" / "smw" / "2022")
    charts = sorted(p.name for p in folder.glob("*.png"))
    write_chart_order_csv(folder / "chart_order.csv", parse_chart_order(PAGE, set(charts)))
    _write(
        folder / "transcription" / "known_disagreements.csv",
        "chart_file,row,explanation\nweek5cfb.png,1,reviewed\n",
    )
    paths = DataPaths(vault=tmp_path / "vault")
    inputs = load_second_source_inputs(paths)
    assert len(inputs.rows) == 3
    assert {r.source_url for r in inputs.rows} == {
        "https://www.sportsmediawatch.com/college-football-tv-ratings/2022-season/"
    }
    assert inputs.known == {("smw", 2022): frozenset({"week5cfb.png:1"})}
    assert load_second_source_inputs(paths, seasons=[2021]).rows == ()


def test_loader_rejects_a_season_page_for_another_year(tmp_path: Path) -> None:
    folder = build_season(tmp_path / "vault" / "raw" / "smw" / "2023")
    charts = sorted(p.name for p in folder.glob("*.png"))
    write_chart_order_csv(folder / "chart_order.csv", parse_chart_order(PAGE, set(charts)))
    with pytest.raises(ReferenceTableError, match="does not name the season"):
        load_second_source_inputs(DataPaths(vault=tmp_path / "vault"))
