"""Fox booth model for NFL Task 1 (D-01, D-02, D-03, D-15, D-16).

Pure functions over the plan 13 game frame. Only regular-season Fox games on Fox
doubleheader Sundays enter. A booth is its play-by-play voice within one season
(booth identity never spans seasons) with the modal analyst stored; a game with a
different analyst is a fill-in that stays with the booth. The lead booth, the AGOTW
crew, is the booth with the most AGOTW calls, or the cited override. Ambiguous AGOTW
weeks (D-16) cast no vote. Nothing here decides AGOTW by crew.

Person ids are analysis-only; these tables stay in the private vault.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

import polars as pl

from booth_review.nfl.reference import NflLeadBoothOverride

LEAD_CLOSE_MARGIN = 1

GAME_BOOTH_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "game_id": pl.String,
    "season": pl.Int64,
    "week": pl.Int64,
    "game_date": pl.Date,
    "booth_pbp_person_id": pl.String,
    "regular_analyst_person_id": pl.String,
    "analyst_person_id": pl.String,
    "is_fill_in": pl.Boolean,
    "is_agotw": pl.Boolean,
    "late_national_status": pl.String,
}

LEAD_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "season": pl.Int64,
    "lead_pbp_person_id": pl.String,
    "lead_source": pl.String,
    "lead_votes": pl.Int64,
    "runner_up_pbp_person_id": pl.String,
    "runner_up_votes": pl.Int64,
    "close": pl.Boolean,
    "tied": pl.Boolean,
}

BOOTH_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "season": pl.Int64,
    "booth_pbp_person_id": pl.String,
    "regular_analyst_person_id": pl.String,
    "dh_games": pl.Int64,
    "agotw_games": pl.Int64,
    "fill_in_games": pl.Int64,
    "is_lead_booth": pl.Boolean,
    "booth_rank": pl.Int64,
}


@dataclass(frozen=True)
class NflBooths:
    game_booths: pl.DataFrame
    booths: pl.DataFrame
    leads: pl.DataFrame
    reviews: Mapping[str, list[dict[str, object]]]
    counts: Mapping[str, int]


def _modal(values: list[str]) -> str | None:
    """Most frequent value; ties go to the lexically smallest."""
    if not values:
        return None
    counts = Counter(values)
    top = max(counts.values())
    return min(v for v, c in counts.items() if c == top)


def assign_booths(frame: pl.DataFrame) -> tuple[pl.DataFrame, dict[str, int]]:
    """Fox DH-Sunday games keyed by (season, pbp voice) with fill-in flags."""
    fox = frame.filter((pl.col("game_type") == "REG") & (pl.col("network_id") == "fox"))
    dh = fox.filter(pl.col("fox_dh_sunday").fill_null(False))
    single = fox.filter(~pl.col("fox_dh_sunday").fill_null(False))
    skipped = single.filter(pl.col("game_date").dt.weekday() == 7).select("season", "game_date")
    skipped_weeks = skipped.unique().height

    no_pbp = dh.filter(pl.col("pbp_person_id").is_null())
    kept = dh.filter(pl.col("pbp_person_id").is_not_null())

    regular: dict[tuple[int, str], str | None] = {}
    for (season, pbp), group in kept.group_by(["season", "pbp_person_id"]):
        analysts = [a for a in group["analyst_person_id"].to_list() if a is not None]
        regular[(int(season), str(pbp))] = _modal(analysts)

    rows: list[dict[str, object]] = []
    for row in kept.sort(["season", "game_date", "game_id"]).iter_rows(named=True):
        key = (int(row["season"]), str(row["pbp_person_id"]))
        reg = regular[key]
        analyst = row["analyst_person_id"]
        rows.append(
            {
                "game_id": row["game_id"],
                "season": row["season"],
                "week": row["week"],
                "game_date": row["game_date"],
                "booth_pbp_person_id": row["pbp_person_id"],
                "regular_analyst_person_id": reg,
                "analyst_person_id": analyst,
                "is_fill_in": analyst is not None and analyst != reg,
                "is_agotw": bool(row["is_agotw"]),
                "late_national_status": row["late_national_status"],
            }
        )
    game_booths = pl.DataFrame(rows, schema=GAME_BOOTH_SCHEMA)
    counts = {
        "fox_dh_games": game_booths.height,
        "skipped_single_header_weeks": skipped_weeks,
        "no_pbp_games": no_pbp.height,
        "fill_in_games": int(game_booths["is_fill_in"].sum()) if game_booths.height else 0,
    }
    return game_booths, counts


def _settled_agotw(game_booths: pl.DataFrame) -> pl.DataFrame:
    return game_booths.filter(pl.col("is_agotw") & (pl.col("late_national_status") != "ambiguous"))


def infer_lead_booths(
    game_booths: pl.DataFrame, overrides: Mapping[int, NflLeadBoothOverride]
) -> pl.DataFrame:
    """One row per season: the lead booth, its source, votes and close/tied flags."""
    votes_by_season: dict[int, Counter[str]] = {}
    games_by_season: dict[int, Counter[str]] = {}
    for row in game_booths.iter_rows(named=True):
        games_by_season.setdefault(int(row["season"]), Counter())[row["booth_pbp_person_id"]] += 1
    for row in _settled_agotw(game_booths).iter_rows(named=True):
        votes_by_season.setdefault(int(row["season"]), Counter())[row["booth_pbp_person_id"]] += 1

    seasons = sorted(set(games_by_season) | set(overrides))
    out: list[dict[str, object]] = []
    for season in seasons:
        votes = votes_by_season.get(season, Counter())
        games = games_by_season.get(season, Counter())
        ranked = sorted(votes, key=lambda p: (-votes[p], -games[p], p))
        override = overrides.get(season)
        if override is not None:
            lead = override.person_id
            others = [p for p in ranked if p != lead]
            runner = others[0] if others else None
            out.append(
                {
                    "season": season,
                    "lead_pbp_person_id": lead,
                    "lead_source": "override",
                    "lead_votes": votes.get(lead, 0),
                    "runner_up_pbp_person_id": runner,
                    "runner_up_votes": votes[runner] if runner else 0,
                    "close": False,
                    "tied": False,
                }
            )
            continue
        if not ranked:
            out.append(
                {
                    "season": season,
                    "lead_pbp_person_id": None,
                    "lead_source": None,
                    "lead_votes": 0,
                    "runner_up_pbp_person_id": None,
                    "runner_up_votes": 0,
                    "close": False,
                    "tied": False,
                }
            )
            continue
        lead = ranked[0]
        runner = ranked[1] if len(ranked) > 1 else None
        runner_votes = votes[runner] if runner else 0
        margin = votes[lead] - runner_votes
        out.append(
            {
                "season": season,
                "lead_pbp_person_id": lead,
                "lead_source": "inferred",
                "lead_votes": votes[lead],
                "runner_up_pbp_person_id": runner,
                "runner_up_votes": runner_votes,
                "close": runner is not None and margin <= LEAD_CLOSE_MARGIN,
                "tied": runner is not None and margin == 0,
            }
        )
    return pl.DataFrame(out, schema=LEAD_SCHEMA)


def build_booths(frame: pl.DataFrame, overrides: Mapping[int, NflLeadBoothOverride]) -> NflBooths:
    """Booth assignment, lead inference, ranks and the AGOTW-miss reports."""
    game_booths, counts = assign_booths(frame)
    leads = infer_lead_booths(game_booths, overrides)
    lead_by_season: dict[int, str | None] = {
        int(r["season"]): r["lead_pbp_person_id"] for r in leads.iter_rows(named=True)
    }
    settled = _settled_agotw(game_booths)

    booth_rows: list[dict[str, object]] = []
    for (season, pbp), group in game_booths.group_by(["season", "booth_pbp_person_id"]):
        booth_rows.append(
            {
                "season": int(season),
                "booth_pbp_person_id": str(pbp),
                "regular_analyst_person_id": group["regular_analyst_person_id"][0],
                "dh_games": group.height,
                "agotw_games": int(
                    group.filter(
                        pl.col("is_agotw") & (pl.col("late_national_status") != "ambiguous")
                    ).height
                ),
                "fill_in_games": int(group["is_fill_in"].sum()),
                "is_lead_booth": lead_by_season.get(int(season)) == pbp,
                "booth_rank": None,
            }
        )
    # Ranks: the lead is 1, others 2, 3, ... by DH-Sunday games then person id.
    # Null when the season has no lead booth.
    by_season: dict[int, list[dict[str, object]]] = {}
    for row in booth_rows:
        by_season.setdefault(int(row["season"]), []).append(row)  # type: ignore[call-overload]
    for season, rows in by_season.items():
        if lead_by_season.get(season) is None:
            continue
        rows.sort(
            key=lambda r: (
                not r["is_lead_booth"],
                -int(r["dh_games"]),  # type: ignore[call-overload]
                str(r["booth_pbp_person_id"]),
            )
        )
        for i, row in enumerate(rows, start=1):
            row["booth_rank"] = i
    booths = pl.DataFrame(booth_rows, schema=BOOTH_SCHEMA).sort(
        ["season", "booth_rank", "booth_pbp_person_id"], nulls_last=True
    )

    reviews: dict[str, list[dict[str, object]]] = {
        "lead_booth": [],
        "agotw_misses": [],
        "lead_absent_weeks": [],
    }
    override_no_games = 0
    for lrow in leads.iter_rows(named=True):
        season = int(lrow["season"])
        reason = None
        if lrow["lead_source"] == "override":
            has_games = booths.filter(
                (pl.col("season") == season)
                & (pl.col("booth_pbp_person_id") == lrow["lead_pbp_person_id"])
            ).height
            if not has_games:
                override_no_games += 1
                reason = "override-no-games"
        elif lrow["lead_pbp_person_id"] is None:
            reason = "no-agotw-votes"
        elif lrow["tied"]:
            reason = "tied"
        elif lrow["close"]:
            reason = "close"
        reviews["lead_booth"].append({**lrow, "reason": reason})

    for srow in settled.sort(["season", "week", "game_id"]).iter_rows(named=True):
        season = int(srow["season"])
        lead = lead_by_season.get(season)
        if lead is None or srow["booth_pbp_person_id"] == lead:
            continue
        same_week = game_booths.filter(
            (pl.col("season") == season)
            & (pl.col("week") == srow["week"])
            & (pl.col("booth_pbp_person_id") == lead)
        )
        reviews["agotw_misses"].append(
            {
                "season": season,
                "week": srow["week"],
                "agotw_booth_pbp_person_id": srow["booth_pbp_person_id"],
                "lead_on_other_fox_game": same_week.height > 0,
            }
        )

    for season, lead in sorted(lead_by_season.items()):
        if lead is None:
            continue
        season_games = game_booths.filter(pl.col("season") == season)
        for week in sorted(season_games["week"].unique().to_list()):
            wk = season_games.filter(pl.col("week") == week)
            if wk.filter(pl.col("booth_pbp_person_id") == lead).height == 0:
                reviews["lead_absent_weeks"].append({"season": season, "week": week})

    counts = {
        **counts,
        "seasons_close": int(leads["close"].sum()) if leads.height else 0,
        "seasons_tied": int(leads["tied"].sum()) if leads.height else 0,
        "seasons_overridden": leads.filter(pl.col("lead_source") == "override").height,
        "agotw_miss_weeks": len(reviews["agotw_misses"]),
        "lead_absent_weeks": len(reviews["lead_absent_weeks"]),
        "override_no_games": override_no_games,
    }
    return NflBooths(
        game_booths=game_booths, booths=booths, leads=leads, reviews=reviews, counts=counts
    )
