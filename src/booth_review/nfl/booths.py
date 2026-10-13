"""NFL booth model for every network group (D-01 to D-07, D-20).

Pure functions over the game frame. A booth is (season, network group, play-by-play
voice) with the modal analyst (from 506-sourced games) stored; a game with a different
analyst is a fill-in that stays with the booth. Every regular-season game a booth called
for its group counts; there is no doubleheader gate. Booth identity never spans seasons or
groups.

Each group-season's order comes from, in precedence: the cited published rank
(`nfl_booth_ranks.csv`), a cited lead-booth override, then flagship-window inference
(Fox AGOTW, CBS late national, NBC SNF, ESPN/ABC MNF, Amazon TNF; groups with no
flagship use the booth with the most games). The rest rank by games called. Inference
votes count only games whose crew came from 506, so a published lineup never votes for
itself; lineup-filled games still count toward a booth's games. Ambiguous Fox AGOTW
weeks (D-16) cast no vote. Where a published lead or analyst differs from the inferred
one the build writes a `booth_rank_disagreements` review (counts only in logs).

These tables stay in the private vault; the NFL site shows names resolved from
person ids.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import polars as pl

from booth_review.nfl.network_groups import NETWORK_GROUPS, flagship_expr, with_network_group
from booth_review.nfl.reference import NflBoothRank, NflLeadBoothOverride

LEAD_CLOSE_MARGIN = 1

_HAS_FLAGSHIP = {g.id: g.flagship is not None for g in NETWORK_GROUPS}

GAME_BOOTH_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "game_id": pl.String,
    "season": pl.Int64,
    "week": pl.Int64,
    "game_date": pl.Date,
    "network_group": pl.String,
    "booth_pbp_person_id": pl.String,
    "regular_analyst_person_id": pl.String,
    "analyst_person_id": pl.String,
    "is_fill_in": pl.Boolean,
    "is_agotw": pl.Boolean,
    "is_flagship": pl.Boolean,
    "late_national_status": pl.String,
    "crew_source": pl.String,
}

LEAD_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "season": pl.Int64,
    "network_group": pl.String,
    "lead_pbp_person_id": pl.String,
    "lead_source": pl.String,
    "lead_votes": pl.Int64,
    "runner_up_pbp_person_id": pl.String,
    "runner_up_votes": pl.Int64,
    "close": pl.Boolean,
    "tied": pl.Boolean,
    "inferred_lead_pbp_person_id": pl.String,
}

BOOTH_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "season": pl.Int64,
    "network_group": pl.String,
    "booth_pbp_person_id": pl.String,
    "regular_analyst_person_id": pl.String,
    "games": pl.Int64,
    "flagship_games": pl.Int64,
    "fill_in_games": pl.Int64,
    "lineup_games": pl.Int64,
    "is_lead_booth": pl.Boolean,
    "booth_rank": pl.Int64,
    "rank_source": pl.String,
}

_DISAGREEMENT_KEYS = (
    "season",
    "network_group",
    "kind",
    "published_pbp_person_id",
    "inferred_pbp_person_id",
    "published_analyst_person_id",
    "modal_analyst_person_id",
)

_NO_RANKS: Mapping[tuple[str, int], Sequence[NflBoothRank]] = {}


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
    """Regular-season games keyed by (season, network group, pbp voice) with fill-in flags."""
    reg = with_network_group(frame.filter(pl.col("game_type") == "REG")).with_columns(
        flagship_expr()
    )
    in_group = reg.filter(pl.col("network_group").is_not_null())
    no_pbp = in_group.filter(pl.col("pbp_person_id").is_null())
    kept = in_group.filter(pl.col("pbp_person_id").is_not_null())

    regular: dict[tuple[int, str, str], str | None] = {}
    for (season, grp, pbp), group in kept.group_by(["season", "network_group", "pbp_person_id"]):
        # Lineup-filled games carry the published analyst by construction, so only
        # 506-sourced games pick the modal analyst; a booth with none falls back to all.
        pairs = list(zip(group["analyst_person_id"], group["crew_source"], strict=True))
        analysts = [a for a, src in pairs if a is not None and src == "506"] or [
            a for a, _ in pairs if a is not None
        ]
        regular[(int(season), str(grp), str(pbp))] = _modal(analysts)

    rows: list[dict[str, object]] = []
    for row in kept.sort(["season", "game_date", "game_id"]).iter_rows(named=True):
        key = (int(row["season"]), str(row["network_group"]), str(row["pbp_person_id"]))
        reg_analyst = regular[key]
        analyst = row["analyst_person_id"]
        rows.append(
            {
                "game_id": row["game_id"],
                "season": row["season"],
                "week": row["week"],
                "game_date": row["game_date"],
                "network_group": row["network_group"],
                "booth_pbp_person_id": row["pbp_person_id"],
                "regular_analyst_person_id": reg_analyst,
                "analyst_person_id": analyst,
                "is_fill_in": analyst is not None and analyst != reg_analyst,
                "is_agotw": bool(row["is_agotw"]),
                "is_flagship": bool(row["is_flagship"]),
                "late_national_status": row["late_national_status"],
                "crew_source": row["crew_source"],
            }
        )
    game_booths = pl.DataFrame(rows, schema=GAME_BOOTH_SCHEMA)
    counts = {
        "booth_games": game_booths.height,
        "no_pbp_games": no_pbp.height,
        "fill_in_games": int(game_booths["is_fill_in"].sum()) if game_booths.height else 0,
        "lineup_games": game_booths.filter(pl.col("crew_source") == "published_lineup").height,
    }
    return game_booths, counts


def _vote_rows(game_booths: pl.DataFrame) -> pl.DataFrame:
    """Games allowed to vote: 506-sourced, and flagship-window when the group has one."""
    from_506 = game_booths.filter(pl.col("crew_source") == "506")
    flagship_groups = [g for g, has in _HAS_FLAGSHIP.items() if has]
    return from_506.filter(pl.col("is_flagship") | ~pl.col("network_group").is_in(flagship_groups))


def _empty_lead(season: int, group: str, source: str | None) -> dict[str, object]:
    return {
        "season": season,
        "network_group": group,
        "lead_pbp_person_id": None,
        "lead_source": source,
        "lead_votes": 0,
        "runner_up_pbp_person_id": None,
        "runner_up_votes": 0,
        "close": False,
        "tied": False,
        "inferred_lead_pbp_person_id": None,
    }


def infer_lead_booths(
    game_booths: pl.DataFrame,
    ranks: Mapping[tuple[str, int], Sequence[NflBoothRank]],
    overrides: Mapping[tuple[str, int], NflLeadBoothOverride],
) -> pl.DataFrame:
    """One row per (season, group): the lead booth, its source, votes and close/tied flags."""
    votes: dict[tuple[int, str], Counter[str]] = {}
    games: dict[tuple[int, str], Counter[str]] = {}
    for row in game_booths.iter_rows(named=True):
        key = (int(row["season"]), str(row["network_group"]))
        games.setdefault(key, Counter())[row["booth_pbp_person_id"]] += 1
    for row in _vote_rows(game_booths).iter_rows(named=True):
        key = (int(row["season"]), str(row["network_group"]))
        votes.setdefault(key, Counter())[row["booth_pbp_person_id"]] += 1

    keys = set(games) | {(s, g) for (g, s) in ranks} | {(s, g) for (g, s) in overrides}
    group_order = {g.id: i for i, g in enumerate(NETWORK_GROUPS)}
    out: list[dict[str, object]] = []
    for season, group in sorted(keys, key=lambda k: (k[0], group_order.get(k[1], 99), k[1])):
        v = votes.get((season, group), Counter())
        gm = games.get((season, group), Counter())
        ranked = sorted(gm, key=lambda p: (-v[p], -gm[p], p))
        inferred = ranked[0] if ranked and v[ranked[0]] > 0 else None
        cited = [r for r in ranks.get((group, season), ()) if r.rank == 1]
        override = overrides.get((group, season))
        if cited:
            lead, source = cited[0].pbp_person_id, "published"
        elif override is not None:
            lead, source = override.person_id, "override"
        elif inferred is not None:
            lead, source = inferred, "inferred"
        else:
            out.append(_empty_lead(season, group, None))
            continue
        others = [p for p in ranked if p != lead and v[p] > 0]
        runner = others[0] if others else None
        runner_votes = v[runner] if runner else 0
        margin = v.get(lead, 0) - runner_votes
        inferred_flags = source == "inferred"
        out.append(
            {
                "season": season,
                "network_group": group,
                "lead_pbp_person_id": lead,
                "lead_source": source,
                "lead_votes": v.get(lead, 0),
                "runner_up_pbp_person_id": runner,
                "runner_up_votes": runner_votes,
                "close": inferred_flags and runner is not None and margin <= LEAD_CLOSE_MARGIN,
                "tied": inferred_flags and runner is not None and margin == 0,
                "inferred_lead_pbp_person_id": inferred,
            }
        )
    return pl.DataFrame(out, schema=LEAD_SCHEMA)


def _ordered_booths(
    lead_row: Mapping[str, object],
    entries: dict[str, dict[str, object]],
    cited: Sequence[NflBoothRank],
) -> list[str]:
    """Booth person ids in rank order for one (season, group)."""
    by_games = sorted(entries, key=lambda p: (-int(entries[p]["games"]), p))  # type: ignore[call-overload]
    lead = lead_row["lead_pbp_person_id"]
    if lead_row["lead_source"] == "published":
        first = [r.pbp_person_id for r in sorted(cited, key=lambda r: r.rank)]
        first = [p for p in first if p in entries]
        return first + [p for p in by_games if p not in first]
    return ([str(lead)] if lead in entries else []) + [p for p in by_games if p != lead]


def build_booths(
    frame: pl.DataFrame,
    ranks: Mapping[tuple[str, int], Sequence[NflBoothRank]] = _NO_RANKS,
    overrides: Mapping[tuple[str, int], NflLeadBoothOverride] | None = None,
) -> NflBooths:
    """Booth assignment, lead inference, ranks, and the review reports."""
    built = {int(s) for s in frame["season"].unique().to_list()}
    ranks = {k: v for k, v in ranks.items() if k[1] in built}
    overrides = {k: v for k, v in (overrides or {}).items() if k[1] in built}
    game_booths, counts = assign_booths(frame)
    leads = infer_lead_booths(game_booths, ranks, overrides)

    booth_rows: list[dict[str, object]] = []
    reviews: dict[str, list[dict[str, object]]] = {
        "lead_booth": [],
        "agotw_misses": [],
        "lead_absent_weeks": [],
        "booth_rank_disagreements": [],
    }
    override_no_games = 0
    for lrow in leads.iter_rows(named=True):
        season, group = int(lrow["season"]), str(lrow["network_group"])
        cell = game_booths.filter((pl.col("season") == season) & (pl.col("network_group") == group))
        cited = ranks.get((group, season), ())
        entries: dict[str, dict[str, object]] = {}
        for (pbp,), bg in cell.group_by(["booth_pbp_person_id"]):
            entries[str(pbp)] = {
                "regular_analyst_person_id": bg["regular_analyst_person_id"][0],
                "games": bg.height,
                "flagship_games": int(bg["is_flagship"].sum()),
                "fill_in_games": int(bg["is_fill_in"].sum()),
                "lineup_games": bg.filter(pl.col("crew_source") == "published_lineup").height,
            }
        for r in cited:
            entries.setdefault(
                r.pbp_person_id,
                {
                    "regular_analyst_person_id": r.analyst_person_id,
                    "games": 0,
                    "flagship_games": 0,
                    "fill_in_games": 0,
                    "lineup_games": 0,
                },
            )

        lead = lrow["lead_pbp_person_id"]
        source = lrow["lead_source"]
        # An override naming a booth with no games here is as good as no lead (D-23).
        lead_known = lead is not None and (source != "override" or lead in entries)
        order = _ordered_booths(lrow, entries, cited) if lead_known else []
        for i, pbp in enumerate(order, start=1):
            booth_rows.append(
                {
                    "season": season,
                    "network_group": group,
                    "booth_pbp_person_id": pbp,
                    **entries[pbp],
                    "is_lead_booth": pbp == lead,
                    "booth_rank": i,
                    "rank_source": source,
                }
            )
        if not lead_known:
            # D-23: no known lead, so rank by games called and label none of them Lead.
            by_games = sorted(entries, key=lambda p: (-int(entries[p]["games"]), p))  # type: ignore[call-overload]
            for i, pbp in enumerate(by_games, start=1):
                booth_rows.append(
                    {
                        "season": season,
                        "network_group": group,
                        "booth_pbp_person_id": pbp,
                        **entries[pbp],
                        "is_lead_booth": False,
                        "booth_rank": i,
                        "rank_source": "games",
                    }
                )

        reason = None
        if source == "override" and lead not in entries:
            override_no_games += 1
            reason = "override-no-games"
        elif source == "published":
            reason = "published"
        elif lead is None:
            reason = "no-flagship-votes"
        elif lrow["tied"]:
            reason = "tied"
        elif lrow["close"]:
            reason = "close"
        reviews["lead_booth"].append({**lrow, "reason": reason})

        if source == "published":
            inferred = lrow["inferred_lead_pbp_person_id"]
            if inferred is not None and inferred != lead:
                reviews["booth_rank_disagreements"].append(
                    dict.fromkeys(_DISAGREEMENT_KEYS)
                    | {
                        "season": season,
                        "network_group": group,
                        "kind": "lead",
                        "published_pbp_person_id": lead,
                        "inferred_pbp_person_id": inferred,
                    }
                )
            for r in sorted(cited, key=lambda r: r.rank):
                entry = entries[r.pbp_person_id]
                modal = entry["regular_analyst_person_id"]
                if entry["games"] and modal != r.analyst_person_id:
                    reviews["booth_rank_disagreements"].append(
                        dict.fromkeys(_DISAGREEMENT_KEYS)
                        | {
                            "season": season,
                            "network_group": group,
                            "kind": "analyst",
                            "published_pbp_person_id": r.pbp_person_id,
                            "published_analyst_person_id": r.analyst_person_id,
                            "modal_analyst_person_id": modal,
                        }
                    )

    group_order = {g.id: i for i, g in enumerate(NETWORK_GROUPS)}
    booth_rows.sort(
        key=lambda r: (
            int(r["season"]),  # type: ignore[call-overload]
            group_order.get(str(r["network_group"]), 99),
            r["booth_rank"] if r["booth_rank"] is not None else 1_000_000,
            str(r["booth_pbp_person_id"]),
        )
    )
    booths = pl.DataFrame(booth_rows, schema=BOOTH_SCHEMA)

    # Fox keeps its AGOTW miss and lead-absent reports.
    fox_leads = {
        int(r["season"]): r["lead_pbp_person_id"]
        for r in leads.filter(pl.col("network_group") == "fox").iter_rows(named=True)
    }
    fox = game_booths.filter(pl.col("network_group") == "fox")
    settled = fox.filter(pl.col("is_agotw") & (pl.col("late_national_status") != "ambiguous"))
    for srow in settled.sort(["season", "week", "game_id"]).iter_rows(named=True):
        season = int(srow["season"])
        lead = fox_leads.get(season)
        if lead is None or srow["booth_pbp_person_id"] == lead:
            continue
        same_week = fox.filter(
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
    for season, lead in sorted(fox_leads.items()):
        if lead is None:
            continue
        season_games = fox.filter(pl.col("season") == season)
        for week in sorted(season_games["week"].unique().to_list()):
            wk = season_games.filter(pl.col("week") == week)
            if wk.filter(pl.col("booth_pbp_person_id") == lead).height == 0:
                reviews["lead_absent_weeks"].append({"season": season, "week": week})

    counts = {
        "booth_games": counts["booth_games"],
        "no_pbp_games": counts["no_pbp_games"],
        "fill_in_games": counts["fill_in_games"],
        "published_lineup_games": counts["lineup_games"],
        "seasons_close": int(leads["close"].sum()) if leads.height else 0,
        "seasons_tied": int(leads["tied"].sum()) if leads.height else 0,
        "seasons_overridden": leads.filter(pl.col("lead_source") == "override").height,
        "seasons_published": leads.filter(pl.col("lead_source") == "published").height,
        "booth_rank_disagreements": len(reviews["booth_rank_disagreements"]),
        "agotw_miss_weeks": len(reviews["agotw_misses"]),
        "lead_absent_weeks": len(reviews["lead_absent_weeks"]),
        "override_no_games": override_no_games,
    }
    return NflBooths(
        game_booths=game_booths, booths=booths, leads=leads, reviews=reviews, counts=counts
    )
