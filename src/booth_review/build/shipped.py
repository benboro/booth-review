"""Which telecasts the site data ships, why an unrated game has no figure, and
the network rated-share audit (04.13 D-10, D-11, D-13).

Pure functions, no I/O. `build_site_data` uses these so the bowl review and the
site data can never disagree on which games ship.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

import polars as pl

Cause = Literal["rarely_rated", "pending", "rr_dip", "none"]

# Ratings Reference's coverage dips in 2021-2024; see docs/known-gaps.md
# section "Ratings Reference coverage: a real dip in 2021-2024" (04.13 D-10).
RR_DIP_SEASONS = range(2021, 2025)


def unrated_shipped_expr() -> pl.Expr:
    """Rows shipped in `telecasts_unrated` (04.13 D-13): not plotted, on the
    main feed, with a game and a resolved network. build_site_data and the
    bowl review both use this, so they never disagree on which games ship.
    """
    return (
        ~pl.col("plotted").fill_null(False)
        & (pl.col("feed_type") == "main")
        & pl.col("game_id").is_not_null()
        & pl.col("network_id").is_not_null()
    )


def left_out_unrated_expr() -> pl.Expr:
    """Main-feed rows that are not plotted and fail `unrated_shipped_expr`
    (no game or no network), the exact complement of the shipped predicate
    (review IN-02). Alt-feed and plotted rows are not left out.
    """
    return (
        (pl.col("feed_type") == "main")
        & ~pl.col("plotted").fill_null(False)
        & ~unrated_shipped_expr()
    )


def select_unrated_shipped(
    telecasts: pl.DataFrame, sort_keys: list[str]
) -> tuple[pl.DataFrame, int]:
    """The unrated rows to ship, never putting a game in the site data twice
    (review WR-01): rows whose game already has a plotted telecast are
    dropped, and only the first row per game (by `sort_keys`) is kept.
    Returns (frame sorted by sort_keys, number of eligible rows dropped).
    """
    eligible = telecasts.filter(unrated_shipped_expr())
    plotted_games = telecasts.filter(pl.col("plotted").fill_null(False)).select("game_id")
    fresh = eligible.join(plotted_games, on="game_id", how="anti")
    kept = fresh.sort(sort_keys, nulls_last=True).unique(
        subset="game_id", keep="first", maintain_order=True
    )
    return kept, eligible.height - kept.height


def shipped_expr() -> pl.Expr:
    """Every row that ships in either block: plotted or unrated-shipped."""
    return pl.col("plotted").fill_null(False) | unrated_shipped_expr()


def _at_or_after(season_type: str, week: int, through: str | None) -> bool:
    if through is None:
        return True
    if through == "postseason":
        return season_type == "postseason"
    return season_type == "postseason" or week >= int(through)


def no_rating_cause(
    *,
    season: int,
    season_type: str,
    week: int,
    network_id: str,
    rarely_rated: Mapping[str, bool],
    current_season: int,
    viewership_through_week: str | None,
    rated_not_plotted: bool,
) -> Cause:
    """The one cause shown for an unrated game, first match wins (04.13 D-10):
    rated-but-not-plotted (an alt-only figure) -> "none"; rarely-rated network ->
    "rarely_rated"; current season at or after viewership_through_week ->
    "pending"; 2021-2024 -> "rr_dip"; else "none".

    The pending rule is "at or after" (CONTEXT D-10 item 2, confirmed by the user
    on 2026-10-05): a week's figures arrive over several days, and a strict
    "after" would flag nothing.
    """
    if rated_not_plotted:
        return "none"
    if rarely_rated.get(network_id, False):
        return "rarely_rated"
    if season == current_season and _at_or_after(season_type, week, viewership_through_week):
        return "pending"
    if season in RR_DIP_SEASONS:
        return "rr_dip"
    return "none"


def network_rated_counts(telecasts: pl.DataFrame) -> dict[str, tuple[int, int]]:
    """network_id -> (main-feed games, rated main-feed games) over main-feed
    rows that have a network."""
    main = telecasts.filter((pl.col("feed_type") == "main") & pl.col("network_id").is_not_null())
    counts: dict[str, tuple[int, int]] = {}
    for row in main.select("network_id", "rated").iter_rows(named=True):
        games, rated = counts.get(row["network_id"], (0, 0))
        counts[row["network_id"]] = (games + 1, rated + (1 if row["rated"] else 0))
    return counts


def rarity_verdict(
    games: int,
    rated: int,
    flag: bool,
    *,
    min_games: int = 25,
    high: float = 0.25,
    low: float = 0.10,
) -> Literal["flagged_but_mostly_rated", "unflagged_but_mostly_unrated"] | None:
    """Audit only (D-11): report a network whose hand-set flag contradicts its
    rated share. The thresholds never decide a flag."""
    if games < min_games:
        return None
    share = rated / games
    if flag and share > high:
        return "flagged_but_mostly_rated"
    if not flag and share < low:
        return "unflagged_but_mostly_unrated"
    return None


def rarity_contradictions(
    counts: Mapping[str, tuple[int, int]], rarity: Mapping[str, bool]
) -> tuple[int, int]:
    """(flagged_but_mostly_rated, unflagged_but_mostly_unrated) over `counts`."""
    flagged = 0
    unflagged = 0
    for network_id, (games, rated) in counts.items():
        verdict = rarity_verdict(games, rated, rarity.get(network_id, False))
        if verdict == "flagged_but_mostly_rated":
            flagged += 1
        elif verdict == "unflagged_but_mostly_unrated":
            unflagged += 1
    return flagged, unflagged
