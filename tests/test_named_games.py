"""Franchise grouping and first-meeting rivalry resolution on synthetic data (D-07, D-13)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import polars as pl
import pytest

from booth_review.build.bowls import BowlEntry
from booth_review.build.named_games import (
    Franchise,
    build_franchises,
    check_game_slugs,
    resolve_rivalry_games,
)
from booth_review.build.rivalries import Rivalry
from booth_review.errors import BowlCrosswalkError, VaultStateError

NF, LV = "Northfield", "Lakeview"


def _games(rows: list[dict[str, Any]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={
            "game_id": pl.Int64,
            "season": pl.Int64,
            "start_utc": pl.Datetime("us", "UTC"),
            "home_team": pl.String,
            "away_team": pl.String,
            "home_id": pl.Int64,
            "away_id": pl.Int64,
            "game_type": pl.String,
            "notes": pl.String,
        },
    )


def _g(
    game_id: int,
    when: datetime,
    *,
    home: tuple[str, int] = (NF, 1),
    away: tuple[str, int] = (LV, 2),
    game_type: str = "regular",
    notes: str | None = None,
) -> dict[str, Any]:
    return {
        "game_id": game_id,
        "season": when.year,
        "start_utc": when,
        "home_team": home[0],
        "away_team": away[0],
        "home_id": home[1],
        "away_id": away[1],
        "game_type": game_type,
        "notes": notes,
    }


def _riv(**kw: Any) -> Rivalry:
    base: dict[str, Any] = {
        "rivalry_id": "lake-cup",
        "name": "Lake Cup",
        "team_a": NF,
        "team_b": LV,
        "season_from": None,
        "season_to": None,
    }
    base.update(kw)
    return Rivalry(**base)


def _bowl(core: str | None, franchise: str | None, at_bowl: bool = True) -> BowlEntry:
    official = f"{core} presented" if core else None
    return BowlEntry(official, core, at_bowl, franchise)


# -- franchises -------------------------------------------------------------------------------


def test_franchise_latest_name_and_former() -> None:
    entries = {
        1: _bowl("Bayside Bowl", "harbor-bowl"),
        2: _bowl("Harbor Bowl", "harbor-bowl"),
        3: _bowl("Summit Bowl", "summit-bowl"),
    }
    result = build_franchises(entries, {1: 2018, 2: 2021, 3: 2021})
    assert result == {
        "harbor-bowl": Franchise("harbor-bowl", "Harbor Bowl", ("Bayside Bowl",)),
        "summit-bowl": Franchise("summit-bowl", "Summit Bowl", ()),
    }


def test_franchise_renamed_back_excludes_label_from_former() -> None:
    entries = {
        1: _bowl("Bayside Bowl", "harbor-bowl"),
        2: _bowl("Harbor Bowl", "harbor-bowl"),
        3: _bowl("Bayside Bowl", "harbor-bowl"),
    }
    result = build_franchises(entries, {1: 2016, 2: 2018, 3: 2020})
    assert result["harbor-bowl"].name == "Bayside Bowl"
    assert result["harbor-bowl"].former == ("Harbor Bowl",)


def test_franchise_two_games_one_season_fails_count_only() -> None:
    entries = {1: _bowl("Bayside Bowl", "harbor-bowl"), 2: _bowl("Harbor Bowl", "harbor-bowl")}
    with pytest.raises(VaultStateError) as exc:
        build_franchises(entries, {1: 2021, 2: 2021})
    assert str(exc.value) == "bowls.csv: 1 franchise(s) with two games in one season"
    assert "Bowl" not in str(exc.value)


def test_franchise_missing_slug_fails_count_only() -> None:
    entries = {1: _bowl("Bayside Bowl", None)}
    with pytest.raises(BowlCrosswalkError) as exc:
        build_franchises(entries, {1: 2021})
    assert str(exc.value) == "telecasts: 1 plotted bowl row(s) without a franchise"


def test_franchise_ignores_unnamed_not_at_bowl_and_unplotted() -> None:
    entries = {
        1: _bowl(None, None),
        2: BowlEntry(None, None, False),
        3: _bowl("Bayside Bowl", None),  # not plotted
        4: _bowl("Summit Bowl", "summit-bowl"),
    }
    result = build_franchises(entries, {1: 2021, 2: 2021, 4: 2021})
    assert list(result) == ["summit-bowl"]


# -- rivalries --------------------------------------------------------------------------------


def test_title_rematch_is_demoted() -> None:
    # A title game without a title note (seasons before 2022): the fallback rule.
    games = _games(
        [
            _g(10, datetime(2024, 9, 7, 17, tzinfo=UTC)),
            _g(11, datetime(2024, 12, 7, 17, tzinfo=UTC)),
        ]
    )
    res = resolve_rivalry_games(games, [_riv()])
    assert res.by_game == {10: "lake-cup"}
    assert res.rematches_demoted == 1


# Invented notes text: only the case-insensitive "championship" test matters.
_TITLE_NOTE = "Harbor Conference CHAMPIONSHIP Game"


def test_title_game_before_rivalry_game_is_excluded() -> None:
    # The title game is played a week before the rivalry game (both "regular").
    games = _games(
        [
            _g(10, datetime(2026, 12, 5, 17, tzinfo=UTC), notes=_TITLE_NOTE),
            _g(11, datetime(2026, 12, 12, 20, tzinfo=UTC)),
        ]
    )
    res = resolve_rivalry_games(games, [_riv()])
    assert res.by_game == {11: "lake-cup"}
    assert res.title_games_excluded == 1
    assert res.rematches_demoted == 0


def test_title_game_as_only_meeting_is_not_tagged() -> None:
    games = _games([_g(10, datetime(2025, 12, 6, 17, tzinfo=UTC), notes=_TITLE_NOTE)])
    res = resolve_rivalry_games(games, [_riv()])
    assert res.by_game == {}
    assert res.title_games_excluded == 1
    assert res.rematches_demoted == 0


def test_title_game_after_rivalry_game_is_excluded_not_demoted() -> None:
    games = _games(
        [
            _g(10, datetime(2024, 10, 12, 17, tzinfo=UTC)),
            _g(11, datetime(2024, 12, 7, 17, tzinfo=UTC), notes=_TITLE_NOTE.lower()),
        ]
    )
    res = resolve_rivalry_games(games, [_riv()])
    assert res.by_game == {10: "lake-cup"}
    assert res.title_games_excluded == 1
    assert res.rematches_demoted == 0


def test_other_notes_do_not_exclude() -> None:
    games = _games([_g(10, datetime(2024, 9, 7, 17, tzinfo=UTC), notes="Harbor Classic")])
    res = resolve_rivalry_games(games, [_riv()])
    assert res.by_game == {10: "lake-cup"}
    assert res.title_games_excluded == 0


def test_title_note_on_other_pair_not_counted() -> None:
    games = _games(
        [
            _g(10, datetime(2024, 9, 7, 17, tzinfo=UTC)),
            _g(
                11,
                datetime(2024, 12, 7, 17, tzinfo=UTC),
                home=("Eastport", 3),
                notes=_TITLE_NOTE,
            ),
        ]
    )
    res = resolve_rivalry_games(games, [_riv()])
    assert res.by_game == {10: "lake-cup"}
    assert res.title_games_excluded == 0


def test_bowl_meeting_not_tagged_regular_is() -> None:
    games = _games(
        [
            _g(10, datetime(2023, 11, 25, 17, tzinfo=UTC)),
            _g(11, datetime(2023, 12, 30, 17, tzinfo=UTC), game_type="bowl"),
        ]
    )
    res = resolve_rivalry_games(games, [_riv()])
    assert res.by_game == {10: "lake-cup"}
    assert res.rematches_demoted == 0


def test_lone_bowl_meeting_not_tagged() -> None:
    games = _games([_g(11, datetime(2023, 12, 30, 17, tzinfo=UTC), game_type="bowl")])
    res = resolve_rivalry_games(games, [_riv()])
    assert res.by_game == {}
    assert res.rematches_demoted == 0


def test_sorted_by_start_not_row_order() -> None:
    games = _games(
        [
            _g(11, datetime(2024, 12, 7, 17, tzinfo=UTC)),
            _g(10, datetime(2024, 9, 7, 17, tzinfo=UTC)),
        ]
    )
    assert resolve_rivalry_games(games, [_riv()]).by_game == {10: "lake-cup"}


def test_equal_start_breaks_on_lower_game_id() -> None:
    when = datetime(2024, 9, 7, 17, tzinfo=UTC)
    games = _games([_g(12, when), _g(9, when)])
    res = resolve_rivalry_games(games, [_riv()])
    assert res.by_game == {9: "lake-cup"}
    assert res.rematches_demoted == 1


def test_swapped_home_away_tags_both_seasons() -> None:
    games = _games(
        [
            _g(10, datetime(2022, 9, 7, 17, tzinfo=UTC)),
            _g(11, datetime(2023, 9, 7, 17, tzinfo=UTC), home=(LV, 2), away=(NF, 1)),
        ]
    )
    assert resolve_rivalry_games(games, [_riv()]).by_game == {10: "lake-cup", 11: "lake-cup"}


def test_season_limits_apply() -> None:
    games = _games(
        [
            _g(10, datetime(2023, 9, 7, 17, tzinfo=UTC)),
            _g(11, datetime(2024, 9, 7, 17, tzinfo=UTC)),
        ]
    )
    res = resolve_rivalry_games(games, [_riv(season_from=2024)])
    assert res.by_game == {11: "lake-cup"}
    res = resolve_rivalry_games(games, [_riv(season_to=2023)])
    assert res.by_game == {10: "lake-cup"}


def test_first_meeting_in_games_table_only_makes_later_a_rematch() -> None:
    # Game 10 may be unrated downstream, but the rule runs over every game.
    games = _games(
        [
            _g(10, datetime(2024, 9, 7, 17, tzinfo=UTC)),
            _g(11, datetime(2024, 12, 7, 17, tzinfo=UTC)),
        ]
    )
    res = resolve_rivalry_games(games, [_riv()])
    assert 11 not in res.by_game


def test_other_pairs_are_ignored() -> None:
    games = _games(
        [
            _g(10, datetime(2024, 9, 7, 17, tzinfo=UTC)),
            _g(11, datetime(2024, 9, 8, 17, tzinfo=UTC), home=("Eastport", 3), away=(LV, 2)),
        ]
    )
    res = resolve_rivalry_games(games, [_riv()])
    assert res.by_game == {10: "lake-cup"}
    assert res.rematches_demoted == 0


def test_team_not_in_games_fails() -> None:
    games = _games([_g(10, datetime(2024, 9, 7, 17, tzinfo=UTC))])
    with pytest.raises(VaultStateError) as exc:
        resolve_rivalry_games(games, [_riv(team_b="Nowhere")])
    assert str(exc.value) == "rivalries.csv: 1 team name(s) not found in the games table"
    assert "Nowhere" not in str(exc.value)


def test_team_with_two_ids_fails() -> None:
    games = _games(
        [
            _g(10, datetime(2024, 9, 7, 17, tzinfo=UTC)),
            _g(11, datetime(2024, 9, 14, 17, tzinfo=UTC), home=(NF, 99)),
        ]
    )
    with pytest.raises(VaultStateError) as exc:
        resolve_rivalry_games(games, [_riv()])
    assert str(exc.value) == "rivalries.csv: 1 team name(s) map to more than one team id"
    assert NF not in str(exc.value)


def test_duplicate_id_pair_fails() -> None:
    games = _games([_g(10, datetime(2024, 9, 7, 17, tzinfo=UTC))])
    rivals = [_riv(), _riv(rivalry_id="other-cup", name="Other Cup", team_a=LV, team_b=NF)]
    with pytest.raises(VaultStateError) as exc:
        resolve_rivalry_games(games, rivals)
    assert str(exc.value) == "rivalries.csv: 1 rivalr(ies) share a team pair"


# -- slugs ------------------------------------------------------------------------------------


def test_slug_collision_fails() -> None:
    with pytest.raises(VaultStateError) as exc:
        check_game_slugs({"harbor-bowl"}, ["lakeshore", "harbor-bowl"])
    assert str(exc.value) == "named games: 1 slug(s) collide or use a reserved CFP slug"


def test_reserved_slug_fails() -> None:
    with pytest.raises(VaultStateError):
        check_game_slugs(set(), ["cfp-semifinal"])


def test_distinct_slugs_pass() -> None:
    check_game_slugs({"harbor-bowl"}, ["lake-cup"])
