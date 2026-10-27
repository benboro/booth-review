"""Generator for the synthetic NFL site-data fixture (999.5 plan 02).

Everything here is invented: franchises, people, scores, viewer counts and
example.com URLs. Nothing is read from the vault. `build_fixture()` returns a
payload that already passed `validate_nfl_site_data`, and `main()` writes it to
tests/fixtures/contract/nfl-data.fixture.json; tests/test_nfl_contract.py checks
the committed file equals this output.

Run: uv run python tests/nfl_site_fixture.py
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from booth_review.contract.nfl_models import (
    NFL_SLOTS,
    NFL_VIEW_CATEGORIES,
    NflBoothColumns,
    NflGameColumns,
    NflUpcomingColumns,
    NflViewershipColumns,
    validate_nfl_site_data,
)

# Synthetic venues (Phase 24): two US stadiums and a foreign one, so a map has a dot, a second
# dot and an edge marker; a null place stands for a stadium missing from the location table.
VENUES: list[dict[str, Any]] = [
    {
        "name": "Fixture Field",
        "city": "Faketown",
        "state": "TX",
        "country": "US",
        "lat": 29.7,
        "lon": -95.4,
    },
    {
        "name": "Example Dome",
        "city": "Sampleville",
        "state": "OH",
        "country": "US",
        "lat": 41.5,
        "lon": -81.7,
    },
    {
        "name": "Test Park",
        "city": "Londonish",
        "state": None,
        "country": "GB",
        "lat": 51.5,
        "lon": -0.1,
    },
]
PLACE_CYCLE: list[int | None] = [0, 1, None, 2, 0]
UPCOMING_PLACE_CYCLE: list[int | None] = [0, 1, 2, None, 0, 1, 0, None, 1, 2]

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "contract" / "nfl-data.fixture.json"

_ET = ZoneInfo("America/New_York")

FRANCHISES = [
    ("f-lanterns", "Northfield Lanterns"),
    ("f-gulls", "Harbor City Gulls"),
    ("f-foxes", "Ridgeport Foxes"),
    ("f-owls", "Granite Bay Owls"),
    ("f-pilots", "Lakeshore Pilots"),
    ("f-comets", "Mesa Comets"),
]
# Team names as displayed in a season; index 6 is franchise 0's earlier name.
TEAM_NAMES = [
    ("Northfield Lanterns", "NFL"),
    ("Harbor City Gulls", "HCG"),
    ("Ridgeport Foxes", "RPF"),
    ("Granite Bay Owls", "GBO"),
    ("Lakeshore Pilots", "LSP"),
    ("Mesa Comets", "MSC"),
    ("Northfield Torches", "NFT"),
]
NETWORKS = [
    ("fox", "Fox", "fox"),
    ("cbs", "CBS", "cbs"),
    ("nbc", "NBC", "nbc"),
    ("espn", "ESPN", "disney"),
    ("prime", "Prime", "other"),
    ("peacock", "Peacock", "nbc"),
    ("abc", "ABC", "disney"),
    ("nfln", "NFL Network", "other"),
    ("netflix", "Netflix", "other"),
]
FOX, CBS, NBC, ESPN, PRIME, PEACOCK, ABC, NFLN, NETFLIX = range(9)
# Picker order: (id, name, flagship label, member network indexes). The flagship
# games are told apart per group in `_is_flagship`.
NETWORK_GROUPS = [
    ("fox", "Fox", "AGOTW", [FOX]),
    ("cbs", "CBS", "Late national", [CBS]),
    ("nbc", "NBC", "SNF", [NBC, PEACOCK]),
    ("espn_abc", "ESPN/ABC", "MNF", [ESPN, ABC]),
    ("prime", "Amazon", "TNF", [PRIME]),
    ("nfln", "NFL Network", None, [NFLN]),
    ("netflix", "Netflix", None, [NETFLIX]),
]
LINEUP_URL = "https://example.com/lineup"
PEOPLE = [
    "Ada Quill",
    "Ben Marlow",
    "Cy Fable",
    "Dee Harrow",
    "Eli Thorne",
    "Fay Lindqvist",
    "Gus Pell",
    "Hana Roark",
    "Ivo Strand",
    "Jun Vale",
    "Kit Bramley",
    "Lou Danvers",
    "Max Eller",
    "Ned Pryor",
    "Opal Reyes",
    "Pia Voss",
    "Rex Dunmore",
]
ERAS = [
    ("era-a", "Invented measurement era A", None, "2024-12-31", "https://example.com/era-a"),
    ("era-b", "Invented measurement era B", "2025-01-01", None, "https://example.com/era-b"),
]
SLOT = {name: i for i, name in enumerate(NFL_SLOTS)}

# Fox booths by season: lead (AGOTW), two named others, and the pooled rest.
_LEAD = {2024: (0, 1), 2025: (2, 3), 2026: (2, 3)}
_CREW_FOX_O1 = (4, 5)
_CREW_FOX_O2 = (6, 7)
_CREW_FILL = (12, 1)
_CREW_CBS = (8, 9)
_CREW_NBC = (10, 11)
_CREW_ESPN = (12, 11)
_CREW_PRIME = (12, 10)
_CREW_CBS2 = (13, 14)
_CREW_NETFLIX = (15, 16)

LOW_N_THRESHOLD = 8

_SLOT_SUFFIXES = (
    "christmas",
    "thanksgiving",
    "black_friday",
    "international",
    "tnf",
    "snf",
    "mnf",
    "saturday",
    "friday",
    "sunday_early",
    "sunday_late",
    "other",
)


def _game(
    season: int,
    week: int,
    day: str,
    hhmm: str,
    home: int,
    away: int,
    slot: str,
    network: int | None,
    crew: tuple[int, int] | None,
    *,
    flags: str = "",
    played: bool = True,
    viewers: bool = True,
    cause: str | None = None,
    exc: bool = True,
    booth: str | None = None,
    tie: bool = False,
    original: tuple[str, int, str] | None = None,
    sideline: int | None = None,
    no_kickoff: bool = False,
    lineup: bool = False,
) -> dict[str, Any]:
    kickoff = None
    if not no_kickoff:
        hour, minute = (int(x) for x in hhmm.split(":"))
        y, m, d = (int(x) for x in day.split("-"))
        kickoff = datetime(y, m, d, hour, minute, tzinfo=_ET).isoformat()
    return {
        "season": season,
        "week": week,
        "date": day,
        "kickoff": kickoff,
        "home": home,
        "away": away,
        "slot": slot,
        "network": network,
        "crew": crew,
        "flags": flags,
        "played": played,
        "viewers": viewers and played,
        "cause": cause,
        "exc": exc and played,
        "booth": booth,
        "tie": tie,
        "original": original,
        "sideline": sideline,
        "no_kickoff": no_kickoff,
        "lineup": lineup,
    }


def _specs() -> list[dict[str, Any]]:
    """The invented games. Flags: S standalone, A AGOTW, C CBS national,
    I international, F flexed. S, A and C never overlap in one game."""
    g = _game
    return [
        # 2024
        g(2024, 1, "2024-09-05", "20:20", 0, 1, "TNF", PRIME, _CREW_PRIME, flags="S"),
        g(
            2024,
            1,
            "2024-09-08",
            "16:25",
            2,
            3,
            "Sunday late",
            FOX,
            _LEAD[2024],
            flags="A",
            booth="lead",
        ),
        g(2024, 1, "2024-09-08", "13:00", 4, 5, "Sunday early", CBS, _CREW_CBS, flags="C"),
        g(2024, 2, "2024-09-15", "20:20", 1, 2, "SNF", NBC, _CREW_NBC, flags="S"),
        g(2024, 2, "2024-09-16", "20:15", 3, 4, "MNF", ESPN, _CREW_ESPN, flags="S"),
        g(
            2024,
            3,
            "2024-09-22",
            "16:25",
            0,
            5,
            "Sunday late",
            FOX,
            _LEAD[2024],
            flags="A",
            booth="lead",
        ),
        g(
            2024,
            4,
            "2024-09-29",
            "09:30",
            2,
            4,
            "International",
            None,
            None,
            flags="I",
            viewers=False,
            cause="none",
            exc=False,
        ),
        g(2024, 5, "2024-10-06", "13:00", 3, 0, "Sunday early", FOX, _CREW_FOX_O1, booth="o1"),
        g(
            2024,
            5,
            "2024-10-06",
            "16:25",
            1,
            5,
            "Sunday late",
            FOX,
            _LEAD[2024],
            flags="A",
            booth="lead",
            viewers=False,
            cause="regional",
        ),
        g(
            2024,
            6,
            "2024-10-13",
            "13:00",
            2,
            1,
            "Sunday early",
            FOX,
            _CREW_FOX_O2,
            booth="o2",
            viewers=False,
            cause="none",
            exc=False,
        ),
        g(
            2024,
            8,
            "2024-10-27",
            "20:20",
            5,
            0,
            "SNF",
            NBC,
            _CREW_NBC,
            flags="SF",
            original=("Sunday late", FOX, "https://example.com/wiki/2024-week-8-flex"),
        ),
        g(2024, 11, "2024-11-17", "13:00", 3, 1, "Sunday early", FOX, _CREW_FILL, booth="pool"),
        g(2024, 12, "2024-11-21", "20:15", 4, 2, "TNF", PRIME, _CREW_PRIME, flags="S", tie=True),
        g(2024, 13, "2024-11-28", "12:30", 1, 3, "Thanksgiving", CBS, _CREW_CBS, flags="S"),
        g(2024, 13, "2024-11-29", "15:00", 0, 2, "Black Friday", PRIME, _CREW_PRIME, flags="S"),
        g(2024, 16, "2024-12-21", "13:00", 5, 3, "Saturday", ESPN, _CREW_ESPN, flags="S"),
        g(
            2024,
            17,
            "2024-12-25",
            "13:00",
            2,
            4,
            "Christmas",
            NBC,
            _CREW_NBC,
            flags="S",
            sideline=5,
        ),
        g(2024, 10, "2024-11-10", "13:00", 1, 4, "Sunday early", CBS, _CREW_CBS2),
        g(2024, 14, "2024-12-08", "13:00", 4, 0, "Other", PEACOCK, _CREW_NBC, flags="S"),
        g(2024, 15, "2024-12-14", "16:30", 3, 2, "Saturday", NFLN, None, flags="S"),
        g(2024, 18, "2025-01-05", "13:00", 0, 1, "Sunday early", FOX, _CREW_FOX_O1, booth="o1"),
        g(
            2024,
            18,
            "2025-01-05",
            "16:25",
            3,
            5,
            "Sunday late",
            FOX,
            _LEAD[2024],
            flags="A",
            booth="lead",
        ),
        # 2025
        g(2025, 1, "2025-09-04", "20:20", 1, 0, "TNF", NBC, _CREW_NBC, flags="S"),
        g(
            2025,
            1,
            "2025-09-07",
            "16:25",
            2,
            4,
            "Sunday late",
            FOX,
            _LEAD[2025],
            flags="A",
            booth="lead",
        ),
        g(2025, 1, "2025-09-07", "13:00", 3, 5, "Sunday early", CBS, _CREW_CBS, flags="C"),
        g(2025, 2, "2025-09-14", "13:00", 0, 3, "Sunday early", FOX, _CREW_FOX_O1, booth="o1"),
        g(
            2025,
            3,
            "2025-09-21",
            "16:25",
            5,
            1,
            "Sunday late",
            FOX,
            _CREW_FILL,
            flags="A",
            booth="lead",
        ),
        g(2025, 4, "2025-09-28", "09:30", 0, 2, "International", ESPN, _CREW_ESPN, flags="SI"),
        g(
            2025,
            5,
            "2025-10-05",
            "16:25",
            4,
            3,
            "Sunday late",
            FOX,
            _LEAD[2025],
            flags="AF",
            booth="lead",
            original=("Sunday early", CBS, "https://example.com/wiki/2025-week-5-flex"),
        ),
        g(
            2025,
            6,
            "2025-10-12",
            "13:00",
            1,
            4,
            "Sunday early",
            FOX,
            _CREW_FOX_O2,
            booth="o2",
            viewers=False,
            cause="regional",
        ),
        g(2025, 7, "2025-10-19", "20:20", 0, 4, "SNF", NBC, _CREW_NBC, flags="S", sideline=5),
        g(
            2025,
            8,
            "2025-10-26",
            "16:25",
            3,
            2,
            "Sunday late",
            FOX,
            _LEAD[2025],
            flags="A",
            booth="lead",
        ),
        g(2025, 4, "2025-09-29", "20:15", 1, 3, "MNF", ABC, _CREW_ESPN),
        g(2025, 9, "2025-11-02", "13:00", 0, 3, "Sunday early", CBS, _CREW_CBS2),
        g(2025, 9, "2025-11-03", "20:15", 5, 0, "MNF", ESPN, _CREW_ESPN, flags="S"),
        g(2025, 10, "2025-11-09", "13:00", 2, 1, "Sunday early", CBS, _CREW_CBS, flags="C"),
        g(2025, 11, "2025-11-16", "13:00", 5, 2, "Sunday early", FOX, _CREW_FILL, booth="pool"),
        g(
            2025,
            12,
            "2025-11-23",
            "16:25",
            1,
            3,
            "Sunday late",
            FOX,
            _LEAD[2025],
            flags="A",
            booth="lead",
        ),
        g(2025, 13, "2025-11-27", "12:30", 4, 5, "Thanksgiving", CBS, _CREW_CBS, flags="S"),
        g(2025, 14, "2025-12-07", "13:00", 0, 2, "Sunday early", FOX, _CREW_FOX_O2, booth="o2"),
        g(
            2025,
            16,
            "2025-12-20",
            "16:30",
            5,
            4,
            "Saturday",
            ESPN,
            _CREW_ESPN,
            flags="S",
            exc=False,
        ),
        g(2025, 14, "2025-12-05", "20:15", 3, 1, "Friday", NFLN, None, flags="S"),
        g(2025, 17, "2025-12-25", "16:30", 1, 0, "Christmas", PRIME, _CREW_PRIME, flags="S"),
        g(2025, 17, "2025-12-25", "20:15", 3, 0, "Christmas", NETFLIX, _CREW_NETFLIX, flags="S"),
        # 2026, in progress through week 3
        g(2026, 1, "2026-09-10", "20:20", 2, 3, "TNF", NBC, _CREW_NBC, flags="S"),
        g(
            2026,
            1,
            "2026-09-13",
            "16:25",
            0,
            1,
            "Sunday late",
            FOX,
            _LEAD[2026],
            flags="A",
            booth="lead",
        ),
        g(2026, 2, "2026-09-20", "13:00", 0, 3, "Other", PEACOCK, _CREW_NBC, flags="S"),
        g(
            2026,
            2,
            "2026-09-20",
            "20:20",
            1,
            4,
            "SNF",
            NBC,
            _CREW_NBC,
            flags="S",
            lineup=True,
        ),
        g(
            2026,
            3,
            "2026-09-27",
            "20:20",
            0,
            2,
            "SNF",
            NBC,
            _CREW_NBC,
            flags="S",
            lineup=True,
            viewers=False,
            cause="pending",
        ),
        g(
            2026,
            2,
            "2026-09-20",
            "16:25",
            4,
            5,
            "Sunday late",
            FOX,
            _LEAD[2026],
            flags="A",
            booth="lead",
        ),
        g(
            2026,
            3,
            "2026-09-27",
            "13:00",
            1,
            2,
            "Sunday early",
            CBS,
            _CREW_CBS,
            flags="C",
            viewers=False,
            cause="pending",
        ),
        g(
            2026,
            4,
            "2026-10-04",
            "16:25",
            3,
            0,
            "Sunday late",
            FOX,
            _LEAD[2026],
            flags="A",
            booth="lead",
            played=False,
            cause="pending",
        ),
        g(
            2026,
            4,
            "2026-10-04",
            "20:20",
            5,
            1,
            "SNF",
            NBC,
            None,
            flags="S",
            played=False,
            cause="pending",
            no_kickoff=True,
        ),
    ]


def _points(i: int, tie: bool) -> tuple[int, int]:
    home = 17 + (i * 7) % 14
    away = home if tie else 14 + (i * 5) % 15
    if not tie and away == home:
        away += 1
    return home, away


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _team_name_index(franchise: int, season: int) -> int:
    return 6 if franchise == 0 and season == 2024 else franchise


def _games_block(specs: list[dict[str, Any]], person_roles: dict[int, str]) -> dict[str, list[Any]]:
    cols: dict[str, list[Any]] = {name: [] for name in NflGameColumns.model_fields}
    for i, s in enumerate(specs):
        hp = ap = margin = None
        if s["played"]:
            hp, ap = _points(i, s["tie"])
            margin = hp - ap
        crew: list[dict[str, Any]] = []
        if s["crew"] is not None:
            pbp, analyst = s["crew"]
            crew = [
                {"person": pbp, "role": person_roles[pbp]},
                {"person": analyst, "role": person_roles[analyst]},
            ]
        if s["sideline"] is not None:
            crew.append({"person": s["sideline"], "role": "unknown"})
        rated = s["viewers"]
        original = s["original"]
        values: dict[str, Any] = {
            "season": s["season"],
            "week": s["week"],
            "date": s["date"],
            "kickoff": s["kickoff"],
            "home": s["home"],
            "away": s["away"],
            "home_name": _team_name_index(s["home"], s["season"]),
            "away_name": _team_name_index(s["away"], s["season"]),
            "home_points": hp,
            "away_points": ap,
            "final_margin": margin,
            "slot": SLOT[s["slot"]],
            "standalone": "S" in s["flags"],
            "agotw": "A" in s["flags"],
            "cbs_national": "C" in s["flags"],
            "international": "I" in s["flags"],
            "flexed": "F" in s["flags"],
            "original_slot": SLOT[original[0]] if original else None,
            "original_network": original[1] if original else None,
            "change_url": original[2] if original else None,
            "network": s["network"],
            "crew": crew,
            "crew_source": (("published_lineup" if s["lineup"] else "506") if crew else None),
            "crew_source_url": LINEUP_URL if crew and s["lineup"] else None,
            "excitement": round(2.0 + (i * 37 % 17) / 10, 2) if s["exc"] else None,
            "viewers": 8_000_000 + 350_000 * i if rated else None,
            "scope": ("window" if s["slot"].startswith("Sunday") else "game") if rated else None,
            "era": (0 if s["season"] == 2024 else 1) if rated else None,
            "rr_url": f"https://example.com/rr/{i}" if rated else None,
            "source_url": f"https://example.com/src/{i}" if rated else None,
            "cause": None if rated else (s["cause"] or "none"),
            "place": PLACE_CYCLE[i % len(PLACE_CYCLE)],
        }
        for name, value in values.items():
            cols[name].append(value)
    return cols


def _upcoming_block(person_roles: dict[int, str]) -> dict[str, list[Any]]:
    """Week 5 of 2026 as the This weekend tab sees it (Phase 18): four CBS 1:00 games (two
    with crews of booth rank 1 and 2), two FOX 4:25 games, one slot-table SNF game, one
    game with no kickoff yet, one with no network yet and one neutral-site game."""
    # (day|None, hhmm|None, home, away, slot, network|None, basis, crew, rank, neutral)
    rows: list[tuple[Any, ...]] = [
        ("2026-10-11", "13:00", 0, 1, "Sunday early", CBS, "506", _CREW_CBS, 1, False),
        ("2026-10-11", "13:00", 2, 3, "Sunday early", CBS, "506", _CREW_CBS2, 2, False),
        ("2026-10-11", "13:00", 4, 5, "Sunday early", CBS, "506", None, None, False),
        ("2026-10-11", "13:00", 3, 0, "Sunday early", CBS, "506", None, None, False),
        ("2026-10-11", "16:25", 5, 2, "Sunday late", FOX, "506", None, None, False),
        ("2026-10-11", "16:25", 1, 4, "Sunday late", FOX, "506", None, None, False),
        ("2026-10-11", "20:20", 3, 5, "SNF", NBC, "slot", None, None, False),
        ("2026-10-11", None, 1, 5, None, CBS, "506", None, None, False),
        ("2026-10-11", "13:00", 2, 0, "Sunday early", None, None, None, None, False),
        ("2026-10-11", "09:30", 4, 3, "International", NFLN, "506", None, None, True),
    ]
    cols: dict[str, list[Any]] = {name: [] for name in NflUpcomingColumns.model_fields}
    for day, hhmm, home, away, slot, network, basis, crew, rank, neutral in rows:
        kickoff = None
        if hhmm is not None:
            hour, minute = (int(x) for x in hhmm.split(":"))
            y, m, d = (int(x) for x in day.split("-"))
            kickoff = datetime(y, m, d, hour, minute, tzinfo=_ET).isoformat()
        entries = [] if crew is None else [{"person": p, "role": person_roles[p]} for p in crew]
        values: dict[str, Any] = {
            "season": 2026,
            "week": 5,
            "date": day,
            "kickoff": kickoff,
            "home": home,
            "away": away,
            "home_name": _team_name_index(home, 2026),
            "away_name": _team_name_index(away, 2026),
            "slot": None if slot is None else SLOT[slot],
            "international": slot == "International",
            "neutral": neutral,
            "network": network,
            "network_basis": basis,
            "crew": entries,
            "crew_source": "506" if entries else None,
            "crew_source_url": LINEUP_URL if entries else None,
            "booth_rank": rank,
            "place": UPCOMING_PLACE_CYCLE[len(cols["season"]) % len(UPCOMING_PLACE_CYCLE)],
        }
        for name in cols:
            cols[name].append(values[name])
    return cols


def _special_block(
    specs: list[dict[str, Any]], weeks: dict[int, dict[str, int]]
) -> dict[str, list[Any]]:
    slot_suffix = {
        "Christmas": "christmas",
        "Thanksgiving": "thanksgiving",
        "Black Friday": "black_friday",
        "International": "international",
        "TNF": "tnf",
        "SNF": "snf",
        "MNF": "mnf",
        "Saturday": "saturday",
        "Friday": "friday",
        "Sunday early": "sunday_early",
        "Sunday late": "sunday_late",
        "Other": "other",
    }
    rows: dict[tuple[int, int], dict[str, Any]] = {}
    for s in specs:
        for franchise in (s["home"], s["away"]):
            row = rows.setdefault((franchise, s["season"]), _empty_special(franchise, s["season"]))
            row["games"] += 1
            flags = s["flags"]
            # Exclusive precedence: standalone, then AGOTW, then CBS national.
            if "S" in flags:
                row["standalone_total"] += 1
                row[f"standalone_{slot_suffix[s['slot']]}"] += 1
            elif "A" in flags:
                row["agotw"] += 1
            elif "C" in flags:
                row["cbs_national"] += 1
            if "I" in flags:
                row["international"] += 1
                if not set(flags) & set("SAC"):
                    row["international_other"] += 1
            if "F" in flags:
                row["flexed"] += 1
    ordered = [rows[key] for key in sorted(rows, key=lambda k: (k[0], k[1]))]
    for row in ordered:
        row["special"] = row["standalone_total"] + row["agotw"] + row["cbs_national"]
        w = weeks[row["season"]]
        fox_den = w["fox_doubleheader_weeks"] - w["fox_ambiguous_weeks"]
        cbs_den = w["cbs_doubleheader_weeks"] - w["cbs_ambiguous_weeks"]
        row["agotw_rate"] = round(row["agotw"] / fox_den, 4) if fox_den > 0 else None
        row["cbs_national_rate"] = round(row["cbs_national"] / cbs_den, 4) if cbs_den > 0 else None
    for row in ordered:
        row["solo_thursday"] = row["standalone_tnf"]
        row["solo_sunday"] = row["standalone_snf"]
        row["solo_monday"] = row["standalone_mnf"]
        row["solo_holiday"] = (
            row["standalone_christmas"]
            + row["standalone_thanksgiving"]
            + row["standalone_black_friday"]
        )
        row["solo_other"] = row["standalone_total"] - (
            row["solo_thursday"] + row["solo_sunday"] + row["solo_monday"] + row["solo_holiday"]
        )
    names = list(ordered[0])
    return {name: [row[name] for row in ordered] for name in names}


def _empty_special(franchise: int, season: int) -> dict[str, Any]:
    row: dict[str, Any] = {"franchise": franchise, "season": season, "games": 0}
    row["standalone_total"] = 0
    for suffix in _SLOT_SUFFIXES:
        row[f"standalone_{suffix}"] = 0
    for name in ("solo_thursday", "solo_sunday", "solo_monday", "solo_holiday", "solo_other"):
        row[name] = 0
    for name in (
        "agotw",
        "cbs_national",
        "international",
        "international_other",
        "flexed",
        "special",
    ):
        row[name] = 0
    row["agotw_rate"] = None
    row["cbs_national_rate"] = None
    return row


# (season, group id, rank, rank_source, people, booth tag, fill_in_games)
_BOOTH_LAYOUT: list[tuple[int, str, int, str, tuple[int, int], str, int]] = [
    (2024, "fox", 1, "inferred", _LEAD[2024], "fox:lead", 0),
    (2024, "fox", 2, "inferred", _CREW_FOX_O1, "fox:o1", 0),
    (2024, "fox", 3, "inferred", _CREW_FOX_O2, "fox:o2", 0),
    (2025, "fox", 1, "published", _LEAD[2025], "fox:lead", 1),
    (2025, "fox", 2, "published", _CREW_FOX_O1, "fox:o1", 0),
    (2025, "fox", 3, "published", _CREW_FOX_O2, "fox:o2", 0),
    # The newest season is in progress: published ranks, one booth with no games yet.
    (2026, "fox", 1, "published", _LEAD[2026], "fox:lead", 0),
    (2026, "fox", 2, "published", _CREW_FOX_O1, "fox:o1", 0),
    # No lead is known for CBS 2024 (D-23): ranked by games called, none labeled Lead.
    (2024, "cbs", 1, "games", _CREW_CBS, "cbs:b1", 0),
    (2024, "cbs", 2, "games", _CREW_CBS2, "cbs:b2", 0),
    (2025, "cbs", 1, "override", _CREW_CBS, "cbs:b1", 0),
    (2025, "cbs", 2, "override", _CREW_CBS2, "cbs:b2", 0),
    (2026, "cbs", 1, "override", _CREW_CBS, "cbs:b1", 0),
    (2024, "nbc", 1, "published", _CREW_NBC, "nbc:b1", 0),
    (2025, "nbc", 1, "published", _CREW_NBC, "nbc:b1", 0),
    (2026, "nbc", 1, "published", _CREW_NBC, "nbc:b1", 0),
    (2024, "espn_abc", 1, "published", _CREW_ESPN, "espn_abc:b1", 0),
    (2025, "espn_abc", 1, "published", _CREW_ESPN, "espn_abc:b1", 0),
    (2024, "prime", 1, "published", _CREW_PRIME, "prime:b1", 0),
    (2025, "prime", 1, "published", _CREW_PRIME, "prime:b1", 0),
    (2025, "netflix", 1, "published", _CREW_NETFLIX, "netflix:b1", 0),
]

_NON_FOX_BOOTH = {
    _CREW_CBS: "cbs:b1",
    _CREW_CBS2: "cbs:b2",
    _CREW_NBC: "nbc:b1",
    _CREW_ESPN: "espn_abc:b1",
    _CREW_PRIME: "prime:b1",
    _CREW_NETFLIX: "netflix:b1",
}


def _booth_tag(s: dict[str, Any]) -> str | None:
    """The booth row a game belongs to; fill-in-only Fox games belong to none."""
    if s["network"] == FOX:
        return f"fox:{s['booth']}" if s["booth"] in ("lead", "o1", "o2") else None
    return _NON_FOX_BOOTH.get(s["crew"]) if s["crew"] is not None else None


def _is_flagship(group: str, s: dict[str, Any]) -> bool:
    flags, slot = s["flags"], s["slot"]
    return {
        "fox": "A" in flags,
        "cbs": "C" in flags,
        "nbc": slot == "SNF",
        "espn_abc": slot == "MNF",
        "prime": slot == "TNF",
    }.get(group, False)


def _booth_rows(specs: list[dict[str, Any]], games: dict[str, list[Any]]) -> dict[str, list[Any]]:
    group_index = {gid: i for i, (gid, *_rest) in enumerate(NETWORK_GROUPS)}
    out: dict[str, list[Any]] = {name: [] for name in NflBoothColumns.model_fields}
    for k, (season, group, rank, source, people, tag, fill_in) in enumerate(_BOOTH_LAYOUT):
        idx = [i for i, s in enumerate(specs) if s["season"] == season and _booth_tag(s) == tag]
        margins = [
            abs(games["final_margin"][i]) for i in idx if games["final_margin"][i] is not None
        ]
        excs = [games["excitement"][i] for i in idx if games["excitement"][i] is not None]
        viewers = [float(games["viewers"][i]) for i in idx if games["viewers"][i] is not None]
        n_m, n_e = len(margins), len(excs)
        adj = k % 5 - 2

        def resid(n: int, scale: float, adj: int = adj) -> float | None:
            return round(adj * scale, 3) if n else None

        def se(n: int, base: float) -> float | None:
            return round(base / max(n, 1) ** 0.5, 3) if n else None

        row = {
            "season": season,
            "network_group": group_index[group],
            "rank": rank,
            "rank_source": source,
            "is_lead": rank == 1 and source != "games",
            "pbp_person": people[0],
            "analyst_person": people[1],
            "games": len(idx),
            "flagship_games": sum(1 for i in idx if _is_flagship(group, specs[i])),
            "fill_in_games": fill_in,
            "lineup_games": sum(1 for i in idx if specs[i]["lineup"]),
            "raw_n_margin": n_m,
            "raw_n_excitement": n_e,
            "raw_n_viewers": len(viewers),
            "raw_mean_abs_margin": _mean(margins),
            "raw_mean_excitement": _mean(excs),
            "raw_mean_viewers": _mean(viewers),
            "adj_n_margin": n_m,
            "adj_n_excitement": n_e,
            "adj_margin_resid": resid(n_m, 0.9),
            "adj_margin_se": se(n_m, 3.0),
            "adj_excitement_resid": resid(n_e, 0.15),
            "adj_excitement_se": se(n_e, 0.5),
            "low_n": len(idx) < 2,
            "game_list": idx,
        }
        for name, value in row.items():
            out[name].append(value)
    return out


_CATEGORY_BY_SLOT = {
    "SNF": "snf",
    "MNF": "mnf",
    "TNF": "tnf",
    "Thanksgiving": "thanksgiving",
    "Christmas": "christmas",
    "Black Friday": "black_friday",
    "International": "international",
    "Saturday": "saturday",
    "Friday": "friday",
    "Other": "other",
}


def _view_category(s: dict[str, Any]) -> str | None:
    if "A" in s["flags"]:
        return "agotw"
    if "C" in s["flags"]:
        return "cbs_national"
    return _CATEGORY_BY_SLOT.get(s["slot"])


def _viewership_rows(
    specs: list[dict[str, Any]], games: dict[str, list[Any]]
) -> dict[str, list[Any]]:
    cat_index = {cid: i for i, (cid, _label, _w) in enumerate(NFL_VIEW_CATEGORIES)}
    members: dict[tuple[int, int], list[int]] = {}
    for i, s in enumerate(specs):
        cat = _view_category(s)
        if cat is not None and games["viewers"][i] is not None:
            members.setdefault((cat_index[cat], s["season"]), []).append(i)
    out: dict[str, list[Any]] = {name: [] for name in NflViewershipColumns.model_fields}
    for k, (key, idx) in enumerate(sorted(members.items())):
        cat_i, season = key
        cat = NFL_VIEW_CATEGORIES[cat_i][0]
        n = len(idx)
        resid: float | None = round((k % 5 - 2) * 110000.0, 1)
        se: float | None = round(300000.0 / n**0.5, 1)
        low_n = n < 2
        if cat == "christmas":
            resid, se, low_n = None, None, True
        elif cat == "thanksgiving":
            low_n = True
        elif cat == "agotw" and season == 2026:
            resid, se, low_n = None, None, True
        row = {
            "category": cat_i,
            "season": season,
            "era": 0 if season == 2024 else 1,
            "games": n,
            "mean_viewers": _mean([float(games["viewers"][i]) for i in idx]),
            "viewership_resid": resid,
            "viewership_se": se,
            "low_n": low_n,
            "game_list": idx,
        }
        for name, value in row.items():
            out[name].append(value)
    return out


def build_fixture() -> dict[str, Any]:
    """The full synthetic payload, validated against the contract."""
    specs = sorted(_specs(), key=lambda s: (s["date"], s["kickoff"] or "", s["home"]))
    # Roles by person: first-named crew slot is play-by-play, second analyst.
    person_roles = {p: "pbp" for p in (0, 2, 4, 6, 8, 10, 12, 13, 15)}
    person_roles.update({p: "analyst" for p in (1, 3, 5, 7, 9, 11, 14, 16)})
    weeks = {
        2024: {
            "fox_doubleheader_weeks": 8,
            "fox_ambiguous_weeks": 0,
            "cbs_doubleheader_weeks": 8,
            "cbs_ambiguous_weeks": 1,
        },
        2025: {
            "fox_doubleheader_weeks": 9,
            "fox_ambiguous_weeks": 1,
            "cbs_doubleheader_weeks": 9,
            "cbs_ambiguous_weeks": 0,
        },
        2026: {
            "fox_doubleheader_weeks": 0,
            "fox_ambiguous_weeks": 0,
            "cbs_doubleheader_weeks": 0,
            "cbs_ambiguous_weeks": 0,
        },
    }
    games = _games_block(specs, person_roles)
    payload: dict[str, Any] = {
        "schema_version": "2.2.0",
        "freshness": {
            "season": 2026,
            "in_progress": True,
            "through_week": 3,
            "viewership_through_week": 2,
            "crews_default_season": 2025,
            "weekend": {
                "week": 5,
                "schedule_updated_at": "2026-10-09T21:30:00Z",
                "crews_506_saved_at": "2026-10-06T02:14:00Z",
            },
        },
        "constants": {
            "viewership_scope": "window",
            "coverage_normalized": False,
            "excitement_method": "GEI-style",
            "low_n_threshold": LOW_N_THRESHOLD,
        },
        "lookups": {
            "franchises": [{"id": i, "name": n} for i, n in FRANCHISES],
            "team_names": [{"name": n, "short": sh} for n, sh in TEAM_NAMES],
            "networks": [{"id": i, "name": n, "family": fam} for i, n, fam in NETWORKS],
            "network_groups": [
                {"id": i, "name": n, "flagship": flag, "members": members}
                for i, n, flag, members in NETWORK_GROUPS
            ],
            "view_categories": [
                {"id": i, "label": label, "window_level": w} for i, label, w in NFL_VIEW_CATEGORIES
            ],
            "people": [{"id": f"p{k:02d}", "name": n} for k, n in enumerate(PEOPLE)],
            "venues": VENUES,
            "eras": [
                {"id": i, "label": label, "start": start, "end": end, "source_url": url}
                for i, label, start, end, url in ERAS
            ],
            "slots": list(NFL_SLOTS),
        },
        "games": games,
        "upcoming": _upcoming_block(person_roles),
        "special": _special_block(specs, weeks),
        "season_weeks": {
            "season": list(weeks),
            **{
                name: [weeks[s][name] for s in weeks]
                for name in (
                    "fox_doubleheader_weeks",
                    "fox_ambiguous_weeks",
                    "cbs_doubleheader_weeks",
                    "cbs_ambiguous_weeks",
                )
            },
        },
        "booths": _booth_rows(specs, games),
        "viewership": _viewership_rows(specs, games),
    }
    validate_nfl_site_data(payload)
    return payload


def render(obj: dict[str, Any]) -> str:
    return json.dumps(obj, indent=1, sort_keys=True) + "\n"


def main() -> int:
    FIXTURE_PATH.write_text(render(build_fixture()))
    print(f"wrote {FIXTURE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
