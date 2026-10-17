"""Retrosheet loader: safe zip reading, column projection, gametype map, cache."""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from pathlib import Path

import polars as pl
import pytest

from booth_review.config import DataPaths
from booth_review.errors import ParseError
from booth_review.sources.retrosheet import loader

FIXTURES = Path(__file__).parent / "fixtures" / "mlb" / "retrosheet"
DOC = Path(__file__).parent.parent / "docs" / "sources" / "retrosheet.md"


def _fixture(name: str) -> bytes:
    return (FIXTURES / f"{name}_synthetic.csv").read_bytes()


def make_zip(members: dict[str, bytes] | None = None, year: int = 2020) -> bytes:
    """A synthetic season bundle built from the synthetic fixtures."""
    if members is None:
        members = {f"{year}{k}.csv": _fixture(k) for k in ("gameinfo", "plays", "allplayers")}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _doc_columns(member: str) -> list[str]:
    line = next(
        ln
        for ln in DOC.read_text(encoding="utf-8").splitlines()
        if ln.startswith(f"- `{member}.csv`")
    )
    body = line.split(":", 1)[1]
    return [t.strip(" .") for t in body.split(",") if re.fullmatch(r"\s*[a-z_0-9]+\.?\s*", t)]


def _header(name: str) -> list[str]:
    return _fixture(name).split(b"\n", 1)[0].decode().split(",")


def test_fixture_headers_match_recorded_doc() -> None:
    assert _header("gameinfo") == _doc_columns("gameinfo")
    assert _header("allplayers") == _doc_columns("allplayers")
    plays_header = _header("plays")
    for column in _doc_columns("plays"):
        if re.fullmatch(r"[a-z_]+", column):
            assert column in plays_header
    for tup, name in (
        (loader.GAMEINFO_COLUMNS, "gameinfo"),
        (loader.PLAYS_COLUMNS, "plays"),
        (loader.ALLPLAYERS_COLUMNS, "allplayers"),
    ):
        assert set(tup) <= set(_doc_columns(name))
        assert set(tup) <= set(_header(name))


def test_open_member_returns_single_member() -> None:
    assert loader.open_member(make_zip(), "gameinfo") == _fixture("gameinfo")


def test_open_member_rejects_traversal() -> None:
    bundle = make_zip({"../2020plays.csv": b"x", "2020plays.csv": b"y"})
    with pytest.raises(ParseError, match="unsafe"):
        loader.open_member(bundle, "plays")
    with pytest.raises(ParseError, match="unsafe"):
        loader.open_member(make_zip({"/2020plays.csv": b"x"}), "plays")


def test_open_member_rejects_oversized_member(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loader, "RETROSHEET_MAX_UNCOMPRESSED_BYTES", 10)
    with pytest.raises(ParseError, match="size cap"):
        loader.open_member(make_zip(), "plays")


def test_open_member_rejects_duplicate_member() -> None:
    buffer = io.BytesIO()
    with pytest.warns(UserWarning), zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("2020plays.csv", b"a")
        archive.writestr("2020plays.csv", b"b")
    with pytest.raises(ParseError, match="more than one"):
        loader.open_member(buffer.getvalue(), "plays")


def test_open_member_missing_member() -> None:
    with pytest.raises(ParseError, match="no plays member"):
        loader.open_member(make_zip({"2020gameinfo.csv": b"x"}), "plays")


def test_read_gameinfo_projects_and_maps_rounds() -> None:
    frame = loader.read_gameinfo(make_zip())
    assert frame.columns == [*loader.GAMEINFO_COLUMNS, "round"]
    assert frame["round"].to_list() == ["regular", "wild_card", "regular"]
    assert frame["number"].to_list() == [0, 0, 2]
    assert frame.schema["vruns"] == pl.Int32


def test_gametype_map_covers_recorded_words() -> None:
    recorded = {"regular", "allstar", "wildcard", "divisionseries", "lcs", "worldseries", "playoff"}
    assert set(loader.GAMETYPE_ROUNDS) == recorded
    assert loader.GAMETYPE_ROUNDS["playoff"] == "tiebreak"


def test_unknown_gametype_fails_naming_code_only() -> None:
    text = _fixture("gameinfo").decode().replace(",wildcard,", ",mystery,")
    bundle = make_zip({"2020gameinfo.csv": text.encode()})
    with pytest.raises(ParseError, match="unknown gametype mystery"):
        loader.read_gameinfo(bundle)


def test_missing_column_names_only_that_column() -> None:
    text = _fixture("allplayers").decode().replace("id,last,first", "id,surname,first", 1)
    with pytest.raises(ParseError) as err:
        loader.read_allplayers(make_zip({"2020allplayers.csv": text.encode()}))
    assert str(err.value) == "retrosheet allplayers: missing column last"


def test_read_plays_preserves_file_order() -> None:
    frame = loader.read_plays(make_zip(), 2020)
    assert frame.columns == ["seq", *loader.PLAYS_COLUMNS, "season"]
    assert frame["seq"].to_list() == list(range(frame.height))
    assert frame["gid"].to_list()[0] == "XBB202004010"
    assert frame["gid"].to_list() == sorted(frame["gid"].to_list())
    assert frame["bat_f"].to_list()[0] == 2


def test_read_allplayers_names() -> None:
    frame = loader.read_allplayers(make_zip())
    assert frame.columns == ["id", "last", "first"]
    assert "abat01" in frame["id"].to_list()


def test_cached_slim_plays_reuses_matching_sha(tmp_path: Path) -> None:
    paths = DataPaths(vault=tmp_path)
    bundle = make_zip()
    first = loader.cached_slim_plays(paths, 2020, bundle)
    target = paths.interim / "mlb_plays_2020.parquet"
    assert target.is_file()
    stamp = target.stat().st_mtime_ns
    second = loader.cached_slim_plays(paths, 2020, bundle)
    assert target.stat().st_mtime_ns == stamp
    assert second.equals(first)
    # a different archive invalidates the cache
    other = make_zip({"2020plays.csv": _fixture("plays")[:-1] + b"\n", "2020gameinfo.csv": b"x"})
    loader.cached_slim_plays(paths, 2020, other)
    sidecar = target.with_name(target.name + ".sha256")
    assert sidecar.read_text(encoding="utf-8").strip() == hashlib.sha256(other).hexdigest()
