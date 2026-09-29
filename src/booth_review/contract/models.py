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

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

SCHEMA_VERSION = "1.2.0"


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
    excitement: list[float | None]
    pregame: list[float | None]
    flags: list[list[int]]
    combined_feeds: list[int | None]
    crew: list[list[CrewEntry]]
    game_type: list[Literal["regular", "bowl", "playoff"]]
    playoff_round: list[Literal["first_round", "quarterfinal", "semifinal", "championship"] | None]
    home_conference: list[int | None]
    away_conference: list[int | None]


class CoverageRow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    season: int
    network: int | None = None
    rated_telecasts: int
    matched_game: int
    matched_crew: int
    match_rate: float | None = None
    headline_present: int
    excitement_present: int
    pregame_present: int
    duplicate_merges: int
    combined_figures: int
    publisher_counts: dict[str, int]


class SiteData(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["1.2.0"]
    generated_at: str
    freshness: Freshness
    lookups: Lookups
    telecasts: TelecastColumns
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
        num_people = len(self.lookups.people)
        num_publishers = len(self.lookups.publishers)
        num_flags = len(self.lookups.flags)
        num_conferences = len(self.lookups.conferences)

        for i in range(n):
            if not 0 <= tc.away_team[i] < num_teams:
                raise ValueError(f"telecasts.away_team[{i}]: team index out of range")
            if not 0 <= tc.home_team[i] < num_teams:
                raise ValueError(f"telecasts.home_team[{i}]: team index out of range")
            if not 0 <= tc.network[i] < num_networks:
                raise ValueError(f"telecasts.network[{i}]: network index out of range")
            for j, outlet in enumerate(tc.outlets[i]):
                if not 0 <= outlet < num_networks:
                    raise ValueError(f"telecasts.outlets[{i}][{j}]: network index out of range")
            publisher = tc.publisher[i]
            if publisher is not None and not 0 <= publisher < num_publishers:
                raise ValueError(f"telecasts.publisher[{i}]: publisher index out of range")
            for j, flag_index in enumerate(tc.flags[i]):
                if not 0 <= flag_index < num_flags:
                    raise ValueError(f"telecasts.flags[{i}][{j}]: flag index out of range")
            for j, crew_entry in enumerate(tc.crew[i]):
                if not 0 <= crew_entry.person < num_people:
                    raise ValueError(f"telecasts.crew[{i}][{j}].person: person index out of range")
            if tc.viewers[i] <= 0:
                raise ValueError(f"telecasts.viewers[{i}]: must be > 0")
            if not tc.rr_urls[i]:
                raise ValueError(f"telecasts.rr_urls[{i}]: must not be empty")
            combined = tc.combined_feeds[i]
            if combined is not None and combined < 2:
                raise ValueError(f"telecasts.combined_feeds[{i}]: must be null or >= 2")
            home_conference = tc.home_conference[i]
            if home_conference is not None and not 0 <= home_conference < num_conferences:
                raise ValueError(f"telecasts.home_conference[{i}]: conference index out of range")
            away_conference = tc.away_conference[i]
            if away_conference is not None and not 0 <= away_conference < num_conferences:
                raise ValueError(f"telecasts.away_conference[{i}]: conference index out of range")
            if tc.playoff_round[i] is not None and tc.game_type[i] != "playoff":
                raise ValueError(f"telecasts.playoff_round[{i}]: set on a non-playoff game")

        for i, row in enumerate(self.coverage):
            if row.network is not None and not 0 <= row.network < num_networks:
                raise ValueError(f"coverage[{i}].network: network index out of range")

        return self


def validate_site_data(obj: object) -> SiteData:
    """Validate `obj` (a parsed site-data.json body) against the contract."""
    return SiteData.model_validate(obj)


# Plan 11's display-field allowlist: only these column names may ever appear
# in the real build's telecasts payload (SITE-19).
SITE_DATA_FIELDS: tuple[str, ...] = tuple(TelecastColumns.model_fields)
