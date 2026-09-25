"""RR headline-figure selection (D-06, SPIKE-02).

One documented, unit-tested rule instead of "most recent" or "follow
supersedes_id alone" (Pitfall 1: a later preliminary figure is not the right
pick over an earlier final one). Reads the claim id from `model_extra["id"]`,
the key name found in the real Ratings Reference inventory (01-11).
"""

from __future__ import annotations

from booth_review.sources.ratingsref.parser import RRClaim

HEADLINE_RULE = (
    "Headline figure: among claims with metric_type == 'avg_audience' and "
    "unit == 'viewers', drop any claim that appears as another claim's "
    "supersedes_id, then rank the rest by status (revised > final > "
    "preliminary > any other status), then by figure_type (currency over "
    "any other figure_type), then by higher confidence, then by the latest "
    "first_published. The top-ranked claim after those tie-breaks is the "
    "headline claim; ties on every field keep the first one encountered."
)

_STATUS_RANK: dict[str, int] = {"revised": 0, "final": 1, "preliminary": 2}


def _claim_id(claim: RRClaim) -> str | None:
    extra = claim.model_extra or {}
    value = extra.get("id")
    return value if isinstance(value, str) else None


def _rank_key(claim: RRClaim) -> tuple[int, int, float]:
    status_rank = _STATUS_RANK.get(claim.status, 3)
    extra = claim.model_extra or {}
    currency_rank = 0 if extra.get("figure_type") == "currency" else 1
    confidence_rank = -(claim.confidence if claim.confidence is not None else 0.0)
    return (status_rank, currency_rank, confidence_rank)


def select_headline(claims: list[RRClaim]) -> RRClaim | None:
    """Pick the one claim HEADLINE_RULE names, or None when no eligible
    avg_audience/viewers claim exists.
    """
    superseded_ids = {claim.supersedes_id for claim in claims if claim.supersedes_id is not None}
    eligible = [
        claim
        for claim in claims
        if claim.metric_type == "avg_audience"
        and claim.unit == "viewers"
        and _claim_id(claim) not in superseded_ids
    ]
    if not eligible:
        return None

    best_key = min(_rank_key(claim) for claim in eligible)
    tied = [claim for claim in eligible if _rank_key(claim) == best_key]
    tied.sort(key=lambda claim: claim.first_published or "", reverse=True)
    return tied[0]
