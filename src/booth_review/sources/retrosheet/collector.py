"""RetrosheetCollector: downloads index recon, then per-season csvs bundles.

Only /downloads/ on www.retrosheet.org is ever planned; gamelogs and boxesetc
are refused before any request. Archives are validated (zip magic, size cap)
before caching and are never extracted here.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from booth_review.config import DataPaths
from booth_review.errors import FetchError, ResponseTooLargeError
from booth_review.mlb.constants import RETROSHEET_MAX_ZIP_BYTES
from booth_review.mlb.layout import (
    RETROSHEET_INDEX_PATH,
    RETROSHEET_INDEX_URL,
    retrosheet_asset_path,
)
from booth_review.mlb.seasons import mlb_current_season
from booth_review.sources.retrosheet.assets import (
    RETROSHEET_DOWNLOADS_BASE,
    RETROSHEET_HOST,
    RetrosheetAsset,
    discover_assets,
)
from booth_review.transport.cache import FreezeGuard, RawCache
from booth_review.transport.types import FetchRequest, Source

logger = logging.getLogger(__name__)

SOURCE: Source = "mlb_retrosheet"
_ZIP_MAGIC = b"PK\x03\x04"
_FORBIDDEN = ("gamelogs", "boxesetc")
# Only the downloads index page and one csvs bundle per season (AGENTS.md).
_ALLOWED_PATH = re.compile(r"^/downloads/(?:csvdownloads\.html|(\d{4})/\1csvs\.zip)$")


class RetrosheetPathError(FetchError):
    """A planned URL is outside the allowed Retrosheet paths. Never names the URL."""


class RetrosheetIntegrityError(FetchError):
    """A download failed the zip-magic or size check. Count-only message."""


class RetrosheetMissingAsset(FetchError):
    """An expected asset is not on the cached index. Names kind and season only."""


def check_retrosheet_url(url: str) -> None:
    """Raise RetrosheetPathError unless `url` is the index page or one season bundle."""
    lowered = url.lower()
    if any(word in lowered for word in _FORBIDDEN):
        raise RetrosheetPathError("Retrosheet URL points at a disallowed path")
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != RETROSHEET_HOST or parts.query or parts.fragment:
        raise RetrosheetPathError("Retrosheet URL is not a plain https URL on the Retrosheet host")
    if "%" in parts.path or any(seg in (".", "..") for seg in parts.path.split("/")):
        raise RetrosheetPathError("Retrosheet URL has dot or encoded path segments")
    if not _ALLOWED_PATH.match(parts.path):
        raise RetrosheetPathError("Retrosheet URL is outside the allowed downloads")


@dataclass(frozen=True)
class RetrosheetSummary:
    planned: int
    fetched: int
    cached: int
    frozen: int
    failed: int
    dry_run: bool = False
    unreleased: int = 0
    """Default-range seasons whose bundle is not on the index yet (not an error)."""

    def counts(self) -> dict[str, int]:
        return {
            "planned": self.planned,
            "fetched": self.fetched,
            "cached": self.cached,
            "frozen": self.frozen,
            "failed": self.failed,
        }


def _verify(content: bytes) -> None:
    if len(content) > RETROSHEET_MAX_ZIP_BYTES:
        raise RetrosheetIntegrityError("Retrosheet download exceeds the size cap")
    if not content.startswith(_ZIP_MAGIC):
        raise RetrosheetIntegrityError("Retrosheet download is not a zip archive")


class RetrosheetCollector:
    def __init__(self, cache: RawCache, paths: DataPaths) -> None:
        self._cache = cache
        self._paths = paths

    def plan_index(self) -> FetchRequest:
        check_retrosheet_url(RETROSHEET_INDEX_URL)
        return FetchRequest(
            source=SOURCE,
            season=None,
            url=RETROSHEET_INDEX_URL,
            cache_path=RETROSHEET_INDEX_PATH,
        )

    def assets_from_cache(self) -> list[RetrosheetAsset] | None:
        """Assets on the cached index, or None when the index is not cached."""
        body = self._cache.read_cached(self.plan_index())
        if body is None:
            return None
        return discover_assets(body, RETROSHEET_DOWNLOADS_BASE)

    @staticmethod
    def _find(assets: Sequence[RetrosheetAsset], kind: str, season: int | None) -> RetrosheetAsset:
        for asset in assets:
            if asset.kind == kind and asset.season == season:
                return asset
        label = kind if season is None else f"{kind} {season}"
        raise RetrosheetMissingAsset(f"expected Retrosheet asset not on the index: {label}")

    def plan(
        self,
        seasons: Sequence[int],
        assets: Sequence[RetrosheetAsset],
        *,
        optional_from: int | None = None,
    ) -> tuple[list[tuple[FetchRequest, RetrosheetAsset]], int, int]:
        """(requests to consider, frozen-season skips, unreleased skips). Raises
        before any request if an expected asset is missing, except that seasons at
        or after `optional_from` may be absent from the index: Retrosheet releases
        the current season's bundle late, so that is the expected state."""
        freeze = FreezeGuard.load(self._paths.frozen)
        wanted: list[RetrosheetAsset] = []
        frozen = unreleased = 0
        for season in sorted(set(seasons)):
            try:
                bundle = self._find(assets, "season_bundle", season)
            except RetrosheetMissingAsset:
                if optional_from is not None and season >= optional_from:
                    unreleased += 1
                    continue
                raise
            if freeze.is_frozen(SOURCE, season):
                frozen += 1
                continue
            wanted.append(bundle)
        out: list[tuple[FetchRequest, RetrosheetAsset]] = []
        for asset in wanted:
            check_retrosheet_url(asset.url)
            req = FetchRequest(
                source=SOURCE,
                season=asset.season,
                url=asset.url,
                cache_path=retrosheet_asset_path(asset.name),
                max_bytes=RETROSHEET_MAX_ZIP_BYTES,
            )
            out.append((req, asset))
        return out, frozen, unreleased

    def run(
        self,
        seasons: Sequence[int],
        *,
        index_only: bool = False,
        dry_run: bool = False,
        refresh: bool = False,
        current_season: int | None = None,
        optional_from: int | None = None,
    ) -> RetrosheetSummary:
        """`refresh` re-downloads only bundles for `current_season` or later: a
        completed season is never re-fetched. `optional_from` is for the default
        range (see `plan`)."""
        if current_season is None:
            current_season = mlb_current_season(datetime.now(UTC).date())
        index_req = self.plan_index()
        if index_only:
            if dry_run:
                return RetrosheetSummary(1, 0, 0, 0, 0, dry_run=True)
            cached_before = self._cache.read_cached(index_req) is not None and not refresh
            self._cache.get_or_fetch(index_req, refresh=refresh)
            return RetrosheetSummary(1, 0 if cached_before else 1, 1 if cached_before else 0, 0, 0)

        if dry_run:
            assets = self.assets_from_cache()
            if assets is None:
                return RetrosheetSummary(0, 0, 0, 0, 0, dry_run=True)
        else:
            body = self._cache.get_or_fetch(index_req, refresh=False).content
            assets = discover_assets(body, RETROSHEET_DOWNLOADS_BASE)

        plan, frozen, unreleased = self.plan(seasons, assets, optional_from=optional_from)
        if dry_run:
            return RetrosheetSummary(
                len(plan), 0, 0, frozen, 0, dry_run=True, unreleased=unreleased
            )

        fetched = cached = failed = 0
        for req, asset in plan:
            exists = self._cache.read_cached(req) is not None
            refresh_this = refresh and asset.season is not None and asset.season >= current_season
            if exists and not refresh_this:
                cached += 1
                continue
            try:
                self._cache.get_or_fetch(req, refresh=exists, validate=_verify)
            except (RetrosheetIntegrityError, ResponseTooLargeError):
                failed += 1
                continue
            except FetchError as exc:
                status = exc.status_code
                if status is not None and 400 <= status < 500 and status != 429:
                    failed += 1
                    continue
                raise
            fetched += 1
        return RetrosheetSummary(len(plan), fetched, cached, frozen, failed, unreleased=unreleased)
