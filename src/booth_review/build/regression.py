"""The regression guard (AUDIT-03): compare a build's per-season metrics
against the last *accepted* build baseline and the Phase 2 completeness
counts, and report blocked when either drops.

The baseline (`audit/build_baseline.csv`) changes only through an explicit
`accept_baseline` call -- Plan 11 exposes this as `booth-review build
--accept-baseline`. A missing baseline means "nothing accepted yet" (every
build passes trivially until the first accept); a corrupt baseline raises
`VaultStateError` rather than silently being treated as absent or as a pass
(T-03-40) -- tampering with the baseline file is a security-relevant event,
not a routine miss.

The Phase 2 completeness counts (`audit/completeness.json`, from
`audit.completeness.write_completeness`) are the starting input baseline
(D-06/roadmap): even before any build has ever been accepted, a build whose
raw inputs (506 pages, RR records cached, CFBD endpoint files) are thinner
than what Phase 2 already collected is blocked.

Every reason string names only a season, a metric, and numbers (T-03-41) --
never a team, announcer, or figure. An increase in any metric never blocks.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from booth_review.audit.completeness import CFBD_SEASON_ENDPOINTS
from booth_review.build.io import write_review_csv
from booth_review.config import DataPaths
from booth_review.errors import VaultStateError

if TYPE_CHECKING:
    from booth_review.build.tables import BuildTables

METRIC_COLUMNS: tuple[str, ...] = (
    "season",
    "rr_records",
    "rated_telecasts",
    "records_with_crew",
    "records_with_506_crew",
    "match_rate",
    "sports506_pages",
    "rr_records_cached",
    "cfbd_files",
)

# The header of a baseline accepted before records_with_506_crew existed
# (04.3 IN-06). It still loads; that metric then has no baseline yet, so it
# is not compared until the next --accept-baseline writes it.
_LEGACY_METRIC_COLUMNS: tuple[str, ...] = tuple(
    column for column in METRIC_COLUMNS if column != "records_with_506_crew"
)

_REGRESSION_COLUMNS: tuple[str, ...] = ("season", "metric", "baseline", "current", "status")

# The METRIC_COLUMNS fields compared directly against an accepted baseline
# (every column except "season" itself).
_BASELINE_METRICS: tuple[str, ...] = METRIC_COLUMNS[1:]

# completeness.json source -> (its own count key, the SeasonMetrics field it
# corresponds to). "cached" is check_506's/check_rr's own counts key;
# "present" is check_cfbd's -- see audit/completeness.py.
_COMPLETENESS_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("sports506", "cached", "sports506_pages"),
    ("ratingsref", "cached", "rr_records_cached"),
    ("cfbd", "present", "cfbd_files"),
)

_RATE_DECIMALS = 4


@dataclass(frozen=True)
class SeasonMetrics:
    """One season's build metrics -- the AUDIT-03 comparison unit."""

    season: int
    rr_records: int
    rated_telecasts: int
    records_with_crew: int
    # None only when loaded from a legacy baseline that predates the column.
    records_with_506_crew: int | None
    match_rate: float | None
    sports506_pages: int
    rr_records_cached: int
    cfbd_files: int


@dataclass(frozen=True)
class RegressionResult:
    """The guard's verdict: whether the build is blocked, why, and how many
    seasons the comparison covered."""

    blocked: bool
    reasons: tuple[str, ...]
    compared_seasons: int
    note: str


def build_metrics(tables: BuildTables, paths: DataPaths) -> list[SeasonMetrics]:
    """One `SeasonMetrics` per season the build touched, sorted by season.

    `rr_records`/`rated_telecasts`/`records_with_crew`/`match_rate` come from
    `tables.diagnostics` (the same counts `build.tables.main` prints);
    `records_with_506_crew` is `records_with_crew` before crew overrides, so
    an override covering a lost 506 crew cannot hide the loss;
    `sports506_pages`/`rr_records_cached`/`cfbd_files` are read straight from
    the vault's raw cache, independent of anything the build itself joined,
    so a regression in raw collection is caught even if the join layer would
    otherwise hide it.
    """
    result: list[SeasonMetrics] = []
    for season, diag in sorted(tables.diagnostics.per_season.items()):
        sports506_dir = paths.raw / "sports506" / str(season)
        sports506_pages = (
            len(list(sports506_dir.glob("wk-*.html"))) if sports506_dir.is_dir() else 0
        )

        rr_dir = paths.raw / "ratingsref" / "telecast" / str(season)
        rr_records_cached = len(list(rr_dir.glob("*.json"))) if rr_dir.is_dir() else 0

        cfbd_files = sum(
            1
            for endpoint in CFBD_SEASON_ENDPOINTS
            if (paths.raw / "cfbd" / endpoint / f"{season}.json").is_file()
        )

        result.append(
            SeasonMetrics(
                season=season,
                rr_records=diag.get("rr_records", 0),
                rated_telecasts=diag.get("rated_telecasts", 0),
                records_with_crew=diag.get("records_with_crew", 0),
                records_with_506_crew=diag.get("records_with_506_crew", 0),
                match_rate=tables.diagnostics.join08_by_season.get(season),
                sports506_pages=sports506_pages,
                rr_records_cached=rr_records_cached,
                cfbd_files=cfbd_files,
            )
        )
    return result


def _metrics_rows(metrics: Sequence[SeasonMetrics]) -> list[dict[str, object]]:
    return [
        {
            "season": m.season,
            "rr_records": m.rr_records,
            "rated_telecasts": m.rated_telecasts,
            "records_with_crew": m.records_with_crew,
            "records_with_506_crew": m.records_with_506_crew,
            "match_rate": m.match_rate,
            "sports506_pages": m.sports506_pages,
            "rr_records_cached": m.rr_records_cached,
            "cfbd_files": m.cfbd_files,
        }
        for m in sorted(metrics, key=lambda m: m.season)
    ]


def load_baseline(paths: DataPaths) -> dict[int, SeasonMetrics] | None:
    """Read `audit/build_baseline.csv` into {season: SeasonMetrics}.

    Returns None when the file is missing (nothing accepted yet). A legacy
    header (no `records_with_506_crew`) loads with that metric as None. Raises
    VaultStateError, naming only the file and line, on a header that matches
    neither METRIC_COLUMNS nor the legacy header, a non-integer count, or a duplicate season
    (T-03-40: a tampered or corrupt baseline never silently passes or is
    treated as absent).
    """
    path = paths.audit / "build_baseline.csv"
    if not path.is_file():
        return None

    try:
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            try:
                header = next(reader)
            except StopIteration:
                raise VaultStateError(f"{path}: empty baseline file") from None
            columns = tuple(header)
            if columns not in (METRIC_COLUMNS, _LEGACY_METRIC_COLUMNS):
                raise VaultStateError(
                    f"{path}: header {columns!r} does not match expected {METRIC_COLUMNS!r}"
                )

            result: dict[int, SeasonMetrics] = {}
            for line_no, raw_row in enumerate(reader, start=2):
                if not raw_row or all(cell.strip() == "" for cell in raw_row):
                    continue
                if len(raw_row) != len(columns):
                    raise VaultStateError(
                        f"{path}: line {line_no}: expected {len(columns)} columns"
                    )
                values = dict(zip(columns, raw_row, strict=True))
                try:
                    season = int(values["season"])
                    metrics = SeasonMetrics(
                        season=season,
                        rr_records=int(values["rr_records"]),
                        rated_telecasts=int(values["rated_telecasts"]),
                        records_with_crew=int(values["records_with_crew"]),
                        records_with_506_crew=(
                            int(values["records_with_506_crew"])
                            if "records_with_506_crew" in values
                            else None
                        ),
                        match_rate=(
                            float(values["match_rate"]) if values["match_rate"] != "" else None
                        ),
                        sports506_pages=int(values["sports506_pages"]),
                        rr_records_cached=int(values["rr_records_cached"]),
                        cfbd_files=int(values["cfbd_files"]),
                    )
                except ValueError as exc:
                    raise VaultStateError(f"{path}: line {line_no}: non-integer count") from exc
                if season in result:
                    raise VaultStateError(f"{path}: line {line_no}: duplicate season {season}")
                result[season] = metrics
    except OSError as exc:
        raise VaultStateError(f"could not load baseline from {path}") from exc
    return result


def load_completeness_counts(paths: DataPaths) -> dict[int, dict[str, int]] | None:
    """Read `audit/completeness.json` into {season: {sports506, ratingsref,
    cfbd}} input counts (the Phase 2 starting baseline, D-06).

    Returns None when the file is missing. Raises VaultStateError on a
    missing/non-list "cells" array or a malformed cell (same
    missing-vs-corrupt distinction as job/catchup.py's job-state loader).
    """
    path = paths.audit / "completeness.json"
    if not path.is_file():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VaultStateError(f"could not load completeness counts from {path}") from exc

    if not isinstance(data, dict) or not isinstance(data.get("cells"), list):
        raise VaultStateError(f"{path}: expected an object with a 'cells' array")

    count_key_by_source = {source: count_key for source, count_key, _field in _COMPLETENESS_FIELDS}

    result: dict[int, dict[str, int]] = {}
    for cell in data["cells"]:
        if not isinstance(cell, dict):
            raise VaultStateError(f"{path}: malformed cell entry")
        season = cell.get("season")
        source = cell.get("source")
        counts = cell.get("counts")
        if (
            not isinstance(season, int)
            or source not in count_key_by_source
            or not isinstance(counts, dict)
        ):
            raise VaultStateError(f"{path}: malformed cell entry")
        count_key = count_key_by_source[source]
        value = counts.get(count_key)
        if not isinstance(value, int):
            raise VaultStateError(
                f"{path}: season {season} {source} cell missing integer '{count_key}'"
            )
        result.setdefault(season, {})[source] = value
    return result


def _match_rate_dropped(
    season: int, current: float | None, baseline: float | None
) -> tuple[bool, str | None]:
    if baseline is None:
        return False, None
    baseline_rounded = round(baseline, _RATE_DECIMALS)
    current_rounded = round(current, _RATE_DECIMALS) if current is not None else None
    if current_rounded is None or current_rounded < baseline_rounded:
        return True, (
            f"season {season}: match_rate {current_rounded} below baseline {baseline_rounded}"
        )
    return False, None


def _count_dropped(
    season: int, metric: str, current: int | None, baseline: int | None
) -> tuple[bool, str | None]:
    if baseline is None:
        return False, None  # a metric the accepted baseline predates: nothing to compare
    if current is None or current < baseline:
        return True, f"season {season}: {metric} {current} below baseline {baseline}"
    return False, None


def _compare_baseline(
    current_by_season: Mapping[int, SeasonMetrics], baseline: Mapping[int, SeasonMetrics]
) -> tuple[list[dict[str, object]], list[str]]:
    comparisons: list[dict[str, object]] = []
    reasons: list[str] = []

    for season in sorted(baseline):
        base = baseline[season]
        current = current_by_season.get(season)
        if current is None:
            reasons.append(f"season {season}: missing from current build")
            for metric in _BASELINE_METRICS:
                comparisons.append(
                    {
                        "season": season,
                        "metric": metric,
                        "baseline": getattr(base, metric),
                        "current": None,
                        "status": "blocked",
                    }
                )
            continue

        for metric in _BASELINE_METRICS:
            base_value = getattr(base, metric)
            current_value = getattr(current, metric)
            if metric == "match_rate":
                blocked, reason = _match_rate_dropped(season, current_value, base_value)
            else:
                blocked, reason = _count_dropped(season, metric, current_value, base_value)
            comparisons.append(
                {
                    "season": season,
                    "metric": metric,
                    "baseline": base_value,
                    "current": current_value,
                    "status": "blocked" if blocked else "ok",
                }
            )
            if blocked and reason is not None:
                reasons.append(reason)

    return comparisons, reasons


def _compare_completeness(
    current_by_season: Mapping[int, SeasonMetrics], completeness: Mapping[int, Mapping[str, int]]
) -> tuple[list[dict[str, object]], list[str]]:
    comparisons: list[dict[str, object]] = []
    reasons: list[str] = []

    for season in sorted(completeness):
        counts = completeness[season]
        current = current_by_season.get(season)
        for source, _count_key, field in _COMPLETENESS_FIELDS:
            expected = counts.get(source)
            if expected is None:
                continue
            current_value = getattr(current, field) if current is not None else None
            metric = f"{source}_completeness"
            blocked, reason = _count_dropped(season, metric, current_value, expected)
            comparisons.append(
                {
                    "season": season,
                    "metric": metric,
                    "baseline": expected,
                    "current": current_value,
                    "status": "blocked" if blocked else "ok",
                }
            )
            if blocked and reason is not None:
                reasons.append(reason)

    return comparisons, reasons


def check_regression(
    current: Sequence[SeasonMetrics],
    baseline: Mapping[int, SeasonMetrics] | None,
    completeness: Mapping[int, Mapping[str, int]] | None,
) -> RegressionResult:
    """Compare `current` against the accepted `baseline` and the Phase 2
    `completeness` counts. With no baseline, only the completeness
    comparison runs; with neither, the result is never blocked ("no
    baseline"). An increase in any metric never blocks.
    """
    current_by_season = {m.season: m for m in current}
    reasons: list[str] = []
    compared_seasons: set[int] = set()

    if baseline:
        _, baseline_reasons = _compare_baseline(current_by_season, baseline)
        reasons.extend(baseline_reasons)
        compared_seasons.update(baseline)

    if completeness:
        _, completeness_reasons = _compare_completeness(current_by_season, completeness)
        reasons.extend(completeness_reasons)
        compared_seasons.update(completeness)

    if not baseline and not completeness:
        note = "no baseline"
    elif baseline and completeness:
        note = "compared against the accepted baseline and the Phase 2 completeness counts"
    elif baseline:
        note = "compared against the accepted baseline (no completeness counts on file)"
    else:
        note = "compared against the Phase 2 completeness counts (no accepted baseline yet)"

    return RegressionResult(
        blocked=bool(reasons),
        reasons=tuple(reasons),
        compared_seasons=len(compared_seasons),
        note=note,
    )


def accept_baseline(paths: DataPaths, metrics: Sequence[SeasonMetrics]) -> list[str]:
    """Write `metrics` as the new accepted baseline (`audit/build_baseline.csv`),
    the only way that file ever changes (Plan 11's `--accept-baseline`)."""
    write_review_csv(paths.audit / "build_baseline.csv", METRIC_COLUMNS, _metrics_rows(metrics))
    return ["audit/build_baseline.csv"]


def write_metrics(paths: DataPaths, metrics: Sequence[SeasonMetrics]) -> list[str]:
    """Write this build's own metrics (`audit/build_metrics.csv`), independent
    of whether they were ever accepted as the baseline."""
    write_review_csv(paths.audit / "build_metrics.csv", METRIC_COLUMNS, _metrics_rows(metrics))
    return ["audit/build_metrics.csv"]


def write_regression_report(
    paths: DataPaths,
    current: Sequence[SeasonMetrics],
    baseline: Mapping[int, SeasonMetrics] | None,
    completeness: Mapping[int, Mapping[str, int]] | None,
    result: RegressionResult,
) -> list[str]:
    """Write `audit/regression.csv` (season, metric, baseline, current,
    status), one row per metric this run actually compared -- every row here
    is independently derived from `current`/`baseline`/`completeness`, so it
    can never disagree with `result.reasons`.
    """
    current_by_season = {m.season: m for m in current}
    rows: list[dict[str, object]] = []
    if baseline:
        baseline_rows, _ = _compare_baseline(current_by_season, baseline)
        rows.extend(baseline_rows)
    if completeness:
        completeness_rows, _ = _compare_completeness(current_by_season, completeness)
        rows.extend(completeness_rows)

    def _sort_key(row: dict[str, object]) -> tuple[int, str]:
        season = row["season"]
        return (season if isinstance(season, int) else 0, str(row["metric"]))

    rows.sort(key=_sort_key)
    write_review_csv(paths.audit / "regression.csv", _REGRESSION_COLUMNS, rows)
    return ["audit/regression.csv"]
