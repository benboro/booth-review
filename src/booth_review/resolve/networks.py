"""Network layer for JOIN-06: outlet-string -> network resolution, and the
rights-holder primary-network rule.

Rights holder = the highest-precedence outlet among a telecast's main-feed
outlets, by tier (broadcast > cable > conference > regional > streaming >
other); a same-tier tie breaks on each network's `priority` column (lowest
number wins), then on network_id, so the result never depends on which
outlet a source happened to list first. Precedence and every outlet string
this project has observed live in data/reference/networks.csv; nothing is
hardcoded by brand name here (AGENTS.md's crosswalk-only rule, and the
research anti-pattern against hardcoding streaming-brand strings such as
ESPN+/Peacock/Paramount+): a newly observed outlet string that doesn't map
yet is a network_diagnose.py review-file entry, never a code change or a
guess.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from booth_review.errors import ReferenceTableError
from booth_review.reference import read_reference_csv_numbered

NETWORK_COLUMNS = (
    "variant",
    "network_id",
    "display_name",
    "family",
    "tier",
    "feed_type",
    "season_from",
    "season_to",
    "priority",
)

PRIMARY_OVERRIDE_COLUMNS = ("cfbd_game_id", "network_id", "reason")

Tier = Literal["broadcast", "cable", "conference", "regional", "streaming", "other"]
FeedType = Literal["main", "alt", "spanish"]

# Rights-holder precedence, lowest rank wins. The whole point of this table
# (not per-network code) is that a newly observed network only needs a row
# here, at whichever tier the reviewed table says it belongs.
TIER_RANK: dict[Tier, int] = {
    "broadcast": 0,
    "cable": 1,
    "conference": 2,
    "regional": 3,
    "streaming": 4,
    "other": 5,
}

# Same-tier tie-break, lowest priority number wins; a network with no
# priority in the table sorts after every network that has one (this
# sentinel), then ties among priority-less networks break on network_id
# (stable, alphabetical) so the result never depends on outlet listing
# order. A priority lives on the network_id (one value for every variant
# row of that id, checked by load_networks the same way display_name,
# family, and tier are), not on any one outlet string, so it stays a table
# fact rather than per-network code.
_DEFAULT_PRIORITY = 1_000_000
# Tie-break for one network listed as both an alt and a Spanish feed.
_FEED_RANK: dict[str, int] = {"main": 0, "alt": 1, "spanish": 2}

_OVERRIDE_REASONS: frozenset[str] = frozenset(
    {"rights-holder", "simulcast", "neutral-site", "other"}
)

_TIERS: frozenset[str] = frozenset(TIER_RANK)
_FEED_TYPES: frozenset[str] = frozenset({"main", "alt", "spanish"})
_NETWORK_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# ",", "/", ";", or " | " (any whitespace around a separator is collapsed
# away by the whitespace-collapse pass below, so the literal spaces around
# "|" don't need their own branch in the regex).
_SEPARATOR_RE = re.compile(r"[,/;|]")

# 506's non-network status text for a game with no telecast at all: a bare
# "CANCELLED"/"POSTPONED" (optionally followed by a rescheduled date, which
# may itself contain a "/" -- "POSTPONED TO 12/1" is never a network string
# split into "POSTPONED TO 12" and "1", it is one placeholder), or a bare
# "PPV" with no identifiable network attached. Checked against the whole
# outlet text before splitting (so an embedded date's "/" is never treated
# as a network separator), and again against each split-off part as a
# defensive second pass. Format detection on the placeholder's own text, not
# a per-network brand list.
_PLACEHOLDER_RE = re.compile(r"^(cancelled|postponed.*|ppv)$", re.IGNORECASE)


def _is_placeholder(text: str) -> bool:
    return bool(_PLACEHOLDER_RE.match(text))


# The same generic feed markers sports506.parser._classify_feed checks
# (restated here rather than imported, since this module reads outlet text
# from three sources, not just 506's network cell); a marker is read from a
# trailing parenthesized suffix rather than a substring search, since this
# function must also return the base outlet name with the marker removed.
_ALT_MARKERS = ("alt-cast", "alt")
_SPANISH_MARKER = "spanish"
_TRAILING_PAREN_RE = re.compile(r"\s*\(([^()]*)\)\s*$")

_NEG_INF = float("-inf")
_POS_INF = float("inf")


def _collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def split_outlets(text: str) -> list[str]:
    """Split a raw outlet string on ",", "/", ";", or "|" (a " | " separator
    included); empty parts dropped, each remaining part whitespace-collapsed.
    A lone "-" part is dropped too -- 506's own convention for "no network
    listed" (e.g. a postponed or otherwise untelevised game), never a real
    outlet name, and structurally equivalent to the already-dropped empty
    part. A whole-text status placeholder ("CANCELLED", "POSTPONED", a
    "POSTPONED TO <date>" with its own embedded "/", or a bare "PPV") is
    dropped the same way, checked before any splitting so a rescheduled
    date's "/" is never mistaken for an outlet separator; the same check
    also applies to each already-split part, in case a placeholder appears
    alongside a real outlet.
    """
    collapsed_whole = _collapse_whitespace(text)
    if not collapsed_whole or collapsed_whole == "-" or _is_placeholder(collapsed_whole):
        return []
    parts = _SEPARATOR_RE.split(text)
    return [
        collapsed
        for part in parts
        if (collapsed := _collapse_whitespace(part))
        and collapsed != "-"
        and not _is_placeholder(collapsed)
    ]


def strip_feed_marker(text: str) -> tuple[str, FeedType | None]:
    """Split a trailing parenthesized alt-cast or Spanish marker off `text`,
    e.g. "Net2 (alt-cast)" gives ("Net2", "alt"), "Net (alt)" gives ("Net",
    "alt"), and "Net2 (Spanish)" gives ("Net2", "spanish"). A name with no
    recognized marker -- including a plain "Net Deportes"-style outlet name,
    whose Spanish feed type comes from the network table row, not a marker
    -- is returned unchanged with `None`.
    """
    match = _TRAILING_PAREN_RE.search(text)
    if match is None:
        return _collapse_whitespace(text), None
    marker = match.group(1).strip().lower()
    if marker in _ALT_MARKERS:
        return _collapse_whitespace(text[: match.start()]), "alt"
    if marker == _SPANISH_MARKER:
        return _collapse_whitespace(text[: match.start()]), "spanish"
    return _collapse_whitespace(text), None


def _parse_optional_int(value: str, *, path_name: str, line_no: int, field: str) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise ReferenceTableError(
            f"{path_name}: line {line_no}: invalid {field} {value!r}"
        ) from None


def _ranges_overlap(
    a_from: int | None, a_to: int | None, b_from: int | None, b_to: int | None
) -> bool:
    lo = max(a_from if a_from is not None else _NEG_INF, b_from if b_from is not None else _NEG_INF)
    hi = min(a_to if a_to is not None else _POS_INF, b_to if b_to is not None else _POS_INF)
    return lo <= hi


@dataclass(frozen=True)
class NetworkRow:
    variant: str
    network_id: str
    display_name: str
    family: str
    tier: Tier
    feed_type: FeedType
    season_from: int | None
    season_to: int | None
    priority: int | None


class NetworkTable:
    """Outlet-string -> network resolution, built from data/reference/
    networks.csv (or a fixture with the same shape)."""

    def __init__(self, rows: Sequence[NetworkRow]) -> None:
        self._rows = tuple(rows)
        self._by_variant_key: dict[str, list[NetworkRow]] = {}
        self._networks: dict[str, tuple[str, str, Tier]] = {}
        for row in self._rows:
            key = _collapse_whitespace(row.variant).lower()
            self._by_variant_key.setdefault(key, []).append(row)
            self._networks[row.network_id] = (row.display_name, row.family, row.tier)

    def lookup(self, outlet: str, season: int) -> NetworkRow | None:
        """The row whose variant matches `outlet` case-insensitively (after
        whitespace collapse) and whose season range covers `season`; None
        when no row matches -- an unmapped outlet is never a guess."""
        key = _collapse_whitespace(outlet).lower()
        for row in self._by_variant_key.get(key, ()):
            if (row.season_from is None or season >= row.season_from) and (
                row.season_to is None or season <= row.season_to
            ):
                return row
        return None

    def networks(self) -> dict[str, tuple[str, str, Tier]]:
        """network_id -> (display_name, family, tier) for every distinct
        network_id in the table."""
        return dict(self._networks)


def load_networks(reference_dir: Path, *, required: bool = False) -> NetworkTable:
    """Read networks.csv. Not required by default, so tests (and any code
    exercised before the real table is populated) get an empty table rather
    than a crash. Raises ReferenceTableError (naming the file and line) on:
    an invalid tier or feed_type, a network_id outside the shared slug
    convention (^[a-z0-9]+(-[a-z0-9]+)*$), the same (variant, season) range
    mapped to two different network ids, or one network_id carrying two
    different display names, families, tiers, or priorities across its rows.
    A blank priority is None (the default same-tier tie-break rank in
    primary_network); a non-blank priority must parse as an integer.
    """
    path = reference_dir / "networks.csv"
    raw_rows = read_reference_csv_numbered(path, NETWORK_COLUMNS, required=required)

    rows: list[NetworkRow] = []
    variant_ranges: dict[str, list[tuple[int | None, int | None, str]]] = {}
    network_identity: dict[str, tuple[str, str, Tier, int | None]] = {}

    for line_no, raw in raw_rows:
        network_id = raw["network_id"]
        if not _NETWORK_ID_RE.match(network_id):
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: invalid network_id {network_id!r}"
            )

        tier_raw = raw["tier"]
        if tier_raw not in _TIERS:
            raise ReferenceTableError(f"{path.name}: line {line_no}: invalid tier {tier_raw!r}")
        tier = cast(Tier, tier_raw)

        feed_type_raw = raw["feed_type"]
        if feed_type_raw not in _FEED_TYPES:
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: invalid feed_type {feed_type_raw!r}"
            )
        feed_type = cast(FeedType, feed_type_raw)

        season_from = _parse_optional_int(
            raw["season_from"], path_name=path.name, line_no=line_no, field="season_from"
        )
        season_to = _parse_optional_int(
            raw["season_to"], path_name=path.name, line_no=line_no, field="season_to"
        )
        priority = _parse_optional_int(
            raw["priority"], path_name=path.name, line_no=line_no, field="priority"
        )

        display_name = raw["display_name"]
        family = raw["family"]

        identity = network_identity.get(network_id)
        if identity is None:
            network_identity[network_id] = (display_name, family, tier, priority)
        elif identity != (display_name, family, tier, priority):
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: network_id {network_id!r} already has a "
                "different display_name, family, tier, or priority on an earlier row"
            )

        variant_key = _collapse_whitespace(raw["variant"]).lower()
        for other_from, other_to, other_id in variant_ranges.get(variant_key, ()):
            if other_id != network_id and _ranges_overlap(
                season_from, season_to, other_from, other_to
            ):
                raise ReferenceTableError(
                    f"{path.name}: line {line_no}: variant {raw['variant']!r} maps to two "
                    "different network ids in an overlapping season range"
                )
        variant_ranges.setdefault(variant_key, []).append((season_from, season_to, network_id))

        rows.append(
            NetworkRow(
                variant=raw["variant"],
                network_id=network_id,
                display_name=display_name,
                family=family,
                tier=tier,
                feed_type=feed_type,
                season_from=season_from,
                season_to=season_to,
                priority=priority,
            )
        )
    return NetworkTable(rows)


@dataclass(frozen=True)
class PrimaryResult:
    network_id: str | None
    outlets: tuple[str, ...]
    unmapped: tuple[str, ...]
    feed_type: FeedType


def primary_network(outlet_texts: Sequence[str], season: int, table: NetworkTable) -> PrimaryResult:
    """Pick the rights-holder network from a telecast's raw outlet text(s).

    Every text is split (split_outlets) and each part's feed marker stripped
    (strip_feed_marker) before lookup. Among the outlets that map to a known
    network, the main-feed outlet with the lowest TIER_RANK wins; a tie
    within the same tier breaks on the tied networks' `priority` column
    (lowest number wins), then on network_id, so the choice is the same
    regardless of which outlet a source listed first. Alt/Spanish-feed
    outlets are skipped for this choice unless every mapped outlet is alt or
    Spanish, in which case the same tier/priority/network_id order picks
    among those (then alt before Spanish for one network listed both ways)
    and `feed_type` carries the winner's feed. Unmapped strings are returned separately
    (a network_diagnose.py review candidate), never guessed at; `network_id`
    is None only when nothing mapped at all.
    """
    mapped: list[tuple[str, NetworkRow, FeedType]] = []
    unmapped: list[str] = []
    seen_ids: dict[str, None] = {}

    for text in outlet_texts:
        for outlet in split_outlets(text):
            base, marker_feed = strip_feed_marker(outlet)
            row = table.lookup(base, season)
            if row is None:
                unmapped.append(outlet)
                continue
            feed = marker_feed if marker_feed is not None else row.feed_type
            mapped.append((row.network_id, row, feed))
            seen_ids.setdefault(row.network_id, None)

    outlet_ids = tuple(seen_ids)

    if not mapped:
        return PrimaryResult(
            network_id=None, outlets=outlet_ids, unmapped=tuple(unmapped), feed_type="main"
        )

    def _pick_key(item: tuple[str, NetworkRow, FeedType]) -> tuple[int, int, str, int]:
        return (
            TIER_RANK[item[1].tier],
            item[1].priority if item[1].priority is not None else _DEFAULT_PRIORITY,
            item[1].network_id,
            _FEED_RANK[item[2]],
        )

    main_candidates = [item for item in mapped if item[2] == "main"]
    if main_candidates:
        best_id, _best_row, _ = min(main_candidates, key=_pick_key)
        return PrimaryResult(
            network_id=best_id, outlets=outlet_ids, unmapped=tuple(unmapped), feed_type="main"
        )

    # Every mapped outlet is alt or Spanish: the same order-independent pick,
    # carrying the winner's own feed (WR-04).
    alt_id, _alt_row, alt_feed = min(mapped, key=_pick_key)
    return PrimaryResult(
        network_id=alt_id, outlets=outlet_ids, unmapped=tuple(unmapped), feed_type=alt_feed
    )


def load_primary_overrides(reference_dir: Path) -> dict[int, str]:
    """Read primary_network_overrides.csv (not required): cfbd_game_id ->
    the network_id that forces the primary network for that one game (D-06:
    pointer-only, a fixed-vocabulary reason code, never crew/figure text).
    Raises ReferenceTableError on a reason outside {rights-holder,
    simulcast, neutral-site, other}, a network_id outside the shared slug
    convention, or a duplicate cfbd_game_id. Whether each network_id exists
    in networks.csv is checked by `check_primary_overrides`.
    """
    path = reference_dir / "primary_network_overrides.csv"
    raw_rows = read_reference_csv_numbered(path, PRIMARY_OVERRIDE_COLUMNS, required=False)

    overrides: dict[int, str] = {}
    for line_no, raw in raw_rows:
        reason = raw["reason"]
        if reason not in _OVERRIDE_REASONS:
            raise ReferenceTableError(f"{path.name}: line {line_no}: invalid reason {reason!r}")
        try:
            game_id = int(raw["cfbd_game_id"])
        except ValueError:
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: invalid cfbd_game_id {raw['cfbd_game_id']!r}"
            ) from None
        if game_id in overrides:
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: duplicate cfbd_game_id {game_id}"
            )
        network_id = raw["network_id"]
        if not _NETWORK_ID_RE.match(network_id):
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: invalid network_id {network_id!r}"
            )
        overrides[game_id] = network_id
    return overrides


def check_primary_overrides(overrides: Mapping[int, str], table: NetworkTable) -> None:
    """Raise ReferenceTableError when a primary override names a network_id
    networks.csv doesn't define (a typo would otherwise give telecasts a
    network with no display name or family).
    """
    unknown = sorted(set(overrides.values()) - set(table.networks()))
    if unknown:
        raise ReferenceTableError(
            f"primary_network_overrides.csv: {len(unknown)} network_id(s) not in "
            "networks.csv: " + ", ".join(unknown)
        )


NETWORK_RARITY_COLUMNS = ("network_id", "rarely_rated")


def load_network_rarity(reference_dir: Path) -> dict[str, bool]:
    """Read network_rarity.csv (required): network_id -> whether that network's
    games are rarely publicly rated. Hand-set per D-11 (04.13), never computed
    from a threshold; it drives the "rarely rated network" no-rating cause.
    Raises ReferenceTableError on an id outside the slug convention, a value
    other than exactly "true" or "false", or a duplicate network_id. Coverage
    against networks.csv is checked by `check_network_rarity`.
    """
    path = reference_dir / "network_rarity.csv"
    raw_rows = read_reference_csv_numbered(path, NETWORK_RARITY_COLUMNS, required=True)

    rarity: dict[str, bool] = {}
    for line_no, raw in raw_rows:
        network_id = raw["network_id"]
        if not _NETWORK_ID_RE.match(network_id):
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: invalid network_id {network_id!r}"
            )
        value = raw["rarely_rated"]
        if value not in ("true", "false"):
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: rarely_rated must be true or false"
            )
        if network_id in rarity:
            raise ReferenceTableError(
                f"{path.name}: line {line_no}: duplicate network_id {network_id!r}"
            )
        rarity[network_id] = value == "true"
    return rarity


def check_network_rarity(rarity: Mapping[str, bool], table: NetworkTable) -> None:
    """Raise ReferenceTableError when network_rarity.csv names a network_id
    networks.csv doesn't define, or leaves a networks.csv network_id without a
    row (so a newly mapped network forces a review).
    """
    known = set(table.networks())
    unknown = sorted(set(rarity) - known)
    if unknown:
        raise ReferenceTableError(
            f"network_rarity.csv: {len(unknown)} network_id(s) not in networks.csv: "
            + ", ".join(unknown)
        )
    missing = sorted(known - set(rarity))
    if missing:
        raise ReferenceTableError(
            f"network_rarity.csv: {len(missing)} networks.csv network_id(s) have no row: "
            + ", ".join(missing)
        )
