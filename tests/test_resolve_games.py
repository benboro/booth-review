"""Tests for resolve/games.py: match_506, match_rr, and is_fbs_game, and
resolve/crew.py's resolve_crew, all promoted from spike/join.py in Phase 3
(JOIN-02, JOIN-03, JOIN-07).

Fixtures: tests/fixtures/spike/506_wk-*.html (invented crews and matchups,
D-07).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from booth_review.resolve.crew import resolve_crew
from booth_review.resolve.games import is_fbs_game, match_506, match_rr
from booth_review.sources.cfbd.parser import CfbdGame
from booth_review.sources.ratingsref.parser import RRClaim, RRRecord, RRTelecast
from booth_review.sources.sports506.parser import parse_week_page

FIXTURES = Path(__file__).parent / "fixtures" / "spike"


def _game(
    game_id: int,
    *,
    away: str,
    home: str,
    start_et_iso: str,
    neutral: bool = False,
    notes: str | None = None,
    home_classification: str | None = "fbs",
    away_classification: str | None = "fbs",
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
        home_classification=home_classification,
        home_conference="Example Conference",
        home_points=27,
        away_id=None,
        away_team=away,
        away_classification=away_classification,
        away_conference="Example Conference",
        away_points=20,
        excitement_index=5.0,
        notes=notes,
    )


def _week_listings(name: str, label: str) -> list:
    return parse_week_page((FIXTURES / name).read_bytes(), season=2025, week_label=label)


# -- games.match_506 --------------------------------------------------------------------


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


# -- games.match_rr ----------------------------------------------------------------------


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


# -- games.is_fbs_game --------------------------------------------------------------------


def test_is_fbs_game_true_when_either_side_is_fbs() -> None:
    home_fbs = _game(
        1,
        away="Example",
        home="Sample",
        start_et_iso="2025-09-13T12:00:00-04:00",
        home_classification="fbs",
        away_classification="fcs",
    )
    away_fbs = _game(
        2,
        away="Example",
        home="Sample",
        start_et_iso="2025-09-13T12:00:00-04:00",
        home_classification="fcs",
        away_classification="fbs",
    )
    assert is_fbs_game(home_fbs) is True
    assert is_fbs_game(away_fbs) is True


def test_is_fbs_game_false_for_fcs_vs_fcs() -> None:
    game = _game(
        3,
        away="Example",
        home="Sample",
        start_et_iso="2025-09-13T12:00:00-04:00",
        home_classification="fcs",
        away_classification="fcs",
    )
    assert is_fbs_game(game) is False


def test_is_fbs_game_false_when_both_classifications_are_none() -> None:
    game = _game(
        4,
        away="Example",
        home="Sample",
        start_et_iso="2025-09-13T12:00:00-04:00",
        home_classification=None,
        away_classification=None,
    )
    assert is_fbs_game(game) is False


# -- crew.resolve_crew --------------------------------------------------------------------


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
