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
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from booth_review.build import pages
from booth_review.build.site_data import _contract_error_summary
from booth_review.config import load_cfbd_key
from booth_review.contract.models import SiteData, validate_site_data
from booth_review.errors import MissingApiKeyError, SiteBuildError
from booth_review.transport.cache import atomic_write_bytes

PLOTLY_BUNDLE = "vendor/plotly-4.1.1.min.js"
PLOTLY_SHA256 = "3b6e15d45dbb7fca5bd2094291e961ddc5472cd887009e6009a56dab668d721f"
COPY_SUFFIXES = frozenset({".html", ".js", ".css"})
BUILD_MARKER = ".booth-review-site"
VERSION_TOKEN = "__SITE_DATA_VERSION__"
FOOTER_TOKEN = "<!-- booth-review:footer -->"

_DEFAULT_FIXTURE = Path("tests/fixtures/contract/site-data.fixture.json")


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
    """Refuse a vendored Plotly bundle whose digest isn't PLOTLY_SHA256
    (T-04-16): a tampered or wrong-version bundle never reaches dist/site.
    """
    bundle_path = site_src / PLOTLY_BUNDLE
    if not bundle_path.is_file():
        raise SiteBuildError("vendored Plotly bundle not found")
    digest = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    if digest != PLOTLY_SHA256:
        raise SiteBuildError("vendored Plotly bundle digest mismatch")


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
            raise SiteBuildError(f"CFBD key found in build output: {relative}; output removed")
    return True


def _copy_site_source(site_src: Path, out_dir: Path) -> list[str]:
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
        dest = out_dir / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        copied.append(relative.as_posix())
    return copied


def _assemble_into(
    stage: Path, *, site: SiteData, body: bytes, site_src: Path, docs: Path
) -> tuple[list[str], list[str], str]:
    """Write the whole site into the (empty) staging dir `stage`: copy the
    source, write site-data.json, cache-bust/fill index.html, render the
    pages, and mark the dir as a booth-review build. Returns the copied
    files, the rendered page files, and the data version.
    """
    copied = _copy_site_source(site_src, stage)
    atomic_write_bytes(stage / "site-data.json", body)
    version = hashlib.sha256(body).hexdigest()[:10]

    index_path = stage / "index.html"
    if not index_path.is_file():
        raise SiteBuildError("index.html not found in site source")
    index_text = index_path.read_text(encoding="utf-8")
    if index_text.count(VERSION_TOKEN) != 1:
        raise SiteBuildError(f"index.html: expected exactly one {VERSION_TOKEN} token")
    if index_text.count(FOOTER_TOKEN) != 1:
        raise SiteBuildError(f"index.html: expected exactly one {FOOTER_TOKEN} token")
    index_text = index_text.replace(VERSION_TOKEN, version)
    index_text = index_text.replace(FOOTER_TOKEN, pages.footer_html(site.freshness))
    atomic_write_bytes(index_path, index_text.encode("utf-8"))

    page_files = pages.write_pages(stage, site, docs)
    atomic_write_bytes(stage / BUILD_MARKER, b"")
    return copied, page_files, version


def assemble_site(*, source: Path, out_dir: Path, site_src: Path, docs: Path) -> SiteBuildResult:
    """Assemble `out_dir` from `site_src`, `docs`, and the site-data
    payload at `source` (D-14): validate, copy, cache-bust, render pages,
    then run the key-leak guard last.

    Everything is built in a hidden sibling staging dir and swapped over
    `out_dir` only once every step, the key-leak guard included, has
    passed (WR-01). A failed build removes its staging dir and leaves
    `out_dir` exactly as it was, so it never leaves behind a half-written,
    unmarked dir that the next run would refuse to overwrite.
    """
    site, body = load_site_payload(source)
    _verify_bundle(site_src)
    _check_out_dir(out_dir)

    stage = _make_staging_dir(out_dir)
    try:
        copied, page_files, version = _assemble_into(
            stage, site=site, body=body, site_src=site_src, docs=docs
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
    )
