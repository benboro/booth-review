"""The NFL cache-path and source-key contract every NFL plan builds against.

All NFL raw files live under `raw/nfl/<source>/...` and carry `nfl_*` source
keys, so CFB globbers and CFB freeze keys never see them. Paths are POSIX,
relative to `data/vault/raw/`.
"""

from __future__ import annotations

from booth_review.transport.types import Source

# Separate from audit.completeness.SOURCES, which must never be extended.
NFL_SOURCES: tuple[Source, ...] = (
    "nfl_sports506",
    "nfl_ratingsref",
    "nfl_nflverse",
    "nfl_wikipedia",
)

NFL_RAW_PREFIX = "nfl/"
NFL_FIRST_SEASON = 2014

NFLVERSE_SCHEDULES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
NFLVERSE_SCHEDULES_PATH = "nfl/nflverse/schedules/games.csv"

NFLVERSE_API_BASE = "https://api.github.com/repos/nflverse/nflverse-data"
NFLVERSE_PBP_TAG = "pbp"
NFLVERSE_PBP_RELEASE_PATH = "nfl/nflverse/pbp/_release.json"


def nflverse_pbp_assets_page_path(page: int) -> str:
    return f"nfl/nflverse/pbp/_assets-p{page}.json"


def nflverse_pbp_path(season: int) -> str:
    return f"nfl/nflverse/pbp/play_by_play_{season}.parquet"


def nfl_rr_path(season: int, telecast_id: str) -> str:
    return f"nfl/ratingsref/telecast/{season}/{telecast_id}.json"


def nfl_506_url(season: int, week: int) -> str:
    """Manifest identity of a hand-saved 506 NFL page; never fetched."""
    return f"https://506sports.com/nfl.php?yr={season}&wk={week}"


def nfl_506_path(season: int, week: int) -> str:
    return f"nfl/sports506/{season}/wk-{week:02d}.html"


def wikipedia_url(season: int) -> str:
    return f"https://en.wikipedia.org/wiki/{season}_NFL_season"


def wikipedia_path(season: int) -> str:
    return f"nfl/wikipedia/{season}.html"
