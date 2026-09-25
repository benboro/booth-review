"""Tests for the Ratings Reference sitemap and JSON record parsers.

All fixtures under tests/fixtures/ratingsref/ are synthetic: invented team
names and example.org source URLs, never copied from a real 506/RR/CFBD row.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from booth_review.errors import ParseError
from booth_review.seasons import season_window
from booth_review.sources.ratingsref.parser import parse_record
from booth_review.sources.ratingsref.sitemap import parse_sitemap, select_entries

FIXTURES = Path(__file__).parent / "fixtures" / "ratingsref"

_XXE_SITEMAP = b"""<?xml version="1.0"?>
<!DOCTYPE urlset [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://ratingsreference.com/telecast/cfb-example-team-&xxe;-other-team-2025-09-01</loc><lastmod>2026-01-01</lastmod></url>
</urlset>
"""


def test_parse_sitemap_filters_to_dated_cfb_entries() -> None:
    xml = (FIXTURES / "sitemap_synthetic.xml").read_bytes()
    entries, skipped = parse_sitemap(xml)
    assert len(entries) == 4
    assert skipped == 2


def test_parse_sitemap_entry_fields() -> None:
    xml = (FIXTURES / "sitemap_synthetic.xml").read_bytes()
    entries, _ = parse_sitemap(xml)
    entry = next(e for e in entries if e.event_date == date(2025, 9, 13))
    assert entry.telecast_id == "cfb-northfield-state-lakeshore-tech-2025-09-13"
    assert entry.record_url == (
        "https://ratingsreference.com/telecast/cfb-northfield-state-lakeshore-tech-2025-09-13"
    )
    assert entry.json_url == (
        "https://ratingsreference.com/api/telecast/"
        "cfb-northfield-state-lakeshore-tech-2025-09-13.json"
    )
    assert entry.season == 2025
    assert entry.lastmod == "2026-09-20T00:00:00+00:00"


def test_parse_sitemap_season_logic_on_january_entry() -> None:
    xml = (FIXTURES / "sitemap_synthetic.xml").read_bytes()
    entries, _ = parse_sitemap(xml)
    jan_entry = next(e for e in entries if e.event_date == date(2026, 1, 10))
    assert jan_entry.season == 2025


def test_select_entries_within_season_window() -> None:
    xml = (FIXTURES / "sitemap_synthetic.xml").read_bytes()
    entries, _ = parse_sitemap(xml)
    start, end = season_window(2025)
    selected = select_entries(entries, start, end)
    assert len(selected) == 3
    assert all(start <= e.event_date <= end for e in selected)


def test_parse_sitemap_refuses_entity_expansion() -> None:
    try:
        entries, _ = parse_sitemap(_XXE_SITEMAP)
    except ParseError:
        return
    for entry in entries:
        assert "root:" not in entry.record_url
        assert "&xxe;" not in entry.record_url or "xxe" not in entry.telecast_id


def test_parse_record_returns_typed_telecast_and_claims() -> None:
    content = (FIXTURES / "record_synthetic.json").read_bytes()
    record = parse_record(content)
    assert record.telecast.id == "cfb-northfield-state-lakeshore-tech-2025-09-13"
    assert record.telecast.event_date == date(2025, 9, 13)
    assert record.telecast.networks == ["ECN"]
    assert record.telecast.teams == ["cfb-northfield-state", "cfb-lakeshore-tech"]
    assert len(record.claims) == 3


def test_parse_record_claim_statuses_cover_final_preliminary_and_peak() -> None:
    content = (FIXTURES / "record_synthetic.json").read_bytes()
    record = parse_record(content)
    metric_status_pairs = {(c.metric_type, c.status) for c in record.claims}
    assert ("avg_audience", "final") in metric_status_pairs
    assert ("avg_audience", "preliminary") in metric_status_pairs
    assert ("peak_audience", "final") in metric_status_pairs


def test_parse_record_keeps_unknown_claim_fields_in_extra() -> None:
    content = (FIXTURES / "record_synthetic.json").read_bytes()
    record = parse_record(content)
    final_avg_claim = next(
        c for c in record.claims if c.metric_type == "avg_audience" and c.status == "final"
    )
    assert final_avg_claim.model_extra is not None
    assert final_avg_claim.model_extra.get("figure_type") == "currency"


def test_parse_record_drops_peers_block() -> None:
    content = (FIXTURES / "record_synthetic.json").read_bytes()
    record = parse_record(content)
    assert "peers" not in (record.model_extra or {})


def test_parse_record_missing_telecast_id_raises_named_field() -> None:
    import json

    data = json.loads((FIXTURES / "record_synthetic.json").read_bytes())
    del data["telecast"]["id"]
    with pytest.raises(ParseError, match=r"telecast\.id"):
        parse_record(json.dumps(data).encode("utf-8"))


def test_record_url_property() -> None:
    content = (FIXTURES / "record_synthetic.json").read_bytes()
    record = parse_record(content)
    assert record.record_url == (
        "https://ratingsreference.com/telecast/cfb-northfield-state-lakeshore-tech-2025-09-13"
    )
