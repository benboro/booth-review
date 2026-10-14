"""Named statistical and smoke constants for the MLB module (Phase 9)."""

from __future__ import annotations

import math

# Win-expectancy (WE) table
WE_TRAIN_SEASONS = tuple(range(2015, 2026))  # Retrosheet seasons the table trains on
WE_TRAIN_INNINGS = 9  # regulation innings kept as table states
WE_MAX_DIFF = 10  # score differential is clipped to +/- this
WE_EXTRA_INNING_CAP = 10  # extra innings are pooled at this inning
WE_GHOST_RUNNER_SEASONS = (*range(2020, 2026), 2026)  # automatic runner in extras (regular season)
WE_PRIOR_K = 30  # pseudo-observations of smoothing toward the neighbor prior
WE_ENFORCE_MONOTONE = True  # force WE nondecreasing in the lead
WE_MIN_TRAIN_GAMES = 5000  # fewer training games than this fails the build
MIN_WE_PLAYS = 30  # a game needs this many plays to get an excitement score

# Stakes (leverage proxy)
GB_SD_PER_ROOT_GAME = math.sqrt(1 / 8)  # sd of the games-behind change per sqrt(games left)
STAKES_GAME_SHIFT = 0.5  # half-game shift for ties on the cutoff
STAKES_MIN_GAMES = 20  # earlier in the season stakes are not scored
STAKES_EXCLUDED_SEASONS = (2020,)  # shortened season distorts the baseline
STAKES_BASELINE_SEASONS = tuple(s for s in range(2017, 2026) if s not in STAKES_EXCLUDED_SEASONS)
WC_SPOTS_BY_ERA = ((2012, 2021, 2), (2022, 9999, 3))  # (first, last, spots per league)
SEASON_GAMES = 162  # regular-season length
MIN_BAND_N = 200  # smallest sample for a stakes band to stand alone
STAKES_BAND_QUANTILES = (0.50, 0.80, 0.95)  # band edges on the baseline distribution
LOW_N = 10  # fewer games than this is flagged low-n

# Matching and coverage
MAX_DATE_SHIFT_DAYS = 1  # a telecast may match a game one day off
CREW_COVERAGE_BAR = 0.95  # share of listings needing a crew

# Smoke checks
MLB_SMOKE_MIN_LISTINGS = 5
MLB_SMOKE_MIN_OUTLET_SHARE = 0.95
MLB_SMOKE_MIN_ROUND_CREW_SHARE = 0.5

# Collection limits
MLB_REFRESH_CAP_DEFAULT = 40  # Ratings Reference re-fetches per run
STATSAPI_MAX_REQUESTS = 60  # per run, if the gated host is ever approved
RETROSHEET_MAX_ZIP_BYTES = 400_000_000
RETROSHEET_MAX_UNCOMPRESSED_BYTES = 2_000_000_000

EXCITEMENT_METHOD = "WE-table (Retrosheet)"
STAKES_METHOD = (
    "leverage proxy (record, games behind division and last wild card, through the previous day)"
)


def wc_spots(season: int) -> int:
    """Wild-card spots per league in `season`."""
    for first, last, spots in WC_SPOTS_BY_ERA:
        if first <= season <= last:
            return spots
    raise ValueError(f"no wild-card era for season {season}")
