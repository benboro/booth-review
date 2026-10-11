"""Offline tests for the Wikipedia collector and scheduling-changes parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from booth_review.errors import FrozenSeasonError, RobotsDisallowedError
from booth_review.sources.wikipedia.collector import WikipediaCollector
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient

FIXTURES = Path(__file__).parent / "fixtures" / "nfl" / "wikipedia"
ROBOTS = "https://en.wikipedia.org/robots.txt"


def _url(season: int) -> str:
    return f"https://en.wikipedia.org/wiki/{season}_NFL_season"


def _cache(vault_paths, handle, fake_clock) -> RawCache:
    client = PoliteClient(transport=handle.transport, clock=fake_clock.now, sleep=fake_clock.sleep)
    return RawCache(vault_paths, client)


def test_collector_plan_is_one_plain_wiki_request(vault_paths, mock_transport_factory) -> None:
    handle = mock_transport_factory({})
    collector = WikipediaCollector(RawCache(vault_paths, PoliteClient(transport=handle.transport)))
    (req,) = collector.plan(2014)
    assert req.source == "nfl_wikipedia"
    assert req.season == 2014
    assert req.url == _url(2014)
    assert req.cache_path == "nfl/wikipedia/2014.html"
    assert "/w/" not in req.url
    assert "/api/" not in req.url


def test_collector_fetches_once_then_serves_from_cache(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    handle = mock_transport_factory(
        {
            ROBOTS: (404, b"nf", {}),
            _url(2014): (200, b"<html>a</html>", {}),
            _url(2015): (200, b"<html>b</html>", {}),
        }
    )
    collector = WikipediaCollector(_cache(vault_paths, handle, fake_clock))
    summaries = collector.run([2014, 2015], refresh=False, dry_run=False)
    assert [s.fetched for s in summaries] == [1, 1]
    assert len(handle.requests) == 3  # one robots + two articles
    assert all("booth-review/" in r.headers["user-agent"] for r in handle.requests)
    again = collector.run([2014, 2015], refresh=False, dry_run=False)
    assert [s.cached for s in again] == [1, 1]
    assert len(handle.requests) == 3


def test_collector_refresh_sends_validators_and_records_304(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    handle = mock_transport_factory(
        {
            ROBOTS: (404, b"nf", {}),
            _url(2026): (200, b"<html>x</html>", {"ETag": '"abc"'}),
        }
    )
    collector = WikipediaCollector(_cache(vault_paths, handle, fake_clock))
    collector.run([2026], refresh=False, dry_run=False)
    handle2 = mock_transport_factory({ROBOTS: (404, b"nf", {}), _url(2026): (304, b"", {})})
    collector2 = WikipediaCollector(_cache(vault_paths, handle2, fake_clock))
    (summary,) = collector2.run([2026], refresh=True, dry_run=False)
    assert summary.not_modified == 1
    article = next(r for r in handle2.requests if r.url == _url(2026))
    assert article.headers["if-none-match"] == '"abc"'


def test_collector_wildcard_robots_disallow_raises(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    handle = mock_transport_factory(
        {ROBOTS: (200, b"User-agent: *\nDisallow: /wiki/*_NFL_season\n", {})}
    )
    collector = WikipediaCollector(_cache(vault_paths, handle, fake_clock))
    with pytest.raises(RobotsDisallowedError):
        collector.run([2014], refresh=False, dry_run=False)
    assert all(r.url == ROBOTS for r in handle.requests)


def test_collector_frozen_season_never_requested_even_with_refresh(
    vault_paths, mock_transport_factory, fake_clock
) -> None:
    vault_paths.frozen.write_text(json.dumps({"nfl_wikipedia": [2014]}))
    handle = mock_transport_factory({})
    collector = WikipediaCollector(_cache(vault_paths, handle, fake_clock))
    with pytest.raises(FrozenSeasonError):
        collector.run([2014], refresh=True, dry_run=False)
    assert handle.requests == []
