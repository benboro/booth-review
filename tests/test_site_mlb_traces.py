"""16-01: MLB site code stays inside the vendored Plotly bundle's trace types (MLB-03).

The partial bundle ships scatter, scattergl and bar only (12-DECISIONS). A `type:` literal
that is neither one of those nor a known non-trace literal fails the test. MLB-03 (extend the
bundle) is therefore not triggered while this passes.
"""

from __future__ import annotations

import re
from pathlib import Path

SITE_MLB = Path(__file__).resolve().parents[1] / "site" / "sports" / "mlb"
TRACE_TYPES = {"scatter", "scattergl", "bar"}
NON_TRACE = {"line", "rect", "linear", "log", "date", "category"}
TYPE_LITERAL = re.compile(r"""\btype:\s*['"](\w+)['"]""")
NFL_IMPORT = re.compile(r"""from\s+['"][./]*(?:sports/)?nfl/|['"]\.\./nfl/""")


def _unknown_types(source: str) -> list[str]:
    return [t for t in TYPE_LITERAL.findall(source) if t not in TRACE_TYPES | NON_TRACE]


def _mlb_files() -> list[Path]:
    files = sorted(SITE_MLB.rglob("*.js"))
    assert files, "no MLB site files found"
    return files


def test_mlb_trace_types_are_in_the_vendored_bundle() -> None:
    # The guard must not pass vacuously: a heatmap literal is rejected by the same classifier.
    assert _unknown_types("{ type: 'heatmap', mode: 'markers' }") == ["heatmap"]
    assert _unknown_types('{ type: "scattergl" }') == []
    bad = {f.name: _unknown_types(f.read_text(encoding="utf-8")) for f in _mlb_files()}
    bad = {name: types for name, types in bad.items() if types}
    assert not bad, f"MLB files use trace types outside the bundle: {bad}"


def test_mlb_never_imports_nfl_modules() -> None:
    assert NFL_IMPORT.search("import x from '../../nfl/data.js'")
    offenders = [f.name for f in _mlb_files() if NFL_IMPORT.search(f.read_text(encoding="utf-8"))]
    assert not offenders, f"MLB files import NFL modules: {offenders}"
