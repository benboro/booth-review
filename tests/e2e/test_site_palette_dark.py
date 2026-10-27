"""DARK-01 (17-03): dark chart palette, theme-keyed pill text and outline, tooltips, tone B."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

OpenApp = Callable[[Page, str], None]

# Light branch of palette.js captured in-page from the unmodified module before 17-03 edits.
LIGHT_SNAPSHOT: dict[str, Any] = {
    "ACCENT": "#1E2321",
    "DIVIDER": "#DAE0DD",
    "FAMILY_COLORS": {
        "disney": "#0072B2",
        "fox": "#009E73",
        "cbs": "#B77F00",
        "nbc": "#C972A2",
        "cw": "#1D96DB",
        "wbd": "#D55E00",
        "conference": "#000000",
        "other": "#8B8B8B",
    },
    "INK": "#1E2321",
    "MAP_DOT_NEUTRAL": "#B3AA9C",
    "MAP_FAMILY_COLORS": {
        "disney": "#0072B2",
        # Phase 24: families under 3:1 on the land are deepened toward black (hue kept).
        "fox": "#009970",
        "cbs": "#B37C00",
        "nbc": "#BF6C9A",
        "cw": "#1C8FD0",
        "wbd": "#D55E00",
        "conference": "#6A5BA0",
        "other": "#878787",
    },
    "MAP_LAND": "#E8EDEA",
    "MAP_MARKER_LABEL": "#5A6460",
    "MAP_OUTLINE": "#BCC6C2",
    "MUTED": "#5A6460",
    "PAGE_BG": "#F5F7F6",
    "POSTSEASON_BAND": "rgba(166, 120, 40, 0.07)",
    "POSTSEASON_LABEL": "#6E4A10",
    "SPECIAL": "#1B4F5C",
    "SURFACE": "#EBEFED",
    "ZERO_LINE": "#C0C9C5",
    "PILL_TEXT_COLOR_light": {
        "disney": "#FFFFFF",
        "fox": "#000000",
        "cbs": "#000000",
        "nbc": "#000000",
        "cw": "#000000",
        "wbd": "#000000",
        "conference": "#FFFFFF",
        "other": "#000000",
    },
    "DOT_OUTLINE_light": "#000000",
    "shades": {
        "disney": [
            "#0072B2",
            "#66AAD1",
            "#00446B",
            "#A6CEE4",
            "#00283E",
            "#338EC1",
            "#005B8E",
            "#CCE3F0",
        ],
        "fox": [
            "#009E73",
            "#66C5AB",
            "#005F45",
            "#A6DDCE",
            "#003728",
            "#33B18F",
            "#007E5C",
            "#CCECE3",
        ],
        "cbs": [
            "#B77F00",
            "#D4B266",
            "#6E4C00",
            "#E6D2A6",
            "#402C00",
            "#C59933",
            "#926600",
            "#F1E5CC",
        ],
        "nbc": [
            "#C972A2",
            "#DFAAC7",
            "#794461",
            "#ECCEDE",
            "#462839",
            "#D48EB5",
            "#A15B82",
            "#F4E3EC",
        ],
        "cw": [
            "#1D96DB",
            "#77C0E9",
            "#115A83",
            "#B0DAF2",
            "#0A354D",
            "#4AABE2",
            "#1778AF",
            "#D2EAF8",
        ],
        "wbd": [
            "#D55E00",
            "#E69E66",
            "#803800",
            "#F0C7A6",
            "#4B2100",
            "#DD7E33",
            "#AA4B00",
            "#F7DFCC",
        ],
        "conference": [
            "#000000",
            "#666666",
            "#A6A6A6",
            "#333333",
            "#CCCCCC",
            "#808080",
            "#000000",
            "#666666",
        ],
        "other": [
            "#8B8B8B",
            "#B9B9B9",
            "#535353",
            "#D6D6D6",
            "#313131",
            "#A2A2A2",
            "#6F6F6F",
            "#E8E8E8",
        ],
    },
}

_FAMILIES = ["disney", "fox", "cbs", "nbc", "cw", "wbd", "conference", "other"]
_PAGE = "#191D1C"
_SURFACE = "#212625"
_LAND = "#242A28"

_DARK_FAMILY = {
    "disney": "#0A7BC0",
    "fox": "#009E73",
    "cbs": "#E69F00",
    "nbc": "#CC79A7",
    "cw": "#56B4E9",
    "wbd": "#D55E00",
    "conference": "#E4DFD6",
    "other": "#9C958A",
}
_DARK_TONE_B = {
    "disney": "#0D6DA7",
    "fox": "#048A65",
    "cbs": "#C88B04",
    "nbc": "#B26B92",
    "cw": "#4D9DCA",
    "wbd": "#B95404",
    "conference": "#C6C2BA",
    "other": "#898379",
}
_DARK_SCALARS = {
    "PAGE_BG": _PAGE,
    "SURFACE": _SURFACE,
    "INK": "#E5EAE8",
    "ACCENT": "#E5EAE8",
    "MUTED": "#9EA8A4",
    "DIVIDER": "#333A38",
    "ZERO_LINE": "#56605C",
    "SPECIAL": "#68BACB",
    "POSTSEASON_BAND": "rgba(212, 160, 60, 0.07)",
    "POSTSEASON_LABEL": "#E8BE6E",
    "MAP_LAND": _LAND,
    "MAP_OUTLINE": "#46504D",
    "MAP_DOT_NEUTRAL": "#8B8377",
}


@pytest.fixture
def app(guarded_page: Page, open_app: OpenApp) -> Page:
    open_app(guarded_page, "")
    return guarded_page


def _ev(page: Page, module: str, body: str, arg: Any = None) -> Any:
    script = f"async (arg) => {{ const M = await import('./modules/{module}'); {body} }}"
    return page.evaluate(script, arg)


def _ratio(page: Page, a: str, b: str) -> float:
    return float(_ev(page, "palette.js", "return M.contrastRatio(arg[0], arg[1]);", [a, b]))


def _hex_close(a: str, b: str, step: int = 1) -> bool:
    return all(abs(int(a[i : i + 2], 16) - int(b[i : i + 2], 16)) <= step for i in (1, 3, 5))


def test_light_branch_is_unchanged(app: Page) -> None:
    got = _ev(
        app,
        "palette.js",
        """
        const out = {};
        for (const [k, v] of Object.entries(M)) {
          if (k === 'PILL_TEXT_COLOR' || k === 'DOT_OUTLINE') continue;
          if (v && typeof v === 'object' && 'light' in v && 'dark' in v) out[k] = v.light;
        }
        out.PILL_TEXT_COLOR_light = M.PILL_TEXT_COLOR.light;
        out.DOT_OUTLINE_light = M.DOT_OUTLINE.light;
        out.shades = {};
        for (const f of arg) out.shades[f] = M.channelShades(f, 'light', 8);
        return JSON.parse(JSON.stringify(out));
        """,
        _FAMILIES,
    )
    assert got == LIGHT_SNAPSHOT


def test_dark_family_colours(app: Page) -> None:
    got = _ev(app, "palette.js", "return JSON.parse(JSON.stringify(M.FAMILY_COLORS.dark));")
    assert got == _DARK_FAMILY
    for fam, color in _DARK_FAMILY.items():
        assert _ratio(app, color, _PAGE) >= 3.0, fam
        assert _ratio(app, color, _SURFACE) >= 3.0, fam


def test_dark_pill_text(app: Page) -> None:
    got = _ev(app, "palette.js", "return JSON.parse(JSON.stringify(M.PILL_TEXT_COLOR.dark));")
    assert got == {f: ("#FFFFFF" if f == "disney" else "#000000") for f in _FAMILIES}
    for fam in _FAMILIES:
        assert _ratio(app, got[fam], _DARK_FAMILY[fam]) >= 4.5, fam


def test_dark_scalars(app: Page) -> None:
    got = _ev(
        app,
        "palette.js",
        (
            "const o = {}; for (const k of arg) o[k] = M[k].dark; "
            "o.DOT_OUTLINE = M.DOT_OUTLINE.dark; return o;"
        ),
        list(_DARK_SCALARS),
    )
    assert got.pop("DOT_OUTLINE") == "#E5EAE8"
    assert got == _DARK_SCALARS


def test_dark_map(app: Page) -> None:
    got = _ev(app, "palette.js", "return JSON.parse(JSON.stringify(M.MAP_FAMILY_COLORS.dark));")
    assert got == {**_DARK_FAMILY, "conference": "#9A8CD0"}
    for fam, color in got.items():
        assert _ratio(app, color, _LAND) >= 3.0, fam


def test_dark_channel_shades(app: Page) -> None:
    for fam in _FAMILIES:
        shades = _ev(app, "palette.js", "return M.channelShades(arg, 'dark', 8);", fam)
        # Phase 17 review F6: a 7th and 8th channel get their own shades, never a repeat.
        assert len(set(shades)) == 8, (fam, shades)
        for i, s in enumerate(shades):
            assert _ratio(app, s, _PAGE) >= 3.1, (fam, s)
            for t in shades[i + 1 :]:
                # The ladder's first shades keep the 1.15 gap; the finer dark extension 1.10.
                assert _ratio(app, s, t) >= 1.1, (fam, s, t)


def test_dark_shade_count_matches_light(app: Page) -> None:
    # Phase 17 review F6: dark reaches at least the light distinct-shade count for every family,
    # each shade at 3.1:1 or more on the dark page and 1.10 or more against every other shade.
    counts = _ev(
        app,
        "palette.js",
        """
        const out = {};
        for (const f of arg) {
          out[f] = {
            light: new Set(M.channelShades(f, 'light', 40)).size,
            dark: [...new Set(M.channelShades(f, 'dark', 40))],
          };
        }
        return out;
        """,
        _FAMILIES,
    )
    for fam, c in counts.items():
        dark = c["dark"]
        assert len(dark) >= c["light"], (fam, len(dark), c["light"])
        for i, s in enumerate(dark):
            assert _ratio(app, s, _PAGE) >= 3.1, (fam, s)
            for t in dark[i + 1 :]:
                assert _ratio(app, s, t) >= 1.1, (fam, s, t)
    assert _ev(app, "palette.js", "return M.channelShades('disney', 'dark', 8)[0];") != _ev(
        app, "palette.js", "return M.channelShades('disney', 'dark', 8)[6];"
    )


def test_bar_tones_dark(app: Page) -> None:
    for fam, expected in _DARK_TONE_B.items():
        tones = _ev(
            app,
            "bar-chart.js",
            "return M.barTones({ family: arg }, 'dark');",
            fam,
        )
        assert _hex_close(tones["b"], expected), (fam, tones["b"])
        assert _ratio(app, tones["b"], _PAGE) >= 3.0, fam
        assert _ratio(app, tones["a"], tones["b"]) >= 1.15, fam
    light = _ev(app, "bar-chart.js", "return M.barTones({ family: 'fox' }, 'light');")
    mixed = _ev(app, "palette.js", "return M.mixHex('#009E73', M.PAGE_BG.light, 0.55);")
    assert light["b"] == mixed


def test_frame_layout_dark(app: Page) -> None:
    dark = _ev(app, "chart-frame.js", "return M.frameLayout({}, { theme: 'dark' });")
    assert dark["paper_bgcolor"] == _PAGE
    assert dark["plot_bgcolor"] == _PAGE
    assert dark["hoverlabel"]["bgcolor"] == _SURFACE
    assert dark["hoverlabel"]["font"]["color"] == "#E5EAE8"
    assert dark["hoverlabel"]["bordercolor"] == "#333A38"
    light = _ev(app, "chart-frame.js", "return M.frameLayout({}, { theme: 'light' });")
    assert light["hoverlabel"]["font"]["color"] == "#1E2321"


def test_makepill_dark(app: Page) -> None:
    got = _ev(
        app,
        "pill.js",
        """
        const mk = (t, f, th) => { const s = M.makePill(t, f, th);
          return [s.style.color, s.style.backgroundColor]; };
        return [mk('ESPN', 'disney', 'dark'), mk('X', 'conference', 'dark'),
          mk('X', 'conference', 'light')];
        """,
    )
    assert got[0] == ["rgb(255, 255, 255)", "rgb(10, 123, 192)"]
    assert got[1] == ["rgb(0, 0, 0)", "rgb(228, 223, 214)"]
    assert got[2][0] == "rgb(255, 255, 255)"
