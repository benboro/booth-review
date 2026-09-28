"""Tests for build/viewership.py: every claim kept, the headline pick over
pooled merged-record claims (JOIN-04), the RR-current disagreement reason,
era/measurement/model-break/combined flags, and the plotted rule (D-10).

Telecasts and records are hand-built directly (no reference CSVs, no
build_telecasts call) since build_viewership/apply_headlines only need a
telecasts frame (TELECASTS_SCHEMA-shaped) and a records_by_telecast mapping.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from booth_review.build.telecasts import TELECASTS_SCHEMA, TelecastBuild
from booth_review.build.viewership import (
    TELECAST_FLAGS_SCHEMA,
    VIEWERSHIP_SCHEMA,
    apply_headlines,
    build_viewership,
)
from booth_review.flags.era import MeasurementEra
from booth_review.flags.events import EventFlag
from booth_review.sources.ratingsref.parser import RRClaim, RRRecord, RRTelecast


def _claim(
    *,
    claim_id: str,
    status: str = "final",
    value: float | None = 2_000_000.0,
    metric_type: str = "avg_audience",
    unit: str | None = "viewers",
    supersedes_id: str | None = None,
    figure_type: str | None = "currency",
    confidence: float | None = 1.0,
    first_published: str | None = "2025-09-16",
    measured_by: str | None = "nielsen",
    era_id: str | None = "rr-era-a",
    composite_of: list[str] | None = None,
    publisher: str | None = None,
) -> RRClaim:
    return RRClaim.model_validate(
        {
            "metric_type": metric_type,
            "status": status,
            "value": value,
            "unit": unit,
            "supersedes_id": supersedes_id,
            "confidence": confidence,
            "first_published": first_published,
            "id": claim_id,
            "figure_type": figure_type,
            "measured_by": measured_by,
            "era_id": era_id,
            "composite_of": composite_of,
            "publisher": publisher,
        }
    )


def _record(
    *,
    record_id: str,
    claims: list[RRClaim],
    rr_current_claim_id: str | None = None,
    rr_current_status: str = "no_peers",
    event_date: date = date(2025, 9, 13),
) -> RRRecord:
    return RRRecord(
        telecast=RRTelecast(
            id=record_id,
            event_date=event_date,
            teams=["cfb-example", "cfb-sample"],
            networks=["Net Alpha"],
        ),
        claims=claims,
        rr_current_claim_id=rr_current_claim_id,
        rr_current_status=rr_current_status,
    )


def _telecast_row(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "telecast_id": "1-alpha",
        "game_id": 1,
        "season": 2025,
        "date_et": date(2025, 9, 13),
        "network_id": "alpha",
        "feed_type": "main",
        "outlets": ["alpha"],
        "rated": True,
        "rr_telecast_ids": [],
        "rr_record_urls": [],
        "duplicate_merges": 0,
        "rr_match_confidence": "exact",
        "s506_match_confidence": "exact",
        "match_confidence": "exact",
        "s506_pointer": "1:0",
        "s506_week": "1",
        "s506_url": "https://506sports.com/ncaaf.php?yr=2025&wk=1",
        "kickoff_et": None,
        "crew_matched": True,
        "crew_network_mismatch": False,
        "combined_feeds": None,
        "plotted": False,
        "headline_claim_id": None,
        "headline_value": None,
        "headline_publisher": None,
        "headline_source_url": None,
        "measurement_type": None,
        "era_id": None,
        "rr_current_check": None,
        "model_break": None,
    }
    defaults.update(overrides)
    return defaults


def _telecasts_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=TELECASTS_SCHEMA)


def _build_telecast_build(
    rows: list[dict[str, object]], records_by_telecast: dict[str, list[RRRecord]]
) -> TelecastBuild:
    return TelecastBuild(
        telecasts=_telecasts_frame(rows),
        listing_links=pl.DataFrame(),
        records_by_telecast=records_by_telecast,
        counts={},
        unmatched_rows=[],
        unresolved_rows=[],
    )


_ERAS = [
    MeasurementEra(
        era_id="era-early",
        label="Early",
        start=None,
        end=date(2025, 8, 31),
        rr_era_ids=frozenset({"rr-era-a"}),
        source_url="https://example.com/era-early",
        note="",
    ),
    MeasurementEra(
        era_id="era-late",
        label="Late",
        start=date(2025, 9, 1),
        end=None,
        rr_era_ids=frozenset({"rr-era-b"}),
        source_url="https://example.com/era-late",
        note="",
    ),
]

_EVENT_FLAGS = [
    EventFlag(
        flag_id="carriage-dispute",
        kind="event",
        label="Invented carriage dispute",
        start=date(2025, 9, 10),
        end=date(2025, 9, 20),
        season_from=None,
        networks=frozenset(),
        source_url="https://example.com/event",
        note="",
    ),
    EventFlag(
        flag_id="model-break-2025",
        kind="model_break",
        label="Invented model break",
        start=None,
        end=None,
        season_from=2025,
        networks=frozenset(),
        source_url="https://example.com/modelbreak",
        note="",
    ),
]


# -- build_viewership: all claims kept, is_headline, is_rr_current ---------------------------


def test_all_claims_are_kept_only_one_is_headline() -> None:
    record = _record(
        record_id="cfb-example-sample-2025-09-13",
        claims=[
            _claim(claim_id="c-final", status="final"),
            _claim(claim_id="c-prelim", status="preliminary"),
            _claim(claim_id="c-peak", metric_type="peak_audience", unit="viewers"),
        ],
    )
    rows = [_telecast_row()]
    build = _build_telecast_build(rows, {"1-alpha": [record]})

    viewership = build_viewership(build, _ERAS)

    assert viewership.height == 3
    headline_rows = viewership.filter(pl.col("is_headline"))
    assert headline_rows.height == 1
    assert headline_rows.row(0, named=True)["claim_id"] == "c-final"


def test_headline_is_selected_over_pooled_claims_of_merged_records() -> None:
    record_a = _record(
        record_id="cfb-example-sample-2025-09-13-a",
        claims=[_claim(claim_id="c-a-final", status="final", value=100.0)],
    )
    record_b = _record(
        record_id="cfb-example-sample-2025-09-13-b",
        claims=[_claim(claim_id="c-b-prelim", status="preliminary", value=200.0)],
    )
    rows = [_telecast_row()]
    build = _build_telecast_build(rows, {"1-alpha": [record_a, record_b]})

    viewership = build_viewership(build, _ERAS)

    headline_rows = viewership.filter(pl.col("is_headline"))
    assert headline_rows.height == 1
    assert headline_rows.row(0, named=True)["claim_id"] == "c-a-final"


def test_no_eligible_claim_means_no_headline_row() -> None:
    record = _record(
        record_id="cfb-example-sample-2025-09-13",
        claims=[_claim(claim_id="c-peak", metric_type="peak_audience", unit="viewers")],
    )
    rows = [_telecast_row()]
    build = _build_telecast_build(rows, {"1-alpha": [record]})

    viewership = build_viewership(build, _ERAS)

    assert viewership.filter(pl.col("is_headline")).height == 0


def test_is_rr_current_null_when_status_is_not_found() -> None:
    record = _record(
        record_id="cfb-example-sample-2025-09-13",
        claims=[_claim(claim_id="c-final")],
        rr_current_claim_id=None,
        rr_current_status="no_self_row",
    )
    rows = [_telecast_row()]
    build = _build_telecast_build(rows, {"1-alpha": [record]})

    viewership = build_viewership(build, _ERAS)

    assert viewership.row(0, named=True)["is_rr_current"] is None


def test_is_rr_current_true_when_claim_matches_rr_pick() -> None:
    record = _record(
        record_id="cfb-example-sample-2025-09-13",
        claims=[_claim(claim_id="c-final")],
        rr_current_claim_id="c-final",
        rr_current_status="found",
    )
    rows = [_telecast_row()]
    build = _build_telecast_build(rows, {"1-alpha": [record]})

    viewership = build_viewership(build, _ERAS)

    assert viewership.row(0, named=True)["is_rr_current"] is True


def test_viewership_schema_columns_and_dtypes() -> None:
    build = _build_telecast_build([_telecast_row()], {})
    viewership = build_viewership(build, _ERAS)

    assert viewership.columns == list(VIEWERSHIP_SCHEMA.keys())
    for column, dtype in VIEWERSHIP_SCHEMA.items():
        assert viewership.schema[column] == dtype


# -- era boundary and era_check ---------------------------------------------------------------


def test_era_assigned_by_telecast_air_date_not_rr_era_id() -> None:
    record = _record(
        record_id="cfb-example-sample-2025-09-13",
        claims=[_claim(claim_id="c-final", era_id="rr-era-a")],  # RR says the early era
        event_date=date(2025, 9, 13),
    )
    # Telecast's own date_et is Sept 13, in the *late* era per our own table.
    rows = [_telecast_row(date_et=date(2025, 9, 13))]
    build = _build_telecast_build(rows, {"1-alpha": [record]})

    viewership = build_viewership(build, _ERAS)

    row = viewership.row(0, named=True)
    assert row["era_id"] == "era-late"
    assert row["era_check"] == "disagree"  # rr-era-a isn't era-late's rr_era_ids


def test_era_check_agrees_when_rr_era_id_matches() -> None:
    record = _record(
        record_id="cfb-example-sample-2025-09-13",
        claims=[_claim(claim_id="c-final", era_id="rr-era-b")],
    )
    rows = [_telecast_row(date_et=date(2025, 9, 13))]
    build = _build_telecast_build(rows, {"1-alpha": [record]})

    viewership = build_viewership(build, _ERAS)

    assert viewership.row(0, named=True)["era_check"] == "agree"


def test_era_check_not_comparable_when_rr_era_id_is_missing() -> None:
    record = _record(
        record_id="cfb-example-sample-2025-09-13",
        claims=[_claim(claim_id="c-final", era_id=None)],
    )
    rows = [_telecast_row(date_et=date(2025, 9, 13))]
    build = _build_telecast_build(rows, {"1-alpha": [record]})

    viewership = build_viewership(build, _ERAS)

    assert viewership.row(0, named=True)["era_check"] == "not_comparable"


# -- measurement type ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("measured_by", "expected"),
    [("nielsen", "nielsen"), ("blend", "nielsen_adobe"), (None, "unknown"), ("other", "unknown")],
)
def test_measurement_type_per_claim(measured_by: str | None, expected: str) -> None:
    record = _record(
        record_id="cfb-example-sample-2025-09-13",
        claims=[_claim(claim_id="c-final", measured_by=measured_by)],
    )
    rows = [_telecast_row()]
    build = _build_telecast_build(rows, {"1-alpha": [record]})

    viewership = build_viewership(build, _ERAS)

    assert viewership.row(0, named=True)["measurement_type"] == expected


# -- apply_headlines: headline columns, disagreement reasons -----------------------------------


def test_apply_headlines_fills_headline_columns() -> None:
    record = _record(
        record_id="cfb-example-sample-2025-09-13",
        claims=[_claim(claim_id="c-final", value=1_500_000.0, publisher="Example PR")],
    )
    rows = [_telecast_row()]
    build = _build_telecast_build(rows, {"1-alpha": [record]})
    viewership = build_viewership(build, _ERAS)

    telecasts, disagreements, _era_disagreements, _flags = apply_headlines(
        build.telecasts, viewership, build.records_by_telecast, _ERAS, _EVENT_FLAGS
    )

    row = telecasts.row(0, named=True)
    assert row["headline_claim_id"] == "c-final"
    assert row["headline_value"] == 1_500_000.0
    assert row["headline_publisher"] == "Example PR"
    assert row["measurement_type"] == "nielsen"
    assert row["era_id"] == "era-late"
    assert disagreements == []


def test_apply_headlines_disagreement_reason_same_rank_key() -> None:
    older = _claim(claim_id="c-older", status="final", first_published="2025-09-14")
    newer = _claim(claim_id="c-newer", status="final", first_published="2025-09-18")
    record = _record(
        record_id="cfb-example-sample-2025-09-13",
        claims=[older, newer],
        rr_current_claim_id="c-older",
        rr_current_status="found",
    )
    rows = [_telecast_row()]
    build = _build_telecast_build(rows, {"1-alpha": [record]})
    viewership = build_viewership(build, _ERAS)

    _telecasts, disagreements, _era, _flags = apply_headlines(
        build.telecasts, viewership, build.records_by_telecast, _ERAS, _EVENT_FLAGS
    )

    assert len(disagreements) == 1
    assert disagreements[0]["reason"] == "same_rank_key"
    assert disagreements[0]["headline_claim_id"] == "c-newer"
    assert disagreements[0]["rr_current_claim_id"] == "c-older"


def test_apply_headlines_disagreement_reason_rule_difference() -> None:
    final_claim = _claim(claim_id="c-final", status="final")
    prelim_claim = _claim(claim_id="c-prelim", status="preliminary")
    record = _record(
        record_id="cfb-example-sample-2025-09-13",
        claims=[final_claim, prelim_claim],
        rr_current_claim_id="c-prelim",
        rr_current_status="found",
    )
    rows = [_telecast_row()]
    build = _build_telecast_build(rows, {"1-alpha": [record]})
    viewership = build_viewership(build, _ERAS)

    _telecasts, disagreements, _era, _flags = apply_headlines(
        build.telecasts, viewership, build.records_by_telecast, _ERAS, _EVENT_FLAGS
    )

    assert len(disagreements) == 1
    assert disagreements[0]["reason"] == "rule_difference"


def test_apply_headlines_agrees_when_rr_current_matches() -> None:
    record = _record(
        record_id="cfb-example-sample-2025-09-13",
        claims=[_claim(claim_id="c-final")],
        rr_current_claim_id="c-final",
        rr_current_status="found",
    )
    rows = [_telecast_row()]
    build = _build_telecast_build(rows, {"1-alpha": [record]})
    viewership = build_viewership(build, _ERAS)

    telecasts, disagreements, _era, _flags = apply_headlines(
        build.telecasts, viewership, build.records_by_telecast, _ERAS, _EVENT_FLAGS
    )

    assert telecasts.row(0, named=True)["rr_current_check"] == "agree"
    assert disagreements == []


def test_apply_headlines_not_comparable_when_no_records() -> None:
    rows = [_telecast_row(rated=False, network_id="alpha")]
    build = _build_telecast_build(rows, {})
    viewership = build_viewership(build, _ERAS)

    telecasts, disagreements, _era, _flags = apply_headlines(
        build.telecasts, viewership, build.records_by_telecast, _ERAS, _EVENT_FLAGS
    )

    assert telecasts.row(0, named=True)["rr_current_check"] is None
    assert disagreements == []


# -- telecast_flags kinds -----------------------------------------------------------------------


def test_telecast_flags_include_era_event_model_break_measurement_and_combined() -> None:
    record = _record(
        record_id="cfb-example-sample-2025-09-13",
        claims=[_claim(claim_id="c-final", measured_by="blend", composite_of=["cfb-a", "cfb-b"])],
    )
    rows = [_telecast_row(combined_feeds=2)]
    build = _build_telecast_build(rows, {"1-alpha": [record]})
    viewership = build_viewership(build, _ERAS)

    _telecasts, _dis, _era_dis, flags = apply_headlines(
        build.telecasts, viewership, build.records_by_telecast, _ERAS, _EVENT_FLAGS
    )

    kinds = set(flags["kind"].to_list())
    assert kinds == {"era", "event", "model_break", "measurement", "combined"}
    assert flags.columns == list(TELECAST_FLAGS_SCHEMA.keys())


def test_telecast_flags_omit_measurement_and_combined_when_not_applicable() -> None:
    record = _record(
        record_id="cfb-example-sample-2025-09-13",
        claims=[_claim(claim_id="c-final", measured_by="nielsen", composite_of=None)],
    )
    rows = [_telecast_row(combined_feeds=None)]
    build = _build_telecast_build(rows, {"1-alpha": [record]})
    viewership = build_viewership(build, _ERAS)

    _telecasts, _dis, _era_dis, flags = apply_headlines(
        build.telecasts, viewership, build.records_by_telecast, _ERAS, _EVENT_FLAGS
    )

    kinds = set(flags["kind"].to_list())
    assert "measurement" not in kinds
    assert "combined" not in kinds


def test_model_break_flag_only_applies_from_its_season_on() -> None:
    rows = [_telecast_row(season=2024)]
    build = _build_telecast_build(rows, {})
    viewership = build_viewership(build, _ERAS)

    telecasts, _dis, _era_dis, flags = apply_headlines(
        build.telecasts, viewership, build.records_by_telecast, _ERAS, _EVENT_FLAGS
    )

    assert telecasts.row(0, named=True)["model_break"] is False
    assert "model_break" not in set(flags["kind"].to_list())


# -- era disagreement rows ----------------------------------------------------------------------


def test_era_disagreement_rows_reflect_viewership_disagreements() -> None:
    record = _record(
        record_id="cfb-example-sample-2025-09-13",
        claims=[_claim(claim_id="c-final", era_id="rr-era-a")],  # disagrees with era-late
    )
    rows = [_telecast_row()]
    build = _build_telecast_build(rows, {"1-alpha": [record]})
    viewership = build_viewership(build, _ERAS)

    _telecasts, _dis, era_disagreements, _flags = apply_headlines(
        build.telecasts, viewership, build.records_by_telecast, _ERAS, _EVENT_FLAGS
    )

    assert len(era_disagreements) == 1
    assert era_disagreements[0]["claim_id"] == "c-final"
    assert era_disagreements[0]["era_id"] == "era-late"
    assert era_disagreements[0]["rr_era_id"] == "rr-era-a"


# -- plotted rule (D-10) -------------------------------------------------------------------------


def test_plotted_true_for_rated_main_telecast_with_headline() -> None:
    record = _record(record_id="cfb-example-sample-2025-09-13", claims=[_claim(claim_id="c-final")])
    rows = [_telecast_row(rated=True, feed_type="main")]
    build = _build_telecast_build(rows, {"1-alpha": [record]})
    viewership = build_viewership(build, _ERAS)

    telecasts, *_ = apply_headlines(
        build.telecasts, viewership, build.records_by_telecast, _ERAS, _EVENT_FLAGS
    )

    assert telecasts.row(0, named=True)["plotted"] is True


def test_plotted_false_for_spanish_feed_telecast_even_with_headline() -> None:
    record = _record(record_id="cfb-example-sample-2025-09-13", claims=[_claim(claim_id="c-final")])
    rows = [_telecast_row(rated=True, feed_type="spanish", telecast_id="1-alpha-es")]
    build = _build_telecast_build(rows, {"1-alpha-es": [record]})
    viewership = build_viewership(build, _ERAS)

    telecasts, *_ = apply_headlines(
        build.telecasts, viewership, build.records_by_telecast, _ERAS, _EVENT_FLAGS
    )

    assert telecasts.row(0, named=True)["plotted"] is False


def test_plotted_false_when_rated_but_no_headline_claim() -> None:
    record = _record(
        record_id="cfb-example-sample-2025-09-13",
        claims=[_claim(claim_id="c-peak", metric_type="peak_audience")],
    )
    rows = [_telecast_row(rated=True, feed_type="main")]
    build = _build_telecast_build(rows, {"1-alpha": [record]})
    viewership = build_viewership(build, _ERAS)

    telecasts, *_ = apply_headlines(
        build.telecasts, viewership, build.records_by_telecast, _ERAS, _EVENT_FLAGS
    )

    assert telecasts.row(0, named=True)["plotted"] is False


def test_plotted_false_for_unrated_telecast() -> None:
    rows = [_telecast_row(rated=False, feed_type="main")]
    build = _build_telecast_build(rows, {})
    viewership = build_viewership(build, _ERAS)

    telecasts, *_ = apply_headlines(
        build.telecasts, viewership, build.records_by_telecast, _ERAS, _EVENT_FLAGS
    )

    assert telecasts.row(0, named=True)["plotted"] is False


# -- CR-02: null/non-positive claims never plot ------------------------------------------------


def test_plotted_false_when_only_claim_has_null_value() -> None:
    record = _record(
        record_id="cfb-example-sample-2025-09-13",
        claims=[_claim(claim_id="c-null", value=None)],
    )
    rows = [_telecast_row(rated=True, feed_type="main")]
    build = _build_telecast_build(rows, {"1-alpha": [record]})
    viewership = build_viewership(build, _ERAS)

    telecasts, *_ = apply_headlines(
        build.telecasts, viewership, build.records_by_telecast, _ERAS, _EVENT_FLAGS
    )

    row = telecasts.row(0, named=True)
    assert row["plotted"] is False
    assert row["headline_value"] is None
    assert viewership["is_headline"].to_list() == [False]


def test_null_top_ranked_claim_loses_to_lower_ranked_claim_with_a_value() -> None:
    record = _record(
        record_id="cfb-example-sample-2025-09-13",
        claims=[
            _claim(claim_id="c-revised", status="revised", value=None),
            _claim(claim_id="c-final", status="final", value=4_000_000.0),
        ],
    )
    rows = [_telecast_row(rated=True, feed_type="main")]
    build = _build_telecast_build(rows, {"1-alpha": [record]})
    viewership = build_viewership(build, _ERAS)

    telecasts, *_ = apply_headlines(
        build.telecasts, viewership, build.records_by_telecast, _ERAS, _EVENT_FLAGS
    )

    row = telecasts.row(0, named=True)
    assert row["plotted"] is True
    assert row["headline_claim_id"] == "c-final"
    assert row["headline_value"] == 4_000_000.0
