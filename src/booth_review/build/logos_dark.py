"""Dark-theme variants of the vendored network logos (Phase 17, D-09).

`<img>` logos cannot see page CSS, so black wordmarks vanish on the warm-dark
ground. `dark_variant` recolours one source SVG's paints so every mark reads on
the four dark surfaces; assembly writes the result to `logos/dark/<name>.svg`.
The sources under `site/logos/` are never edited.

Rules, applied to every paint (UI-SPEC "Dark logo variants"):

1. A dark neutral (OKLab chroma < 0.04, lightness < 0.28, under 3:1 on some dark
   surface) becomes off-white. The cutoff leaves Prime navy #232F3E to rule 4.
2. In a flipped-disc file, a light neutral (the letters) becomes the dark ground.
3. A paint that already clears 3:1 on all four surfaces is kept.
4. Any other paint is lifted in OKLab lightness (hue and chroma held) to the
   first step that clears 3.1:1 on all four surfaces.
5. White in a file that had a lift stays white while it clears 3:1 against every
   lifted paint, else it takes the dark ground.

Only colour tokens are rewritten, by regex, so every other byte is unchanged;
an unrecognised colour syntax raises `SiteBuildError`, and so does `currentColor`
(an `<img>` resolves it to black) or any fill/stroke/stop-color paint the strict
regexes do not parse (for example `fill = "#000"`), which a loose scan counts.
Stdlib only.
"""

from __future__ import annotations

import math
import re

from booth_review.errors import SiteBuildError

DARK_BACKGROUNDS: tuple[str, ...] = ("#1D1B18", "#26231F", "#223A40", "#274046")
OFF_WHITE = "#ECE7DF"
DARK_GROUND = "#1D1B18"
WHITE = "#FFFFFF"

# Files whose light neutral letters sit on a dark backplate that rule 1 flips.
FLIP_PAIR_FILES: frozenset[str] = frozenset({"abc.svg", "espnu.svg"})

NEUTRAL_CHROMA = 0.04
DARK_NEUTRAL_L = 0.28
LIGHT_NEUTRAL_L = 0.85
KEEP_CONTRAST = 3.0
LIFT_CONTRAST = 3.1
LIFT_STEP = 0.005

_KEEP_WORDS = frozenset({"none", "inherit", "transparent"})
_NAMED = {"black": "#000000", "white": "#FFFFFF"}

# fill="..." attributes and `fill: ...` declarations (style attributes, <style>).
_ATTR = re.compile(r"""(?<=\s)(fill|stroke|stop-color)=(["'])(.*?)\2""", re.S)
_DECL = re.compile(r"(?<![\w-])(fill|stroke|stop-color)(\s*:\s*)([^;\"'}<]+)")
_ROOT = re.compile(r"<svg\b[^>]*>", re.S)
_HEX = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
# Every paint property name followed by `=` or `:`, however spaced (not fill-rule and kin).
_LOOSE = re.compile(r"(?<![\w-])(fill|stroke|stop-color)(?![\w-])\s*[=:]")


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


def _to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _from_linear(c: float) -> float:
    c = min(1.0, max(0.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def luminance(hex_color: str) -> float:
    """WCAG relative luminance (same formula as palette.js)."""
    r, g, b = (_to_linear(c) for c in _hex_to_rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two hex colours."""
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def to_oklab(hex_color: str) -> tuple[float, float, float]:
    r, g, b = (_to_linear(c) for c in _hex_to_rgb(hex_color))
    lng = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    lc, mc, sc = lng ** (1 / 3), m ** (1 / 3), s ** (1 / 3)
    return (
        0.2104542553 * lc + 0.7936177850 * mc - 0.0040720468 * sc,
        1.9779984951 * lc - 2.4285922050 * mc + 0.4505937099 * sc,
        0.0259040371 * lc + 0.7827717662 * mc - 0.8086757660 * sc,
    )


def from_oklab(lab: tuple[float, float, float]) -> str:
    """OKLab to a gamut-clamped, rounded `#RRGGBB`."""
    big_l, a, b = lab
    lc = big_l + 0.3963377774 * a + 0.2158037573 * b
    mc = big_l - 0.1055613458 * a - 0.0638541728 * b
    sc = big_l - 0.0894841775 * a - 1.2914855480 * b
    lng, m, s = lc**3, mc**3, sc**3
    r = 4.0767416621 * lng - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * lng + 2.6097574011 * m - 0.3413193965 * s
    bl = -0.0041960863 * lng - 0.7034186147 * m + 1.7076147010 * s
    return "#" + "".join(f"{round(_from_linear(c) * 255):02X}" for c in (r, g, bl))


def _chroma(lab: tuple[float, float, float]) -> float:
    return math.hypot(lab[1], lab[2])


def _min_contrast(hex_color: str) -> float:
    return min(contrast(hex_color, bg) for bg in DARK_BACKGROUNDS)


def _lift(hex_color: str) -> str:
    big_l, a, b = to_oklab(hex_color)
    while big_l < 1.0:
        big_l += LIFT_STEP
        candidate = from_oklab((big_l, a, b))
        if _min_contrast(candidate) >= LIFT_CONTRAST:
            return candidate
    return WHITE


def _normalise(token: str) -> str | None:
    """Return `#RRGGBB` (upper) for a colour token, None to leave it alone."""
    value = token.strip()
    low = value.lower()
    if low == "currentcolor":
        raise SiteBuildError("logo dark variant: currentColor paints black in an <img>")
    if low in _KEEP_WORDS or low.startswith("url("):
        return None
    if low in _NAMED:
        return _NAMED[low]
    match = _HEX.match(value)
    if match is None:
        raise SiteBuildError(f"logo dark variant: unsupported colour syntax {value!r}")
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return "#" + digits.upper()


def _paints(text: str) -> list[str]:
    attrs = list(_ATTR.finditer(text))
    decls = list(_DECL.finditer(text))
    loose = len(_LOOSE.findall(text))
    if loose != len(attrs) + len(decls):
        raise SiteBuildError(
            f"logo dark variant: {loose} paint properties but only "
            f"{len(attrs) + len(decls)} parse as fill/stroke/stop-color tokens"
        )
    found = [_normalise(m.group(3)) for m in attrs]
    found += [_normalise(m.group(3)) for m in decls]
    return [p for p in found if p is not None]


def _build_mapping(paints: set[str], *, flip_pair: bool) -> dict[str, str]:
    mapping: dict[str, str] = {}
    lifted: list[str] = []
    for paint in sorted(paints):
        lab = to_oklab(paint)
        neutral = _chroma(lab) < NEUTRAL_CHROMA
        low = _min_contrast(paint)
        if neutral and lab[0] < DARK_NEUTRAL_L and low < KEEP_CONTRAST:
            mapping[paint] = OFF_WHITE
        elif flip_pair and neutral and lab[0] >= LIGHT_NEUTRAL_L:
            mapping[paint] = DARK_GROUND
        elif low >= KEEP_CONTRAST:
            mapping[paint] = paint
        else:
            mapping[paint] = _lift(paint)
            lifted.append(mapping[paint])
    # Rule 5: white pairs stay white while they clear 3:1 against every lifted paint.
    if (
        lifted
        and mapping.get(WHITE) == WHITE
        and any(contrast(WHITE, fill) < KEEP_CONTRAST for fill in lifted)
    ):
        mapping[WHITE] = DARK_GROUND
    return mapping


def dark_variant(source: bytes, *, flip_pair: bool = False) -> bytes:
    """Return the dark-theme bytes for one source logo SVG (deterministic)."""
    text = source.decode("utf-8")
    mapping = _build_mapping(set(_paints(text)), flip_pair=flip_pair)

    def swap(token: str) -> str:
        norm = _normalise(token)
        if norm is None:
            return token
        new = mapping[norm]
        return token if new == norm and token.strip().lower() not in _NAMED else new

    text = _ATTR.sub(lambda m: f"{m.group(1)}={m.group(2)}{swap(m.group(3))}{m.group(2)}", text)
    text = _DECL.sub(lambda m: f"{m.group(1)}{m.group(2)}{swap(m.group(3))}", text)
    root = _ROOT.search(text)
    if root is not None and not re.search(r"(?<=\s)fill\s*[=:]", root.group(0)):
        text = f'{text[: root.start() + 4]} fill="{OFF_WHITE}"{text[root.start() + 4 :]}'
    return text.encode("utf-8")
