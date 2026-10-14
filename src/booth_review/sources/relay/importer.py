"""RelayImporter: hand-read MLB relay crews into the private vault (D-09, D-20).

A session reads a blog's posts and the press pages they cite, and stages the
extracted facts as one CSV in `data/incoming/mlb-relay/`. This importer
validates it strictly and copies it to `raw/mlb/relay/crew_relays.csv`. Nothing
is fetched. Messages carry line numbers and column names only, never a cell.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from booth_review.config import DataPaths
from booth_review.errors import BoothReviewError, FrozenSeasonError
from booth_review.mlb.layout import MLB_RELAY_PATH
from booth_review.transport.cache import FreezeGuard, Manifest, ManifestEntry, RawCache
from booth_review.transport.cache import atomic_write_bytes as _atomic_write_bytes

SOURCE = "mlb_relay"
DEFAULT_RELAY_DIR = Path("data/incoming/mlb-relay")
RELAY_COLUMNS: tuple[str, ...] = (
    "season",
    "game_date",
    "away_club",
    "home_club",
    "game_number",
    "network_id",
    "pbp",
    "analyst_1",
    "analyst_2",
    "post_url",
    "press_name",
    "press_url",
    "read_date",
)
RELAY_POST_HOSTS = frozenset({"tamirmoore.blogspot.com"})
RELAY_MAX_ROWS = 2000
RELAY_MAX_BYTES = 1_000_000

_REQUIRED = ("away_club", "home_club", "network_id", "pbp", "post_url", "press_url")
_FORMULA_START = ("=", "+", "-", "@")
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class RelayValidationError(BoothReviewError):
    """A relay CSV problem; the message holds line numbers and column names only."""


@dataclass(frozen=True)
class RelayRow:
    line: int
    season: int
    game_date: date
    away_club: str
    home_club: str
    game_number: int
    network_id: str
    pbp: str
    analyst_1: str
    analyst_2: str
    post_url: str
    press_name: str
    press_url: str
    read_date: str


def _https_host(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return None
    return parts.hostname.lower()


def _parse_iso(value: str) -> date | None:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def validate_relay_csv(content: bytes) -> list[RelayRow]:
    """Parse and validate a staged relay CSV, or raise RelayValidationError."""
    if len(content) > RELAY_MAX_BYTES:
        raise RelayValidationError("file exceeds the size cap")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RelayValidationError("file is not valid UTF-8") from exc
    reader = csv.reader(io.StringIO(text, newline=""))
    header = next(reader, None)
    if header is None:
        raise RelayValidationError("file is empty")
    if tuple(header) != RELAY_COLUMNS:
        pos = next(
            (i + 1 for i, (a, b) in enumerate(zip(header, RELAY_COLUMNS, strict=False)) if a != b),
            min(len(header), len(RELAY_COLUMNS)) + 1,
        )
        raise RelayValidationError(f"header mismatch at column position {pos}")

    rows: list[RelayRow] = []
    seen: dict[tuple[date, str, str, int], int] = {}
    for record in reader:
        line = reader.line_num
        if not record:
            continue
        if len(rows) >= RELAY_MAX_ROWS:
            raise RelayValidationError("file exceeds the row cap")
        if len(record) != len(RELAY_COLUMNS):
            raise RelayValidationError(f"line {line}: wrong number of columns")
        cells = dict(zip(RELAY_COLUMNS, record, strict=True))
        for col, cell in cells.items():
            if cell.startswith(_FORMULA_START):
                raise RelayValidationError(f"line {line}: column {col}: formula-like cell")
        for col in _REQUIRED:
            if not cells[col].strip():
                raise RelayValidationError(f"line {line}: column {col}: empty")
        game_date = _parse_iso(cells["game_date"])
        if game_date is None:
            raise RelayValidationError(f"line {line}: column game_date: not ISO YYYY-MM-DD")
        if not cells["season"].isdigit() or int(cells["season"]) != game_date.year:
            raise RelayValidationError(f"line {line}: column season: not the game_date year")
        if cells["game_number"] not in {"0", "1", "2"}:
            raise RelayValidationError(f"line {line}: column game_number: not 0, 1 or 2")
        if _https_host(cells["post_url"]) not in RELAY_POST_HOSTS:
            raise RelayValidationError(f"line {line}: column post_url: not https on the allow-list")
        if _https_host(cells["press_url"]) is None:
            raise RelayValidationError(f"line {line}: column press_url: not https")
        if cells["read_date"] and _parse_iso(cells["read_date"]) is None:
            raise RelayValidationError(f"line {line}: column read_date: not ISO YYYY-MM-DD")
        key = (game_date, cells["away_club"], cells["home_club"], int(cells["game_number"]))
        if key in seen:
            raise RelayValidationError(f"lines {seen[key]} and {line}: duplicate game")
        seen[key] = line
        rows.append(
            RelayRow(
                line=line,
                season=int(cells["season"]),
                game_date=game_date,
                away_club=cells["away_club"],
                home_club=cells["home_club"],
                game_number=int(cells["game_number"]),
                network_id=cells["network_id"],
                pbp=cells["pbp"],
                analyst_1=cells["analyst_1"],
                analyst_2=cells["analyst_2"],
                post_url=cells["post_url"],
                press_name=cells["press_name"],
                press_url=cells["press_url"],
                read_date=cells["read_date"],
            )
        )
    return rows


@dataclass
class RelayImportResult:
    """Counts only; never a cell value."""

    rows: int = 0
    written: int = 0
    skipped_existing: int = 0
    changed_without_force: int = 0
    problems: int = 0

    def counts(self) -> dict[str, int]:
        return {
            "rows": self.rows,
            "written": self.written,
            "skipped_existing": self.skipped_existing,
            "changed_without_force": self.changed_without_force,
        }

    @property
    def has_problems(self) -> bool:
        return bool(self.problems or self.changed_without_force)


class RelayImporter:
    """Imports the staged relay crew CSV into the vault."""

    def __init__(self, cache: RawCache, paths: DataPaths) -> None:
        self._cache = cache
        self._paths = paths
        self._manifest = Manifest(paths.manifest)

    def run(
        self, season: int, *, src: Path | None = None, force: bool = False
    ) -> RelayImportResult:
        freeze = FreezeGuard.load(self._paths.frozen)
        if freeze.is_frozen(SOURCE, season):
            raise FrozenSeasonError(f"cannot import frozen season: {SOURCE} {season}")

        result = RelayImportResult()
        folder = src if src is not None else DEFAULT_RELAY_DIR
        files = sorted(p for p in folder.glob("*.csv") if p.is_file()) if folder.is_dir() else []
        if len(files) != 1:
            result.problems = 1  # zero or several staged files
            return result
        content = files[0].read_bytes()
        try:
            rows = validate_relay_csv(content)
        except RelayValidationError:
            result.problems = 1
            raise
        result.rows = len(rows)

        dest = self._paths.raw / MLB_RELAY_PATH
        if dest.is_file():
            if dest.read_bytes() == content:
                result.skipped_existing = 1
                return result
            if not force:
                result.changed_without_force = 1
                return result
        _atomic_write_bytes(dest, content)
        self._manifest.append(
            ManifestEntry(
                url=rows[0].post_url if rows else "",
                source=SOURCE,
                season=season,
                kind="page",
                fetched_at=datetime.now(UTC).strftime(_TIME_FORMAT),
                status=200,
                etag=None,
                last_modified=None,
                sha256=hashlib.sha256(content).hexdigest(),
                path=MLB_RELAY_PATH,
                bytes=len(content),
                final_url=rows[0].post_url if rows else "",
                origin="manual",
                saved_at=datetime.fromtimestamp(files[0].stat().st_mtime, UTC).strftime(
                    _TIME_FORMAT
                ),
            )
        )
        result.written = 1
        return result
