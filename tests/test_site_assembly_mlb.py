"""MLB flag handling and the sport registry in site assembly (D-01, D-16).

Flag-off output must equal the CFB / CFB+NFL builds of before; the NFL tests pin
those by digest, and this file compares trees so a registry change cannot move a
byte. Synthetic fixtures only; the key is an invented canary.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from booth_review.build import pages
from booth_review.build import site_assembly as sa
from booth_review.build.site_assembly import (
    add_sport_to_site,
    assemble_site,
    load_mlb_site_payload,
    load_nfl_site_payload,
    mlb_site_enabled,
    refresh_sport_data,
    site_sports,
)
from booth_review.errors import KeyLeakError, SiteBuildError

REPO_ROOT = Path(__file__).resolve().parents[1]
CFB_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "contract" / "site-data.fixture.json"
NFL_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "contract" / "nfl-data.fixture.json"
MLB_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "contract" / "mlb-data.fixture.json"

_CANARY = "invented-mlb-canary-key-0001"


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # never read a real .env
    monkeypatch.delenv("CFBD_API_KEY", raising=False)


@pytest.fixture
def src(tmp_path: Path) -> Path:
    """A copy of site/ with a placeholder MLB module dir, plus docs with MLB blocks."""
    dest = tmp_path / "_src"
    shutil.copytree(REPO_ROOT / "site", dest, ignore=shutil.ignore_patterns("node_modules"))
    (dest / "sports" / "mlb").mkdir(exist_ok=True)
    (dest / "sports" / "mlb" / "index.js").write_text("// synthetic placeholder\n", "utf-8")
    return dest


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    dest = tmp_path / "_docs"
    shutil.copytree(REPO_ROOT / "docs", dest)
    with (dest / "methodology.md").open("a", encoding="utf-8") as fh:
        fh.write("\n<!-- mlb:start -->\n\n## MLB: Synthetic section\n\n<!-- mlb:end -->\n")
    return dest


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build(out: Path, src: Path, docs: Path, **kw: object) -> sa.SiteBuildResult:
    return assemble_site(source=CFB_FIXTURE, out_dir=out, site_src=src, docs=docs, **kw)  # type: ignore[arg-type]


def _nfl() -> dict[str, object]:
    return {"nfl": True, "nfl_payload": load_nfl_site_payload(NFL_FIXTURE)}


def _mlb() -> dict[str, object]:
    return {"mlb": True, "mlb_payload": load_mlb_site_payload(MLB_FIXTURE)}


@pytest.mark.parametrize(
    ("value", "expected"),
    [("true", True), ("True", False), ("1", False), ("", False)],
)
def test_mlb_flag_is_an_exact_compare(value: str, expected: bool) -> None:
    assert mlb_site_enabled({"MLB_SITE_ENABLED": value}) is expected
    assert mlb_site_enabled({}) is False


def test_registry_order_and_switch_tuple() -> None:
    assert [s.id for s in sa.SPORT_SPECS] == ["cfb", "nfl", "mlb"]
    assert sa.SITE_SPORTS == (("cfb", "CFB"), ("nfl", "NFL"), ("mlb", "MLB"))


@pytest.mark.parametrize("with_nfl", [False, True])
def test_mlb_off_builds_are_unchanged_and_hold_no_mlb(
    tmp_path: Path, src: Path, docs: Path, with_nfl: bool
) -> None:
    kw = _nfl() if with_nfl else {}
    plain = tmp_path / "plain"
    off = tmp_path / "off"
    _build(plain, REPO_ROOT / "site", REPO_ROOT / "docs", **kw)
    result = _build(off, src, docs, mlb=False, mlb_payload=None, **kw)
    # Only methodology.html differs: this test's docs copy carries an MLB block.
    assert {k: v for k, v in _tree(plain).items() if k != "methodology.html"} == {
        k: v for k, v in _tree(off).items() if k != "methodology.html"
    }
    assert not (off / "sports" / "mlb").exists()
    assert not (off / "mlb-data.json").exists()
    assert "Synthetic section" not in (off / "methodology.html").read_text("utf-8")
    assert result.mlb_games is None
    assert site_sports(off) == (("cfb", "nfl") if with_nfl else ("cfb",))


def test_mlb_on_build(tmp_path: Path, src: Path, docs: Path) -> None:
    out = tmp_path / "out"
    model, body = load_mlb_site_payload(MLB_FIXTURE)
    result = _build(out, src, docs, **_nfl(), **_mlb())
    index = (out / "index.html").read_text("utf-8")
    assert '<meta name="booth-review-sports" content="cfb,nfl,mlb">' in index
    topbar = index.split('<header id="topbar">')[1].split("</header>")[0]
    assert topbar.index('data-sport="cfb"') < topbar.index('data-sport="nfl"')
    assert topbar.index('data-sport="nfl"') < topbar.index('data-sport="mlb"')
    assert (out / "mlb-data.json").read_bytes() == body
    assert (out / "sports" / "mlb" / "index.js").is_file()
    assert "Synthetic section" in (out / "methodology.html").read_text("utf-8")
    assert result.mlb_games == len(model.games.season)
    assert "mlb-data.json" in result.files
    assert site_sports(out) == ("cfb", "nfl", "mlb")


def test_mlb_alone_lists_cfb_then_mlb(tmp_path: Path, src: Path, docs: Path) -> None:
    out = tmp_path / "out"
    _build(out, src, docs, **_mlb())
    assert site_sports(out) == ("cfb", "mlb")
    assert not (out / "sports" / "nfl").exists()
    assert not (out / "nfl-data.json").exists()


def test_mlb_payload_flag_pairing_is_enforced(tmp_path: Path, src: Path, docs: Path) -> None:
    with pytest.raises(SiteBuildError, match="MLB is off"):
        _build(tmp_path / "a", src, docs, mlb_payload=load_mlb_site_payload(MLB_FIXTURE))
    with pytest.raises(SiteBuildError, match="no MLB data file"):
        _build(tmp_path / "b", src, docs, mlb=True)


def test_invalid_mlb_source_is_count_only(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema_version": "9", "secret": "do-not-echo"}', "utf-8")
    with pytest.raises(SiteBuildError) as caught:
        load_mlb_site_payload(bad)
    assert "do-not-echo" not in str(caught.value)


def test_planted_key_in_mlb_file_fails_and_keeps_out_dir(
    tmp_path: Path, src: Path, docs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    _build(out, src, docs)
    before = _tree(out)
    monkeypatch.setenv("CFBD_API_KEY", _CANARY)
    model, body = load_mlb_site_payload(MLB_FIXTURE)
    planted = (model, body + _CANARY.encode())
    with pytest.raises(KeyLeakError):
        _build(out, src, docs, mlb=True, mlb_payload=planted)  # type: ignore[arg-type]
    assert _tree(out) == before


def test_add_sport_keeps_nfl(
    tmp_path: Path, src: Path, docs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CFBD_API_KEY", _CANARY)
    out = tmp_path / "out"
    _build(out, src, docs, **_nfl())
    before = _tree(out)
    result = add_sport_to_site(
        "mlb",
        site_out=out,
        site_src=src,
        docs=docs,
        payload=load_mlb_site_payload(MLB_FIXTURE),
    )
    assert result.replaced
    after = _tree(out)
    nfl_paths = [k for k in before if k.startswith("sports/nfl/") or k == "nfl-data.json"]
    assert nfl_paths
    assert all(after[k] == before[k] for k in nfl_paths)
    assert site_sports(out) == ("cfb", "nfl", "mlb")
    direct = tmp_path / "direct"
    _build(direct, src, docs, **_nfl(), **_mlb())
    assert _tree(direct) == after


def test_add_sport_from_cfb_only_and_refusals(
    tmp_path: Path, src: Path, docs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CFBD_API_KEY", _CANARY)
    out = tmp_path / "out"
    _build(out, src, docs)
    payload = load_mlb_site_payload(MLB_FIXTURE)
    add_sport_to_site("mlb", site_out=out, site_src=src, docs=docs, payload=payload)
    assert site_sports(out) == ("cfb", "mlb")
    with pytest.raises(SiteBuildError, match="can take it"):
        add_sport_to_site("mlb", site_out=out, site_src=src, docs=docs, payload=payload)
    with pytest.raises(SiteBuildError, match="unknown sport"):
        add_sport_to_site("cfb", site_out=out, site_src=src, docs=docs, payload=payload)
    (tmp_path / "plain").mkdir()
    with pytest.raises(SiteBuildError, match="not a booth-review site build"):
        add_sport_to_site(
            "mlb", site_out=tmp_path / "plain", site_src=src, docs=docs, payload=payload
        )


def test_refresh_sport_data_replaces_the_mlb_file(
    tmp_path: Path, src: Path, docs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CFBD_API_KEY", _CANARY)
    out = tmp_path / "out"
    _build(out, src, docs, **_mlb())
    result = refresh_sport_data("mlb", site_out=out, source=MLB_FIXTURE)
    assert result.replaced
    assert (out / "mlb-data.json").read_bytes() == load_mlb_site_payload(MLB_FIXTURE)[1]


def test_check_sport_file_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    body = load_mlb_site_payload(MLB_FIXTURE)[1]
    assert sa.check_sport_file_key("mlb", body, scratch_parent=tmp_path / "s") is False
    monkeypatch.setenv("CFBD_API_KEY", _CANARY)
    assert sa.check_sport_file_key("mlb", body, scratch_parent=tmp_path / "s") is True
    with pytest.raises(KeyLeakError):
        sa.check_sport_file_key("mlb", body + _CANARY.encode(), scratch_parent=tmp_path / "s")
    assert not [p for p in (tmp_path / "s").iterdir()]


# -- page markers --------------------------------------------------------------------------


def test_mlb_blocks_kept_or_dropped() -> None:
    text = "a\n<!-- mlb:start -->\nb\n<!-- mlb:end -->\nc\n"
    assert pages._apply_all_sport_blocks(text, nfl=False, mlb=True) == "a\nb\nc\n"
    assert pages._apply_all_sport_blocks(text, nfl=False, mlb=False) == "a\nc\n"
    assert pages._apply_all_sport_blocks(text, nfl=True, mlb=False) == "a\nc\n"


@pytest.mark.parametrize(
    "text",
    [
        "<!-- mlb:start -->\nx\n",
        "x\n<!-- mlb:end -->\n",
        "<!-- mlb:start -->\n<!-- mlb:start -->\n<!-- mlb:end -->\n<!-- mlb:end -->\n",
    ],
)
@pytest.mark.parametrize("enabled", [True, False])
def test_unbalanced_or_nested_mlb_markers_fail_closed(text: str, enabled: bool) -> None:
    with pytest.raises(SiteBuildError, match="MLB marker"):
        pages._apply_all_sport_blocks(text, nfl=False, mlb=enabled)


def test_nfl_wrapper_still_works() -> None:
    text = "a\n<!-- nfl:start -->\nb\n<!-- nfl:end -->\n"
    assert pages._apply_nfl_blocks(text, nfl=False) == "a\n"
    with pytest.raises(SiteBuildError, match="NFL marker"):
        pages._apply_nfl_blocks("<!-- nfl:start -->\n", nfl=True)
