"""Bowl-crosswalk pipeline behavior (04.2-04): the private review file, the
loud count-only failure, and the unknown-name count. Synthetic data only.
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from test_cli_build import _seed_build_raw

from booth_review.build.bowls import BowlEntry
from booth_review.build.games import GAMES_SCHEMA
from booth_review.build.pipeline import run_build
from booth_review.build.tables import REVIEW_BOWLS_COLUMNS, bowl_review_rows
from booth_review.build.telecasts import TELECASTS_SCHEMA
from booth_review.config import DataPaths
from booth_review.errors import BowlCrosswalkError

_REFERENCE_FIXTURES = Path(__file__).parent / "fixtures" / "reference"
_SENTINEL = "SENTINEL ZEBRA HARBOR BOWL NOTE"


def _game(game_id: int, season: int, game_type: str, note: str | None = None) -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(GAMES_SCHEMA)
    row.update(
        game_id=game_id,
        season=season,
        date_et=date(season, 12, 30),
        game_type=game_type,
        playoff_round="quarterfinal" if game_type == "playoff" else None,
        away_team="Fixture Away",
        home_team="Fixture Home",
        notes=note,
    )
    return row


def _telecast(game_id: int, plotted: bool = True) -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(TELECASTS_SCHEMA)
    row.update(telecast_id=f"{game_id}-x", game_id=game_id, plotted=plotted)
    return row


def test_bowl_review_rows_lists_only_missing_plotted_postseason_games() -> None:
    games = pl.DataFrame(
        [
            _game(9, 2025, "bowl", _SENTINEL),
            _game(3, 2024, "playoff"),
            _game(4, 2024, "bowl"),  # has a crosswalk row
            _game(5, 2024, "regular"),
            _game(6, 2024, "bowl"),  # unplotted
        ],
        schema=GAMES_SCHEMA,
    )
    telecasts = pl.DataFrame(
        [
            _telecast(9),
            _telecast(9),  # duplicate telecast for the same game
            _telecast(3),
            _telecast(4),
            _telecast(5),
            _telecast(6, plotted=False),
        ],
        schema=TELECASTS_SCHEMA,
    )
    rows = bowl_review_rows(telecasts, games, {4: BowlEntry(None, None, True)})
    assert [r["cfbd_game_id"] for r in rows] == [3, 9]
    assert set(rows[0]) == set(REVIEW_BOWLS_COLUMNS)
    assert rows[1]["raw_note"] == _SENTINEL


def _vault_with_sentinel_note(git_vault: DataPaths, tmp_path: Path, bowls_rows: str) -> Path:
    _seed_build_raw(git_vault)
    games_file = git_vault.raw / "cfbd" / "games" / "2025.json"
    games = json.loads(games_file.read_text(encoding="utf-8"))
    for game in games:
        if game["id"] == 500007:
            game["notes"] = _SENTINEL
    games_file.write_text(json.dumps(games), encoding="utf-8")

    reference = tmp_path / "reference_ext"
    shutil.copytree(_REFERENCE_FIXTURES, reference)
    with (reference / "networks.csv").open("a", encoding="utf-8", newline="") as fh:
        fh.write("ECN,ecn,Example Cable Network,family-ecn,cable,main,,,\n")
        fh.write("ECN2,ecn2,Example Cable Network 2,family-ecn,cable,main,,,\n")
        fh.write("ESPN,espn,ESPN,family-espn,cable,main,,,\n")
        fh.write("ESPN2,espn2,ESPN2,family-espn,cable,main,,,\n")
        fh.write("ESPNU,espnu,ESPNU,family-espn,cable,main,,,\n")
        fh.write("ESPN Deportes,espn-deportes,ESPN Deportes,family-espn,cable,spanish,,,\n")
    (reference / "bowls.csv").write_text(
        "cfbd_game_id,official_name,core_name,at_bowl,franchise\n" + bowls_rows, encoding="utf-8"
    )
    return reference


def test_missing_crosswalk_row_writes_review_file_then_fails_count_only(
    git_vault: DataPaths, tmp_path: Path
) -> None:
    reference = _vault_with_sentinel_note(git_vault, tmp_path, "")
    with pytest.raises(BowlCrosswalkError) as info:
        run_build(git_vault, reference, commit=False, accept_baseline=False)
    assert _SENTINEL not in str(info.value)

    review = (git_vault.vault / "interim" / "review_bowls.csv").read_text(encoding="utf-8")
    assert "500007" in review
    assert _SENTINEL in review  # private vault file only
    assert not (git_vault.vault / "processed" / "site-data.json").exists()
    assert not (git_vault.vault / "audit" / "build_baseline.csv").exists()


def test_unknown_name_is_counted(git_vault: DataPaths, tmp_path: Path) -> None:
    reference = _vault_with_sentinel_note(git_vault, tmp_path, "500007,,,true,\n")
    outcome = run_build(git_vault, reference, commit=False, accept_baseline=False)
    assert outcome.counts["bowl_names_unknown"] == 1
    site = (git_vault.vault / "processed" / "site-data.json").read_text(encoding="utf-8")
    assert _SENTINEL not in site


def test_no_unknown_names_counts_zero(git_vault: DataPaths, tmp_path: Path) -> None:
    reference = _vault_with_sentinel_note(
        git_vault, tmp_path, "500007,Zebra Ridge Bowl,Ridge Bowl,true,ridge-bowl\n"
    )
    outcome = run_build(git_vault, reference, commit=False, accept_baseline=False)
    assert outcome.counts["bowl_names_unknown"] == 0
