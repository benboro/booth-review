"""Tests for spike/names.py (team normalization, significant tokens, the
optional crosswalk lookup) and spike/selection.py (candidate flags, the
20-game selection).

Fixtures: tests/fixtures/spike/cfbd_games_2025.json (30 synthetic games) and
tests/fixtures/spike/rr_sitemap.xml (22 synthetic RR sitemap entries), all
invented teams and telecast ids (D-07). No real team, person, or figure
appears in this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from booth_review.sources.cfbd.parser import CfbdGame, parse_games
from booth_review.sources.ratingsref.sitemap import parse_sitemap
from booth_review.spike.names import load_crosswalk, normalize_team, significant_tokens
from booth_review.spike.selection import (
    DEFAULT_SEED,
    Candidate,
    SelectionError,
    build_candidates,
    select_games,
)

FIXTURES = Path(__file__).parent / "fixtures" / "spike"


def _load_games() -> list[CfbdGame]:
    return parse_games((FIXTURES / "cfbd_games_2025.json").read_bytes())


def _load_rr_entries() -> list:
    entries, _skipped = parse_sitemap((FIXTURES / "rr_sitemap.xml").read_bytes())
    return entries


# -- names.normalize_team -----------------------------------------------------------


def test_normalize_team_strips_leading_rank_and_okina() -> None:
    assert normalize_team("12 Hawaiʻi") == "hawaii"  # noqa: RUF001


def test_normalize_team_spells_out_ampersand() -> None:
    assert normalize_team("Example A&M") == "example a and m"


def test_normalize_team_replaces_hyphens_with_spaces() -> None:
    assert normalize_team("north-field-state") == "north field state"


def test_normalize_team_folds_accents_and_strips_whitespace() -> None:
    assert normalize_team("  San José State ") == "san jose state"


# -- names.significant_tokens --------------------------------------------------------


def test_significant_tokens_drops_short_tokens_and_stopwords() -> None:
    assert significant_tokens("Northfield State University") == {"northfield"}


def test_significant_tokens_keeps_multiple_real_tokens() -> None:
    assert significant_tokens("Example Ridge College") == {"example", "ridge"}


# -- names.load_crosswalk ------------------------------------------------------------


def test_load_crosswalk_returns_empty_mapping_when_file_absent(tmp_path: Path) -> None:
    assert load_crosswalk(tmp_path) == {}


def test_load_crosswalk_reads_variant_to_canonical(tmp_path: Path) -> None:
    ref_dir = tmp_path / "data" / "reference"
    ref_dir.mkdir(parents=True)
    (ref_dir / "team_crosswalk.csv").write_text(
        "variant,canonical\nexample variant,Example Canonical\n", encoding="utf-8"
    )
    assert load_crosswalk(tmp_path) == {"example variant": "Example Canonical"}


# -- selection.build_candidates -------------------------------------------------------


def test_build_candidates_flags_every_required_category() -> None:
    games = _load_games()
    rr_entries = _load_rr_entries()
    candidates = build_candidates(games, rr_entries)
    by_id = {c.game.id: c for c in candidates}

    assert "rematch" in by_id[500001].categories
    assert "rematch" in by_id[500002].categories
    assert "neutral" in by_id[500003].categories
    assert "neutral" in by_id[500004].categories
    assert "post_dst_november" in by_id[500005].categories
    assert "late_or_hawaii" in by_id[500006].categories
    assert "cfp" in by_id[500007].categories


def test_build_candidates_rated_hint_true_for_sitemap_covered_games() -> None:
    games = _load_games()
    rr_entries = _load_rr_entries()
    candidates = build_candidates(games, rr_entries)
    by_id = {c.game.id: c for c in candidates}

    assert by_id[500001].rated_hint is True
    # id 500030 has no matching sitemap entry in the fixture.
    assert by_id[500030].rated_hint is False


def test_build_candidates_non_rematch_pair_not_flagged() -> None:
    games = _load_games()
    rr_entries = _load_rr_entries()
    candidates = build_candidates(games, rr_entries)
    by_id = {c.game.id: c for c in candidates}
    assert "rematch" not in by_id[500003].categories


# -- selection.select_games ------------------------------------------------------------


def test_select_games_returns_exactly_20_covering_every_category() -> None:
    games = _load_games()
    rr_entries = _load_rr_entries()
    candidates = build_candidates(games, rr_entries)
    selections = select_games(candidates, seed=DEFAULT_SEED)

    assert len(selections) == 20
    category_counts: dict[str, int] = {}
    for s in selections:
        for cat in s.categories:
            category_counts[cat] = category_counts.get(cat, 0) + 1

    assert category_counts.get("rematch", 0) >= 2
    assert category_counts.get("neutral", 0) >= 2
    assert category_counts.get("post_dst_november", 0) >= 1
    assert category_counts.get("late_or_hawaii", 0) >= 1
    assert category_counts.get("cfp", 0) >= 1


def test_select_games_draws_only_from_rated_hint_candidates() -> None:
    games = _load_games()
    rr_entries = _load_rr_entries()
    candidates = build_candidates(games, rr_entries)
    rated_hint_ids = {c.game.id for c in candidates if c.rated_hint}

    selections = select_games(candidates, seed=DEFAULT_SEED)
    assert all(s.cfbd_game_id in rated_hint_ids for s in selections)


def test_select_games_is_identical_across_calls_with_same_seed() -> None:
    games = _load_games()
    rr_entries = _load_rr_entries()
    candidates = build_candidates(games, rr_entries)

    first = select_games(candidates, seed=DEFAULT_SEED)
    second = select_games(candidates, seed=DEFAULT_SEED)
    assert first == second


def test_select_games_tags_name_stress_for_diacritics_or_parens() -> None:
    games = _load_games()
    rr_entries = _load_rr_entries()
    candidates = build_candidates(games, rr_entries)
    selections = select_games(candidates, seed=DEFAULT_SEED)

    hawaii_selection = next(s for s in selections if s.cfbd_game_id == 500006)
    assert "name_stress" in hawaii_selection.categories


def test_select_games_raises_when_a_category_has_no_rated_hint_candidate() -> None:
    games = _load_games()
    candidates = build_candidates(games, [])  # no RR entries at all -> no rated_hint

    with pytest.raises(SelectionError):
        select_games(candidates, seed=DEFAULT_SEED)


def test_select_games_raises_naming_the_missing_category() -> None:
    games = _load_games()
    rr_entries = _load_rr_entries()
    # Drop the CFP game's sitemap entry so "cfp" has zero rated_hint candidates.
    entries_without_cfp = [e for e in rr_entries if "thornfield" not in e.telecast_id]
    candidates = build_candidates(games, entries_without_cfp)

    with pytest.raises(SelectionError, match="cfp"):
        select_games(candidates, seed=DEFAULT_SEED)


def test_candidate_is_a_frozen_dataclass_instance() -> None:
    games = _load_games()
    rr_entries = _load_rr_entries()
    candidates = build_candidates(games, rr_entries)
    assert isinstance(candidates[0], Candidate)


def test_build_candidates_excludes_games_with_no_fbs_team() -> None:
    from dataclasses import replace

    games = _load_games()
    lower = replace(games[0], id=999_001, home_classification="iii", away_classification="iii")
    mixed = replace(games[1], id=999_002, home_classification="fcs", away_classification="fbs")

    ids = {c.game.id for c in build_candidates([*games, lower, mixed], _load_rr_entries())}

    assert 999_001 not in ids
    assert 999_002 in ids


def test_replace_games_swaps_only_the_given_rows() -> None:
    from booth_review.spike.selection import replace_games

    candidates = build_candidates(_load_games(), _load_rr_entries())
    original = select_games(candidates)
    required = {"rematch", "neutral", "post_dst_november", "late_or_hawaii", "cfp"}
    plain = [i for i, s in enumerate(original, start=1) if not required & set(s.categories)]
    rows = plain[:2]

    updated = replace_games(original, rows, candidates)

    original_ids = {s.cfbd_game_id for s in original}
    for i, (before, after) in enumerate(zip(original, updated, strict=True), start=1):
        if i in rows:
            assert after.cfbd_game_id not in original_ids
        else:
            assert after == before


def test_replace_games_raises_when_a_required_category_cannot_be_refilled() -> None:
    from booth_review.spike.selection import replace_games

    candidates = build_candidates(_load_games(), _load_rr_entries())
    original = select_games(candidates)
    only_post_dst = next(
        i for i, s in enumerate(original, start=1) if "post_dst_november" in s.categories
    )
    selected = {s.cfbd_game_id for s in original}
    unused_post_dst = [
        c
        for c in candidates
        if c.rated_hint and "post_dst_november" in c.categories and c.game.id not in selected
    ]
    assert unused_post_dst == []  # every rated post-DST game in the fixture is already selected

    with pytest.raises(SelectionError, match="post_dst_november"):
        replace_games(original, [only_post_dst], candidates)


def test_replace_games_rejects_out_of_range_rows() -> None:
    from booth_review.spike.selection import SelectionError, replace_games

    candidates = build_candidates(_load_games(), _load_rr_entries())
    original = select_games(candidates)

    with pytest.raises(SelectionError):
        replace_games(original, [0], candidates)
