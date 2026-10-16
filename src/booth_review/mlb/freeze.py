"""MLB completeness and freeze (D-22 as amended), kept apart from the CFB and NFL audits.

`audit.completeness.SOURCES` and `audit.freeze` are untouched. This module checks the
MLB inputs of a completed season itself and merges only `mlb_*` keys into
ledger/frozen.json. A season freezes on or after `mlb_freeze_date` (March 1 of the next
year, so the late Retrosheet release can still be collected). 2026 is never frozen in
this phase. The freeze also records a digest of the season's Retrosheet game-info rows,
so a later semi-annual Retrosheet re-issue that changes them is detectable; a person
who has checked the change accepts it with `--accept-drift`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from booth_review.audit.freeze import load_frozen
from booth_review.config import DataPaths
from booth_review.errors import ParseError
from booth_review.mlb.collect_cli import load_mlb_rr_windows
from booth_review.mlb.constants import MLB_CURRENT_SEASON
from booth_review.mlb.layout import (
    MLB_ROUNDS,
    MLB_SOURCES,
    mlb_506_path,
    mlb_rr_path,
    mlb_wikipedia_path,
    retrosheet_asset_path,
)
from booth_review.mlb.seasons import mlb_freeze_date
from booth_review.sources.retrosheet.loader import read_gameinfo
from booth_review.sources.sports506.mlb_parser import mlb_smoke_check
from booth_review.transport.cache import atomic_write_json

__all__ = [
    "FIRST_UNFROZEN_SEASON",
    "FREEZE_RECORD",
    "DriftAcceptResult",
    "MlbCompleteness",
    "MlbFreezeResult",
    "accept_retrosheet_drift",
    "freeze_mlb_seasons",
    "mlb_completeness",
    "parse_mlb_waiver",
    "retrosheet_digest",
    "retrosheet_drift",
]

_WAIVER_RE = re.compile(r"^(\d{4}):([a-z0-9_]+)$")
_TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"
FREEZE_RECORD = "mlb_freeze.json"
#: This phase never freezes the current season (D-22 as amended).
FIRST_UNFROZEN_SEASON = MLB_CURRENT_SEASON


@dataclass(frozen=True)
class MlbCompleteness:
    """Whether `season`'s MLB inputs are all present; `reasons` maps each failing source."""

    season: int
    ok: bool
    reasons: Mapping[str, str]
    evidence: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class MlbFreezeResult:
    frozen: tuple[int, ...]
    refused: Mapping[int, str]
    written: tuple[str, ...]
    waived: tuple[str, ...] = ()


def parse_mlb_waiver(text: str) -> tuple[int, str]:
    """Parse "SEASON:source" (e.g. "2016:mlb_wikipedia"); source must be an MLB source."""
    match = _WAIVER_RE.match(text)
    if match is None:
        raise argparse.ArgumentTypeError(f"invalid waiver (expected SEASON:source): {text!r}")
    if match.group(2) not in MLB_SOURCES:
        raise argparse.ArgumentTypeError(f"unknown source in waiver: {match.group(2)!r}")
    return int(match.group(1)), match.group(2)


def retrosheet_digest(paths: DataPaths, season: int) -> str:
    """sha256 over the season's game-info rows, sorted lexically and LF-joined."""
    bundle = paths.raw / retrosheet_asset_path(f"{season}csvs.zip")
    if not bundle.is_file():
        return hashlib.sha256(b"").hexdigest()
    try:
        frame = read_gameinfo(bundle.read_bytes())
    except ParseError:
        return hashlib.sha256(b"unreadable").hexdigest()
    rows = sorted(
        ",".join("" if v is None else str(v) for v in row)
        for row in frame.sort(frame.columns).iter_rows()
    )
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def mlb_completeness(paths: DataPaths, season: int) -> MlbCompleteness:
    reasons: dict[str, str] = {}
    evidence: dict[str, int] = {}

    bundle = (paths.raw / retrosheet_asset_path(f"{season}csvs.zip")).is_file()
    evidence["mlb_retrosheet"] = int(bundle)
    if not bundle:
        reasons["mlb_retrosheet"] = "season bundle missing"

    article = (paths.raw / mlb_wikipedia_path(season)).is_file()
    evidence["mlb_wikipedia"] = int(article)
    if not article:
        reasons["mlb_wikipedia"] = "season article missing"

    good = 0
    absent: list[str] = []
    failing: list[str] = []
    for label in MLB_ROUNDS:
        page = paths.raw / mlb_506_path(season, label)
        if not page.is_file():
            absent.append(label)
        elif mlb_smoke_check(page.read_bytes(), season=season, label=label) is None:
            good += 1
        else:
            failing.append(label)
    evidence["mlb_sports506"] = good
    if absent or failing:
        parts = []
        if absent:
            parts.append(f"missing rounds {', '.join(absent)}")
        if failing:
            parts.append(f"failed smoke check rounds {', '.join(failing)}")
        reasons["mlb_sports506"] = "; ".join(parts)

    rr_dir = (paths.raw / mlb_rr_path(season, "x")).parent
    records = len(list(rr_dir.glob("*.json"))) if rr_dir.is_dir() else 0
    evidence["mlb_ratingsref"] = records
    if load_mlb_rr_windows(paths) is None:
        reasons["mlb_ratingsref"] = "windows file missing (run mlb rr-backfill)"
    elif records == 0:
        reasons["mlb_ratingsref"] = "no telecast records"

    # The relay only covers the current season, so a completed season needs nothing.
    evidence["mlb_relay"] = 0
    return MlbCompleteness(season, not reasons, reasons, evidence)


def _read_record(paths: DataPaths) -> dict[str, object]:
    path = paths.audit / FREEZE_RECORD
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def freeze_mlb_seasons(
    paths: DataPaths,
    seasons: Sequence[int],
    today: date,
    *,
    waivers: Sequence[tuple[int, str]] = (),
    dry_run: bool = False,
) -> MlbFreezeResult:
    """Freeze `seasons` for the five `mlb_*` sources, all or nothing.

    A season is refused when it is 2026 or later, `today` is before its freeze date,
    or any source is incomplete and not waived. Any refusal writes nothing.
    Already-frozen seasons are skipped. Keys of other leagues are never changed.
    """
    refused: dict[int, str] = {}
    waived = set(waivers)
    for season, source in waivers:
        if season not in seasons:
            refused[season] = f"waiver {season}:{source} is not among the seasons being frozen"

    current = load_frozen(paths.frozen)
    pending: list[MlbCompleteness] = []
    used: list[str] = []
    for season in seasons:
        if all(season in current.get(source, []) for source in MLB_SOURCES):
            continue
        if season >= FIRST_UNFROZEN_SEASON:
            refused[season] = "the current season is not frozen in this phase"
            continue
        if today < mlb_freeze_date(season):
            refused[season] = f"not past its freeze date ({mlb_freeze_date(season)})"
            continue
        result = mlb_completeness(paths, season)
        bad = {s: r for s, r in result.reasons.items() if (season, s) not in waived}
        if bad:
            refused[season] = "; ".join(f"{s}: {r}" for s, r in sorted(bad.items()))
            continue
        used += [f"{season}:{s}" for s in sorted(result.reasons)]
        pending.append(result)

    if refused:
        return MlbFreezeResult((), dict(refused), ())
    frozen = tuple(r.season for r in pending)
    if dry_run or not pending:
        return MlbFreezeResult(frozen, {}, (), tuple(used))

    for source in MLB_SOURCES:
        current[source] = sorted(set(current.get(source, [])) | set(frozen))
    atomic_write_json(paths.frozen, current)

    record = _read_record(paths)
    digests = dict(record.get("retrosheet_digest") or {})  # type: ignore[call-overload]
    evidence = dict(record.get("evidence") or {})  # type: ignore[call-overload]
    for r in pending:
        digests[str(r.season)] = retrosheet_digest(paths, r.season)
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
            "retrosheet_digest": digests,
        },
    )
    return MlbFreezeResult(
        frozen, {}, ("ledger/frozen.json", f"audit/{FREEZE_RECORD}"), tuple(used)
    )


def retrosheet_drift(paths: DataPaths) -> list[int]:
    """Frozen seasons whose current Retrosheet digest differs from the frozen one."""
    digests = _read_record(paths).get("retrosheet_digest")
    if not isinstance(digests, dict):
        return []
    return sorted(
        int(season)
        for season, digest in digests.items()
        if retrosheet_digest(paths, int(season)) != digest
    )


@dataclass(frozen=True)
class DriftAcceptResult:
    accepted: tuple[int, ...]
    unchanged: tuple[int, ...]
    not_frozen: tuple[int, ...]
    written: tuple[str, ...]


def accept_retrosheet_drift(
    paths: DataPaths, seasons: Sequence[int], today: date, *, dry_run: bool = False
) -> DriftAcceptResult:
    """Re-record the digest of frozen `seasons` whose Retrosheet rows drifted.

    Run after checking the drift (`--check-drift`) and deciding the re-issued rows are
    right. A season with no frozen digest refuses the whole call and writes nothing.
    Each accepted season gets its date under `drift_accepted` in the freeze record.
    """
    record = _read_record(paths)
    digests = dict(record.get("retrosheet_digest") or {})  # type: ignore[call-overload]
    not_frozen = tuple(s for s in seasons if str(s) not in digests)
    if not_frozen:
        return DriftAcceptResult((), (), not_frozen, ())
    accepted: list[int] = []
    unchanged: list[int] = []
    for season in seasons:
        current = retrosheet_digest(paths, season)
        if current == digests[str(season)]:
            unchanged.append(season)
        else:
            digests[str(season)] = current
            accepted.append(season)
    if dry_run or not accepted:
        return DriftAcceptResult(tuple(accepted), tuple(unchanged), (), ())
    stamp = datetime(today.year, today.month, today.day, tzinfo=UTC).strftime(_TIME_FMT)
    history = dict(record.get("drift_accepted") or {})  # type: ignore[call-overload]
    for season in accepted:
        history[str(season)] = [*history.get(str(season), []), stamp]
    atomic_write_json(
        paths.audit / FREEZE_RECORD,
        {**record, "retrosheet_digest": digests, "drift_accepted": history},
    )
    return DriftAcceptResult(tuple(accepted), tuple(unchanged), (), (f"audit/{FREEZE_RECORD}",))
