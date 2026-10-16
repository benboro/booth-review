"""MLB game universe, game keys and the per-season postseason map (synthetic only)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import NamedTuple

import polars as pl
import pytest
from mlb_games_support import FIXTURES, build_reference, bundle_zip, gameinfo_row, page_html

from booth_review.config import DataPaths
from booth_review.mlb.games import (
    build_mlb_games,
    build_postseason_map,
    game_key,
    postseason_map,
    write_postseason_map_review,
)
from booth_review.mlb.inputs import Review, load_mlb_inputs
from booth_review.mlb.layout import mlb_506_path, mlb_wikipedia_path, retrosheet_asset_path
from booth_review.mlb.listings import listings_to_telecasts
from booth_review.mlb.reference import MlbReference
from booth_review.mlb.teams import MlbNetworkResolver
from booth_review.sources.wikipedia.mlb_parser import MapProposal

OVERRIDES = "2024,lcs,NL,netb,https://example.invalid/map-2024\n"


class Built(NamedTuple):
    games: pl.DataFrame
    telecasts: pl.DataFrame
    reviews: list[Review]
    ref: MlbReference
    paths: DataPaths


def _row(gid: str, vis: str, home: str, day: str, kind: str, year: int, number: int = 0) -> dict:
    return gameinfo_row(gid, vis, home, day, kind, season=year, number=number)


def _vault(tmp_path: Path) -> DataPaths:
    paths = DataPaths(vault=tmp_path / "vault")
    raw = paths.raw

    def put(relative: str, data: bytes) -> None:
        target = raw / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    rows_2025 = [
        _row("A1", "XAA", "XBB", "20250601", "regular", 2025),
        _row("A2", "XAA", "XBB", "20250602", "allstar", 2025),
        _row("W1", "XCC", "XDD", "20251001", "wildcard", 2025),
        _row("W2", "XCC", "XDD", "20251002", "wildcard", 2025),
        _row("D1", "XAA", "XBB", "20251004", "divisionseries", 2025),
        _row("D2", "XAA", "XBB", "20251005", "divisionseries", 2025),
        _row("S1", "XAA", "XCC", "20251025", "worldseries", 2025),
        _row("T1", "XBB", "XAA", "20250930", "playoff", 2025),
    ]
    put(retrosheet_asset_path("2025csvs.zip"), bundle_zip(rows_2025, 2025))
    rows_2024 = [
        _row("L1", "XCC", "XDD", "20241014", "lcs", 2024),
        _row("L2", "XAA", "XBB", "20241015", "lcs", 2024),
    ]
    put(retrosheet_asset_path("2024csvs.zip"), bundle_zip(rows_2024, 2024))
    rows_2016 = [
        _row("Y1", "XAA", "XBB", "20161007", "divisionseries", 2016),
        _row("Y2", "XCC", "XDD", "20161008", "divisionseries", 2016),
        _row("Y3", "XAA", "XCC", "20161025", "worldseries", 2016),
        _row("Y4", "XCC", "XDD", "20161004", "wildcard", 2016),
    ]
    put(retrosheet_asset_path("2016csvs.zip"), bundle_zip(rows_2016, 2016))
    put(
        mlb_wikipedia_path(2016),
        (FIXTURES / "wikipedia" / "postseason_synthetic.html").read_bytes(),
    )
    # 2025 wild card round page: exact, date-shifted (one day late) and unmatched listings.
    put(
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
                (
                    "Friday, October 03",
                    "Game 2: Charlie Chargers @ Delta Bay",
                    "8:00 PM ET",
                    "TBS",
                    "A B, C D",
                ),
                (
                    "Friday, October 03",
                    "Game 1: Delta Bay @ Charlie Chargers",
                    "9:00 PM ET",
                    "TBS",
                    "A B",
                ),
            ]
        ),
    )
    # 2026: a regular national game and a championship series on a round page.
    put(
        mlb_506_path(2026, "3"),
        page_html([("Friday, June 05", "Alpha City @ Bravo Town", "7:10 PM ET", "MLBN*", "")]),
    )
    put(
        mlb_506_path(2026, "CS"),
        page_html(
            [
                (
                    "Tuesday, October 13",
                    "Game 1: Alpha City @ Bravo Town",
                    "8:00 PM ET",
                    "FOX",
                    "A B, C D",
                ),
                (
                    "Wednesday, October 14",
                    "Game 2: Alpha City @ Bravo Town",
                    "8:00 PM ET",
                    "FOX",
                    "A B, C D",
                ),
            ]
        ),
    )
    return paths


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Built:
    tmp_path = tmp_path_factory.mktemp("games")
    paths = _vault(tmp_path)
    ref = build_reference(tmp_path / "ref", OVERRIDES)
    inputs = load_mlb_inputs(paths, [2016, 2024, 2025, 2026])
    listings = [item for page in inputs.pages.values() for item in page.listings]
    telecasts, reviews = listings_to_telecasts(listings, ref)
    games, final, more = build_mlb_games(inputs, ref, telecasts)
    return Built(games, final, [*reviews, *more], ref, paths)


def _kinds(reviews: list[Review]) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in reviews:
        out[item.kind] = out.get(item.kind, 0) + item.count
    return out


def _game(built: Built, gid: str) -> dict:
    return built.games.filter(pl.col("retrosheet_gid") == gid).row(0, named=True)


def test_game_key_format() -> None:
    assert game_key(date(2026, 6, 5), "alpha", "bravo", 0) == "2026-06-05|alpha|bravo|0"
    assert game_key(date(2026, 6, 5), "alpha", "bravo", 2) == "2026-06-05|alpha|bravo|2"


def test_regular_and_allstar_retrosheet_games_stay_out(built: Built) -> None:
    gids = set(built.games["retrosheet_gid"].drop_nulls())
    assert "A1" not in gids and "A2" not in gids
    assert built.games["game_key"].is_unique().all()


def test_rounds_from_gametype_and_tiebreak_kept(built: Built) -> None:
    assert _game(built, "W1")["round"] == "wild_card"
    assert _game(built, "D1")["round"] == "division"
    assert _game(built, "L1")["round"] == "lcs"
    assert _game(built, "S1")["round"] == "world_series"
    assert _game(built, "T1")["round"] == "tiebreak"


def test_series_league_and_series_game(built: Built) -> None:
    assert _game(built, "W1")["series_league"] == "NL"
    assert _game(built, "D1")["series_league"] == "AL"
    assert _game(built, "S1")["series_league"] is None
    assert _game(built, "T1")["series_league"] is None
    assert [_game(built, g)["series_game"] for g in ("W1", "W2")] == [1, 2]
    assert [_game(built, g)["series_game"] for g in ("D1", "D2")] == [1, 2]


def test_scores_and_home_won(built: Built) -> None:
    game = _game(built, "D1")
    assert (game["away_score"], game["home_score"], game["home_won"]) == (3, 4, True)
    assert game["game_key"] == "2025-10-04|alpha|bravo|0"


def test_2026_games_come_from_506_only(built: Built) -> None:
    current = built.games.filter(pl.col("season") == 2026)
    assert sorted(current["round"].to_list()) == ["lcs", "lcs", "regular"]
    assert current["retrosheet_gid"].null_count() == 3
    lcs = current.filter(pl.col("round") == "lcs").sort("game_date")
    assert lcs["series_league"].to_list() == ["AL", "AL"]
    assert lcs["series_game"].to_list() == [1, 2]
    regular = built.telecasts.filter((pl.col("season") == 2026) & (pl.col("round").is_null()))
    assert regular.height == 1
    assert regular["production"].to_list() == ["simulcast"]


def test_2025_round_listings_attach_exact_then_one_day(built: Built) -> None:
    wc = built.telecasts.filter((pl.col("season") == 2025) & (pl.col("source") == "506"))
    assert wc.height == 2
    exact = wc.filter(pl.col("game_key") == "2025-10-01|charlie|delta|0").row(0, named=True)
    assert exact["date_shift"] is False
    shifted = wc.filter(pl.col("game_key") == "2025-10-02|charlie|delta|0").row(0, named=True)
    assert shifted["date_shift"] is True
    assert str(shifted["game_date"]) == "2025-10-02"  # the Retrosheet date is kept
    assert shifted["network_id"] == "tbs"
    kinds = _kinds(built.reviews)
    assert kinds["date_shift"] == 1
    assert kinds["unmatched_round_listing"] == 1


def test_never_shift_beyond_one_day(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    ref = build_reference(tmp_path / "ref")
    zip_path = paths.raw / retrosheet_asset_path("2025csvs.zip")
    zip_path.parent.mkdir(parents=True)
    zip_path.write_bytes(bundle_zip([_row("W1", "XCC", "XDD", "20251001", "wildcard", 2025)], 2025))
    page = paths.raw / mlb_506_path(2025, "WC")
    page.parent.mkdir(parents=True)
    page.write_bytes(
        page_html(
            [
                (
                    "Friday, October 03",
                    "Game 1: Charlie Chargers @ Delta Bay",
                    "8:00 PM ET",
                    "TBS",
                    "A B",
                )
            ]
        )
    )
    inputs = load_mlb_inputs(paths, [2025])
    telecasts, _ = listings_to_telecasts(
        [item for p in inputs.pages.values() for item in p.listings], ref
    )
    _, final, reviews = build_mlb_games(inputs, ref, telecasts)
    assert final.filter(pl.col("source") == "506").is_empty()
    assert _kinds(reviews)["unmatched_round_listing"] == 1


def test_map_telecasts_from_wikipedia_and_overrides(built: Built) -> None:
    mapped = built.telecasts.filter(pl.col("source") == "map")
    by_gid = dict(
        zip(
            built.games.filter(pl.col("retrosheet_gid").is_not_null())["game_key"].to_list(),
            built.games.filter(pl.col("retrosheet_gid").is_not_null())["retrosheet_gid"].to_list(),
            strict=True,
        )
    )
    networks = {by_gid[k]: n for k, n in zip(mapped["game_key"], mapped["network_id"], strict=True)}
    assert networks["Y1"] == "neta"  # division AL, from the Wikipedia proposal
    assert networks["Y3"] == "neta"  # world series, league-less row
    assert networks["Y4"] == "netb"  # wild card falls back to the league-less row
    assert networks["L1"] == "netb"  # 2024 NL championship series, from the override
    assert "Y2" not in networks  # division NL has no map row: review, not a guess
    assert "L2" not in networks  # 2024 AL championship series has no map row
    assert mapped["crew_names"].list.len().max() == 0
    assert set(mapped["production"]) == {"own"}
    assert _kinds(built.reviews)["no_outlet"] >= 2


def test_every_postseason_game_has_outlet_or_review(built: Built) -> None:
    retro = built.games.filter(pl.col("retrosheet_gid").is_not_null())
    with_outlet = set(built.telecasts["game_key"])
    missing = retro.filter(~pl.col("game_key").is_in(list(with_outlet))).height
    outlets_missing = sum(r.count for r in built.reviews if r.kind == "no_outlet")
    # 2025 tiebreak/division/world series games lack both a 506 row and a map row.
    assert missing == outlets_missing


def _proposal(rnd: str, league: str | None, raw: str) -> MapProposal:
    return MapProposal(2030, rnd, league, raw, "https://example.invalid/w", "h")


def test_map_override_wins_and_ambiguity_leaves_outlet_null(tmp_path: Path) -> None:
    ref = build_reference(
        tmp_path / "ref", "2030,division,AL,netc,https://example.invalid/override\n"
    )
    resolver = MlbNetworkResolver.from_reference(ref)
    proposals = [
        _proposal("DS", "AL", "NetA"),
        _proposal("CS", "NL", "NetA"),
        _proposal("CS", "NL", "NetB"),
        _proposal("WS", None, "NetB"),
    ]
    rows, reviews = postseason_map(2030, proposals, ref.map_overrides, resolver)
    by_key = {(r.round, r.league): r for r in rows}
    assert by_key[("division", "AL")].network_id == "netc"
    assert by_key[("division", "AL")].source == "override"
    assert by_key[("lcs", "NL")].network_id is None
    assert by_key[("world_series", None)].network_id == "netb"
    assert [r.kind for r in reviews] == ["ambiguous_map"]


def test_unresolved_proposal_network_is_reviewed(tmp_path: Path) -> None:
    ref = build_reference(tmp_path / "ref")
    resolver = MlbNetworkResolver.from_reference(ref)
    rows, reviews = postseason_map(
        2030, [_proposal("WS", None, "Unknown Net")], ref.map_overrides, resolver
    )
    assert rows[0].network_id is None
    assert {r.kind for r in reviews} == {"unresolved_map_network", "no_map_network"}


def test_map_review_file_is_written(built: Built) -> None:
    inputs = load_mlb_inputs(built.paths, [2016, 2024])
    rows, _ = build_postseason_map(inputs, built.ref)
    target = write_postseason_map_review(built.paths, rows)
    assert target.name == "review_mlb_postseason_map.csv"
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "season,round,league,network_id,source,source_url"
    assert any(line.startswith("2024,lcs,NL,netb,override,") for line in lines)
    assert any(line.startswith("2016,division,AL,neta,wikipedia,") for line in lines)


def test_2026_round_listing_attaches_to_a_retrosheet_game_once_it_exists(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path / "vault")
    ref = build_reference(tmp_path / "ref")
    zip_path = paths.raw / retrosheet_asset_path("2026csvs.zip")
    zip_path.parent.mkdir(parents=True)
    zip_path.write_bytes(
        bundle_zip(
            [
                _row("Z1", "XAA", "XBB", "20261014", "lcs", 2026),
                _row("Z2", "XAA", "XBB", "20261015", "lcs", 2026),
            ],
            2026,
        )
    )
    page = paths.raw / mlb_506_path(2026, "CS")
    page.parent.mkdir(parents=True)
    page.write_bytes(
        page_html(
            [
                (
                    "Tuesday, October 13",
                    "Game 1: Alpha City @ Bravo Town",
                    "8:00 PM ET",
                    "FOX",
                    "A B, C D",
                ),
                (
                    "Thursday, October 15",
                    "Game 2: Alpha City @ Bravo Town",
                    "8:00 PM ET",
                    "FOX",
                    "A B, C D",
                ),
            ]
        )
    )
    inputs = load_mlb_inputs(paths, [2026])
    telecasts, _ = listings_to_telecasts(
        [item for p in inputs.pages.values() for item in p.listings], ref
    )
    games, final, reviews = build_mlb_games(inputs, ref, telecasts)

    # One game per Retrosheet game: the 506 listings join it instead of adding a copy.
    assert sorted(games["game_key"].to_list()) == [
        "2026-10-14|alpha|bravo|0",
        "2026-10-15|alpha|bravo|0",
    ]
    assert games["retrosheet_gid"].null_count() == 0
    listed = final.filter(pl.col("source") == "506").sort("game_date")
    assert listed["game_key"].to_list() == games.sort("game_date")["game_key"].to_list()
    assert listed["date_shift"].to_list() == [True, False]
    assert final.height == 2
    assert _kinds(reviews)["date_shift"] == 1


def _series_game(day: int, number: int | None) -> dict:
    return {
        "game_key": f"k{day}",
        "season": 2026,
        "game_date": date(2026, 10, day),
        "away_club": "alpha",
        "home_club": "charlie",
        "game_number": 0,
        "round": "world_series",
        "series_league": None,
        "series_game": number,
    }


def test_series_game_numbers_by_index_only_when_that_is_safe(tmp_path: Path) -> None:
    from booth_review.mlb.games import _number_series

    ref = build_reference(tmp_path / "ref")

    def numbered(*explicit: int | None) -> tuple[list[int | None], list[Review]]:
        games = {f"k{d}": _series_game(d, n) for d, n in enumerate(explicit, start=24)}
        reviews: list[Review] = []
        _number_series(games, ref, reviews)
        return [g["series_game"] for g in games.values()], reviews

    # No explicit numbers: date order.
    assert numbered(None, None, None) == ([1, 2, 3], [])
    # An unprefixed game between prefixed ones fits the gap-free sequence.
    assert numbered(1, None, 3) == ([1, 2, 3], [])
    # "Game 3" is listed first: filling the rest by position would repeat or skip numbers.
    values, reviews = numbered(3, None)
    assert values == [3, None]
    assert [(r.source, r.kind) for r in reviews] == [("games", "series_game_unknown")]
    # Everything prefixed keeps 506's numbers even with a game missing.
    assert numbered(1, 2, 4) == ([1, 2, 4], [])


def test_half_parsed_retrosheet_bundle_is_dropped_whole(tmp_path: Path) -> None:
    import io
    import zipfile

    paths = DataPaths(vault=tmp_path / "vault")
    good = paths.raw / retrosheet_asset_path("2024csvs.zip")
    good.parent.mkdir(parents=True)
    good.write_bytes(bundle_zip([_row("L1", "XCC", "XDD", "20241014", "lcs", 2024)], 2024))
    # 2025 holds game info but no allplayers member, so the second read fails.
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        source = zipfile.ZipFile(
            io.BytesIO(bundle_zip([_row("W1", "XCC", "XDD", "20251001", "wildcard", 2025)], 2025))
        )
        archive.writestr("2025gameinfo.csv", source.read("2025gameinfo.csv"))
    (paths.raw / retrosheet_asset_path("2025csvs.zip")).write_bytes(out.getvalue())

    inputs = load_mlb_inputs(paths, [2024, 2025])

    assert inputs.retrosheet_failures == 1
    assert sorted(inputs.retrosheet_zips) == [2024]
    assert set(inputs.gameinfo["season"].to_list()) == {2024}


def test_round_wide_override_replaces_league_proposals(tmp_path: Path) -> None:
    ref = build_reference(
        tmp_path / "ref",
        "2030,lcs,,netc,https://example.invalid/round\n"
        "2030,division,AL,netb,https://example.invalid/al\n",
    )
    resolver = MlbNetworkResolver.from_reference(ref)
    proposals = [
        _proposal("CS", "AL", "NetA"),
        _proposal("CS", "NL", "NetA"),
        _proposal("CS", "NL", "NetB"),
        _proposal("DS", "AL", "NetA"),
        _proposal("DS", "NL", "NetA"),
    ]
    rows, reviews = postseason_map(2030, proposals, ref.map_overrides, resolver)
    by_key = {(r.round, r.league): r for r in rows}

    # The blank-league override reaches both leagues, including the ambiguous NL proposal.
    assert by_key[("lcs", "AL")].network_id == by_key[("lcs", "NL")].network_id == "netc"
    assert by_key[("lcs", "NL")].source == "override"
    # A league-specific override still wins for its own league; the other keeps Wikipedia's.
    assert by_key[("division", "AL")].network_id == "netb"
    assert by_key[("division", "NL")].network_id == "neta"
    assert reviews == []
