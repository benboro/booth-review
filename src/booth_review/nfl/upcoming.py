"""Unplayed NFL games of the weekend (Phase 18, D-11 to D-18).

The played-game pipeline keeps only games past kickoff + 4 h. This module builds the
other side: every regular-season game in a week up to the current one that has not
been played, including games whose date or kickoff time is still TBD (kept, never
skipped), with a network and a crew only when a source names them.

Network sources, in order: the saved 506 NFL page (`network_basis` "506"); else, for a
plain Thursday, Sunday or Monday night game, the hand-curated slot-rights table
`nfl_slot_networks.csv` ("slot"); else None (Network TBA). Nothing is guessed. Crews
come only from the 506 import, never from published lineups (D-15). Every slot-rule
line lives in `_slot_network`, so dropping the rule is a one-file change.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from booth_review.errors import ReferenceTableError
from booth_review.nfl.changes import match_schedule_changes
from booth_review.nfl.games import PLAYED_AFTER, NflReference
from booth_review.nfl.inputs import NflInputs
from booth_review.nfl.layout import nfl_506_url
from booth_review.nfl.listings import ListingMatch, match_506_listings
from booth_review.nfl.network_groups import network_group_of
from booth_review.nfl.people import resolve_crew
from booth_review.nfl.reference import NFL_NETWORK_IDS
from booth_review.nfl.rules import SlotName, slot_name
from booth_review.nfl.schedule import UpcomingNflGame
from booth_review.reference import read_reference_csv_numbered

SLOT_NETWORKS_FILE = "nfl_slot_networks.csv"
SLOT_NETWORK_COLUMNS = ("season", "slot", "network_id", "source_url")
SLOT_NAMES = frozenset({"TNF", "SNF", "MNF"})

#: The last regular-season week: never given a slot network (flex scheduling).
_LAST_WEEK = 18

UPCOMING_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "season": pl.Int64,
    "week": pl.Int64,
    "game_id": pl.String,
    "game_date": pl.Date,
    "kickoff_utc": pl.Datetime("us", "UTC"),
    "home_franchise_id": pl.String,
    "away_franchise_id": pl.String,
    "home_display_name": pl.String,
    "away_display_name": pl.String,
    "slot_name": pl.String,
    "is_international": pl.Boolean,
    "is_neutral": pl.Boolean,
    "network_id": pl.String,
    "network_basis": pl.String,
    "pbp_person_id": pl.String,
    "analyst_person_id": pl.String,
    "sideline_person_ids": pl.List(pl.String),
    "crew_source": pl.String,
    "crew_source_url": pl.String,
    "booth_rank": pl.Int64,
}
UPCOMING_COLUMNS = tuple(UPCOMING_SCHEMA)

UPCOMING_COUNT_KEYS = (
    "upcoming_games",
    "upcoming_unplaced",
    "upcoming_unresolved_teams",
    "upcoming_network_tba",
    "upcoming_slot_basis",
    "upcoming_slot_table_missing",
)


def load_slot_networks(reference_directory: Path) -> dict[tuple[int, str], str]:
    """(season, slot) -> network id from nfl_slot_networks.csv; a missing file is empty."""
    path = reference_directory / SLOT_NETWORKS_FILE
    rows = read_reference_csv_numbered(path, SLOT_NETWORK_COLUMNS, required=False)
    table: dict[tuple[int, str], str] = {}
    for line_no, raw in rows:
        try:
            season = int(raw["season"])
        except ValueError:
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: season is not a number"
            ) from None
        if raw["slot"] not in SLOT_NAMES:
            raise ReferenceTableError(f"{path.name}: line {line_no}: slot must be TNF, SNF or MNF")
        if raw["network_id"] not in NFL_NETWORK_IDS:
            raise ReferenceTableError(f"{path.name}: line {line_no}: unknown network id")
        if not raw["source_url"].startswith("https://"):
            raise ReferenceTableError(f"{path.name}: line {line_no}: source_url must be https")
        table[(season, raw["slot"])] = raw["network_id"]
    return table


def current_nfl_week(games: Sequence[UpcomingNflGame], now: datetime) -> int | None:
    """Last fully played week plus one, capped at the last week, for the latest season.

    A game is played once its kickoff + 4 h has passed (D-18). A game with no kickoff yet
    is never played, so one unscheduled game keeps its week open. None without rows.
    """
    if not games:
        return None
    season = max(g.season for g in games)
    weeks = sorted({g.week for g in games if g.season == season})
    last_played: int | None = None
    for week in weeks:
        in_week = [g for g in games if g.season == season and g.week == week]
        if all(g.kickoff_et is not None and g.kickoff_et + PLAYED_AFTER <= now for g in in_week):
            last_played = week
        else:
            break
    if last_played is None:
        return weeks[0]
    return min(last_played + 1, weeks[-1])


def _slot_network(
    game: UpcomingNflGame,
    *,
    international: bool,
    changed: bool,
    slots: Mapping[tuple[int, str], str],
) -> str | None:
    """The slot-rights network of a plain TNF, SNF or MNF game, else None.

    Excluded: international and unknown-site neutral games, Thanksgiving, Black Friday,
    Christmas, Wednesday and Saturday games (slot_name is not TNF/SNF/MNF), the Week 1
    Thursday opener, Week 18, a game in the season's Wikipedia scheduling-changes list,
    and any game without a kickoff time.
    """
    kickoff = game.kickoff_et
    if kickoff is None or international or changed or game.week >= _LAST_WEEK:
        return None
    if game.week == 1 and kickoff.weekday() == 3:
        return None
    slot: SlotName = slot_name(kickoff, outside_us=False)
    if slot not in SLOT_NAMES:
        return None
    return slots.get((game.season, slot))


def assemble_upcoming(
    inputs: NflInputs,
    ref: NflReference,
    *,
    now: datetime,
    reference_directory: Path,
) -> tuple[pl.DataFrame, dict[str, int]]:
    """The unplayed games of weeks up to the current one, plus their counts."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    counts: dict[str, int] = dict.fromkeys(UPCOMING_COUNT_KEYS, 0)
    counts["upcoming_unplaced"] = inputs.upcoming_unplaced
    week = current_nfl_week(inputs.upcoming, now)
    if week is None:
        return pl.DataFrame(schema=UPCOMING_SCHEMA), counts
    season = max(g.season for g in inputs.upcoming)
    pending = [
        g
        for g in inputs.upcoming
        if g.season == season
        and g.week <= week
        and (g.kickoff_et is None or g.kickoff_et + PLAYED_AFTER > now)
    ]
    slots = load_slot_networks(reference_directory)
    if pending and not any(s == season for s, _ in slots):
        counts["upcoming_slot_table_missing"] = 1
    listings, _ = match_506_listings(inputs, ref.teams, ref.networks, games=pending)
    changes, _ = match_schedule_changes(inputs, ref.teams, ref.networks)

    rows: list[dict[str, object]] = []
    for game in pending:
        home = ref.teams.resolve("nflverse", game.home_team, game.season)
        away = ref.teams.resolve("nflverse", game.away_team, game.season)
        if home.franchise_id is None or away.franchise_id is None:
            counts["upcoming_unresolved_teams"] += 1
            continue
        country = ref.stadiums.get(ref.stadium_overrides.get(game.game_id, game.stadium_id))
        neutral = game.location == "Neutral"
        # Unknown site on a neutral field is treated as possibly international: no slot fill.
        international = country is not None and country != "US"
        uncertain = international or (country is None and neutral)
        match: ListingMatch | None = listings.get(game.game_id)
        network_id: str | None = None
        basis: str | None = None
        if match is not None and match.network_id is not None:
            network_id, basis = match.network_id, "506"
        else:
            slot_network = _slot_network(
                game,
                international=uncertain,
                changed=game.game_id in changes,
                slots=slots,
            )
            if slot_network is not None:
                network_id, basis = slot_network, "slot"
                counts["upcoming_slot_basis"] += 1
        if network_id is None:
            counts["upcoming_network_tba"] += 1

        crew = resolve_crew(match.crew_names if match else (), ref.people)
        has_crew = bool(crew.pbp_person_id or crew.analyst_person_id or crew.sideline_person_ids)
        booth_rank: int | None = None
        group = network_group_of(network_id)
        if has_crew and group is not None and crew.pbp_person_id is not None:
            for booth in ref.booth_ranks.get((group, game.season), ()):
                if booth.pbp_person_id == crew.pbp_person_id:
                    booth_rank = booth.rank
                    break
        kickoff = game.kickoff_et
        rows.append(
            {
                "season": game.season,
                "week": game.week,
                "game_id": game.game_id,
                "game_date": game.gameday,
                "kickoff_utc": None if kickoff is None else kickoff.astimezone(UTC),
                "home_franchise_id": home.franchise_id,
                "away_franchise_id": away.franchise_id,
                "home_display_name": home.display_name,
                "away_display_name": away.display_name,
                "slot_name": (
                    None if kickoff is None else slot_name(kickoff, outside_us=international)
                ),
                "is_international": international,
                "is_neutral": neutral,
                "network_id": network_id,
                "network_basis": basis,
                "pbp_person_id": crew.pbp_person_id,
                "analyst_person_id": crew.analyst_person_id,
                "sideline_person_ids": list(crew.sideline_person_ids),
                "crew_source": "506" if has_crew else None,
                "crew_source_url": nfl_506_url(game.season, game.week) if has_crew else None,
                "booth_rank": booth_rank,
            }
        )
    counts["upcoming_games"] = len(rows)
    frame = (
        pl.DataFrame(rows, schema=UPCOMING_SCHEMA, orient="row")
        if rows
        else pl.DataFrame(schema=UPCOMING_SCHEMA)
    )
    frame = frame.sort(
        ["week", "game_date", "kickoff_utc", "network_id", "home_franchise_id"], nulls_last=True
    )
    return frame, counts
