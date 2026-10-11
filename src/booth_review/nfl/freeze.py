"""NFL completeness and freeze (D-11), kept apart from the CFB audit.

`audit.completeness.SOURCES` and `audit.freeze` are untouched: this module
checks the NFL inputs of a season itself and merges only `nfl_*` keys into
ledger/frozen.json. A season freezes on or after `nfl_freeze_date` (March 1
after the season). The freeze also records a digest of the season's schedule
rows so later drift in the living games.csv is detectable.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from booth_review.audit.freeze import _load_frozen
from booth_review.config import DataPaths
from booth_review.nfl.layout import (
    NFL_SOURCES,
    NFLVERSE_SCHEDULES_PATH,
    nfl_506_path,
    nfl_rr_path,
    nflverse_pbp_path,
    wikipedia_path,
)
from booth_review.nfl.schedule import parse_schedules
from booth_review.nfl.seasons import nfl_freeze_date
from booth_review.sources.sports506.importer import NFL_PROFILE
from booth_review.sources.sports506.nfl_parser import nfl_smoke_check
from booth_review.transport.cache import atomic_write_json

_WAIVER_RE = re.compile(r"^(\d{4}):([a-z0-9_]+)$")
_TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"
FREEZE_RECORD = "nfl_freeze.json"


@dataclass(frozen=True)
class NflCompleteness:
    """Whether `season`'s NFL inputs are all present; `reasons` maps each failing source."""

    season: int
    ok: bool
    reasons: Mapping[str, str]
    evidence: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class NflFreezeResult:
    frozen: tuple[int, ...]
    refused: Mapping[int, str]
    written: tuple[str, ...]
    waived: tuple[str, ...] = ()


def parse_nfl_waiver(text: str) -> tuple[int, str]:
    """Parse "SEASON:source" (e.g. "2015:nfl_wikipedia"); source must be an NFL source."""
    match = _WAIVER_RE.match(text)
    if match is None:
        raise argparse.ArgumentTypeError(f"invalid waiver (expected SEASON:source): {text!r}")
    if match.group(2) not in NFL_SOURCES:
        raise argparse.ArgumentTypeError(f"unknown source in waiver: {match.group(2)!r}")
    return int(match.group(1)), match.group(2)


def _season_rows(paths: DataPaths, season: int) -> list[str]:
    """The season's games.csv rows (header excluded), re-serialized one per line."""
    source = paths.raw / NFLVERSE_SCHEDULES_PATH
    if not source.is_file():
        return []
    reader = csv.reader(io.StringIO(source.read_text(encoding="utf-8"), newline=""))
    header = next(reader, None)
    if header is None or "season" not in header:
        return []
    index = header.index("season")
    rows: list[str] = []
    for row in reader:
        if len(row) > index and row[index] == str(season):
            out = io.StringIO()
            csv.writer(out, lineterminator="").writerow(row)
            rows.append(out.getvalue())
    return rows


def schedule_digest(paths: DataPaths, season: int) -> str:
    """sha256 over the season's schedule rows, sorted lexically and LF-joined."""
    return hashlib.sha256("\n".join(sorted(_season_rows(paths, season))).encode()).hexdigest()


def nfl_completeness(paths: DataPaths, season: int) -> NflCompleteness:
    reasons: dict[str, str] = {}
    evidence: dict[str, int] = {}

    # nfl_nflverse: schedule REG rows and the pbp file.
    schedule = paths.raw / NFLVERSE_SCHEDULES_PATH
    reg_rows = 0
    if schedule.is_file():
        reg_rows = sum(
            1
            for g in parse_schedules(schedule.read_bytes(), seasons=[season])
            if g.game_type == "REG"
        )
    evidence["nfl_nflverse"] = reg_rows
    if reg_rows == 0:
        reasons["nfl_nflverse"] = "no regular-season schedule rows"
    elif not (paths.raw / nflverse_pbp_path(season)).is_file():
        reasons["nfl_nflverse"] = "play-by-play file missing"

    # nfl_sports506: every expected week page present and passing the smoke check.
    expected = NFL_PROFILE.labels(season)
    good = 0
    absent: list[str] = []
    failing: list[str] = []
    for label in expected:
        page = paths.raw / nfl_506_path(season, int(label))
        if not page.is_file():
            absent.append(label)
        elif nfl_smoke_check(page.read_bytes(), season=season, week=int(label)).passed:
            good += 1
        else:
            failing.append(label)
    evidence["nfl_sports506"] = good
    if absent or failing:
        parts = []
        if absent:
            parts.append(f"missing weeks {', '.join(absent)}")
        if failing:
            parts.append(f"failed smoke check weeks {', '.join(failing)}")
        reasons["nfl_sports506"] = "; ".join(parts)

    # nfl_wikipedia: the season article.
    article = (paths.raw / wikipedia_path(season)).is_file()
    evidence["nfl_wikipedia"] = int(article)
    if not article:
        reasons["nfl_wikipedia"] = "season article missing"

    # nfl_ratingsref: at least one telecast record.
    rr_dir = (paths.raw / nfl_rr_path(season, "x")).parent
    records = len(list(rr_dir.glob("*.json"))) if rr_dir.is_dir() else 0
    evidence["nfl_ratingsref"] = records
    if records == 0:
        reasons["nfl_ratingsref"] = "no telecast records"

    return NflCompleteness(season, not reasons, reasons, evidence)


def _read_record(paths: DataPaths) -> dict[str, object]:
    path = paths.audit / FREEZE_RECORD
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def freeze_nfl_seasons(
    paths: DataPaths,
    seasons: Sequence[int],
    today: date,
    *,
    waivers: Sequence[tuple[int, str]] = (),
    dry_run: bool = False,
) -> NflFreezeResult:
    """Freeze `seasons` for the four `nfl_*` sources, all or nothing.

    A season is refused when `today` is before its freeze date or any source is
    incomplete and not waived. Any refusal writes nothing. Already-frozen
    seasons are skipped. CFB keys in frozen.json are never changed.
    """
    refused: dict[int, str] = {}
    waived = {w for w in waivers}
    for season, source in waivers:
        if season not in seasons:
            refused[season] = f"waiver {season}:{source} is not among the seasons being frozen"

    current = _load_frozen(paths.frozen)
    pending: list[NflCompleteness] = []
    used: list[str] = []
    for season in seasons:
        if all(season in current.get(source, []) for source in NFL_SOURCES):
            continue
        if today < nfl_freeze_date(season):
            refused[season] = f"not past its freeze date ({nfl_freeze_date(season)})"
            continue
        result = nfl_completeness(paths, season)
        bad = {s: r for s, r in result.reasons.items() if (season, s) not in waived}
        if bad:
            refused[season] = "; ".join(f"{s}: {r}" for s, r in sorted(bad.items()))
            continue
        used += [f"{season}:{s}" for s in sorted(result.reasons)]
        pending.append(result)

    if refused:
        return NflFreezeResult((), dict(refused), ())
    frozen = tuple(r.season for r in pending)
    if dry_run or not pending:
        return NflFreezeResult(frozen, {}, (), tuple(used))

    for source in NFL_SOURCES:
        current[source] = sorted(set(current.get(source, [])) | set(frozen))
    atomic_write_json(paths.frozen, current)

    record = _read_record(paths)
    digests = dict(record.get("schedule_digest") or {})  # type: ignore[call-overload]
    evidence = dict(record.get("evidence") or {})  # type: ignore[call-overload]
    for r in pending:
        digests[str(r.season)] = schedule_digest(paths, r.season)
        evidence[str(r.season)] = dict(r.evidence)
    prior_seasons = record.get("seasons") or []
    prior_waivers = record.get("waivers") or []
    atomic_write_json(
        paths.audit / FREEZE_RECORD,
        {
            "frozen_at": datetime(today.year, today.month, today.day, tzinfo=UTC).strftime(
                _TIME_FMT
            ),
            "seasons": sorted(set(prior_seasons) | set(frozen)),  # type: ignore[call-overload]
            "waivers": sorted(set(prior_waivers) | set(used)),  # type: ignore[call-overload]
            "evidence": evidence,
            "schedule_digest": digests,
        },
    )
    return NflFreezeResult(
        frozen, {}, ("ledger/frozen.json", f"audit/{FREEZE_RECORD}"), tuple(used)
    )


def schedule_drift(paths: DataPaths) -> list[int]:
    """Frozen seasons whose current schedule-row digest differs from the frozen one."""
    digests = _read_record(paths).get("schedule_digest")
    if not isinstance(digests, dict):
        return []
    return sorted(
        int(season)
        for season, digest in digests.items()
        if schedule_digest(paths, int(season)) != digest
    )
