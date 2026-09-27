"""Telecast-people links (JOIN-03): every crew name on a matched 506
listing becomes one telecast_people row keyed by person_id, never by crew
string, with a role (pbp, analyst, unknown) and a feed type (main, alt,
spanish).

Role assignment follows people/roles.py (D-03/D-04): a two-person crew is
always [pbp, analyst] by listed position; any other size falls back, per
person, to that person's role_override, else their usual_role, else
unknown. Identity comes from people/registry.py (D-01/D-02): a name is
looked up by fold_person against every registered person's variants; a name
missing from the reviewed registry becomes an in-memory-only provisional
person (registered False) via the same fold-grouping register_names uses
for a real registry run, listed in review_people_new.csv for a human to
fold into the public registry later. This build never rewrites people.csv
itself (T-03-36).

An alt or Spanish listing's crew links to the game's rated main telecast --
when the game has exactly one, or the one whose network family matches the
listing's own network when several -- so the person/role filters can
include or exclude MegaCast/alt-cast people from the main dot (D-08); it
also links to its own stored alt/Spanish-feed telecast of the same game and
network when one exists (D-10). A listing that can't be linked to a main
telecast this way is counted "unlinked", never guessed.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import polars as pl

from booth_review.people.normalize import is_placeholder
from booth_review.people.registry import PeopleRegistry, PersonOverride, register_names
from booth_review.people.roles import Role, crew_roles
from booth_review.resolve.networks import NetworkTable
from booth_review.sources.sports506.parser import Listing506

PEOPLE_SCHEMA: dict[str, pl.DataType] = {
    "person_id": pl.Utf8(),
    "canonical_name": pl.Utf8(),
    "variants": pl.List(pl.Utf8()),
    "usual_role": pl.Utf8(),
    "registered": pl.Boolean(),
}

TELECAST_PEOPLE_SCHEMA: dict[str, pl.DataType] = {
    "telecast_id": pl.Utf8(),
    "person_id": pl.Utf8(),
    "role": pl.Utf8(),
    "feed_type": pl.Utf8(),
    "crew_position": pl.Int32(),
    "s506_pointer": pl.Utf8(),
    "source": pl.Utf8(),
}

# review_people_new.csv (vault interim/): a name build_people_links couldn't
# resolve against the reviewed registry, for a human to fold in later.
NEW_NAME_COLUMNS = ("name", "occurrences", "season_first", "season_last", "provisional_id")

_OVERRIDE_SOURCE = "override"
_REGISTERED_SOURCE = "registered"
_PROVISIONAL_SOURCE = "provisional"

_COUNT_KEYS: tuple[str, ...] = (
    "rows_role_pbp",
    "rows_role_analyst",
    "rows_role_unknown",
    "rows_feed_main",
    "rows_feed_alt",
    "rows_feed_spanish",
    "provisional_persons",
    "unlinked_alt_listings",
    "placeholders_skipped",
    "override_rows",
)


@dataclass(frozen=True)
class PeopleLinks:
    """Every table and diagnostic build_people_links produces."""

    people: pl.DataFrame
    telecast_people: pl.DataFrame
    counts: dict[str, int]
    new_name_rows: list[dict[str, object]]


def _network_family(network_id: str | None, networks: NetworkTable) -> str | None:
    if network_id is None:
        return None
    row = networks.networks().get(network_id)
    return row[1] if row is not None else None


def _main_candidates_by_game(telecasts: pl.DataFrame) -> dict[int, list[tuple[str, str | None]]]:
    """game_id -> [(telecast_id, network_id), ...] for every rated main-feed
    telecast, the pool `_resolve_main_link` picks the game's alt/Spanish
    crews' main-dot link from (D-08).
    """
    candidates: dict[int, list[tuple[str, str | None]]] = {}
    if telecasts.height == 0:
        return candidates
    main_rated = telecasts.filter((pl.col("feed_type") == "main") & pl.col("rated"))
    for row in main_rated.select("telecast_id", "game_id", "network_id").iter_rows(named=True):
        candidates.setdefault(row["game_id"], []).append((row["telecast_id"], row["network_id"]))
    return candidates


def _resolve_main_link(
    game_id: int,
    listing_network_id: str | None,
    candidates_by_game: Mapping[int, Sequence[tuple[str, str | None]]],
    networks: NetworkTable,
) -> str | None:
    """The game's rated main telecast_id an alt/Spanish listing's crew links
    to: the sole candidate when there is exactly one, else the candidate
    whose network family matches the listing's own resolved network; None
    (unlinked) when neither rule picks exactly one (D-08).
    """
    candidates = candidates_by_game.get(game_id, ())
    if len(candidates) == 1:
        return candidates[0][0]
    if len(candidates) > 1:
        listing_family = _network_family(listing_network_id, networks)
        if listing_family is not None:
            matches = [
                telecast_id
                for telecast_id, network_id in candidates
                if _network_family(network_id, networks) == listing_family
            ]
            if len(matches) == 1:
                return matches[0]
    return None


def build_people_links(
    listing_links: pl.DataFrame,
    listings_by_pointer: Mapping[tuple[int, str], Listing506],
    telecasts: pl.DataFrame,
    registry: PeopleRegistry,
    person_overrides: Sequence[PersonOverride],
    networks: NetworkTable,
) -> PeopleLinks:
    """Link every crew name on a matched 506 listing to a person_id and role
    (JOIN-03, D-03, D-04, D-08, D-10). `registry`/`person_overrides` come
    from data/reference/ (people.registry.load_people /
    load_person_overrides); this function never writes them back.
    """
    registered_ids_before = set(registry.persons.keys())
    override_by_slot: dict[tuple[int, str, int], str] = {
        (o.season, o.pointer, o.position): o.person_id for o in person_overrides
    }
    candidates_by_game = _main_candidates_by_game(telecasts)

    counts: dict[str, int] = dict.fromkeys(_COUNT_KEYS, 0)

    name_counts: Counter[str] = Counter()
    name_seasons: dict[str, tuple[int, int]] = {}

    # -- Pass 1: collect every non-placeholder crew name across every matched
    # listing, so a provisional person is registered (and folded with any
    # other not-yet-known spelling of the same name) before roles/links are
    # resolved. --------------------------------------------------------------
    for link_row in listing_links.iter_rows(named=True):
        listing = listings_by_pointer.get((link_row["season"], link_row["pointer"]))
        if listing is None:  # pragma: no cover - defensive: every link row has a source listing
            continue
        for name in listing.crew_names:
            if is_placeholder(name):
                counts["placeholders_skipped"] += 1
                continue
            name_counts[name] += 1
            season = link_row["season"]
            lo, hi = name_seasons.get(name, (season, season))
            name_seasons[name] = (min(lo, season), max(hi, season))

    working_registry = register_names(registry, dict(name_counts)) if name_counts else registry

    usual_map: dict[str, Role] = {pid: p.usual_role for pid, p in working_registry.persons.items()}
    override_role_map: dict[str, Role] = {
        pid: p.role_override
        for pid, p in working_registry.persons.items()
        if p.role_override is not None
    }

    telecast_people_rows: dict[tuple[str, str, str], dict[str, object]] = {}

    # -- Pass 2: resolve each listing's crew into person_ids/roles, then link
    # to every telecast that listing's crew belongs to. ----------------------
    for link_row in listing_links.iter_rows(named=True):
        season = link_row["season"]
        pointer = link_row["pointer"]
        listing = listings_by_pointer.get((season, pointer))
        if listing is None:  # pragma: no cover - defensive
            continue

        filtered_names = [name for name in listing.crew_names if not is_placeholder(name)]
        if not filtered_names:
            continue

        slot_person_ids: list[str] = []
        slot_sources: list[str] = []
        for position, name in enumerate(filtered_names):
            override_id = override_by_slot.get((season, pointer, position))
            if override_id is not None:
                slot_person_ids.append(override_id)
                slot_sources.append(_OVERRIDE_SOURCE)
                counts["override_rows"] += 1
                continue
            person_id = working_registry.lookup(name)
            if person_id is None:  # pragma: no cover - register_names covers every name seen
                continue
            slot_person_ids.append(person_id)
            slot_sources.append(
                _REGISTERED_SOURCE if person_id in registered_ids_before else _PROVISIONAL_SOURCE
            )

        roles = crew_roles(slot_person_ids, usual_map, override_role_map)

        is_main = listing.feed_kind == "main"
        targets: list[str] = []
        if is_main:
            if link_row["telecast_id"] is not None:
                targets.append(link_row["telecast_id"])
        else:
            if link_row["telecast_id"] is not None:
                targets.append(link_row["telecast_id"])
            main_link = _resolve_main_link(
                link_row["game_id"], link_row["network_id"], candidates_by_game, networks
            )
            if main_link is not None:
                if main_link not in targets:
                    targets.append(main_link)
            else:
                counts["unlinked_alt_listings"] += 1

        if not targets:
            continue

        feed_type = listing.feed_kind if listing.feed_kind != "unknown" else "main"

        for telecast_id in targets:
            for position, (person_id, role, source) in enumerate(
                zip(slot_person_ids, roles, slot_sources, strict=True)
            ):
                key = (telecast_id, person_id, feed_type)
                if key in telecast_people_rows:
                    continue
                telecast_people_rows[key] = {
                    "telecast_id": telecast_id,
                    "person_id": person_id,
                    "role": role,
                    "feed_type": feed_type,
                    "crew_position": position,
                    "s506_pointer": pointer,
                    "source": source,
                }
                counts[f"rows_role_{role}"] += 1
                counts[f"rows_feed_{feed_type}"] += 1

    telecast_people = pl.DataFrame(
        list(telecast_people_rows.values()), schema=TELECAST_PEOPLE_SCHEMA
    )
    if telecast_people.height:
        telecast_people = telecast_people.sort(["telecast_id", "person_id", "feed_type"])

    provisional_ids = sorted(set(working_registry.persons.keys()) - registered_ids_before)
    counts["provisional_persons"] = len(provisional_ids)

    new_name_rows: list[dict[str, object]] = []
    for person_id in provisional_ids:
        person = working_registry.persons[person_id]
        occurrences = sum(name_counts[v] for v in person.variants if v in name_counts)
        seasons = [name_seasons[v] for v in person.variants if v in name_seasons]
        season_first = min(lo for lo, _hi in seasons) if seasons else None
        season_last = max(hi for _lo, hi in seasons) if seasons else None
        new_name_rows.append(
            {
                "name": person.canonical_name,
                "occurrences": occurrences,
                "season_first": season_first,
                "season_last": season_last,
                "provisional_id": person_id,
            }
        )
    new_name_rows.sort(key=lambda row: str(row["name"]))

    people_rows: list[dict[str, object]] = []
    for person_id, person in sorted(working_registry.persons.items(), key=lambda item: item[0]):
        people_rows.append(
            {
                "person_id": person_id,
                "canonical_name": person.canonical_name,
                "variants": sorted(person.variants),
                "usual_role": person.role_override or person.usual_role,
                "registered": person_id in registered_ids_before,
            }
        )
    people = pl.DataFrame(people_rows, schema=PEOPLE_SCHEMA)
    if people.height:
        people = people.sort("person_id")

    return PeopleLinks(
        people=people,
        telecast_people=telecast_people,
        counts=counts,
        new_name_rows=new_name_rows,
    )
