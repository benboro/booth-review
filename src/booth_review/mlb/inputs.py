"""Load every MLB input from raw/mlb/ only (D-20 step 2).

Nothing outside `raw/mlb/` is read, so CFB and NFL raw directories never reach
the MLB build. Missing optional sources (Wikipedia pages, the relay file,
Retrosheet bundles for a season) give empty inputs, never an error. Pages and
bundles that fail to parse are counted, never fatal, and counts never carry a
file name or content.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from booth_review.config import DataPaths
from booth_review.errors import ParseError
from booth_review.mlb.layout import (
    MLB_RELAY_PATH,
    MLB_ROUNDS,
    mlb_506_path,
    mlb_wikipedia_list_path,
    mlb_wikipedia_path,
    retrosheet_asset_path,
)
from booth_review.sources.retrosheet.loader import read_allplayers, read_gameinfo
from booth_review.sources.sports506.mlb_parser import MlbPage, parse_mlb_page

_WIKIPEDIA_LIST_SLUGS = ("wild_card", "lcs_al", "lcs_nl", "world_series")


@dataclass(frozen=True)
class Review:
    """A gap or ambiguity for human review: a source, a kind and a count.

    `pointer` holds only ids and labels (season/label, game key), never source text.
    """

    source: str
    kind: str
    count: int = 1
    pointer: str = ""


@dataclass(frozen=True)
class MlbInputs:
    """Parsed MLB inputs, keyed by season (and page label)."""

    pages: Mapping[tuple[int, str], MlbPage]
    gameinfo: pl.DataFrame
    allplayers: pl.DataFrame
    retrosheet_zips: Mapping[int, Path]
    wikipedia: Mapping[int, str]
    wikipedia_lists: Mapping[str, str]
    relay_rows: tuple[Mapping[str, str], ...]
    page_parse_failures: int = 0
    retrosheet_failures: int = 0
    seasons: tuple[int, ...] = field(default_factory=tuple)


def _label_of(file_name: str) -> str | None:
    if not (file_name.startswith("wk-") and file_name.endswith(".html")):
        return None
    label = file_name[len("wk-") : -len(".html")]
    if label.isdigit():
        return str(int(label))
    return label if label in MLB_ROUNDS else None


def _read_relay(path: Path) -> tuple[Mapping[str, str], ...]:
    if not path.is_file():
        return ()
    text = path.read_bytes().decode("utf-8", errors="replace")
    return tuple(dict(row) for row in csv.DictReader(io.StringIO(text)))


def load_mlb_inputs(paths: DataPaths, seasons: Sequence[int]) -> MlbInputs:
    """Read 506 pages, Retrosheet bundles, Wikipedia pages and the relay file."""
    raw = paths.raw
    pages: dict[tuple[int, str], MlbPage] = {}
    page_failures = 0
    gameinfo_frames: list[pl.DataFrame] = []
    player_frames: list[pl.DataFrame] = []
    zips: dict[int, Path] = {}
    retro_failures = 0
    wikipedia: dict[int, str] = {}

    for season in sorted(set(seasons)):
        page_dir = (raw / mlb_506_path(season, "1")).parent
        if page_dir.is_dir():
            for page_path in sorted(page_dir.glob("wk-*.html")):
                label = _label_of(page_path.name)
                if label is None:
                    continue
                try:
                    pages[(season, label)] = parse_mlb_page(
                        page_path.read_bytes(), season=season, label=label
                    )
                except ParseError:
                    page_failures += 1

        bundle = raw / retrosheet_asset_path(f"{season}csvs.zip")
        if bundle.is_file():
            try:
                data = bundle.read_bytes()
                # Both members must parse before either counts: a half-read bundle would
                # feed game info with no plays or lineups behind it.
                season_info = read_gameinfo(data)
                season_players = read_allplayers(data)
                gameinfo_frames.append(season_info)
                player_frames.append(season_players)
                zips[season] = bundle
            except ParseError:
                retro_failures += 1

        article = raw / mlb_wikipedia_path(season)
        if article.is_file():
            wikipedia[season] = article.read_bytes().decode("utf-8", errors="replace")

    lists: dict[str, str] = {}
    for slug in _WIKIPEDIA_LIST_SLUGS:
        list_path = raw / mlb_wikipedia_list_path(slug)
        if list_path.is_file():
            lists[slug] = list_path.read_bytes().decode("utf-8", errors="replace")

    gameinfo = (
        pl.concat(gameinfo_frames, how="vertical_relaxed") if gameinfo_frames else pl.DataFrame()
    )
    players = (
        pl.concat(player_frames, how="vertical_relaxed").unique(subset=["id"], keep="first")
        if player_frames
        else pl.DataFrame()
    )
    return MlbInputs(
        pages=pages,
        gameinfo=gameinfo,
        allplayers=players,
        retrosheet_zips=zips,
        wikipedia=wikipedia,
        wikipedia_lists=lists,
        relay_rows=_read_relay(raw / MLB_RELAY_PATH),
        page_parse_failures=page_failures,
        retrosheet_failures=retro_failures,
        seasons=tuple(sorted(set(seasons))),
    )
