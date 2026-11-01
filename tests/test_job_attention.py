"""Tests for job/attention.py: the D-12 count-only attention issue body.

Every constructor's shape is exercised, plus the whitelist rejections that
matter most: a planted key ("CFBD_API_KEY=abc") and a query-string URL
("https://x/y?z=1") must both fail loudly, never reach a built body.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from booth_review.job.attention import (
    _LINE_RE,
    ATTENTION_TITLE,
    REMINDER_506_NFL_URL,
    REMINDER_AA_CFB_URL,
    REMINDER_AA_NFL_URL,
    REMINDER_ESPNPR_CFB_URL,
    REMINDER_FOX_CFB_URL,
    AttentionItem,
    aa_crews_skipped,
    aa_feed_blocked,
    aa_feed_policy_stale,
    aa_feed_unverified,
    build_attention_body,
    cfbd_failed,
    cfbd_remaining,
    cfbd_step_failed,
    error_type_name,
    espnpr_week_unsaved,
    has_attention,
    missed_runs,
    nfl_506_missing,
    nfl_506_stale,
    push_failed,
    reminder_506_nfl,
    reminder_506_nfl_played,
    reminder_aa_cfb,
    reminder_aa_cfb_link,
    reminder_aa_nfl,
    reminder_espnpr,
    reminder_fox_cfb,
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
    assert item.line == "506 2026 pages to save: weeks 3, 4, bowls"
    assert item.severity == "attention"


def test_sports506_missing_names_single_week_and_bowls() -> None:
    assert sports506_missing(2026, ["6"]).line == "506 2026 pages to save: week 6"
    assert sports506_missing(2026, ["B"]).line == "506 2026 pages to save: bowls"


def test_nfl_506_lines_name_singular_and_plural_weeks() -> None:
    assert nfl_506_missing(2026, ["2"]).line == "nfl 506 pages missing for 2026: week 2"
    assert nfl_506_missing(2026, ["2", "3"]).line == "nfl 506 pages missing for 2026: weeks 2, 3"
    assert nfl_506_stale(2026, ["2"]).line == (
        "nfl 506 pages saved before their games finished for 2026: week 2"
    )
    assert nfl_506_stale(2026, ["2", "3"]).line == (
        "nfl 506 pages saved before their games finished for 2026: weeks 2, 3"
    )


def test_every_cfb_week_label_fits_the_attention_body() -> None:
    labels = [*(str(n) for n in range(17)), "B"]
    items = [sports506_missing(2026, labels), sports506_stale(2026, labels)]
    assert build_attention_body(items, generated_at=_NOW) is not None


def test_sports506_missing_rejects_unrecognized_label() -> None:
    with pytest.raises(ValueError):
        sports506_missing(2026, ["17"])


def test_sports506_stale_line_format() -> None:
    item = sports506_stale(2026, ["2"])
    assert item.line == "506 2026 pages saved before their games finished: week 2"
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


def test_match_rate_explained_names_each_season_and_the_override_file() -> None:
    from booth_review.job.attention import match_rate_explained

    items = match_rate_explained([(2022, 1), (2026, 2)])

    assert [(i.kind, i.severity) for i in items] == [("match_rate_explained", "attention")]
    assert items[0].line == (
        "match_rate below baseline only from rated games 506 lists with no crew, "
        "not a block (games per season 2022: 1, 2026: 2): "
        "an override in data/reference/crew_overrides.csv fills them"
    )
    assert build_attention_body(items, generated_at=_NOW) is not None


def test_match_rate_explained_splits_seasons_across_lines_keeping_every_count() -> None:
    from booth_review.job.attention import match_rate_explained

    many = [(season, 10 + season % 7) for season in range(2014, 2027)]
    items = match_rate_explained(many)

    assert len(items) > 1
    assert build_attention_body(items, generated_at=_NOW) is not None
    text = "\n".join(item.line for item in items)
    for item in items:
        assert len(item.line) <= 200
        assert "data/reference/crew_overrides.csv" in item.line
        assert "not a block" in item.line
    for season, games in many:
        assert text.count(f"{season}: {games}") == 1
    with pytest.raises(ValueError):
        match_rate_explained([])
    with pytest.raises(ValueError):
        match_rate_explained([(2026, -1)])


def test_deploy_held_shows_the_hold_start_in_eastern_time() -> None:
    from booth_review.job.attention import deploy_held

    item = deploy_held(datetime(2026, 10, 29, 14, 5, tzinfo=UTC))

    assert item.kind == "deploy_held"
    assert item.severity == "attention"
    assert item.line == (
        "deploy held since 2026-10-29 10:05 ET: the last build was blocked by the "
        "regression guard (clears on the first unblocked build)"
    )
    assert build_attention_body([item], generated_at=_NOW) is not None
    with pytest.raises(ValueError):
        deploy_held(datetime(2026, 10, 29, 14, 5))  # noqa: DTZ001


def test_new_step_names_accepted() -> None:
    for step in ("build", "site", "staleness"):
        assert step_failed(step, "SiteBuildError").line == f"{step} step failed: SiteBuildError"
    with pytest.raises(ValueError):
        step_failed("deploy", "Oops")


def test_bowls_missing_says_shown_as_bowl() -> None:
    from booth_review.job import attention as a

    item = a.bowls_missing(3)
    assert "shown as Bowl" in item.line
    assert "plotted" not in item.line
    assert item.severity == "attention"


def test_nfl_site_constructors() -> None:
    from booth_review.job.attention import (
        nfl_site_failed,
        nfl_site_key_check_failed,
        nfl_site_switch_off,
    )

    assert nfl_site_switch_off().kind == "nfl_site_switch_off"
    assert nfl_site_switch_off().line == (
        "nfl site data: no valid file this run, "
        "NFL switch off unless the deploy carries the live copy"
    )
    assert nfl_site_key_check_failed().kind == "nfl_site_key_check_failed"
    assert nfl_site_failed("missing").kind == "nfl_site_failed"
    assert "last good file kept" in nfl_site_failed("invalid").line
    carry = nfl_site_failed("carry_over_invalid").line
    assert "carry over invalid" in carry
    assert "vault file not used" in carry
    assert "last good file kept" not in carry
    with pytest.raises(ValueError):
        nfl_site_failed("other")  # type: ignore[arg-type]


# -- 04.19 D-14: the ESPN Press Room commentators reminder ------------------------------------


def test_espnpr_week_unsaved_line_names_the_page_and_the_import_command() -> None:
    from booth_review.job.attention import _LINE_RE, espnpr_week_unsaved

    item = espnpr_week_unsaved(2026, "7")
    assert item.kind == "espnpr_week_unsaved"
    assert item.severity == "attention"
    assert item.line.startswith("espn pr 2026 commentators page not saved for week 7 ")
    assert item.line == (
        "espn pr 2026 commentators page not saved for week 7 (save "
        "https://espnpressroom.com/2026-27-espn-college-football-commentators-schedule/ "
        "by Monday, then booth-review import espnpr)"
    )
    assert _LINE_RE.match(item.line)
    body = build_attention_body([item, espnpr_week_unsaved(2026, "12")], generated_at=_NOW)
    assert body is not None


def test_espnpr_commentators_url_wraps_the_season_pair() -> None:
    from booth_review.job.attention import espnpr_commentators_url

    assert espnpr_commentators_url(2099) == (
        "https://espnpressroom.com/2099-00-espn-college-football-commentators-schedule/"
    )


@pytest.mark.parametrize("label", ["B", "", "007", "7a", "7?x=1", "-1"])
def test_espnpr_week_unsaved_rejects_a_label_that_is_not_a_week_number(label: str) -> None:
    from booth_review.job.attention import espnpr_week_unsaved

    with pytest.raises(ValueError):
        espnpr_week_unsaved(2026, label)


def test_step_failed_accepts_espnpr_gaps() -> None:
    assert step_failed("espnpr_gaps", "ValueError").line == "espnpr_gaps step failed: ValueError"


# -- Phase 24 reminders ---------------------------------------------------------------


def _passes(item: AttentionItem) -> None:
    assert _LINE_RE.match(item.line)
    assert len(item.line) <= 200
    assert item.line in build_attention_body([item], generated_at=_NOW)


def test_reminder_espnpr_line() -> None:
    item = reminder_espnpr(2026, "10")
    assert item.kind == "reminder_espnpr"
    assert item.severity == "reminder"
    assert item.line == (
        "reminder 2026 cfb week 10: save the espn pr commentators release "
        f"{REMINDER_ESPNPR_CFB_URL}, then booth-review import espnpr"
    )
    assert (
        REMINDER_ESPNPR_CFB_URL
        == "https://espnpressroom.com/press-release-category/college-football/"
    )
    _passes(item)
    assert not item.line.startswith(espnpr_week_unsaved(2026, "10").line[:30])


@pytest.mark.parametrize(
    ("builder", "kind", "url", "sport"),
    [
        (reminder_aa_cfb, "reminder_aa_cfb", REMINDER_AA_CFB_URL, "cfb"),
        (reminder_fox_cfb, "reminder_fox_cfb", REMINDER_FOX_CFB_URL, "cfb"),
        (reminder_aa_nfl, "reminder_aa_nfl", REMINDER_AA_NFL_URL, "nfl"),
    ],
)
def test_reminder_link_builders(builder, kind: str, url: str, sport: str) -> None:
    week = "10" if sport == "cfb" else "9"
    item = builder(2026, week)
    assert item.kind == kind
    assert item.line.startswith(f"reminder 2026 {sport} week {week}: ")
    assert item.line.endswith(url)
    _passes(item)
    assert builder(2026, "8").line != item.line  # the week label keeps each week distinct


def test_reminder_506_nfl_line() -> None:
    item = reminder_506_nfl(2026, "9")
    assert item.kind == "reminder_506_nfl"
    assert item.line == (
        "reminder 2026 nfl week 9: save the 506 nfl week 9 page before thursday night "
        f"{REMINDER_506_NFL_URL}, then booth-review import 506 --season 2026 --league nfl"
    )
    _passes(item)


def test_reminder_506_nfl_played_lines() -> None:
    missing = reminder_506_nfl_played(2026, "9", "missing", ["3", "5"])
    stale = reminder_506_nfl_played(2026, "9", "stale", ["4"])
    assert missing.kind == stale.kind == "reminder_506_nfl_played"
    assert missing.line == (
        "reminder 2026 nfl week 9: 506 nfl pages not saved for weeks 3, 5, "
        f"save {REMINDER_506_NFL_URL}"
    )
    assert stale.line == (
        "reminder 2026 nfl week 9: 506 nfl pages saved before their games finished for week 4, "
        f"save {REMINDER_506_NFL_URL}"
    )
    for item in (missing, stale):
        _passes(item)
    assert missing.line != nfl_506_missing(2026, ["3", "5"]).line
    assert stale.line != nfl_506_stale(2026, ["4"]).line


def test_reminder_builders_reject_bad_input() -> None:
    for builder in (reminder_espnpr, reminder_aa_cfb, reminder_fox_cfb):
        for bad in ("x1", "", "100"):
            with pytest.raises(ValueError):
                builder(2026, bad)
    for builder in (reminder_aa_nfl, reminder_506_nfl):
        for bad in ("x1", "", "19"):
            with pytest.raises(ValueError):
                builder(2026, bad)
    with pytest.raises(ValueError):
        reminder_506_nfl_played(2026, "9", "late", ["3"])
    with pytest.raises(ValueError):
        reminder_506_nfl_played(2026, "9", "missing", [])
    with pytest.raises(ValueError):
        reminder_506_nfl_played(2026, "9", "missing", ["19"])
    with pytest.raises(ValueError):
        reminder_506_nfl_played(2026, "19", "missing", ["3"])


AA_POST = (
    "https://awfulannouncing.com/schedules/week-10-college-football-announcing-schedule-2026.html"
)


def test_reminder_aa_cfb_points_at_the_schedules_page() -> None:
    assert reminder_aa_cfb(2026, "10").line.endswith("https://awfulannouncing.com/schedules/")


def test_reminder_aa_cfb_link_line() -> None:
    item = reminder_aa_cfb_link(2026, "10", AA_POST)
    assert item.kind == "reminder_aa_cfb_link"
    assert item.severity == "reminder"
    assert item.line.startswith("reminder 2026 cfb week 10: ")
    assert AA_POST in item.line
    _passes(item)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/schedules/x.html",
        AA_POST + "?utm=1",
        AA_POST.replace("https", "http"),
        AA_POST + "#frag",
        "https://awfulannouncing.com/schedules/a b.html",
        "https://awfulannouncing.com/schedules/" + "a" * 200,
    ],
)
def test_reminder_aa_cfb_link_rejects_bad_urls(url: str) -> None:
    with pytest.raises(ValueError):
        reminder_aa_cfb_link(2026, "10", url)


@pytest.mark.parametrize(
    ("builder", "needle"),
    [
        (aa_feed_policy_stale, "--confirm-terms"),
        (aa_feed_unverified, "--feed --verify schedules"),
        (aa_feed_blocked, "--policy-check"),
    ],
)
def test_aa_feed_attention_lines(builder, needle: str) -> None:
    item = builder()
    assert item.severity == "attention"
    assert needle in item.line
    assert "booth-review collect aa" in item.line
    _passes(item)


@pytest.mark.parametrize("reason", ["robots", "policy", "not_cached", "no_validator", "error"])
def test_aa_crews_skipped_lines(reason: str) -> None:
    item = aa_crews_skipped(reason)  # type: ignore[arg-type]
    assert item.severity == "attention"
    assert "http" not in item.line
    _passes(item)
