from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PIL")

from PIL import Image

from booth_review.sources.smw.tiles import main, tile_chart, tile_season


def _png(path: Path, height: int, width: int = 400) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), "white").save(path)


def test_tall_chart_ranges_and_csv(tmp_path: Path) -> None:
    png = tmp_path / "c.png"
    _png(png, 5000)
    out = tmp_path / "tiles" / "c"
    rows = tile_chart(png, out)
    assert [(y0, y1) for _, y0, y1 in rows] == [
        (0, 1600),
        (1440, 3040),
        (2880, 4480),
        (4320, 5000),
    ]
    assert (out / "tiles.csv").read_text().splitlines()[0] == "tile,y0,y1"
    with Image.open(out / "tile-04.png") as tile:
        assert tile.size == (400, 680)


def test_short_chart_writes_nothing(tmp_path: Path) -> None:
    png = tmp_path / "c.png"
    _png(png, 2000)
    out = tmp_path / "tiles" / "c"
    assert tile_chart(png, out) == []
    assert not out.exists()


def test_idempotent_and_removes_stale(tmp_path: Path) -> None:
    png = tmp_path / "c.png"
    _png(png, 5000)
    out = tmp_path / "tiles" / "c"
    tile_chart(png, out)
    first = out / "tile-02.png"
    before = first.stat().st_mtime_ns
    (out / "tile-09.png").write_bytes(b"stale")
    tile_chart(png, out)
    assert first.stat().st_mtime_ns == before
    assert not (out / "tile-09.png").exists()


def test_season_and_main_stay_under_tiles(tmp_path: Path) -> None:
    season = tmp_path / "2099"
    _png(season / "tall.png", 3000)
    _png(season / "short.png", 1000)
    assert tile_season(season) == {"charts": 2, "tiled": 1, "tiles": 2}
    assert main(["--season", "2099", "--root", str(tmp_path)]) == 0
    assert sorted(p.name for p in (season / "tiles").iterdir()) == ["tall"]
