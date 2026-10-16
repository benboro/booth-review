"""Offline tests for the MLB Wikipedia collector, grid expander and parsers."""

from __future__ import annotations

import hashlib
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from booth_review.mlb.layout import MLB_WIKIPEDIA_LIST_PAGES, mlb_wikipedia_url
from booth_review.sources.wikipedia.mlb_collector import SOURCE, MlbWikipediaCollector
from booth_review.sources.wikipedia.mlb_parser import (
    extract_postseason_map,
    parse_broadcaster_list,
    parse_national_list,
)
from booth_review.sources.wikipedia.tables import expand_wikitable
from booth_review.transport.cache import RawCache
from booth_review.transport.client import PoliteClient

FIXTURES = Path(__file__).parent / "fixtures" / "mlb" / "wikipedia"
URL = "https://en.wikipedia.org/wiki/Synthetic"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _collector(vault_paths, mock_transport_factory) -> MlbWikipediaCollector:
    handle = mock_transport_factory({})
    return MlbWikipediaCollector(RawCache(vault_paths, PoliteClient(transport=handle.transport)))


def test_collector_plan_is_one_plain_wiki_request(vault_paths, mock_transport_factory) -> None:
    (req,) = _collector(vault_paths, mock_transport_factory).plan(2014)
    assert req.source == SOURCE == "mlb_wikipedia"
    assert req.url == mlb_wikipedia_url(2014)
    assert req.cache_path == "mlb/wikipedia/2014.html"


def test_collector_plan_lists_only_plain_wiki_urls(vault_paths, mock_transport_factory) -> None:
    reqs = _collector(vault_paths, mock_transport_factory).plan_lists()
    assert len(reqs) == len(MLB_WIKIPEDIA_LIST_PAGES)
    for req in reqs:
        assert req.season is None
        assert req.url.startswith("https://en.wikipedia.org/wiki/")
        assert "/w/" not in req.url
        assert "/api/" not in req.url
        assert req.cache_path.startswith("mlb/wikipedia/lists/")


def test_collector_dry_run_sends_nothing(vault_paths, mock_transport_factory) -> None:
    handle = mock_transport_factory({})
    collector = MlbWikipediaCollector(
        RawCache(vault_paths, PoliteClient(transport=handle.transport))
    )
    summaries = collector.run([2014, 2015], lists=True, dry_run=True)
    assert len(summaries) == 3
    assert handle.requests == []


def test_expand_wikitable_spans_footnotes_and_nesting() -> None:
    soup = BeautifulSoup(_read("broadcaster_list_synthetic.html"), "html.parser")
    table = soup.find("table")
    assert isinstance(table, Tag)
    grid = expand_wikitable(table)
    assert len({len(r) for r in grid}) == 1
    assert grid[0][2] == grid[0][3] == "Booth"
    assert grid[2][0] == grid[3][0] == "2016"  # rowspan repeated
    assert grid[2][3] == "Sam Beta and Lee Gamma"  # footnote stripped
    assert all("Nested" not in c for r in grid for c in r)


def test_expand_wikitable_caps_runaway_spans() -> None:
    html = '<table><tr><td rowspan="999999">a</td><td colspan="999999">b</td></tr></table>'
    table = BeautifulSoup(html, "html.parser").find("table")
    assert isinstance(table, Tag)
    grid = expand_wikitable(table)
    assert len(grid) == 1
    assert len(grid[0]) <= 3


def _grid(html: str) -> list[list[str]]:
    table = BeautifulSoup(html, "html.parser").find("table")
    assert isinstance(table, Tag)
    return expand_wikitable(table)


def test_expand_wikitable_short_row_under_a_rowspan_keeps_columns() -> None:
    grid = _grid(
        "<table><tr><td>A</td><td>B</td><td rowspan='2'>C</td></tr>"
        "<tr><td>D</td></tr>"
        "<tr><td>E</td><td>F</td><td>G</td></tr></table>"
    )
    assert grid == [["A", "B", "C"], ["D", "", "C"], ["E", "F", "G"]]


def test_expand_wikitable_colspan_over_a_pending_rowspan_drops_it() -> None:
    grid = _grid(
        "<table><tr><td>A</td><td rowspan='3'>B</td></tr>"
        "<tr><td colspan='2'>X</td></tr>"
        "<tr><td>P</td><td>Q</td></tr></table>"
    )
    assert grid == [["A", "B"], ["X", "X"], ["P", "Q"]]


def test_list_crews_split_analysts_and_scope() -> None:
    result = parse_broadcaster_list(_read("broadcaster_list_synthetic.html"), URL, "lcs_al")
    assert result.unparsed == []
    by_net = {(c.season, c.network_raw): c for c in result.crews}
    a16 = by_net[(2016, "NetA")]
    assert (a16.round, a16.league, a16.scope) == ("CS", "AL", "per_series")
    assert a16.pbp_raw == "Pat Alpha"
    assert a16.analysts_raw == ("Sam Beta", "Lee Gamma")
    assert a16.source_url == URL
    b16 = by_net[(2016, "NetB")]
    assert b16.scope == "per_game"
    assert b16.analysts_raw == ("Ray Epsilon", "Jo Zeta")
    assert b16.series_label is not None
    assert by_net[(2017, "NetA")].analysts_raw == ("Sam Beta", "Lee Gamma")
    assert all(c.season != 2099 for c in result.crews)


def test_world_series_has_no_league() -> None:
    result = parse_broadcaster_list(_read("broadcaster_list_synthetic.html"), URL, "world_series")
    assert {c.round for c in result.crews} == {"WS"}
    assert {c.league for c in result.crews} == {None}


def test_malformed_list_is_unparsed_not_guessed() -> None:
    result = parse_broadcaster_list(_read("broadcaster_list_malformed.html"), URL, "wild_card")
    assert result.crews == []
    assert len(result.unparsed) == 1
    assert result.unparsed[0].headers == ("Foo", "Bar", "Baz")


def test_postseason_map_proposals_hash_evidence() -> None:
    props = extract_postseason_map(
        _read("postseason_synthetic.html"), 2016, URL, ["NetA", "NetB", "NetC"]
    )
    keys = {(p.round, p.league, p.network_raw) for p in props}
    assert keys == {
        ("DS", "AL", "NetA"),
        ("CS", "NL", "NetB"),
        ("WS", None, "NetA"),
        ("WC", None, "NetB"),
    }
    sentence = "NetA televised the American League Division Series."
    ds = next(p for p in props if p.round == "DS")
    assert ds.evidence_hash == hashlib.sha256(sentence.encode()).hexdigest()
    assert all(p.source_url == URL and p.season == 2016 for p in props)
    assert not any(hasattr(p, "sentence") for p in props)


def test_national_list_order() -> None:
    crews = parse_national_list(_read("national_list_synthetic.html"), URL)
    assert [(c.network_raw, c.rank) for c in crews] == [("NetA", 1), ("NetA", 2), ("NetB", 1)]
    assert crews[0].pbp_raw == "Pat Alpha"
    assert crews[0].analysts_raw == ("Sam Beta",)
    assert crews[1].analysts_raw == ("Ray Epsilon", "Jo Zeta")
    assert crews[2].pbp_raw == "Lee Gamma"
    assert crews[2].analysts_raw == ("Max Eta",)


def test_radio_tables_skipped_and_spaced_headers_read() -> None:
    html = (
        "<h2>National television</h2><table class='wikitable'>"
        "<tr><th>Year</th><th>Network</th><th>Play-by-play</th><th>Color commentator (s)</th></tr>"
        "<tr><td>2016</td><td>TV</td><td>Pat Alpha</td><td>Sam Beta</td></tr></table>"
        "<h2>National radio</h2><table class='wikitable'>"
        "<tr><th>Year</th><th>Network</th><th>Play-by-play</th><th>Color commentator</th></tr>"
        "<tr><td>2016</td><td>Radio</td><td>Ray Delta</td><td>Lee Gamma</td></tr></table>"
    )
    result = parse_broadcaster_list(html, URL, "lcs_al")
    assert [c.network_raw for c in result.crews] == ["TV"]


def test_wrapped_headings_and_nested_sections_feed_the_map() -> None:
    html = (
        "<div class='mw-heading mw-heading2'><h2>Broadcasting</h2></div>"
        "<section><div class='mw-heading'><h3>Television coverage</h3></div>"
        "<p>Fox aired the World Series.</p></section>"
        "<section><div class='mw-heading'><h3>Radio</h3></div>"
        "<p>ESPN aired the World Series.</p></section>"
    )
    proposals = extract_postseason_map(html, 2099, URL, ["Fox", "ESPN"])
    assert [(p.round, p.network_raw) for p in proposals] == [("WS", "Fox")]


def test_stacked_play_by_play_keeps_the_series_voice() -> None:
    html = (
        "<table><tr><th>Year</th><th>Network</th><th>Play-by-play</th>"
        "<th>Color commentator(s)</th></tr>"
        "<tr><td>2019</td><td>NetA</td>"
        "<td>Pat Alpha (Games 1-3)<br />Quinn Delta (Game 4)</td>"
        "<td>Sam Beta</td></tr></table>"
    )
    crew = parse_broadcaster_list(html, URL, "lcs_al").crews[0]
    assert crew.pbp_raw == "Pat Alpha"
    assert crew.network_raw == "NetA"
    assert crew.analysts_raw == ("Sam Beta",)


_LIST_HEAD = (
    "<table><tr><th>Year</th><th>Network</th><th>Play-by-play</th>"
    "<th>Color commentator(s)</th></tr>"
)


def test_stacked_play_by_play_notes_become_per_game_crews() -> None:
    html = (
        _LIST_HEAD + "<tr><td>2019</td><td>NetA</td>"
        "<td>Pat Alpha (Games 1\u20133, 5\u20136)<br />Quinn Delta (Game 4)</td>"
        "<td>Sam Beta</td></tr></table>"
    )
    crews = parse_broadcaster_list(html, URL, "lcs_al").crews
    per_game = {c.pbp_raw: c for c in crews if c.scope == "per_game"}
    assert per_game["Pat Alpha"].series_label == "Games 1, 2, 3, 5, 6"
    assert per_game["Quinn Delta"].series_label == "Games 4"
    assert per_game["Quinn Delta"].analysts_raw == ("Sam Beta",)
    assert [c.pbp_raw for c in crews if c.scope == "per_series"] == ["Pat Alpha"]


def test_stacked_analysts_with_notes_pair_with_the_game() -> None:
    html = (
        _LIST_HEAD + "<tr><td>2019</td><td>NetA</td><td>Pat Alpha</td>"
        "<td>Sam Beta (Games 1-3)<br />Lou Gamma (Game 4)</td></tr></table>"
    )
    crews = parse_broadcaster_list(html, URL, "lcs_al").crews
    by_label = {c.series_label: c for c in crews if c.scope == "per_game"}
    assert by_label["Games 1, 2, 3"].analysts_raw == ("Sam Beta",)
    assert by_label["Games 4"].analysts_raw == ("Lou Gamma",)
    assert by_label["Games 4"].pbp_raw == "Pat Alpha"
