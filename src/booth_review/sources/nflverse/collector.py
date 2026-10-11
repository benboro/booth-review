"""NflverseCollector: nflverse schedules and per-season play-by-play (D-21).

Schedules come from raw.githubusercontent.com. Play-by-play parquet comes
through the api.github.com release-asset API: the `pbp` release is listed
(paginated), then each asset is requested with `Accept: application/octet-stream`
(the API answers with a redirect to a signed asset host, which the client
follows without forwarding Authorization). github.com release-download URLs are
never used: its robots.txt disallows `/*/download`.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from booth_review.config import DataPaths
from booth_review.errors import FetchError, ParseError, VaultStateError
from booth_review.nfl.layout import (
    NFLVERSE_API_BASE,
    NFLVERSE_PBP_RELEASE_PATH,
    NFLVERSE_PBP_TAG,
    NFLVERSE_SCHEDULES_PATH,
    NFLVERSE_SCHEDULES_URL,
    nflverse_pbp_assets_page_path,
    nflverse_pbp_path,
)
from booth_review.sources.base import BatchSummary, run_requests
from booth_review.transport.cache import FreezeGuard, RawCache
from booth_review.transport.types import FetchRequest

logger = logging.getLogger(__name__)

API_HEADERS: tuple[tuple[str, str], ...] = (
    ("Accept", "application/vnd.github+json"),
    ("X-GitHub-Api-Version", "2022-11-28"),
)
ASSET_HEADERS: tuple[tuple[str, str], ...] = (("Accept", "application/octet-stream"),)
ASSETS_PER_PAGE = 100
MAX_ASSET_PAGES = 10
ASSET_LEDGER_NAME = "nfl_nflverse_assets.jsonl"
_TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"
_PARQUET_MAGIC = b"PAR1"


class NflverseSchemaError(ParseError):
    """The release listing is not the expected shape. Messages carry counts and
    field names only."""


class NflverseIntegrityError(FetchError):
    """Downloaded bytes failed the size or parquet-magic check. Count-only message."""


@dataclass(frozen=True)
class NflverseAsset:
    asset_id: int
    name: str
    size: int
    updated_at: str


@dataclass(frozen=True)
class NflverseSummary:
    """The result of one run_pbp call."""

    fetched: int
    unchanged: int
    not_modified: int
    frozen: int
    frozen_missing: int
    missing_assets: tuple[int, ...]
    failed: int
    planned: int
    dry_run: bool = False

    def counts(self) -> dict[str, int]:
        """Counts for vault.batch_message, in a fixed key order."""
        return {
            "fetched": self.fetched,
            "unchanged": self.unchanged,
            "not_modified": self.not_modified,
            "frozen": self.frozen,
            "frozen_missing": self.frozen_missing,
            "missing_assets": len(self.missing_assets),
            "failed": self.failed,
        }


@dataclass(frozen=True)
class _Plan:
    to_fetch: list[tuple[FetchRequest, NflverseAsset, bool]]
    unchanged: int
    frozen: int
    frozen_missing: int
    missing: tuple[int, ...]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class NflverseCollector:
    """Plans and fetches nflverse schedules and the pbp release listing."""

    def __init__(
        self,
        cache: RawCache,
        paths: DataPaths,
        *,
        lock: Callable[[], AbstractContextManager[object]] | None = None,
        now: Callable[[], datetime] = _utc_now,
        token: str | None = None,
    ) -> None:
        """`token` (optional GITHUB_TOKEN) is sent as a bearer token to
        api.github.com requests only; never to raw.githubusercontent.com, and
        it is never logged or stored."""
        self._cache = cache
        self._paths = paths
        self._lock: Callable[[], AbstractContextManager[object]] = lock or contextlib.nullcontext
        self._now = now
        self._token = token

    # -- schedules ---------------------------------------------------------------

    def plan_schedules(self) -> FetchRequest:
        return FetchRequest(
            source="nfl_nflverse",
            season=None,
            url=NFLVERSE_SCHEDULES_URL,
            cache_path=NFLVERSE_SCHEDULES_PATH,
        )

    def run_schedules(self, *, refresh: bool, dry_run: bool) -> BatchSummary:
        return run_requests(
            self._cache,
            [self.plan_schedules()],
            source="nfl_nflverse",
            season_label="schedules",
            dry_run=dry_run,
            refresh=refresh,
        )

    # -- pbp release listing -------------------------------------------------------

    def _release_request(self) -> FetchRequest:
        return FetchRequest(
            source="nfl_nflverse",
            season=None,
            url=f"{NFLVERSE_API_BASE}/releases/tags/{NFLVERSE_PBP_TAG}",
            cache_path=NFLVERSE_PBP_RELEASE_PATH,
            headers=API_HEADERS,
        )

    def _assets_request(self, release_id: int, page: int) -> FetchRequest:
        return FetchRequest(
            source="nfl_nflverse",
            season=None,
            url=(
                f"{NFLVERSE_API_BASE}/releases/{release_id}/assets"
                f"?per_page={ASSETS_PER_PAGE}&page={page}"
            ),
            cache_path=nflverse_pbp_assets_page_path(page),
            headers=API_HEADERS,
        )

    def _load(self, req: FetchRequest, *, dry_run: bool) -> bytes | None:
        if dry_run:
            return self._cache.read_cached(req)
        return self._cache.get_or_fetch(req, refresh=True, bearer_token=self._token).content

    def pbp_assets(self, *, dry_run: bool) -> list[NflverseAsset]:
        """The release's assets, from the live listing (or, in dry-run, only
        from cached listing files, sending nothing)."""
        release_body = self._load(self._release_request(), dry_run=dry_run)
        if release_body is None:
            return []
        release_id = self._parse_release(release_body)

        assets: list[NflverseAsset] = []
        for page in range(1, MAX_ASSET_PAGES + 1):
            body = self._load(self._assets_request(release_id, page), dry_run=dry_run)
            if body is None:
                return assets
            items = self._parse_page(body, page)
            assets.extend(items)
            if len(items) < ASSETS_PER_PAGE:
                return assets
        raise NflverseSchemaError(f"asset listing still full after {MAX_ASSET_PAGES} pages")

    @staticmethod
    def _parse_release(body: bytes) -> int:
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise NflverseSchemaError("release listing is not valid JSON") from exc
        if not isinstance(data, dict) or not _is_int(data.get("id")):
            raise NflverseSchemaError("release listing: field id missing or not an integer")
        return int(data["id"])

    @staticmethod
    def _parse_page(body: bytes, page: int) -> list[NflverseAsset]:
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise NflverseSchemaError(f"asset listing page {page} is not valid JSON") from exc
        if not isinstance(data, list):
            raise NflverseSchemaError(f"asset listing page {page}: expected a list")
        out: list[NflverseAsset] = []
        for item in data:
            if not isinstance(item, dict):
                raise NflverseSchemaError(f"asset listing page {page}: item is not an object")
            for key, ok in (
                ("id", _is_int(item.get("id"))),
                ("name", isinstance(item.get("name"), str)),
                ("size", _is_int(item.get("size"))),
                ("updated_at", isinstance(item.get("updated_at"), str)),
            ):
                if not ok:
                    raise NflverseSchemaError(
                        f"asset listing page {page}: field {key} missing or wrong type"
                    )
            out.append(
                NflverseAsset(
                    asset_id=item["id"],
                    name=item["name"],
                    size=item["size"],
                    updated_at=item["updated_at"],
                )
            )
        return out

    # -- pbp download ----------------------------------------------------------------

    @property
    def _ledger_path(self) -> Path:
        return self._paths.ledger / ASSET_LEDGER_NAME

    def _load_ledger(self) -> dict[str, dict[str, Any]]:
        """Latest line per asset name, by recorded_at (a union merge can reorder lines)."""
        latest: dict[str, dict[str, Any]] = {}
        if not self._ledger_path.is_file():
            return latest
        with self._ledger_path.open(encoding="utf-8") as fh:
            for number, raw_line in enumerate(fh, start=1):
                stripped = raw_line.strip()
                if not stripped:
                    continue
                try:
                    line = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise VaultStateError(f"{ASSET_LEDGER_NAME} line {number} is not JSON") from exc
                if (
                    not isinstance(line, dict)
                    or not isinstance(line.get("name"), str)
                    or not isinstance(line.get("recorded_at"), str)
                ):
                    raise VaultStateError(f"{ASSET_LEDGER_NAME} line {number}: bad shape")
                current = latest.get(line["name"])
                if current is None or line["recorded_at"] >= current["recorded_at"]:
                    latest[line["name"]] = line
        return latest

    def _classify(self, seasons: Sequence[int], assets: Sequence[NflverseAsset]) -> _Plan:
        by_name = {a.name: a for a in assets}
        ledger = self._load_ledger()
        freeze = FreezeGuard.load(self._paths.frozen)
        to_fetch: list[tuple[FetchRequest, NflverseAsset, bool]] = []
        unchanged = frozen = frozen_missing = 0
        missing: list[int] = []
        for season in seasons:
            rel = nflverse_pbp_path(season)
            exists = (self._paths.raw / rel).is_file()
            if freeze.is_frozen("nfl_nflverse", season):
                if exists:
                    frozen += 1
                else:
                    frozen_missing += 1
                continue
            asset = by_name.get(f"play_by_play_{season}.parquet")
            if asset is None:
                missing.append(season)
                continue
            recorded = ledger.get(asset.name)
            if (
                exists
                and recorded is not None
                and recorded.get("updated_at") == asset.updated_at
                and recorded.get("size") == asset.size
            ):
                unchanged += 1
                continue
            req = FetchRequest(
                source="nfl_nflverse",
                season=season,
                url=f"{NFLVERSE_API_BASE}/releases/assets/{asset.asset_id}",
                cache_path=rel,
                headers=ASSET_HEADERS,
            )
            to_fetch.append((req, asset, exists))
        return _Plan(to_fetch, unchanged, frozen, frozen_missing, tuple(missing))

    def plan_pbp(
        self, seasons: Sequence[int], assets: Sequence[NflverseAsset]
    ) -> list[tuple[FetchRequest, NflverseAsset, bool]]:
        """One request per season that needs a download. The bool says a cached
        file already exists, so the fetch must use refresh=True. Seasons that
        are unchanged, frozen, or without an asset are left out."""
        return self._classify(seasons, assets).to_fetch

    def run_pbp(self, seasons: Sequence[int], *, dry_run: bool) -> NflverseSummary:
        """Download changed pbp seasons, verify, and ledger them.

        The size and parquet-magic check runs inside RawCache before anything is
        written (WR-02): a download that fails it is counted as failed and never
        replaces the cached file, the ledger gets no line, and the other seasons
        still run. A season with no ledger line is fetched unconditionally, so a
        bad file cached by an earlier version can't be confirmed by a 304.
        """
        assets = self.pbp_assets(dry_run=dry_run)
        plan = self._classify(seasons, assets)
        if dry_run:
            return self._summary(plan, fetched=0, not_modified=0, failed=0, dry_run=True)

        ledger = self._load_ledger()
        fetched = not_modified = failed = 0
        for req, asset, exists in plan.to_fetch:
            try:
                result = self._cache.get_or_fetch(
                    req,
                    refresh=exists,
                    bearer_token=self._token,
                    conditional=asset.name in ledger,
                    validate=functools.partial(self._verify, asset=asset),
                )
            except NflverseIntegrityError:
                failed += 1
                continue
            except FetchError as exc:
                status = exc.status_code
                if status is not None and 400 <= status < 500 and status != 429:
                    failed += 1
                    continue
                raise
            self._record(asset, result.content)
            if result.outcome == "not_modified":
                not_modified += 1
            else:
                fetched += 1
        return self._summary(
            plan, fetched=fetched, not_modified=not_modified, failed=failed, dry_run=False
        )

    @staticmethod
    def _summary(
        plan: _Plan, *, fetched: int, not_modified: int, failed: int, dry_run: bool
    ) -> NflverseSummary:
        return NflverseSummary(
            fetched=fetched,
            unchanged=plan.unchanged,
            not_modified=not_modified,
            frozen=plan.frozen,
            frozen_missing=plan.frozen_missing,
            missing_assets=plan.missing,
            failed=failed,
            planned=len(plan.to_fetch),
            dry_run=dry_run,
        )

    @staticmethod
    def _verify(content: bytes, asset: NflverseAsset) -> None:
        if len(content) != asset.size:
            raise NflverseIntegrityError("pbp download size differs from the listing size")
        if not (content.startswith(_PARQUET_MAGIC) and content.endswith(_PARQUET_MAGIC)):
            raise NflverseIntegrityError("pbp download is not a parquet file")

    def _record(self, asset: NflverseAsset, content: bytes) -> None:
        line = {
            "name": asset.name,
            "asset_id": asset.asset_id,
            "size": asset.size,
            "updated_at": asset.updated_at,
            "sha256": hashlib.sha256(content).hexdigest(),
            "recorded_at": self._now().strftime(_TIME_FMT),
        }
        with self._lock():
            self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self._ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, sort_keys=True) + "\n")
