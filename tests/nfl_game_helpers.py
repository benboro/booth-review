"""Synthetic builders for the NFL game-frame tests (invented teams, networks and games)."""

from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from nfl_join_helpers import listing, sched_row, schedule_csv

from booth_review.flags.era import load_eras
from booth_review.nfl.games import NflReference
from booth_review.nfl.inputs import NflInputs
from booth_review.nfl.reference import (
    FranchiseName,
    NflBoothRank,
    NflFranchises,
    NflNetworkRow,
    NflTeamCrosswalkRow,
    NflWeekOverride,
)
from booth_review.nfl.schedule import parse_schedules
from booth_review.nfl.teams import NflNetworkResolver, NflTeamResolver
from booth_review.people.registry import load_people
from booth_review.sources.ratingsref.parser import RRRecord
from booth_review.sources.sports506.nfl_parser import NflListing506

FIXTURE = Path(__file__).parent / "fixtures" / "nfl" / "reference"
NOW = datetime(2030, 1, 1, tzinfo=UTC)
TEAM_COUNT = 60

NETWORK_VARIANTS = {
    "cbs": ("CBS",),
    "fox": ("FOX",),
    "nbc": ("NBC",),
    "espn": ("ESPN",),
    "abc": ("ABC",),
    "nfln": ("NFLN", "NFL Network"),
}


def abbr(n: int) -> str:
    return f"T{n:02d}"


def team_name(n: int) -> str:
    return f"Team {n:02d}"


def make_teams() -> NflTeamResolver:
    names: dict[str, tuple[FranchiseName, ...]] = {}
    rows: list[NflTeamCrosswalkRow] = []
    for n in range(1, TEAM_COUNT + 1):
        fid = f"team-{n:02d}"
        names[fid] = (FranchiseName(None, None, f"Display {n:02d}", f"Nick{n:02d}"),)
        for variant in (abbr(n), team_name(n)):
            rows.append(NflTeamCrosswalkRow("any", variant, fid, None, None, ""))
    return NflTeamResolver(NflFranchises(names), rows)


def make_networks() -> NflNetworkResolver:
    rows = [
        NflNetworkRow(source, variant, nid, "")
        for nid, variants in NETWORK_VARIANTS.items()
        for source in ("nflverse", "sports506", "ratingsref", "wikipedia")
        for variant in variants
    ]
    return NflNetworkResolver(rows)


def make_ref(
    tmp_path: Path,
    *,
    stadiums: Mapping[str, str] | None = None,
    overrides: Sequence[NflWeekOverride] = (),
    booth_ranks: Mapping[tuple[str, int], tuple[NflBoothRank, ...]] | None = None,
) -> NflReference:
    dest = tmp_path / "ref"
    if not dest.exists():
        shutil.copytree(FIXTURE, dest)
    return NflReference(
        teams=make_teams(),
        networks=make_networks(),
        stadiums=dict(stadiums or {"FAKE01": "GB"}),
        week_overrides={(o.season, o.week, o.network): o for o in overrides},
        people=load_people(dest),
        eras=load_eras(dest),
        booth_ranks=dict(booth_ranks or {}),
    )


def override(season: int, week: int, network: str, game_id: str) -> NflWeekOverride:
    return NflWeekOverride(
        season, week, network, game_id, "https://example.com/override", "agotw-text-source"
    )


def game_row(
    game_id: str,
    away: int,
    home: int,
    day: str,
    time: str = "13:00",
    *,
    season: int = 2015,
    week: int = 1,
    weekday: str = "Sunday",
    **over: str,
) -> dict[str, str]:
    return sched_row(
        game_id,
        week,
        day,
        abbr(away),
        abbr(home),
        season=str(season),
        weekday=weekday,
        gametime=time,
        **over,
    )


def make_inputs(
    rows: list[dict[str, str]],
    *,
    listings: Sequence[NflListing506] = (),
    rr: Sequence[RRRecord] = (),
    rr_season: int = 2015,
    pbp: Mapping[int, Path] | None = None,
) -> NflInputs:
    by_week: dict[tuple[int, int], tuple[NflListing506, ...]] = {}
    for item in listings:
        by_week[(item.season, item.week)] = (*by_week.get((item.season, item.week), ()), item)
    return NflInputs(
        games=tuple(parse_schedules(schedule_csv(rows))),
        listings=by_week,
        listing_parse_failures=0,
        rr_records={rr_season: tuple(rr)} if rr else {},
        changes={},
        pbp_paths=dict(pbp or {}),
    )


def listing_for(
    away: int,
    home: int,
    network: str = "FOX",
    *,
    season: int = 2015,
    week: int = 1,
    idx: int = 0,
    crew: Sequence[str] = (),
    national: bool = False,
    intl_city: str | None = None,
) -> NflListing506:
    base = listing(team_name(away), team_name(home), network, week=week, idx=idx, crew=crew)
    return replace(base, season=season, is_national_line=national, intl_city=intl_city)


def rr_record(
    slug: str,
    day: str,
    away: int,
    home: int,
    networks: Sequence[str] = (),
    *,
    value: float | None = 5_000_000,
    source_url: str = "https://example.com/figure",
) -> RRRecord:
    claims = []
    if value is not None:
        claims.append(
            {
                "id": "c1",
                "metric_type": "avg_audience",
                "status": "final",
                "value": value,
                "unit": "viewers",
                "cut": "total",
                "era_id": "rr-era-b",
                "measured_by": "Fixture Panel",
                "source_url": source_url,
            }
        )
    return RRRecord.model_validate(
        {
            "telecast": {
                "id": slug,
                "event_date": day,
                "teams": [team_name(away), team_name(home)],
                "networks": list(networks),
                "title": "Invented title",
            },
            "claims": claims,
        }
    )
