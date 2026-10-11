"""2014-2015 acceptance gate on synthetic game frames."""

from __future__ import annotations

from test_nfl_special_table import game, table

from booth_review.nfl.acceptance import check_acceptance


def frame(*rows: dict):
    return table(list(rows)).frame


def test_unmatched_standalone_fails_with_row() -> None:
    res = check_acceptance(frame(game("a", 2014, 3, "h", "v", is_standalone=True)))
    assert res.unmatched == 1 and res.multi_network == 0
    assert res.rows[0]["reason"] == "no-rr-network"
    assert res.rows[0]["game_id"] == "a" and res.rows[0]["week"] == 3


def test_all_matched_passes() -> None:
    res = check_acceptance(
        frame(game("a", 2014, 3, "h", "v", is_standalone=True, rr_network_ids=["nbc"]))
    )
    assert (res.unmatched, res.multi_network) == (0, 0)


def test_later_seasons_are_informational_only() -> None:
    res = check_acceptance(frame(game("a", 2016, 3, "h", "v", is_standalone=True)))
    assert res.unmatched == 0 and res.informational_2016_plus == 1


def test_non_standalone_and_playoffs_ignored() -> None:
    res = check_acceptance(
        frame(
            game("a", 2014, 3, "h", "v"),
            game("b", 2014, 20, "h", "v", is_standalone=True, game_type="POST"),
        )
    )
    assert res.unmatched == 0


def test_simulcasts_pass_and_are_counted() -> None:
    res = check_acceptance(
        frame(
            game("a", 2014, 3, "h", "v", is_standalone=True, rr_network_ids=["cbs", "nfln"]),
            game("b", 2015, 4, "h", "v", is_standalone=True, rr_network_ids=["abc", "espn"]),
        )
    )
    assert (res.unmatched, res.multi_network) == (0, 2)


def test_mixed_slate() -> None:
    res = check_acceptance(
        frame(
            game("a", 2014, 3, "h", "v", is_standalone=True, rr_network_ids=["cbs", "nfln"]),
            game("b", 2014, 4, "h", "v", is_standalone=True, rr_network_ids=["nbc"]),
            game("c", 2014, 5, "h", "v", is_standalone=True),
        )
    )
    assert (res.unmatched, res.multi_network) == (1, 1)
