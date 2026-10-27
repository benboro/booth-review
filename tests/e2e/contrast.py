"""Shared e2e contrast helper: the WCAG 2.x ratio of two computed colours."""

from __future__ import annotations

import re

_NUM = re.compile(r"[\d.]+")


def _channels(css_color: str) -> tuple[float, float, float]:
    """The red, green and blue (0-255) of a computed `rgb(...)` or `rgba(...)` string."""
    nums = _NUM.findall(css_color)
    if len(nums) < 3:
        raise ValueError(f"not an rgb colour: {css_color!r}")
    return float(nums[0]), float(nums[1]), float(nums[2])


def luminance(css_color: str) -> float:
    """WCAG relative luminance of a computed `rgb()` string."""

    def lin(v: float) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(v) for v in _channels(css_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(fg_rgb: str, bg_rgb: str) -> float:
    """WCAG contrast ratio of a foreground over an opaque background, both computed `rgb()`."""
    a, b = luminance(fg_rgb), luminance(bg_rgb)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)
