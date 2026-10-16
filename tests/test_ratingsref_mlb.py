"""Offline tests for the MLB league option of the RR sitemap parser and collector (D-14, D-22)."""

from __future__ import annotations

import json
from datetime import date

import pytest

from booth_review.errors import VaultStateError
from booth_review.mlb.layout import mlb_rr_path
from booth_review.sources.ratingsref.collector import (
    MLB_REFRESH_CAP_DEFAULT,
    SITEMAP_URL,
    RatingsRefCollector,
)
from booth_review.sources.ratingsref.sitemap import parse_sitemap
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient

_LM = "2026-01-01T00:00:00+00:00"
_LM2 = "2026-02-01T00:00:00+00:00"
_WINDOWS = [(date(2026, 3, 20), date(2026, 9, 30))]


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
        ("mlb-reds-blues-2026-04-03", _LM),
        ("mlb-red-sox-white-sox-2026-05-01", _LM),
        ("mlb-hawks-doves-2025-10-30", _LM),
        ("mlb-hawks-doves-2026-11-01", _LM),
        ("mlb-all-star-game-2026-07-14", _LM),
        ("mlb-undated-special", _LM),
    ]
)


def test_sitemap_mlb_calendar_year_seasons() -> None:
    entries, skipped = parse_sitemap(_MIXED, league="mlb")
    by_id = {e.telecast_id: e for e in entries}
    assert by_id["mlb-reds-blues-2026-04-03"].season == 2026
    assert by_id["mlb-hawks-doves-2025-10-30"].season == 2025
    assert by_id["mlb-hawks-doves-2026-11-01"].season == 2026
    assert by_id["mlb-red-sox-white-sox-2026-05-01"].event_date == date(2026, 5, 1)
    assert {e.league for e in entries} == {"mlb"}
    assert skipped == 3


def test_sitemap_default_and_nfl_unchanged_by_mlb_entries() -> None:
    cfb, _ = parse_sitemap(_MIXED)
    assert [e.telecast_id for e in cfb] == ["cfb-aa-bb-2025-09-06"]
    assert cfb[0].season == 2025
    nfl, _ = parse_sitemap(_MIXED, league="nfl")
    assert [e.telecast_id for e in nfl] == ["nfl-gulls-owls-2025-09-07"]


def _collector(vault_paths, handle) -> RatingsRefCollector:
    return RatingsRefCollector(RawCache(vault_paths, _client(handle)), vault_paths, league="mlb")


def test_plan_mlb_source_and_path(vault_paths, mock_transport_factory) -> None:
    entries, _ = parse_sitemap(_MIXED, league="mlb")
    reqs = _collector(vault_paths, mock_transport_factory({})).plan(entries[:1])
    assert reqs[0].source == "mlb_ratingsref"
    assert reqs[0].cache_path == mlb_rr_path(2026, "mlb-reds-blues-2026-04-03")
    assert reqs[0].cache_path.startswith("mlb/ratingsref/")


def test_plan_skips_event_slugs_and_windows(vault_paths, mock_transport_factory) -> None:
    entries, _ = parse_sitemap(_MIXED, league="mlb")
    collector = _collector(vault_paths, mock_transport_factory({}))
    ids = [r.cache_path for r in collector.plan(entries)]
    assert all("all-star" not in i for i in ids)
    assert len(ids) == len(entries) - 1
    windowed = collector.plan(entries, windows=_WINDOWS)
    assert {r.url for r in windowed} == {
        _url("mlb-reds-blues-2026-04-03"),
        _url("mlb-red-sox-white-sox-2026-05-01"),
    }


def test_run_counts_event_and_window(vault_paths, mock_transport_factory) -> None:
    from datetime import UTC, datetime

    today = datetime.now(UTC).date()
    sitemap = vault_paths.raw / "ratingsref" / "sitemap" / f"{today.isoformat()}.xml"
    sitemap.parent.mkdir(parents=True)
    sitemap.write_bytes(_MIXED)
    handle = mock_transport_factory({})
    summary = _collector(vault_paths, handle).run(
        date(2025, 1, 1), date(2026, 12, 31), dry_run=True, windows=_WINDOWS
    )
    assert summary.source == "mlb_ratingsref"
    assert summary.planned == 2
    counts = summary.counts()
    assert counts["skipped_event"] == 1
    assert counts["out_of_window"] == 2
    assert not handle.requests


def test_cap_constant() -> None:
    assert MLB_REFRESH_CAP_DEFAULT == 40


def _seed(vault_paths, ids: dict[str, str]) -> None:
    vault_paths.rr_lastmod.write_text(
        json.dumps(
            {
                i: {"lastmod": lm, "fetched_at": "2026-01-02T00:00:00Z", "record_url": ""}
                for i, lm in ids.items()
            }
        ),
        encoding="utf-8",
    )


def _refresh(vault_paths, mock_transport_factory, xml, extra, **kw):
    handle = mock_transport_factory(
        {
            "https://ratingsreference.com/robots.txt": (404, b"nf", {}),
            SITEMAP_URL: (200, xml, {}),
            **extra,
        }
    )
    return handle, _collector(vault_paths, handle).refresh(dry_run=False, **kw)


def test_mlb_refresh_requires_windows(vault_paths, mock_transport_factory) -> None:
    _seed(vault_paths, {"mlb-reds-blues-2026-04-03": _LM})
    with pytest.raises(ValueError, match="D-14"):
        _refresh(vault_paths, mock_transport_factory, _MIXED, {}, current_season=2026)


def test_mlb_refresh_first_run_guard(vault_paths, mock_transport_factory) -> None:
    _seed(vault_paths, {"cfb-aa-bb-2025-09-06": _LM})
    with pytest.raises(VaultStateError, match="--league mlb"):
        _refresh(
            vault_paths,
            mock_transport_factory,
            _MIXED,
            {},
            current_season=2026,
            windows=_WINDOWS,
        )


def test_mlb_refresh_window_selects_only_in_window(vault_paths, mock_transport_factory) -> None:
    in_new = "mlb-reds-blues-2026-04-03"
    out_new = "mlb-hawks-doves-2019-06-01"
    out_adv = "mlb-owls-gulls-2019-07-01"
    in_known = "mlb-wrens-jays-2026-06-01"
    event = "mlb-all-star-game-2026-07-14"
    _seed(vault_paths, {out_adv: _LM, in_known: _LM})
    xml = _sitemap_xml(
        [(in_new, _LM), (out_new, _LM), (out_adv, _LM2), (in_known, _LM), (event, _LM)]
    )
    handle, summary = _refresh(
        vault_paths,
        mock_transport_factory,
        xml,
        {_url(in_new): (200, _body(in_new), {})},
        current_season=2026,
        windows=_WINDOWS,
    )
    assert (summary.qualifying, summary.new, summary.advanced) == (1, 1, 0)
    assert summary.selected == 1
    assert summary.backlog == 0
    assert summary.out_of_window == 2
    assert summary.skipped_event == 1
    assert summary.fetched == 1
    assert {r.url for r in handle.requests if "/api/telecast/" in r.url} == {_url(in_new)}
    assert (vault_paths.raw / mlb_rr_path(2026, in_new)).is_file()


def test_mlb_refresh_cap_default_is_forty(vault_paths, mock_transport_factory) -> None:
    old = [f"mlb-t{i:02d}-u{i:02d}-2025-04-{(i % 28) + 1:02d}" for i in range(45)]
    _seed(vault_paths, {s: _LM for s in old})
    xml = _sitemap_xml([(s, _LM2) for s in old])
    windows = [(date(2025, 1, 1), date(2025, 12, 31))]
    extra = {_url(s): (200, _body(s), {}) for s in old}
    _, summary = _refresh(
        vault_paths, mock_transport_factory, xml, extra, current_season=2026, windows=windows
    )
    assert summary.selected == 40
    assert summary.backlog == 5


def test_mlb_run_requires_windows_and_sends_nothing(vault_paths, mock_transport_factory) -> None:
    handle = mock_transport_factory({})
    with pytest.raises(ValueError, match="D-14"):
        _collector(vault_paths, handle).run(date(2026, 4, 1), date(2026, 4, 30), dry_run=False)
    assert handle.requests == []
