"""Synthetic builders shared by the MLB listings and games tests.

Everything here is invented: clubs, networks, pages and Retrosheet rows. Nothing
comes from the vault.
"""

from __future__ import annotations

import csv
import io
import shutil
import zipfile
from pathlib import Path

from booth_review.mlb.reference import MlbReference, load_mlb_reference

FIXTURES = Path(__file__).parent / "fixtures" / "mlb"

CLUBS = (
    "club_id,league,division,season_from,season_to,display_name,nickname,note\n"
    "alpha,AL,East,,,Alpha City Aces,Aces,synthetic\n"
    "bravo,AL,West,,,Bravo Town Bravos,Bravos,synthetic\n"
    "charlie,NL,East,,,Charlie Chargers,Chargers,synthetic\n"
    "delta,NL,West,,,Delta Bay Dragons,Dragons,synthetic\n"
)
CROSSWALK = (
    "source,variant,club_id,season_from,season_to,note\n"
    "506,Alpha City,alpha,,,synthetic\n"
    "506,Bravo Town,bravo,,,synthetic\n"
    "506,Charlie Chargers,charlie,,,synthetic\n"
    "506,Delta Bay,delta,,,synthetic\n"
    "retrosheet,XAA,alpha,,,synthetic\n"
    "retrosheet,XBB,bravo,,,synthetic\n"
    "retrosheet,XCC,charlie,,,synthetic\n"
    "retrosheet,XDD,delta,,,synthetic\n"
)
NETWORKS = (
    "source,variant,network_id,family,note\n"
    "506,Apple TV+,apple,apple,synthetic\n"
    "506,FOX,fox_net,fox,synthetic\n"
    "506,FS1,fs1,fox,synthetic\n"
    "506,MLBN,mlbn,other,synthetic\n"
    "506,ESPN Unltd,espn_unltd,disney,synthetic\n"
    "506,TBS,tbs,tbs,synthetic\n"
    "wikipedia,NetA,neta,fox,synthetic\n"
    "wikipedia,NetB,netb,disney,synthetic\n"
    "wikipedia,NetC,netc,nbc,synthetic\n"
)
OVERRIDES_HEADER = "season,round,league,network_id,source_url\n"
GAMEINFO_HEADER = (
    Path(FIXTURES / "retrosheet" / "gameinfo_synthetic.csv")
    .read_text(encoding="utf-8")
    .splitlines()[0]
    .split(",")
)


def build_reference(root: Path, overrides: str = "") -> MlbReference:
    """Write the invented reference tables into `root` and load them."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "mlb_clubs.csv").write_text(CLUBS, encoding="utf-8")
    (root / "mlb_team_crosswalk.csv").write_text(CROSSWALK, encoding="utf-8")
    (root / "mlb_networks.csv").write_text(NETWORKS, encoding="utf-8")
    (root / "mlb_postseason_map_overrides.csv").write_text(
        OVERRIDES_HEADER + overrides, encoding="utf-8"
    )
    for name in ("mlb_booth_ranks.csv", "people.csv"):
        shutil.copy(FIXTURES / "reference" / name, root / name)
    return load_mlb_reference(root)


def page_html(entries: list[tuple[str, str, str, str, str]]) -> bytes:
    """A cgame page. Each entry is (date header, matchup, time, outlet cell, crew cell)."""
    parts = ["<html><body><div id='content'>"]
    last_header = None
    for header, matchup, time_et, outlet, crew in entries:
        if header != last_header:
            parts.append(f"<h3>{header}</h3>")
            last_header = header
        parts.append(
            f'<div id="cgame"><div id="cmatchup">{matchup}</div><div id="ctime">{time_et}</div>'
            f'<div id="cntwk">{outlet}</div><div id="canncrs">{crew}</div></div>'
        )
    parts.append("</div></body></html>")
    return "".join(parts).encode()


def gameinfo_row(
    gid: str,
    vis: str,
    home: str,
    day: str,
    gametype: str,
    *,
    season: int,
    number: int = 0,
    vruns: int = 3,
    hruns: int = 4,
) -> dict[str, str]:
    row = dict.fromkeys(GAMEINFO_HEADER, "")
    row.update(
        gid=gid,
        visteam=vis,
        hometeam=home,
        date=day,
        number=str(number),
        gametype=gametype,
        vruns=str(vruns),
        hruns=str(hruns),
        season=str(season),
    )
    return row


def bundle_zip(rows: list[dict[str, str]], year: int) -> bytes:
    """A csvs bundle with the given gameinfo rows plus the synthetic plays and allplayers."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=GAMEINFO_HEADER, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr(f"{year}gameinfo.csv", buffer.getvalue())
        for kind in ("plays", "allplayers"):
            archive.writestr(
                f"{year}{kind}.csv",
                (FIXTURES / "retrosheet" / f"{kind}_synthetic.csv").read_bytes(),
            )
    return out.getvalue()
