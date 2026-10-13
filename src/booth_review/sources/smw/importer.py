"""SmwImporter: hand-saved Sports Media Watch charts and their transcriptions (04.19 D-04).

SMW's robots.txt blocks scripts, so its season page and chart images are saved
by hand, transcribed in sessions, diffed and merged (D-01), and then copied into
the vault here with a manual manifest entry per file. Nothing is fetched.

The import validates the whole folder before it writes anything: every chart
PNG must be a real PNG with rows in rows.csv, diff.csv and rows.csv must be
exactly what `diff_passes` and `merge_rows` produce from the passes and the
recorded resolutions, so every figure traces to two passes (T-04.19-04-02).
Messages carry counts and file names only, never a cell value.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from booth_review.config import DataPaths
from booth_review.errors import BoothReviewError, FrozenSeasonError
from booth_review.reference import read_reference_csv_numbered
from booth_review.resolve.names import csv_safe
from booth_review.sources.smw.chart_order import (
    ChartOrderResult,
    identify_season_page,
    parse_chart_order,
    write_chart_order_csv,
)
from booth_review.sources.smw.diff import (
    DIFF_COLUMNS,
    KNOWN_DISAGREEMENT_COLUMNS,
    DiffEntry,
    diff_passes,
    load_resolutions,
    merge_rows,
)
from booth_review.sources.smw.rows import ROWS_COLUMNS, load_rows_csv
from booth_review.transport.cache import FreezeGuard, Manifest, ManifestEntry, RawCache
from booth_review.transport.cache import atomic_write_bytes as _atomic_write_bytes

DEFAULT_INCOMING_DIR = Path("data/incoming/smw")
SOURCE = "smw"

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.png$")
_MAX_EXPLANATION = 200
_MANUAL_ORIGIN = "manual"
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def is_png(content: bytes) -> bool:
    """A PNG signature followed by an IHDR chunk."""
    return content[:8] == _PNG_SIGNATURE and content[12:16] == b"IHDR"


def season_dir(root: Path, season: int) -> Path:
    return root / str(season)


def list_chart_pngs(folder: Path) -> list[str]:
    """Names of the *.png files directly in the season folder."""
    return sorted(p.name for p in folder.glob("*.png") if p.is_file())


@dataclass
class SmwImportResult:
    """The outcome of importing one season's SMW folder (counts only)."""

    season: int
    imported: list[str] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)
    skipped_invalid: list[str] = field(default_factory=list)
    changed_without_force: list[str] = field(default_factory=list)
    missing_charts: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        """Counts for vault.batch_message, count-only."""
        return {
            "imported": len(self.imported),
            "skipped": len(self.skipped_existing) + len(self.skipped_invalid),
        }

    @property
    def has_problems(self) -> bool:
        return bool(
            self.skipped_invalid
            or self.changed_without_force
            or self.missing_charts
            or self.problems
        )


@dataclass(frozen=True)
class _Planned:
    rel: str  # path under raw/smw/<season>/
    content: bytes
    mtime: float


def _csv_rows(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    return [dict(row) for _, row in read_reference_csv_numbered(path, columns, required=True)]


def expected_diff_rows(entries: list[DiffEntry]) -> list[dict[str, str]]:
    return [
        {
            "chart_file": csv_safe(e.chart_file),
            "row": csv_safe(e.row),
            "column": csv_safe(e.column),
            "pass_a": csv_safe(e.pass_a),
            "pass_b": csv_safe(e.pass_b),
            "kind": csv_safe(e.kind),
        }
        for e in entries
    ]


def expected_rows_rows(merged: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{c: csv_safe(row.get(c, "")) for c in ROWS_COLUMNS} for row in merged]


class SmwImporter:
    """Imports a reconciled SMW season folder into the vault."""

    def __init__(self, cache: RawCache, paths: DataPaths) -> None:
        self._cache = cache
        self._paths = paths
        self._manifest = Manifest(paths.manifest)

    def run(
        self, season: int, *, incoming_dir: Path | None = None, force: bool = False
    ) -> SmwImportResult:
        freeze = FreezeGuard.load(self._paths.frozen)
        if freeze.is_frozen(SOURCE, season):
            raise FrozenSeasonError(f"cannot import frozen season: {SOURCE} {season}")

        result = SmwImportResult(season=season)
        root = (
            incoming_dir if incoming_dir is not None else season_dir(DEFAULT_INCOMING_DIR, season)
        )
        plan, url = self._validate(root, season, result)
        if result.has_problems or plan is None or url is None:
            return result

        dest_root = self._paths.raw / SOURCE / str(season)
        to_write: list[_Planned] = []
        for item in plan:
            dest = dest_root / item.rel
            if dest.is_file():
                if dest.read_bytes() == item.content:
                    result.skipped_existing.append(item.rel)
                    continue
                if not force:
                    result.changed_without_force.append(item.rel)
                    continue
            to_write.append(item)
        if result.changed_without_force:
            return result  # all or nothing: rerun with --force to overwrite

        for item in to_write:
            self._write(season, url, dest_root / item.rel, item)
            result.imported.append(item.rel)
        return result

    # -- validation ---------------------------------------------------------------

    def _validate(
        self, folder: Path, season: int, result: SmwImportResult
    ) -> tuple[list[_Planned] | None, str | None]:
        page_path = folder / "season-page.html"
        if not page_path.is_file():
            result.problems.append("season-page.html is missing")
            return None, None
        page_bytes = page_path.read_bytes()
        identity = identify_season_page(page_bytes.decode("utf-8", errors="replace"))
        if identity is None or identity[0] != season:
            result.problems.append("season-page.html does not name this season")
            return None, None
        url = identity[1]

        pngs: dict[str, bytes] = {}
        for name in list_chart_pngs(folder):
            content = (folder / name).read_bytes()
            if not _PNG_NAME_RE.match(name) or not is_png(content):
                result.skipped_invalid.append(name)
                continue
            pngs[name] = content
        if result.skipped_invalid:
            return None, None
        if not pngs:
            result.problems.append("no chart PNGs in the folder")
            return None, None

        try:
            order = parse_chart_order(page_bytes.decode("utf-8", errors="replace"), set(pngs))
            if order.unreferenced:
                result.problems.append(
                    f"{len(order.unreferenced)} chart(s) not listed on the season page"
                )
            tdir = folder / "transcription"
            pass_a, pass_b, pass_c = tdir / "pass-a", tdir / "pass-b", tdir / "pass-c"
            if not pass_a.is_dir() or not pass_b.is_dir():
                result.problems.append("pass-a or pass-b folder is missing")
                return None, None

            rows = _csv_rows_checked(tdir / "rows.csv", result)
            if rows is None:
                return None, None
            row_charts = {r["chart_file"] for r in rows}
            result.missing_charts = sorted(set(pngs) - row_charts)
            if result.missing_charts or result.problems:
                return None, None

            charts = sorted(pngs)
            diff = diff_passes(pass_a, pass_b, charts)
            diff_path = tdir / "diff.csv"
            if not diff_path.is_file():
                result.problems.append("diff.csv is missing")
                return None, None
            if _csv_rows(diff_path, DIFF_COLUMNS) != expected_diff_rows(diff):
                result.problems.append("diff.csv does not match the passes")
                return None, None

            resolutions = load_resolutions(tdir / "resolutions.csv")
            merged = merge_rows(
                pass_a,
                pass_c if pass_c.is_dir() else None,
                diff,
                resolutions,
                order.entries,
            )
            if rows != expected_rows_rows(merged):
                result.problems.append("rows.csv does not match the merge")
                return None, None

            known = tdir / "known_disagreements.csv"
            if known.is_file():
                problem = _check_known(known, rows)
                if problem:
                    result.problems.append(problem)
                    return None, None
        except BoothReviewError as exc:
            result.problems.append(f"{type(exc).__name__}: {exc}")
            return None, None

        return self._plan(folder, page_path, pngs, order, tdir), url

    def _plan(
        self,
        folder: Path,
        page_path: Path,
        pngs: dict[str, bytes],
        order: ChartOrderResult,
        tdir: Path,
    ) -> list[_Planned]:
        page_mtime = page_path.stat().st_mtime
        plan = [_Planned("season-page.html", page_path.read_bytes(), page_mtime)]
        for name, content in sorted(pngs.items()):
            plan.append(_Planned(f"charts/{name}", content, (folder / name).stat().st_mtime))
        with tempfile.TemporaryDirectory() as tmp:
            order_path = Path(tmp) / "chart_order.csv"
            write_chart_order_csv(order_path, order)
            plan.append(_Planned("chart_order.csv", order_path.read_bytes(), page_mtime))
        for path in sorted(p for p in tdir.rglob("*.csv") if p.is_file()):
            rel = path.relative_to(tdir).as_posix()
            plan.append(_Planned(f"transcription/{rel}", path.read_bytes(), path.stat().st_mtime))
        return plan

    # -- writing ------------------------------------------------------------------

    def _write(self, season: int, url: str, dest: Path, item: _Planned) -> None:
        _atomic_write_bytes(dest, item.content)
        entry = ManifestEntry(
            url=url,
            source=SOURCE,
            season=season,
            kind="page",
            fetched_at=datetime.now(UTC).strftime(_TIME_FORMAT),
            status=200,
            etag=None,
            last_modified=None,
            sha256=hashlib.sha256(item.content).hexdigest(),
            path=f"{SOURCE}/{season}/{item.rel}",
            bytes=len(item.content),
            final_url=url,
            origin=_MANUAL_ORIGIN,
            saved_at=datetime.fromtimestamp(item.mtime, UTC).strftime(_TIME_FORMAT),
        )
        self._manifest.append(entry)


def _csv_rows_checked(path: Path, result: SmwImportResult) -> list[dict[str, str]] | None:
    if not path.is_file():
        result.problems.append("rows.csv is missing")
        return None
    # Strict load (schema, duplicates, superseded_by targets), then raw cells.
    load_rows_csv(path)
    return _csv_rows(path, ROWS_COLUMNS)


def _check_known(path: Path, rows: list[dict[str, str]]) -> str | None:
    existing = {(r["chart_file"], r["row"]) for r in rows}
    for line_no, raw in read_reference_csv_numbered(
        path, KNOWN_DISAGREEMENT_COLUMNS, required=True
    ):
        if (raw["chart_file"], raw["row"]) not in existing:
            return f"known_disagreements.csv: line {line_no}: row not in rows.csv"
        explanation = raw["explanation"].strip()
        if not explanation or len(explanation) > _MAX_EXPLANATION:
            return f"known_disagreements.csv: line {line_no}: explanation must be 1-200 characters"
    return None
