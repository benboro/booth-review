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
import json
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from booth_review.config import DataPaths
from booth_review.errors import FetchError, ParseError
from booth_review.nfl.layout import (
    NFLVERSE_API_BASE,
    NFLVERSE_PBP_RELEASE_PATH,
    NFLVERSE_PBP_TAG,
    NFLVERSE_SCHEDULES_PATH,
    NFLVERSE_SCHEDULES_URL,
    nflverse_pbp_assets_page_path,
)
from booth_review.sources.base import BatchSummary, run_requests
from booth_review.transport.cache import RawCache
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
