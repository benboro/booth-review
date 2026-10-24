"""Synthetic densifier for the MLB Scatter tests (plans 16-04, 16-07, 16-08).

Deep-copies the parsed synthetic ``mlb-data.json`` and rewrites game columns with invented
values so every Scatter placement occurs at least twice. The contract fixture is never
edited. ``SCATTER_CASE`` holds the expected counts per control setting, computed from the
data the helper writes.
"""

from __future__ import annotations

import copy
from typing import Any

# Per game: (viewers, excitement, scope, network, era). Games 0-5 are regular season, 6-7
# 2014 wild card and World Series, 8-10 2019 division and LCS, 11-12 2025 wild card and
# World Series, 13-14 2026 LCS and division series.
_GAMES: list[tuple[int | None, float | None, str | None, int, int | None]] = [
    (1_800_000, 1.0, "game", 0, 0),  # 0 plot
    (2_000_000, 0.5, "game", 0, 0),  # 1 plot
    (None, 0.7, None, 0, None),  # 2 bottom
    (None, 0.8, None, 0, None),  # 3 bottom
    (1_100_000, None, "game", 0, 0),  # 4 left
    (None, None, None, 0, None),  # 5 corner
    (None, 1.2, None, 2, None),  # 6 bottom
    (12_000_000, 2.4, "game", 1, 0),  # 7 plot
    (3_000_000, None, "game", 2, 0),  # 8 left
    (None, None, None, 2, None),  # 9 corner
    (5_500_000, 1.1, "window", 1, 0),  # 10 plot, window figure
    (None, None, None, 3, None),  # 11 corner
    (8_000_000, 2.0, "game", 2, 1),  # 12 plot, second era
    (4_000_000, None, "game", 1, 0),  # 13 left
    (None, 0.9, None, 2, None),  # 14 bottom
]

# The control settings the tests walk: name -> (stype, sround).
CONTROLS: dict[str, tuple[str | None, str | None]] = {
    "all": (None, None),
    "post": ("post", None),
    "post+lcs": ("post", "lcs"),
    "reg": ("reg", None),
}

ESCAPE_NAME = "Zed <b>&amp; Quill"


def densify_scatter(data: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(data)
    g = out["games"]
    assert len(g["date"]) == len(_GAMES), "fixture game count changed"
    for i, (viewers, excitement, scope, network, era) in enumerate(_GAMES):
        g["viewers"][i] = viewers
        g["wp_excitement"][i] = excitement
        g["scope"][i] = scope if viewers is not None else None
        g["network"][i] = network
        g["era"][i] = era if viewers is not None else None
        g["cause"][i] = None if viewers is not None else "none"
    lk = out["lookups"]
    lk["eras"].append(
        {
            "end": None,
            "id": "e2",
            "label": "Second invented era",
            "source_url": "https://example.org/era2",
            "start": None,
        }
    )
    lk["people"].append({"id": "p9", "name": ESCAPE_NAME})
    return out


def _case(data: dict[str, Any]) -> dict[str, dict[str, int]]:
    g = data["games"]
    post_rounds = {"wild_card", "division", "lcs", "world_series", "tiebreak"}
    case: dict[str, dict[str, int]] = {}
    for name, (stype, sround) in CONTROLS.items():
        rows = []
        for i, rnd in enumerate(g["round"]):
            if stype == "reg" and rnd != "regular":
                continue
            if stype == "post" and (rnd not in post_rounds or (sround and rnd != sround)):
                continue
            rows.append(i)
        counts = {"total": len(rows), "plotted": 0, "noRating": 0, "noExcitement": 0, "neither": 0}
        for i in rows:
            has_v = g["viewers"][i] is not None
            has_e = g["wp_excitement"][i] is not None
            if has_v and has_e:
                counts["plotted"] += 1
            elif has_e:
                counts["noRating"] += 1
            elif has_v:
                counts["noExcitement"] += 1
            else:
                counts["neither"] += 1
        case[name] = counts
    return case


def _build_case() -> dict[str, dict[str, int]]:
    import json
    from pathlib import Path

    base = json.loads(
        (Path(__file__).parents[1] / "fixtures" / "contract" / "mlb-data.fixture.json").read_text(
            encoding="utf-8"
        )
    )
    return _case(densify_scatter(base))


SCATTER_CASE: dict[str, dict[str, int]] = _build_case()
