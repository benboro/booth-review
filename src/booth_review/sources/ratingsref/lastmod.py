"""The Ratings Reference lastmod ledger: the sitemap <lastmod> each record was fetched at.

Two vault files, always read together:

- `ledger/rr_lastmod.json`: the original snapshot, `{telecast_id: {"lastmod",
  "fetched_at", "record_url"}}`. Read-only from 0.2.2 on: nothing rewrites
  it, so it can no longer lose entries to two processes' read-modify-write
  or conflict in a `git pull --rebase` (WR-02). A vault that predates 0.2.2
  keeps it as the base; a new vault never creates it.
- `ledger/rr_lastmod.jsonl`: append-only, one line per fetched record. The
  vault's `ledger/*.jsonl merge=union` rule keeps both sides' lines when the
  job and a local run append between pushes, so the rebase never conflicts.

`load_lastmods` folds both into one `{telecast_id: entry}` map, keeping for
each id the entry with the greatest `lastmod` (ties: the later `fetched_at`),
so neither file order nor a union merge's line order changes the result.
Appends happen one line per write, under the vault lock when the caller
supplies one (RatingsRefCollector), so they never interleave with a
commit's `git add` or a rebase's autostash.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from booth_review.config import DataPaths
from booth_review.errors import VaultStateError
from booth_review.sources.ratingsref.sitemap import SitemapEntry

_TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"
_MIN_DT = datetime.min.replace(tzinfo=UTC)

LastmodEntry = dict[str, str]


def lastmod_ledger_exists(paths: DataPaths) -> bool:
    """Whether either lastmod file exists (a vault that has ever tracked lastmods)."""
    return paths.rr_lastmod.is_file() or paths.rr_lastmod_log.is_file()


def _parse_lastmod(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _entry_key(entry: LastmodEntry) -> tuple[bool, datetime, str]:
    parsed = _parse_lastmod(entry["lastmod"])
    return (parsed is not None, parsed or _MIN_DT, entry.get("fetched_at", ""))


def _require_entry(raw: Any, *, where: str) -> LastmodEntry:
    if not isinstance(raw, dict) or not isinstance(raw.get("lastmod"), str):
        raise VaultStateError(f"invalid lastmod entry in {where}: expected an object with lastmod")
    return {
        key: value
        for key, value in raw.items()
        if key in ("lastmod", "fetched_at", "record_url") and isinstance(value, str)
    }


def _merge(known: dict[str, LastmodEntry], telecast_id: str, entry: LastmodEntry) -> None:
    current = known.get(telecast_id)
    if current is None or _entry_key(entry) > _entry_key(current):
        known[telecast_id] = entry


def load_lastmods(paths: DataPaths) -> dict[str, LastmodEntry]:
    """Every tracked record's latest-known lastmod entry, from both files.

    Raises VaultStateError on a file that isn't valid JSON / JSONL of the
    expected shape, rather than treating the vault as having no lastmods
    (which would make every record look new).
    """
    known: dict[str, LastmodEntry] = {}

    if paths.rr_lastmod.is_file():
        try:
            data = json.loads(paths.rr_lastmod.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise VaultStateError("ledger/rr_lastmod.json is not valid JSON") from exc
        if not isinstance(data, dict):
            raise VaultStateError("ledger/rr_lastmod.json: expected an object")
        for telecast_id, raw in data.items():
            _merge(known, telecast_id, _require_entry(raw, where="ledger/rr_lastmod.json"))

    if paths.rr_lastmod_log.is_file():
        with paths.rr_lastmod_log.open(encoding="utf-8") as fh:
            for number, raw_line in enumerate(fh, start=1):
                stripped = raw_line.strip()
                if not stripped:
                    continue
                where = f"ledger/rr_lastmod.jsonl line {number}"
                try:
                    line = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise VaultStateError(f"{where} is not valid JSON") from exc
                if not isinstance(line, dict) or not isinstance(line.get("telecast_id"), str):
                    raise VaultStateError(f"{where}: expected an object with telecast_id")
                if line.get("event", "fetched") != "fetched":
                    continue
                _merge(known, line["telecast_id"], _require_entry(line, where=where))

    return known


def append_lastmod(paths: DataPaths, entry: SitemapEntry, *, fetched_at: datetime) -> None:
    """Append one fetched record's lastmod line to `ledger/rr_lastmod.jsonl`."""
    line = {
        "event": "fetched",
        "telecast_id": entry.telecast_id,
        "lastmod": entry.lastmod,
        "fetched_at": fetched_at.astimezone(UTC).strftime(_TIME_FMT),
        "record_url": entry.record_url,
    }
    paths.rr_lastmod_log.parent.mkdir(parents=True, exist_ok=True)
    with paths.rr_lastmod_log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, sort_keys=True) + "\n")
