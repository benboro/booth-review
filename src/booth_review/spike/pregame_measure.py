"""The pre-game x-axis measure (SPIKE-04): 2014-2025 coverage by season for
closing spread and pregame win probability, the choice between them, and the
orientation helpers ("closer game plots further right") the site's x-axis
toggle (SITE-03) will use.

Nothing here builds an HTTP client; every fact comes from CFBD files already
cached under data/vault/raw/cfbd/.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from booth_review.config import DataPaths
from booth_review.sources.cfbd.parser import CfbdLine, parse_games, parse_lines, parse_wp_pregame
from booth_review.transport.cache import atomic_write_bytes

_SEASONS: tuple[int, ...] = tuple(range(2014, 2026))
_COVERAGE_GAP_PCT = 2.0

Measure = Literal["closing_spread", "pregame_wp"]


@dataclass(frozen=True)
class SeasonCoverage:
    """One season's universe size and pre-game-measure coverage counts."""

    season: int
    universe: int
    wp_covered: int
    spread_covered: int
    provider_counts: dict[str, int]

    @property
    def wp_pct(self) -> float:
        return round(100 * self.wp_covered / self.universe, 1) if self.universe else 0.0

    @property
    def spread_pct(self) -> float:
        return round(100 * self.spread_covered / self.universe, 1) if self.universe else 0.0


@dataclass(frozen=True)
class MeasureChoice:
    measure: Measure
    reason: str
    min_coverage: float


def coverage_by_season(paths: DataPaths, seasons: Iterable[int]) -> list[SeasonCoverage]:
    """For each season, the JOIN-07 universe (completed games with at least
    one FBS team), how many of those have a non-null pregame win probability,
    how many have a non-null closing spread from any provider, and the
    per-provider spread counts within that universe.
    """
    result: list[SeasonCoverage] = []
    for season in seasons:
        games_path = paths.raw / "cfbd" / "games" / f"{season}.json"
        if not games_path.is_file():
            continue
        games = parse_games(games_path.read_bytes())
        universe_ids = {
            g.id
            for g in games
            if g.completed and (g.home_classification == "fbs" or g.away_classification == "fbs")
        }

        wp_path = paths.raw / "cfbd" / "wp_pregame" / f"{season}.json"
        wp_ids: set[int] = set()
        if wp_path.is_file():
            wp_ids = {row.game_id for row in parse_wp_pregame(wp_path.read_bytes())}

        lines_path = paths.raw / "cfbd" / "lines" / f"{season}.json"
        provider_counts: Counter[str] = Counter()
        spread_game_ids: set[int] = set()
        if lines_path.is_file():
            for line in parse_lines(lines_path.read_bytes()):
                if line.game_id in universe_ids and line.spread is not None:
                    provider_counts[line.provider] += 1
                    spread_game_ids.add(line.game_id)

        result.append(
            SeasonCoverage(
                season=season,
                universe=len(universe_ids),
                wp_covered=len(universe_ids & wp_ids),
                spread_covered=len(spread_game_ids),
                provider_counts=dict(provider_counts),
            )
        )
    return result


def choose_measure(coverages: Sequence[SeasonCoverage]) -> MeasureChoice:
    """Pick the measure with the higher minimum season coverage when the gap
    is at least _COVERAGE_GAP_PCT points; within that gap, pick closing
    spread (points are the more familiar unit for readers, and the CFBD
    inventory separately checks how closely pregame WP tracks the spread).
    """
    min_wp = min((c.wp_pct for c in coverages), default=0.0)
    min_spread = min((c.spread_pct for c in coverages), default=0.0)
    gap = min_spread - min_wp

    if gap >= _COVERAGE_GAP_PCT:
        return MeasureChoice(
            measure="closing_spread",
            reason=(
                f"Closing spread's minimum 2014-2025 season coverage ({min_spread:.1f}%) beats "
                f"pregame win probability's ({min_wp:.1f}%) by {gap:.1f} points, at or above the "
                f"{_COVERAGE_GAP_PCT:.0f}-point threshold for choosing on coverage alone."
            ),
            min_coverage=min_spread,
        )
    if -gap >= _COVERAGE_GAP_PCT:
        return MeasureChoice(
            measure="pregame_wp",
            reason=(
                f"Pregame win probability's minimum 2014-2025 season coverage ({min_wp:.1f}%) "
                f"beats closing spread's ({min_spread:.1f}%) by {-gap:.1f} points, at or above "
                f"the {_COVERAGE_GAP_PCT:.0f}-point threshold for choosing on coverage alone."
            ),
            min_coverage=min_wp,
        )
    return MeasureChoice(
        measure="closing_spread",
        reason=(
            f"Minimum 2014-2025 season coverage is within {_COVERAGE_GAP_PCT:.0f} points either "
            f"way (closing spread {min_spread:.1f}%, pregame win probability {min_wp:.1f}%), so "
            "the choice is made on interpretability: points are a more familiar unit to readers "
            "than a win-probability percentage, and the CFBD inventory checks how closely "
            "pregame WP tracks the spread in the seasons where both are available."
        ),
        min_coverage=min_spread,
    )


def spread_closeness(spread: float) -> float:
    """x = -abs(spread): a pick'em (spread 0) plots at x=0, the rightmost
    value; bigger favorites (either direction) plot further left.
    """
    return -abs(spread)


def wp_closeness(home_win_probability: float) -> float:
    """x = 1 - abs(2p - 1): a 50/50 game plots at x=1, the rightmost value;
    a more lopsided win probability (either direction) plots further left.
    """
    return 1.0 - abs(2.0 * home_win_probability - 1.0)


def _provider_priority(counts: dict[str, int]) -> list[str]:
    """consensus first if it was ever the provider of record, then the rest
    by descending appearance count (ties broken alphabetically for
    determinism). Used to pick one closing spread per game when several
    providers quoted one.
    """
    providers = sorted(counts.keys(), key=lambda p: (-counts[p], p))
    if "consensus" in providers:
        providers.remove("consensus")
        providers.insert(0, "consensus")
    return providers


def _closing_spread_by_game(lines: list[CfbdLine], priority: list[str]) -> dict[int, float]:
    by_game: dict[int, dict[str, float]] = {}
    for line in lines:
        if line.spread is not None:
            by_game.setdefault(line.game_id, {})[line.provider] = line.spread

    result: dict[int, float] = {}
    for game_id, by_provider in by_game.items():
        for provider in priority:
            if provider in by_provider:
                result[game_id] = by_provider[provider]
                break
        else:
            # A provider not in the aggregate priority list (shouldn't happen
            # since priority is built from every provider seen); fall back to
            # an arbitrary one rather than drop the game.
            result[game_id] = next(iter(by_provider.values()))
    return result


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman rank correlation, computed by hand (no numpy/scipy
    dependency) with average ranks for ties.
    """
    n = len(xs)
    if n < 2:
        return None

    def _ranks(values: Sequence[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        ranks = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            avg_rank = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranks[order[k]] = avg_rank
            i = j + 1
        return ranks

    rx, ry = _ranks(xs), _ranks(ys)
    mean_rx, mean_ry = sum(rx) / n, sum(ry) / n
    numerator = sum((a - mean_rx) * (b - mean_ry) for a, b in zip(rx, ry, strict=True))
    denominator = (sum((a - mean_rx) ** 2 for a in rx) * sum((b - mean_ry) ** 2 for b in ry)) ** 0.5
    return numerator / denominator if denominator else 0.0


def _spearman_for_season(
    paths: DataPaths, season: int, priority: list[str]
) -> tuple[float | None, int]:
    """Spearman correlation between |spread| and |wp - 0.5| for `season`'s
    universe games that have both a picked closing spread and a pregame WP
    row. Returns (correlation, n).
    """
    games_path = paths.raw / "cfbd" / "games" / f"{season}.json"
    lines_path = paths.raw / "cfbd" / "lines" / f"{season}.json"
    wp_path = paths.raw / "cfbd" / "wp_pregame" / f"{season}.json"
    if not (games_path.is_file() and lines_path.is_file() and wp_path.is_file()):
        return None, 0

    games = parse_games(games_path.read_bytes())
    universe_ids = {
        g.id
        for g in games
        if g.completed and (g.home_classification == "fbs" or g.away_classification == "fbs")
    }
    spreads = _closing_spread_by_game(parse_lines(lines_path.read_bytes()), priority)
    wp_by_game = {
        row.game_id: row.home_win_probability for row in parse_wp_pregame(wp_path.read_bytes())
    }

    xs: list[float] = []
    ys: list[float] = []
    for game_id in universe_ids:
        if game_id in spreads and game_id in wp_by_game:
            xs.append(abs(spreads[game_id]))
            ys.append(abs(wp_by_game[game_id] - 0.5))
    return _spearman(xs, ys), len(xs)


_COVERAGE_CSV_FIELDS = (
    "season",
    "universe",
    "wp_covered",
    "wp_pct",
    "spread_covered",
    "spread_pct",
    "providers",
)


def _write_coverage_csv(paths: DataPaths, coverages: Sequence[SeasonCoverage]) -> None:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_COVERAGE_CSV_FIELDS)
    writer.writeheader()
    for c in coverages:
        providers_str = ", ".join(f"{p}:{n}" for p, n in sorted(c.provider_counts.items()))
        writer.writerow(
            {
                "season": c.season,
                "universe": c.universe,
                "wp_covered": c.wp_covered,
                "wp_pct": c.wp_pct,
                "spread_covered": c.spread_covered,
                "spread_pct": c.spread_pct,
                "providers": providers_str,
            }
        )
    atomic_write_bytes(paths.spike / "pregame-coverage.csv", buf.getvalue().encode("utf-8"))


_ORIENTATION_FORMULAS: dict[Measure, str] = {
    "closing_spread": "x = -abs(spread) (0 = pick'em, plots rightmost; bigger favorites plot left)",
    "pregame_wp": (
        "x = 1 - abs(2p - 1) (p = home win probability; 0.5 plots rightmost; "
        "more lopsided games plot left)"
    ),
}


def _write_measure_report(
    paths: DataPaths,
    coverages: Sequence[SeasonCoverage],
    choice: MeasureChoice,
    priority: list[str],
    correlation: float | None,
    correlation_n: int,
) -> None:
    lines = [
        "# Pre-game x-axis measure (SPIKE-04)",
        "",
        f"Chosen measure: {choice.measure}",
        f"Reason: {choice.reason}",
        f"Orientation: {_ORIENTATION_FORMULAS[choice.measure]}",
        "",
        "## Coverage by season (2014-2025)",
        "",
        "| Season | Universe | WP covered | WP % | Spread covered | Spread % |",
        "|---|---|---|---|---|---|",
    ]
    for c in coverages:
        lines.append(
            f"| {c.season} | {c.universe} | {c.wp_covered} | {c.wp_pct} | "
            f"{c.spread_covered} | {c.spread_pct} |"
        )
    lines += [
        "",
        "## Provider priority",
        "",
        f"Closing spread per game is taken from the first of these providers with a "
        f"non-null spread that season: {priority}",
        "",
        "## 2025 spread vs. pregame-WP agreement",
        "",
    ]
    if correlation is None:
        lines.append("Not enough overlapping 2025 games with both a spread and a pregame WP row.")
    else:
        lines.append(
            f"Spearman correlation between |spread| and |wp - 0.5| across {correlation_n} 2025 "
            f"games with both values: r = {correlation:.3f}"
        )
    lines.append("")
    atomic_write_bytes(paths.spike / "pregame-measure.md", "\n".join(lines).encode("utf-8"))


def run_pregame_measure(paths: DataPaths) -> MeasureChoice:
    """Rebuild the SPIKE-04 coverage CSV and decision report from the 2014-2025
    CFBD files already cached in the vault, and return the choice.
    """
    coverages = coverage_by_season(paths, _SEASONS)
    choice = choose_measure(coverages)

    aggregate_counts: Counter[str] = Counter()
    for c in coverages:
        aggregate_counts.update(c.provider_counts)
    priority = _provider_priority(dict(aggregate_counts))

    correlation, correlation_n = (
        _spearman_for_season(paths, 2025, priority) if 2025 in _SEASONS else (None, 0)
    )

    _write_coverage_csv(paths, coverages)
    _write_measure_report(paths, coverages, choice, priority, correlation, correlation_n)
    return choice
