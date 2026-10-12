"""Assemble dist/site (D-14): copy the committed `site/` source, validate
and write `site-data.json`, cache-bust and fill index.html's footer token,
and render `methodology.html`/`coverage.html` (build.pages).

Reads `site/`, `docs/`, and exactly one site-data.json (the vault's
`processed/site-data.json` or the synthetic contract fixture); writes only
to the caller-supplied out dir; never writes to the vault; prints nothing
itself (the CLI does the printing). The only place this module touches the
CFBD key is `check_no_key_leak`, which never prints or logs it -- a second,
independent gate on top of `build.site_data`'s own "never reads the key"
guarantee (SITE-19).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from booth_review.build import pages
from booth_review.build.site_data import _contract_error_summary
from booth_review.config import load_cfbd_key
from booth_review.contract.models import SiteData, validate_site_data
from booth_review.contract.nfl_models import NflSiteData, validate_nfl_site_data
from booth_review.errors import KeyLeakError, MissingApiKeyError, SiteBuildError
from booth_review.transport.cache import atomic_write_bytes

PLOTLY_BUNDLE = "vendor/plotly-4.1.1.min.js"
PLOTLY_SHA256 = "3b6e15d45dbb7fca5bd2094291e961ddc5472cd887009e6009a56dab668d721f"
MAP_GEOMETRY = "vendor/us-states-albers.js"
MAP_GEOMETRY_SHA256 = "ff1e0a82d121f389782ef3ff466fc2910a08b7594af9e92598ac4032a9e2d3dc"
COPY_SUFFIXES = frozenset({".html", ".js", ".css"})
BUILD_MARKER = ".booth-review-site"
VERSION_TOKEN = "__SITE_DATA_VERSION__"
FOOTER_TOKEN = "<!-- booth-review:footer -->"

SPORTS_META_TOKEN = "<!-- booth-review:sports-meta -->"
SPORT_SWITCH_TOKEN = "<!-- booth-review:sport-switch -->"
NFL_DATA_FILE = "nfl-data.json"
# The switch is data-driven (D-19): a later sport is one more tuple.
SITE_SPORTS: tuple[tuple[str, str], ...] = (("cfb", "CFB"), ("nfl", "NFL"))
_CFB_ONLY = tuple(sid for sid, _ in SITE_SPORTS[:1])

_DEFAULT_FIXTURE = Path("tests/fixtures/contract/site-data.fixture.json")
_DEFAULT_NFL_FIXTURE = Path("tests/fixtures/contract/nfl-data.fixture.json")


def nfl_site_enabled(env: Mapping[str, str]) -> bool:
    """The one NFL flag (D-18): only the exact string "true" turns NFL on."""
    return env.get("NFL_SITE_ENABLED") == "true"


def nfl_fixture_path() -> Path:
    """The synthetic NFL fixture, or BOOTH_REVIEW_NFL_FIXTURE when set."""
    env = os.environ.get("BOOTH_REVIEW_NFL_FIXTURE")
    return Path(env) if env else _DEFAULT_NFL_FIXTURE


def site_source_dir() -> Path:
    """site/, or BOOTH_REVIEW_SITE_SRC when set (mirrors reference_dir())."""
    env = os.environ.get("BOOTH_REVIEW_SITE_SRC")
    return Path(env) if env else Path("site")


def docs_dir() -> Path:
    """docs/, or BOOTH_REVIEW_DOCS when set (mirrors reference_dir())."""
    env = os.environ.get("BOOTH_REVIEW_DOCS")
    return Path(env) if env else Path("docs")


def fixture_path() -> Path:
    """The synthetic contract fixture, or BOOTH_REVIEW_SITE_FIXTURE when set."""
    env = os.environ.get("BOOTH_REVIEW_SITE_FIXTURE")
    return Path(env) if env else _DEFAULT_FIXTURE


@dataclass(frozen=True)
class SiteBuildResult:
    out_dir: Path
    files: tuple[str, ...]
    telecasts: int
    people: int
    data_version: str
    key_checked: bool
    nfl_games: int | None = None


@dataclass(frozen=True)
class NflRefreshResult:
    games: int
    key_checked: bool
    replaced: bool


def load_site_payload(source: Path) -> tuple[SiteData, bytes]:
    """Read and validate `source` against the site-data contract.

    Returns the validated model and its bytes, serialized exactly like
    `build.site_data.write_site_data` (compact, sorted-key JSON), so the
    same content always produces the same cache-bust version. Raises
    SiteBuildError, naming a location only, on a missing file or a
    contract failure (SITE-19).
    """
    if not source.is_file():
        raise SiteBuildError(f"{source} not found")
    raw = json.loads(source.read_text(encoding="utf-8"))
    try:
        site = validate_site_data(raw)
    except ValidationError as exc:
        raise SiteBuildError(_contract_error_summary(exc)) from None
    payload = site.model_dump(mode="json")
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return site, body


def load_nfl_site_payload(source: Path) -> tuple[NflSiteData, bytes]:
    """Read and validate `source` against the NFL site-data contract.

    Returns the model and its canonical compact sorted-key bytes. Raises
    SiteBuildError naming a location only on a missing file or a contract
    failure.
    """
    if not source.is_file():
        raise SiteBuildError(f"{source} not found")
    return nfl_site_payload_from_bytes(source.read_bytes(), name=source.name)


def nfl_site_payload_from_bytes(
    raw: bytes, *, name: str = NFL_DATA_FILE
) -> tuple[NflSiteData, bytes]:
    """Validate `raw` nfl-data.json bytes against the NFL contract.

    Returns the model and its canonical compact sorted-key bytes. Raises
    SiteBuildError naming `name` or a contract location only, never a value.
    """
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise SiteBuildError(f"{name}: not valid JSON") from None
    try:
        nfl = validate_nfl_site_data(parsed)
    except ValidationError as exc:
        raise SiteBuildError(_contract_error_summary(exc)) from None
    payload = nfl.model_dump(mode="json")
    try:
        # NaN or Infinity would be invalid JSON (WR-04); the contract rejects
        # them first, so this only guards against drift.
        text = json.dumps(payload, separators=(",", ":"), sort_keys=True, allow_nan=False)
    except ValueError:
        raise SiteBuildError(f"{name}: a number is not finite") from None
    return nfl, text.encode("utf-8")


def _nfl_game_count(nfl: NflSiteData) -> int:
    return len(nfl.games.season)


def _check_out_dir(out_dir: Path) -> None:
    """Refuse a non-empty `out_dir` unless it is a previous booth-review
    site build (T-04-17): only then is it safe to replace. Touches nothing.
    """
    if out_dir.exists() and any(out_dir.iterdir()) and not (out_dir / BUILD_MARKER).is_file():
        raise SiteBuildError(
            f"refusing to overwrite {out_dir}: not a previous booth-review site build"
        )


def _make_staging_dir(out_dir: Path) -> Path:
    """Create a fresh, hidden sibling of `out_dir` to assemble into (WR-01).

    A sibling (same parent) so the final swap is a same-filesystem rename;
    created with a plain `mkdir` rather than `tempfile.mkdtemp`, so it gets
    the usual umask permissions (not mkdtemp's 0700) once it becomes the site.
    """
    target = out_dir.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{target.name}.staging-{os.getpid()}-{secrets.token_hex(4)}"
    staging.mkdir()
    return staging


def _swap_into_place(staging: Path, out_dir: Path) -> None:
    """Replace `out_dir` (a previous build, an empty dir, or nothing) with
    the fully assembled `staging` dir. The old build is renamed aside before
    the new one is renamed in, and only then deleted, so no step ever
    deletes the old build before the new one is in place.
    """
    target = out_dir.resolve()
    retired: Path | None = None
    if target.exists():
        retired = target.parent / f".{target.name}.retired-{os.getpid()}-{secrets.token_hex(4)}"
        target.rename(retired)
    staging.rename(target)
    if retired is not None:
        shutil.rmtree(retired, ignore_errors=True)


def _verify_bundle(site_src: Path) -> None:
    """Refuse vendored files whose digest isn't pinned: the Plotly bundle
    (PLOTLY_SHA256, T-04-16) and the map geometry (MAP_GEOMETRY_SHA256,
    T-04.18-10). A tampered or wrong-version file never reaches dist/site.
    """
    bundle_path = site_src / PLOTLY_BUNDLE
    if not bundle_path.is_file():
        raise SiteBuildError("vendored Plotly bundle not found")
    digest = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    if digest != PLOTLY_SHA256:
        raise SiteBuildError("vendored Plotly bundle digest mismatch")
    geometry_path = site_src / MAP_GEOMETRY
    if not geometry_path.is_file():
        raise SiteBuildError("vendored map geometry not found")
    if hashlib.sha256(geometry_path.read_bytes()).hexdigest() != MAP_GEOMETRY_SHA256:
        raise SiteBuildError("vendored map geometry digest mismatch")


def check_no_key_leak(out_dir: Path) -> bool:
    """Grep every file under `out_dir` for the configured CFBD key (T-04-13).

    Returns False when no key is configured (nothing to compare against).
    CI never holds the real key; its site-build step sets a synthetic
    canary `CFBD_API_KEY` instead, so this grep still runs there and would
    catch any build path that copied the configured key into the output
    (WR-02). On a hit, removes `out_dir` and raises SiteBuildError naming
    the offending file only, never the key.
    """
    try:
        key = load_cfbd_key()
    except MissingApiKeyError:
        return False
    needle = key.encode("utf-8")
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file():
            continue
        if needle in path.read_bytes():
            relative = path.relative_to(out_dir)
            shutil.rmtree(out_dir)
            raise KeyLeakError(f"CFBD key found in build output: {relative}; output removed")
    return True


def check_nfl_file_key(body: bytes, *, scratch_parent: Path) -> bool:
    """Key-check `body` as nfl-data.json in a hidden temp dir under
    `scratch_parent` (never inside a site dir), via `check_no_key_leak`.
    False when no key is configured; KeyLeakError on a hit.
    """
    scratch_parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".nfl-keycheck-", dir=scratch_parent))
    try:
        (tmp / NFL_DATA_FILE).write_bytes(body)
        return check_no_key_leak(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def refresh_nfl_data(*, site_out: Path, source: Path) -> NflRefreshResult:
    """Replace `site_out/nfl-data.json` with a validated, key-checked file.

    Staged in a hidden sibling of `site_out`, so a kill never leaves a temp
    file inside the deployed dir. With no key configured nothing is replaced.
    On any failure the existing file is untouched.
    """
    if not (site_out / BUILD_MARKER).is_file():
        raise SiteBuildError(f"refusing to refresh {site_out}: not a booth-review site build")
    nfl, body = load_nfl_site_payload(source)
    stage = site_out.parent / f".{site_out.name}.nfl-refresh-{secrets.token_hex(6)}"
    stage.mkdir()
    try:
        staged = stage / NFL_DATA_FILE
        staged.write_bytes(body)
        if not check_no_key_leak(stage):
            return NflRefreshResult(games=_nfl_game_count(nfl), key_checked=False, replaced=False)
        staged.replace(site_out / NFL_DATA_FILE)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return NflRefreshResult(games=_nfl_game_count(nfl), key_checked=True, replaced=True)


_SPORTS_META_RE = re.compile(r'<meta name="booth-review-sports" content="([a-z,]*)">')


def site_sports(site_out: Path) -> tuple[str, ...]:
    """The sports a built site's index.html lists in its sports meta, such as
    ("cfb",) for a switch-less site or ("cfb", "nfl") for one with the switch.
    Empty when there is no index.html or not exactly one sports meta. This,
    not the env flag, says whether a built site loads nfl-data.json (IN-04).
    """
    index = site_out / "index.html"
    if not index.is_file():
        return ()
    found = _SPORTS_META_RE.findall(index.read_text(encoding="utf-8"))
    if len(found) != 1:
        return ()
    return tuple(sid for sid in found[0].split(",") if sid)


def _remove_empty_parents(path: Path, root: Path) -> None:
    """Remove the now-empty dirs between `path` and `root` (both exclusive)."""
    for parent in path.parents:
        if parent == root or root not in parent.parents:
            return
        try:
            parent.rmdir()
        except OSError:
            return


def _promote_into(stage: Path, site_out: Path) -> None:
    """Move every file of the assembled `stage` that is new to `site_out` or
    differs from it into `site_out`, index.html last.

    Each move is one same-filesystem rename, and index.html is what turns the
    switch on, so until that last rename the site is still the whole,
    switch-less CFB build: a kill at any point never leaves CFB broken. On an
    error the moved files are put back (from copies in a hidden sibling) and
    the added ones removed. Never deletes a file the stage does not replace.
    """
    staged = {p.relative_to(stage) for p in stage.rglob("*") if p.is_file()}
    present = {p.relative_to(site_out) for p in site_out.rglob("*") if p.is_file()}
    if present - staged:
        raise SiteBuildError(f"refusing to patch {site_out}: it holds files the NFL build does not")
    index = Path("index.html")
    changed = sorted(
        rel
        for rel in staged
        if rel not in present or (site_out / rel).read_bytes() != (stage / rel).read_bytes()
    )
    order = [rel for rel in changed if rel != index] + ([index] if index in changed else [])
    root = site_out.resolve()
    backup = Path(tempfile.mkdtemp(prefix=f".{root.name}.nfl-backup-", dir=root.parent))
    moved: list[tuple[Path, bool]] = []
    try:
        for rel in order:
            dest = site_out / rel
            existed = dest.is_file()
            if existed:
                (backup / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, backup / rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            (stage / rel).replace(dest)
            moved.append((rel, existed))
    except Exception:
        for rel, existed in reversed(moved):
            dest = site_out / rel
            if existed:
                (backup / rel).replace(dest)
            else:
                dest.unlink(missing_ok=True)
                _remove_empty_parents(dest, site_out)
        raise
    finally:
        shutil.rmtree(backup, ignore_errors=True)


def add_nfl_to_site(
    *,
    site_out: Path,
    site_src: Path,
    docs: Path,
    nfl_payload: tuple[NflSiteData, bytes],
) -> NflRefreshResult:
    """Turn the NFL switch on in a switch-less site build (iter-2 WR-02, D-20).

    `site_out` must be a booth-review build whose sports meta lists CFB only.
    The site is re-assembled with NFL on, from the site's own site-data.json
    (so every CFB byte, the cache-bust version included, stays the same) and
    `nfl_payload` (an already-validated model and its canonical bytes), in a
    hidden sibling staging dir that is key-checked whole. Only then are the
    new and changed files (the switch and sports meta in index.html, the
    `sports/nfl/` modules, the NFL methodology section and nfl-data.json)
    moved in, index.html last (`_promote_into`).

    With no key configured nothing is changed (replaced=False). On any error,
    a key hit included, `site_out` is left as it was: the switch-less CFB site.
    """
    if not (site_out / BUILD_MARKER).is_file():
        raise SiteBuildError(f"refusing to add NFL to {site_out}: not a booth-review site build")
    if site_sports(site_out) != _CFB_ONLY:
        raise SiteBuildError(f"refusing to add NFL to {site_out}: not a CFB-only site build")
    current = site_out / "site-data.json"
    site, body = load_site_payload(current)
    if body != current.read_bytes():
        raise SiteBuildError(f"refusing to add NFL to {site_out}: site-data.json is not canonical")
    nfl, nfl_body = nfl_payload
    _verify_bundle(site_src)
    stage = _make_staging_dir(site_out)
    try:
        _assemble_into(
            stage, site=site, body=body, site_src=site_src, docs=docs, nfl=True, nfl_body=nfl_body
        )
        if not check_no_key_leak(stage):
            return NflRefreshResult(games=_nfl_game_count(nfl), key_checked=False, replaced=False)
        _promote_into(stage, site_out)
    finally:
        # On a key hit `check_no_key_leak` already removed `stage`; otherwise
        # it holds what was not moved (unchanged files) or a failed build.
        shutil.rmtree(stage, ignore_errors=True)
    return NflRefreshResult(games=_nfl_game_count(nfl), key_checked=True, replaced=True)


def _sport_switch_html(sports: tuple[tuple[str, str], ...]) -> str:
    """The segmented switch, built from constants only (T-999.5-20)."""
    buttons = "".join(
        f'<button type="button" data-sport="{sid}" '
        f'aria-pressed="{"true" if i == 0 else "false"}">{label}</button>'
        for i, (sid, label) in enumerate(sports)
    )
    return (
        f'<div id="sport-switch" class="segmented" role="group" aria-label="Sport">{buttons}</div>'
    )


def _copy_site_source(site_src: Path, out_dir: Path, *, include_nfl: bool = True) -> list[str]:
    """Copy every non-dotfile under `site_src` whose suffix is in
    COPY_SUFFIXES into `out_dir`, preserving relative paths (COPY_SUFFIXES
    also blocks any CSV/data dump from ever reaching dist/site, T-04-14).
    """
    copied: list[str] = []
    for path in sorted(site_src.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(site_src)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if path.suffix not in COPY_SUFFIXES:
            continue
        if not include_nfl and relative.parts[:2] == ("sports", "nfl"):
            continue
        dest = out_dir / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        copied.append(relative.as_posix())
    return copied


def _assemble_into(
    stage: Path,
    *,
    site: SiteData,
    body: bytes,
    site_src: Path,
    docs: Path,
    nfl: bool = False,
    nfl_body: bytes | None = None,
) -> tuple[list[str], list[str], str]:
    """Write the whole site into the (empty) staging dir `stage`: copy the
    source, write site-data.json, cache-bust/fill index.html, render the
    pages, and mark the dir as a booth-review build. Returns the copied
    files, the rendered page files, and the data version.
    """
    copied = _copy_site_source(site_src, stage, include_nfl=nfl)
    atomic_write_bytes(stage / "site-data.json", body)
    if nfl_body is not None:
        atomic_write_bytes(stage / NFL_DATA_FILE, nfl_body)
        copied.append(NFL_DATA_FILE)
    version = hashlib.sha256(body).hexdigest()[:10]

    index_path = stage / "index.html"
    if not index_path.is_file():
        raise SiteBuildError("index.html not found in site source")
    index_text = index_path.read_text(encoding="utf-8")
    if index_text.count(VERSION_TOKEN) != 1:
        raise SiteBuildError(f"index.html: expected exactly one {VERSION_TOKEN} token")
    if index_text.count(FOOTER_TOKEN) != 1:
        raise SiteBuildError(f"index.html: expected exactly one {FOOTER_TOKEN} token")
    for token in (SPORTS_META_TOKEN, SPORT_SWITCH_TOKEN):
        if index_text.count(token) != 1:
            raise SiteBuildError(f"index.html: expected exactly one {token} token")
    sports = SITE_SPORTS if nfl else SITE_SPORTS[:1]
    meta = f'<meta name="booth-review-sports" content="{",".join(sid for sid, _ in sports)}">'
    index_text = index_text.replace(SPORTS_META_TOKEN, meta)
    index_text = index_text.replace(SPORT_SWITCH_TOKEN, _sport_switch_html(sports) if nfl else "")
    index_text = index_text.replace(VERSION_TOKEN, version)
    index_text = index_text.replace(FOOTER_TOKEN, pages.footer_html(site.freshness))
    atomic_write_bytes(index_path, index_text.encode("utf-8"))

    page_files = pages.write_pages(stage, site, docs, nfl=nfl)
    atomic_write_bytes(stage / BUILD_MARKER, b"")
    return copied, page_files, version


def assemble_site(
    *,
    source: Path,
    out_dir: Path,
    site_src: Path,
    docs: Path,
    nfl: bool = False,
    nfl_payload: tuple[NflSiteData, bytes] | None = None,
) -> SiteBuildResult:
    """Assemble `out_dir` from `site_src`, `docs`, and the site-data
    payload at `source` (D-14): validate, copy, cache-bust, render pages,
    then run the key-leak guard last.

    `nfl_payload` is an already-validated NFL model and its canonical bytes
    (`load_nfl_site_payload`), so the CFB build never parses NFL input itself
    and cannot fail on a second, different read of it (WR-03, D-20).

    Everything is built in a hidden sibling staging dir and swapped over
    `out_dir` only once every step, the key-leak guard included, has
    passed (WR-01). A failed build removes its staging dir and leaves
    `out_dir` exactly as it was, so it never leaves behind a half-written,
    unmarked dir that the next run would refuse to overwrite.
    """
    if nfl_payload is not None and not nfl:
        raise SiteBuildError("nfl_payload given while NFL is off")
    if nfl and nfl_payload is None:
        # WR-01 / D-18: the switch never ships without its data file.
        raise SiteBuildError("NFL is on but no NFL data file was given")
    site, body = load_site_payload(source)
    nfl_site, nfl_body = nfl_payload if nfl_payload is not None else (None, None)
    _verify_bundle(site_src)
    _check_out_dir(out_dir)

    stage = _make_staging_dir(out_dir)
    try:
        copied, page_files, version = _assemble_into(
            stage,
            site=site,
            body=body,
            site_src=site_src,
            docs=docs,
            nfl=nfl,
            nfl_body=nfl_body,
        )
        key_checked = check_no_key_leak(stage)
        _swap_into_place(stage, out_dir)
    finally:
        # On success `stage` was renamed to `out_dir`; on a leak,
        # `check_no_key_leak` already removed it. Anything else left over is
        # a failed build's partial output.
        shutil.rmtree(stage, ignore_errors=True)

    files = tuple(sorted({*copied, "site-data.json", *page_files}))
    return SiteBuildResult(
        out_dir=out_dir,
        files=files,
        telecasts=len(site.telecasts.season),
        people=len(site.lookups.people),
        data_version=version,
        key_checked=key_checked,
        nfl_games=_nfl_game_count(nfl_site) if nfl_site is not None else None,
    )
