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

NFL_SCHEMA_VERSION = "1.0.0"

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


class NflFreshness(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    season: int
    in_progress: bool
    through_week: int | None
    viewership_through_week: int | None
    fox_default_season: int | None


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
    """Fox booth rows, one per season and booth, never pooled across seasons."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    season: list[int]
    group: list[Literal["lead", "other", "others_pooled"]]
    rank: list[int | None]
    pbp_person: list[int | None]
    analyst_person: list[int | None]
    games: list[int]
    fill_in_games: list[int]
    raw_n_margin: list[int]
    raw_n_excitement: list[int]
    raw_n_volatility: list[int]
    raw_mean_abs_margin: list[float | None]
    raw_mean_excitement: list[float | None]
    raw_mean_volatility: list[float | None]
    adj_n_margin: list[int]
    adj_n_excitement: list[int]
    adj_n_volatility: list[int]
    adj_margin_resid: list[float | None]
    adj_margin_se: list[float | None]
    adj_excitement_resid: list[float | None]
    adj_excitement_se: list[float | None]
    adj_volatility_resid: list[float | None]
    adj_volatility_se: list[float | None]
    low_n: list[bool]
    game_list: list[list[int]]


class NflAgotwColumns(BaseModel):
    """AGOTW viewership rows per season and Nielsen era."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    season: list[int]
    era: list[int]
    group: list[Literal["lead", "other"] | None]
    pbp_person: list[int | None]
    analyst_person: list[int | None]
    games: list[int]
    fill_in_games: list[int]
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

    schema_version: Literal["1.0.0"]
    freshness: NflFreshness
    constants: NflConstants
    lookups: NflLookups
    games: NflGameColumns
    special: NflSpecialColumns
    season_weeks: NflSeasonWeekColumns
    fox_booths: NflBoothColumns
    agotw_viewership: NflAgotwColumns

    @model_validator(mode="after")
    def _check_alignment_and_indexes(self) -> NflSiteData:
        """Aligned column lengths, in-range lookup indexes and the invariants.

        Error messages name `block.column[position]` only, never cell content,
        so a failing real build never echoes vault rows into logs.
        """
        if tuple(self.lookups.slots) != NFL_SLOTS:
            raise ValueError("lookups.slots: must equal the NFL slot names in order")
        for block in ("games", "special", "fox_booths", "agotw_viewership"):
            _check_finite(block, getattr(self, block))
        referenced_people: set[int] = set()
        referenced_networks: set[int] = set()
        n_games = self._check_games(referenced_people, referenced_networks)
        self._check_special()
        self._check_season_weeks()
        self._check_booths(n_games, referenced_people)
        self._check_agotw(n_games, referenced_people)
        for k in range(len(self.lookups.people)):
            if k not in referenced_people:
                raise ValueError(f"lookups.people[{k}]: not referenced by anything")
        for k in range(len(self.lookups.networks)):
            if k not in referenced_networks:
                raise ValueError(f"lookups.networks[{k}]: not referenced by any game")
        return self

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
            self._check_points(i)
            self._check_rating(i)
        return n

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
            if s.special[i] != s.standalone_total[i] + s.agotw[i] + s.cbs_national[i]:
                raise ValueError(
                    f"special.special[{i}]: does not equal standalone_total + agotw + cbs_national"
                )
            if s.international_other[i] > s.international[i]:
                raise ValueError(f"special.international_other[{i}]: exceeds international")

    def _check_season_weeks(self) -> None:
        w = self.season_weeks
        n = _check_lengths("season_weeks", w, "season")
        for i in range(n):
            if w.fox_ambiguous_weeks[i] > w.fox_doubleheader_weeks[i]:
                raise ValueError(f"season_weeks.fox_ambiguous_weeks[{i}]: exceeds doubleheader")
            if w.cbs_ambiguous_weeks[i] > w.cbs_doubleheader_weeks[i]:
                raise ValueError(f"season_weeks.cbs_ambiguous_weeks[{i}]: exceeds doubleheader")

    def _check_booths(self, num_games: int, referenced_people: set[int]) -> None:
        b = self.fox_booths
        n = _check_lengths("fox_booths", b, "season")
        num_people = len(self.lookups.people)
        leads: set[int] = set()
        for i in range(n):
            for col in ("pbp_person", "analyst_person"):
                value = getattr(b, col)[i]
                _check_index("fox_booths", col, i, value, num_people)
                if value is not None:
                    referenced_people.add(value)
            _check_game_list("fox_booths", i, b.game_list[i], num_games)
            if b.group[i] == "lead":
                if b.season[i] in leads:
                    raise ValueError(f"fox_booths.group[{i}]: second lead row in one season")
                leads.add(b.season[i])
            if b.group[i] == "others_pooled" and (
                b.pbp_person[i] is not None or b.analyst_person[i] is not None
            ):
                raise ValueError(f"fox_booths.pbp_person[{i}]: a pooled row names no people")

    def _check_agotw(self, num_games: int, referenced_people: set[int]) -> None:
        a = self.agotw_viewership
        n = _check_lengths("agotw_viewership", a, "season")
        num_people = len(self.lookups.people)
        for i in range(n):
            _check_index("agotw_viewership", "era", i, a.era[i], len(self.lookups.eras))
            for col in ("pbp_person", "analyst_person"):
                value = getattr(a, col)[i]
                _check_index("agotw_viewership", col, i, value, num_people)
                if value is not None:
                    referenced_people.add(value)
            _check_game_list("agotw_viewership", i, a.game_list[i], num_games)


def validate_nfl_site_data(obj: object) -> NflSiteData:
    """Validate `obj` (a parsed nfl-data.json body) against the contract."""
    return NflSiteData.model_validate(obj)


# The display-field allowlist for the games block.
NFL_GAME_FIELDS: tuple[str, ...] = tuple(NflGameColumns.model_fields)
