"""The telecasts table (JOIN-02/05/06): match every 506 listing and RR record
to a CFBD game through the crosswalk-aware matcher (resolve/teams.py,
resolve/overrides.py, resolve/games.py), resolve each telecast's primary
(rights-holder) network (resolve/networks.py), merge duplicate RR records
that land on the same (game, primary network) key (JOIN-05), attach the
matching 506 main listing for crew (JOIN-03), and carry every mapped outlet
for the hover (JOIN-06).

Matching runs against every division's games (the caller's `index` covers
all of them); scope is then checked against `games`, the already FBS-scoped,
season-type-filtered frame from build.games -- a record or listing matched to
a game missing from that frame is out of scope, never guessed into it.

Every review CSV row this module discovers (an unmatched record/listing, an
unresolved team name) is built through resolve.diagnose's shared row-builders
(`unmatched_row`, `unresolved_rows`, `track_unresolved`, `suggest_canonical`),
so a real vault's `python -m booth_review.resolve.diagnose` and this build
report the exact same evidence for the exact same input (T-03-29).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

import polars as pl

from booth_review.build.sources import SeasonSources
from booth_review.errors import VaultStateError
from booth_review.people.normalize import is_placeholder
from booth_review.resolve.diagnose import (
    UnmatchedRow,
    UnresolvedTeamRow,
    counts_as_unresolved,
    suggest_canonical,
    track_unresolved,
)
from booth_review.resolve.games import (
    CONFIDENCE_RANK,
    GameIndex,
    MatchConfidence,
    match_listing_to_game,
    match_record_to_game,
)
from booth_review.resolve.names import to_et_date, to_et_datetime
from booth_review.resolve.networks import (
    FeedType,
    NetworkTable,
    PrimaryResult,
    primary_network,
    split_outlets,
    strip_feed_marker,
)
from booth_review.resolve.overrides import GameOverride, pointer_for_listing, pointer_for_record
from booth_review.resolve.teams import TeamResolver
from booth_review.sources.cfbd.parser import CfbdGame
from booth_review.sources.ratingsref.parser import RRRecord
from booth_review.sources.sports506.parser import Listing506

TELECASTS_SCHEMA: dict[str, pl.DataType] = {
    "telecast_id": pl.Utf8(),
    "game_id": pl.Int64(),
    "season": pl.Int32(),
    "date_et": pl.Date(),
    "network_id": pl.Utf8(),
    "feed_type": pl.Utf8(),
    "outlets": pl.List(pl.Utf8()),
    "rated": pl.Boolean(),
    "rr_telecast_ids": pl.List(pl.Utf8()),
    "rr_record_urls": pl.List(pl.Utf8()),
    "duplicate_merges": pl.Int32(),
    "rr_match_confidence": pl.Utf8(),
    "s506_match_confidence": pl.Utf8(),
    "match_confidence": pl.Utf8(),
    "s506_pointer": pl.Utf8(),
    "s506_week": pl.Utf8(),
    "s506_url": pl.Utf8(),
    "kickoff_et": pl.Utf8(),
    "crew_matched": pl.Boolean(),
    "crew_network_mismatch": pl.Boolean(),
    # Filled by build.crew_overrides.apply_crew_overrides (04.3 D-11/D-13).
    "crew_patched": pl.Boolean(),
    "crew_source_url": pl.Utf8(),
    "crew_source_label": pl.Utf8(),
    "combined_feeds": pl.Int32(),
    # Filled by build.viewership.apply_headlines (Plan 08 Task 2); left
    # nullable here.
    "plotted": pl.Boolean(),
    "headline_claim_id": pl.Utf8(),
    "headline_value": pl.Float64(),
    "headline_publisher": pl.Utf8(),
    "headline_source_url": pl.Utf8(),
    "measurement_type": pl.Utf8(),
    "era_id": pl.Utf8(),
    "rr_current_check": pl.Utf8(),
    "model_break": pl.Boolean(),
}

LISTING_LINKS_SCHEMA: dict[str, pl.DataType] = {
    "season": pl.Int32(),
    "week_label": pl.Utf8(),
    "source_row_index": pl.Int32(),
    "pointer": pl.Utf8(),
    "game_id": pl.Int64(),
    "feed_kind": pl.Utf8(),
    "network_id": pl.Utf8(),
    "telecast_id": pl.Utf8(),
    "crew_size": pl.Int32(),
}

_UNMAPPED_ID = "unmapped"

_COUNT_KEYS: tuple[str, ...] = (
    "rr_records",
    "rr_parse_errors",
    "rr_excluded",
    "rr_out_of_scope",
    "rr_unmatched",
    "rr_matched",
    "rated_telecasts",
    "rated_with_crew",
    "records_with_crew",
    # records_with_crew as the 506 join alone left it: apply_crew_overrides
    # (04.3) raises records_with_crew for a patched crew but never this, so
    # the AUDIT-03 guard can still see a 506 crew that disappears (IN-06).
    "records_with_506_crew",
    "duplicate_merges",
    "listings_total",
    "listings_matched",
    "listings_unmatched",
    "unmapped_outlets",
    "unresolved_team_names",
)


@dataclass(frozen=True)
class TelecastBuild:
    """Every table and diagnostic row build_telecasts produces."""

    telecasts: pl.DataFrame
    listing_links: pl.DataFrame
    records_by_telecast: dict[str, list[RRRecord]]
    counts: dict[int, dict[str, int]]
    unmatched_rows: list[UnmatchedRow]
    unresolved_rows: list[UnresolvedTeamRow]


@dataclass
class _TelecastDraft:
    """One (game, primary network) telecast under construction."""

    key: tuple[str | None, FeedType]
    game: CfbdGame
    rated: bool
    records: list[tuple[RRRecord, MatchConfidence]] = field(default_factory=list)
    matched_listing: Listing506 | None = None
    listing_confidence: MatchConfidence | None = None
    crew_network_mismatch: bool = False

    @property
    def network_id(self) -> str | None:
        return self.key[0]

    @property
    def feed_type(self) -> FeedType:
        return self.key[1]


def _telecast_id(game_id: int, network_id: str | None, feed_type: FeedType) -> str:
    """`<game_id>-<network_id>` for a main feed; an alt/Spanish feed of the
    same network gets a `-<feed_type>` suffix so it can never share an id
    with that network's main feed (D-10). Main-feed ids keep their original
    shape, so every existing pointer to one stays valid.
    """
    base = f"{game_id}-{network_id if network_id is not None else _UNMAPPED_ID}"
    return base if feed_type == "main" else f"{base}-{feed_type}"


def _listing_primary(listing: Listing506, season: int, table: NetworkTable) -> PrimaryResult:
    texts = [listing.network_raw] if listing.network_raw else []
    return primary_network(texts, season, table)


def _telecast_outlets(
    primary_id: str | None,
    rr_networks: Sequence[str],
    listing_networks: Sequence[str],
    media_outlets: Sequence[str],
    season: int,
    table: NetworkTable,
) -> list[str]:
    ordered: list[str] = []
    if primary_id is not None:
        ordered.append(primary_id)
    for raw_texts in (rr_networks, listing_networks, media_outlets):
        for outlet_text in raw_texts:
            for outlet in _split_and_lookup(outlet_text, season, table):
                if outlet not in ordered:
                    ordered.append(outlet)
    return ordered


def _split_and_lookup(text: str, season: int, table: NetworkTable) -> list[str]:
    ids: list[str] = []
    for outlet in split_outlets(text):
        base, _marker = strip_feed_marker(outlet)
        row = table.lookup(base, season)
        if row is not None and row.network_id not in ids:
            ids.append(row.network_id)
    return ids


def _worst_confidence(confidences: Sequence[MatchConfidence]) -> MatchConfidence | None:
    if not confidences:
        return None
    return max(confidences, key=lambda c: CONFIDENCE_RANK[c])


def _combined_feeds(records: Sequence[RRRecord]) -> int | None:
    for record in records:
        for claim in record.claims:
            if claim.composite_of:
                return len(claim.composite_of)
    return None


def _listing_link_row(
    listing: Listing506, game_id: int, network_id: str | None, telecast_id: str | None
) -> dict[str, object]:
    return {
        "season": listing.season,
        "week_label": listing.week_label,
        "source_row_index": listing.source_row_index,
        "pointer": pointer_for_listing(listing),
        "game_id": game_id,
        "feed_kind": listing.feed_kind,
        "network_id": network_id,
        "telecast_id": telecast_id,
        "crew_size": len(listing.crew_names),
    }


def _finalize_telecast(
    draft: _TelecastDraft, season: int, networks_table: NetworkTable, media_outlets: Sequence[str]
) -> dict[str, object]:
    game = draft.game
    telecast_id = _telecast_id(game.id, draft.network_id, draft.feed_type)

    rr_networks_text = [n for record, _ in draft.records for n in record.telecast.networks]
    listing_networks_text = (
        [draft.matched_listing.network_raw]
        if draft.matched_listing is not None and draft.matched_listing.network_raw
        else []
    )
    outlets = _telecast_outlets(
        draft.network_id,
        rr_networks_text,
        listing_networks_text,
        media_outlets,
        season,
        networks_table,
    )

    rr_confidences = [confidence for _, confidence in draft.records]
    rr_match_confidence = _worst_confidence(rr_confidences)
    s506_match_confidence = draft.listing_confidence
    match_confidence = _worst_confidence(
        [c for c in (rr_match_confidence, s506_match_confidence) if c is not None]
    )

    crew_matched = draft.matched_listing is not None and any(
        not is_placeholder(name) for name in draft.matched_listing.crew_names
    )

    date_et: date = to_et_date(game.start_date)
    if draft.matched_listing is not None and draft.matched_listing.kickoff_et is not None:
        kickoff_et = draft.matched_listing.kickoff_et.isoformat()
    elif game.start_time_tbd:
        kickoff_et = None
    else:
        kickoff_et = to_et_datetime(game.start_date).isoformat()

    return {
        "telecast_id": telecast_id,
        "game_id": game.id,
        "season": season,
        "date_et": date_et,
        "network_id": draft.network_id,
        "feed_type": draft.feed_type,
        "outlets": outlets,
        "rated": draft.rated,
        "rr_telecast_ids": [record.telecast.id for record, _ in draft.records],
        "rr_record_urls": [record.record_url for record, _ in draft.records],
        "duplicate_merges": max(len(draft.records) - 1, 0),
        "rr_match_confidence": rr_match_confidence,
        "s506_match_confidence": s506_match_confidence,
        "match_confidence": match_confidence,
        "s506_pointer": (
            pointer_for_listing(draft.matched_listing)
            if draft.matched_listing is not None
            else None
        ),
        "s506_week": (
            draft.matched_listing.week_label if draft.matched_listing is not None else None
        ),
        "s506_url": (
            f"https://506sports.com/ncaaf.php?yr={season}&wk={draft.matched_listing.week_label}"
            if draft.matched_listing is not None
            else None
        ),
        "kickoff_et": kickoff_et,
        "crew_matched": crew_matched,
        "crew_network_mismatch": draft.crew_network_mismatch,
        "crew_patched": False,
        "crew_source_url": None,
        "crew_source_label": None,
        "combined_feeds": _combined_feeds([record for record, _ in draft.records]),
        "plotted": False,
        "headline_claim_id": None,
        "headline_value": None,
        "headline_publisher": None,
        "headline_source_url": None,
        "measurement_type": None,
        "era_id": None,
        "rr_current_check": None,
        "model_break": None,
    }


@dataclass
class _GameDelta:
    rated_telecasts: int = 0
    rated_with_crew: int = 0
    records_with_crew: int = 0
    duplicate_merges: int = 0
    unmapped_outlets: int = 0


def _build_game_telecasts(
    *,
    game: CfbdGame,
    season: int,
    records: Sequence[tuple[RRRecord, MatchConfidence]],
    listings: Sequence[tuple[Listing506, MatchConfidence]],
    networks_table: NetworkTable,
    primary_overrides: Mapping[int, str],
    media_outlets: Sequence[str],
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, list[RRRecord]], _GameDelta]:
    delta = _GameDelta()

    main_listings = [(ln, conf) for ln, conf in listings if ln.feed_kind == "main"]
    other_listings = [(ln, conf) for ln, conf in listings if ln.feed_kind != "main"]

    listing_primaries: dict[int, PrimaryResult] = {}
    for ln, _conf in listings:
        primary = _listing_primary(ln, season, networks_table)
        delta.unmapped_outlets += len(primary.unmapped)
        listing_primaries[id(ln)] = primary

    # The (network, feed) key each main listing matches telecasts on: its own
    # primary, except that a per-game primary override replaces a main-feed
    # listing's network exactly as it does an RR record's (WR-05), so an
    # overridden game's listings (including every simulcast listing) still
    # find the rated telecast. listing_links keeps each listing's own network.
    listing_match_keys: dict[int, tuple[str | None, FeedType]] = {}
    for ln, _conf in main_listings:
        primary = listing_primaries[id(ln)]
        match_network_id = primary.network_id
        if primary.feed_type == "main" and game.id in primary_overrides:
            match_network_id = primary_overrides[game.id]
        listing_match_keys[id(ln)] = (match_network_id, primary.feed_type)

    # The first main 506 listing (page order), for the "no RR outlet maps"
    # primary-network fallback -- None when the game has no main listing at
    # all.
    main_listings_by_order = sorted(main_listings, key=lambda item: item[0].source_row_index)
    fallback_network_id = (
        listing_primaries[id(main_listings_by_order[0][0])].network_id
        if main_listings_by_order
        else None
    )

    # -- Group RR records by their effective primary network/feed --------------------------
    groups: dict[tuple[str | None, FeedType], list[tuple[RRRecord, MatchConfidence]]] = {}
    for record, confidence in records:
        primary = primary_network(record.telecast.networks, season, networks_table)
        delta.unmapped_outlets += len(primary.unmapped)
        network_id = primary.network_id
        if network_id is None:
            network_id = fallback_network_id
        if primary.feed_type == "main" and game.id in primary_overrides:
            network_id = primary_overrides[game.id]
        groups.setdefault((network_id, primary.feed_type), []).append((record, confidence))

    drafts: dict[tuple[str | None, FeedType], _TelecastDraft] = {
        key: _TelecastDraft(key=key, game=game, rated=True, records=list(group))
        for key, group in groups.items()
    }

    main_assignment: dict[int, tuple[str | None, FeedType]] = {}
    attached: set[int] = set()

    # -- Direct match: a main listing whose own primary (network AND feed)
    # equals the telecast's. Comparing the feed too keeps a network's main
    # listing (and its crew) on that network's main telecast, never its
    # alt/Spanish one (D-10). ---------------------------------------------------------------
    for key in sorted(drafts, key=lambda k: (k[0] or "", k[1])):
        draft = drafts[key]
        candidates = [
            (ln, conf)
            for ln, conf in main_listings
            if id(ln) not in attached and listing_match_keys[id(ln)] == key
        ]
        if not candidates:
            continue
        candidates.sort(key=lambda item: item[0].source_row_index)
        chosen, conf = candidates[0]
        draft.matched_listing = chosen
        draft.listing_confidence = conf
        draft.crew_network_mismatch = False
        main_assignment[id(chosen)] = key
        attached.add(id(chosen))

    # -- Fallback: exactly one still-unattached main listing on the game, only
    # ever onto a main-feed telecast (an alt/Spanish feed never borrows the
    # main listing's crew). -------------------------------------------------------------
    leftover_main = [
        (ln, conf)
        for ln, conf in main_listings
        if id(ln) not in attached and listing_primaries[id(ln)].feed_type == "main"
    ]
    needing_crew = [
        d for d in drafts.values() if d.matched_listing is None and d.feed_type == "main"
    ]
    if len(leftover_main) == 1 and needing_crew:
        needing_crew.sort(key=lambda d: (d.network_id or "", d.feed_type))
        chosen, conf = leftover_main[0]
        target = needing_crew[0]
        target.matched_listing = chosen
        target.listing_confidence = conf
        target.crew_network_mismatch = True
        main_assignment[id(chosen)] = target.key
        attached.add(id(chosen))

    # -- Any remaining main listing becomes (or joins) its own unrated telecast ------------
    remaining_main = [(ln, conf) for ln, conf in main_listings if id(ln) not in attached]
    for ln, conf in remaining_main:
        unrated_key = listing_match_keys[id(ln)]
        unrated_draft = drafts.get(unrated_key)
        if unrated_draft is None:
            unrated_draft = _TelecastDraft(key=unrated_key, game=game, rated=False)
            drafts[unrated_key] = unrated_draft
        if unrated_draft.matched_listing is None:
            unrated_draft.matched_listing = ln
            unrated_draft.listing_confidence = conf
        main_assignment[id(ln)] = unrated_key
        attached.add(id(ln))

    # -- Finalize every telecast -------------------------------------------------------------
    telecast_rows: list[dict[str, object]] = []
    telecast_by_key: dict[tuple[str | None, FeedType], str] = {}
    records_by_telecast: dict[str, list[RRRecord]] = {}

    for draft_key, draft in drafts.items():
        row = _finalize_telecast(draft, season, networks_table, media_outlets)
        telecast_id = str(row["telecast_id"])
        telecast_by_key[draft_key] = telecast_id
        telecast_rows.append(row)
        if draft.records:
            records_by_telecast[telecast_id] = [record for record, _ in draft.records]
        if draft.rated:
            delta.rated_telecasts += 1
            if row["crew_matched"]:
                delta.rated_with_crew += 1
                delta.records_with_crew += len(draft.records)
        delta.duplicate_merges += max(len(draft.records) - 1, 0)

    # -- listing_links: one row per matched listing, main or alt/spanish ------------------
    link_rows: list[dict[str, object]] = []
    for ln, _conf in main_listings:
        link_key = main_assignment.get(id(ln))
        link_telecast_id = telecast_by_key.get(link_key) if link_key is not None else None
        link_rows.append(
            _listing_link_row(ln, game.id, listing_primaries[id(ln)].network_id, link_telecast_id)
        )
    for ln, _conf in other_listings:
        primary = listing_primaries[id(ln)]
        other_telecast_id = telecast_by_key.get((primary.network_id, primary.feed_type))
        link_rows.append(_listing_link_row(ln, game.id, primary.network_id, other_telecast_id))

    return telecast_rows, link_rows, records_by_telecast, delta


def build_telecasts(
    sources: Sequence[SeasonSources],
    games: pl.DataFrame,
    resolver: TeamResolver,
    index: GameIndex,
    overrides: Mapping[tuple[str, int, str], GameOverride],
    networks: NetworkTable,
    primary_overrides: Mapping[int, str],
    media_by_game: Mapping[int, Sequence[str]],
) -> TelecastBuild:
    """Match, merge, and attach every RR record and 506 listing in `sources`
    into telecasts (JOIN-02/05/06). `games` is the already FBS-scoped,
    season-type-filtered frame from build.games: a matched game missing from
    it is out of scope. `index` covers every division's games so matching
    itself never presupposes scope.
    """
    fbs_game_ids: set[int] = set(games["game_id"].to_list())
    unresolved_counts: dict[tuple[str, str], dict[str, int]] = {}
    unmatched: list[UnmatchedRow] = []
    counts: dict[int, dict[str, int]] = {}
    all_telecast_rows: list[dict[str, object]] = []
    all_listing_link_rows: list[dict[str, object]] = []
    records_by_telecast: dict[str, list[RRRecord]] = {}

    for season_sources in sources:
        season = season_sources.season
        season_counts: dict[str, int] = dict.fromkeys(_COUNT_KEYS, 0)
        season_counts["rr_records"] = len(season_sources.rr_records)
        season_counts["rr_parse_errors"] = season_sources.rr_parse_errors
        counts[season] = season_counts

        records_by_game: dict[int, list[tuple[RRRecord, MatchConfidence]]] = {}
        for record in season_sources.rr_records:
            match = match_record_to_game(record, index, resolver, overrides)
            by_override = match.source == "override"
            for team_slug in record.telecast.teams:
                resolved = resolver.resolve("ratingsref", team_slug, season)
                track_unresolved(
                    unresolved_counts,
                    "ratingsref",
                    team_slug,
                    season,
                    resolved,
                    by_override=by_override,
                )
                if counts_as_unresolved(team_slug, resolved, by_override=by_override):
                    season_counts["unresolved_team_names"] += 1
            if match.excluded:
                season_counts["rr_excluded"] += 1
                continue
            if match.game is None:
                season_counts["rr_unmatched"] += 1
                teams = record.telecast.teams
                unmatched.append(
                    UnmatchedRow(
                        source="ratingsref",
                        season=season,
                        pointer=pointer_for_record(record),
                        date_et=record.telecast.event_date.isoformat(),
                        away_raw=teams[0] if teams else "",
                        home_raw=teams[1] if len(teams) > 1 else "",
                        network_raw=", ".join(record.telecast.networks),
                        confidence=match.confidence,
                        reason="ambiguous" if match.confidence == "ambiguous" else "none",
                    )
                )
                continue
            if match.game.id not in fbs_game_ids:
                season_counts["rr_out_of_scope"] += 1
                continue
            season_counts["rr_matched"] += 1
            records_by_game.setdefault(match.game.id, []).append((record, match.confidence))

        listings_by_game: dict[int, list[tuple[Listing506, MatchConfidence]]] = {}
        for listing in season_sources.listings:
            match = match_listing_to_game(listing, index, resolver, overrides)
            by_override = match.source == "override"
            for raw in (listing.away_raw, listing.home_raw):
                resolved = resolver.resolve("sports506", raw, season)
                track_unresolved(
                    unresolved_counts, "sports506", raw, season, resolved, by_override=by_override
                )
                if counts_as_unresolved(raw, resolved, by_override=by_override):
                    season_counts["unresolved_team_names"] += 1
            if match.excluded:
                continue
            season_counts["listings_total"] += 1
            if match.game is not None and match.confidence != "none":
                season_counts["listings_matched"] += 1
                listings_by_game.setdefault(match.game.id, []).append((listing, match.confidence))
                if match.game.id not in fbs_game_ids:
                    primary = _listing_primary(listing, season, networks)
                    all_listing_link_rows.append(
                        _listing_link_row(listing, match.game.id, primary.network_id, None)
                    )
            else:
                season_counts["listings_unmatched"] += 1
                unmatched.append(
                    UnmatchedRow(
                        source="sports506",
                        season=season,
                        pointer=pointer_for_listing(listing),
                        date_et=listing.date_et.isoformat(),
                        away_raw=listing.away_raw,
                        home_raw=listing.home_raw,
                        network_raw=listing.network_raw or "",
                        confidence=match.confidence,
                        reason="ambiguous" if match.confidence == "ambiguous" else "none",
                    )
                )

        game_ids = {gid for gid in records_by_game if gid in fbs_game_ids}
        game_ids |= {gid for gid in listings_by_game if gid in fbs_game_ids}

        for game_id in sorted(game_ids):
            game = index.by_id(game_id)
            if game is None:  # pragma: no cover - defensive: games frame implies the index has it
                continue
            telecast_rows, link_rows, telecast_records, delta = _build_game_telecasts(
                game=game,
                season=season,
                records=records_by_game.get(game_id, []),
                listings=listings_by_game.get(game_id, []),
                networks_table=networks,
                primary_overrides=primary_overrides,
                media_outlets=list(media_by_game.get(game_id, ())),
            )
            all_telecast_rows.extend(telecast_rows)
            all_listing_link_rows.extend(link_rows)
            records_by_telecast.update(telecast_records)
            season_counts["rated_telecasts"] += delta.rated_telecasts
            season_counts["rated_with_crew"] += delta.rated_with_crew
            season_counts["records_with_crew"] += delta.records_with_crew
            season_counts["records_with_506_crew"] += delta.records_with_crew
            season_counts["duplicate_merges"] += delta.duplicate_merges
            season_counts["unmapped_outlets"] += delta.unmapped_outlets

    games_by_season: dict[int, list[CfbdGame]] = {s.season: s.games for s in sources}
    unresolved_team_rows: list[UnresolvedTeamRow] = []
    for (source, raw_name), info in unresolved_counts.items():
        suggested_name, suggested_id = suggest_canonical(
            raw_name, info["season_last"], games_by_season
        )
        unresolved_team_rows.append(
            UnresolvedTeamRow(
                source=source,
                season_first=info["season_first"],
                season_last=info["season_last"],
                raw_name=raw_name,
                occurrences=info["count"],
                suggested_canonical=suggested_name or "",
                suggested_cfbd_team_id=str(suggested_id) if suggested_id is not None else "",
            )
        )
    unresolved_team_rows.sort(key=lambda row: (row.source, row.raw_name))
    unmatched.sort(key=lambda row: (row.source, row.season, row.pointer))

    telecasts_frame = pl.DataFrame(all_telecast_rows, schema=TELECASTS_SCHEMA)
    if telecasts_frame.height:
        telecasts_frame = telecasts_frame.sort("telecast_id")
        duplicate_ids = telecasts_frame.height - telecasts_frame["telecast_id"].n_unique()
        if duplicate_ids:
            # Count-only (T-03-04): a duplicate id would let one telecast's RR
            # records overwrite another's in records_by_telecast.
            raise VaultStateError(f"telecasts: {duplicate_ids} duplicate telecast_id value(s)")
    listing_links_frame = pl.DataFrame(all_listing_link_rows, schema=LISTING_LINKS_SCHEMA)
    if listing_links_frame.height:
        listing_links_frame = listing_links_frame.sort(["season", "week_label", "source_row_index"])

    return TelecastBuild(
        telecasts=telecasts_frame,
        listing_links=listing_links_frame,
        records_by_telecast=records_by_telecast,
        counts=counts,
        unmatched_rows=unmatched,
        unresolved_rows=unresolved_team_rows,
    )
