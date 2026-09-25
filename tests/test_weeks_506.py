"""Tests for D-03 smoke_check and D-05 discover_season_weeks (sports506/weeks.py).

Nav-discovery tests build small synthetic HTML strings in-test rather than
reusing tests/fixtures/sports506/*.html (those fixtures don't carry a nav
block); smoke-check tests reuse the existing week_synthetic.html fixture,
whose structure (never real 506 content, D-07) is shared with test_parser_506.py.
"""

from __future__ import annotations

from pathlib import Path

from booth_review.sources.sports506.weeks import (
    SMOKE_MIN_CREW_SHARE,
    SeasonWeeks,
    discover_season_weeks,
    label_from_cache_name,
    smoke_check,
)

FIXTURES = Path(__file__).parent / "fixtures" / "sports506"


def _nav_page(anchors: list[str]) -> bytes:
    links = "\n".join(f'<a href="{href}">wk</a>' for href in anchors)
    return f"<html><body><nav>{links}</nav></body></html>".encode()


def _one_game_page(*, crew: str) -> bytes:
    return (
        b"<html><body>"
        b"<h3>SATURDAY, SEPTEMBER 6</h3>"
        b'<div id="cgame"><div id="cmatchup">Alpha State @ Beta Tech</div>'
        b'<div id="ctime">7:00 PM</div><div id="cntwk">ECN</div>'
        b'<div id="canncrs">' + crew.encode() + b"</div></div>"
        b"</body></html>"
    )


def _four_games_one_crew_page() -> bytes:
    rows = []
    for i in range(4):
        crew = "Pat Example, Jordan Sample" if i == 0 else ""
        rows.append(
            f'<div id="cgame"><div id="cmatchup">Team{i}A @ Team{i}B</div>'
            f'<div id="ctime">7:00 PM</div><div id="cntwk">ECN</div>'
            f'<div id="canncrs">{crew}</div></div>'
        )
    body = "<h3>SATURDAY, SEPTEMBER 6</h3>" + "".join(rows)
    return f"<html><body>{body}</body></html>".encode()


# -- discover_season_weeks --------------------------------------------------------------


def test_discover_season_weeks_reads_own_season_nav_ignores_others_numeric_order_b_last() -> None:
    anchors = [
        "https://506sports.com/ncaaf.php?yr=2020&wk=0",
        "https://506sports.com/ncaaf.php?yr=2020&wk=1",
        "https://506sports.com/ncaaf.php?yr=2020&wk=2",
        "https://506sports.com/ncaaf.php?yr=2020&wk=3",
        "https://506sports.com/ncaaf.php?yr=2020&wk=4",
        "https://506sports.com/ncaaf.php?yr=2020&wk=5",
        "https://506sports.com/ncaaf.php?yr=2020&wk=7",
        "https://506sports.com/ncaaf.php?yr=2020&wk=B",
        "https://506sports.com/ncaaf.php?yr=2019&wk=3",
        "https://506sports.com/ncaaf.php?yr=2021&wk=1",
    ]
    result = discover_season_weeks(_nav_page(anchors), 2020)
    assert result == SeasonWeeks(labels=["0", "1", "2", "3", "4", "5", "7", "B"], unsupported=[])


def test_discover_season_weeks_recognizes_amp_entity_and_literal_ampersand() -> None:
    anchors = [
        "https://506sports.com/ncaaf.php?yr=2025&amp;wk=1",
        "https://506sports.com/ncaaf.php?yr=2025&wk=2",
    ]
    result = discover_season_weeks(_nav_page(anchors), 2025)
    assert result.labels == ["1", "2"]


def test_discover_season_weeks_normalizes_zero_padded_labels_and_dedupes() -> None:
    anchors = [
        "https://506sports.com/ncaaf.php?yr=2025&wk=01",
        "https://506sports.com/ncaaf.php?yr=2025&wk=1",
        "https://506sports.com/ncaaf.php?yr=2025&wk=01",
    ]
    result = discover_season_weeks(_nav_page(anchors), 2025)
    assert result.labels == ["1"]


def test_discover_season_weeks_reports_unsupported_label_separately() -> None:
    anchors = [
        "https://506sports.com/ncaaf.php?yr=2025&wk=1",
        "https://506sports.com/ncaaf.php?yr=2025&wk=17",
    ]
    result = discover_season_weeks(_nav_page(anchors), 2025)
    assert result.labels == ["1"]
    assert result.unsupported == ["17"]


def test_discover_season_weeks_no_matching_anchors_returns_empty_lists() -> None:
    result = discover_season_weeks(b"<html><body>no nav here</body></html>", 2025)
    assert result == SeasonWeeks(labels=[], unsupported=[])


# -- smoke_check --------------------------------------------------------------------------


def test_smoke_check_passes_on_week_synthetic_fixture() -> None:
    html = (FIXTURES / "week_synthetic.html").read_bytes()
    result = smoke_check(html, season=2025, week_label="5")
    assert result.passed is True
    assert result.games == 4
    assert result.with_crew == 3
    assert result.reason is None


def test_smoke_check_fails_below_crew_share_threshold() -> None:
    result = smoke_check(_four_games_one_crew_page(), season=2025, week_label="5")
    assert result.passed is False
    assert result.games == 4
    assert result.with_crew == 1
    assert result.reason == "smoke check failed: 1/4 games with crew"
    assert SMOKE_MIN_CREW_SHARE > 1 / 4


def test_smoke_check_fails_with_no_schedule_rows_never_raises() -> None:
    result = smoke_check(b"<html><body>not a week page</body></html>", season=2025, week_label="5")
    assert result.passed is False
    assert result.reason is not None
    assert result.reason.startswith("parse failed:")


def test_smoke_check_fails_on_empty_bytes_never_raises() -> None:
    result = smoke_check(b"", season=2025, week_label="5")
    assert result.passed is False
    assert result.reason is not None
    assert result.reason.startswith("parse failed:")


def test_smoke_check_passes_at_exactly_one_game_full_crew() -> None:
    result = smoke_check(
        _one_game_page(crew="Pat Example, Jordan Sample"), season=2025, week_label="0"
    )
    assert result.passed is True
    assert result.games == 1
    assert result.with_crew == 1


# -- label_from_cache_name ------------------------------------------------------------------


def test_label_from_cache_name_maps_zero_padded_and_bowls() -> None:
    assert label_from_cache_name("wk-00.html") == "0"
    assert label_from_cache_name("wk-12.html") == "12"
    assert label_from_cache_name("wk-B.html") == "B"
    assert label_from_cache_name("not-a-week.html") is None
