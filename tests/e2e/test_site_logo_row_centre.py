"""Network logos centre in one-line table rows (user 2026-11-13).

`span.net-mark` is inline-flex, and an inline-flex box sits on the text baseline by its
logo's bottom edge, which lifted logos 2-5px above the row's centre in the This weekend
compact table and the Crews tables. Each mark here is built by the real `networkMark` and
styled by the real style sheet, inside the same table classes those views use.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


@pytest.fixture
def app_page(guarded_page: Page, open_app: Callable[[Page, str], None]) -> Page:
    """The app loaded once so `import('./modules/...')` resolves."""
    open_app(guarded_page, "")
    return guarded_page


TOL = 1.0

# A wordmark (14px), a badge (20px) and the 24px MW+ mark.
NETWORKS = [
    {"id": "fox", "name": "FOX", "family": "fox"},
    {"id": "abc", "name": "ABC", "family": "disney"},
    {"id": "mountain-west-network", "name": "Mountain West Network", "family": "conference"},
]

# (table class, row class, network cell class) for each one-line row surface.
SURFACES = [
    ("wk-compact-table", "wk-crow", ""),
    ("crews-table", "crews-row", "crews-network"),
    ("crews-games", "crews-game", ""),
]

_JS = """
async ([networks, surfaces]) => {
  const { networkMark } = await import(new URL('./modules/network.js', location.href).href);
  const host = document.createElement('div');
  document.body.appendChild(host);
  const out = [];
  for (const [tableCls, rowCls, cellCls] of surfaces) {
    for (const net of networks) {
      const table = document.createElement('table');
      table.className = tableCls;
      const row = table.createTBody().insertRow();
      row.className = rowCls;
      row.insertCell().textContent = 'Fresno State @ Boise State';
      const cell = row.insertCell();
      if (cellCls) cell.className = cellCls;
      cell.appendChild(networkMark(net));
      host.appendChild(table);
      const img = cell.querySelector('img');
      await img.decode().catch(() => {});
      const r = img.getBoundingClientRect();
      const rr = row.getBoundingClientRect();
      out.push([tableCls, net.id, r.top + r.height / 2 - (rr.top + rr.height / 2), r.height]);
    }
  }
  host.remove();
  return out;
}
"""


def test_network_logos_centre_in_one_line_rows(app_page: Page) -> None:
    got = app_page.evaluate(_JS, [NETWORKS, SURFACES])
    assert len(got) == len(NETWORKS) * len(SURFACES)
    for table, net_id, offset, height in got:
        assert height > 0, (table, net_id)
        assert abs(offset) <= TOL, (table, net_id, offset)
