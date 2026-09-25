"""Behavioral tests for RawCache, Manifest, FreezeGuard, and atomic writes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

import pytest

from booth_review.errors import FetchError, FrozenSeasonError, VaultStateError
from booth_review.transport import cache as cache_module
from booth_review.transport.cache import FreezeGuard, RawCache
from booth_review.transport.client import PoliteClient
from booth_review.transport.types import FetchRequest

_MANIFEST_KEYS = {
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
}


@dataclass
class RecordingGuard:
    raise_on_before: bool = False
    before_calls: list = field(default_factory=list)
    after_calls: list = field(default_factory=list)

    def before_fetch(self, req):
        self.before_calls.append(req)
        if self.raise_on_before:
            raise RuntimeError("blocked by guard")

    def after_fetch(self, req, resp):
        self.after_calls.append((req, resp))


def _client(handle, *, fake_clock=None):
    kwargs: dict = {"transport": handle.transport}
    if fake_clock is not None:
        kwargs["clock"] = fake_clock.now
        kwargs["sleep"] = fake_clock.sleep
    else:
        kwargs["clock"] = lambda: 0.0
        kwargs["sleep"] = lambda seconds: None
    return PoliteClient(**kwargs)


def _manifest_lines(paths) -> list[dict]:
    if not paths.manifest.is_file():
        return []
    return [json.loads(line) for line in paths.manifest.read_text(encoding="utf-8").splitlines()]


# -- Cache hits ---------------------------------------------------------------


def test_cached_hit_returns_bytes_and_sends_nothing(vault_paths, mock_transport_factory) -> None:
    cache_path = "sports506/2025/wk01.html"
    dest = vault_paths.raw / cache_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"<html>cached</html>")

    handle = mock_transport_factory({})
    client = _client(handle)
    cache = RawCache(vault_paths, client)
    req = FetchRequest(
        source="sports506",
        season=2025,
        url="https://506sports.com/ncaaf.php?yr=2025&wk=1",
        cache_path=cache_path,
    )

    result = cache.get_or_fetch(req)

    assert result.outcome == "cached"
    assert result.content == b"<html>cached</html>"
    assert handle.requests == []
    assert cache.counters["cached"] == 1


# -- Misses ---------------------------------------------------------------------


def test_miss_writes_file_atomically_and_appends_manifest_with_exact_keys(
    vault_paths, mock_transport_factory
) -> None:
    body = b"<html>week1</html>"
    handle = mock_transport_factory(
        {
            "https://506sports.com/robots.txt": (404, b"nf", {}),
            "https://506sports.com/ncaaf.php?yr=2025&wk=1": (200, body, {}),
        }
    )
    client = _client(handle)
    cache = RawCache(vault_paths, client)
    cache_path = "sports506/2025/wk01.html"
    req = FetchRequest(
        source="sports506",
        season=2025,
        url="https://506sports.com/ncaaf.php?yr=2025&wk=1",
        cache_path=cache_path,
    )

    result = cache.get_or_fetch(req)

    assert result.outcome == "fetched"
    written = vault_paths.raw / cache_path
    assert written.read_bytes() == body

    lines = _manifest_lines(vault_paths)
    page_lines = [line for line in lines if line["kind"] == "page"]
    assert len(page_lines) == 1
    entry = page_lines[0]
    assert set(entry.keys()) == _MANIFEST_KEYS
    assert entry["sha256"] == hashlib.sha256(body).hexdigest()
    assert entry["path"] == cache_path
    assert entry["bytes"] == len(body)
    assert entry["fetched_at"].endswith("Z")
    assert cache.counters["fetched"] == 1


def test_non2xx_appends_manifest_without_writing_file_and_raises(
    vault_paths, mock_transport_factory
) -> None:
    handle = mock_transport_factory(
        {
            "https://506sports.com/robots.txt": (404, b"nf", {}),
            "https://506sports.com/ncaaf.php?yr=2025&wk=99": (404, b"not found", {}),
        }
    )
    client = _client(handle)
    cache = RawCache(vault_paths, client)
    cache_path = "sports506/2025/wk99.html"
    req = FetchRequest(
        source="sports506",
        season=2025,
        url="https://506sports.com/ncaaf.php?yr=2025&wk=99",
        cache_path=cache_path,
    )

    with pytest.raises(FetchError) as exc_info:
        cache.get_or_fetch(req)

    assert exc_info.value.status_code == 404
    assert not (vault_paths.raw / cache_path).exists()

    lines = _manifest_lines(vault_paths)
    page_lines = [line for line in lines if line["kind"] == "page"]
    assert len(page_lines) == 1
    assert page_lines[0]["path"] is None
    assert page_lines[0]["sha256"] is None


# -- Frozen seasons ---------------------------------------------------------------


def test_frozen_miss_raises_before_any_request(vault_paths, mock_transport_factory) -> None:
    vault_paths.frozen.write_text(
        json.dumps({"sports506": [2014], "ratingsref": [], "cfbd": []})
    )
    handle = mock_transport_factory({})
    client = _client(handle)
    cache = RawCache(vault_paths, client)
    req = FetchRequest(
        source="sports506",
        season=2014,
        url="https://506sports.com/ncaaf.php?yr=2014&wk=1",
        cache_path="sports506/2014/wk01.html",
    )

    with pytest.raises(FrozenSeasonError):
        cache.get_or_fetch(req)

    assert handle.requests == []


def test_frozen_but_already_cached_entry_is_still_returned(
    vault_paths, mock_transport_factory
) -> None:
    vault_paths.frozen.write_text(
        json.dumps({"sports506": [2014], "ratingsref": [], "cfbd": []})
    )
    cache_path = "sports506/2014/wk01.html"
    dest = vault_paths.raw / cache_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"<html>archived</html>")

    handle = mock_transport_factory({})
    client = _client(handle)
    cache = RawCache(vault_paths, client)
    req = FetchRequest(
        source="sports506",
        season=2014,
        url="https://506sports.com/ncaaf.php?yr=2014&wk=1",
        cache_path=cache_path,
    )

    result = cache.get_or_fetch(req)

    assert result.outcome == "cached"
    assert result.content == b"<html>archived</html>"
    assert handle.requests == []


def test_refresh_on_frozen_season_raises(vault_paths, mock_transport_factory) -> None:
    vault_paths.frozen.write_text(
        json.dumps({"sports506": [2014], "ratingsref": [], "cfbd": []})
    )
    cache_path = "sports506/2014/wk01.html"
    dest = vault_paths.raw / cache_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"<html>old</html>")

    handle = mock_transport_factory({})
    client = _client(handle)
    cache = RawCache(vault_paths, client)
    req = FetchRequest(
        source="sports506",
        season=2014,
        url="https://506sports.com/ncaaf.php?yr=2014&wk=1",
        cache_path=cache_path,
    )

    with pytest.raises(FrozenSeasonError):
        cache.get_or_fetch(req, refresh=True)

    assert handle.requests == []


# -- status() -------------------------------------------------------------------


def test_status_returns_cached_new_and_frozen_miss_without_sending(
    vault_paths, mock_transport_factory
) -> None:
    vault_paths.frozen.write_text(
        json.dumps({"sports506": [2014], "ratingsref": [], "cfbd": []})
    )
    cached_path = "sports506/2025/wk01.html"
    dest = vault_paths.raw / cached_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"x")

    handle = mock_transport_factory({})
    client = _client(handle)
    cache = RawCache(vault_paths, client)

    cached_req = FetchRequest(
        source="sports506", season=2025, url="https://506sports.com/a", cache_path=cached_path
    )
    new_req = FetchRequest(
        source="sports506",
        season=2025,
        url="https://506sports.com/b",
        cache_path="sports506/2025/wk02.html",
    )
    frozen_req = FetchRequest(
        source="sports506",
        season=2014,
        url="https://506sports.com/c",
        cache_path="sports506/2014/wk01.html",
    )

    assert cache.status(cached_req) == "cached"
    assert cache.status(new_req) == "new"
    assert cache.status(frozen_req) == "frozen-miss"
    assert handle.requests == []


# -- Conditional refresh / 304 -----------------------------------------------------


def test_refresh_sends_conditional_headers_and_304_returns_cached(
    vault_paths, mock_transport_factory
) -> None:
    cache_path = "ratingsref/telecast/2025/a.json"
    dest = vault_paths.raw / cache_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b'{"cached": true}')

    prior_entry = {
        "url": "https://ratingsreference.com/api/telecast/a.json",
        "source": "ratingsref",
        "season": 2025,
        "kind": "page",
        "fetched_at": "2026-01-01T00:00:00Z",
        "status": 200,
        "etag": '"abc"',
        "last_modified": "Wed, 21 Oct 2015 07:28:00 GMT",
        "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
        "path": cache_path,
        "bytes": len(dest.read_bytes()),
        "final_url": "https://ratingsreference.com/api/telecast/a.json",
    }
    vault_paths.manifest.write_text(json.dumps(prior_entry, sort_keys=True) + "\n")

    handle = mock_transport_factory(
        {
            "https://ratingsreference.com/robots.txt": (404, b"nf", {}),
            "https://ratingsreference.com/api/telecast/a.json": (304, b"", {}),
        }
    )
    client = _client(handle)
    cache = RawCache(vault_paths, client)
    req = FetchRequest(
        source="ratingsref",
        season=2025,
        url="https://ratingsreference.com/api/telecast/a.json",
        cache_path=cache_path,
    )

    result = cache.get_or_fetch(req, refresh=True)

    assert result.outcome == "not_modified"
    assert result.content == b'{"cached": true}'
    assert cache.counters["not_modified"] == 1

    page_request = next(r for r in handle.requests if r.url.endswith("a.json"))
    assert page_request.headers["if-none-match"] == '"abc"'
    assert page_request.headers["if-modified-since"] == "Wed, 21 Oct 2015 07:28:00 GMT"

    lines = _manifest_lines(vault_paths)
    assert lines[-1]["status"] == 304
    assert lines[-1]["path"] == cache_path


# -- Guards -----------------------------------------------------------------------


def test_guard_before_fetch_raising_prevents_any_request(
    vault_paths, mock_transport_factory
) -> None:
    handle = mock_transport_factory(
        {
            "https://506sports.com/robots.txt": (404, b"nf", {}),
            "https://506sports.com/ncaaf.php?yr=2025&wk=1": (200, b"ok", {}),
        }
    )
    client = _client(handle)
    guard = RecordingGuard(raise_on_before=True)
    cache = RawCache(vault_paths, client, guards=[guard])
    req = FetchRequest(
        source="sports506",
        season=2025,
        url="https://506sports.com/ncaaf.php?yr=2025&wk=1",
        cache_path="sports506/2025/wk01.html",
    )

    with pytest.raises(RuntimeError):
        cache.get_or_fetch(req)

    assert handle.requests == []
    assert guard.after_calls == []


def test_guard_after_fetch_called_once_for_non2xx_response(
    vault_paths, mock_transport_factory
) -> None:
    handle = mock_transport_factory(
        {
            "https://506sports.com/robots.txt": (404, b"nf", {}),
            "https://506sports.com/ncaaf.php?yr=2025&wk=1": (500, b"boom", {}),
        }
    )
    client = _client(handle)
    guard = RecordingGuard()
    cache = RawCache(vault_paths, client, guards=[guard])
    req = FetchRequest(
        source="sports506",
        season=2025,
        url="https://506sports.com/ncaaf.php?yr=2025&wk=1",
        cache_path="sports506/2025/wk01.html",
    )

    with pytest.raises(FetchError):
        cache.get_or_fetch(req)

    assert len(guard.after_calls) == 1
    assert guard.after_calls[0][1].status_code == 500


# -- cache_path validation -----------------------------------------------------------


def test_cache_path_absolute_raises_before_any_request(
    vault_paths, mock_transport_factory
) -> None:
    handle = mock_transport_factory({})
    client = _client(handle)
    cache = RawCache(vault_paths, client)
    req = FetchRequest(
        source="sports506", season=2025, url="https://506sports.com/a", cache_path="/etc/passwd"
    )

    with pytest.raises(ValueError):
        cache.get_or_fetch(req)

    assert handle.requests == []


def test_cache_path_dotdot_raises_before_any_request(
    vault_paths, mock_transport_factory
) -> None:
    handle = mock_transport_factory({})
    client = _client(handle)
    cache = RawCache(vault_paths, client)
    req = FetchRequest(
        source="sports506",
        season=2025,
        url="https://506sports.com/a",
        cache_path="../outside.html",
    )

    with pytest.raises(ValueError):
        cache.get_or_fetch(req)

    assert handle.requests == []


# -- robots.txt caching -------------------------------------------------------------


def test_robots_fetch_writes_raw_robots_file_and_manifest_kind_robots(
    vault_paths, mock_transport_factory
) -> None:
    robots_body = b"User-agent: *\nAllow: /\n"
    handle = mock_transport_factory(
        {
            "https://506sports.com/robots.txt": (200, robots_body, {}),
            "https://506sports.com/ncaaf.php?yr=2025&wk=1": (200, b"<html>week1</html>", {}),
        }
    )
    client = _client(handle)
    cache = RawCache(vault_paths, client)
    req = FetchRequest(
        source="sports506",
        season=2025,
        url="https://506sports.com/ncaaf.php?yr=2025&wk=1",
        cache_path="sports506/2025/wk01.html",
    )

    cache.get_or_fetch(req)

    robots_files = list((vault_paths.raw / "_robots" / "506sports.com").glob("*.txt"))
    assert len(robots_files) == 1
    assert robots_files[0].read_bytes() == robots_body

    lines = _manifest_lines(vault_paths)
    robots_lines = [line for line in lines if line["kind"] == "robots"]
    assert len(robots_lines) == 1
    assert robots_lines[0]["source"] == "sports506"
    assert robots_lines[0]["season"] is None
    assert robots_lines[0]["path"] is not None


# -- Bearer token never leaks --------------------------------------------------------


def test_bearer_token_never_appears_in_any_vault_file(vault_paths, mock_transport_factory) -> None:
    handle = mock_transport_factory(
        {
            "https://api.collegefootballdata.com/robots.txt": (404, b"nf", {}),
            "https://api.collegefootballdata.com/games?year=2025": (200, b'{"ok": true}', {}),
        }
    )
    client = _client(handle)
    cache = RawCache(vault_paths, client)
    req = FetchRequest(
        source="cfbd",
        season=2025,
        url="https://api.collegefootballdata.com/games?year=2025",
        cache_path="cfbd/games/2025.json",
        endpoint="/games",
    )

    cache.get_or_fetch(req, bearer_token="SENTINEL-KEY-123")

    for path in vault_paths.vault.rglob("*"):
        if path.is_file():
            assert b"SENTINEL-KEY-123" not in path.read_bytes()


# -- Atomic writes ------------------------------------------------------------------


def test_atomic_write_bytes_leaves_no_tmp_files_after_success(vault_paths) -> None:
    dest = vault_paths.raw / "sports506" / "2025" / "wk02.html"
    cache_module.atomic_write_bytes(dest, b"hello")

    assert dest.read_bytes() == b"hello"
    assert list(dest.parent.glob(".tmp-*")) == []


def test_atomic_write_bytes_exception_leaves_destination_untouched(
    vault_paths, monkeypatch
) -> None:
    dest = vault_paths.raw / "sports506" / "2025" / "wk01.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"original")

    def boom(fd):
        raise OSError("disk full")

    monkeypatch.setattr(cache_module.os, "fsync", boom)

    with pytest.raises(OSError):
        cache_module.atomic_write_bytes(dest, b"new content")

    assert dest.read_bytes() == b"original"
    assert list(dest.parent.glob(".tmp-*")) == []


# -- FreezeGuard ----------------------------------------------------------------------


def test_freeze_guard_load_missing_file_raises_vault_state_error(tmp_path) -> None:
    with pytest.raises(VaultStateError):
        FreezeGuard.load(tmp_path / "missing.json")
