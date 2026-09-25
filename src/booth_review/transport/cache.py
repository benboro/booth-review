"""RawCache: cached, manifest-recorded fetches on top of PoliteClient.

Every response ever fetched lands under data/vault/raw/ exactly once (unless
explicitly refreshed) and every fetch attempt is recorded in an append-only,
header-free JSONL manifest (FOUND-01). A frozen (source, season) refuses to
fetch at all (FOUND-02). Writes are atomic (temp file + Path.replace).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from booth_review.config import HOST_SOURCE, DataPaths
from booth_review.errors import FetchError, FrozenSeasonError, VaultStateError
from booth_review.transport.client import PoliteClient
from booth_review.transport.types import FetchGuard, FetchRequest, FetchResponse, Validators

CacheStatus = Literal["cached", "new", "frozen-miss"]
Outcome = Literal["cached", "fetched", "not_modified"]

_MANIFEST_FIELDS = (
    "url",
    "source",
    "season",
    "kind",
    "fetched_at",
    "status",
    "etag",
    "last_modified",
    "sha256",
    "path",
    "bytes",
    "final_url",
)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write `data` to `path` atomically: temp file in the same dir, then replace.

    On any exception the temp file is removed and `path` is left untouched.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # delete=False: the file must survive its own close() so Path.replace can
    # rename it afterward; a `with` block would delete it on close instead.
    tmp = tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tmp-", delete=False)  # noqa: SIM115
    tmp_path = Path(tmp.name)
    try:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        tmp_path.replace(path)
    except BaseException:
        tmp.close()
        tmp_path.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, obj: object) -> None:
    """Write `obj` as indented, sorted-key JSON, atomically."""
    payload = json.dumps(obj, indent=2, sort_keys=True) + "\n"
    atomic_write_bytes(path, payload.encode("utf-8"))


@dataclass(frozen=True)
class CacheResult:
    content: bytes
    outcome: Outcome
    path: Path


@dataclass(frozen=True)
class ManifestEntry:
    """One line of the manifest. Never carries request or response headers."""

    url: str
    source: str
    season: int | None
    kind: str
    fetched_at: str
    status: int
    etag: str | None
    last_modified: str | None
    sha256: str | None
    path: str | None
    bytes: int | None
    final_url: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "url": self.url,
                "source": self.source,
                "season": self.season,
                "kind": self.kind,
                "fetched_at": self.fetched_at,
                "status": self.status,
                "etag": self.etag,
                "last_modified": self.last_modified,
                "sha256": self.sha256,
                "path": self.path,
                "bytes": self.bytes,
                "final_url": self.final_url,
            },
            sort_keys=True,
        )


class Manifest:
    """Append-only JSONL manifest at data/vault/ledger/requests.jsonl."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def append(self, entry: ManifestEntry) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(entry.to_json())
            fh.write("\n")

    def entries(self) -> Iterator[dict[str, Any]]:
        if not self._path.is_file():
            return
        with self._path.open(encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped:
                    yield json.loads(stripped)

    def latest_validators(self, url: str) -> Validators | None:
        """The most recent successful (written) entry's etag/last_modified for `url`."""
        latest: dict[str, Any] | None = None
        for entry in self.entries():
            if entry.get("url") == url and entry.get("path") is not None:
                latest = entry
        if latest is None:
            return None
        return Validators(etag=latest.get("etag"), last_modified=latest.get("last_modified"))


class FreezeGuard:
    """Answers whether a (source, season) is frozen (never re-fetched)."""

    def __init__(self, frozen: dict[str, list[int]]) -> None:
        self._frozen = frozen

    @classmethod
    def load(cls, path: Path) -> FreezeGuard:
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
        return cls(data)

    def is_frozen(self, source: str, season: int | None) -> bool:
        if season is None:
            return False
        return season in self._frozen.get(source, [])


class RawCache:
    """The cache layer: serves hits offline, writes misses atomically, and
    refuses frozen-season misses before any request is sent.
    """

    def __init__(
        self,
        paths: DataPaths,
        client: PoliteClient,
        *,
        guards: Sequence[FetchGuard] = (),
        freeze: FreezeGuard | None = None,
    ) -> None:
        self._paths = paths
        self._client = client
        self._guards = list(guards)
        self._freeze = freeze if freeze is not None else FreezeGuard.load(paths.frozen)
        self._manifest = Manifest(paths.manifest)
        self.counters: dict[str, int] = {"cached": 0, "fetched": 0, "not_modified": 0}
        client.add_robots_listener(self._on_robots)

    def _resolve_cache_path(self, cache_path: str) -> Path:
        pure = PurePosixPath(cache_path)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"invalid cache_path: {cache_path!r}")
        raw_resolved = self._paths.raw.resolve()
        candidate = (self._paths.raw / cache_path).resolve()
        if candidate != raw_resolved and raw_resolved not in candidate.parents:
            raise ValueError(f"cache_path escapes raw/: {cache_path!r}")
        return self._paths.raw / cache_path

    def status(self, req: FetchRequest) -> CacheStatus:
        path = self._resolve_cache_path(req.cache_path)
        if path.exists():
            return "cached"
        if self._freeze.is_frozen(req.source, req.season):
            return "frozen-miss"
        return "new"

    def read_cached(self, req: FetchRequest) -> bytes | None:
        path = self._resolve_cache_path(req.cache_path)
        if path.exists():
            return path.read_bytes()
        return None

    def get_or_fetch(
        self,
        req: FetchRequest,
        *,
        refresh: bool = False,
        bearer_token: str | None = None,
    ) -> CacheResult:
        path = self._resolve_cache_path(req.cache_path)

        if path.exists() and not refresh:
            self.counters["cached"] += 1
            return CacheResult(content=path.read_bytes(), outcome="cached", path=path)

        if self._freeze.is_frozen(req.source, req.season):
            raise FrozenSeasonError(f"cannot fetch frozen season: {req.source} {req.season}")

        for guard in self._guards:
            guard.before_fetch(req)

        validators = self._manifest.latest_validators(req.url) if refresh else None
        resp = self._client.fetch(req.url, validators=validators, bearer_token=bearer_token)

        for guard in self._guards:
            guard.after_fetch(req, resp)

        return self._handle_response(req, path, resp)

    def _handle_response(self, req: FetchRequest, path: Path, resp: FetchResponse) -> CacheResult:
        fetched_at = resp.fetched_at.strftime("%Y-%m-%dT%H:%M:%SZ")

        if resp.status_code == 200:
            atomic_write_bytes(path, resp.content)
            self._manifest.append(
                self._entry(req, resp, fetched_at, content=resp.content, path=path)
            )
            self.counters["fetched"] += 1
            return CacheResult(content=resp.content, outcome="fetched", path=path)

        if resp.status_code == 304:
            content = path.read_bytes()
            self._manifest.append(self._entry(req, resp, fetched_at, content=content, path=path))
            self.counters["not_modified"] += 1
            return CacheResult(content=content, outcome="not_modified", path=path)

        self._manifest.append(
            ManifestEntry(
                url=req.url,
                source=req.source,
                season=req.season,
                kind=req.kind,
                fetched_at=fetched_at,
                status=resp.status_code,
                etag=resp.etag,
                last_modified=resp.last_modified,
                sha256=None,
                path=None,
                bytes=None,
                final_url=resp.final_url,
            )
        )
        raise FetchError(
            f"fetch failed with status {resp.status_code}: {req.url}",
            status_code=resp.status_code,
        )

    def _entry(
        self,
        req: FetchRequest,
        resp: FetchResponse,
        fetched_at: str,
        *,
        content: bytes,
        path: Path,
    ) -> ManifestEntry:
        return ManifestEntry(
            url=req.url,
            source=req.source,
            season=req.season,
            kind=req.kind,
            fetched_at=fetched_at,
            status=resp.status_code,
            etag=resp.etag,
            last_modified=resp.last_modified,
            sha256=hashlib.sha256(content).hexdigest(),
            path=path.relative_to(self._paths.raw).as_posix(),
            bytes=len(content),
            final_url=resp.final_url,
        )

    def _on_robots(self, host: str, resp: FetchResponse) -> None:
        date_str = resp.fetched_at.strftime("%Y-%m-%d")
        path = self._paths.raw / "_robots" / host / f"{date_str}.txt"
        atomic_write_bytes(path, resp.content)
        entry = ManifestEntry(
            url=f"https://{host}/robots.txt",
            source=HOST_SOURCE[host],
            season=None,
            kind="robots",
            fetched_at=resp.fetched_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            status=resp.status_code,
            etag=resp.etag,
            last_modified=resp.last_modified,
            sha256=hashlib.sha256(resp.content).hexdigest(),
            path=path.relative_to(self._paths.raw).as_posix(),
            bytes=len(resp.content),
            final_url=resp.final_url,
        )
        self._manifest.append(entry)
