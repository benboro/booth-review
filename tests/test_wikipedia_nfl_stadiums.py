"""Offline tests for the NFL stadium article planner, parser and draft writer."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from booth_review.cli import main
from booth_review.nfl.layout import (
    NFL_WIKIPEDIA_STADIUM_PAGES,
    wikipedia_stadium_path,
)
from booth_review.nfl.stadium_draft import DRAFT_COLUMNS, build_draft_rows, write_draft
from booth_review.sources.wikipedia.collector import WikipediaCollector
from booth_review.sources.wikipedia.stadium_parser import parse_stadium_coordinates
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient

REFERENCE = Path(__file__).parent.parent / "data" / "reference"


def _collector(vault_paths, mock_transport_factory) -> WikipediaCollector:
    handle = mock_transport_factory({})
    return WikipediaCollector(RawCache(vault_paths, PoliteClient(transport=handle.transport)))


def test_plan_stadiums_is_plain_wiki_urls(vault_paths, mock_transport_factory) -> None:
    plan = _collector(vault_paths, mock_transport_factory).plan_stadiums()
    assert plan
    urls = [r.url for r in plan]
    assert len(set(urls)) == len(urls)  # a shared article is requested once
    for req in plan:
        assert req.source == "nfl_wikipedia"
        assert req.season is None
        assert req.url.startswith("https://en.wikipedia.org/wiki/")
        for banned in ("/w/", "/api/", "?", "index.php"):
            assert banned not in req.url
        assert req.cache_path.startswith("nfl/wikipedia/stadiums/")


def test_pages_cover_reference_rows_with_same_title() -> None:
    pages = dict(NFL_WIKIPEDIA_STADIUM_PAGES)
    with (REFERENCE / "nfl_stadiums.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            prefix = "https://en.wikipedia.org/wiki/"
            if row["source_url"].startswith(prefix):
                assert pages[row["stadium_id"]] == row["source_url"][len(prefix) :]


def test_parse_geo_span() -> None:
    html = b'<div id="coordinates"><span class="geo">33.7554; -84.4008</span></div>'
    assert parse_stadium_coordinates(html) == (33.7554, -84.4008)


def test_parse_geo_dec_fallback() -> None:
    html = (
        b'<table class="infobox"><span class="geo-dec">40.81\xc2\xb0N 74.07\xc2\xb0W</span></table>'
    )
    assert parse_stadium_coordinates(html) == (40.81, -74.07)


def test_parse_none_without_microformat() -> None:
    assert parse_stadium_coordinates(b"<html><p>no coordinates</p></html>") is None


@pytest.mark.parametrize("value", ["95.0; 10.0", "10.0; 200.0", "abc"])
def test_parse_out_of_range_is_none(value: str) -> None:
    html = f'<span class="geo">{value}</span>'.encode()
    assert parse_stadium_coordinates(html) is None


def test_draft_rows_from_cache(vault_paths, tmp_path: Path) -> None:
    cached = vault_paths.raw / wikipedia_stadium_path("ATL97")
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b'<span class="geo">33.7554; -84.4008</span>')
    bad = vault_paths.raw / wikipedia_stadium_path("BAL00")
    bad.write_bytes(b"<p>none</p>")
    rows = {r["stadium_id"]: r for r in build_draft_rows(vault_paths, REFERENCE)}
    assert (rows["ATL97"]["lat"], rows["ATL97"]["lon"]) == ("33.7554", "-84.4008")
    assert rows["ATL97"]["name"] == "Mercedes-Benz Stadium"
    assert rows["BAL00"]["lat"] == "" and "no coordinates" in rows["BAL00"]["note"]
    assert rows["BOS00"]["note"] == "article not cached"
    assert rows["BOS00"]["source_url"].startswith("https://en.wikipedia.org/wiki/")
    target = write_draft(list(rows.values()), tmp_path / "out")
    header = target.read_text(encoding="utf-8").splitlines()[0]
    assert header == ",".join(DRAFT_COLUMNS)


def test_shared_article_id_reads_owner_cache(vault_paths) -> None:
    owner = vault_paths.raw / wikipedia_stadium_path("GER00")
    owner.parent.mkdir(parents=True)
    owner.write_bytes(b'<span class="geo">48.2188; 11.6247</span>')
    rows = {r["stadium_id"]: r for r in build_draft_rows(vault_paths, REFERENCE)}
    assert rows["MUN01"]["lat"] == "48.2188"


def test_cli_dry_run_sends_nothing(
    git_vault, mock_transport_factory, patched_client, capsys
) -> None:
    handle = mock_transport_factory({})
    patched_client(handle)
    code = main(
        ["collect", "wikipedia", "--league", "nfl", "--stadiums", "--season", "2026", "--dry-run"]
    )
    assert code == 0
    assert handle.requests == []
    assert "planned" in capsys.readouterr().out


def test_cli_stadiums_rejected_for_mlb(capsys) -> None:
    code = main(["collect", "wikipedia", "--league", "mlb", "--stadiums", "--season", "2026"])
    assert code == 2
