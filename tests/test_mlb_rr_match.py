"""Ratings Reference MLB record match on synthetic data (invented clubs and ids)."""

from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path

import polars as pl
from mlb_games_support import build_reference

from booth_review.flags.era import MeasurementEra
from booth_review.mlb.games import GAME_SCHEMA
from booth_review.mlb.listings import game_key
from booth_review.mlb.reference import MlbNetworkRow, MlbTeamCrosswalkRow
from booth_review.mlb.rr_match import MLB_RR_CAUSES, RRGameMatch, RRReview, match_mlb_rr
from booth_review.mlb.teams import MlbNetworkResolver, MlbTeamResolver
from booth_review.sources.ratingsref.parser import RRRecord

ERAS = [
    MeasurementEra(
        "era-a", "A", None, date(2025, 8, 31), frozenset({"rr-a"}), "https://example.org/e", ""
    ),
    MeasurementEra(
        "era-b", "B", date(2025, 9, 1), None, frozenset({"rr-b"}), "https://example.org/e", ""
    ),
]
CLAIM = {
    "id": "c1",
    "metric_type": "avg_audience",
    "status": "final",
    "value": 5_000_000,
    "unit": "viewers",
    "cut": "full_telecast",
    "era_id": "rr-b",
    "measured_by": "Fixture Panel",
    "source_url": "https://example.org/figure",
}


def resolvers(tmp_path: Path) -> tuple[MlbTeamResolver, MlbNetworkResolver]:
    ref = build_reference(tmp_path / "ref")
    rows = tuple(
        MlbTeamCrosswalkRow("ratingsref", v, c, None, None, "")
        for v, c in (
            ("aces", "alpha"),
            ("bravos", "bravo"),
            ("red-sox", "charlie"),
            ("dragons", "delta"),
        )
    )
    ref = dataclasses.replace(
        ref,
        crosswalk=ref.crosswalk + rows,
        networks=(*ref.networks, MlbNetworkRow("ratingsref", "Apple TV+", "apple", "apple", "")),
    )
    return MlbTeamResolver.from_reference(ref), MlbNetworkResolver.from_reference(ref)


def games(*specs: tuple[date, str, str, int]) -> pl.DataFrame:
    rows = [
        {
            "game_key": game_key(d, a, h, n),
            "season": d.year,
            "game_date": d,
            "away_club": a,
            "home_club": h,
            "game_number": n,
            "round": None,
            "series_league": None,
            "series_game": None,
            "neutral": False,
            "venue_note": None,
            "retrosheet_gid": None,
            "home_won": None,
            "away_score": None,
            "home_score": None,
        }
        for d, a, h, n in specs
    ]
    return pl.DataFrame(rows, schema=dict(GAME_SCHEMA))


def record(slug: str, day: str, *, claims=(), networks=(), teams=()) -> RRRecord:
    return RRRecord.model_validate(
        {
            "telecast": {
                "id": slug,
                "event_date": day,
                "teams": list(teams),
                "networks": list(networks),
                "title": "Invented title",
            },
            "claims": list(claims),
        }
    )


def run(tmp_path, game_frame, records):
    teams, networks = resolvers(tmp_path)
    return match_mlb_rr(records, game_frame, pl.DataFrame(), teams, ERAS, networks)


D = date(2026, 5, 2)
ONE = games((D, "alpha", "bravo", 0))


def only(matches: list[RRGameMatch]) -> RRGameMatch:
    assert len(matches) == 1
    return matches[0]


def test_exact_match_keeps_urls_and_era(tmp_path: Path) -> None:
    rec = record("mlb-aces-bravos-2026-05-02", "2026-05-02", claims=[CLAIM], networks=["Apple TV+"])
    matches, reviews = run(tmp_path, ONE, [rec])
    m = only(matches)
    assert (m.tier, m.cause, m.viewers, m.viewership_label) == ("date", None, 5_000_000, "per-game")
    assert m.record_url == rec.record_url
    assert m.headline_source_url == "https://example.org/figure"
    assert m.era_id == "era-b" and m.era_check == "agree"
    assert m.network_ids == ("apple",)
    assert reviews == []


def test_multi_word_nickname_slug(tmp_path: Path) -> None:
    g = games((D, "charlie", "bravo", 0))
    m = only(
        run(tmp_path, g, [record("mlb-bravos-red-sox-2026-05-02", "2026-05-02", claims=[CLAIM])])[0]
    )
    assert m.viewers == 5_000_000


def test_teams_field_is_used_before_slug(tmp_path: Path) -> None:
    rec = record(
        "mlb-odd-slug-2026-05-02", "2026-05-02", claims=[CLAIM], teams=["mlb-aces", "mlb-bravos"]
    )
    assert only(run(tmp_path, ONE, [rec])[0]).viewers == 5_000_000


def test_one_day_shift_is_flagged_and_two_days_is_unmatched(tmp_path: Path) -> None:
    shifted = record("mlb-aces-bravos-2026-05-03", "2026-05-03", claims=[CLAIM])
    m, reviews = run(tmp_path, ONE, [shifted])
    assert only(m).tier == "date-shift" and reviews == []
    far = record("mlb-aces-bravos-2026-05-05", "2026-05-05", claims=[CLAIM])
    m2, reviews2 = run(tmp_path, ONE, [far])
    assert only(m2).cause == "none"
    assert reviews2 == [RRReview(2026, "mlb-aces-bravos-2026-05-05", "unmatched")]


def test_unresolved_team_is_reviewed(tmp_path: Path) -> None:
    _, reviews = run(
        tmp_path, ONE, [record("mlb-zzz-yyy-2026-05-02", "2026-05-02", claims=[CLAIM])]
    )
    assert reviews == [RRReview(2026, "mlb-zzz-yyy-2026-05-02", "unresolved_team")]


def test_doubleheader_is_ambiguous_and_never_attached(tmp_path: Path) -> None:
    dh = games((D, "alpha", "bravo", 1), (D, "alpha", "bravo", 2))
    matches, reviews = run(
        tmp_path, dh, [record("mlb-aces-bravos-2026-05-02", "2026-05-02", claims=[CLAIM])]
    )
    assert [m.cause for m in matches] == ["ambiguous_doubleheader"] * 2
    assert all(m.viewers is None and m.record_url is None for m in matches)
    assert [r.reason for r in reviews] == ["ambiguous_doubleheader"]


def test_conflicting_finals_are_reported_not_summed(tmp_path: Path) -> None:
    a = record("mlb-aces-bravos-2026-05-02", "2026-05-02", claims=[CLAIM], networks=["Fox"])
    b = record(
        "mlb-aces-bravos-2026-05-02",
        "2026-05-02",
        claims=[{**CLAIM, "id": "c2", "value": 7_000_000}],
        networks=["Fox"],
    )
    m, reviews = run(tmp_path, ONE, [a, b])
    assert only(m).cause == "conflict" and only(m).viewers is None
    assert [r.reason for r in reviews] == ["conflict", "conflict"]
    assert len(only(m).record_urls) == 2


def test_superseding_record_resolves_without_conflict(tmp_path: Path) -> None:
    a = record("mlb-aces-bravos-2026-05-02", "2026-05-02", claims=[CLAIM])
    b = record(
        "mlb-aces-bravos-2026-05-02",
        "2026-05-02",
        claims=[{**CLAIM, "id": "c2", "value": 6_000_000, "supersedes_id": "c1"}],
    )
    m, reviews = run(tmp_path, ONE, [a, b])
    assert only(m).cause is None and only(m).viewers == 6_000_000 and reviews == []


def test_per_network_records_are_never_summed(tmp_path: Path) -> None:
    a = record("mlb-aces-bravos-2026-05-02", "2026-05-02", claims=[CLAIM], networks=["Net One"])
    b = record(
        "mlb-aces-bravos-2026-05-02",
        "2026-05-02",
        claims=[{**CLAIM, "id": "c2", "value": 1_000_000}],
        networks=["Net Two"],
    )
    m, _ = run(tmp_path, ONE, [a, b])
    assert only(m).cause == "per_network" and only(m).viewers is None


def test_per_network_cut_keeps_record_url(tmp_path: Path) -> None:
    rec = record(
        "mlb-aces-bravos-2026-05-02", "2026-05-02", claims=[{**CLAIM, "cut": "per_network"}]
    )
    m = only(run(tmp_path, ONE, [rec])[0])
    assert (m.cause, m.viewers, m.record_url) == ("per_network", None, rec.record_url)


def test_events_are_skipped(tmp_path: Path) -> None:
    recs = [
        record("mlb-all-star-2026-07-14", "2026-07-14", claims=[CLAIM]),
        record("mlb-home-run-derby-2026-07-13", "2026-07-13", claims=[CLAIM]),
    ]
    _, reviews = run(tmp_path, ONE, recs)
    assert [r.reason for r in reviews] == ["event", "event"]


def test_window_figure_is_labelled(tmp_path: Path) -> None:
    rec = record(
        "mlb-aces-bravos-2026-05-02",
        "2026-05-02",
        claims=[{**CLAIM, "figure_scope": "split_window"}],
    )
    m = only(run(tmp_path, ONE, [rec])[0])
    assert (m.cause, m.viewership_label, m.viewers) == ("window_level", "window-level", 5_000_000)


def test_composite_and_unnormalized_labels(tmp_path: Path) -> None:
    comp = record(
        "mlb-aces-bravos-2026-05-02", "2026-05-02", claims=[{**CLAIM, "composite_of": ["x", "y"]}]
    )
    assert only(run(tmp_path, ONE, [comp])[0]).viewership_label == "composite"
    raw = record(
        "mlb-aces-bravos-2026-05-02", "2026-05-02", claims=[{**CLAIM, "unnormalized": True}]
    )
    assert only(run(tmp_path, ONE, [raw])[0]).viewership_label == "unnormalized"


def test_game_without_record_is_none(tmp_path: Path) -> None:
    m = only(run(tmp_path, ONE, [])[0])
    assert (m.cause, m.viewers, m.record_url, m.viewership_label) == ("none", None, None, "none")
    assert m.cause in MLB_RR_CAUSES
