"""Read Retrosheet per-season csvs bundles safely and project recorded columns.

The column tuples below are a subset of the headers recorded in
docs/sources/retrosheet.md ("Columns"); that doc is the source of truth. A bundle
is read member by member from the zip: nothing is extracted to disk.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile

import polars as pl

from booth_review.build.io import write_parquet_atomic
from booth_review.config import DataPaths
from booth_review.errors import ParseError
from booth_review.mlb.constants import RETROSHEET_MAX_UNCOMPRESSED_BYTES

GAMEINFO_COLUMNS: tuple[str, ...] = (
    "gid",
    "visteam",
    "hometeam",
    "site",
    "date",
    "number",
    "starttime",
    "daynight",
    "innings",
    "gametype",
    "vruns",
    "hruns",
    "season",
)

PLAYS_COLUMNS: tuple[str, ...] = (
    "gid",
    "inning",
    "vis_home",
    "batteam",
    "pitteam",
    "score_v",
    "score_h",
    "batter",
    "pitcher",
    "lp",
    "bat_f",
    "pa",
)

ALLPLAYERS_COLUMNS: tuple[str, ...] = ("id", "last", "first")

#: Recorded gametype words -> model round (RESEARCH A4). "allstar" is recorded in
#: gameinfo but is not a modeled round; it keeps its own label. "playoff" is the
#: rare tiebreak game.
GAMETYPE_ROUNDS: dict[str, str] = {
    "regular": "regular",
    "wildcard": "wild_card",
    "divisionseries": "division",
    "lcs": "lcs",
    "worldseries": "world_series",
    "playoff": "tiebreak",
    "allstar": "allstar",
}

_INT_COLUMNS = {
    "inning": pl.Int32,
    "vis_home": pl.Int8,
    "score_v": pl.Int32,
    "score_h": pl.Int32,
    "lp": pl.Int8,
    "bat_f": pl.Int8,
    "pa": pl.Int8,
    "vruns": pl.Int32,
    "hruns": pl.Int32,
    "number": pl.Int8,
    "innings": pl.Int32,
    "season": pl.Int32,
}

_KINDS = frozenset({"gameinfo", "plays", "allplayers"})


def open_member(zip_bytes: bytes, kind: str) -> bytes:
    """Return the bytes of the single `<year><kind>.csv` member of a bundle."""
    if kind not in _KINDS:
        raise ParseError(f"retrosheet: unsupported member kind {kind}")
    pattern = re.compile(rf"^\d*{kind}\.csv$")
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ParseError("retrosheet: bundle is not a zip archive") from exc
    with archive:
        for info in archive.infolist():
            name = info.filename
            if ".." in name.split("/") or name.startswith(("/", "\\")) or "\\" in name:
                raise ParseError("retrosheet: unsafe member name in bundle")
        matches = [i for i in archive.infolist() if pattern.match(i.filename)]
        if not matches:
            raise ParseError(f"retrosheet: no {kind} member in bundle")
        if len(matches) > 1:
            raise ParseError(f"retrosheet: more than one {kind} member in bundle")
        info = matches[0]
        if info.file_size > RETROSHEET_MAX_UNCOMPRESSED_BYTES:
            raise ParseError(f"retrosheet: {kind} member exceeds the size cap")
        with archive.open(info) as stream:
            data = stream.read(info.file_size + 1)
        if len(data) > info.file_size:
            raise ParseError(f"retrosheet: {kind} member larger than declared")
        return data


def _read_projected(data: bytes, columns: tuple[str, ...], label: str) -> pl.DataFrame:
    header = data.split(b"\n", 1)[0].decode("utf-8", errors="replace").strip()
    names = header.split(",")
    for column in columns:
        if column not in names:
            raise ParseError(f"retrosheet {label}: missing column {column}")
    frame = pl.read_csv(
        io.BytesIO(data),
        columns=list(columns),
        infer_schema=False,
    )
    casts = [pl.col(c).cast(_INT_COLUMNS[c], strict=True) for c in columns if c in _INT_COLUMNS]
    return frame.with_columns(casts) if casts else frame


def read_gameinfo(zip_bytes: bytes) -> pl.DataFrame:
    """Game info with GAMEINFO_COLUMNS plus a derived `round` column."""
    frame = _read_projected(open_member(zip_bytes, "gameinfo"), GAMEINFO_COLUMNS, "gameinfo")
    for code in frame["gametype"].unique().to_list():
        if code not in GAMETYPE_ROUNDS:
            raise ParseError(f"retrosheet gameinfo: unknown gametype {code}")
    return frame.with_columns(
        pl.col("gametype").replace_strict(GAMETYPE_ROUNDS, return_dtype=pl.String).alias("round")
    )


def read_plays(zip_bytes: bytes, season: int) -> pl.DataFrame:
    """PLAYS_COLUMNS in file order plus `seq` (row index) and `season`."""
    frame = _read_projected(open_member(zip_bytes, "plays"), PLAYS_COLUMNS, "plays")
    return frame.with_row_index("seq").with_columns(
        pl.col("seq").cast(pl.Int64), pl.lit(season, dtype=pl.Int32).alias("season")
    )


def read_allplayers(zip_bytes: bytes) -> pl.DataFrame:
    """Player id with first and last name."""
    return _read_projected(open_member(zip_bytes, "allplayers"), ALLPLAYERS_COLUMNS, "allplayers")


def cached_slim_plays(paths: DataPaths, season: int, zip_bytes: bytes) -> pl.DataFrame:
    """Slim plays for a season, cached in interim/ keyed by the archive sha256."""
    digest = hashlib.sha256(zip_bytes).hexdigest()
    target = paths.interim / f"mlb_plays_{season}.parquet"
    sidecar = target.with_name(target.name + ".sha256")
    if (
        target.is_file()
        and sidecar.is_file()
        and sidecar.read_text(encoding="utf-8").strip() == digest
    ):
        return pl.read_parquet(target)
    frame = read_plays(zip_bytes, season)
    write_parquet_atomic(frame, target)
    sidecar.write_text(digest + "\n", encoding="utf-8")
    return frame
