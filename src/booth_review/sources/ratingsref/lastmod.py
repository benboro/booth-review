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
`load_fetched_lastmods` keeps the entry fetched most recently instead (ties:
the greater `lastmod`), with the same order independence; the refresh compares
the sitemap against that one. "Most recently" is by each line's own `fetched_at`,
so it assumes the clones that append (the job and local runs) keep roughly
synchronized clocks: a clone running behind can write a newer fetch that sorts
older, and the record then requalifies on every run until a fetch stamped after
the older one lands (bounded by the skew).

The log also records refresh failures (`"event": "failed"`, with the sitemap
lastmod the fetch was attempted at): a 4xx (`status` is the code) or a body that
did not parse as a record (`status` is null). `load_failures` reads them so
the refresh can hold back a record that keeps failing instead of letting it
take the head of the capped queue every run (WR-04).
Appends happen one line per write, under the vault lock when the caller
supplies one (RatingsRefCollector), so they never interleave with a
commit's `git add` or a rebase's autostash.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from booth_review.config import DataPaths
from booth_review.errors import VaultStateError
from booth_review.sources.ratingsref.sitemap import SitemapEntry

_FETCHED_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"
"""`fetched_at` and `failed_at` keep microseconds: the ledger orders fetches and
failures by them, and two clones can write one record within a second. Older lines (and the
snapshot) have whole seconds; the reader accepts both."""
_MIN_DT = datetime.min.replace(tzinfo=UTC)

LastmodEntry = dict[str, str]


@dataclass(frozen=True)
class FailedFetch:
    """A record's most recent failed refresh fetch."""

    lastmod: str
    """The sitemap lastmod the failed fetch was attempted at."""
    failed_at: datetime
    status: int | None


def lastmod_ledger_exists(paths: DataPaths) -> bool:
    """Whether either lastmod file exists (a vault that has ever tracked lastmods)."""
    return paths.rr_lastmod.is_file() or paths.rr_lastmod_log.is_file()


def lastmod_has_prefix(paths: DataPaths, prefix: str) -> bool:
    """Whether any tracked record's telecast_id starts with `prefix` (e.g. "nfl-")."""
    return any(telecast_id.startswith(prefix) for telecast_id in load_lastmods(paths))


def _parse_lastmod(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _entry_key(entry: LastmodEntry) -> tuple[bool, datetime, datetime]:
    parsed = _parse_lastmod(entry["lastmod"])
    fetched = _parse_lastmod(entry.get("fetched_at", ""))
    return (parsed is not None, parsed or _MIN_DT, fetched or _MIN_DT)


def _require_entry(raw: Any, *, where: str) -> LastmodEntry:
    if not isinstance(raw, dict) or not isinstance(raw.get("lastmod"), str):
        raise VaultStateError(f"invalid lastmod entry in {where}: expected an object with lastmod")
    return {
        key: value
        for key, value in raw.items()
        if key in ("lastmod", "fetched_at", "record_url") and isinstance(value, str)
    }


def _fetch_key(
    entry: LastmodEntry,
) -> tuple[bool, datetime, tuple[bool, datetime, datetime], str]:
    """Order entries by when they were fetched; ties fall back to `_entry_key`.

    The raw lastmod string is the last tiebreak: two spellings of one instant
    (`...Z` and `...+00:00`) tie on every parsed field, and the refresh compares
    the raw string, so without it the line order would pick the winner.
    """
    fetched = _parse_lastmod(entry.get("fetched_at", ""))
    return (fetched is not None, fetched or _MIN_DT, _entry_key(entry), entry["lastmod"])


def _merge(
    known: dict[str, LastmodEntry],
    telecast_id: str,
    entry: LastmodEntry,
    key: Callable[[LastmodEntry], Any],
) -> None:
    current = known.get(telecast_id)
    # Entries that tie on `key` still differ in spelling or record_url; comparing
    # every retained field last keeps the winner independent of line order.
    if current is None or (key(entry), sorted(entry.items())) > (
        key(current),
        sorted(current.items()),
    ):
        known[telecast_id] = entry


def _load(paths: DataPaths, key: Callable[[LastmodEntry], Any]) -> dict[str, LastmodEntry]:
    known: dict[str, LastmodEntry] = {}

    if paths.rr_lastmod.is_file():
        try:
            data = json.loads(paths.rr_lastmod.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise VaultStateError("ledger/rr_lastmod.json is not valid JSON") from exc
        if not isinstance(data, dict):
            raise VaultStateError("ledger/rr_lastmod.json: expected an object")
        for telecast_id, raw in data.items():
            _merge(known, telecast_id, _require_entry(raw, where="ledger/rr_lastmod.json"), key)

    for where, line in _log_lines(paths):
        if line.get("event", "fetched") == "fetched":
            _merge(known, line["telecast_id"], _require_entry(line, where=where), key)

    return known


def load_lastmods(paths: DataPaths) -> dict[str, LastmodEntry]:
    """Every tracked record's greatest-lastmod entry, from both files.

    Raises VaultStateError on a file that isn't valid JSON / JSONL of the
    expected shape, rather than treating the vault as having no lastmods
    (which would make every record look new).
    """
    return _load(paths, _entry_key)


def load_fetched_lastmods(paths: DataPaths) -> dict[str, LastmodEntry]:
    """Every tracked record's most recently fetched entry, from both files.

    This is the lastmod a record was last fetched at, which is what a refresh
    compares the sitemap against. It can be older than the greatest lastmod
    `load_lastmods` returns when the sitemap's lastmod moved backwards; the
    refresh must then treat the record as fetched at the sitemap's value, not
    as advanced again on every run. Raises VaultStateError like `load_lastmods`.
    """
    return _load(paths, _fetch_key)


def _log_lines(paths: DataPaths) -> Iterator[tuple[str, dict[str, Any]]]:
    if not paths.rr_lastmod_log.is_file():
        return
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
            yield where, line


def _failure_key(failure: FailedFetch) -> tuple[datetime, str, int]:
    """Newest failure first; ties settle on lastmod then status, never on line order."""
    return (failure.failed_at, failure.lastmod, -1 if failure.status is None else failure.status)


def load_failures(paths: DataPaths) -> dict[str, FailedFetch]:
    """Each record's most recent failed refresh fetch (by `failed_at`)."""
    failures: dict[str, FailedFetch] = {}
    for where, line in _log_lines(paths):
        if line.get("event") != "failed":
            continue
        lastmod, failed_at, status = line.get("lastmod"), line.get("failed_at"), line.get("status")
        if not isinstance(lastmod, str) or not isinstance(failed_at, str):
            raise VaultStateError(f"{where}: a failed line needs lastmod and failed_at")
        when = _parse_lastmod(failed_at)
        if when is None:
            raise VaultStateError(f"{where}: failed_at is not a UTC timestamp")
        found = FailedFetch(
            lastmod=lastmod,
            failed_at=when,
            status=status if isinstance(status, int) else None,
        )
        current = failures.get(line["telecast_id"])
        if current is None or _failure_key(found) > _failure_key(current):
            failures[line["telecast_id"]] = found
    return failures


def _append(paths: DataPaths, line: dict[str, Any]) -> None:
    paths.rr_lastmod_log.parent.mkdir(parents=True, exist_ok=True)
    with paths.rr_lastmod_log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, sort_keys=True) + "\n")


def append_lastmod(paths: DataPaths, entry: SitemapEntry, *, fetched_at: datetime) -> None:
    """Append one fetched record's lastmod line to `ledger/rr_lastmod.jsonl`."""
    _append(
        paths,
        {
            "event": "fetched",
            "telecast_id": entry.telecast_id,
            "lastmod": entry.lastmod,
            "fetched_at": fetched_at.astimezone(UTC).strftime(_FETCHED_FMT),
            "record_url": entry.record_url,
        },
    )


def append_failure(
    paths: DataPaths, entry: SitemapEntry, *, status: int | None, failed_at: datetime
) -> None:
    """Append one record's failed-fetch line to `ledger/rr_lastmod.jsonl`.

    `status` is the 4xx code, or None when the response was rejected as not an RR record.
    """
    _append(
        paths,
        {
            "event": "failed",
            "telecast_id": entry.telecast_id,
            "lastmod": entry.lastmod,
            "failed_at": failed_at.astimezone(UTC).strftime(_FETCHED_FMT),
            "status": status,
        },
    )
