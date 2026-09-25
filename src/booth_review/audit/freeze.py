"""D-06 freeze: writes ledger/frozen.json only after re-verifying completeness
and freeze dates itself, so an incomplete or too-early season can never be
frozen by accident (T-02-21).

`freeze_seasons` always (re)builds and persists the completeness report
(audit/completeness.json + .md) before checking it, so the report is fresh
evidence regardless of the freeze outcome -- but `ledger/frozen.json` and
`audit/freeze.json`, the one-way state, are written only when every
season x source cell is complete or explicitly waived.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from booth_review.audit.completeness import SOURCES, build_completeness, write_completeness
from booth_review.config import DataPaths
from booth_review.errors import FreezeRefusedError, VaultStateError
from booth_review.seasons import freeze_date, is_past_freeze_date
from booth_review.transport.cache import atomic_write_json

_WAIVER_RE = re.compile(r"^(\d{4}):([a-z0-9]+)$")


@dataclass(frozen=True)
class Waiver:
    """An explicit, per-season-per-source exception to the completeness bar."""

    season: int
    source: str


@dataclass
class FreezeResult:
    """The outcome of one freeze_seasons call."""

    seasons_added: list[int]
    already_frozen: list[int]
    waivers: list[Waiver]


def parse_waiver(text: str) -> Waiver:
    """Parse "SEASON:source" (e.g. "2020:sports506") into a Waiver.

    Raises argparse.ArgumentTypeError (never a bare ValueError) so this can
    be used directly as an argparse `type=`.
    """
    match = _WAIVER_RE.match(text)
    if match is None:
        raise argparse.ArgumentTypeError(f"invalid waiver (expected SEASON:source): {text!r}")
    season = int(match.group(1))
    source = match.group(2)
    if source not in SOURCES:
        raise argparse.ArgumentTypeError(f"unknown source in waiver: {source!r}")
    return Waiver(season=season, source=source)


def _load_frozen(path: Path) -> dict[str, list[int]]:
    """Load ledger/frozen.json, validated the same way FreezeGuard.load does."""
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
        raise VaultStateError(f"could not load frozen-season state from {path}") from exc
    if not isinstance(data, dict) or not all(
        isinstance(seasons, list) and all(isinstance(s, int) for s in seasons)
        for seasons in data.values()
    ):
        raise VaultStateError(f"invalid frozen-season state in {path}: expected {{str: [int]}}")
    return {source: list(seasons) for source, seasons in data.items()}


def freeze_seasons(
    paths: DataPaths,
    seasons: Sequence[int],
    *,
    today: date,
    waivers: Sequence[Waiver] = (),
    dry_run: bool = False,
) -> FreezeResult:
    """Freeze `seasons` in ledger/frozen.json for every source.

    Refuses (raises FreezeRefusedError, writes nothing to frozen.json or
    audit/freeze.json) when any season is not yet past its freeze date, or
    when any season x source cell is incomplete and not covered by a
    matching Waiver. Already-frozen seasons are a no-op.
    """
    for season in seasons:
        if not is_past_freeze_date(season, today):
            raise FreezeRefusedError(
                f"season {season} is not past its freeze date ({freeze_date(season)})"
            )

    now = datetime(today.year, today.month, today.day, tzinfo=UTC)
    report = build_completeness(paths, seasons, now=now)
    if not dry_run:
        write_completeness(paths, report)

    waived = {(waiver.season, waiver.source) for waiver in waivers}
    unwaived_incomplete = [
        cell for cell in report.incomplete_cells() if (cell.season, cell.source) not in waived
    ]
    if unwaived_incomplete:
        lines = []
        for cell in unwaived_incomplete:
            reason = f" ({'; '.join(cell.reasons)})" if cell.reasons else ""
            lines.append(f"{cell.season}:{cell.source}{reason}")
        raise FreezeRefusedError(
            f"{len(unwaived_incomplete)} incomplete season/source cell(s) not waived:\n"
            + "\n".join(lines)
        )

    current = _load_frozen(paths.frozen)
    for source in SOURCES:
        current.setdefault(source, [])

    already_frozen: list[int] = []
    seasons_added: list[int] = []
    for season in seasons:
        if all(season in current[source] for source in SOURCES):
            already_frozen.append(season)
        else:
            seasons_added.append(season)

    if not dry_run:
        merged = {source: sorted(set(values) | set(seasons)) for source, values in current.items()}
        atomic_write_json(paths.frozen, merged)

        completeness_bytes = (paths.audit / "completeness.json").read_bytes()
        record = {
            "frozen_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "seasons": list(seasons),
            "waivers": [f"{waiver.season}:{waiver.source}" for waiver in waivers],
            "completeness_sha256": hashlib.sha256(completeness_bytes).hexdigest(),
        }
        atomic_write_json(paths.audit / "freeze.json", record)

    return FreezeResult(
        seasons_added=seasons_added, already_frozen=already_frozen, waivers=list(waivers)
    )
