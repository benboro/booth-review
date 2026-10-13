"""Crop tall Sports Media Watch charts into overlapping strips.

This only crops pixels so a transcription session can read a tall chart at full
size instead of a downscaled copy (D-21). There is no OCR, no text extraction and
no image analysis here; the strips are read by a person or a session.

Output stays under ``<root>/<season>/tiles/<chart stem>/`` (gitignored data).
"""

from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

DEFAULT_ROOT = Path("data/incoming/smw")


def _ranges(height: int, tile_height: int, overlap: int) -> list[tuple[int, int]]:
    step = tile_height - overlap
    out: list[tuple[int, int]] = []
    y0 = 0
    while True:
        y1 = min(y0 + tile_height, height)
        out.append((y0, y1))
        if y1 >= height:
            return out
        y0 += step


def tile_chart(
    png: Path,
    out_dir: Path,
    *,
    min_height: int = 2600,
    tile_height: int = 1600,
    overlap: int = 160,
) -> list[tuple[str, int, int]]:
    """Write overlapping strips for a chart taller than ``min_height``.

    Returns ``(tile name, y0, y1)`` rows; empty when the chart is short enough.
    Identical tiles are not rewritten and stale tiles are removed.
    """
    from PIL import Image  # dev dependency, imported lazily

    if not 0 <= overlap < tile_height:
        msg = "overlap must be non-negative and smaller than tile_height"
        raise ValueError(msg)
    with Image.open(png) as img:
        width, height = img.size
        if height <= min_height:
            return []
        out_dir.mkdir(parents=True, exist_ok=True)
        rows: list[tuple[str, int, int]] = []
        for i, (y0, y1) in enumerate(_ranges(height, tile_height, overlap), start=1):
            name = f"tile-{i:02d}.png"
            target = out_dir / name
            tmp = out_dir / f".{name}.tmp"
            img.crop((0, y0, width, y1)).save(tmp, format="PNG")
            if target.exists() and target.read_bytes() == tmp.read_bytes():
                tmp.unlink()
            else:
                tmp.replace(target)
            rows.append((name, y0, y1))
    keep = {r[0] for r in rows}
    for stale in out_dir.glob("tile-*.png"):
        if stale.name not in keep:
            stale.unlink()
    with (out_dir / "tiles.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["tile", "y0", "y1"])
        writer.writerows(rows)
    return rows


def tile_season(season_dir: Path) -> dict[str, int]:
    """Tile every ``*.png`` directly in the season folder; return counts."""
    counts = {"charts": 0, "tiled": 0, "tiles": 0}
    for png in sorted(season_dir.glob("*.png")):
        counts["charts"] += 1
        out_dir = season_dir / "tiles" / png.stem
        rows = tile_chart(png, out_dir)
        if rows:
            counts["tiled"] += 1
            counts["tiles"] += len(rows)
        elif out_dir.exists():
            shutil.rmtree(out_dir)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    season_dir = args.root / str(args.season)
    if not season_dir.is_dir():
        parser.error(f"no chart folder for season {args.season}")
    counts = tile_season(season_dir)
    print(
        f"season {args.season}: {counts['charts']} charts, "
        f"{counts['tiled']} tiled, {counts['tiles']} tiles"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
