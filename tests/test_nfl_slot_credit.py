"""18-REVIEW IN-04: the NFL This weekend view builds the Wikipedia credit link from the season
(`https://en.wikipedia.org/wiki/<season>_NFL_season`) instead of shipping each slot row's
`source_url`. Until the contract carries the URL, this pins the client pattern to the
reference table, so a curated row citing a different article fails here, not on the site."""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SLOT_TABLE = ROOT / "data" / "reference" / "nfl_slot_networks.csv"
WEEKEND_VIEW = ROOT / "site" / "sports" / "nfl" / "views" / "weekend.js"
CLIENT_PATTERN = "https://en.wikipedia.org/wiki/${season}_NFL_season"


def test_client_credit_pattern_is_the_one_in_the_view() -> None:
    source = WEEKEND_VIEW.read_text(encoding="utf-8")
    assert source.count(CLIENT_PATTERN) == 1


def test_every_slot_row_cites_the_article_the_client_links() -> None:
    with SLOT_TABLE.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows
    for row in rows:
        season = row["season"]
        assert re.fullmatch(r"20\d\d", season), row
        expected = CLIENT_PATTERN.replace("${season}", season)
        assert row["source_url"] == expected, (row, expected)
