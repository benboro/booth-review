"""Crew resolution for a matched CFBD game's 506 listing(s), promoted from
the Phase 1 spike (D-06) into booth_review.resolve for Phase 3's join layer
(JOIN-03).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from booth_review.sources.sports506.parser import Listing506


@dataclass(frozen=True)
class CrewResolution:
    crew: str | None
    matched_listing: Listing506 | None
    notes: str


def resolve_crew(listings: Sequence[Listing506], rr_networks: Sequence[str]) -> CrewResolution:
    """Pick the main-feed listing whose network matches one of `rr_networks`
    (case-insensitive); else the first main-feed listing. Alt and Spanish
    feeds are never the resolved crew; they go into notes.
    """
    main_listings = [ln for ln in listings if ln.feed_kind == "main"]
    other_listings = [ln for ln in listings if ln.feed_kind != "main"]

    rr_networks_lower = {n.lower() for n in rr_networks}
    matched = next(
        (
            ln
            for ln in main_listings
            if ln.network_raw and ln.network_raw.lower() in rr_networks_lower
        ),
        None,
    )
    chosen = matched if matched is not None else (main_listings[0] if main_listings else None)

    notes = "; ".join(
        f"{ln.feed_kind}: {ln.network_raw or '(no network)'} ({ln.crew_raw or 'no crew listed'})"
        for ln in other_listings
    )
    crew = chosen.crew_raw if chosen is not None else None
    return CrewResolution(crew=crew, matched_listing=chosen, notes=notes)
