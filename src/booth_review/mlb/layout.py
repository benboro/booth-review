"""The MLB cache-path and source-key contract every MLB plan builds against.

All MLB raw files live under `raw/mlb/<source>/...` and carry `mlb_*` source
keys, so CFB globbers and CFB freeze keys never see them. Paths are POSIX,
relative to `data/vault/raw/`.
"""

from __future__ import annotations

from datetime import date

from booth_review.transport.types import Source

# Separate from audit.completeness.SOURCES, which must never be extended.
MLB_SOURCES: tuple[Source, ...] = (
    "mlb_sports506",
    "mlb_ratingsref",
    "mlb_retrosheet",
    "mlb_wikipedia",
    "mlb_relay",
)
MLB_OPTIONAL_SOURCES: tuple[Source, ...] = ("mlb_statsapi",)

MLB_RAW_PREFIX = "mlb/"
MLB_FIRST_SEASON = 2014
MLB_ROUNDS = ("WC", "DS", "CS", "WS")

RETROSHEET_INDEX_URL = "https://www.retrosheet.org/downloads/csvdownloads.html"
RETROSHEET_INDEX_PATH = "mlb/retrosheet/_index/csvdownloads.html"

MLB_RELAY_PATH = "mlb/relay/crew_relays.csv"

# (slug, article title, round_kind). Plain /wiki/ articles only.
MLB_WIKIPEDIA_LIST_PAGES: tuple[tuple[str, str, str], ...] = (
    (
        "wild_card",
        "List_of_Major_League_Baseball_wild_card_round_broadcasters",
        "wild_card",
    ),
    (
        "lcs_al",
        "List_of_American_League_Championship_Series_broadcasters",
        "lcs_al",
    ),
    (
        "lcs_nl",
        "List_of_National_League_Championship_Series_broadcasters",
        "lcs_nl",
    ),
    ("world_series", "List_of_World_Series_broadcasters", "world_series"),
    # Title assumed (RESEARCH A10); plan 09-16 confirms it from the cached page.
    (
        "national_current",
        "List_of_current_Major_League_Baseball_broadcasters",
        "national_current",
    ),
)


def mlb_506_url(season: int, label: str) -> str:
    """Manifest identity of a hand-saved 506 MLB page; never fetched."""
    return f"https://506sports.com/mlb.php?yr={season}&wk={label}"


def mlb_506_path(season: int, label: str) -> str:
    """Numeric labels are zero-padded to two digits; round labels stay verbatim."""
    name = f"{int(label):02d}" if label.isdigit() else label
    return f"mlb/sports506/{season}/wk-{name}.html"


def mlb_rr_path(season: int, telecast_id: str) -> str:
    return f"mlb/ratingsref/telecast/{season}/{telecast_id}.json"


def retrosheet_asset_path(name: str) -> str:
    if not name or "/" in name or ".." in name:
        raise ValueError(f"unsafe Retrosheet asset name: {name!r}")
    return f"mlb/retrosheet/assets/{name}"


def mlb_wikipedia_url(year: int) -> str:
    return f"https://en.wikipedia.org/wiki/{year}_Major_League_Baseball_postseason"


def mlb_wikipedia_path(year: int) -> str:
    return f"mlb/wikipedia/{year}.html"


def mlb_wikipedia_list_url(title: str) -> str:
    return f"https://en.wikipedia.org/wiki/{title}"


def mlb_wikipedia_list_path(slug: str) -> str:
    return f"mlb/wikipedia/lists/{slug}.html"


def statsapi_schedule_path(day: date) -> str:
    return f"mlb/statsapi/schedule/{day.isoformat()}.json"
