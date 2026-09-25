"""Runtime wiring: the one place production code constructs PoliteClient,
RawCache, CfbdBudget, and VaultRepo (D-15).

`make_client()` is the single seam production code uses to build a
PoliteClient; tests monkeypatch `booth_review.runtime.make_client` to return
one built on a mock transport instead, so no other module needs to know how
a real client differs from a test one.
"""

from __future__ import annotations

from dataclasses import dataclass

from booth_review.config import CFBD_FLOOR_DEFAULT, DataPaths
from booth_review.transport.budget import CfbdBudget
from booth_review.transport.cache import FreezeGuard, RawCache
from booth_review.transport.client import PoliteClient
from booth_review.transport.types import FetchGuard
from booth_review.vault import VaultRepo


def make_client() -> PoliteClient:
    """Construct the one production PoliteClient with production defaults."""
    return PoliteClient()


@dataclass
class Runtime:
    """Everything a CLI command needs: paths, client, cache, budget, vault."""

    paths: DataPaths
    client: PoliteClient
    cache: RawCache
    budget: CfbdBudget | None
    vault: VaultRepo


def build_runtime(
    *,
    with_budget: bool,
    floor: int = CFBD_FLOOR_DEFAULT,
    max_calls: int | None = None,
    tag: str | None = None,
) -> Runtime:
    """Wire a Runtime for one CLI command.

    Checks the vault first (VaultStateError if missing or not its own git
    repo, so a missing vault fails loudly and never falls back to fetching
    into some other folder), loads FreezeGuard, and builds RawCache with a
    CfbdBudget guard when `with_budget` is True.
    """
    paths = DataPaths.from_env()
    vault = VaultRepo(paths.vault)
    vault.check()

    freeze = FreezeGuard.load(paths.frozen)
    client = make_client()

    budget: CfbdBudget | None = None
    guards: list[FetchGuard] = []
    if with_budget:
        budget = CfbdBudget(paths.cfbd_ledger, floor=floor, max_calls=max_calls, tag=tag)
        guards.append(budget)

    cache = RawCache(paths, client, guards=guards, freeze=freeze)

    return Runtime(paths=paths, client=client, cache=cache, budget=budget, vault=vault)
