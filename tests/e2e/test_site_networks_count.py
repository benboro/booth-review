"""Networks trigger count (D-36) -- the toolbar button counts only the checked
channels among the rows the Networks list currently shows, proven against the
synthetic fixture build served by `guarded_page`/`open_app`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _open_filter(page: Page, name: str) -> None:
    """Opens `#pop-{name}` and waits for the toggle event to settle."""
    page.click(f"#trigger-{name}")
    page.wait_for_function(f"document.getElementById('pop-{name}').matches(':popover-open')")
    page.wait_for_function(
        f"document.getElementById('trigger-{name}').getAttribute('aria-expanded') === 'true'"
    )


def _net_item(page: Page, net_id: str) -> Any:
    return page.locator(f".check-item:has(input[data-network-id='{net_id}'])")


def _uncheck(page: Page, net_id: str) -> None:
    page.locator(f"input[data-network-id='{net_id}']").uncheck()


def _trigger(page: Page) -> Any:
    return page.locator("#trigger-networks")


def test_networks_count_counts_only_shown_rows(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-36: kris-venn offers net-a (unrated game 13), net-b and net-c; unchecking net-c
    leaves two shown rows checked."""
    open_app(guarded_page, "?people=kris-venn")
    _open_filter(guarded_page, "networks")
    expect(_net_item(guarded_page, "net-d")).to_be_hidden()
    _uncheck(guarded_page, "net-c")
    expect(_trigger(guarded_page)).to_have_text("Networks · 2")
    assert _trigger(guarded_page).get_attribute("data-active") == "true"


def test_networks_count_absent_when_every_shown_row_is_checked(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-36 with D-15: no count, inactive look, but the pick stays stored and resettable."""
    open_app(guarded_page, "?people=kris-venn&networks=net-a,net-b,net-c")
    expect(_trigger(guarded_page)).to_have_text("Networks")
    assert _trigger(guarded_page).get_attribute("data-active") == "false"
    assert "networks=net-a,net-b,net-c" in guarded_page.evaluate("location.search")
    _open_filter(guarded_page, "networks")
    reset = guarded_page.locator("#pop-networks .group-reset")
    assert reset.get_attribute("aria-disabled") == "false"


def test_phone_filters_badge_agrees_with_networks_trigger(
    mobile_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """WR-02: the phone badge counts Networks only when its trigger shows a
    count (D-36), so a stored pick with every shown row checked adds nothing;
    the pick stays in the URL and the Reset stays live (D-15)."""
    open_app(mobile_page, "?people=kris-venn&networks=net-a,net-b,net-c")
    expect(_trigger(mobile_page)).to_have_text("Networks")
    expect(mobile_page.locator("#filters-button")).to_have_text("Filters (1)")
    assert "networks=net-a,net-b,net-c" in mobile_page.evaluate("location.search")
    reset = mobile_page.locator(".group-reset[data-reset='networks']")
    assert reset.get_attribute("aria-disabled") == "false"
    mobile_page.evaluate("window.__testHooks.setState({ networks: ['net-b'] })")
    expect(_trigger(mobile_page)).to_have_text("Networks · 1")
    expect(mobile_page.locator("#filters-button")).to_have_text("Filters (2)")


def test_networks_count_ignores_hidden_family_chip_toggle(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
) -> None:
    """D-36: a legend chip for a family with no offered channel leaves the count alone
    (Kris Venn is offered no `other`-family channel)."""
    mutated = json.loads(json.dumps(fixture_raw))
    # net-e (index 4) already exists in the fixture for its unrated games; re-family it.
    mutated["lookups"]["networks"][4] = {"id": "net-e", "name": "Echo Sports", "family": "other"}
    mutated["lookups"]["networks"].append({"id": "net-f", "name": "Foxtrot TV", "family": "other"})
    mutated["telecasts"]["network"][3] = 4
    mutated["telecasts"]["outlets"][3] = [4]
    mutated["telecasts"]["network"][11] = 5
    mutated["telecasts"]["outlets"][11] = [5]
    body = json.dumps(mutated)
    guarded_page.route(
        "**/site-data.json*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=body),
    )
    open_app(guarded_page, "?people=kris-venn")
    _open_filter(guarded_page, "networks")
    _uncheck(guarded_page, "net-c")
    expect(_trigger(guarded_page)).to_have_text("Networks · 2")
    chip = guarded_page.locator('#legend-chips button[data-family="other"]')
    chip.click()
    expect(chip).to_have_attribute("aria-pressed", "false")
    expect(_trigger(guarded_page)).to_have_text("Networks · 2")


def test_networks_count_includes_greyed_explicit_pick(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """D-36: a greyed explicit pick is a shown, checked row and counts."""
    open_app(guarded_page, "?people=dale-harlow&networks=net-b")
    _open_filter(guarded_page, "networks")
    expect(_net_item(guarded_page, "net-a")).to_be_visible()
    expect(_net_item(guarded_page, "net-b")).to_be_visible()
    expect(_trigger(guarded_page)).to_have_text("Networks · 1")


def test_networks_count_unchanged_without_people(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    """Guard: with no announcer every channel is shown, so the count is the pick size."""
    open_app(guarded_page, "?networks=net-a")
    expect(_trigger(guarded_page)).to_have_text("Networks · 1")
    open_app(guarded_page, "?networks=net-a,net-b")
    expect(_trigger(guarded_page)).to_have_text("Networks · 2")
