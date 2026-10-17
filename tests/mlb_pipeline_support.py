"""A synthetic MLB vault for the build, command and freeze tests (plan 09-24).

Everything here is invented: clubs, players, pages, Retrosheet bundles and Ratings
Reference records. Nothing comes from the real vault. The vault holds a 2025 bundle
(regular games for the win-expectancy table, two postseason games), optional 2026
results, a 2025 wild-card page with an unresolved crew name, an Apple 2026 page and one
Ratings Reference record.
"""

from __future__ import annotations

import csv
import io
import json
import shutil
import zipfile
from pathlib import Path

from mlb_games_support import (
    GAMEINFO_HEADER,
    build_reference,
    gameinfo_row,
    page_html,
)

from booth_review.config import DataPaths
from booth_review.mlb.layout import mlb_506_path, mlb_rr_path, retrosheet_asset_path
from booth_review.sources.retrosheet.loader import PLAYS_COLUMNS

_REPO_REFERENCE = Path(__file__).parent / "fixtures" / "reference"

RR_SLUG = "mlb-aces-bravos-2025-10-04"
RR_WILD_CARD_SLUG = "mlb-chargers-dragons-2025-10-01"
RR_CLAIM = {
    "id": "c1",
    "metric_type": "avg_audience",
    "status": "final",
    "value": 4_000_000,
    "unit": "viewers",
    "cut": "full_telecast",
    "era_id": "rr-era-c",
    "measured_by": "Fixture Panel",
    "source_url": "https://example.invalid/figure",
}


def _plays_csv(gid: str, vis: str, home: str, *, plays: int = 36) -> list[dict[str, str]]:
    """`plays` plays: two per half-inning, visitors score 3 and the home side 4 in total."""
    away_scores = {6, 14, 26}
    home_scores = {9, 17, 30, 33}
    score_v = score_h = 0
    lp = {0: 0, 1: 0}
    rows: list[dict[str, str]] = []
    for k in range(plays):
        inning = k // 4 + 1
        side = (k // 2) % 2  # 0 = visitors bat
        lp[side] = lp[side] % 9 + 1
        rows.append(
            {
                "gid": gid,
                "inning": str(inning),
                "top_bot": str(side),
                "vis_home": str(side),
                "batteam": vis if side == 0 else home,
                "pitteam": home if side == 0 else vis,
                "score_v": str(score_v),
                "score_h": str(score_h),
                "batter": f"{'v' if side == 0 else 'h'}bat{lp[side]}",
                "pitcher": "hpit1" if side == 0 else "vpit1",
                "lp": str(lp[side]),
                "bat_f": str(lp[side] + 1),
                "pa": "1",
                "outs_pre": str(k % 2),
                "br1_pre": "",
                "br2_pre": "",
                "br3_pre": "",
            }
        )
        score_v += int(k in away_scores)
        score_h += int(k in home_scores)
    return rows


def _allplayers() -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["id", "last", "first"])
    for side in ("v", "h"):
        for n in range(1, 10):
            writer.writerow([f"{side}bat{n}", f"Last{side}{n}", f"First{side}{n}"])
    writer.writerow(["hpit1", "Lasthp", "Firsthp"])
    writer.writerow(["vpit1", "Lastvp", "Firstvp"])
    return out.getvalue().encode()


def bundle(year: int, rows: list[dict[str, str]], clubs: dict[str, tuple[str, str]]) -> bytes:
    """A Retrosheet csvs bundle; `clubs` maps gid -> (visitor code, home code) for its plays."""
    games = io.StringIO()
    gwriter = csv.DictWriter(games, fieldnames=GAMEINFO_HEADER, lineterminator="\n")
    gwriter.writeheader()
    gwriter.writerows(rows)
    plays = io.StringIO()
    pwriter = csv.DictWriter(plays, fieldnames=list(PLAYS_COLUMNS), lineterminator="\n")
    pwriter.writeheader()
    for gid, (vis, home) in clubs.items():
        pwriter.writerows(_plays_csv(gid, vis, home))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr(f"{year}gameinfo.csv", games.getvalue())
        archive.writestr(f"{year}plays.csv", plays.getvalue())
        archive.writestr(f"{year}allplayers.csv", _allplayers())
    return out.getvalue()


def _put(paths: DataPaths, relative: str, data: bytes) -> None:
    target = paths.raw / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def make_reference(root: Path) -> Path:
    """Reference tables for the synthetic vault: clubs, networks, ranks, people, eras."""
    build_reference(root)
    with (root / "mlb_team_crosswalk.csv").open("a", encoding="utf-8", newline="") as handle:
        nicknames = (
            ("aces", "alpha"),
            ("bravos", "bravo"),
            ("chargers", "charlie"),
            ("dragons", "delta"),
        )
        for variant, club in nicknames:
            handle.write(f"ratingsref,{variant},{club},,,synthetic\n")
        handle.write("relay,Alpha City,alpha,,,synthetic\nrelay,Bravo Town,bravo,,,synthetic\n")
    shutil.copy(_REPO_REFERENCE / "measurement_eras.csv", root / "measurement_eras.csv")
    return root


def make_vault(paths: DataPaths, *, with_2026: bool = False, with_rr: bool = True) -> None:
    """Write the raw files of the synthetic vault under `paths.raw`."""
    regular: list[dict[str, str]] = []
    clubs: dict[str, tuple[str, str]] = {}
    for n in range(1, 7):
        gid = f"XBB2025060{n}0"
        regular.append(
            gameinfo_row(gid, "XAA", "XBB", f"2025060{n}", "regular", season=2025, number=0)
        )
        clubs[gid] = ("XAA", "XBB")
    post = [
        gameinfo_row("W1", "XCC", "XDD", "20251001", "wildcard", season=2025),
        gameinfo_row("D1", "XAA", "XBB", "20251004", "divisionseries", season=2025),
    ]
    clubs["W1"] = ("XCC", "XDD")
    clubs["D1"] = ("XAA", "XBB")
    _put(
        paths,
        retrosheet_asset_path("2025csvs.zip"),
        bundle(2025, [*regular, *post], clubs),
    )
    if with_2026:
        row = gameinfo_row("XBB202606050", "XAA", "XBB", "20260605", "regular", season=2026)
        _put(
            paths,
            retrosheet_asset_path("2026csvs.zip"),
            bundle(2026, [row], {"XBB202606050": ("XAA", "XBB")}),
        )
    _put(
        paths,
        mlb_506_path(2025, "WC"),
        page_html(
            [
                (
                    "Wednesday, October 01",
                    "Game 1: Charlie Chargers @ Delta Bay",
                    "8:00 PM ET",
                    "TBS",
                    "A B, C D",
                ),
            ]
        ),
    )
    _put(
        paths,
        mlb_506_path(2026, "3"),
        page_html(
            [
                (
                    "Friday, June 05",
                    "Alpha City @ Bravo Town",
                    "7:10 PM ET",
                    "Apple TV+",
                    "Ana Fixture, Bo Fixture",
                ),
                ("Saturday, June 06", "Charlie Chargers @ Delta Bay", "7:10 PM ET", "MLBN*", ""),
                ("Sunday, June 07", "Bravo Town @ Alpha City", "1:00 PM ET", "FOX", ""),
            ]
        ),
    )
    if with_rr:
        for slug, day, teams in (
            (RR_SLUG, "2025-10-04", ["mlb-aces", "mlb-bravos"]),
            (RR_WILD_CARD_SLUG, "2025-10-01", ["mlb-chargers", "mlb-dragons"]),
        ):
            record = {
                "telecast": {
                    "id": slug,
                    "event_date": day,
                    "teams": teams,
                    "networks": [],
                    "title": "Invented",
                },
                "claims": [RR_CLAIM],
            }
            _put(paths, mlb_rr_path(2025, slug), json.dumps(record).encode())


RELAY_HEADER = (
    "season,game_date,away_club,home_club,game_number,network_id,pbp,analyst_1,analyst_2,"
    "post_url,press_name,press_url,read_date"
)


def write_relay(paths: DataPaths, row: str) -> None:
    target = paths.raw / "mlb/relay/crew_relays.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(RELAY_HEADER + "\n" + row + "\n", encoding="utf-8")
