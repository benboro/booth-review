"""The viewership table (JOIN-04) and headline/era/flag application: every
claim of every RR record merged into a telecast, the headline figure
HEADLINE_RULE picks over the telecast's pooled claims, the RR
current-figure disagreement log, era/measurement-type/model-break/combined
flags, and the plotted rule (D-10).

Every figure is kept (`build_viewership`); `apply_headlines` then fills each
telecast's headline/era/measurement/flag columns from the same pooled claims
and returns the disagreement rows and per-telecast flag rows for the caller
to write.

Second-source figures (04.19 D-09) are rows too, tagged by `source`; the
headline comes from `select_headline_across_sources`, and the RR-only
bookkeeping (rr_current_check, disagreement log, nielsen_adobe flag) applies
only when the headline is an RR claim.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from types import MappingProxyType

import polars as pl

from booth_review.build.telecasts import TelecastBuild
from booth_review.flags.era import MeasurementEra, era_check, era_for
from booth_review.flags.events import EventFlag, event_flags_for
from booth_review.flags.measurement_type import measurement_type
from booth_review.resolve.headline import (
    claim_id,
    claim_source,
    compare_with_rr_current,
    is_usable_value,
    rank_key,
    select_headline_across_sources,
)
from booth_review.sources.ratingsref.parser import RRClaim, RRRecord

VIEWERSHIP_SCHEMA: dict[str, pl.DataType] = {
    "telecast_id": pl.Utf8(),
    "source": pl.Utf8(),
    "rr_telecast_id": pl.Utf8(),
    "record_url": pl.Utf8(),
    "claim_id": pl.Utf8(),
    "metric_type": pl.Utf8(),
    "status": pl.Utf8(),
    "value": pl.Float64(),
    "unit": pl.Utf8(),
    "cut": pl.Utf8(),
    "figure_type": pl.Utf8(),
    "publisher": pl.Utf8(),
    "source_url": pl.Utf8(),
    "first_published": pl.Utf8(),
    "confidence": pl.Float64(),
    "rr_era_id": pl.Utf8(),
    "measured_by": pl.Utf8(),
    "measurement_type": pl.Utf8(),
    "era_id": pl.Utf8(),
    "era_check": pl.Utf8(),
    "is_headline": pl.Boolean(),
    "is_rr_current": pl.Boolean(),
    "carrier_network": pl.Utf8(),
    "composite_of": pl.List(pl.Utf8()),
}

# One row per (telecast, flag): the flag ids build.viewership.apply_headlines
# discovers (era, event, model_break, measurement, combined). Co-located here
# rather than in build.tables (which re-exports it) since apply_headlines,
# not tables.py, is what builds these rows -- putting the schema in tables.py
# instead would need a tables -> viewership -> tables import cycle.
TELECAST_FLAGS_SCHEMA: dict[str, pl.DataType] = {
    "telecast_id": pl.Utf8(),
    "flag_id": pl.Utf8(),
    "kind": pl.Utf8(),
}

_MEASUREMENT_FLAG_ID = "nielsen_adobe"
_COMBINED_FLAG_ID = "combined"


def _figure_type(claim: RRClaim) -> str | None:
    extra = claim.model_extra or {}
    value = extra.get("figure_type")
    return value if isinstance(value, str) else None


def _pooled_claims(records: Sequence[RRRecord]) -> list[RRClaim]:
    return [claim for record in records for claim in record.claims]


_NO_SECOND_CLAIMS: Mapping[str, Sequence[RRClaim]] = MappingProxyType({})


def build_viewership(
    telecast_build: TelecastBuild,
    eras: Sequence[MeasurementEra],
    second_claims_by_telecast: Mapping[str, Sequence[RRClaim]] = _NO_SECOND_CLAIMS,
) -> pl.DataFrame:
    """One row per claim of every RR record merged into a telecast plus one
    per loaded second-source claim (all figures kept), with `is_headline` True
    on the one claim the headline rules pick per telecast (JOIN-04) and
    `is_rr_current` reporting whether that claim is RR's own current pick,
    null when RR's pick isn't "found" (research Assumption A3).
    """
    telecast_dates: dict[str, date] = {
        row["telecast_id"]: row["date_et"]
        for row in telecast_build.telecasts.select("telecast_id", "date_et").iter_rows(named=True)
    }

    rows: list[dict[str, object]] = []
    telecast_ids = sorted(set(telecast_build.records_by_telecast) | set(second_claims_by_telecast))
    for telecast_id in telecast_ids:
        records = telecast_build.records_by_telecast.get(telecast_id, [])
        second_claims = second_claims_by_telecast.get(telecast_id, ())
        telecast_date = telecast_dates.get(telecast_id)
        era = era_for(telecast_date, eras) if telecast_date is not None else None

        pooled = _pooled_claims(records)
        picked = select_headline_across_sources(pooled, second_claims)
        headline_id = claim_id(picked[0]) if picked is not None else None

        def row_for(
            claim: RRClaim,
            *,
            source: str,
            rr_telecast_id: str | None,
            record_url: str | None,
            is_current: bool | None,
            telecast_id: str = telecast_id,
            era: MeasurementEra | None = era,
            headline_id: str | None = headline_id,
        ) -> dict[str, object]:
            this_claim_id = claim_id(claim)
            return {
                "telecast_id": telecast_id,
                "source": source,
                "rr_telecast_id": rr_telecast_id,
                "record_url": record_url,
                "claim_id": this_claim_id,
                "metric_type": claim.metric_type,
                "status": claim.status,
                "value": claim.value,
                "unit": claim.unit,
                "cut": claim.cut,
                "figure_type": _figure_type(claim),
                "publisher": claim.publisher,
                "source_url": claim.source_url,
                "first_published": claim.first_published,
                "confidence": claim.confidence,
                "rr_era_id": claim.era_id,
                "measured_by": claim.measured_by,
                "measurement_type": measurement_type(claim.measured_by),
                "era_id": era.era_id if era is not None else None,
                "era_check": (
                    era_check(era, claim.era_id) if era is not None else "not_comparable"
                ),
                "is_headline": headline_id is not None and this_claim_id == headline_id,
                "is_rr_current": is_current,
                "carrier_network": claim.carrier_network,
                "composite_of": claim.composite_of,
            }

        for record in records:
            for claim in record.claims:
                is_current: bool | None
                if record.rr_current_status != "found":
                    is_current = None
                else:
                    is_current = claim_id(claim) == record.rr_current_claim_id
                rows.append(
                    row_for(
                        claim,
                        source="rr",
                        rr_telecast_id=record.telecast.id,
                        record_url=record.record_url,
                        is_current=is_current,
                    )
                )
        for claim in second_claims:
            rows.append(
                row_for(
                    claim,
                    source=claim_source(claim),
                    rr_telecast_id=None,
                    record_url=None,
                    is_current=None,
                )
            )

    frame = pl.DataFrame(rows, schema=VIEWERSHIP_SCHEMA)
    if frame.height:
        frame = frame.sort(["telecast_id", "claim_id"])
    return frame


def apply_headlines(
    telecasts: pl.DataFrame,
    viewership: pl.DataFrame,
    records_by_telecast: Mapping[str, Sequence[RRRecord]],
    eras: Sequence[MeasurementEra],
    event_flags: Sequence[EventFlag],
    second_claims_by_telecast: Mapping[str, Sequence[RRClaim]] = _NO_SECOND_CLAIMS,
) -> tuple[pl.DataFrame, list[dict[str, object]], list[dict[str, object]], pl.DataFrame]:
    """Fill every telecast's headline/era/measurement/flag columns from its
    pooled claims (JOIN-04, FLAG-01..04, D-10) and return
    (telecasts, headline_disagreement_rows, era_disagreement_rows,
    telecast_flags).
    """
    disagreement_rows: list[dict[str, object]] = []
    telecast_flag_rows: list[dict[str, object]] = []
    updated_rows: list[dict[str, object]] = []

    flags_by_id = {flag.flag_id: flag for flag in event_flags}

    for row in telecasts.iter_rows(named=True):
        updated = dict(row)
        telecast_id = updated["telecast_id"]
        date_et = updated["date_et"]
        season = updated["season"]
        network_id = updated["network_id"]

        era = era_for(date_et, eras)
        updated["era_id"] = era.era_id
        telecast_flag_rows.append(
            {"telecast_id": telecast_id, "flag_id": era.era_id, "kind": "era"}
        )

        model_break = False
        for flag_id in event_flags_for(date_et, season, network_id, event_flags):
            flag = flags_by_id[flag_id]
            telecast_flag_rows.append(
                {"telecast_id": telecast_id, "flag_id": flag_id, "kind": flag.kind}
            )
            if flag.kind == "model_break":
                model_break = True
        updated["model_break"] = model_break

        records = records_by_telecast.get(telecast_id, [])
        pooled = _pooled_claims(records)
        picked = select_headline_across_sources(
            pooled, second_claims_by_telecast.get(telecast_id, ())
        )
        headline = picked[0] if picked is not None else None

        if headline is None or picked is None:
            updated["rr_current_check"] = None
        else:
            updated["headline_source"] = picked[1]
            updated["headline_claim_id"] = claim_id(headline)
            updated["headline_value"] = headline.value
            updated["headline_publisher"] = headline.publisher
            updated["headline_source_url"] = headline.source_url
            updated["measurement_type"] = measurement_type(headline.measured_by)
            if picked[1] == "rr" and updated["measurement_type"] == "nielsen_adobe":
                telecast_flag_rows.append(
                    {
                        "telecast_id": telecast_id,
                        "flag_id": _MEASUREMENT_FLAG_ID,
                        "kind": "measurement",
                    }
                )

            owning_record = (
                next((r for r in records if headline in r.claims), None)
                if picked[1] == "rr"
                else None
            )
            if owning_record is not None:
                check = compare_with_rr_current(headline, owning_record)
                updated["rr_current_check"] = check
                if check == "disagree":
                    rr_current_claim = next(
                        (
                            c
                            for c in owning_record.claims
                            if claim_id(c) == owning_record.rr_current_claim_id
                        ),
                        None,
                    )
                    reason = "rule_difference"
                    if rr_current_claim is not None and rank_key(headline) == rank_key(
                        rr_current_claim
                    ):
                        reason = "same_rank_key"
                    disagreement_rows.append(
                        {
                            "telecast_id": telecast_id,
                            "rr_telecast_id": owning_record.telecast.id,
                            "headline_claim_id": claim_id(headline),
                            "rr_current_claim_id": owning_record.rr_current_claim_id,
                            "reason": reason,
                        }
                    )
            else:
                updated["rr_current_check"] = None

        if updated["combined_feeds"] is not None:
            telecast_flag_rows.append(
                {"telecast_id": telecast_id, "flag_id": _COMBINED_FLAG_ID, "kind": "combined"}
            )

        updated["plotted"] = bool(
            updated["rated"]
            and updated["feed_type"] == "main"
            and headline is not None
            and is_usable_value(headline.value)
        )

        updated_rows.append(updated)

    updated_telecasts = pl.DataFrame(updated_rows, schema=dict(telecasts.schema))
    if updated_telecasts.height:
        updated_telecasts = updated_telecasts.sort("telecast_id")

    era_disagreement_rows: list[dict[str, object]] = [
        {
            "telecast_id": row["telecast_id"],
            "rr_telecast_id": row["rr_telecast_id"],
            "claim_id": row["claim_id"],
            "era_id": row["era_id"],
            "rr_era_id": row["rr_era_id"],
        }
        for row in viewership.filter(pl.col("era_check") == "disagree").iter_rows(named=True)
    ]

    telecast_flags = pl.DataFrame(telecast_flag_rows, schema=TELECAST_FLAGS_SCHEMA)
    if telecast_flags.height:
        telecast_flags = telecast_flags.sort(["telecast_id", "flag_id"])

    return updated_telecasts, disagreement_rows, era_disagreement_rows, telecast_flags
