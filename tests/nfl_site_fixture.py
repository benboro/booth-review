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
    NflAgotwColumns,
    NflBoothColumns,
    NflGameColumns,
    validate_nfl_site_data,
)

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
NETWORKS = [("fox", "Fox"), ("cbs", "CBS"), ("nbc", "NBC"), ("espn", "ESPN"), ("prime", "Prime")]
FOX, CBS, NBC, ESPN, PRIME = range(5)
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
        g(2025, 17, "2025-12-25", "16:30", 1, 0, "Christmas", PRIME, _CREW_PRIME, flags="S"),
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
            "excitement": round(2.0 + (i * 37 % 17) / 10, 2) if s["exc"] else None,
            "viewers": 8_000_000 + 350_000 * i if rated else None,
            "scope": ("window" if s["slot"].startswith("Sunday") else "game") if rated else None,
            "era": (0 if s["season"] == 2024 else 1) if rated else None,
            "rr_url": f"https://example.com/rr/{i}" if rated else None,
            "source_url": f"https://example.com/src/{i}" if rated else None,
            "cause": None if rated else (s["cause"] or "none"),
        }
        for name, value in values.items():
            cols[name].append(value)
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
    names = list(ordered[0])
    return {name: [row[name] for row in ordered] for name in names}


def _empty_special(franchise: int, season: int) -> dict[str, Any]:
    row: dict[str, Any] = {"franchise": franchise, "season": season, "games": 0}
    row["standalone_total"] = 0
    for suffix in _SLOT_SUFFIXES:
        row[f"standalone_{suffix}"] = 0
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


def _booth_rows(specs: list[dict[str, Any]], games: dict[str, list[Any]]) -> dict[str, list[Any]]:
    layout = [
        ("lead", 1, "lead"),
        ("other", 2, "o1"),
        ("other", 3, "o2"),
        ("others_pooled", None, "pool"),
    ]
    people_by_booth = {"o1": _CREW_FOX_O1, "o2": _CREW_FOX_O2}
    fill_ins = {(2025, "lead"): 1}
    out: dict[str, list[Any]] = {name: [] for name in NflBoothColumns.model_fields}
    k = 0
    for season in (2024, 2025):
        for group, rank, tag in layout:
            idx = [i for i, s in enumerate(specs) if s["season"] == season and s["booth"] == tag]
            pbp, analyst = (
                _LEAD[season] if tag == "lead" else people_by_booth.get(tag, (None, None))
            )
            margins = [
                abs(games["final_margin"][i]) for i in idx if games["final_margin"][i] is not None
            ]
            excs = [games["excitement"][i] for i in idx if games["excitement"][i] is not None]
            vols = [round(e * 0.5, 4) for e in excs] if tag != "pool" else []
            n_m, n_e, n_v = len(margins), len(excs), len(vols)
            adj = k % 5 - 2

            def resid(n: int, scale: float, adj: int = adj) -> float | None:
                return round(adj * scale, 3) if n else None

            def se(n: int, base: float) -> float | None:
                return round(base / max(n, 1) ** 0.5, 3) if n else None

            row = {
                "season": season,
                "group": group,
                "rank": rank,
                "pbp_person": pbp,
                "analyst_person": analyst,
                "games": len(idx),
                "fill_in_games": fill_ins.get((season, tag), 0),
                "raw_n_margin": n_m,
                "raw_n_excitement": n_e,
                "raw_n_volatility": n_v,
                "raw_mean_abs_margin": _mean(margins),
                "raw_mean_excitement": _mean(excs),
                "raw_mean_volatility": _mean(vols),
                "adj_n_margin": n_m,
                "adj_n_excitement": n_e,
                "adj_n_volatility": n_v,
                "adj_margin_resid": resid(n_m, 0.9),
                "adj_margin_se": se(n_m, 3.0),
                "adj_excitement_resid": resid(n_e, 0.15),
                "adj_excitement_se": se(n_e, 0.5),
                "adj_volatility_resid": resid(n_v, 0.08),
                "adj_volatility_se": se(n_v, 0.3),
                "low_n": season == 2024 and tag == "o2",
                "game_list": idx,
            }
            for name, value in row.items():
                out[name].append(value)
            k += 1
    return out


def _agotw_rows(specs: list[dict[str, Any]], games: dict[str, list[Any]]) -> dict[str, list[Any]]:
    # season, resid, se, low_n, fill_in_games
    plan = [
        (2024, -310000.0, 240000.0, False, 0),
        (2025, 415000.0, 205000.0, False, 1),
        (2026, None, None, True, 0),
    ]
    out: dict[str, list[Any]] = {name: [] for name in NflAgotwColumns.model_fields}
    for season, resid, se, low_n, fill_in in plan:
        idx = [i for i, s in enumerate(specs) if s["season"] == season and s["booth"] == "lead"]
        viewers = [games["viewers"][i] for i in idx if games["viewers"][i] is not None]
        row = {
            "season": season,
            "era": 0 if season == 2024 else 1,
            "group": "lead",
            "pbp_person": _LEAD[season][0],
            "analyst_person": _LEAD[season][1],
            "games": len(idx),
            "fill_in_games": fill_in,
            "mean_viewers": _mean([float(v) for v in viewers]),
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
    person_roles = {p: "pbp" for p in (0, 2, 4, 6, 8, 10, 12)}
    person_roles.update({p: "analyst" for p in (1, 3, 5, 7, 9, 11)})
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
        "schema_version": "1.0.0",
        "freshness": {
            "season": 2026,
            "in_progress": True,
            "through_week": 3,
            "viewership_through_week": 2,
            "fox_default_season": 2025,
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
            "networks": [{"id": i, "name": n} for i, n in NETWORKS],
            "people": [{"id": f"p{k:02d}", "name": n} for k, n in enumerate(PEOPLE)],
            "eras": [
                {"id": i, "label": label, "start": start, "end": end, "source_url": url}
                for i, label, start, end, url in ERAS
            ],
            "slots": list(NFL_SLOTS),
        },
        "games": games,
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
        "fox_booths": _booth_rows(specs, games),
        "agotw_viewership": _agotw_rows(specs, games),
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
