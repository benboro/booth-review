"""Pre-game x-axis inputs, promoted from the Phase 1 spike (SPIKE-04) into
booth_review.resolve: the provider-priority pick for a game's one closing
spread, and the -|spread| orientation the site's x-axis (SITE-03) uses.
"""

from __future__ import annotations

from booth_review.sources.cfbd.parser import CfbdLine


def provider_priority(counts: dict[str, int]) -> list[str]:
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


def closing_spread_by_game(lines: list[CfbdLine], priority: list[str]) -> dict[int, float]:
    """One closing spread per game_id: the first of `priority`'s providers
    with a non-null spread for that game, or an arbitrary quoted spread if
    none of `priority`'s providers quoted this particular game.
    """
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


def pregame_x(spread: float | None) -> float | None:
    """The pre-game x-axis value (SPIKE-04): minus the absolute closing
    spread, so a pick'em (spread 0) plots at x=0, the rightmost value, and
    bigger favorites (either direction) plot further left. A missing spread
    stays None (D-11 null-safety); it is never coerced to 0.
    """
    return -abs(spread) if spread is not None else None
