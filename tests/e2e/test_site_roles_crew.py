"""04.6 SITE-37/38 primitives: role pills, crew box, role controls, boxed selection row."""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_SCHEMES = ("light", "dark")

_RESOLVE_JS = """
(el) => {
  const read = (css) => {
    const c = document.createElement('canvas'); c.width = 1; c.height = 1;
    const ctx = c.getContext('2d', { willReadFrequently: true });
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = css; ctx.fillRect(0, 0, 1, 1);
    const d = ctx.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3]];
  };
  const cs = getComputedStyle(el);
  return { color: read(cs.color), background: read(cs.backgroundColor) };
}
"""

_PILLS_JS = """
async () => {
  const { makeRolePill } = await import(new URL('./modules/pill.js', location.href).href);
  const box = document.createElement('div');
  box.className = 'crew-box';
  box.id = 'test-crew-box';
  for (const r of ['pbp', 'analyst', 'unknown']) box.append(makeRolePill(r));
  document.body.append(box);
}
"""


def _parse_rgb(css_color: str) -> tuple[float, float, float]:
    nums = re.findall(r"[\d.]+", css_color)
    return float(nums[0]), float(nums[1]), float(nums[2])


def _relative_luminance(rgb: tuple[float, float, float]) -> float:
    def channel(c: float) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast_ratio(fg: tuple[float, float, float], bg: tuple[float, float, float]) -> float:
    l1 = _relative_luminance(fg) + 0.05
    l2 = _relative_luminance(bg) + 0.05
    return max(l1, l2) / min(l1, l2)


def _token(page: Page, name: str) -> str:
    result: str = page.evaluate(
        "(n) => { const s = document.createElement('span'); s.style.color = `var(${n})`;"
        "document.body.append(s); const c = getComputedStyle(s).color; s.remove(); return c; }",
        name,
    )
    return result


def _resolved(page: Page, selector: str) -> dict[str, list[int]]:
    result: dict[str, list[int]] = page.locator(selector).evaluate(_RESOLVE_JS)
    return result


def _rgb(px: list[int]) -> tuple[float, float, float]:
    return float(px[0]), float(px[1]), float(px[2])


def _composite(top: list[int], under: tuple[float, float, float]) -> tuple[float, float, float]:
    a = top[3] / 255
    return tuple(top[i] * a + under[i] * (1 - a) for i in range(3))  # type: ignore[return-value]


def test_role_key_allowlists_prototype_names(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    keys = guarded_page.evaluate(
        """async () => {
          const { roleKey } = await import(new URL('./modules/pill.js', location.href).href);
          return ['pbp', 'analyst', 'constructor', '__proto__', 'toString', '', null, undefined, 7]
            .map((r) => roleKey(r));
        }"""
    )
    assert keys == ["pbp", "analyst"] + ["unknown"] * 7


def test_make_role_pill_text_name_and_safety(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    rows = guarded_page.evaluate(
        """async () => {
          const { makeRolePill } = await import(new URL('./modules/pill.js', location.href).href);
          const roles = ['pbp', 'analyst', 'unknown', 'constructor',
            '<img src=x onerror=alert(1)>'];
          return roles.map((r) => {
            const s = makeRolePill(r);
            return { cls: s.className, role: s.dataset.role, roleAttr: s.getAttribute('role'),
                     label: s.getAttribute('aria-label'), text: s.textContent,
                     kids: s.childNodes.length, color: s.style.color };
          });
        }"""
    )
    expected = [
        ("pbp", "PBP", "PBP, play-by-play"),
        ("analyst", "Analyst", "Analyst"),
        ("unknown", "Sideline", "Sideline"),
        ("unknown", "Sideline", "Sideline"),
        ("unknown", "Sideline", "Sideline"),
    ]
    for row, (role, text, label) in zip(rows, expected, strict=True):
        assert row["cls"] == "role-pill"
        assert row["role"] == role
        assert row["roleAttr"] == "img"
        assert row["label"] == label
        assert row["text"] == text
        assert row["kids"] == 1
        assert row["color"] == ""


@pytest.mark.parametrize("scheme", _SCHEMES)
def test_role_pill_contrast(
    guarded_page: Page, open_app: Callable[[Page, str], None], scheme: str
) -> None:
    guarded_page.emulate_media(color_scheme=scheme)  # type: ignore[arg-type]
    open_app(guarded_page, "")
    guarded_page.evaluate(_PILLS_JS)
    bg = _parse_rgb(_token(guarded_page, "--bg"))
    tint = _composite(
        _resolved(guarded_page, "#test-crew-box")["background"],
        _parse_rgb(_token(guarded_page, "--surface")),
    )
    for role in ("pbp", "analyst", "unknown"):
        info = _resolved(guarded_page, f"#test-crew-box .role-pill[data-role={role}]")
        fg = _rgb(info["color"])
        own = info["background"]
        backs = {"bg": bg, "tint": tint}
        if own[3] > 0:
            backs = {"own": _rgb(own)}
        for name, back in backs.items():
            ratio = _contrast_ratio(fg, back)
            assert ratio >= 4.5, f"{role} on {name} in {scheme}: {ratio:.2f}"


@pytest.mark.parametrize("scheme", _SCHEMES)
def test_crew_box_style(
    guarded_page: Page, open_app: Callable[[Page, str], None], scheme: str
) -> None:
    guarded_page.emulate_media(color_scheme=scheme)  # type: ignore[arg-type]
    open_app(guarded_page, "")
    guarded_page.evaluate(_PILLS_JS)
    style = guarded_page.locator("#test-crew-box").evaluate(
        "(el) => { const c = getComputedStyle(el); return { w: c.borderTopWidth, "
        "s: c.borderTopStyle, col: c.borderTopColor, r: c.borderTopLeftRadius, "
        "p: c.paddingTop }; }"
    )
    assert style["w"] == "1px"
    assert style["s"] == "solid"
    assert style["col"] == _token(guarded_page, "--special")
    assert style["r"] == "8px"
    assert style["p"] == "8px"


def test_role_control_pills(guarded_page: Page, open_app: Callable[[Page, str], None]) -> None:
    open_app(guarded_page, "?school=northfield&view=bars")
    toggle = guarded_page.locator("#bar-role-toggle")
    both = toggle.locator('button[data-role=""]')
    assert both.locator(".role-pill").count() == 0
    assert (both.text_content() or "").strip() == "Both"
    for role, label, text in (
        ("pbp", "PBP, play-by-play", "PBP"),
        ("analyst", "Analyst", "Analyst"),
    ):
        btn = toggle.locator(f'button[data-role="{role}"]')
        pills = btn.locator(".role-pill")
        assert pills.count() == 1
        assert pills.get_attribute("data-role") == role
        assert btn.get_attribute("aria-label") == label
        assert (btn.text_content() or "").strip() == text
    toggle.locator('button[data-role="pbp"]').click()
    assert toggle.locator('button[data-role="pbp"]').get_attribute("aria-pressed") == "true"
    assert "role=pbp" in guarded_page.url


def test_role_filter_popover_pills(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    guarded_page.click("#trigger-role")
    guarded_page.wait_for_function("document.getElementById('pop-role').matches(':popover-open')")
    labels = guarded_page.locator("#pop-role label")
    assert labels.count() == 2
    for i in range(2):
        assert labels.nth(i).locator(".role-pill").count() == 1
    assert guarded_page.get_by_role("checkbox", name="PBP, play-by-play").count() == 1
    assert guarded_page.get_by_role("checkbox", name="Analyst").count() == 1


@pytest.mark.parametrize("scheme", _SCHEMES)
def test_selection_row_box(
    guarded_page: Page, open_app: Callable[[Page, str], None], scheme: str
) -> None:
    guarded_page.emulate_media(color_scheme=scheme)  # type: ignore[arg-type]
    open_app(guarded_page, "?people=dale-harlow")
    row = guarded_page.locator("#selection-row")
    style = row.evaluate(
        "(el) => { const c = getComputedStyle(el); return { w: c.borderTopWidth, "
        "col: c.borderTopColor, r: c.borderTopLeftRadius, p: c.paddingTop }; }"
    )
    assert style["w"] == "1px"
    assert style["col"] == _token(guarded_page, "--special")
    assert style["r"] == "8px"
    assert style["p"] == "8px"
    assert row.locator("#summary").count() == 0
    assert row.locator("#compare-note").count() == 0


_SHOW_TOOLTIP_JS = """
async ([i, selectedIds]) => {
  const { showTooltip } = await import(new URL('./modules/tooltip.js', location.href).href);
  const data = window.__testHooks.data;
  const selected = new Set(selectedIds.map((id) => data.personIndexById.get(id)));
  showTooltip(data, i, { axis: 'pregame', theme: 'light', clientX: 200, clientY: 200, selected });
}
"""


@pytest.mark.parametrize("scheme", _SCHEMES)
def test_tooltip_crew_box_and_pills(
    guarded_page: Page, open_app: Callable[[Page, str], None], scheme: str
) -> None:
    guarded_page.emulate_media(color_scheme=scheme)  # type: ignore[arg-type]
    open_app(guarded_page, "")
    guarded_page.evaluate(_SHOW_TOOLTIP_JS, [0, []])
    box = guarded_page.locator("#chart-tooltip .crew-box")
    assert box.count() == 1
    lines = box.locator(".crew-line")
    assert lines.count() == 2
    assert lines.nth(0).locator(".crew-name").text_content() == "Dale Harlow"
    assert lines.nth(0).locator(".role-pill").get_attribute("data-role") == "pbp"
    assert lines.nth(1).locator(".crew-name").text_content() == "Dale Harlow Jr."
    assert lines.nth(1).locator(".role-pill").get_attribute("data-role") == "analyst"
    assert "Play-by-play:" not in guarded_page.inner_text("#chart-tooltip")
    border = box.evaluate("(el) => getComputedStyle(el).borderTopColor")
    assert border == _token(guarded_page, "--special")


@pytest.mark.parametrize("scheme", _SCHEMES)
def test_tooltip_selected_name_is_bold(
    guarded_page: Page, open_app: Callable[[Page, str], None], scheme: str
) -> None:
    guarded_page.emulate_media(color_scheme=scheme)  # type: ignore[arg-type]
    open_app(guarded_page, "?people=dale-harlow")
    guarded_page.evaluate(_SHOW_TOOLTIP_JS, [0, ["dale-harlow"]])
    weights = guarded_page.locator("#chart-tooltip .crew-name").evaluate_all(
        "els => els.map(e => getComputedStyle(e).fontWeight)"
    )
    assert weights == ["600", "400"]


@pytest.mark.parametrize("scheme", _SCHEMES)
def test_crew_not_recorded_has_no_box(
    guarded_page: Page, open_app: Callable[[Page, str], None], scheme: str
) -> None:
    guarded_page.emulate_media(color_scheme=scheme)  # type: ignore[arg-type]
    open_app(guarded_page, "")
    guarded_page.evaluate(
        """async () => {
          const { tooltipModel, renderTooltipContent, ensureTooltipEl } =
            await import(new URL('./modules/tooltip.js', location.href).href);
          const model = tooltipModel(window.__testHooks.data, 0, { axis: 'pregame' });
          model.crew = [];
          const el = ensureTooltipEl();
          renderTooltipContent(el, model, 'light');
          el.hidden = false;
        }"""
    )
    assert guarded_page.locator("#chart-tooltip .crew-box").count() == 0
    missing = guarded_page.locator("#chart-tooltip .crew-missing")
    assert missing.text_content() == "Crew not recorded"
    assert missing.evaluate("(el) => getComputedStyle(el).color") == _token(guarded_page, "--muted")


@pytest.mark.parametrize("scheme", _SCHEMES)
def test_modal_crew_box_wraps_all_feeds(
    guarded_page: Page, open_app: Callable[[Page, str], None], scheme: str
) -> None:
    guarded_page.emulate_media(color_scheme=scheme)  # type: ignore[arg-type]
    open_app(guarded_page, "")
    # Telecast 7 has an alt-cast analyst; telecast 8 has an unknown-role person.
    guarded_page.evaluate("window.__testHooks.openPanel(7)")
    boxes = guarded_page.locator("#panel-body .crew-box")
    assert boxes.count() == 1
    items = boxes.locator("li")
    assert items.count() == 3
    alt = items.nth(2)
    assert (alt.text_content() or "").endswith("Analyst (alt-cast)")
    kids = alt.evaluate("(el) => [...el.children].map(c => c.className)")
    assert kids == ["name-with-roles", "crew-feed"]
    assert alt.locator(".name-with-roles").evaluate(
        "(el) => [...el.children].map(c => c.className)"
    ) == ["crew-name", "role-pill"]
    border = boxes.evaluate("(el) => getComputedStyle(el).borderTopColor")
    assert border == _token(guarded_page, "--special")
    guarded_page.evaluate("window.__testHooks.openPanel(8)")
    pill = guarded_page.locator("#panel-body .crew-box li .role-pill[data-role=unknown]")
    assert pill.count() == 1
    assert pill.text_content() == "Sideline"


def test_crew_name_markup_is_text(
    guarded_page: Page, open_app: Callable[[Page, str], None]
) -> None:
    open_app(guarded_page, "")
    result = guarded_page.evaluate(
        """async () => {
          const { tooltipModel, renderTooltipContent } =
            await import(new URL('./modules/tooltip.js', location.href).href);
          const data = structuredClone(window.__testHooks.data);
          data.personIndexById = window.__testHooks.data.personIndexById;
          data.lookups.people[0].name = '<b>x</b>';
          const div = document.createElement('div');
          renderTooltipContent(div, tooltipModel(data, 0, { axis: 'pregame' }), 'light');
          return { bold: div.querySelectorAll('b').length,
                   text: div.querySelector('.crew-name').textContent };
        }"""
    )
    assert result == {"bold": 0, "text": "<b>x</b>"}


@pytest.mark.parametrize("font_setting", ["default", "dejavu", "wide"], indirect=True)
@pytest.mark.parametrize("width", [1280, 360])
def test_table_crew_pills_stay_on_their_names_line(
    guarded_page: Page,
    open_app: Callable[[Page, str], None],
    fixture_raw: dict[str, Any],
    width: int,
) -> None:
    """SITE-38: a role pill never wraps onto a line without its announcer.

    Long names force the crew cell to wrap; each pill's top must equal the
    top of its name's last line box, and the cell must not overflow
    horizontally (decision: `.name-with-roles { white-space: nowrap }`).
    """
    raw = copy.deepcopy(fixture_raw)
    for person in raw["lookups"]["people"]:
        person["name"] = f"{person['name']} Featherstone-Wellington"
    guarded_page.route("**/site-data.json*", lambda route: route.fulfill(json=raw))
    guarded_page.set_viewport_size({"width": width, "height": 800})
    open_app(guarded_page, "?people=dale-harlow")
    cells = guarded_page.locator("#games-table tbody tr td:has(.name-with-roles)")
    assert cells.count() > 0
    result = cells.first.evaluate(
        """(td) => {
          const units = [...td.querySelectorAll('.name-with-roles')];
          return {
            overflow: td.scrollWidth > td.clientWidth + 1,
            pages: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
            units: units.map((u) => {
              const name = u.querySelector('.crew-name').getClientRects();
              const lastLineTop = name[name.length - 1].top;
              return [...u.querySelectorAll('.role-pill')].map(
                (p) => Math.abs(p.getBoundingClientRect().top - lastLineTop) < 8,
              );
            }),
          };
        }"""
    )
    assert result["units"], "expected crew units"
    assert all(all(u) for u in result["units"])
    assert not result["overflow"]
