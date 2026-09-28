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


# -- rr_current_claim_id / rr_current_status (research Pattern 2, T-03-05) -----------------


def _record_data() -> dict:
    import json

    return json.loads((FIXTURES / "record_synthetic.json").read_bytes())


def test_rr_current_found_with_exactly_one_current_self_row() -> None:
    import json

    data = _record_data()
    self_id = data["telecast"]["id"]
    data["peers"] = {
        "rows": [{"telecast_id": self_id, "claim_id": "the-current-claim", "current": True}]
    }
    record = parse_record(json.dumps(data).encode("utf-8"))
    assert record.rr_current_claim_id == "the-current-claim"
    assert record.rr_current_status == "found"


def test_rr_current_no_peers_when_peers_key_is_absent() -> None:
    import json

    data = _record_data()
    del data["peers"]
    record = parse_record(json.dumps(data).encode("utf-8"))
    assert record.rr_current_claim_id is None
    assert record.rr_current_status == "no_peers"


def test_rr_current_no_peers_when_peers_is_null_or_lacks_rows() -> None:
    import json

    for peers_value in (None, {}, {"rows": "not-a-list"}):
        data = _record_data()
        data["peers"] = peers_value
        record = parse_record(json.dumps(data).encode("utf-8"))
        assert record.rr_current_claim_id is None
        assert record.rr_current_status == "no_peers"


def test_rr_current_no_self_row_when_no_row_matches() -> None:
    import json

    data = _record_data()
    self_id = data["telecast"]["id"]
    data["peers"] = {
        "rows": [
            {"telecast_id": "some-other-telecast", "claim_id": "c-other", "current": True},
            {"telecast_id": self_id, "claim_id": "c-not-current", "current": False},
        ]
    }
    record = parse_record(json.dumps(data).encode("utf-8"))
    assert record.rr_current_claim_id is None
    assert record.rr_current_status == "no_self_row"


def test_rr_current_multiple_current_when_two_self_rows_are_current() -> None:
    import json

    data = _record_data()
    self_id = data["telecast"]["id"]
    data["peers"] = {
        "rows": [
            {"telecast_id": self_id, "claim_id": "c-one", "current": True},
            {"telecast_id": self_id, "claim_id": "c-two", "current": True},
        ]
    }
    record = parse_record(json.dumps(data).encode("utf-8"))
    assert record.rr_current_claim_id is None
    assert record.rr_current_status == "multiple_current"


def test_rr_current_skips_a_malformed_row_without_raising() -> None:
    import json

    data = _record_data()
    self_id = data["telecast"]["id"]
    data["peers"] = {
        "rows": [
            "not-a-dict-row",
            {"telecast_id": self_id, "claim_id": 12345, "current": True},  # claim_id not a string
            {"telecast_id": self_id, "claim_id": "c-good", "current": True},
        ]
    }
    record = parse_record(json.dumps(data).encode("utf-8"))
    assert record.rr_current_claim_id == "c-good"
    assert record.rr_current_status == "found"
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


def test_parse_record_accepts_int_tier() -> None:
    """Real Ratings Reference records carry an int tier level (e.g. 1, 2),
    not the string label ("national") the initial fixture used.
    """
    import json

    data = json.loads((FIXTURES / "record_synthetic.json").read_bytes())
    data["telecast"]["tier"] = 2
    record = parse_record(json.dumps(data).encode("utf-8"))
    assert record.telecast.tier == 2
