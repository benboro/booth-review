"""The font recipe writes exactly the committed, ruff-formatted codepoint module."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from booth_review.build.serif_glyph_set import SERIF_CODEPOINTS

REPO_ROOT = Path(__file__).resolve().parents[1]
RECIPE = REPO_ROOT / "ops" / "fonts" / "build_lm_demi.py"
COMMITTED = REPO_ROOT / "src" / "booth_review" / "build" / "serif_glyph_set.py"


def test_recipe_output_equals_the_committed_file() -> None:
    spec = importlib.util.spec_from_file_location("build_lm_demi", RECIPE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text = module._codepoints_module(sorted(SERIF_CODEPOINTS))
    assert text == COMMITTED.read_text(encoding="utf-8")
