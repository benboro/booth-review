"""RFC 9309 wildcard robots rules."""

from __future__ import annotations

from booth_review.transport.robots import RobotsRules

AGENT = "booth-review/0.1 (+https://example.invalid)"


def _rules(*lines: str) -> RobotsRules:
    return RobotsRules.parse(list(lines), agent=AGENT)


def test_wildcard_blocks_github_release_downloads() -> None:
    # Older CPython robotparsers ignore wildcards and allow this URL (newer
    # 3.13 patch releases don't), so the result never depends on the stdlib.
    lines = ["User-agent: *", "Disallow: /*/download"]
    url = "https://github.com/o/r/releases/download/t/f.parquet"
    assert _rules(*lines).disallows(url) is True


def test_dollar_anchor() -> None:
    rules = _rules("User-agent: *", "Disallow: /*.json$")
    assert rules.disallows("https://h/a/b.json") is True
    assert rules.disallows("https://h/a/b.json?x=1") is False


def test_longest_match_wins_and_tie_goes_to_allow() -> None:
    rules = _rules("User-agent: *", "Disallow: /a/", "Allow: /a/ok")
    assert rules.disallows("https://h/a/ok/x") is False
    assert rules.disallows("https://h/a/no") is True
    tie = _rules("User-agent: *", "Disallow: /a", "Allow: /a")
    assert tie.disallows("https://h/a") is False


def test_named_group_beats_wildcard_group() -> None:
    rules = _rules(
        "User-agent: *",
        "Disallow: /",
        "",
        "User-agent: booth-review",
        "Disallow: /private",
    )
    assert rules.disallows("https://h/public") is False
    assert rules.disallows("https://h/private/x") is True


def test_consecutive_user_agent_lines_share_a_group() -> None:
    rules = _rules("User-agent: other", "User-agent: *", "Disallow: /x")
    assert rules.disallows("https://h/x") is True


def test_empty_rules_and_empty_disallow_allow_everything() -> None:
    assert RobotsRules.allow_all().disallows("https://h/anything") is False
    assert _rules("User-agent: *", "Disallow:").disallows("https://h/a") is False


def test_literal_regex_characters_are_escaped() -> None:
    rules = _rules("User-agent: *", "Disallow: /a.b(c")
    assert rules.disallows("https://h/a.b(c") is True
    assert rules.disallows("https://h/aXb(c") is False
