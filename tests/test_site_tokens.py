"""Phase 13 design tokens: values, removed tokens, type scale and contrast (V8).

Pure text checks on site/style.css; no browser. The colour pairs below are the
ones the UI-SPEC "Color" section promises.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CSS = Path(__file__).resolve().parent.parent / "site" / "style.css"

LIGHT = {
    "--bg": "#F5F7F6",
    "--surface": "#EBEFED",
    "--ink": "#1E2321",
    "--muted": "#5A6460",
    "--rule": "#DAE0DD",
    "--rule-strong": "#C0C9C5",
    "--accent": "#1B4F5C",
    "--accent-soft": "#E3EDEF",
    "--accent-soft-hover": "#D3E3E7",
    "--disabled": "#8E9894",
    "--legend-none": "#687270",
    "--error": "#B3261E",
    "--game-rivalry": "#8F2D3A",
}
REMOVED = (
    "--text",
    "--border",
    "--muted-weak",
    "--reset",
    "--special",
    "--on-special",
    "--font-family",
    "--font-label",
)
SIZE_TOKENS = {"--font-caption", "--font-body", "--font-heading", "--font-display"}
ALLOWED_SIZES = {"12px", "14px", "20px", "22px", "27px"}


def _css() -> str:
    return CSS.read_text(encoding="utf-8")


def _root_tokens() -> dict[str, str]:
    css = _css()
    start = css.index(":root {")
    block = css[start : css.index("\n}", start)]
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"(--[\w-]+):\s*([^;]+);", block)}


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_light_token_values() -> None:
    tokens = _root_tokens()
    for name, value in LIGHT.items():
        assert tokens[name].upper() == value, f"{name}: {tokens.get(name)} != {value}"


def test_removed_tokens_are_gone() -> None:
    css = _css()
    for name in REMOVED:
        assert not re.search(rf"{re.escape(name)}(?![\w-])", css.replace("--font-caption", "")), (
            name
        )


def test_exactly_four_size_tokens() -> None:
    sizes = {k for k in _root_tokens() if k.startswith("--font-")}
    assert sizes == SIZE_TOKENS


def test_font_size_literals_are_on_the_scale() -> None:
    css = re.sub(r"/\*.*?\*/", "", _css(), flags=re.S)
    offenders: list[str] = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selector, body = m.group(1).strip(), m.group(2)
        for decl in re.finditer(r"(?<![\w-])(font-size|font):\s*([^;]+);", body):
            prop, value = decl.groups()
            if prop == "font-size":
                sizes = re.findall(r"\d+(?:\.\d+)?px", value)
            else:
                sizes = re.findall(r"(?<![\w/.])(\d+(?:\.\d+)?px)(?=\s*/|\s|$)", value)
            for size in sizes:
                if size not in ALLOWED_SIZES and not (
                    size == "16px" and "filters-sheet" in selector
                ):
                    offenders.append(f"{selector}: {decl.group(0)}")
    assert not offenders, offenders


def test_fonts_are_self_hosted() -> None:
    css = _css()
    assert css.count("@font-face") == 4
    assert "fonts.googleapis" not in css
    for name in (
        "roboto-condensed-latin-400-normal",
        "roboto-latin-400-normal",
        "roboto-latin-600-normal",
        "lm-roman-demi-latin-600-normal",
    ):
        assert f'url("fonts/{name}.woff2") format("woff2")' in css


TEXT_PAIRS = [
    (fg, bg)
    for fg in ("--ink", "--muted", "--accent")
    for bg in ("--bg", "--surface", "--accent-soft")
]


@pytest.mark.parametrize(("fg", "bg"), TEXT_PAIRS)
def test_text_contrast(fg: str, bg: str) -> None:
    tokens = _root_tokens()
    ratio = _ratio(tokens[fg], tokens[bg])
    assert ratio >= 4.5, f"{fg} on {bg}: {ratio:.2f}:1"


@pytest.mark.parametrize("fg", ["--game-playoff", "--game-bowl", "--game-rivalry"])
@pytest.mark.parametrize("bg", ["--bg", "--surface"])
def test_game_icon_contrast(fg: str, bg: str) -> None:
    tokens = _root_tokens()
    ratio = _ratio(tokens[fg], tokens[bg])
    assert ratio >= 3.0, f"{fg} on {bg}: {ratio:.2f}:1"


@pytest.mark.parametrize("fg", ["--game-playoff-text", "--error"])
@pytest.mark.parametrize("bg", ["--bg", "--surface"])
def test_text_colours_contrast(fg: str, bg: str) -> None:
    tokens = _root_tokens()
    ratio = _ratio(tokens[fg], tokens[bg])
    assert ratio >= 4.5, f"{fg} on {bg}: {ratio:.2f}:1"


@pytest.mark.parametrize("tone", ["gold", "silver"])
def test_rank_pill_text_contrast(tone: str) -> None:
    tokens = _root_tokens()
    ratio = _ratio(tokens[f"--pill-{tone}-ink"], tokens[f"--pill-{tone}-fill"])
    assert ratio >= 4.5, f"pill {tone} text: {ratio:.2f}:1"


@pytest.mark.parametrize("tone", ["gold", "silver"])
@pytest.mark.parametrize("bg", ["--bg", "--accent-soft"])
def test_rank_pill_edge_contrast(tone: str, bg: str) -> None:
    tokens = _root_tokens()
    ratio = _ratio(tokens[f"--pill-{tone}-edge"], tokens[bg])
    assert ratio >= 3.0, f"pill {tone} edge on {bg}: {ratio:.2f}:1"


DARK = {
    "--bg": "#191D1C",
    "--surface": "#212625",
    "--ink": "#E5EAE8",
    "--muted": "#9EA8A4",
    "--rule": "#333A38",
    "--rule-strong": "#434B48",
    "--accent": "#68BACB",
    "--accent-soft": "#223A40",
    "--accent-soft-hover": "#274046",
    "--disabled": "#76807C",
    "--legend-none": "#87918D",
    "--error": "#F0877F",
    "--game-playoff": "#D9A420",
    "--game-bowl": "#D9824A",
    "--game-rivalry": "#E0707F",
    "--game-playoff-text": "#E3B845",
    "--pill-gold-fill": "#3F3413",
    "--pill-gold-ink": "#F2DFA0",
    "--pill-gold-edge": "#B8921F",
    "--pill-silver-fill": "#37393E",
    "--pill-silver-ink": "#D9DBDF",
    "--pill-silver-edge": "#8E939B",
}

# (foreground, background, minimum ratio) from the 17-UI-SPEC contrast table;
# decoration and disabled rows are exempt.
DARK_CONTRAST = [
    ("--ink", "--bg", 4.5),
    ("--ink", "--surface", 4.5),
    ("--ink", "--accent-soft", 4.5),
    ("--ink", "--accent-soft-hover", 4.5),
    ("--muted", "--bg", 4.5),
    ("--muted", "--surface", 4.5),
    ("--muted", "--accent-soft", 4.5),
    ("--accent", "--bg", 4.5),
    ("--accent", "--surface", 4.5),
    ("--accent", "--accent-soft", 4.5),
    ("--accent", "--accent-soft-hover", 4.5),
    ("--error", "--bg", 4.5),
    ("--error", "--surface", 4.5),
    ("--game-playoff-text", "--bg", 4.5),
    ("--game-playoff-text", "--surface", 4.5),
    ("--game-playoff", "--bg", 3.0),
    ("--game-playoff", "--surface", 3.0),
    ("--game-bowl", "--bg", 3.0),
    ("--game-bowl", "--surface", 3.0),
    ("--game-rivalry", "--bg", 3.0),
    ("--game-rivalry", "--surface", 3.0),
    ("--pill-gold-ink", "--pill-gold-fill", 4.5),
    ("--pill-silver-ink", "--pill-silver-fill", 4.5),
    ("--pill-gold-edge", "--bg", 3.0),
    ("--pill-gold-edge", "--accent-soft", 3.0),
    ("--pill-silver-edge", "--bg", 3.0),
    ("--pill-silver-edge", "--accent-soft", 3.0),
]


def _dark_tokens() -> dict[str, str]:
    css = _css()
    start = css.index('[data-theme="dark"] {')
    block = css[start : css.index("\n}", start)]
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"(--[\w-]+):\s*([^;]+);", block)}


def test_dark_token_values() -> None:
    tokens = _dark_tokens()
    for name, value in DARK.items():
        assert tokens[name].upper() == value, f"{name}: {tokens.get(name)} != {value}"
    block = _css()[_css().index('[data-theme="dark"] {') :].split("\n}", 1)[0]
    assert "color-scheme: dark" in block


@pytest.mark.parametrize(("fg", "bg", "minimum"), DARK_CONTRAST)
def test_dark_contrast(fg: str, bg: str, minimum: float) -> None:
    tokens = _dark_tokens()
    ratio = _ratio(tokens[fg], tokens[bg])
    assert ratio >= minimum, f"dark {fg} on {bg}: {ratio:.2f}:1"


# Phase 26 (26-UI-SPEC.md): every text pair meets 4.5:1 and icons 3:1 in light and dark.
# Exempt on purpose: --disabled (disabled controls) and --rule / --rule-strong (decoration).
THEME_CONTRAST = [
    ("--ink", "--bg", 4.5),
    ("--muted", "--bg", 4.5),
    ("--accent", "--bg", 4.5),
    ("--legend-none", "--bg", 4.5),
    ("--ink", "--surface", 4.5),
    ("--muted", "--surface", 4.5),
    ("--accent", "--surface", 4.5),
    ("--accent", "--accent-soft", 4.5),
    ("--game-playoff", "--bg", 3.0),
    ("--game-bowl", "--bg", 3.0),
    ("--game-rivalry", "--bg", 3.0),
]


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize(("fg", "bg", "minimum"), THEME_CONTRAST)
def test_theme_contrast(theme: str, fg: str, bg: str, minimum: float) -> None:
    tokens = _root_tokens() if theme == "light" else _dark_tokens()
    ratio = _ratio(tokens[fg], tokens[bg])
    assert ratio >= minimum, f"{theme} {fg} on {bg}: {ratio:.2f}:1"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_bg_text_on_accent(theme: str) -> None:
    tokens = _root_tokens() if theme == "light" else _dark_tokens()
    ratio = _ratio(tokens["--bg"], tokens["--accent"])
    assert ratio >= 4.5, f"{theme} --bg on --accent: {ratio:.2f}:1"


def test_print_block_restates_light_tokens() -> None:
    css = _css()
    start = css.index('@media print {\n  [data-theme="dark"] {')
    block = css[start : css.index("\n  }", start)]
    printed = {
        m.group(1): m.group(2).strip().upper()
        for m in re.finditer(r"(--[\w-]+):\s*([^;]+);", block)
    }
    light = {k: v.upper() for k, v in _root_tokens().items()}
    assert "--legend-none" in printed
    for name, value in printed.items():
        assert light[name] == value, f"print {name}: {value} != light {light[name]}"
