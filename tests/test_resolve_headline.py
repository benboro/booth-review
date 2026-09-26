"""Tests for resolve/headline.py: the RR headline-figure rule (HEADLINE_RULE,
select_headline), promoted from spike/headline.py in Phase 3 (JOIN-04), plus
compare_with_rr_current, which compares HEADLINE_RULE's pick against RR's own
current-figure pick (RRRecord.rr_current_claim_id).
"""

from __future__ import annotations

from booth_review.resolve.headline import HEADLINE_RULE, compare_with_rr_current, select_headline
from booth_review.sources.ratingsref.parser import RRClaim, RRRecord, RRTelecast


def _claim(
    *,
    claim_id: str,
    status: str = "final",
    value: float = 2000000.0,
    metric_type: str = "avg_audience",
    unit: str | None = "viewers",
    supersedes_id: str | None = None,
    figure_type: str | None = "currency",
    confidence: float | None = 1.0,
    first_published: str | None = "2025-09-16",
) -> RRClaim:
    claim = RRClaim.model_validate(
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
        }
    )
    return claim


# -- headline.select_headline ---------------------------------------------------------


def test_headline_rule_constant_is_documented() -> None:
    assert "avg_audience" in HEADLINE_RULE
    assert "supersedes_id" in HEADLINE_RULE


def test_select_headline_prefers_final_over_later_preliminary() -> None:
    final = _claim(claim_id="c-final", status="final", value=13990000, first_published="2025-09-15")
    preliminary = _claim(
        claim_id="c-prelim", status="preliminary", value=14150000, first_published="2025-09-18"
    )
    chosen = select_headline([final, preliminary])
    assert chosen is not None
    assert chosen.value == 13990000


def test_select_headline_ignores_peak_audience() -> None:
    avg = _claim(claim_id="c-avg", value=2000000)
    peak = _claim(claim_id="c-peak", metric_type="peak_audience", value=2600000)
    chosen = select_headline([avg, peak])
    assert chosen is not None
    assert chosen.metric_type == "avg_audience"


def test_select_headline_prefers_revised_over_final() -> None:
    final = _claim(claim_id="c-final", status="final", value=2000000)
    revised = _claim(claim_id="c-revised", status="revised", value=2100000)
    chosen = select_headline([final, revised])
    assert chosen is not None
    assert chosen.status == "revised"


def test_select_headline_drops_superseded_claim() -> None:
    old = _claim(claim_id="c-old", status="preliminary", value=1500000)
    new = _claim(claim_id="c-new", status="final", value=1550000, supersedes_id="c-old")
    chosen = select_headline([old, new])
    assert chosen is not None
    assert chosen.value == 1550000


def test_select_headline_returns_none_without_an_eligible_claim() -> None:
    peak_only = _claim(claim_id="c-peak", metric_type="peak_audience", value=2600000)
    assert select_headline([peak_only]) is None


def test_select_headline_prefers_currency_over_other_figure_types() -> None:
    non_currency = _claim(claim_id="c-a", status="final", figure_type="self_report", value=1000000)
    currency = _claim(claim_id="c-b", status="final", figure_type="currency", value=1100000)
    chosen = select_headline([non_currency, currency])
    assert chosen is not None
    assert chosen.value == 1100000


# -- headline.compare_with_rr_current ---------------------------------------------------


def _record_with_rr_current(
    *, rr_current_claim_id: str | None, rr_current_status: str = "found"
) -> RRRecord:
    return RRRecord(
        telecast=RRTelecast(
            id="cfb-example-sample-2025-09-13",
            event_date="2025-09-13",  # type: ignore[arg-type]
            teams=["cfb-example", "cfb-sample"],
        ),
        claims=[],
        rr_current_claim_id=rr_current_claim_id,
        rr_current_status=rr_current_status,  # type: ignore[arg-type]
    )


def test_compare_with_rr_current_agrees_when_ids_match() -> None:
    headline = _claim(claim_id="c-agree")
    record = _record_with_rr_current(rr_current_claim_id="c-agree")
    assert compare_with_rr_current(headline, record) == "agree"


def test_compare_with_rr_current_disagrees_when_ids_differ() -> None:
    headline = _claim(claim_id="c-headline")
    record = _record_with_rr_current(rr_current_claim_id="c-rr-current")
    assert compare_with_rr_current(headline, record) == "disagree"


def test_compare_with_rr_current_not_comparable_when_headline_is_none() -> None:
    record = _record_with_rr_current(rr_current_claim_id="c-rr-current")
    assert compare_with_rr_current(None, record) == "not_comparable"


def test_compare_with_rr_current_not_comparable_when_rr_current_is_none() -> None:
    headline = _claim(claim_id="c-headline")
    record = _record_with_rr_current(rr_current_claim_id=None, rr_current_status="no_peers")
    assert compare_with_rr_current(headline, record) == "not_comparable"
