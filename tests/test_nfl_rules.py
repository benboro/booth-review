"""Field-list edge cases for the NFL rules, on synthetic kickoffs."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from booth_review.nfl.rules import (
    ET,
    STANDALONE_GAP,
    DhInput,
    doubleheader_networks,
    is_flexed,
    is_special,
    late_national_candidates,
    pick_late_national,
    slot_name,
    standalone_ids,
    thanksgiving,
)


def k(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=ET)


def test_gap_constant() -> None:
    assert STANDALONE_GAP.total_seconds() == 3 * 3600


def test_monday_doubleheader_neither_standalone_both_mnf() -> None:
    a, b = k(2024, 10, 14, 19, 15), k(2024, 10, 14, 20, 15)
    assert standalone_ids({"a": a, "b": b}) == frozenset()
    assert slot_name(a, outside_us=False) == "MNF"
    assert slot_name(b, outside_us=False) == "MNF"


def test_monday_exactly_three_hours_fails() -> None:
    a, b = k(2024, 10, 14, 19), k(2024, 10, 14, 22)
    assert standalone_ids({"a": a, "b": b}) == frozenset()


def test_gap_just_over_three_hours_passes() -> None:
    a, b = k(2024, 10, 14, 19), k(2024, 10, 14, 22, 1)
    assert standalone_ids({"a": a, "b": b}) == frozenset({"a", "b"})


def test_thanksgiving_three_games() -> None:
    ks = {"a": k(2024, 11, 28, 13), "b": k(2024, 11, 28, 16, 30), "c": k(2024, 11, 28, 20)}
    assert standalone_ids(ks) == frozenset(ks)
    assert {slot_name(v, outside_us=False) for v in ks.values()} == {"Thanksgiving"}


def test_saturday_tripleheader_all_pass() -> None:
    ks = {"a": k(2024, 12, 21, 13), "b": k(2024, 12, 21, 16, 30), "c": k(2024, 12, 21, 20)}
    assert standalone_ids(ks) == frozenset(ks)
    assert slot_name(ks["a"], outside_us=False) == "Saturday"


def test_saturday_5_and_8_fails() -> None:
    ks = {"a": k(2025, 12, 20, 17), "b": k(2025, 12, 20, 20)}
    assert standalone_ids(ks) == frozenset()


def test_saturday_430_and_800_passes() -> None:
    ks = {"a": k(2025, 12, 20, 16, 30), "b": k(2025, 12, 20, 20)}
    assert standalone_ids(ks) == frozenset(ks)


def test_christmas_on_streamer_all_standalone() -> None:
    # Dec 25 2025 is a Thursday; network is irrelevant to the rule.
    ks = {"a": k(2025, 12, 25, 13), "b": k(2025, 12, 25, 16, 30), "c": k(2025, 12, 25, 20, 15)}
    assert standalone_ids(ks) == frozenset(ks)
    assert {slot_name(v, outside_us=False) for v in ks.values()} == {"Christmas"}


def test_international_930_sunday_standalone() -> None:
    intl, a, b = k(2024, 10, 6, 9, 30), k(2024, 10, 6, 13), k(2024, 10, 6, 16, 25)
    assert "i" in standalone_ids({"i": intl, "a": a, "b": b})
    assert slot_name(intl, outside_us=True) == "International"


def test_friday_brazil_international() -> None:
    f = k(2025, 9, 5, 20, 15)
    assert f.weekday() == 4
    assert standalone_ids({"f": f, "s": k(2025, 9, 7, 13)}) == frozenset({"f", "s"})
    assert slot_name(f, outside_us=True) == "International"
    assert slot_name(f, outside_us=False) == "Friday"


def test_international_in_1pm_window_not_standalone_and_sunday_early() -> None:
    intl, other = k(2024, 10, 13, 13), k(2024, 10, 13, 13)
    assert standalone_ids({"i": intl, "o": other}) == frozenset()
    assert slot_name(intl, outside_us=True) == "Sunday early"


def test_single_game_season_is_standalone() -> None:
    assert standalone_ids({"a": k(2024, 9, 8, 13)}) == frozenset({"a"})


def test_thanksgiving_and_black_friday_dates() -> None:
    assert thanksgiving(2024) == date(2024, 11, 28)
    assert thanksgiving(2025) == date(2025, 11, 27)
    assert slot_name(k(2025, 11, 28, 15), outside_us=False) == "Black Friday"


def test_christmas_beats_thursday() -> None:
    assert slot_name(k(2025, 12, 25, 20, 15), outside_us=False) == "Christmas"


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (k(2024, 9, 12, 20, 15), "TNF"),
        (k(2024, 9, 8, 20, 20), "SNF"),
        (k(2024, 9, 8, 15, 0), "Sunday late"),
        (k(2024, 9, 8, 14, 59), "Sunday early"),
        (k(2024, 9, 10, 19), "Other"),
        (k(2024, 9, 11, 19), "Other"),
        (k(2024, 9, 12, 13), "Other"),
    ],
)
def test_slot_names(when: datetime, expected: str) -> None:
    assert slot_name(when, outside_us=False) == expected


def test_is_special_rollup_ignores_international_and_flex() -> None:
    kw = {"game_type": "REG", "include_playoffs": False}
    assert not is_special(is_standalone=False, is_agotw=False, is_cbs_national=False, **kw)
    assert is_special(is_standalone=True, is_agotw=False, is_cbs_national=False, **kw)
    assert is_special(is_standalone=False, is_agotw=True, is_cbs_national=False, **kw)
    assert is_special(is_standalone=False, is_agotw=False, is_cbs_national=True, **kw)


def test_is_special_playoffs_toggle() -> None:
    kw = {"is_standalone": True, "is_agotw": False, "is_cbs_national": False}
    assert not is_special(game_type="DIV", include_playoffs=False, **kw)
    assert is_special(game_type="DIV", include_playoffs=True, **kw)


def test_flex_into_snf_is_flexed() -> None:
    assert is_flexed(
        current_slot="SNF",
        original_slot="Sunday early",
        is_late_national=False,
        original_time_et="13:00",
        current_time_et="20:20",
    )


def test_cross_flex_not_flexed() -> None:
    assert not is_flexed(
        current_slot="Sunday early",
        original_slot="Sunday early",
        is_late_national=False,
        original_time_et="13:00",
        current_time_et="13:00",
    )


def test_flex_into_late_national_is_flexed() -> None:
    assert is_flexed(
        current_slot="Sunday late",
        original_slot="Sunday early",
        is_late_national=True,
        original_time_et="13:00",
        current_time_et="16:25",
    )


def test_late_national_not_moved_not_flexed() -> None:
    assert not is_flexed(
        current_slot="Sunday late",
        original_slot="Sunday late",
        is_late_national=True,
        original_time_et="16:25",
        current_time_et="16:25",
    )


def test_no_original_slot_not_flexed() -> None:
    assert not is_flexed(
        current_slot="SNF",
        original_slot=None,
        is_late_national=False,
        original_time_et=None,
        current_time_et="20:20",
    )


# --- doubleheader / late national ---


def dh(gid: str, hh: int, mm: int, net: str | None, day: int = 8) -> DhInput:
    return DhInput(gid, k(2024, 12, day, hh, mm), net)


def test_dh_fox_only() -> None:
    games = [dh("a", 13, 0, "fox"), dh("b", 16, 25, "fox"), dh("c", 13, 0, "cbs")]
    assert doubleheader_networks(games) == frozenset({"fox"})


def test_dh_both() -> None:
    games = [
        dh("a", 13, 0, "fox"),
        dh("b", 16, 25, "fox"),
        dh("c", 13, 0, "cbs"),
        dh("d", 16, 25, "cbs"),
    ]
    assert doubleheader_networks(games) == frozenset({"fox", "cbs"})


def test_dh_saturday_empty() -> None:
    games = [dh("a", 13, 0, "fox", day=14), dh("b", 16, 25, "fox", day=14)]
    assert doubleheader_networks(games) == frozenset()


def test_dh_1605_is_not_late_national() -> None:
    games = [dh("a", 13, 0, "fox"), dh("b", 16, 5, "fox")]
    assert doubleheader_networks(games) == frozenset()
    assert late_national_candidates(games, "fox") == ()


def test_dh_ignores_unknown_network() -> None:
    games = [dh("a", 13, 0, None), dh("b", 16, 25, None)]
    assert doubleheader_networks(games) == frozenset()


def test_pick_single() -> None:
    p = pick_late_national(["a"], rr_named=set(), s506_named=set(), override_game_id=None)
    assert (p.game_id, p.source) == ("a", "single")


def test_pick_rr() -> None:
    p = pick_late_national(["a", "b"], rr_named={"b"}, s506_named=set(), override_game_id=None)
    assert (p.game_id, p.source) == ("b", "rr")


def test_pick_506() -> None:
    p = pick_late_national(["a", "b"], rr_named=set(), s506_named={"a"}, override_game_id=None)
    assert (p.game_id, p.source) == ("a", "506")


def test_pick_override_settles_ambiguous() -> None:
    p = pick_late_national(["a", "b"], rr_named={"a", "b"}, s506_named=set(), override_game_id="b")
    assert (p.game_id, p.source, p.override_unused) == ("b", "override", False)


def test_pick_ambiguous() -> None:
    p = pick_late_national(["a", "b"], rr_named=set(), s506_named=set(), override_game_id=None)
    assert (p.game_id, p.source) == (None, "ambiguous")


def test_override_non_candidate_raises() -> None:
    with pytest.raises(ValueError, match="not a late national candidate"):
        pick_late_national(["a", "b"], rr_named=set(), s506_named=set(), override_game_id="z")


def test_override_on_settled_week_unused() -> None:
    p = pick_late_national(["a", "b"], rr_named={"a"}, s506_named=set(), override_game_id="b")
    assert (p.game_id, p.source, p.override_unused) == ("a", "rr", True)
