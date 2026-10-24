"""13-14 phone scroll cue (`site/modules/scroll-cue.js`): the scroll extent follows the table
as it narrows, a rebuilt table's cue releases its observers, and the pinned width comes from
the table on screen."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

WRAP = "document.querySelector('#mlb-chart-area .crews-table-wrap.table-scroll')"


def test_scroll_extent_shrinks_when_the_table_narrows(
    mlb_mobile_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    page = mlb_mobile_page
    open_mlb_app(page, "?sport=mlb")
    page.wait_for_function(f"() => {WRAP}.classList.contains('has-more-right')")
    # Hide every column past the second: the table now fits, so the fade and extent must go.
    page.evaluate(
        f"""() => {{
          {WRAP}.querySelectorAll('tr').forEach((tr) =>
            [...tr.children].slice(2).forEach((c) => {{ c.style.display = 'none'; }}));
          {WRAP}.querySelector('table').style.cssText = 'width:auto;min-width:0';
        }}"""
    )
    page.wait_for_function(
        f"""() => {{ const w = {WRAP};
          return w.scrollWidth <= w.clientWidth
            && !w.classList.contains('has-more-right'); }}"""
    )


def test_detaching_a_rebuilt_table_releases_its_observers(
    mlb_mobile_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """CFB Crews rebuilds its tables on every render; each old cue must let go of them."""
    page = mlb_mobile_page
    page.add_init_script(
        """(() => {
          window.__cueLive = { io: 0, ro: 0, mq: 0 };
          for (const [name, key] of [['IntersectionObserver', 'io'], ['ResizeObserver', 'ro']]) {
            const Base = window[name];
            window[name] = class extends Base {
              constructor(...a) { super(...a); window.__cueLive[key] += 1; }
              disconnect() { window.__cueLive[key] -= 1; return super.disconnect(); }
            };
          }
          const add = MediaQueryList.prototype.addEventListener;
          const remove = MediaQueryList.prototype.removeEventListener;
          MediaQueryList.prototype.addEventListener = function (...a) {
            window.__cueLive.mq += 1; return add.apply(this, a);
          };
          MediaQueryList.prototype.removeEventListener = function (...a) {
            window.__cueLive.mq -= 1; return remove.apply(this, a);
          };
        })()"""
    )
    open_mlb_app(page, "?sport=mlb")
    grown = page.evaluate(
        """async () => {
          const { attachScrollCue } = await import('./modules/scroll-cue.js');
          const module = document.createElement('div');
          module.className = 'module';
          const head = document.createElement('div');
          head.className = 'module-head';
          module.append(head);
          document.body.append(module);
          const before = { ...window.__cueLive };
          let detach = () => {};
          for (let i = 0; i < 20; i += 1) {
            detach();
            const wrap = document.createElement('div');
            wrap.append(document.createElement('table'));
            module.replaceChildren(head, wrap);
            detach = attachScrollCue(wrap, null);
          }
          const now = window.__cueLive;
          return { io: now.io - before.io, ro: now.ro - before.ro, mq: now.mq - before.mq };
        }"""
    )
    assert grown == {"io": 1, "ro": 1, "mq": 1}


def test_phone_postseason_twin_is_not_in_a_scroller(
    mlb_mobile_page: Page, open_mlb_app: Callable[..., None]
) -> None:
    """16-05 (N1): the desktop grid owns the scroll box and cue; the phone twin sits in a plain
    wrapper so the page scrolls and its header sticks to the viewport."""
    page = mlb_mobile_page
    open_mlb_app(page, "?sport=mlb&view=postseason")
    view = "#mlb-view-postseason"
    assert page.locator(f"{view} .mlb-grid-wrap").is_hidden()
    assert (
        page.locator(f"{view} .mlb-phone-grid")
        .locator("xpath=ancestor::*[contains(@class,'table-scroll')]")
        .count()
        == 0
    )
    assert (
        page.locator(f"{view} .mlb-phone-wrap").evaluate("e => getComputedStyle(e).overflowY")
        == "visible"
    )
