"""The games table (JOIN-07's spine): every FBS-involving CFBD game,
FBS-scoped and null-safe (FLAG-04), with one picked closing spread, the
pre-game x value (SPIKE-04), pregame win probability, and CFBD poll ranks --
built deterministically from raw sources only (D-11, D-12).

Postseason games take their ranks from the latest regular-season week that
has rankings, never the postseason "final" poll: CFBD only publishes that
poll after the bowls are played, so it was never the ranking in force at
kickoff for any of those games. This deviates from research Open Question
2's suggestion (use the postseason week=1 poll uniformly) on purpose.

Ranks otherwise come from the CFBD poll at week + RANK_WEEK_OFFSET,
preferring "Playoff Committee Rankings" over "AP Top 25" when both exist for
that week (matching 506's own rank-prefix convention, which follows AP until
the committee poll starts, per Phase 1's finding). RANK_WEEK_OFFSET was
picked by running `python -m booth_review.build.games` against the real
2014-2026 vault: offset 0 agreed with 506's own printed rank digit 96.2% of
the time (3275/3403 comparisons) against offset -1's 23.8% (748/3149) -- see
the Phase 3 Plan 07 SUMMARY for the full per-season breakdown.

CFBD `notes` is carried as the last column for the private bowl review file
(D-19); it never reaches site data. games.parquet stays in the private vault.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence

import polars as pl

from booth_review.build.sources import SeasonSources, load_all_sources
from booth_review.config import DataPaths
from booth_review.resolve.games import is_fbs_game, match_506
from booth_review.resolve.lines import closing_spread_by_game, pregame_x, provider_priority
from booth_review.resolve.names import normalize_team, to_et_date, to_et_datetime
from booth_review.sources.cfbd.parser import CfbdGame, CfbdLine
from booth_review.sources.sports506.parser import Listing506

GAMES_SCHEMA: dict[str, pl.DataType] = {
    "game_id": pl.Int64(),
    "season": pl.Int32(),
    "week": pl.Int32(),
    "season_type": pl.Utf8(),
    "start_utc": pl.Datetime("us", "UTC"),
    "date_et": pl.Date(),
    "kickoff_et": pl.Utf8(),
    "neutral_site": pl.Boolean(),
    "venue_id": pl.Int64(),
    "conference_game": pl.Boolean(),
    "home_id": pl.Int64(),
    "home_team": pl.Utf8(),
    "home_classification": pl.Utf8(),
    "home_conference": pl.Utf8(),
    "home_points": pl.Int32(),
    "away_id": pl.Int64(),
    "away_team": pl.Utf8(),
    "away_classification": pl.Utf8(),
    "away_conference": pl.Utf8(),
    "away_points": pl.Int32(),
    "excitement": pl.Float64(),
    "closing_spread": pl.Float64(),
    "spread_provider": pl.Utf8(),
    "pregame_x": pl.Float64(),
    "home_win_prob": pl.Float64(),
    "home_rank": pl.Int32(),
    "away_rank": pl.Int32(),
    "rank_poll": pl.Utf8(),
    "game_type": pl.Utf8(),
    "playoff_round": pl.Utf8(),
    "notes": pl.Utf8(),
}

# CFBD's exact poll-name strings (confirmed against the real 2014-2026 vault,
# Phase 3 Plan 07): filtering by a guessed name doesn't work (docs/sources/cfbd.md).
POLL_PREFERENCE: tuple[str, ...] = ("Playoff Committee Rankings", "AP Top 25")
RANK_WEEK_OFFSET: int = 0

# CFBD's own "playoff.round" values observed across the 2014-2026 vault
# (D-17): any other string collapses playoff_round to null rather than
# shipping an unrecognized label.
CFP_ROUNDS: frozenset[str] = frozenset({"first_round", "quarterfinal", "semifinal", "championship"})

_IN_SCOPE_SEASON_TYPES = frozenset({"regular", "postseason"})

# season -> (season_type, week) -> (normalized-school -> rank, poll name used)
_RankIndex = dict[int, dict[tuple[str, int], tuple[dict[str, int], str]]]


def _build_rank_index(sources: Sequence[SeasonSources]) -> _RankIndex:
    index: _RankIndex = {}
    for season_sources in sources:
        by_week: dict[tuple[str, int], tuple[dict[str, int], str]] = {}
        for poll_week in season_sources.rankings:
            season_type = poll_week.season_type or "regular"
            polls_by_name = {poll.poll: poll.ranks for poll in poll_week.polls}
            for preferred in POLL_PREFERENCE:
                if preferred in polls_by_name:
                    ranks_by_team = {
                        normalize_team(rank.school): rank.rank for rank in polls_by_name[preferred]
                    }
                    by_week[(season_type, poll_week.week)] = (ranks_by_team, preferred)
                    break
        index[season_sources.season] = by_week
    return index


def _latest_regular_week_with_rankings(
    by_week: dict[tuple[str, int], tuple[dict[str, int], str]],
) -> int | None:
    regular_weeks = [week for season_type, week in by_week if season_type == "regular"]
    return max(regular_weeks) if regular_weeks else None


def _ranks_for_game(
    game: CfbdGame, by_week: dict[tuple[str, int], tuple[dict[str, int], str]]
) -> tuple[int | None, int | None, str | None]:
    if game.season_type == "postseason":
        latest = _latest_regular_week_with_rankings(by_week)
        lookup_key = ("regular", latest) if latest is not None else None
    else:
        lookup_key = ((game.season_type or "regular"), game.week + RANK_WEEK_OFFSET)

    entry = by_week.get(lookup_key) if lookup_key is not None else None
    if entry is None:
        return None, None, None
    ranks_by_team, poll_name = entry
    home_rank = ranks_by_team.get(normalize_team(game.home_team))
    away_rank = ranks_by_team.get(normalize_team(game.away_team))
    return home_rank, away_rank, poll_name


def _game_type(game: CfbdGame) -> str:
    """D-17: CFP (CFBD's own `playoff` object non-null) -> "playoff",
    regardless of physical venue; any other postseason game -> "bowl";
    everything else, including conference championships, -> "regular".
    """
    if game.is_cfp:
        return "playoff"
    if game.season_type == "postseason":
        return "bowl"
    return "regular"


def _playoff_round(game: CfbdGame) -> str | None:
    if game.is_cfp and game.playoff_round in CFP_ROUNDS:
        return game.playoff_round
    return None


def _provider_by_game(lines: Sequence[CfbdLine], priority: Sequence[str]) -> dict[int, str]:
    """The provider `closing_spread_by_game` effectively picked for each
    game_id, for provenance (the `spread_provider` column) -- grouping
    mirrors `closing_spread_by_game`'s own so the two never disagree.
    """
    by_game: dict[int, dict[str, float]] = {}
    for line in lines:
        if line.spread is not None:
            by_game.setdefault(line.game_id, {})[line.provider] = line.spread

    providers: dict[int, str] = {}
    for game_id, by_provider in by_game.items():
        for provider in priority:
            if provider in by_provider:
                providers[game_id] = provider
                break
        else:
            providers[game_id] = next(iter(by_provider))
    return providers


def build_games_frame(sources: Sequence[SeasonSources]) -> pl.DataFrame:
    """Every FBS-involving regular/postseason game across `sources`, one row
    per game_id, sorted by game_id. Deterministic: the same `sources` always
    produce the same frame.
    """
    rank_index = _build_rank_index(sources)

    all_lines: list[CfbdLine] = [line for s in sources for line in s.lines]
    provider_counts: Counter[str] = Counter()
    for line in all_lines:
        if line.spread is not None:
            provider_counts[line.provider] += 1
    priority = provider_priority(dict(provider_counts))
    spread_by_game = closing_spread_by_game(all_lines, priority)
    provider_by_game = _provider_by_game(all_lines, priority)

    wp_by_game: dict[int, float] = {
        row.game_id: row.home_win_probability for s in sources for row in s.wp_pregame
    }

    rows: list[dict[str, object]] = []
    for season_sources in sources:
        by_week = rank_index.get(season_sources.season, {})
        for game in season_sources.games:
            if not is_fbs_game(game):
                continue
            season_type = game.season_type or "regular"
            if season_type not in _IN_SCOPE_SEASON_TYPES:
                continue

            home_rank, away_rank, rank_poll = _ranks_for_game(game, by_week)
            spread = spread_by_game.get(game.id)
            provider = provider_by_game.get(game.id) if spread is not None else None
            kickoff_et = (
                None if game.start_time_tbd else to_et_datetime(game.start_date).isoformat()
            )

            rows.append(
                {
                    "game_id": game.id,
                    "season": game.season,
                    "week": game.week,
                    "season_type": season_type,
                    "start_utc": game.start_date,
                    "date_et": to_et_date(game.start_date),
                    "kickoff_et": kickoff_et,
                    "neutral_site": game.neutral_site,
                    "venue_id": game.venue_id,
                    "conference_game": game.conference_game,
                    "home_id": game.home_id,
                    "home_team": game.home_team,
                    "home_classification": game.home_classification,
                    "home_conference": game.home_conference,
                    "home_points": game.home_points,
                    "away_id": game.away_id,
                    "away_team": game.away_team,
                    "away_classification": game.away_classification,
                    "away_conference": game.away_conference,
                    "away_points": game.away_points,
                    "excitement": game.excitement_index,
                    "closing_spread": spread,
                    "spread_provider": provider,
                    "pregame_x": pregame_x(spread),
                    "home_win_prob": wp_by_game.get(game.id),
                    "home_rank": home_rank,
                    "away_rank": away_rank,
                    "rank_poll": rank_poll,
                    "game_type": _game_type(game),
                    "playoff_round": _playoff_round(game),
                    "notes": game.notes,
                }
            )

    frame = pl.DataFrame(rows, schema=GAMES_SCHEMA)
    return frame.sort("game_id")


def rank_alignment(
    sources: Sequence[SeasonSources],
    frame: pl.DataFrame,
    offsets: Sequence[int] = (0, -1),
) -> dict[int, tuple[int, int]]:
    """For every regular-season game in `frame` whose 506 listing carries a
    printed rank digit, whether that digit equals the CFBD poll rank looked
    up at week + offset, for each offset in `offsets` -> {offset: (agree,
    compared)}. Only a side where 506 actually printed a rank is compared
    (a missing 506 rank isn't a claim of "unranked"). `sources` is grouped by
    season once up front so each game is matched only against its own
    season's listings, not every season's, keeping a full-vault run fast.
    """
    listings_by_season: dict[int, list[Listing506]] = {s.season: s.listings for s in sources}
    games_by_id: dict[int, CfbdGame] = {
        game.id: game for season_sources in sources for game in season_sources.games
    }
    rank_index = _build_rank_index(sources)

    result: dict[int, tuple[int, int]] = dict.fromkeys(offsets, (0, 0))
    for row in frame.iter_rows(named=True):
        if row["season_type"] != "regular":
            continue
        game = games_by_id.get(row["game_id"])
        if game is None:
            continue
        match = match_506(game, listings_by_season.get(game.season, []))
        if match.confidence == "none" or not match.listings:
            continue
        listing = match.listings[0]
        by_week = rank_index.get(game.season, {})

        for offset in offsets:
            agree, compared = result[offset]
            entry = by_week.get(("regular", game.week + offset))
            if entry is not None:
                ranks_by_team, _poll = entry
                home_expected = ranks_by_team.get(normalize_team(game.home_team))
                away_expected = ranks_by_team.get(normalize_team(game.away_team))
                if listing.home_rank is not None:
                    compared += 1
                    if listing.home_rank == home_expected:
                        agree += 1
                if listing.away_rank is not None:
                    compared += 1
                    if listing.away_rank == away_expected:
                        agree += 1
            result[offset] = (agree, compared)
    return result


def _null_pct(frame: pl.DataFrame, column: str) -> float:
    total = frame.height
    if total == 0:
        return 0.0
    return round(100 * frame[column].null_count() / total, 1)


def main(argv: Sequence[str] | None = None) -> None:
    """Print counts only (T-03-28): games per season, FBS-scoped null rates
    for excitement/closing_spread/home_win_prob, and rank_alignment's
    agreement rates for offsets 0 and -1. Never prints a team, person, or
    figure -- this is a coverage diagnostic, not a data dump.
    """
    arg_parser = argparse.ArgumentParser(description="Build the games table diagnostic.")
    arg_parser.add_argument("--season", type=int, default=None)
    args = arg_parser.parse_args(argv)

    paths = DataPaths.from_env()
    seasons = [args.season] if args.season is not None else None
    sources = load_all_sources(paths, seasons)
    frame = build_games_frame(sources)

    print(f"games: {frame.height} total")
    print("season | games | excitement null% | spread null% | home_win_prob null%")
    for season in sorted({row["season"] for row in frame.select("season").iter_rows(named=True)}):
        sub = frame.filter(pl.col("season") == season)
        print(
            f"  {season} | {sub.height} | {_null_pct(sub, 'excitement')} | "
            f"{_null_pct(sub, 'closing_spread')} | {_null_pct(sub, 'home_win_prob')}"
        )

    print("rank alignment (agree/compared) vs. 506's printed rank, by week offset:")
    for offset, (agree, compared) in sorted(rank_alignment(sources, frame).items()):
        pct = round(100 * agree / compared, 1) if compared else 0.0
        print(f"  offset {offset}: {agree}/{compared} ({pct}%)")


if __name__ == "__main__":
    main()
