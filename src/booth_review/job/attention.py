"""D-12: the count-only "needs attention" issue body builder.

Failures and needs-attention states (budget floor, source errors, vault push
failure, RR backlog over cap, missing/stale 2026 506 weeks, a season past its
freeze date) go into one tracked issue in the private vault repo (Plan 06
wires this into `gh issue`). D-12 requires the text be count-only: never
joined data, never a URL with parameters beyond the path, never key
material. Every line built here passes a fixed character whitelist before
`build_attention_body` will include it, so a stray exception message, a
query-string URL, or a planted secret fails loudly (ValueError) instead of
silently reaching a GitHub issue. The body never includes a run URL; the
workflow appends the Actions run link itself (Plan 06).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

from booth_review.sources.sports506.collector import WEEK_LABELS

ATTENTION_TITLE = "booth-review job: needs attention"

# Whitelisted characters for any single attention line: letters, digits,
# space, and a small fixed set of punctuation a count-only sentence needs.
# No "?", "=", "@", or newline can ever match -- the exact shapes a URL
# query string or a "KEY=value" secret would need.
_LINE_RE = re.compile(r"^[A-Za-z0-9 ,()_./:#-]+$")
_ERROR_TYPE_RE = re.compile(r"^[A-Za-z]+$")

_MAX_LINES = 60
_MAX_LINE_LEN = 200
_TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"

Severity = Literal["attention", "info"]


@dataclass(frozen=True)
class AttentionItem:
    """One line of the attention issue body, with its severity."""

    kind: str
    line: str
    severity: Severity


def _require_non_negative(name: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{name} must be non-negative: {value!r}")


def _require_error_type(error_type: str) -> None:
    if not _ERROR_TYPE_RE.match(error_type):
        raise ValueError(
            f"error_type must be a bare exception class name matching "
            f"{_ERROR_TYPE_RE.pattern!r}: {error_type!r}"
        )


def _require_labels(labels: list[str]) -> None:
    for label in labels:
        if label not in WEEK_LABELS:
            raise ValueError(f"label is not a recognized 506 week label: {label!r}")


def cfbd_step_failed(error_type: str) -> AttentionItem:
    """The CFBD collection step raised `error_type` (a bare exception class name)."""
    _require_error_type(error_type)
    return AttentionItem(
        kind="cfbd_step_failed", line=f"cfbd step failed: {error_type}", severity="attention"
    )


def rr_step_failed(error_type: str) -> AttentionItem:
    """The Ratings Reference refresh step raised `error_type`."""
    _require_error_type(error_type)
    return AttentionItem(
        kind="rr_step_failed", line=f"rr step failed: {error_type}", severity="attention"
    )


def rr_backlog(n: int, cap: int) -> AttentionItem:
    """`n` RR records qualified for refresh but carried over past the `cap`-per-run limit."""
    _require_non_negative("n", n)
    _require_non_negative("cap", cap)
    return AttentionItem(
        kind="rr_backlog",
        line=f"rr refresh backlog {n} (cap {cap} per run)",
        severity="attention",
    )


def rr_failed(n: int) -> AttentionItem:
    """`n` RR fetches failed during a refresh run."""
    _require_non_negative("n", n)
    return AttentionItem(kind="rr_failed", line=f"rr refresh failed: {n}", severity="attention")


def cfbd_remaining(n: int, floor: int) -> AttentionItem:
    """Informational: `n` CFBD calls remain this month, against the `floor`."""
    _require_non_negative("n", n)
    _require_non_negative("floor", floor)
    return AttentionItem(
        kind="cfbd_remaining",
        line=f"cfbd remaining calls: {n} (floor {floor})",
        severity="info",
    )


def sports506_missing(season: int, labels: list[str]) -> AttentionItem:
    """`labels` are played 2026 506 week pages with no cached page at all."""
    _require_labels(labels)
    return AttentionItem(
        kind="sports506_missing",
        line=f"506 {season} weeks to save: {', '.join(labels)}",
        severity="attention",
    )


def sports506_stale(season: int, labels: list[str]) -> AttentionItem:
    """`labels` are 506 week pages saved before their games finished."""
    _require_labels(labels)
    return AttentionItem(
        kind="sports506_stale",
        line=f"506 {season} weeks saved before their games finished: {', '.join(labels)}",
        severity="attention",
    )


def missed_runs(n: int) -> AttentionItem:
    """`n` scheduled runs were missed since the last success; this run caught up."""
    _require_non_negative("n", n)
    return AttentionItem(
        kind="missed_runs",
        line=f"missed scheduled runs since last success: {n} (caught up this run)",
        severity="info",
    )


def season_past_freeze(season: int, freeze_date: date) -> AttentionItem:
    """`season` is past its COLL-04 freeze date and still unfrozen."""
    return AttentionItem(
        kind="season_past_freeze",
        line=(
            f"season {season} is past its freeze date {freeze_date.isoformat()} "
            "and not frozen: run audit completeness and freeze"
        ),
        severity="attention",
    )


def push_failed(step: str) -> AttentionItem:
    """The vault push failed at `step`."""
    return AttentionItem(
        kind="push_failed", line=f"vault push failed at step {step}", severity="attention"
    )


def has_attention(items: Sequence[AttentionItem]) -> bool:
    """Whether any item is severity "attention" (vs. purely informational)."""
    return any(item.severity == "attention" for item in items)


def build_attention_body(items: Sequence[AttentionItem], *, generated_at: datetime) -> str | None:
    """Build the count-only issue body, or None when there is nothing to report.

    Every line is checked against the whitelist and length limit here, at
    the single point every attention line must pass through -- not left to
    each constructor -- so a manually-built AttentionItem (or a future
    constructor that forgets to validate) can never reach a real issue with
    disallowed text.
    """
    if not items:
        return None

    header = f"Counts only. Updated {generated_at.astimezone(UTC).strftime(_TIME_FMT)}"
    lines = [header]
    for item in items:
        if len(item.line) > _MAX_LINE_LEN:
            raise ValueError(f"attention line exceeds {_MAX_LINE_LEN} characters: {item.line!r}")
        if not _LINE_RE.match(item.line):
            raise ValueError(f"attention line failed the count-only whitelist: {item.line!r}")
        lines.append(f"- {item.line}")

    if len(lines) > _MAX_LINES:
        raise ValueError(f"attention body exceeds {_MAX_LINES} lines ({len(lines)})")

    return "\n".join(lines)
