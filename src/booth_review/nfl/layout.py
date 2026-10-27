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


# Plain English Wikipedia articles read for stadium coordinates (Phase 24). One
# (stadium_id, article title) pair per nflverse or project stadium id; titles are the
# URL path segment as written in data/reference/nfl_stadiums.csv where a row exists.
# Two ids may share one article (GER00 and MUN01 are both Allianz Arena): the first id
# is requested and the later one reads its cached file. Home-stadium titles outside
# nfl_stadiums.csv are shown to the user in the dry-run before any request.
NFL_WIKIPEDIA_STADIUM_PAGES: tuple[tuple[str, str], ...] = (
    ("ATL97", "Mercedes-Benz_Stadium"),
    ("BAL00", "M%26T_Bank_Stadium"),
    ("BER00", "Olympiastadion_(Berlin)"),
    ("BOS00", "Gillette_Stadium"),
    ("BUF00", "Highmark_Stadium_(New_York)"),
    ("CAR00", "Bank_of_America_Stadium"),
    ("CHI98", "Soldier_Field"),
    ("CIN00", "Paycor_Stadium"),
    ("CLE00", "Huntington_Bank_Field"),
    ("DAL00", "AT%26T_Stadium"),
    ("DEN00", "Empower_Field_at_Mile_High"),
    ("DET00", "Ford_Field"),
    ("DUB00", "Croke_Park"),
    ("FRA00", "Waldstadion_(Frankfurt)"),
    ("GER00", "Allianz_Arena"),
    ("GNB00", "Lambeau_Field"),
    ("HOU00", "NRG_Stadium"),
    ("IND00", "Lucas_Oil_Stadium"),
    ("JAX00", "EverBank_Stadium"),
    ("KAN00", "Arrowhead_Stadium"),
    ("LAX01", "SoFi_Stadium"),
    ("LON00", "Wembley_Stadium"),
    ("LON01", "Twickenham_Stadium"),
    ("LON02", "Tottenham_Hotspur_Stadium"),
    ("MAD01", "Santiago_Bernab%C3%A9u_Stadium"),
    ("MEL00", "Melbourne_Cricket_Ground"),
    ("MEX00", "Estadio_Azteca"),
    ("MIA00", "Hard_Rock_Stadium"),
    ("MIN01", "U.S._Bank_Stadium"),
    ("MUN01", "Allianz_Arena"),
    ("NAS00", "Nissan_Stadium"),
    ("NOR00", "Caesars_Superdome"),
    ("NYC01", "MetLife_Stadium"),
    ("PAR00", "Stade_de_France"),
    ("PHI00", "Lincoln_Financial_Field"),
    ("PHO00", "State_Farm_Stadium"),
    ("PIT00", "Acrisure_Stadium"),
    ("RIO00", "Maracan%C3%A3_Stadium"),
    ("SAO00", "Arena_Corinthians"),
    ("SEA00", "Lumen_Field"),
    ("SFO01", "Levi%27s_Stadium"),
    ("TAM00", "Raymond_James_Stadium"),
    ("VEG00", "Allegiant_Stadium"),
    ("WAS00", "Northwest_Stadium"),
)


def wikipedia_stadium_url(title: str) -> str:
    return f"https://en.wikipedia.org/wiki/{title}"


def wikipedia_stadium_path(stadium_id: str) -> str:
    return f"nfl/wikipedia/stadiums/{stadium_id}.html"


def wikipedia_stadium_owner(stadium_id: str) -> str:
    """The id whose request fetched this id's article (the first id with that title)."""
    title = dict(NFL_WIKIPEDIA_STADIUM_PAGES)[stadium_id]
    for sid, other in NFL_WIKIPEDIA_STADIUM_PAGES:
        if other == title:
            return sid
    return stadium_id
