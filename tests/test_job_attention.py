"""Tests for job/attention.py: the D-12 count-only attention issue body.

Every constructor's shape is exercised, plus the whitelist rejections that
matter most: a planted key ("CFBD_API_KEY=abc") and a query-string URL
("https://x/y?z=1") must both fail loudly, never reach a built body.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from booth_review.job.attention import (
    ATTENTION_TITLE,
    AttentionItem,
    build_attention_body,
    cfbd_remaining,
    cfbd_step_failed,
    has_attention,
    missed_runs,
    push_failed,
    rr_backlog,
    rr_failed,
    rr_step_failed,
    season_past_freeze,
    sports506_missing,
    sports506_stale,
)

_NOW = datetime(2026, 10, 15, 0, 10, tzinfo=UTC)


def test_attention_title_is_fixed() -> None:
    assert ATTENTION_TITLE == "booth-review job: needs attention"


# -- constructors ---------------------------------------------------------------------


def test_cfbd_step_failed_line_and_severity() -> None:
    item = cfbd_step_failed("BudgetFloorError")
    assert item.line == "cfbd step failed: BudgetFloorError"
    assert item.severity == "attention"


def test_cfbd_step_failed_rejects_exception_message_not_class_name() -> None:
    with pytest.raises(ValueError, match="error_type"):
        cfbd_step_failed("BudgetFloorError: remaining calls would drop below 250")


def test_rr_step_failed_line() -> None:
    item = rr_step_failed("FetchError")
    assert item.line == "rr step failed: FetchError"
    assert item.severity == "attention"


def test_rr_step_failed_rejects_non_alpha_error_type() -> None:
    with pytest.raises(ValueError, match="error_type"):
        rr_step_failed("Fetch Error 42")


def test_rr_backlog_line() -> None:
    item = rr_backlog(50, 100)
    assert item.line == "rr refresh backlog 50 (cap 100 per run)"


def test_rr_backlog_rejects_negative_counts() -> None:
    with pytest.raises(ValueError):
        rr_backlog(-1, 100)
    with pytest.raises(ValueError):
        rr_backlog(0, -1)


def test_rr_failed_line() -> None:
    item = rr_failed(3)
    assert item.line == "rr refresh failed: 3"
    assert item.severity == "attention"


def test_rr_failed_rejects_negative() -> None:
    with pytest.raises(ValueError):
        rr_failed(-1)


def test_cfbd_remaining_is_info_line() -> None:
    item = cfbd_remaining(500, 250)
    assert item.line == "cfbd remaining calls: 500 (floor 250)"
    assert item.severity == "info"


def test_sports506_missing_line_format() -> None:
    item = sports506_missing(2026, ["3", "4", "B"])
    assert item.line == "506 2026 weeks to save: 3, 4, B"
    assert item.severity == "attention"


def test_sports506_missing_rejects_unrecognized_label() -> None:
    with pytest.raises(ValueError):
        sports506_missing(2026, ["17"])


def test_sports506_stale_line_format() -> None:
    item = sports506_stale(2026, ["2"])
    assert item.line == "506 2026 weeks saved before their games finished: 2"
    assert item.severity == "attention"


def test_missed_runs_line() -> None:
    item = missed_runs(2)
    assert item.line == "missed scheduled runs since last success: 2 (caught up this run)"


def test_season_past_freeze_line() -> None:
    item = season_past_freeze(2025, date(2026, 2, 15))
    assert item.line == (
        "season 2025 is past its freeze date 2026-02-15 "
        "and not frozen: run audit completeness and freeze"
    )
    assert item.severity == "attention"


def test_push_failed_line() -> None:
    item = push_failed("cfbd")
    assert item.line == "vault push failed at step cfbd"
    assert item.severity == "attention"


# -- has_attention --------------------------------------------------------------------


def test_has_attention_true_when_any_attention_item() -> None:
    items = [cfbd_remaining(500, 250), rr_failed(1)]
    assert has_attention(items) is True


def test_has_attention_false_when_only_info() -> None:
    items = [cfbd_remaining(500, 250), missed_runs(1)]
    assert has_attention(items) is False


def test_has_attention_false_on_empty() -> None:
    assert has_attention([]) is False


# -- build_attention_body ---------------------------------------------------------------


def test_build_attention_body_none_on_empty() -> None:
    assert build_attention_body([], generated_at=_NOW) is None


def test_build_attention_body_header_and_lines() -> None:
    items = [rr_failed(1), cfbd_remaining(500, 250)]
    body = build_attention_body(items, generated_at=_NOW)
    assert body is not None
    lines = body.splitlines()
    assert lines[0] == "Counts only. Updated 2026-10-15T00:10:00Z"
    assert lines[1] == "- rr refresh failed: 1"
    assert lines[2] == "- cfbd remaining calls: 500 (floor 250)"


def test_build_attention_body_rejects_query_string_url() -> None:
    items = [AttentionItem(kind="test", line="https://x/y?z=1", severity="attention")]
    with pytest.raises(ValueError, match="whitelist"):
        build_attention_body(items, generated_at=_NOW)


def test_build_attention_body_rejects_planted_key() -> None:
    items = [AttentionItem(kind="test", line="CFBD_API_KEY=abc", severity="attention")]
    with pytest.raises(ValueError, match="whitelist"):
        build_attention_body(items, generated_at=_NOW)


def test_build_attention_body_rejects_at_sign() -> None:
    items = [AttentionItem(kind="test", line="contact me@example.com", severity="info")]
    with pytest.raises(ValueError, match="whitelist"):
        build_attention_body(items, generated_at=_NOW)


def test_build_attention_body_rejects_embedded_newline() -> None:
    items = [AttentionItem(kind="test", line="line one\nline two", severity="info")]
    with pytest.raises(ValueError, match="whitelist"):
        build_attention_body(items, generated_at=_NOW)


def test_build_attention_body_rejects_line_over_max_length() -> None:
    items = [AttentionItem(kind="test", line="a" * 201, severity="info")]
    with pytest.raises(ValueError, match="200"):
        build_attention_body(items, generated_at=_NOW)


def test_build_attention_body_rejects_body_over_max_lines() -> None:
    items = [AttentionItem(kind="test", line=f"item {i}", severity="info") for i in range(60)]
    with pytest.raises(ValueError, match="60"):
        build_attention_body(items, generated_at=_NOW)


def test_build_attention_body_accepts_exactly_max_lines() -> None:
    items = [AttentionItem(kind="test", line=f"item {i}", severity="info") for i in range(59)]
    body = build_attention_body(items, generated_at=_NOW)
    assert body is not None
    assert len(body.splitlines()) == 60
