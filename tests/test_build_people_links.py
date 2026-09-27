"""Tests for build/people_links.py: person_id links with role and feed type,
provisional-person registration, per-slot overrides, and alt/Spanish
main-telecast linking (JOIN-03, D-03, D-04, D-08, D-10).
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from booth_review.build.people_links import (
    NEW_NAME_COLUMNS,
    PEOPLE_SCHEMA,
    TELECAST_PEOPLE_SCHEMA,
    build_people_links,
)
from booth_review.build.tables import assemble_tables
from booth_review.config import DataPaths
from booth_review.people.registry import PeopleRegistry, Person, PersonOverride
from booth_review.resolve.networks import NetworkRow, NetworkTable
from booth_review.sources.sports506.parser import Listing506

_NETWORKS = NetworkTable(
    [
        NetworkRow(
            "Net A", "net-a", "Network A", "family-a", "broadcast", "main", None, None, None
        ),
        NetworkRow("Net B", "net-b", "Network B", "family-b", "cable", "main", None, None, None),
        NetworkRow(
            "Net B Alt", "net-b-alt", "Network B Alt", "family-b", "cable", "alt", None, None, None
        ),
        NetworkRow("Net C", "net-c", "Network C", "family-c", "cable", "main", None, None, None),
        NetworkRow("Net X", "net-x", "Network X", "family-x", "cable", "alt", None, None, None),
    ]
)


def _listing(
    *,
    season: int = 2025,
    week_label: str = "1",
    source_row_index: int = 0,
    crew_names: tuple[str, ...],
    feed_kind: str = "main",
    network_raw: str | None = "Net A",
) -> Listing506:
    return Listing506(
        season=season,
        week_label=week_label,
        source_row_index=source_row_index,
        date_et=date(2025, 9, 6),
        kickoff_et=None,
        away_raw="Away Team",
        away_rank=None,
        home_raw="Home Team",
        home_rank=None,
        neutral=False,
        network_raw=network_raw,
        crew_raw=", ".join(crew_names),
        crew_names=crew_names,
        feed_kind=feed_kind,  # type: ignore[arg-type]
        game_label=None,
    )


def _pointer(listing: Listing506) -> str:
    return f"{listing.week_label}:{listing.source_row_index}"


def _link_row(
    listing: Listing506,
    *,
    game_id: int = 1,
    network_id: str | None = "net-a",
    telecast_id: str | None,
) -> dict[str, object]:
    return {
        "season": listing.season,
        "pointer": _pointer(listing),
        "game_id": game_id,
        "feed_kind": listing.feed_kind,
        "network_id": network_id,
        "telecast_id": telecast_id,
    }


def _links_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(
            schema={
                "season": pl.Int64,
                "pointer": pl.Utf8,
                "game_id": pl.Int64,
                "feed_kind": pl.Utf8,
                "network_id": pl.Utf8,
                "telecast_id": pl.Utf8,
            }
        )
    return pl.DataFrame(rows)


def _telecasts_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(
            schema={
                "telecast_id": pl.Utf8,
                "game_id": pl.Int64,
                "feed_type": pl.Utf8,
                "rated": pl.Boolean,
                "network_id": pl.Utf8,
            }
        )
    return pl.DataFrame(rows)


def _registry(persons: list[Person]) -> PeopleRegistry:
    return PeopleRegistry({p.person_id: p for p in persons})


def _run(
    *,
    listings: list[Listing506],
    link_rows: list[dict[str, object]],
    telecast_rows: list[dict[str, object]] | None = None,
    registry: PeopleRegistry | None = None,
    overrides: list[PersonOverride] | None = None,
    networks: NetworkTable = _NETWORKS,
):
    listings_by_pointer = {(ln.season, _pointer(ln)): ln for ln in listings}
    listing_links = _links_frame(link_rows)
    telecasts = _telecasts_frame(telecast_rows or [])
    return build_people_links(
        listing_links,
        listings_by_pointer,
        telecasts,
        registry if registry is not None else _registry([]),
        overrides or [],
        networks,
    )


# -- Role assignment (D-03/D-04) ---------------------------------------------------------


def test_two_person_crew_is_pbp_then_analyst_by_position() -> None:
    listing = _listing(crew_names=("Alex First", "Sam Second"))
    result = _run(
        listings=[listing],
        link_rows=[_link_row(listing, telecast_id="t1")],
    )

    rows = {r["person_id"]: r for r in result.telecast_people.iter_rows(named=True)}
    first_id = None
    second_id = None
    for row in result.telecast_people.iter_rows(named=True):
        if row["crew_position"] == 0:
            first_id = row["person_id"]
        if row["crew_position"] == 1:
            second_id = row["person_id"]
    assert rows[first_id]["role"] == "pbp"
    assert rows[second_id]["role"] == "analyst"


def test_three_person_crew_uses_override_then_usual_then_unknown() -> None:
    persons = [
        Person("has-override", "Has Override", ("Has Override",), "unknown", "pbp"),
        Person("has-usual", "Has Usual", ("Has Usual",), "analyst", None),
        Person("no-evidence", "No Evidence", ("No Evidence",), "unknown", None),
    ]
    listing = _listing(crew_names=("Has Override", "Has Usual", "No Evidence"))
    result = _run(
        listings=[listing],
        link_rows=[_link_row(listing, telecast_id="t1")],
        registry=_registry(persons),
    )

    roles = {r["person_id"]: r["role"] for r in result.telecast_people.iter_rows(named=True)}
    assert roles["has-override"] == "pbp"
    assert roles["has-usual"] == "analyst"
    assert roles["no-evidence"] == "unknown"


def test_placeholder_crew_slots_are_skipped_and_counted() -> None:
    listing = _listing(crew_names=("Real Person", "TBA"))
    result = _run(listings=[listing], link_rows=[_link_row(listing, telecast_id="t1")])

    assert result.telecast_people.height == 1
    assert result.counts["placeholders_skipped"] == 1


# -- Identity: the person filter must never conflate Golic/Golic Jr., Cris/Jac Collinsworth --


def test_golic_and_golic_jr_stay_distinct_under_the_person_filter() -> None:
    persons = [
        Person("mike-golic", "Mike Golic", ("Mike Golic",), "analyst", None),
        Person("mike-golic-jr", "Mike Golic Jr.", ("Mike Golic Jr.",), "pbp", None),
    ]
    listing_a = _listing(
        week_label="1", source_row_index=0, crew_names=("Mike Golic", "Someone Else")
    )
    listing_b = _listing(
        week_label="1", source_row_index=1, crew_names=("Mike Golic Jr.", "Other Person")
    )
    result = _run(
        listings=[listing_a, listing_b],
        link_rows=[
            _link_row(listing_a, telecast_id="game-a"),
            _link_row(listing_b, telecast_id="game-b"),
        ],
        registry=_registry(persons),
    )

    golic_rows = result.telecast_people.filter(pl.col("person_id") == "mike-golic")
    golic_jr_rows = result.telecast_people.filter(pl.col("person_id") == "mike-golic-jr")
    assert golic_rows["telecast_id"].to_list() == ["game-a"]
    assert golic_jr_rows["telecast_id"].to_list() == ["game-b"]


def test_cris_and_jac_collinsworth_stay_distinct_under_the_person_filter() -> None:
    persons = [
        Person("cris-collinsworth", "Cris Collinsworth", ("Cris Collinsworth",), "analyst", None),
        Person("jac-collinsworth", "Jac Collinsworth", ("Jac Collinsworth",), "pbp", None),
    ]
    listing_a = _listing(
        week_label="1", source_row_index=0, crew_names=("Jac Collinsworth", "Cris Collinsworth")
    )
    listing_b = _listing(week_label="1", source_row_index=1, crew_names=("Jac Collinsworth",))
    result = _run(
        listings=[listing_a, listing_b],
        link_rows=[
            _link_row(listing_a, telecast_id="game-a"),
            _link_row(listing_b, telecast_id="game-b"),
        ],
        registry=_registry(persons),
    )

    cris_rows = result.telecast_people.filter(pl.col("person_id") == "cris-collinsworth")
    jac_rows = result.telecast_people.filter(pl.col("person_id") == "jac-collinsworth")
    assert cris_rows["telecast_id"].to_list() == ["game-a"]
    assert set(jac_rows["telecast_id"].to_list()) == {"game-a", "game-b"}


# -- Provisional persons and the review file --------------------------------------------


def test_unknown_name_becomes_provisional_person_with_review_row() -> None:
    listing = _listing(crew_names=("Newcomer Name", "Second Newcomer"))
    result = _run(listings=[listing], link_rows=[_link_row(listing, telecast_id="t1")])

    people_by_id = {r["person_id"]: r for r in result.people.iter_rows(named=True)}
    telecast_rows = list(result.telecast_people.iter_rows(named=True))
    newcomer_row = next(r for r in telecast_rows if r["crew_position"] == 0)
    assert people_by_id[newcomer_row["person_id"]]["registered"] is False
    assert newcomer_row["source"] == "provisional"
    assert result.counts["provisional_persons"] == 2

    assert {row["name"] for row in result.new_name_rows} == {"Newcomer Name", "Second Newcomer"}
    for row in result.new_name_rows:
        assert row["occurrences"] == 1
        assert row["season_first"] == 2025
        assert row["season_last"] == 2025


def test_registered_person_appears_in_people_frame_even_when_unused() -> None:
    persons = [Person("unused-person", "Unused Person", ("Unused Person",), "unknown", None)]
    result = _run(listings=[], link_rows=[], registry=_registry(persons))

    assert result.people.height == 1
    row = result.people.row(0, named=True)
    assert row["person_id"] == "unused-person"
    assert row["registered"] is True


def test_usual_role_column_prefers_role_override() -> None:
    persons = [Person("p1", "P One", ("P One",), "analyst", "pbp")]
    result = _run(listings=[], link_rows=[], registry=_registry(persons))

    row = result.people.row(0, named=True)
    assert row["usual_role"] == "pbp"


# -- Person overrides (a pointer-only crew-slot replacement) ------------------------------


def test_person_override_replaces_crew_slot() -> None:
    persons = [
        Person("wrong-person", "Wrong Person", ("Wrong Person",), "unknown", None),
        Person("right-person", "Right Person", ("Right Person",), "pbp", None),
    ]
    listing = _listing(
        week_label="1", source_row_index=5, crew_names=("Wrong Person", "Analyst Person")
    )
    override = PersonOverride(
        season=2025, pointer=_pointer(listing), position=0, person_id="right-person", reason="other"
    )
    result = _run(
        listings=[listing],
        link_rows=[_link_row(listing, telecast_id="t1")],
        registry=_registry(persons),
        overrides=[override],
    )

    rows = {r["crew_position"]: r for r in result.telecast_people.iter_rows(named=True)}
    assert rows[0]["person_id"] == "right-person"
    assert rows[0]["source"] == "override"
    assert result.counts["override_rows"] == 1
    # wrong-person is never linked to this telecast at all.
    assert "wrong-person" not in result.telecast_people["person_id"].to_list()


# -- Alt/Spanish listings link to the game's rated main telecast (D-08) plus their own
# stored alt/Spanish-feed telecast when one exists (D-10) --------------------------------


def test_alt_listing_links_to_the_sole_rated_main_telecast() -> None:
    listing = _listing(
        week_label="1",
        source_row_index=0,
        crew_names=("Alt One", "Alt Two"),
        feed_kind="alt",
        network_raw="Net B Alt",
    )
    result = _run(
        listings=[listing],
        link_rows=[_link_row(listing, game_id=1, network_id="net-b-alt", telecast_id=None)],
        telecast_rows=[
            {
                "telecast_id": "main-1",
                "game_id": 1,
                "feed_type": "main",
                "rated": True,
                "network_id": "net-b",
            }
        ],
    )

    assert result.telecast_people["telecast_id"].to_list() == ["main-1", "main-1"]
    assert set(result.telecast_people["feed_type"].to_list()) == {"alt"}
    assert result.counts["unlinked_alt_listings"] == 0


def test_alt_listing_picks_the_family_matched_main_telecast_when_several() -> None:
    listing = _listing(
        week_label="1",
        source_row_index=0,
        crew_names=("Alt One",),
        feed_kind="alt",
        network_raw="Net B Alt",
    )
    result = _run(
        listings=[listing],
        link_rows=[_link_row(listing, game_id=1, network_id="net-b-alt", telecast_id=None)],
        telecast_rows=[
            {
                "telecast_id": "main-b",
                "game_id": 1,
                "feed_type": "main",
                "rated": True,
                "network_id": "net-b",
            },
            {
                "telecast_id": "main-c",
                "game_id": 1,
                "feed_type": "main",
                "rated": True,
                "network_id": "net-c",
            },
        ],
    )

    assert result.telecast_people["telecast_id"].to_list() == ["main-b"]
    assert result.counts["unlinked_alt_listings"] == 0


def test_alt_listing_is_unlinked_when_no_family_matches_among_several() -> None:
    listing = _listing(
        week_label="1",
        source_row_index=0,
        crew_names=("Alt One",),
        feed_kind="alt",
        network_raw="Net X",
    )
    result = _run(
        listings=[listing],
        link_rows=[_link_row(listing, game_id=1, network_id="net-x", telecast_id=None)],
        telecast_rows=[
            {
                "telecast_id": "main-b",
                "game_id": 1,
                "feed_type": "main",
                "rated": True,
                "network_id": "net-b",
            },
            {
                "telecast_id": "main-c",
                "game_id": 1,
                "feed_type": "main",
                "rated": True,
                "network_id": "net-c",
            },
        ],
    )

    assert result.telecast_people.height == 0
    assert result.counts["unlinked_alt_listings"] == 1


def test_alt_listing_also_links_to_its_own_stored_alt_telecast() -> None:
    listing = _listing(
        week_label="1",
        source_row_index=0,
        crew_names=("Alt One",),
        feed_kind="alt",
        network_raw="Net B Alt",
    )
    result = _run(
        listings=[listing],
        link_rows=[_link_row(listing, game_id=1, network_id="net-b-alt", telecast_id="alt-1")],
        telecast_rows=[
            {
                "telecast_id": "main-b",
                "game_id": 1,
                "feed_type": "main",
                "rated": True,
                "network_id": "net-b",
            }
        ],
    )

    linked_ids = set(result.telecast_people["telecast_id"].to_list())
    assert linked_ids == {"main-b", "alt-1"}


# -- Dedup and determinism ----------------------------------------------------------------


def test_telecast_people_rows_are_unique_and_sorted() -> None:
    listing_a = _listing(week_label="1", source_row_index=0, crew_names=("Shared Person",))
    listing_b = _listing(week_label="1", source_row_index=1, crew_names=("Shared Person",))
    result = _run(
        listings=[listing_a, listing_b],
        link_rows=[
            _link_row(listing_a, telecast_id="t1"),
            _link_row(listing_b, telecast_id="t1"),
        ],
    )

    assert result.telecast_people.height == 1
    ids = result.telecast_people["telecast_id"].to_list()
    assert ids == sorted(ids)


# -- Schema shape -----------------------------------------------------------------------


def test_no_crew_raw_or_free_text_column_in_either_schema() -> None:
    assert "crew_raw" not in PEOPLE_SCHEMA
    assert "crew_raw" not in TELECAST_PEOPLE_SCHEMA
    assert set(TELECAST_PEOPLE_SCHEMA) == {
        "telecast_id",
        "person_id",
        "role",
        "feed_type",
        "crew_position",
        "s506_pointer",
        "source",
    }


# -- Integration: a real assemble_tables run over the shared build fixtures --------------


@pytest.fixture
def vault_reference(build_reference: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    extended = tmp_path / "reference_ext"
    shutil.copytree(build_reference, extended)
    with (extended / "networks.csv").open("a", encoding="utf-8", newline="") as fh:
        fh.write("ECN,ecn,Example Cable Network,family-ecn,cable,main,,,\n")
        fh.write("ECN2,ecn2,Example Cable Network 2,family-ecn,cable,main,,,\n")
        fh.write("ESPN,espn,ESPN,family-espn,cable,main,,,\n")
        fh.write("ESPN2,espn2,ESPN2,family-espn,cable,main,,,\n")
        fh.write("ESPNU,espnu,ESPNU,family-espn,cable,main,,,\n")
        fh.write("ESPN Deportes,espn-deportes,ESPN Deportes,family-espn,cable,spanish,,,\n")
    monkeypatch.setenv("BOOTH_REVIEW_REFERENCE", str(extended))
    return extended


def test_assemble_tables_produces_non_empty_schema_exact_people_frames(
    build_vault: DataPaths, vault_reference: Path
) -> None:
    tables = assemble_tables(build_vault, vault_reference, seasons=[2025])

    assert tables.people.height > 0
    assert tables.people.columns == list(PEOPLE_SCHEMA.keys())
    assert tables.telecast_people.height > 0
    assert tables.telecast_people.columns == list(TELECAST_PEOPLE_SCHEMA.keys())
    assert tables.review_rows["review_people_new"][0] == NEW_NAME_COLUMNS


# -- CR-04: an override naming a person_id missing from people.csv fails cleanly -------------


def test_person_override_with_unknown_person_id_raises_reference_table_error() -> None:
    from booth_review.errors import ReferenceTableError

    persons = [Person("known-person", "Known Person", ("Known Person",), "pbp", None)]
    listing = _listing(week_label="1", source_row_index=5, crew_names=("Known Person",))
    override = PersonOverride(
        season=2025,
        pointer=_pointer(listing),
        position=0,
        person_id="no-such-person",
        reason="two-people",
    )

    with pytest.raises(ReferenceTableError, match=r"person_overrides\.csv.*no-such-person"):
        _run(
            listings=[listing],
            link_rows=[_link_row(listing, telecast_id="t1")],
            registry=_registry(persons),
            overrides=[override],
        )
