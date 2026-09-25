"""Tests for spike/headline.py (the RR headline-figure rule) and the matching
part of spike/join.py (match_506, match_rr, resolve_crew).

Task 2 appends build_join_rows/write_outputs/finalize/CLI tests below the
matching-part tests. All RRClaim/RRRecord/Listing506/CfbdGame fixtures are
either constructed directly in this file or loaded from
tests/fixtures/spike/ (invented teams, people, and figures only; D-07).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from booth_review.sources.cfbd.parser import CfbdGame
from booth_review.sources.ratingsref.parser import RRClaim, RRRecord, RRTelecast
from booth_review.sources.sports506.parser import parse_week_page
from booth_review.spike.headline import HEADLINE_RULE, select_headline
from booth_review.spike.join import match_506, match_rr, resolve_crew

FIXTURES = Path(__file__).parent / "fixtures" / "spike"


def _game(
    game_id: int,
    *,
    away: str,
    home: str,
    start_et_iso: str,
    neutral: bool = False,
    notes: str | None = None,
) -> CfbdGame:
    """A minimal synthetic CfbdGame; `start_et_iso` is an ET-local ISO string
    (e.g. "2025-09-13T12:00:00-04:00") converted to UTC, matching how the
    real parser stores start_date.
    """
    start = datetime.fromisoformat(start_et_iso).astimezone(UTC)
    return CfbdGame(
        id=game_id,
        season=2025,
        week=1,
        season_type="regular",
        start_date=start,
        start_time_tbd=False,
        completed=True,
        neutral_site=neutral,
        conference_game=not neutral,
        venue="Example Field",
        home_id=None,
        home_team=home,
        home_classification="fbs",
        home_conference="Example Conference",
        home_points=27,
        away_id=None,
        away_team=away,
        away_classification="fbs",
        away_conference="Example Conference",
        away_points=20,
        excitement_index=5.0,
        notes=notes,
    )


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


# -- join.match_506 --------------------------------------------------------------------


def _week_listings(name: str, label: str) -> list:
    return parse_week_page((FIXTURES / name).read_bytes(), season=2025, week_label=label)


def test_match_506_exact_on_team_pair_and_date() -> None:
    listings = _week_listings("506_wk-01.html", "1")
    game = _game(
        500003, away="Boulderpass", home="Cedarhollow", start_et_iso="2025-08-30T12:00:00-04:00"
    )
    result = match_506(game, listings)
    assert result.confidence == "exact"
    assert len(result.listings) == 1


def test_match_506_date_shift_within_one_day() -> None:
    listings = _week_listings("506_wk-01.html", "1")
    game = _game(
        500008, away="Northfield", home="Ironpeak", start_et_iso="2025-08-30T15:00:00-04:00"
    )
    result = match_506(game, listings)
    assert result.confidence == "date-shift"
    assert len(result.listings) == 1


def test_match_506_partial_on_shared_tokens() -> None:
    listings = _week_listings("506_wk-01.html", "1")
    game = _game(
        500026, away="Highcliff", home="Lakeview", start_et_iso="2025-09-06T12:00:00-04:00"
    )
    result = match_506(game, listings)
    assert result.confidence == "partial"
    assert len(result.listings) == 1


def test_match_506_none_when_nothing_is_nearby() -> None:
    listings = _week_listings("506_wk-01.html", "1")
    game = _game(999999, away="Zzyzx", home="Qanat", start_et_iso="2025-07-01T12:00:00-04:00")
    result = match_506(game, listings)
    assert result.confidence == "none"
    assert result.listings == ()


def test_match_506_returns_every_feed_of_the_matched_game() -> None:
    listings = _week_listings("506_wk-B.html", "B")
    game = _game(
        500007,
        away="Thornfield",
        home="Ravenwood",
        start_et_iso="2026-01-19T19:30:00-05:00",
        neutral=True,
        notes="CFP National Championship",
    )
    result = match_506(game, listings)
    assert result.confidence == "exact"
    assert len(result.listings) == 3
    assert {ln.feed_kind for ln in result.listings} == {"main", "alt", "spanish"}


def test_match_506_ambiguous_when_several_games_qualify_as_partial() -> None:
    week_html = (
        b'<html><body><div id="content"><div class="inner"><article>'
        b"<h3>SATURDAY, SEPTEMBER 6</h3>"
        b'<div id="cgame"><div id="cmatchup">Example Falcons @ Sample Prep</div>'
        b'<div id="ctime">1:00 PM</div><div id="cntwk">ECN</div><div id="canncrs">A B</div></div>'
        b'<div id="cgame"><div id="cmatchup">Example Ridge @ Sample Vale</div>'
        b'<div id="ctime">4:00 PM</div><div id="cntwk">ECN</div><div id="canncrs">C D</div></div>'
        b"</article></div></div></body></html>"
    )
    listings = parse_week_page(week_html, season=2025, week_label="2")
    # Both listings share the "example"/"sample" tokens with this game's teams,
    # so two distinct games qualify as a partial match.
    game = _game(700001, away="Example", home="Sample", start_et_iso="2025-09-06T12:00:00-04:00")
    result = match_506(game, listings)
    assert result.confidence == "ambiguous"
    assert result.listings == ()


# -- join.match_rr ----------------------------------------------------------------------


def _rr_record(
    telecast_id: str,
    *,
    event_date: str,
    teams: list[str],
    networks: list[str],
    claims: list[RRClaim] | None = None,
) -> RRRecord:
    return RRRecord(
        telecast=RRTelecast(
            id=telecast_id,
            event_date=event_date,  # type: ignore[arg-type]
            title=telecast_id,
            networks=networks,
            teams=teams,
            kind="game",
            tier=2,
        ),
        claims=claims or [],
    )


def test_match_rr_exact_on_team_pair_and_date() -> None:
    record = _rr_record(
        "cfb-example-sample-2025-09-13",
        event_date="2025-09-13",
        teams=["cfb-example", "cfb-sample"],
        networks=["ESPN"],
    )
    game = _game(1, away="Example", home="Sample", start_et_iso="2025-09-13T12:00:00-04:00")
    result = match_rr(game, [record])
    assert result.confidence == "exact"
    assert result.records == (record,)


def test_match_rr_keeps_duplicate_records() -> None:
    record_a = _rr_record(
        "cfb-example-sample-2025-09-13",
        event_date="2025-09-13",
        teams=["cfb-example", "cfb-sample"],
        networks=["ESPN"],
    )
    record_b = _rr_record(
        "cfb-sample-example-2025-09-13",
        event_date="2025-09-13",
        teams=["cfb-sample", "cfb-example"],
        networks=["ESPN"],
    )
    game = _game(1, away="Example", home="Sample", start_et_iso="2025-09-13T12:00:00-04:00")
    result = match_rr(game, [record_a, record_b])
    assert result.confidence == "exact"
    assert len(result.records) == 2


def test_match_rr_date_shift() -> None:
    record = _rr_record(
        "cfb-example-sample-2025-09-14",
        event_date="2025-09-14",
        teams=["cfb-example", "cfb-sample"],
        networks=["ESPN"],
    )
    game = _game(1, away="Example", home="Sample", start_et_iso="2025-09-13T12:00:00-04:00")
    result = match_rr(game, [record])
    assert result.confidence == "date-shift"


def test_match_rr_partial_on_shared_tokens() -> None:
    record = _rr_record(
        "cfb-example-ridge-sample-vale-2025-09-13",
        event_date="2025-09-13",
        teams=["cfb-example-ridge", "cfb-sample-vale"],
        networks=["ESPN"],
    )
    game = _game(1, away="Example", home="Sample", start_et_iso="2025-09-13T12:00:00-04:00")
    result = match_rr(game, [record])
    assert result.confidence == "partial"


def test_match_rr_none_when_nothing_matches() -> None:
    record = _rr_record(
        "cfb-other-team-another-team-2025-01-01",
        event_date="2025-01-01",
        teams=["cfb-other-team", "cfb-another-team"],
        networks=["ESPN"],
    )
    game = _game(1, away="Example", home="Sample", start_et_iso="2025-09-13T12:00:00-04:00")
    result = match_rr(game, [record])
    assert result.confidence == "none"
    assert result.records == ()


# -- join.resolve_crew ------------------------------------------------------------------


def test_resolve_crew_prefers_main_feed_matching_rr_network() -> None:
    listings = _week_listings("506_wk-B.html", "B")
    game_listings = [ln for ln in listings if ln.away_raw == "Thornfield"]
    result = resolve_crew(game_listings, ["ESPN", "ESPN2", "ESPNU"])
    assert result.crew == "Chris Fielding, Jordan Sample, Casey Vale"
    assert "alt" in result.notes
    assert "spanish" in result.notes


def test_resolve_crew_falls_back_to_first_main_listing() -> None:
    listings = _week_listings("506_wk-01.html", "1")
    game_listings = [ln for ln in listings if ln.away_raw == "Boulderpass"]
    result = resolve_crew(game_listings, ["SOME OTHER NETWORK"])
    assert result.crew == "Pat Example, J.D. Case Jr."
