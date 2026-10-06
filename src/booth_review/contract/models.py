"""The site-data contract (D-13/D-14): pydantic models for every display
field the Phase 4 static site needs, fixed before any join code exists.

Every model uses `extra="forbid"` so an undeclared field (a CFBD
classification, venue, win probability, or any other bulk field the site
never shows) fails validation instead of silently shipping (SITE-19, CFBD
terms). Every model is `strict=True` so a stringified number never silently
coerces, and `frozen=True` since a validated `SiteData` is a read-only
snapshot of the build output, never mutated after validation.
"""

from __future__ import annotations

from collections import Counter
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "2.2.0"

_S506_HOST = "506sports.com"

# Franchise and rivalry slugs are URL values: kebab-case, one shared namespace
# with the four slugs the client reserves for CFP rounds (04.9 D-16).
GAME_SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
RESERVED_GAME_SLUGS = frozenset(
    {"cfp-national-championship", "cfp-semifinal", "cfp-quarterfinal", "cfp-first-round"}
)

# The longest crew-source label (crew_overrides.csv source_name) allowed.
CREW_SOURCE_LABEL_MAX_LEN = 60


def crew_source_url_problem(url: str) -> str | None:
    """Why `url` cannot cite a hand-confirmed crew, or None when it can.

    A crew source must be an http(s) URL with a host, and never 506 Sports
    (04.3 D-01: an override records a crew some other public source
    publishes). The crew-override loader and the contract share this check.
    The message never echoes the URL.
    """
    if any(ch.isspace() for ch in url):
        return "must not contain whitespace"
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return "must be an http(s) URL with a host"
    if parts.scheme not in {"http", "https"} or not host:
        return "must be an http(s) URL with a host"
    host = host.rstrip(".")
    if host == _S506_HOST or host.endswith("." + _S506_HOST):
        return "must not cite 506 Sports"
    return None


def crew_source_label_problem(label: str) -> str | None:
    """Why `label` cannot name a crew's cited source, or None when it can.

    Non-empty, at most CREW_SOURCE_LABEL_MAX_LEN characters, and no `<` or
    `>`. The crew-override loader (source_name) and the contract share this
    check. The message never echoes the label.
    """
    if not label.strip():
        return "must not be empty"
    if len(label) > CREW_SOURCE_LABEL_MAX_LEN:
        return f"must be at most {CREW_SOURCE_LABEL_MAX_LEN} characters"
    if "<" in label or ">" in label:
        return "must not contain < or >"
    return None


class TeamRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    name: str


class NetworkRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: str
    name: str
    family: str


class ConferenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    name: str
    is_fbs: bool


class BowlRef(BaseModel):
    """A bowl's display names: the official name for that season (with any
    sponsor) and the core name (D-17/D-19). Never a raw CFBD note."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    name: str = Field(min_length=1)
    core: str = Field(min_length=1)
    # Index into lookups.bowl_franchises (04.9 D-07).
    franchise: int

    @model_validator(mode="after")
    def _core_in_name(self) -> BowlRef:
        if self.core not in self.name:
            raise ValueError("bowl core name must be a substring of its name")
        return self


class BowlFranchiseRef(BaseModel):
    """A bowl franchise: the latest core name, older core names for search
    only, and a permanent URL slug (04.9 D-07)."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    slug: str = Field(pattern=GAME_SLUG_PATTERN)
    name: str = Field(min_length=1)
    former: list[str]

    @model_validator(mode="after")
    def _former_names(self) -> BowlFranchiseRef:
        if any(not f for f in self.former):
            raise ValueError("former names must not be empty")
        if len(set(self.former)) != len(self.former):
            raise ValueError("former names must not repeat")
        if self.name in self.former:
            raise ValueError("former names must not include the current name")
        return self


class RivalryRef(BaseModel):
    """A curated rivalry: slug, display name, the article titles put before the
    name ("the" or null), and its two teams as ascending indexes into
    lookups.teams (04.9 D-13, D-18)."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    slug: str = Field(pattern=GAME_SLUG_PATTERN)
    name: str = Field(min_length=1)
    article: Literal["the"] | None
    teams: list[int] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def _teams_ascending(self) -> RivalryRef:
        if self.teams[0] >= self.teams[1]:
            raise ValueError("rivalry teams must be two distinct ascending indexes")
        if self.article is not None and self.name.startswith("The "):
            raise ValueError("rivalry article must be null when the name starts with 'The '")
        return self


class PersonRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: str
    name: str
    variants: list[str]
    usual_role: Literal["pbp", "analyst", "unknown"]


class FlagRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: str
    kind: Literal["era", "event", "measurement", "model_break", "combined"]
    label: str
    source_url: str | None = None


class CrewEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    person: int
    role: Literal["pbp", "analyst", "unknown"]
    feed: Literal["main", "alt", "spanish"]


class Freshness(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    season: int
    crews_through_week: str | None = None
    viewership_through_week: str | None = None


class Lookups(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    teams: list[TeamRef]
    networks: list[NetworkRef]
    people: list[PersonRef]
    publishers: list[str]
    flags: list[FlagRef]
    conferences: list[ConferenceRef]
    bowls: list[BowlRef]
    bowl_franchises: list[BowlFranchiseRef]
    rivalries: list[RivalryRef]


class TelecastColumns(BaseModel):
    """One list per display field; index i across every list is one dot.

    See docs/site-data.md for the field-by-field contract (null rules, the
    SITE requirement each field serves, and the time-slot boundaries).
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    season: list[int]
    date: list[str]
    kickoff: list[str | None]
    time_slot: list[Literal["noon", "afternoon", "prime", "late"] | None]
    away_team: list[int]
    home_team: list[int]
    neutral: list[bool]
    away_points: list[int | None]
    home_points: list[int | None]
    away_rank: list[int | None]
    home_rank: list[int | None]
    network: list[int]
    outlets: list[list[int]]
    viewers: list[int]
    measurement_type: list[Literal["nielsen", "nielsen_adobe", "unknown"]]
    publisher: list[int | None]
    source_url: list[str | None]
    rr_urls: list[list[str]]
    s506_url: list[str | None]
    # 04.3 D-11: a hand-confirmed crew's own cited source; null for 506 crews; both set or both null
    crew_source_url: list[str | None]
    crew_source_label: list[str | None]
    excitement: list[float | None]
    # 04.6 D-08 / 04.8 D-01: closing spread from the HOME team's side (CFBD sign: negative =
    # home favored); null when the closing spread isn't known. The client derives the
    # winner-signed Spread axis from it.
    home_spread: list[float | None]
    flags: list[list[int]]
    combined_feeds: list[int | None]
    crew: list[list[CrewEntry]]
    game_type: list[Literal["regular", "bowl", "playoff"]]
    playoff_round: list[Literal["first_round", "quarterfinal", "semifinal", "championship"] | None]
    home_conference: list[int | None]
    away_conference: list[int | None]
    # Index into lookups.bowls; non-null only for a game played at a named bowl.
    bowl: list[int | None]
    # Index into lookups.rivalries; non-null only for the first regular-season meeting of a
    # curated rivalry's two teams in a season, conference title games excluded (04.9 D-13),
    # resolved by the build
    rivalry: list[int | None]


class UnratedColumns(BaseModel):
    """One list per display field; index j across every list is one game with
    no public viewer figure.

    Rated-only fields (viewers, measurement_type, publisher, source_url,
    rr_urls, flags, combined_feeds) are absent by design (SITE-19, CFBD terms),
    and so is any game or telecast id. Declared explicitly, not inherited, so
    TelecastColumns keeps its field order. See docs/site-data.md.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    season: list[int]
    date: list[str]
    kickoff: list[str | None]
    time_slot: list[Literal["noon", "afternoon", "prime", "late"] | None]
    away_team: list[int]
    home_team: list[int]
    neutral: list[bool]
    away_points: list[int | None]
    home_points: list[int | None]
    away_rank: list[int | None]
    home_rank: list[int | None]
    network: list[int]
    outlets: list[list[int]]
    s506_url: list[str | None]
    crew_source_url: list[str | None]
    crew_source_label: list[str | None]
    excitement: list[float | None]
    home_spread: list[float | None]
    crew: list[list[CrewEntry]]
    game_type: list[Literal["regular", "bowl", "playoff"]]
    playoff_round: list[Literal["first_round", "quarterfinal", "semifinal", "championship"] | None]
    home_conference: list[int | None]
    away_conference: list[int | None]
    bowl: list[int | None]
    rivalry: list[int | None]
    # 04.13 D-10: why the game has no figure. An enum only; the wording lives in
    # site/modules/format.js, never in the data.
    cause: list[Literal["rarely_rated", "pending", "rr_dip", "none"]]


class CoverageRow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    season: int
    network: int | None = None
    rated_telecasts: int
    matched_game: int
    matched_crew: int
    # of matched_crew, how many had no 506 main crew and took theirs from
    # data/reference/crew_overrides.csv (status `patched`, D-13)
    matched_crew_patched: int
    match_rate: float | None = None
    headline_present: int
    excitement_present: int
    spread_present: int  # telecasts whose game has a closing spread
    duplicate_merges: int
    combined_figures: int
    publisher_counts: dict[str, int]


class SiteData(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["2.2.0"]
    generated_at: str
    freshness: Freshness
    lookups: Lookups
    telecasts: TelecastColumns
    telecasts_unrated: UnratedColumns
    coverage: list[CoverageRow]

    @model_validator(mode="after")
    def _check_alignment_and_indexes(self) -> SiteData:
        """Aligned column lengths and in-range lookup indexes.

        Error messages name the column and position only, never cell
        content, so a failing real build never echoes vault rows into logs
        (T-03-04).
        """
        tc = self.telecasts
        n = len(tc.season)
        for name in TelecastColumns.model_fields:
            value = getattr(tc, name)
            if len(value) != n:
                raise ValueError(
                    f"telecasts.{name}: length {len(value)} does not match "
                    f"telecasts.season length {n}"
                )

        num_teams = len(self.lookups.teams)
        num_networks = len(self.lookups.networks)
        num_publishers = len(self.lookups.publishers)
        num_flags = len(self.lookups.flags)
        num_rivalries = len(self.lookups.rivalries)
        num_franchises = len(self.lookups.bowl_franchises)

        referenced_franchises: set[int] = set()
        for j, bowl_ref in enumerate(self.lookups.bowls):
            if not 0 <= bowl_ref.franchise < num_franchises:
                raise ValueError(f"lookups.bowls[{j}].franchise: franchise index out of range")
            referenced_franchises.add(bowl_ref.franchise)
            franchise_ref = self.lookups.bowl_franchises[bowl_ref.franchise]
            if bowl_ref.core != franchise_ref.name and bowl_ref.core not in franchise_ref.former:
                raise ValueError(f"lookups.bowls[{j}].core: not a name of its franchise")
        for k in range(num_franchises):
            if k not in referenced_franchises:
                raise ValueError(f"lookups.bowl_franchises[{k}]: not referenced by any bowl")
        # A franchise's label is its latest core name, so it must be the core of
        # one of its own bowls (04.9 D-08, WR-05).
        cores_by_franchise: dict[int, set[str]] = {}
        for bowl_ref in self.lookups.bowls:
            cores_by_franchise.setdefault(bowl_ref.franchise, set()).add(bowl_ref.core)
        for k, franchise_ref in enumerate(self.lookups.bowl_franchises):
            if franchise_ref.name not in cores_by_franchise.get(k, set()):
                raise ValueError(
                    f"lookups.bowl_franchises[{k}].name: not the core name of any of its bowls"
                )
        # Two Game rows with one label would be indistinguishable in the picker,
        # the toolbar summary, and titles (WR-05). Compared case-insensitively.
        labels = [f.name.casefold() for f in self.lookups.bowl_franchises]
        labels += [r.name.casefold() for r in self.lookups.rivalries]
        duplicated = sum(n - 1 for n in Counter(labels).values() if n > 1)
        if duplicated:
            raise ValueError(f"lookups: {duplicated} named game(s) repeat another's display name")
        slugs = [f.slug for f in self.lookups.bowl_franchises]
        slugs += [r.slug for r in self.lookups.rivalries]
        if len(set(slugs)) != len(slugs) or any(s in RESERVED_GAME_SLUGS for s in slugs):
            raise ValueError("lookups: duplicate or reserved game slug")
        for k, rivalry_ref in enumerate(self.lookups.rivalries):
            if any(not 0 <= t < num_teams for t in rivalry_ref.teams):
                raise ValueError(f"lookups.rivalries[{k}].teams: team index out of range")
        referenced_rivalries: set[int] = set()

        for i in range(n):
            self._check_game_row("telecasts", tc, i, referenced_rivalries)
            for j, flag_index in enumerate(tc.flags[i]):
                if not 0 <= flag_index < num_flags:
                    raise ValueError(f"telecasts.flags[{i}][{j}]: flag index out of range")
            publisher = tc.publisher[i]
            if publisher is not None and not 0 <= publisher < num_publishers:
                raise ValueError(f"telecasts.publisher[{i}]: publisher index out of range")
            if tc.viewers[i] <= 0:
                raise ValueError(f"telecasts.viewers[{i}]: must be > 0")
            if not tc.rr_urls[i]:
                raise ValueError(f"telecasts.rr_urls[{i}]: must not be empty")
            combined = tc.combined_feeds[i]
            if combined is not None and combined < 2:
                raise ValueError(f"telecasts.combined_feeds[{i}]: must be null or >= 2")

        uc = self.telecasts_unrated
        un = len(uc.season)
        for name in UnratedColumns.model_fields:
            value = getattr(uc, name)
            if len(value) != un:
                raise ValueError(
                    f"telecasts_unrated.{name}: length {len(value)} does not match "
                    f"telecasts_unrated.season length {un}"
                )
        for i in range(un):
            self._check_game_row("telecasts_unrated", uc, i, referenced_rivalries)
            if self.lookups.networks[uc.network[i]].id == "unmapped":
                raise ValueError(
                    f"telecasts_unrated.network[{i}]: an unrated game needs a resolved network"
                )

        for k in range(num_rivalries):
            if k not in referenced_rivalries:
                raise ValueError(f"lookups.rivalries[{k}]: not referenced by any telecast")

        for i, row in enumerate(self.coverage):
            if row.network is not None and not 0 <= row.network < num_networks:
                raise ValueError(f"coverage[{i}].network: network index out of range")
            if row.matched_crew_patched < 0:
                raise ValueError(f"coverage[{i}].matched_crew_patched: must not be negative")
            if row.matched_crew_patched > row.matched_crew:
                raise ValueError(f"coverage[{i}].matched_crew_patched: exceeds matched_crew")

        return self

    def _check_game_row(
        self,
        block: str,
        cols: TelecastColumns | UnratedColumns,
        i: int,
        referenced_rivalries: set[int],
    ) -> None:
        """The per-row checks both blocks share. Messages carry the block name,
        column and position only, never a cell value (T-03-04)."""
        lk = self.lookups
        num_teams = len(lk.teams)
        num_networks = len(lk.networks)
        if not 0 <= cols.away_team[i] < num_teams:
            raise ValueError(f"{block}.away_team[{i}]: team index out of range")
        if not 0 <= cols.home_team[i] < num_teams:
            raise ValueError(f"{block}.home_team[{i}]: team index out of range")
        if not 0 <= cols.network[i] < num_networks:
            raise ValueError(f"{block}.network[{i}]: network index out of range")
        for j, outlet in enumerate(cols.outlets[i]):
            if not 0 <= outlet < num_networks:
                raise ValueError(f"{block}.outlets[{i}][{j}]: network index out of range")
        for j, crew_entry in enumerate(cols.crew[i]):
            if not 0 <= crew_entry.person < len(lk.people):
                raise ValueError(f"{block}.crew[{i}][{j}].person: person index out of range")
        num_conferences = len(lk.conferences)
        home_conference = cols.home_conference[i]
        if home_conference is not None and not 0 <= home_conference < num_conferences:
            raise ValueError(f"{block}.home_conference[{i}]: conference index out of range")
        away_conference = cols.away_conference[i]
        if away_conference is not None and not 0 <= away_conference < num_conferences:
            raise ValueError(f"{block}.away_conference[{i}]: conference index out of range")
        if cols.playoff_round[i] is not None and cols.game_type[i] != "playoff":
            raise ValueError(f"{block}.playoff_round[{i}]: set on a non-playoff game")
        source_url = cols.crew_source_url[i]
        source_label = cols.crew_source_label[i]
        if (source_url is None) != (source_label is None):
            raise ValueError(
                f"{block}.crew_source_label[{i}]: must be set together with crew_source_url"
            )
        if source_url is not None and source_label is not None:
            problem = crew_source_url_problem(source_url)
            if problem is not None:
                raise ValueError(f"{block}.crew_source_url[{i}]: {problem}")
            label_problem = crew_source_label_problem(source_label)
            if label_problem is not None:
                raise ValueError(f"{block}.crew_source_label[{i}]: {label_problem}")
            # The pair cites the crew shown, which is always a main-feed
            # booth from crew_overrides.csv (04.3 D-03).
            if not any(entry.feed == "main" for entry in cols.crew[i]):
                raise ValueError(
                    f"{block}.crew[{i}]: must list a main-feed crew when crew_source_url is set"
                )
        bowl = cols.bowl[i]
        if bowl is not None:
            if not 0 <= bowl < len(lk.bowls):
                raise ValueError(f"{block}.bowl[{i}]: bowl index out of range")
            if cols.game_type[i] == "regular":
                raise ValueError(f"{block}.bowl[{i}]: set on a regular game")
        rivalry = cols.rivalry[i]
        if rivalry is not None:
            if not 0 <= rivalry < len(lk.rivalries):
                raise ValueError(f"{block}.rivalry[{i}]: rivalry index out of range")
            if cols.game_type[i] != "regular":
                raise ValueError(f"{block}.rivalry[{i}]: set on a non-regular game")
            pair = sorted([cols.home_team[i], cols.away_team[i]])
            if pair != lk.rivalries[rivalry].teams:
                raise ValueError(f"{block}.rivalry[{i}]: teams do not match the rivalry")
            referenced_rivalries.add(rivalry)


def validate_site_data(obj: object) -> SiteData:
    """Validate `obj` (a parsed site-data.json body) against the contract."""
    return SiteData.model_validate(obj)


# Plan 11's display-field allowlist: only these column names may ever appear
# in the real build's telecasts payload (SITE-19).
SITE_DATA_FIELDS: tuple[str, ...] = tuple(TelecastColumns.model_fields)

# The unrated block's display-field allowlist (SITE-19): no rated-only field,
# no CFBD-only field, no game or telecast id.
UNRATED_FIELDS: tuple[str, ...] = tuple(UnratedColumns.model_fields)
