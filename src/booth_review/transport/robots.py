"""RFC 9309 robots.txt rules with wildcard (`*`) and end-anchor (`$`) support.

`urllib.robotparser` matches rule paths by plain prefix, so a rule such as
`Disallow: /*/download` never blocks anything there. PoliteClient consults this
matcher in addition to the stdlib parser; the two together only ever tighten
what a fetch may do.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit


def _compile(pattern: str) -> re.Pattern[str]:
    """Compile a robots path pattern; literal pieces are escaped."""
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = ".*".join(re.escape(piece) for piece in re.split(r"\*+", body))
    return re.compile(regex + ("$" if anchored else ""), re.DOTALL)


@dataclass(frozen=True)
class RobotsRules:
    """The Allow/Disallow rules of the group that applies to this crawler."""

    rules: tuple[tuple[bool, str], ...] = ()

    @classmethod
    def allow_all(cls) -> RobotsRules:
        return cls(())

    @classmethod
    def parse(cls, lines: Sequence[str], *, agent: str) -> RobotsRules:
        token = agent.split("/", 1)[0].split()[0].lower() if agent.split() else ""
        groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
        agents: list[str] = []
        rules: list[tuple[bool, str]] = []
        in_rules = False
        for raw in lines:
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            field, _, value = line.partition(":")
            field = field.strip().lower()
            value = value.strip()
            if field == "user-agent":
                if in_rules:
                    groups.append((agents, rules))
                    agents, rules, in_rules = [], [], False
                agents.append(value.lower())
            elif field in ("allow", "disallow"):
                in_rules = True
                if value:
                    rules.append((field == "allow", value))
        if agents:
            groups.append((agents, rules))

        specific: list[tuple[bool, str]] = []
        wildcard: list[tuple[bool, str]] = []
        found_specific = False
        for group_agents, group_rules in groups:
            if token and token in group_agents:
                found_specific = True
                specific.extend(group_rules)
            if "*" in group_agents:
                wildcard.extend(group_rules)
        return cls(tuple(specific if found_specific else wildcard))

    def disallows(self, url: str) -> bool:
        parts = urlsplit(url)
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
        best_len = -1
        best_allow = True
        for allow, pattern in self.rules:
            if not _compile(pattern).match(target):
                continue
            length = len(pattern)
            if length > best_len or (length == best_len and allow):
                best_len, best_allow = length, allow
        return best_len >= 0 and not best_allow
