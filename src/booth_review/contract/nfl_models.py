"""The NFL site-data contract (999.5 D-07): pydantic models for every display
field the NFL views need, a parallel of `contract/models.py` on its own
versioned line.

Every model uses `extra="forbid"` so an analysis-only field (`pregame_spread`,
`coverage_share`, raw crew strings, raw win-probability series,
`raw_mean_abs_spread`) fails validation instead of silently shipping. Every
model is `strict=True` so a stringified number never coerces, and
`frozen=True` since a validated payload is a read-only snapshot.

Only regular-season games are representable (D-17): there is no `game_type`
column. There is deliberately no wall-clock `generated_at`, so identical inputs
give identical bytes. See docs/nfl-data.md for the field-by-field contract.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

NFL_SCHEMA_VERSION = "2.0.0"

NflSlotLabel = Literal[
    "Christmas",
    "Thanksgiving",
    "Black Friday",
    "International",
    "TNF",
    "SNF",
    "MNF",
    "Saturday",
    "Friday",
    "Sunday early",
    "Sunday late",
    "Other",
]

# The 999.4 slot names in display order; lookups.slots must equal this tuple.
NFL_SLOTS: tuple[str, ...] = (
    "Christmas",
    "Thanksgiving",
    "Black Friday",
    "International",
    "TNF",
    "SNF",
    "MNF",
    "Saturday",
    "Friday",
    "Sunday early",
    "Sunday late",
    "Other",
)

PersonRole = Literal["pbp", "analyst", "unknown"]

# The CFB FAMILY_COLORS keys the NFL pills use.
NflNetworkFamily = Literal["disney", "fox", "cbs", "nbc", "other"]

# (id, label, window_level) in line order; lookups.view_categories must equal this.
NFL_VIEW_CATEGORIES: tuple[tuple[str, str, bool], ...] = (
    ("agotw", "Fox AGOTW", True),
    ("cbs_national", "CBS late national", True),
    ("snf", "SNF", False),
    ("mnf", "MNF", False),
    ("tnf", "TNF", False),
    ("thanksgiving", "Thanksgiving", False),
    ("christmas", "Christmas", False),
    ("black_friday", "Black Friday", False),
    ("international", "International", False),
    ("saturday", "Saturday", False),
    ("friday", "Friday", False),
    ("other", "Other", False),
)


class NflFreshness(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    season: int
    in_progress: bool
    through_week: int | None
    viewership_through_week: int | None
    crews_default_season: int | None


class NflConstants(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    viewership_scope: Literal["window"]
    coverage_normalized: Literal[False]
    excitement_method: Literal["GEI-style"]
    low_n_threshold: int


class NflFranchiseRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: str
    name: str


class NflTeamNameRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    name: str
    short: str


class NflNetworkRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: str
    name: str
    family: NflNetworkFamily


class NflNetworkGroupRef(BaseModel):
    """A picker entry: networks that share one booth ranking (members index
    lookups.networks) and the label of the group's flagship window."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: str
    name: str
    flagship: str | None
    members: list[int]


class NflViewCategoryRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: str
    label: str
    window_level: bool


class NflPersonRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: str
    name: str


class NflEraRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: str
    label: str
    start: str | None
    end: str | None
    source_url: str


class NflLookups(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    franchises: list[NflFranchiseRef]
    team_names: list[NflTeamNameRef]
    networks: list[NflNetworkRef]
    network_groups: list[NflNetworkGroupRef]
    view_categories: list[NflViewCategoryRef]
    people: list[NflPersonRef]
    eras: list[NflEraRef]
    slots: list[NflSlotLabel]


class NflCrewEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    person: int
    role: PersonRole


class NflGameColumns(BaseModel):
    """One list per display field; index i across every list is one game."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    season: list[int]
    week: list[int]
    date: list[str]
    kickoff: list[str | None]
    home: list[int]
    away: list[int]
    home_name: list[int]
    away_name: list[int]
    home_points: list[int | None]
    away_points: list[int | None]
    final_margin: list[int | None]
    slot: list[int]
    standalone: list[bool]
    agotw: list[bool]
    cbs_national: list[bool]
    international: list[bool]
    flexed: list[bool]
    # Wikipedia-derived (CC BY-SA 4.0, D-23)
    original_slot: list[int | None]
    original_network: list[int | None]
    change_url: list[str | None]
    network: list[int | None]
    crew: list[list[NflCrewEntry]]
    crew_source: list[Literal["506", "published_lineup"] | None]
    crew_source_url: list[str | None]
    excitement: list[float | None]
    viewers: list[int | None]
    scope: list[Literal["window", "game"] | None]
    era: list[int | None]
    rr_url: list[str | None]
    source_url: list[str | None]
    cause: list[Literal["pending", "regional", "none"] | None]


class NflSpecialColumns(BaseModel):
    """One row per franchise-season; counts are exclusive per bar (D-24)."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    franchise: list[int]
    season: list[int]
    games: list[int]
    standalone_total: list[int]
    standalone_christmas: list[int]
    standalone_thanksgiving: list[int]
    standalone_black_friday: list[int]
    standalone_international: list[int]
    standalone_tnf: list[int]
    standalone_snf: list[int]
    standalone_mnf: list[int]
    standalone_saturday: list[int]
    standalone_friday: list[int]
    standalone_sunday_early: list[int]
    standalone_sunday_late: list[int]
    standalone_other: list[int]
    solo_thursday: list[int]
    solo_sunday: list[int]
    solo_monday: list[int]
    solo_holiday: list[int]
    solo_other: list[int]
    agotw: list[int]
    cbs_national: list[int]
    international: list[int]
    international_other: list[int]
    flexed: list[int]
    special: list[int]
    agotw_rate: list[float | None]
    cbs_national_rate: list[float | None]


class NflSeasonWeekColumns(BaseModel):
    """Per-season doubleheader and ambiguous week counts (D-13): the client
    computes a rate's denominator and shows n/a at zero."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    season: list[int]
    fox_doubleheader_weeks: list[int]
    fox_ambiguous_weeks: list[int]
    cbs_doubleheader_weeks: list[int]
    cbs_ambiguous_weeks: list[int]


class NflBoothColumns(BaseModel):
    """Booth rows, one per season, network group and booth, never pooled across
    seasons. Win-probability swing stays in the vault table and is not shipped."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    season: list[int]
    network_group: list[int]
    rank: list[int]
    rank_source: list[Literal["published", "override", "inferred"]]
    is_lead: list[bool]
    pbp_person: list[int]
    analyst_person: list[int | None]
    games: list[int]
    flagship_games: list[int]
    fill_in_games: list[int]
    lineup_games: list[int]
    raw_n_margin: list[int]
    raw_n_excitement: list[int]
    raw_n_viewers: list[int]
    raw_mean_abs_margin: list[float | None]
    raw_mean_excitement: list[float | None]
    raw_mean_viewers: list[float | None]
    adj_n_margin: list[int]
    adj_n_excitement: list[int]
    adj_margin_resid: list[float | None]
    adj_margin_se: list[float | None]
    adj_excitement_resid: list[float | None]
    adj_excitement_se: list[float | None]
    low_n: list[bool]
    game_list: list[list[int]]


class NflViewershipColumns(BaseModel):
    """Viewership rows per special-game category and season."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    category: list[int]
    season: list[int]
    era: list[int]
    games: list[int]
    mean_viewers: list[float | None]
    viewership_resid: list[float | None]
    viewership_se: list[float | None]
    low_n: list[bool]
    game_list: list[list[int]]


# The 12 standalone_ columns of the special block, in slot order.
_STANDALONE_COLUMNS: tuple[str, ...] = (
    "standalone_christmas",
    "standalone_thanksgiving",
    "standalone_black_friday",
    "standalone_international",
    "standalone_tnf",
    "standalone_snf",
    "standalone_mnf",
    "standalone_saturday",
    "standalone_friday",
    "standalone_sunday_early",
    "standalone_sunday_late",
    "standalone_other",
)

_SOLO_COLUMNS: tuple[str, ...] = (
    "solo_thursday",
    "solo_sunday",
    "solo_monday",
    "solo_holiday",
    "solo_other",
)
_SOLO_OTHER_PARTS: tuple[str, ...] = (
    "standalone_saturday",
    "standalone_international",
    "standalone_friday",
    "standalone_sunday_early",
    "standalone_sunday_late",
    "standalone_other",
)


def _check_lengths(block: str, cols: BaseModel, anchor: str) -> int:
    """Every column shares the anchor column's length; messages name columns only."""
    n = len(getattr(cols, anchor))
    for name in type(cols).model_fields:
        if len(getattr(cols, name)) != n:
            raise ValueError(
                f"{block}.{name}: length {len(getattr(cols, name))} does not match "
                f"{block}.{anchor} length {n}"
            )
    return n


def _check_finite(block: str, cols: BaseModel) -> None:
    """Every float cell is finite (WR-04): NaN and Infinity are not valid JSON,
    so one such cell would make the browser reject the whole file. Messages
    name `block.column[position]` only."""
    for name in type(cols).model_fields:
        for i, value in enumerate(getattr(cols, name)):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"{block}.{name}[{i}]: must be finite")


def _check_index(block: str, column: str, i: int, value: int | None, size: int) -> None:
    if value is not None and not 0 <= value < size:
        raise ValueError(f"{block}.{column}[{i}]: index out of range")


def _check_game_list(block: str, i: int, game_list: Sequence[int], num_games: int) -> None:
    for j, g in enumerate(game_list):
        if not 0 <= g < num_games:
            raise ValueError(f"{block}.game_list[{i}][{j}]: game index out of range")


class NflSiteData(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["2.0.0"]
    freshness: NflFreshness
    constants: NflConstants
    lookups: NflLookups
    games: NflGameColumns
    special: NflSpecialColumns
    season_weeks: NflSeasonWeekColumns
    booths: NflBoothColumns
    viewership: NflViewershipColumns

    @model_validator(mode="after")
    def _check_alignment_and_indexes(self) -> NflSiteData:
        """Aligned column lengths, in-range lookup indexes and the invariants.

        Error messages name `block.column[position]` only, never cell content,
        so a failing real build never echoes vault rows into logs.
        """
        if tuple(self.lookups.slots) != NFL_SLOTS:
            raise ValueError("lookups.slots: must equal the NFL slot names in order")
        for block in ("games", "special", "booths", "viewership"):
            _check_finite(block, getattr(self, block))
        self._check_lookups()
        referenced_people: set[int] = set()
        referenced_networks: set[int] = set()
        n_games = self._check_games(referenced_people, referenced_networks)
        self._check_special()
        self._check_season_weeks()
        self._check_booths(n_games, referenced_people)
        self._check_viewership(n_games)
        for k in range(len(self.lookups.people)):
            if k not in referenced_people:
                raise ValueError(f"lookups.people[{k}]: not referenced by anything")
        for k in range(len(self.lookups.networks)):
            if k not in referenced_networks:
                raise ValueError(f"lookups.networks[{k}]: not referenced by any game")
        return self

    def _check_lookups(self) -> None:
        lk = self.lookups
        if [(c.id, c.label, c.window_level) for c in lk.view_categories] != list(
            NFL_VIEW_CATEGORIES
        ):
            raise ValueError("lookups.view_categories: must equal the NFL view categories in order")
        seen_ids: set[str] = set()
        owner: dict[int, int] = {}
        for gi, grp in enumerate(lk.network_groups):
            if grp.id in seen_ids:
                raise ValueError(f"lookups.network_groups[{gi}].id: duplicate")
            seen_ids.add(grp.id)
            if not grp.members:
                raise ValueError(f"lookups.network_groups[{gi}].members: empty")
            for j, m in enumerate(grp.members):
                if not 0 <= m < len(lk.networks):
                    raise ValueError(f"lookups.network_groups[{gi}].members[{j}]: out of range")
                if m in owner:
                    raise ValueError(
                        f"lookups.network_groups[{gi}].members[{j}]: network is in two groups"
                    )
                owner[m] = gi
        for k in range(len(lk.networks)):
            if k not in owner:
                raise ValueError(f"lookups.networks[{k}]: not in any network group")

    def _check_games(self, referenced_people: set[int], referenced_networks: set[int]) -> int:
        g = self.games
        lk = self.lookups
        n = _check_lengths("games", g, "season")
        for i in range(n):
            _check_index("games", "home", i, g.home[i], len(lk.franchises))
            _check_index("games", "away", i, g.away[i], len(lk.franchises))
            _check_index("games", "home_name", i, g.home_name[i], len(lk.team_names))
            _check_index("games", "away_name", i, g.away_name[i], len(lk.team_names))
            _check_index("games", "slot", i, g.slot[i], len(lk.slots))
            _check_index("games", "original_slot", i, g.original_slot[i], len(lk.slots))
            _check_index("games", "original_network", i, g.original_network[i], len(lk.networks))
            _check_index("games", "network", i, g.network[i], len(lk.networks))
            _check_index("games", "era", i, g.era[i], len(lk.eras))
            for col in (g.network[i], g.original_network[i]):
                if col is not None:
                    referenced_networks.add(col)
            for j, entry in enumerate(g.crew[i]):
                if not 0 <= entry.person < len(lk.people):
                    raise ValueError(f"games.crew[{i}][{j}].person: index out of range")
                referenced_people.add(entry.person)
            self._check_crew_source(i)
            self._check_points(i)
            self._check_rating(i)
        return n

    def _check_crew_source(self, i: int) -> None:
        g = self.games
        source, url, crew = g.crew_source[i], g.crew_source_url[i], g.crew[i]
        if source is None and crew:
            raise ValueError(f"games.crew_source[{i}]: required when the game has a crew")
        if source == "published_lineup":
            if not any(e.role == "pbp" for e in crew):
                raise ValueError(f"games.crew_source[{i}]: published_lineup needs a pbp entry")
            if url is None or not url.startswith("https://"):
                raise ValueError(f"games.crew_source_url[{i}]: must be an https citation")
        elif url is not None:
            raise ValueError(f"games.crew_source_url[{i}]: only for published_lineup games")

    def _check_points(self, i: int) -> None:
        g = self.games
        home, away, margin = g.home_points[i], g.away_points[i], g.final_margin[i]
        if (home is None) != (away is None):
            raise ValueError(f"games.away_points[{i}]: must be set together with home_points")
        if home is None or away is None:
            if margin is not None:
                raise ValueError(f"games.final_margin[{i}]: set without points")
        elif margin != home - away:
            raise ValueError(f"games.final_margin[{i}]: does not equal home minus away points")

    def _check_rating(self, i: int) -> None:
        g = self.games
        viewers, cause = g.viewers[i], g.cause[i]
        if viewers is None:
            if cause is None:
                raise ValueError(f"games.cause[{i}]: required when viewers is null")
            if g.scope[i] is not None:
                raise ValueError(f"games.scope[{i}]: set on an unrated game")
            if g.era[i] is not None:
                raise ValueError(f"games.era[{i}]: set on an unrated game")
        else:
            if viewers <= 0:
                raise ValueError(f"games.viewers[{i}]: must be > 0")
            if cause is not None:
                raise ValueError(f"games.cause[{i}]: set on a rated game")

    def _check_special(self) -> None:
        s = self.special
        n = _check_lengths("special", s, "season")
        for i in range(n):
            _check_index("special", "franchise", i, s.franchise[i], len(self.lookups.franchises))
            standalone_sum = sum(getattr(s, name)[i] for name in _STANDALONE_COLUMNS)
            if s.standalone_total[i] != standalone_sum:
                raise ValueError(
                    f"special.standalone_total[{i}]: does not equal the sum of the standalone slots"
                )
            self._check_solo(i)
            if s.special[i] != s.standalone_total[i] + s.agotw[i] + s.cbs_national[i]:
                raise ValueError(
                    f"special.special[{i}]: does not equal standalone_total + agotw + cbs_national"
                )
            if s.international_other[i] > s.international[i]:
                raise ValueError(f"special.international_other[{i}]: exceeds international")

    def _check_solo(self, i: int) -> None:
        s = self.special
        expected = {
            "solo_thursday": s.standalone_tnf[i],
            "solo_sunday": s.standalone_snf[i],
            "solo_monday": s.standalone_mnf[i],
            "solo_holiday": (
                s.standalone_christmas[i]
                + s.standalone_thanksgiving[i]
                + s.standalone_black_friday[i]
            ),
            "solo_other": sum(getattr(s, name)[i] for name in _SOLO_OTHER_PARTS),
        }
        for name, want in expected.items():
            if getattr(s, name)[i] != want:
                raise ValueError(f"special.{name}[{i}]: does not match its standalone slots")
        if sum(getattr(s, name)[i] for name in _SOLO_COLUMNS) != s.standalone_total[i]:
            raise ValueError(
                f"special.solo_other[{i}]: solo columns do not sum to standalone_total"
            )

    def _check_season_weeks(self) -> None:
        w = self.season_weeks
        n = _check_lengths("season_weeks", w, "season")
        for i in range(n):
            if w.fox_ambiguous_weeks[i] > w.fox_doubleheader_weeks[i]:
                raise ValueError(f"season_weeks.fox_ambiguous_weeks[{i}]: exceeds doubleheader")
            if w.cbs_ambiguous_weeks[i] > w.cbs_doubleheader_weeks[i]:
                raise ValueError(f"season_weeks.cbs_ambiguous_weeks[{i}]: exceeds doubleheader")

    def _check_booths(self, num_games: int, referenced_people: set[int]) -> None:
        b = self.booths
        n = _check_lengths("booths", b, "season")
        num_people = len(self.lookups.people)
        groups = self.lookups.network_groups
        by_key: dict[tuple[int, int], list[int]] = {}
        for i in range(n):
            _check_index("booths", "network_group", i, b.network_group[i], len(groups))
            for col in ("pbp_person", "analyst_person"):
                value = getattr(b, col)[i]
                _check_index("booths", col, i, value, num_people)
                if value is not None:
                    referenced_people.add(value)
            _check_game_list("booths", i, b.game_list[i], num_games)
            if len(b.game_list[i]) != b.games[i]:
                raise ValueError(f"booths.game_list[{i}]: length does not equal games")
            for col in ("flagship_games", "fill_in_games", "lineup_games"):
                if getattr(b, col)[i] > b.games[i]:
                    raise ValueError(f"booths.{col}[{i}]: exceeds games")
            in_range = 0 <= b.network_group[i] < len(groups)
            if in_range and groups[b.network_group[i]].flagship is None and b.flagship_games[i] > 0:
                raise ValueError(f"booths.flagship_games[{i}]: the group has no flagship")
            by_key.setdefault((b.season[i], b.network_group[i]), []).append(i)
        for rows in by_key.values():
            ranks = sorted(b.rank[i] for i in rows)
            if ranks != list(range(1, len(rows) + 1)):
                raise ValueError(f"booths.rank[{rows[0]}]: ranks must be exactly 1..n")
            leads = [i for i in rows if b.is_lead[i]]
            if len(leads) != 1 or b.rank[leads[0]] != 1:
                raise ValueError(f"booths.is_lead[{rows[0]}]: exactly one lead, at rank 1")
            if len({b.rank_source[i] for i in rows}) != 1:
                raise ValueError(f"booths.rank_source[{rows[0]}]: mixed sources in one group")

    def _check_viewership(self, num_games: int) -> None:
        v = self.viewership
        n = _check_lengths("viewership", v, "season")
        seen: set[tuple[int, int]] = set()
        for i in range(n):
            _check_index(
                "viewership", "category", i, v.category[i], len(self.lookups.view_categories)
            )
            _check_index("viewership", "era", i, v.era[i], len(self.lookups.eras))
            _check_game_list("viewership", i, v.game_list[i], num_games)
            if (v.category[i], v.season[i]) in seen:
                raise ValueError(
                    f"viewership.category[{i}]: second row for one category and season"
                )
            seen.add((v.category[i], v.season[i]))
            if v.games[i] < 1:
                raise ValueError(f"viewership.games[{i}]: must be >= 1")
            if len(v.game_list[i]) != v.games[i]:
                raise ValueError(f"viewership.game_list[{i}]: length does not equal games")


def validate_nfl_site_data(obj: object) -> NflSiteData:
    """Validate `obj` (a parsed nfl-data.json body) against the contract."""
    return NflSiteData.model_validate(obj)


# The display-field allowlist for the games block.
NFL_GAME_FIELDS: tuple[str, ...] = tuple(NflGameColumns.model_fields)
