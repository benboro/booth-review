"""Dark logo variant generator: UI-SPEC oracle, determinism, lint, contrast (D-09)."""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from test_site_logos import _logo_files, _manifest_rows, lint_svg

from booth_review.build import logos_dark
from booth_review.build.logos_dark import (
    DARK_BACKGROUNDS,
    DARK_GROUND,
    FLIP_PAIR_FILES,
    OFF_WHITE,
    contrast,
    dark_variant,
)
from booth_review.build.site_assembly import assemble_site
from booth_review.errors import SiteBuildError

NS = "http://www.w3.org/2000/svg"

ORACLE = {
    "CC0000": "FA4737",
    "E52534": "FB4046",
    "ED1C24": "FF3C39",
    "D91E25": "FA4642",
    "0049CE": "3E84FF",
    "013CA6": "4A86F6",
    "002E56": "608CBB",
    "183059": "6D89B9",
    "2C4F87": "648AC7",
    "666666": "888888",
    "0082CA": "2190D9",
    "5F53AE": "867DDC",
    "C81A46": "F24A67",
    "0E88D3": "1C8EDA",
    "6E55DC": "8873FD",
    "EF1541": "FF3853",
    "C814C8": "E23CE1",
    "D9005A": "FA3A74",
    "8250FF": "996CFF",
    "6E64FF": "7E78FF",
    "232F3E": "7D8B9D",
}


def _svg(fill: str, root: str = "") -> bytes:
    return (
        f'<svg xmlns="{NS}" viewBox="0 0 10 10"{root}><path fill="{fill}" d="M0 0h10v10z"/></svg>'
    ).encode()


def _path_fill(data: bytes) -> str:
    root = ET.fromstring(data)
    return root.find(f"{{{NS}}}path").attrib["fill"]  # type: ignore[union-attr]


@pytest.mark.parametrize(("light", "dark"), sorted(ORACLE.items()))
def test_oracle_lifts(light: str, dark: str) -> None:
    assert _path_fill(dark_variant(_svg(f"#{light}"))) == f"#{dark}"


@pytest.mark.parametrize("paint", ["#111212", "#000", "#242021", "#07111E", "#231F20", "black"])
def test_neutral_dark_becomes_off_white(paint: str) -> None:
    assert _path_fill(dark_variant(_svg(paint))) == OFF_WHITE


def test_root_without_fill_gains_off_white() -> None:
    out = dark_variant(f'<svg xmlns="{NS}" viewBox="0 0 1 1"><path d="M0 0h1v1z"/></svg>'.encode())
    assert ET.fromstring(out).attrib["fill"] == OFF_WHITE


def test_root_with_fill_is_not_doubled() -> None:
    out = dark_variant(_svg("#FF4500", ' fill="none"'))
    assert ET.fromstring(out).attrib["fill"] == "none"


@pytest.mark.parametrize("paint", ["#F0F0F0", "#FFF"])
def test_flip_pair_letters(paint: str) -> None:
    assert _path_fill(dark_variant(_svg(paint), flip_pair=True)) == DARK_GROUND
    assert _path_fill(dark_variant(_svg(paint), flip_pair=False)) in {paint, paint.upper()}


@pytest.mark.parametrize("paint", ["#00A8E1", "#FF4500", "none"])
def test_unchanged_paints(paint: str) -> None:
    assert _path_fill(dark_variant(_svg(paint))) == paint


def test_style_and_gradient_paints_are_rewritten() -> None:
    src = (
        f'<svg xmlns="{NS}" viewBox="0 0 1 1" fill="none"><defs><style>.a{{fill:#000}}</style>'
        f'<linearGradient id="g"><stop stop-color="#CC0000"/></linearGradient></defs>'
        f'<path style="fill:#111212;stroke:none" d="M0 0"/></svg>'
    ).encode()
    out = dark_variant(src).decode()
    assert "fill:#E5EAE8}" in out
    assert 'stop-color="#F94536"' in out or 'stop-color="#FA4737"' in out
    assert "fill:#E5EAE8;stroke:none" in out


@pytest.mark.parametrize("paint", ["rgb(0,0,0)", "hsl(0,0%,0%)", "red", "navy"])
def test_unknown_colour_syntax_fails(paint: str) -> None:
    with pytest.raises(SiteBuildError, match=r"rgb|hsl|red|navy"):
        dark_variant(_svg(paint))


def test_white_on_lifted_backplate_stays_white() -> None:
    src = (
        f'<svg xmlns="{NS}" viewBox="0 0 1 1" fill="none">'
        f'<path fill="#002e56" d="M0 0"/><path fill="#fff" d="M0 0"/></svg>'
    ).encode()
    out = dark_variant(src).decode()
    assert 'fill="#608CBA"' in out or 'fill="#608CBB"' in out
    assert 'fill="#fff"' in out.lower() or 'fill="#ffffff"' in out.lower()


@pytest.mark.parametrize("path", _logo_files(), ids=lambda p: p.name)
def test_every_source_variant(path) -> None:  # type: ignore[no-untyped-def]
    source = path.read_bytes()
    flip = path.name in FLIP_PAIR_FILES
    first = dark_variant(source, flip_pair=flip)
    assert first == dark_variant(source, flip_pair=flip)
    assert lint_svg(first) == []
    src_root, out_root = ET.fromstring(source), ET.fromstring(first)
    for key in ("viewBox", "width", "height"):
        assert src_root.attrib.get(key) == out_root.attrib.get(key)
    for paint in logos_dark._paints(first.decode()):
        if flip and paint == DARK_GROUND:
            continue
        low = min(contrast(paint, bg) for bg in DARK_BACKGROUNDS)
        assert low >= 3.0, f"{path.name}: {paint} only {low:.2f}:1"


def test_manifest_dark_sha256() -> None:
    rows = _manifest_rows()
    assert rows
    for row in rows:
        path = next(p for p in _logo_files() if p.name == row["file"])
        expected = hashlib.sha256(
            dark_variant(path.read_bytes(), flip_pair=path.name in FLIP_PAIR_FILES)
        ).hexdigest()
        assert row["dark_sha256"] == expected, row["file"]


def test_build_writes_a_dark_variant_for_every_logo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # never read a real .env
    monkeypatch.delenv("CFBD_API_KEY", raising=False)
    root = Path(__file__).resolve().parents[1]
    out = tmp_path / "site"
    result = assemble_site(
        source=root / "tests" / "fixtures" / "contract" / "site-data.fixture.json",
        out_dir=out,
        site_src=root / "site",
        docs=root / "docs",
    )
    for logo in _logo_files():
        built = out / "logos" / "dark" / logo.name
        expected = dark_variant(logo.read_bytes(), flip_pair=logo.name in FLIP_PAIR_FILES)
        assert built.read_bytes() == expected
        assert f"logos/dark/{logo.name}" in result.files


@pytest.mark.parametrize(
    "path_attrs",
    [
        'fill = "#000"',
        'fill ="#000"',
        "fill= '#000'",
        'stroke = "#111212"',
        'stop-color = "#000"',
    ],
)
def test_spaced_paint_attribute_fails(path_attrs: str) -> None:
    # Review 6f: the strict regexes miss a spaced `=`, so the paint would ship unrecoloured;
    # a loose scan's count must match theirs, in the generator and in the lint below alike.
    src = f'<svg xmlns="{NS}" viewBox="0 0 1 1"><path {path_attrs} d="M0 0"/></svg>'
    with pytest.raises(SiteBuildError, match="paint properties"):
        dark_variant(src.encode())
    with pytest.raises(SiteBuildError, match="paint properties"):
        logos_dark._paints(src)


@pytest.mark.parametrize(
    "src",
    [
        f'<svg xmlns="{NS}" viewBox="0 0 1 1"><path fill="currentColor" d="M0 0"/></svg>',
        f'<svg xmlns="{NS}" viewBox="0 0 1 1"><path style="stroke:currentcolor" d="M0 0"/></svg>',
    ],
)
def test_current_color_fails(src: str) -> None:
    with pytest.raises(SiteBuildError, match="currentColor"):
        dark_variant(src.encode())


def test_paint_lookalikes_do_not_trip_the_loose_scan() -> None:
    src = (
        f'<svg xmlns="{NS}" viewBox="0 0 1 1" fill="none"><path fill-rule="evenodd"'
        f' stroke-width="2" fill-opacity=".5" fill="#CC0000" style="stroke-linejoin:round"'
        f' d="M0 0"/></svg>'
    )
    assert logos_dark._paints(src) == ["#CC0000"]
