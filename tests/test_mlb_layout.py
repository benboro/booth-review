"""The MLB path, season and constant contract."""

from __future__ import annotations

import typing
from datetime import date

import pytest

from booth_review.mlb import constants as c
from booth_review.mlb import layout, seasons
from booth_review.transport.types import Source


def test_506_paths_and_urls() -> None:
    assert layout.mlb_506_path(2026, "5") == "mlb/sports506/2026/wk-05.html"
    assert layout.mlb_506_path(2025, "WS") == "mlb/sports506/2025/wk-WS.html"
    assert layout.mlb_506_url(2026, "WC") == "https://506sports.com/mlb.php?yr=2026&wk=WC"


def test_rr_relay_statsapi_paths() -> None:
    assert layout.mlb_rr_path(2026, "x") == "mlb/ratingsref/telecast/2026/x.json"
    assert layout.MLB_RELAY_PATH == "mlb/relay/crew_relays.csv"
    assert (
        layout.statsapi_schedule_path(date(2026, 4, 1)) == "mlb/statsapi/schedule/2026-04-01.json"
    )


def test_wikipedia_urls_use_plain_article_paths() -> None:
    assert (
        layout.mlb_wikipedia_url(2014)
        == "https://en.wikipedia.org/wiki/2014_Major_League_Baseball_postseason"
    )
    assert layout.mlb_wikipedia_path(2014) == "mlb/wikipedia/2014.html"
    urls = [layout.mlb_wikipedia_url(2014)]
    for slug, title, _kind in layout.MLB_WIKIPEDIA_LIST_PAGES:
        urls.append(layout.mlb_wikipedia_list_url(title))
        assert layout.mlb_wikipedia_list_path(slug) == f"mlb/wikipedia/lists/{slug}.html"
    assert len(layout.MLB_WIKIPEDIA_LIST_PAGES) == 4
    for url in urls:
        assert url.startswith("https://en.wikipedia.org/wiki/")
        assert "/w/" not in url
        assert "/api/" not in url


def test_retrosheet_asset_path_rejects_traversal() -> None:
    assert layout.retrosheet_asset_path("gameinfo.zip") == "mlb/retrosheet/assets/gameinfo.zip"
    for bad in ("../x", "a/b", ".."):
        with pytest.raises(ValueError, match="asset"):
            layout.retrosheet_asset_path(bad)


def test_sources_are_valid_literals() -> None:
    valid = set(typing.get_args(Source))
    assert layout.MLB_SOURCES == (
        "mlb_sports506",
        "mlb_ratingsref",
        "mlb_retrosheet",
        "mlb_wikipedia",
        "mlb_relay",
    )
    assert set(layout.MLB_SOURCES) <= valid
    assert "mlb_statsapi" in valid
    assert "mlb_statsapi" not in layout.MLB_SOURCES


def test_calendar_year_seasons() -> None:
    assert seasons.mlb_season_of(date(2026, 4, 1)) == 2026
    assert seasons.mlb_season_of(date(2026, 11, 2)) == 2026
    assert seasons.mlb_season_window(2026) == (date(2026, 1, 1), date(2026, 12, 31))
    assert seasons.mlb_freeze_date(2025) == date(2026, 3, 1)
    assert seasons.mlb_current_season(date(2026, 10, 14)) == 2026


def test_constants() -> None:
    assert c.WE_PRIOR_K == 30
    assert tuple(range(2015, 2026)) == c.WE_TRAIN_SEASONS
    assert c.STAKES_BAND_QUANTILES == (0.50, 0.80, 0.95)
    assert c.MLB_REFRESH_CAP_DEFAULT == 40
    assert c.CREW_COVERAGE_BAR == 0.95
    assert 2020 not in c.STAKES_BASELINE_SEASONS
    assert c.STAKES_BASELINE_SEASONS[0] == 2017
    assert c.wc_spots(2021) == 2
    assert c.wc_spots(2022) == 3
    assert pytest.approx(0.35355339) == c.GB_SD_PER_ROOT_GAME
