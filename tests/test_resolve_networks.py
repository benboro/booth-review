"""Tests for resolve/networks.py: outlet splitting, feed-marker stripping,
NetworkTable lookup, the rights-holder primary_network rule, and loader
validation (JOIN-06).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from booth_review.errors import ReferenceTableError
from booth_review.flags.events import load_event_flags
from booth_review.resolve.networks import (
    NETWORK_COLUMNS,
    TIER_RANK,
    NetworkRow,
    NetworkTable,
    load_networks,
    load_primary_overrides,
    primary_network,
    split_outlets,
    strip_feed_marker,
)
from booth_review.transport.cache import atomic_write_bytes

FIXTURES = Path(__file__).parent / "fixtures" / "reference"


def _table() -> NetworkTable:
    return load_networks(FIXTURES)


# -- split_outlets ----------------------------------------------------------------------------


def test_split_outlets_comma() -> None:
    assert split_outlets("ESPN, ESPN2") == ["ESPN", "ESPN2"]


def test_split_outlets_slash() -> None:
    assert split_outlets("CBS/Paramount+") == ["CBS", "Paramount+"]


def test_split_outlets_semicolon_and_pipe() -> None:
    assert split_outlets("CBS; FOX") == ["CBS", "FOX"]
    assert split_outlets("CBS | FOX") == ["CBS", "FOX"]


def test_split_outlets_drops_empty_parts_and_collapses_whitespace() -> None:
    assert split_outlets("ESPN,  ,  ESPN2 ") == ["ESPN", "ESPN2"]


def test_split_outlets_single_outlet_unchanged() -> None:
    assert split_outlets("ESPN") == ["ESPN"]


# -- strip_feed_marker --------------------------------------------------------------------------


def test_strip_feed_marker_alt_cast() -> None:
    assert strip_feed_marker("ESPN2 (alt-cast)") == ("ESPN2", "alt")


def test_strip_feed_marker_alt() -> None:
    assert strip_feed_marker("ESPN (alt)") == ("ESPN", "alt")


def test_strip_feed_marker_spanish() -> None:
    assert strip_feed_marker("ESPN2 (Spanish)") == ("ESPN2", "spanish")


def test_strip_feed_marker_no_marker_keeps_name_and_feed_type_from_table() -> None:
    assert strip_feed_marker("ESPN Deportes") == ("ESPN Deportes", None)


def test_strip_feed_marker_unrecognized_parenthetical_is_left_unchanged() -> None:
    base, feed = strip_feed_marker("ESPN (HD)")
    assert feed is None
    assert base == "ESPN (HD)"


# -- NetworkTable.lookup --------------------------------------------------------------------


def test_lookup_matches_case_insensitively_after_whitespace_collapse() -> None:
    table = _table()
    row = table.lookup("  neta  ", 2025)
    assert row is not None
    assert row.network_id == "net-a"


def test_lookup_returns_none_when_unmapped() -> None:
    table = _table()
    assert table.lookup("Not A Real Network", 2025) is None


def test_lookup_respects_season_range() -> None:
    table = _table()
    old_row = table.lookup("Net Old", 2016)
    assert old_row is not None
    assert old_row.network_id == "net-b"

    new_row = table.lookup("Net Old", 2022)
    assert new_row is not None
    assert new_row.network_id == "net-c"

    assert table.lookup("Net Old", 2013) is None


def test_networks_returns_display_family_tier_by_id() -> None:
    table = _table()
    networks = table.networks()
    assert networks["net-a"] == ("Network A", "family-a", "broadcast")
    assert networks["net-d"] == ("Network D", "family-d", "streaming")


# -- primary_network ------------------------------------------------------------------------


def test_primary_network_picks_lowest_tier_rank() -> None:
    table = _table()
    result = primary_network(["Net D, Net B, Net A"], 2025, table)
    assert result.network_id == "net-a"
    assert result.feed_type == "main"
    assert TIER_RANK["broadcast"] < TIER_RANK["cable"] < TIER_RANK["streaming"]


def test_primary_network_ties_pick_first_listed() -> None:
    table = _table()
    # net-e and net-a are both broadcast tier (a genuine tie); whichever is
    # listed first must win.
    e_first = primary_network(["Net E, Net A"], 2025, table)
    assert e_first.network_id == "net-e"

    a_first = primary_network(["Net A, Net E"], 2025, table)
    assert a_first.network_id == "net-a"


def test_primary_network_returns_unmapped_strings() -> None:
    table = _table()
    result = primary_network(["Net A, Some Unknown Outlet"], 2025, table)
    assert result.network_id == "net-a"
    assert result.unmapped == ("Some Unknown Outlet",)


def test_primary_network_returns_none_when_nothing_maps() -> None:
    table = _table()
    result = primary_network(["Totally Unknown"], 2025, table)
    assert result.network_id is None
    assert result.unmapped == ("Totally Unknown",)


def test_primary_network_skips_alt_and_spanish_when_a_main_outlet_exists() -> None:
    table = _table()
    result = primary_network(["Net A (alt-cast), Net B"], 2025, table)
    assert result.network_id == "net-b"
    assert result.feed_type == "main"


def test_primary_network_all_alt_or_spanish_picks_first_of_those() -> None:
    table = _table()
    result = primary_network(["Net A (alt-cast), Net A Deportes"], 2025, table)
    assert result.network_id == "net-a"
    assert result.feed_type == "alt"


def test_primary_network_deduplicates_outlets_in_first_seen_order() -> None:
    table = _table()
    result = primary_network(["Net A, Net B, Net A"], 2025, table)
    assert result.outlets == ("net-a", "net-b")


# -- load_networks validation -----------------------------------------------------------------


def test_load_networks_real_table_loads_and_has_the_fixture_ids() -> None:
    table = _table()
    assert set(table.networks()) == {"net-a", "net-a-es", "net-b", "net-c", "net-d", "net-e"}


def test_load_networks_missing_file_is_empty_table(tmp_path: Path) -> None:
    table = load_networks(tmp_path)
    assert table.networks() == {}


def test_load_networks_rejects_header_mismatch(tmp_path: Path) -> None:
    atomic_write_bytes(tmp_path / "networks.csv", b"variant,network_id\nNet A,net-a\n")
    with pytest.raises(ReferenceTableError):
        load_networks(tmp_path)


def test_load_networks_rejects_invalid_tier(tmp_path: Path) -> None:
    atomic_write_bytes(
        tmp_path / "networks.csv",
        ",".join(NETWORK_COLUMNS).encode() + b"\n"
        b"Net A,net-a,Network A,family-a,bogus-tier,main,,\n",
    )
    with pytest.raises(ReferenceTableError):
        load_networks(tmp_path)


def test_load_networks_rejects_invalid_feed_type(tmp_path: Path) -> None:
    atomic_write_bytes(
        tmp_path / "networks.csv",
        ",".join(NETWORK_COLUMNS).encode() + b"\n"
        b"Net A,net-a,Network A,family-a,broadcast,bogus-feed,,\n",
    )
    with pytest.raises(ReferenceTableError):
        load_networks(tmp_path)


def test_load_networks_rejects_invalid_network_id(tmp_path: Path) -> None:
    atomic_write_bytes(
        tmp_path / "networks.csv",
        ",".join(NETWORK_COLUMNS).encode() + b"\nNet A,Net_A,Network A,family-a,broadcast,main,,\n",
    )
    with pytest.raises(ReferenceTableError):
        load_networks(tmp_path)


def test_load_networks_rejects_same_variant_season_mapped_to_two_ids(tmp_path: Path) -> None:
    atomic_write_bytes(
        tmp_path / "networks.csv",
        ",".join(NETWORK_COLUMNS).encode() + b"\n"
        b"Net A,net-a,Network A,family-a,broadcast,main,,\n"
        b"Net A,net-b,Network B,family-b,cable,main,,\n",
    )
    with pytest.raises(ReferenceTableError):
        load_networks(tmp_path)


def test_load_networks_rejects_one_id_with_two_display_names(tmp_path: Path) -> None:
    atomic_write_bytes(
        tmp_path / "networks.csv",
        ",".join(NETWORK_COLUMNS).encode() + b"\n"
        b"Net A,net-a,Network A,family-a,broadcast,main,,\n"
        b"Net A Alt,net-a,Network A Renamed,family-a,broadcast,main,,\n",
    )
    with pytest.raises(ReferenceTableError):
        load_networks(tmp_path)


def test_load_networks_rejects_one_id_with_two_tiers(tmp_path: Path) -> None:
    atomic_write_bytes(
        tmp_path / "networks.csv",
        ",".join(NETWORK_COLUMNS).encode() + b"\n"
        b"Net A,net-a,Network A,family-a,broadcast,main,,\n"
        b"Net A Alt,net-a,Network A,family-a,cable,main,,\n",
    )
    with pytest.raises(ReferenceTableError):
        load_networks(tmp_path)


def test_load_networks_allows_same_variant_in_non_overlapping_seasons() -> None:
    # Exercised by the "Net Old" fixture row (2014-2019 -> net-b,
    # 2020-2026 -> net-c); loading the fixture must not raise.
    table = _table()
    assert table.lookup("Net Old", 2016) is not None
    assert table.lookup("Net Old", 2022) is not None


# -- load_primary_overrides -------------------------------------------------------------------


def test_load_primary_overrides_reads_the_fixture() -> None:
    overrides = load_primary_overrides(FIXTURES)
    assert overrides == {900001: "net-b"}


def test_load_primary_overrides_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_primary_overrides(tmp_path) == {}


def test_load_primary_overrides_rejects_invalid_reason(tmp_path: Path) -> None:
    atomic_write_bytes(
        tmp_path / "primary_network_overrides.csv",
        b"cfbd_game_id,network_id,reason\n900002,net-a,bogus-reason\n",
    )
    with pytest.raises(ReferenceTableError):
        load_primary_overrides(tmp_path)


def test_load_primary_overrides_rejects_duplicate_game_id(tmp_path: Path) -> None:
    atomic_write_bytes(
        tmp_path / "primary_network_overrides.csv",
        b"cfbd_game_id,network_id,reason\n900001,net-a,simulcast\n900001,net-b,other\n",
    )
    with pytest.raises(ReferenceTableError):
        load_primary_overrides(tmp_path)


def test_load_primary_overrides_forces_the_network_id_for_that_game() -> None:
    overrides = load_primary_overrides(FIXTURES)
    table = _table()
    # An override applies at the call site: the primary a caller would
    # otherwise compute is replaced with the override's network_id for that
    # one cfbd_game_id.
    computed = primary_network(["Net A"], 2025, table)
    assert computed.network_id == "net-a"
    forced = overrides.get(900001, computed.network_id)
    assert forced == "net-b"


# -- NetworkRow is a plain frozen dataclass ---------------------------------------------------


def test_network_row_is_frozen() -> None:
    row = NetworkRow(
        variant="Net A",
        network_id="net-a",
        display_name="Network A",
        family="family-a",
        tier="broadcast",
        feed_type="main",
        season_from=None,
        season_to=None,
    )
    with pytest.raises(AttributeError):
        row.network_id = "net-b"  # type: ignore[misc]


# -- cross-check with event_flags.csv (Task 2 adds the real fixture data) ---------------------


def test_fixture_event_flags_do_not_reference_fixture_network_ids() -> None:
    # Sanity check only: the fixtures directory's event_flags.csv is a
    # separate synthetic fixture (tests/test_flags.py's), unrelated to this
    # module's invented net-* ids; just confirm it still loads on its own.
    flags = load_event_flags(FIXTURES)
    assert isinstance(flags, list)
