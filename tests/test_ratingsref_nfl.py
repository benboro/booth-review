"""Offline tests for the NFL league option of the RR sitemap parser and collector (D-18, D-09)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from booth_review.errors import VaultStateError
from booth_review.nfl.layout import nfl_rr_path
from booth_review.sources.ratingsref.collector import (
    NFL_REFRESH_CAP_DEFAULT,
    REFRESH_CAP_DEFAULT,
    SITEMAP_URL,
    RatingsRefCollector,
)
from booth_review.sources.ratingsref.lastmod import lastmod_has_prefix
from booth_review.sources.ratingsref.sitemap import parse_sitemap
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient

_LM = "2026-01-01T00:00:00+00:00"
_LM2 = "2026-02-01T00:00:00+00:00"


def _client(handle) -> PoliteClient:
    return PoliteClient(transport=handle.transport, clock=lambda: 0.0, sleep=lambda s: None)


def _sitemap_xml(entries: list[tuple[str, str]]) -> bytes:
    urls = "".join(
        f"<url><loc>https://ratingsreference.com/telecast/{slug}</loc>"
        f"<lastmod>{lm}</lastmod></url>\n"
        for slug, lm in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}</urlset>\n"
    ).encode()


def _url(slug: str) -> str:
    return f"https://ratingsreference.com/api/telecast/{slug}.json"


def _body(slug: str) -> bytes:
    return json.dumps({"telecast": {"id": slug}}).encode()


_MIXED = _sitemap_xml(
    [
        ("cfb-aa-bb-2025-09-06", _LM),
        ("nfl-gulls-owls-2025-09-07", _LM),
        ("nfl-christmas-gulls-owls-2025-12-25", _LM),
        ("nfl-kickoff-2025-09-04", _LM),
        ("nfl-undated-special", _LM),
        ("mlb-cc-dd-2025-06-01", _LM),
    ]
)


def test_parse_default_is_cfb_only() -> None:
    entries, skipped = parse_sitemap(_MIXED)
    assert [e.telecast_id for e in entries] == ["cfb-aa-bb-2025-09-06"]
    assert entries[0].league == "cfb"
    assert skipped == 5


def test_parse_nfl_selects_nfl_entries_including_event_slugs() -> None:
    entries, skipped = parse_sitemap(_MIXED, league="nfl")
    assert [e.telecast_id for e in entries] == [
        "nfl-gulls-owls-2025-09-07",
        "nfl-christmas-gulls-owls-2025-12-25",
        "nfl-kickoff-2025-09-04",
    ]
    assert {e.league for e in entries} == {"nfl"}
    assert skipped == 3


def test_parse_unknown_league_raises() -> None:
    with pytest.raises(ValueError, match="xyz"):
        parse_sitemap(_MIXED, league="xyz")


def test_plan_uses_league_source_and_path(vault_paths, mock_transport_factory) -> None:
    entries, _ = parse_sitemap(_MIXED, league="nfl")
    cache = RawCache(vault_paths, _client(mock_transport_factory({})))
    reqs = RatingsRefCollector(cache, vault_paths, league="nfl").plan(entries[:1])
    assert reqs[0].source == "nfl_ratingsref"
    assert reqs[0].cache_path == nfl_rr_path(2025, "nfl-gulls-owls-2025-09-07")

    cfb_entries, _ = parse_sitemap(_MIXED)
    cfb = RatingsRefCollector(cache, vault_paths).plan(cfb_entries)
    assert cfb[0].source == "ratingsref"
    assert cfb[0].cache_path == "ratingsref/telecast/2025/cfb-aa-bb-2025-09-06.json"


def test_unknown_collector_league_raises(vault_paths, mock_transport_factory) -> None:
    cache = RawCache(vault_paths, _client(mock_transport_factory({})))
    with pytest.raises(ValueError):
        RatingsRefCollector(cache, vault_paths, league="xyz")


def test_nfl_run_reuses_cached_sitemap_and_ignores_cfb_frozen(
    vault_paths, mock_transport_factory
) -> None:
    vault_paths.frozen.write_text(
        json.dumps({"sports506": [], "ratingsref": [2025], "cfbd": []}), encoding="utf-8"
    )
    today = datetime.now(UTC).date()
    sitemap = vault_paths.raw / "ratingsref" / "sitemap" / f"{today.isoformat()}.xml"
    sitemap.parent.mkdir(parents=True)
    sitemap.write_bytes(_MIXED)
    slug = "nfl-gulls-owls-2025-09-07"
    handle = mock_transport_factory(
        {
            "https://ratingsreference.com/robots.txt": (404, b"nf", {}),
            _url(slug): (200, _body(slug), {}),
        }
    )
    cache = RawCache(vault_paths, _client(handle))
    summary = RatingsRefCollector(cache, vault_paths, league="nfl").run(
        date(2025, 9, 7), date(2025, 9, 7), dry_run=False
    )
    assert summary.source == "nfl_ratingsref"
    assert summary.fetched == 1
    assert not [r for r in handle.requests if r.url == SITEMAP_URL]
    assert (vault_paths.raw / nfl_rr_path(2025, slug)).is_file()


def test_cap_constants() -> None:
    assert NFL_REFRESH_CAP_DEFAULT == 40
    assert REFRESH_CAP_DEFAULT == 100


def _seed(vault_paths, ids: dict[str, str]) -> None:
    vault_paths.rr_lastmod.write_text(
        json.dumps(
            {
                i: {"lastmod": lm, "fetched_at": "2025-12-01T00:00:00Z", "record_url": ""}
                for i, lm in ids.items()
            }
        ),
        encoding="utf-8",
    )


def _nfl_refresh(vault_paths, mock_transport_factory, xml, extra, **kw):
    responses = {
        "https://ratingsreference.com/robots.txt": (404, b"nf", {}),
        SITEMAP_URL: (200, xml, {}),
        **extra,
    }
    handle = mock_transport_factory(responses)
    cache = RawCache(vault_paths, _client(handle))
    collector = RatingsRefCollector(cache, vault_paths, league="nfl")
    return handle, collector.refresh(dry_run=False, **kw)


def test_nfl_refresh_cap_backlog_and_uncapped_new_current(
    vault_paths, mock_transport_factory
) -> None:
    old = [f"nfl-t{i:02d}-u{i:02d}-2015-10-{(i % 28) + 1:02d}" for i in range(45)]
    new = [f"nfl-n{i}-m{i}-2025-09-0{i + 1}" for i in range(3)]
    _seed(vault_paths, {s: _LM for s in old})
    xml = _sitemap_xml([(s, _LM2) for s in old] + [(s, _LM) for s in new])
    extra = {_url(s): (200, _body(s), {}) for s in old + new}
    handle, summary = _nfl_refresh(
        vault_paths,
        mock_transport_factory,
        xml,
        extra,
        current_season=2025,
        cap=NFL_REFRESH_CAP_DEFAULT,
    )
    assert summary.advanced == 45
    assert summary.new == 3
    assert summary.uncapped_current == 3
    assert summary.selected == 43
    assert summary.backlog == 5
    assert summary.fetched == 43
    assert all("/telecast/cfb-" not in r.url for r in handle.requests)


def test_nfl_refresh_refuses_without_nfl_lastmod_lines(vault_paths, mock_transport_factory) -> None:
    _seed(vault_paths, {"cfb-aa-bb-2025-09-06": _LM})
    assert not lastmod_has_prefix(vault_paths, "nfl-")
    with pytest.raises(VaultStateError, match="collect ratingsref --league nfl"):
        _nfl_refresh(vault_paths, mock_transport_factory, _MIXED, {}, current_season=2025, cap=40)


def test_nfl_refresh_fetches_in_frozen_season_and_leaves_cfb(
    vault_paths, mock_transport_factory
) -> None:
    vault_paths.frozen.write_text(
        json.dumps({"sports506": [], "ratingsref": [2019], "cfbd": [], "nfl_ratingsref": [2019]}),
        encoding="utf-8",
    )
    slug = "nfl-gulls-owls-2019-09-08"
    cfb = "cfb-aa-bb-2019-09-07"
    _seed(vault_paths, {slug: _LM, cfb: _LM})
    xml = _sitemap_xml([(slug, _LM2), (cfb, _LM2)])
    handle, summary = _nfl_refresh(
        vault_paths,
        mock_transport_factory,
        xml,
        {_url(slug): (200, _body(slug), {})},
        current_season=2025,
        cap=40,
    )
    assert summary.fetched == 1
    assert (vault_paths.raw / nfl_rr_path(2019, slug)).is_file()
    assert {r.url for r in handle.requests if "/api/telecast/" in r.url} == {_url(slug)}


def test_cfb_refresh_ignores_nfl_lines(vault_paths, mock_transport_factory) -> None:
    cfb = "cfb-aa-bb-2025-09-06"
    _seed(vault_paths, {cfb: _LM, "nfl-gulls-owls-2025-09-07": _LM})
    xml = _sitemap_xml([(cfb, _LM), ("nfl-gulls-owls-2025-09-07", _LM2)])
    handle = mock_transport_factory(
        {"https://ratingsreference.com/robots.txt": (404, b"nf", {}), SITEMAP_URL: (200, xml, {})}
    )
    cache = RawCache(vault_paths, _client(handle))
    summary = RatingsRefCollector(cache, vault_paths).refresh(current_season=2025, dry_run=False)
    assert summary.qualifying == 0
