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
    cfbd_failed,
    cfbd_remaining,
    cfbd_step_failed,
    error_type_name,
    has_attention,
    missed_runs,
    push_failed,
    rr_backlog,
    rr_failed,
    rr_step_failed,
    season_past_freeze,
    sports506_missing,
    sports506_stale,
    step_failed,
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


def test_cfbd_failed_line_and_severity() -> None:
    item = cfbd_failed(5)
    assert item.line == "cfbd calls failed: 5"
    assert item.severity == "attention"


def test_cfbd_failed_rejects_negative() -> None:
    with pytest.raises(ValueError):
        cfbd_failed(-1)


def test_step_failed_line_for_each_generic_step() -> None:
    for step in ("sports506", "freeze", "budget", "state"):
        item = step_failed(step, "ValueError")
        assert item.kind == f"{step}_step_failed"
        assert item.line == f"{step} step failed: ValueError"
        assert item.severity == "attention"


def test_step_failed_rejects_unknown_step_and_message_text() -> None:
    with pytest.raises(ValueError, match="step"):
        step_failed("https://x/y?z=1", "ValueError")
    with pytest.raises(ValueError, match="error_type"):
        step_failed("state", "ValueError: key=abc")


def test_error_type_name_is_the_bare_class_name_never_the_message() -> None:
    assert error_type_name(KeyError("secret ?q=1")) == "KeyError"

    class Odd_Error2(Exception):  # deliberately off-whitelist
        pass

    assert error_type_name(Odd_Error2("x")) == "Exception"


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
    assert item.line == "missed scheduled runs since last attempt: 2 (caught up this run)"


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


# -- Phase 5 count-only constructors ---------------------------------------------------------


def _new_items() -> list[AttentionItem]:
    from booth_review.job import attention as a

    return [
        a.build_blocked(2),
        a.bowls_missing(3),
        a.people_review_due(4),
        a.unresolved_teams(5),
        a.build_stale(5, 4),
        a.plotted_trails_listed(4, 3),
        a.plotted_none_listed(7),
        a.site_key_check_failed(),
        a.site_key_check_skipped(),
        a.failed_attempts(1),
    ]


def test_new_constructors_pass_the_whitelist() -> None:
    body = build_attention_body(_new_items(), generated_at=_NOW)
    assert body is not None
    assert len(body.splitlines()) == 11


def test_new_constructors_reject_negative_counts() -> None:
    from booth_review.job import attention as a

    for call in (
        lambda: a.build_blocked(-1),
        lambda: a.bowls_missing(-1),
        lambda: a.people_review_due(-1),
        lambda: a.unresolved_teams(-1),
        lambda: a.build_stale(-1, 4),
        lambda: a.build_stale(1, -4),
        lambda: a.plotted_trails_listed(-1, 3),
        lambda: a.plotted_none_listed(-1),
        lambda: a.failed_attempts(-1),
    ):
        with pytest.raises(ValueError):
            call()


def test_new_constructor_severities() -> None:
    severities = {item.kind: item.severity for item in _new_items()}
    assert severities.pop("failed_attempts") == "info"
    assert set(severities.values()) == {"attention"}
    assert build_blocked_kind() == "build_blocked"


def build_blocked_kind() -> str:
    from booth_review.job.attention import build_blocked

    return build_blocked(2).kind


def test_new_step_names_accepted() -> None:
    for step in ("build", "site", "staleness"):
        assert step_failed(step, "SiteBuildError").line == f"{step} step failed: SiteBuildError"
    with pytest.raises(ValueError):
        step_failed("deploy", "Oops")
