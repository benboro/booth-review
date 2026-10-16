"""The MLB site-data contract (phase 09 plan 10): pydantic models for every
display field the three MLB views need, a parallel of `contract/nfl_models.py`
on its own versioned line.

Every model uses `extra="forbid"` so an analysis-only field (`is_exclusive`,
`production`, raw crew strings, a raw win-expectancy table, per-play series,
Stats API payloads) fails validation instead of silently shipping. Every model is
`strict=True` so a stringified number never coerces, and `frozen=True` since a
validated payload is a read-only snapshot. `window` is allowed by D-03 but ships
nowhere, because neither the Apple view nor the postseason view needs it.

There is deliberately no wall-clock `generated_at`, so identical inputs give
identical bytes. Validation messages name `block.column[position]` only, never a
cell value. See docs/mlb-data.md for the field-by-field contract.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

MLB_SCHEMA_VERSION = "1.0.0"

# Round labels in display order; lookups.rounds must equal this tuple.
MLB_ROUNDS: tuple[str, ...] = (
    "regular",
    "wild_card",
    "division",
    "lcs",
    "world_series",
    "tiebreak",
)

# Why a game has no viewership figure (null) -- or "none" when nothing explains it.
MLB_CAUSES: tuple[str, ...] = (
    "pending",
    "none",
    "regional",
    "per_network",
    "ambiguous_doubleheader",
    "conflict",
    "window_level",
)

MLB_CREW_SOURCES: tuple[str, ...] = ("override", "506", "relay", "wikipedia")

MlbRound = Literal["regular", "wild_card", "division", "lcs", "world_series", "tiebreak"]
MlbCause = Literal[
    "pending",
    "none",
    "regional",
    "per_network",
    "ambiguous_doubleheader",
    "conflict",
    "window_level",
]
MlbCrewSource = Literal["override", "506", "relay", "wikipedia"]
# Where a game's outlet came from; a Wikipedia outlet must carry its article link.
MlbNetworkSource = Literal["override", "506", "wikipedia"]
MlbCrewRole = Literal["pbp", "analyst"]
MlbNetworkFamily = Literal["disney", "fox", "cbs", "nbc", "tbs", "apple", "other"]
MlbLineupStatus = Literal["present", "pending", "missing"]
MlbQualityStatus = Literal["pending", "ready"]
MlbLeague = Literal["AL", "NL"]
# The labels the Apple ranking emits: "Lead", "#2", "#3", ..., or "Other".
MlbRankLabel = Literal["Lead", "Other"] | Annotated[str, StringConstraints(pattern=r"^#\d+$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class MlbFreshness(_Strict):
    season: int
    in_progress: bool
    retrosheet_through_season: int | None
    quality_pending: bool


class MlbConstants(_Strict):
    excitement_method: str
    stakes_method: str
    low_n_threshold: int
    coverage_bar: float


class MlbClubRef(_Strict):
    id: str
    name: str
    league: MlbLeague | None
    division: str | None


class MlbTeamNameRef(_Strict):
    """A club's name for a span of seasons (clubs rename and relocate)."""

    club: int
    name: str
    short: str
    season_start: int
    season_end: int | None


class MlbNetworkRef(_Strict):
    id: str
    name: str
    family: MlbNetworkFamily


class MlbPersonRef(_Strict):
    id: str
    name: str


class MlbPlayerRef(_Strict):
    """A Retrosheet player id and name, only for players in shipped lineups."""

    id: str
    name: str


class MlbEraRef(_Strict):
    id: str
    label: str
    start: str | None
    end: str | None
    source_url: str


class MlbLeagueRef(_Strict):
    id: MlbLeague
    name: str


class MlbLookups(_Strict):
    clubs: list[MlbClubRef]
    team_names: list[MlbTeamNameRef]
    networks: list[MlbNetworkRef]
    people: list[MlbPersonRef]
    players: list[MlbPlayerRef]
    rounds: list[MlbRound]
    leagues: list[MlbLeagueRef]
    eras: list[MlbEraRef]


class MlbCrewEntry(_Strict):
    person: int
    role: MlbCrewRole


class MlbGameColumns(_Strict):
    """One list per display field; index i across every list is one game."""

    season: list[int]
    date: list[str]
    game_number: list[int]
    away: list[int]
    home: list[int]
    round: list[MlbRound]
    series_league: list[int | None]
    series_game: list[int | None]
    network: list[int | None]
    network_source: list[MlbNetworkSource | None]
    network_source_url: list[str | None]
    crew: list[list[MlbCrewEntry]]
    crew_source: list[MlbCrewSource | None]
    crew_source_url: list[str | None]
    press_url: list[str | None]
    press_name: list[str | None]
    wp_excitement: list[float | None]
    stakes: list[float | None]
    viewers: list[int | None]
    viewership_label: list[str | None]
    scope: list[Literal["window", "game"] | None]
    era: list[int | None]
    rr_url: list[str | None]
    source_url: list[str | None]
    cause: list[MlbCause | None]
    lineup_status: list[MlbLineupStatus]
    lineup_start: list[int | None]
    lineup_end: list[int | None]


class MlbLineupColumns(_Strict):
    """Flat rows: slot 0 is the starting pitcher, slots 1-9 the batting order."""

    game: list[int]
    side: list[Literal["away", "home"]]
    slot: list[int]
    player: list[int]
    position: list[str]
    starter_uncertain: list[bool]


class MlbAppleBoothColumns(_Strict):
    """Apple booth rows, ordered stakes-first (D-07). While quality is pending
    every stakes and excitement figure is null (D-06)."""

    rank_label: list[MlbRankLabel]
    pbp: list[int]
    analyst: list[int | None]
    games: list[int]
    crew_listed: list[int]
    relay_crews: list[int]
    raw_stakes: list[float | None]
    raw_stakes_n: list[int]
    adj_stakes: list[float | None]
    adj_stakes_se: list[float | None]
    raw_excitement: list[float | None]
    adj_excitement: list[float | None]
    adj_excitement_se: list[float | None]
    strength_prior: list[float | None]
    low_n: list[bool]
    quality_status: list[MlbQualityStatus]
    game_list: list[list[int]]


class MlbAppleSummary(_Strict):
    lead_minus_others_stakes: float | None
    lead_minus_others_stakes_se: float | None
    lead_minus_others_excitement: float | None
    lead_minus_others_excitement_se: float | None
    n_lead: int
    n_others: int
    rr_rated: int
    apple_games: int


class MlbPostseasonColumns(_Strict):
    """One row per season, round and league cell. `networks` lists every outlet the
    cell's games aired on (most common first); `outlet_source_url` is the Wikipedia
    article the cell's outlets came from, required whenever one of its shipped games
    has a Wikipedia outlet."""

    season: list[int]
    round: list[MlbRound]
    league: list[int | None]
    networks: list[list[int]]
    outlet_source_url: list[str | None]
    booths: list[list[list[int | None]]]
    games: list[int]
    crew_listed: list[int]
    coverage_num: list[int]
    coverage_den: list[int]
    mean_excitement: list[float | None]
    excitement_n: list[int]
    viewers_mean: list[float | None]
    viewers_n: list[int]
    game_list: list[list[int]]


class MlbPostseasonSeasonColumns(_Strict):
    season: list[int]
    coverage_num: list[int]
    coverage_den: list[int]


_PENDING_NULL_BOOTH_COLUMNS: tuple[str, ...] = (
    "raw_stakes",
    "adj_stakes",
    "adj_stakes_se",
    "raw_excitement",
    "adj_excitement",
    "adj_excitement_se",
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
    """Every float cell is finite: NaN and Infinity are not valid JSON, so one such
    cell would make the browser reject the whole file. Messages name
    `block.column[position]` only."""
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


def _is_https(url: str | None) -> bool:
    return url is not None and url.startswith("https://")


class MlbSiteData(_Strict):
    schema_version: Literal["1.0.0"]
    freshness: MlbFreshness
    constants: MlbConstants
    lookups: MlbLookups
    games: MlbGameColumns
    lineups: MlbLineupColumns
    apple_booths: MlbAppleBoothColumns
    apple_summary: MlbAppleSummary
    postseason: MlbPostseasonColumns
    postseason_seasons: MlbPostseasonSeasonColumns

    @model_validator(mode="after")
    def _check_alignment_and_indexes(self) -> MlbSiteData:
        """Aligned column lengths, in-range lookup indexes and the invariants.

        Error messages name `block.column[position]` only, never cell content,
        so a failing real build never echoes vault rows into logs.
        """
        if tuple(self.lookups.rounds) != MLB_ROUNDS:
            raise ValueError("lookups.rounds: must equal the MLB round names in order")
        for block in ("games", "lineups", "apple_booths", "postseason"):
            _check_finite(block, getattr(self, block))
        self._check_summary_finite()
        self._check_lookups()
        people: set[int] = set()
        networks: set[int] = set()
        players: set[int] = set()
        n_games = self._check_games(people, networks)
        self._check_lineups(n_games, players)
        self._check_apple(n_games, people)
        self._check_postseason(n_games, people, networks)
        self._check_postseason_seasons()
        for k in range(len(self.lookups.people)):
            if k not in people:
                raise ValueError(f"lookups.people[{k}]: not referenced by anything")
        for k in range(len(self.lookups.networks)):
            if k not in networks:
                raise ValueError(f"lookups.networks[{k}]: not referenced by anything")
        for k in range(len(self.lookups.players)):
            if k not in players:
                raise ValueError(f"lookups.players[{k}]: not in any shipped lineup")
        return self

    def _check_summary_finite(self) -> None:
        if not math.isfinite(self.constants.coverage_bar):
            raise ValueError("constants.coverage_bar: must be finite")
        for name, value in self.apple_summary:
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"apple_summary.{name}: must be finite")

    def _check_lookups(self) -> None:
        lk = self.lookups
        for i, t in enumerate(lk.team_names):
            _check_index("lookups.team_names", "club", i, t.club, len(lk.clubs))
        if [x.id for x in lk.leagues] != ["AL", "NL"]:
            raise ValueError("lookups.leagues: must be AL then NL")

    def _check_games(self, people: set[int], networks: set[int]) -> int:
        g = self.games
        lk = self.lookups
        n = _check_lengths("games", g, "season")
        for i in range(n):
            _check_index("games", "away", i, g.away[i], len(lk.clubs))
            _check_index("games", "home", i, g.home[i], len(lk.clubs))
            _check_index("games", "series_league", i, g.series_league[i], len(lk.leagues))
            _check_index("games", "network", i, g.network[i], len(lk.networks))
            _check_index("games", "era", i, g.era[i], len(lk.eras))
            if g.network[i] is not None:
                networks.add(g.network[i])  # type: ignore[arg-type]
            for j, entry in enumerate(g.crew[i]):
                if not 0 <= entry.person < len(lk.people):
                    raise ValueError(f"games.crew[{i}][{j}].person: index out of range")
                people.add(entry.person)
            self._check_round(i)
            self._check_network_source(i)
            self._check_crew_source(i)
            self._check_rating(i)
        return n

    def _check_round(self, i: int) -> None:
        g = self.games
        rnd = g.round[i]
        if rnd == "regular" and (g.series_league[i] is not None or g.series_game[i] is not None):
            raise ValueError(f"games.series_game[{i}]: set on a regular-season game")
        if rnd == "world_series" and g.series_league[i] is not None:
            raise ValueError(f"games.series_league[{i}]: set on a World Series game")
        if g.series_game[i] is not None and g.series_game[i] < 1:  # type: ignore[operator]
            raise ValueError(f"games.series_game[{i}]: must be >= 1")

    def _check_network_source(self, i: int) -> None:
        g = self.games
        source, url = g.network_source[i], g.network_source_url[i]
        if g.network[i] is None:
            if source is not None or url is not None:
                raise ValueError(f"games.network_source[{i}]: set without an outlet")
            return
        if source is None:
            raise ValueError(f"games.network_source[{i}]: required when the game has an outlet")
        if source == "wikipedia" and not _is_https(url):
            raise ValueError(f"games.network_source_url[{i}]: a Wikipedia outlet needs its article")
        if url is not None and (source == "506" or not _is_https(url)):
            raise ValueError(f"games.network_source_url[{i}]: not a valid outlet citation")

    def _check_crew_source(self, i: int) -> None:
        g = self.games
        source, url, crew = g.crew_source[i], g.crew_source_url[i], g.crew[i]
        press_url, press_name = g.press_url[i], g.press_name[i]
        if source is None and crew:
            raise ValueError(f"games.crew_source[{i}]: required when the game has a crew")
        if source is not None and not crew:
            raise ValueError(f"games.crew_source[{i}]: must be null when the crew is empty")
        if source is None and url is not None:
            raise ValueError(f"games.crew_source_url[{i}]: set without a crew")
        if url is not None and not _is_https(url):
            raise ValueError(f"games.crew_source_url[{i}]: must be an https citation")
        if source in ("relay", "wikipedia") and url is None:
            raise ValueError(f"games.crew_source_url[{i}]: required for this crew source")
        if source == "relay":
            if not _is_https(press_url):
                raise ValueError(f"games.press_url[{i}]: relay crews need an https press page")
            if not press_name:
                raise ValueError(f"games.press_name[{i}]: relay crews need the press page name")
        elif press_url is not None or press_name is not None:
            raise ValueError(f"games.press_url[{i}]: only for relay crews")

    def _check_rating(self, i: int) -> None:
        g = self.games
        viewers, cause = g.viewers[i], g.cause[i]
        if viewers is None:
            if cause is None:
                raise ValueError(f"games.cause[{i}]: required when viewers is null")
            for col in ("scope", "era", "viewership_label"):
                if getattr(g, col)[i] is not None:
                    raise ValueError(f"games.{col}[{i}]: set on an unrated game")
        else:
            if viewers <= 0:
                raise ValueError(f"games.viewers[{i}]: must be > 0")
            if cause is not None:
                raise ValueError(f"games.cause[{i}]: set on a rated game")
            if not _is_https(g.rr_url[i]):
                raise ValueError(f"games.rr_url[{i}]: required with a viewers figure")
            if not _is_https(g.source_url[i]):
                raise ValueError(f"games.source_url[{i}]: required with a viewers figure")
        if g.lineup_status[i] == "present":
            start, end = g.lineup_start[i], g.lineup_end[i]
            if start is None or end is None or start > end:
                raise ValueError(f"games.lineup_start[{i}]: needs a valid lineup range")
        elif g.lineup_start[i] is not None or g.lineup_end[i] is not None:
            raise ValueError(f"games.lineup_start[{i}]: set without a present lineup")

    def _check_lineups(self, num_games: int, players: set[int]) -> None:
        ln = self.lineups
        n = _check_lengths("lineups", ln, "game")
        for i in range(n):
            _check_index("lineups", "game", i, ln.game[i], num_games)
            _check_index("lineups", "player", i, ln.player[i], len(self.lookups.players))
            if not 0 <= ln.slot[i] <= 9:
                raise ValueError(f"lineups.slot[{i}]: must be 0 to 9")
            players.add(ln.player[i])
        g = self.games
        for gi in range(num_games):
            start, end = g.lineup_start[gi], g.lineup_end[gi]
            if start is None or end is None:
                continue
            if end >= n:
                raise ValueError(f"games.lineup_end[{gi}]: past the lineups block")
            for k in range(start, end + 1):
                if ln.game[k] != gi:
                    raise ValueError(f"lineups.game[{k}]: outside its game's lineup range")

    def _check_apple(self, num_games: int, people: set[int]) -> None:
        b = self.apple_booths
        n = _check_lengths("apple_booths", b, "pbp")
        for i in range(n):
            _check_index("apple_booths", "pbp", i, b.pbp[i], len(self.lookups.people))
            _check_index("apple_booths", "analyst", i, b.analyst[i], len(self.lookups.people))
            people.add(b.pbp[i])
            if b.analyst[i] is not None:
                people.add(b.analyst[i])  # type: ignore[arg-type]
            _check_game_list("apple_booths", i, b.game_list[i], num_games)
            if len(b.game_list[i]) != b.games[i]:
                raise ValueError(f"apple_booths.game_list[{i}]: length does not equal games")
            if b.crew_listed[i] > b.games[i] or b.relay_crews[i] > b.crew_listed[i]:
                raise ValueError(f"apple_booths.crew_listed[{i}]: exceeds its bound")
            if b.quality_status[i] == "pending":
                for col in _PENDING_NULL_BOOTH_COLUMNS:
                    if getattr(b, col)[i] is not None:
                        raise ValueError(f"apple_booths.{col}[{i}]: must be null while pending")
        s = self.apple_summary
        any_pending = any(q == "pending" for q in b.quality_status)
        if any_pending:
            for name in (
                "lead_minus_others_stakes",
                "lead_minus_others_stakes_se",
                "lead_minus_others_excitement",
                "lead_minus_others_excitement_se",
            ):
                if getattr(s, name) is not None:
                    raise ValueError(f"apple_summary.{name}: must be null while pending")
        if self.freshness.quality_pending != any_pending:
            raise ValueError("freshness.quality_pending: does not match the booth quality status")

    def _check_postseason(self, num_games: int, people: set[int], networks: set[int]) -> None:
        p = self.postseason
        lk = self.lookups
        n = _check_lengths("postseason", p, "season")
        seen: set[tuple[int, str, int | None]] = set()
        for i in range(n):
            _check_index("postseason", "league", i, p.league[i], len(lk.leagues))
            if not p.networks[i]:
                raise ValueError(f"postseason.networks[{i}]: needs at least one outlet")
            for net in p.networks[i]:
                _check_index("postseason", "networks", i, net, len(lk.networks))
                networks.add(net)
            if len(set(p.networks[i])) != len(p.networks[i]):
                raise ValueError(f"postseason.networks[{i}]: repeated outlet")
            if p.round[i] in ("regular",):
                raise ValueError(f"postseason.round[{i}]: regular season is not a postseason round")
            key = (p.season[i], p.round[i], p.league[i])
            if key in seen:
                raise ValueError(f"postseason.season[{i}]: second row for one cell")
            seen.add(key)
            url = p.outlet_source_url[i]
            if url is not None and not _is_https(url):
                raise ValueError(f"postseason.outlet_source_url[{i}]: must be an https link")
            if url is None and any(
                self.games.network_source[g] == "wikipedia"
                for g in p.game_list[i]
                if 0 <= g < num_games
            ):
                raise ValueError(
                    f"postseason.outlet_source_url[{i}]: Wikipedia outlet needs its article"
                )
            for j, booth in enumerate(p.booths[i]):
                if len(booth) != 2 or booth[0] is None:
                    raise ValueError(f"postseason.booths[{i}][{j}]: must be [pbp, analyst]")
                for person in booth:
                    _check_index("postseason", "booths", i, person, len(lk.people))
                    if person is not None:
                        people.add(person)
            _check_game_list("postseason", i, p.game_list[i], num_games)
            if len(p.game_list[i]) != p.games[i]:
                raise ValueError(f"postseason.game_list[{i}]: length does not equal games")
            if p.crew_listed[i] > p.games[i]:
                raise ValueError(f"postseason.crew_listed[{i}]: exceeds games")
            if p.coverage_num[i] > p.coverage_den[i]:
                raise ValueError(f"postseason.coverage_num[{i}]: exceeds coverage_den")
            if p.excitement_n[i] > p.games[i] or p.viewers_n[i] > p.games[i]:
                raise ValueError(f"postseason.excitement_n[{i}]: exceeds games")

    def _check_postseason_seasons(self) -> None:
        ps = self.postseason_seasons
        p = self.postseason
        n = _check_lengths("postseason_seasons", ps, "season")
        if len(set(ps.season)) != n:
            raise ValueError("postseason_seasons.season: duplicate season")
        for i in range(n):
            if ps.coverage_num[i] > ps.coverage_den[i]:
                raise ValueError(f"postseason_seasons.coverage_num[{i}]: exceeds coverage_den")
            # The season counts every postseason game; a cell holds only games with an
            # own-production outlet, so the cells can add up to less, never more.
            rows = [k for k in range(len(p.season)) if p.season[k] == ps.season[i]]
            if (
                sum(p.coverage_num[k] for k in rows) > ps.coverage_num[i]
                or sum(p.coverage_den[k] for k in rows) > ps.coverage_den[i]
            ):
                raise ValueError(f"postseason_seasons.coverage_num[{i}]: smaller than its cells")
        for k in range(len(p.season)):
            if p.season[k] not in ps.season:
                raise ValueError(f"postseason.season[{k}]: season missing from postseason_seasons")


def validate_mlb_site_data(obj: object) -> MlbSiteData:
    """Validate `obj` (a parsed mlb-data.json body) against the contract."""
    return MlbSiteData.model_validate(obj)


# The display-field allowlist for the games block.
MLB_GAME_FIELDS: tuple[str, ...] = tuple(MlbGameColumns.model_fields)
