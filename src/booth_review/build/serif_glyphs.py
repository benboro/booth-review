"""Build-time guard: every serif-slot name must be a character the heading subset carries.

The check reads the generated ``SERIF_CODEPOINTS`` constant (built from the shipped woff2 by
``ops/fonts/build_lm_demi.py``), so the runtime needs no font library. A missing glyph is a
build failure, not a silent fallback to another face.
"""

from __future__ import annotations

from collections.abc import Iterable

from booth_review.build.serif_glyph_set import SERIF_CODEPOINTS
from booth_review.errors import SiteBuildError


def check_serif_text(strings: Iterable[str], *, where: str) -> None:
    """Raise SiteBuildError listing each character the serif subset lacks, sorted by codepoint."""
    missing = {ord(ch) for text in strings for ch in text} - SERIF_CODEPOINTS
    if not missing:
        return
    listed = ", ".join(f"U+{cp:04X} {chr(cp)!r}" for cp in sorted(missing))
    raise SiteBuildError(
        f"serif face lacks {listed} ({where}); add it to the subset or change the name"
    )


def lookup_names(rows: Iterable[object], *fields: str) -> list[str]:
    """The named string fields of each lookup row (pydantic models), for `check_serif_text`."""
    return [str(getattr(row, field)) for row in rows for field in fields]
