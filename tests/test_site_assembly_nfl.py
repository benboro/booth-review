"""NFL flag handling in site assembly (D-18, D-19, D-20, D-25).

Pins the CFB outputs by digest: site-data.json and coverage.html must be
byte-identical flag-off and flag-on, and the flag-off index.html must equal
the pre-phase file once the one added sports meta line is removed.
Synthetic fixtures only; the key is an invented canary.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from booth_review.build import site_assembly as sa
from booth_review.build.site_assembly import (
    BUILD_MARKER,
    assemble_site,
    check_nfl_file_key,
    load_nfl_site_payload,
    nfl_site_enabled,
    refresh_nfl_data,
)
from booth_review.deploy.publish import _site_files
from booth_review.errors import KeyLeakError, SiteBuildError

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_SRC = REPO_ROOT / "site"
DOCS = REPO_ROOT / "docs"
CFB_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "contract" / "site-data.fixture.json"
NFL_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "contract" / "nfl-data.fixture.json"

# Recorded from a fixture build at the commit before this plan.
_SITE_DATA_SHA256 = "09db84ed5ec02ec95e1a7b2a9601afab26bb7bf0622bc8ae25a42527b90467ea"
_COVERAGE_SHA256 = "77f5c7b375e0280082f601e3838fb4dc0f1ff8c309b73e390674ea1ffbe009db"
_INDEX_PRE_PHASE_SHA256 = "2d63d59bca8e587cdad13488386eefcf3bb470c96d5f49280fabea70e8862ae2"

_CANARY = "invented-nfl-canary-key-0001"
_META_OFF = '<meta name="booth-review-sports" content="cfb">'


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # never read a real .env
    monkeypatch.delenv("CFBD_API_KEY", raising=False)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build(out: Path, **kw: object) -> sa.SiteBuildResult:
    return assemble_site(source=CFB_FIXTURE, out_dir=out, site_src=SITE_SRC, docs=DOCS, **kw)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("true", True), ("True", False), ("TRUE", False), ("1", False), ("yes", False), ("", False)],
)
def test_flag_is_an_exact_compare(value: str, expected: bool) -> None:
    assert nfl_site_enabled({"NFL_SITE_ENABLED": value}) is expected
    assert nfl_site_enabled({}) is False


def test_flag_off_build(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = _build(out)
    index = (out / "index.html").read_text(encoding="utf-8")
    assert index.count(_META_OFF) == 1
    assert "sport-switch" not in index
    assert "booth-review:sports-meta" not in index
    stripped = index.replace(_META_OFF + "\n", "")
    assert hashlib.sha256(stripped.encode()).hexdigest() == _INDEX_PRE_PHASE_SHA256
    assert not (out / "sports" / "nfl").exists()
    assert not (out / "nfl-data.json").exists()
    assert _sha(out / "site-data.json") == _SITE_DATA_SHA256
    assert _sha(out / "coverage.html") == _COVERAGE_SHA256
    assert "NFL:" not in (out / "methodology.html").read_text(encoding="utf-8")
    assert result.nfl_games is None


def test_flag_on_build(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = _build(out, nfl=True, nfl_source=NFL_FIXTURE)
    index = (out / "index.html").read_text(encoding="utf-8")
    assert '<meta name="booth-review-sports" content="cfb,nfl">' in index
    topbar = index.split('<header id="topbar">')[1].split("</header>")[0]
    assert 'id="sport-switch"' in topbar
    cfb = topbar.index('data-sport="cfb" aria-pressed="true"')
    assert cfb < topbar.index('data-sport="nfl" aria-pressed="false"')
    nfl, body = load_nfl_site_payload(NFL_FIXTURE)
    assert (out / "nfl-data.json").read_bytes() == body
    assert _sha(out / "site-data.json") == _SITE_DATA_SHA256
    assert _sha(out / "coverage.html") == _COVERAGE_SHA256
    assert 'id="nfl-special-games"' in (out / "methodology.html").read_text(encoding="utf-8")
    assert result.nfl_games == len(nfl.games.season)
    assert "nfl-data.json" in result.files


def test_flag_on_without_source(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = _build(out, nfl=True)
    assert 'id="sport-switch"' in (out / "index.html").read_text(encoding="utf-8")
    assert not (out / "nfl-data.json").exists()
    assert result.nfl_games is None


def test_source_while_off_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SiteBuildError, match="NFL is off"):
        _build(tmp_path / "out", nfl_source=NFL_FIXTURE)


def test_invalid_nfl_source_leaves_out_dir(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _build(out)
    before = {p.name: _sha(p) for p in out.iterdir() if p.is_file()}
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema_version": "9"}', encoding="utf-8")
    with pytest.raises(SiteBuildError):
        _build(out, nfl=True, nfl_source=bad)
    assert {p.name: _sha(p) for p in out.iterdir() if p.is_file()} == before


def _planted(tmp_path: Path) -> Path:
    raw = json.loads(NFL_FIXTURE.read_text(encoding="utf-8"))
    raw["lookups"]["people"][0]["name"] += " " + _CANARY
    path = tmp_path / "planted.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_planted_key_fails_build_and_keeps_out_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    _build(out)
    before = {p.name: _sha(p) for p in out.iterdir() if p.is_file()}
    monkeypatch.setenv("CFBD_API_KEY", _CANARY)
    with pytest.raises(KeyLeakError):
        _build(tmp_path / "out2", nfl=True, nfl_source=_planted(tmp_path))
    assert not (tmp_path / "out2").exists()
    assert {p.name: _sha(p) for p in out.iterdir() if p.is_file()} == before


@pytest.mark.parametrize("token", [sa.SPORTS_META_TOKEN, sa.SPORT_SWITCH_TOKEN])
@pytest.mark.parametrize("mode", ["missing", "duplicated"])
def test_token_must_appear_once(tmp_path: Path, token: str, mode: str) -> None:
    src = tmp_path / "src"
    import shutil

    shutil.copytree(SITE_SRC, src)
    text = (src / "index.html").read_text(encoding="utf-8")
    text = text.replace(token, "" if mode == "missing" else token + token)
    (src / "index.html").write_text(text, encoding="utf-8")
    with pytest.raises(SiteBuildError, match="booth-review:sport"):
        assemble_site(source=CFB_FIXTURE, out_dir=tmp_path / "o", site_src=src, docs=DOCS)


def _site_with_nfl(tmp_path: Path) -> Path:
    out = tmp_path / "site"
    _build(out, nfl=True, nfl_source=NFL_FIXTURE)
    return out


def _new_source(tmp_path: Path) -> Path:
    raw = json.loads(NFL_FIXTURE.read_text(encoding="utf-8"))
    raw["lookups"]["people"][0]["name"] = "Renamed Person"
    path = tmp_path / "new.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_refresh_replaces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = _site_with_nfl(tmp_path)
    monkeypatch.setenv("CFBD_API_KEY", _CANARY)
    new = _new_source(tmp_path)
    result = refresh_nfl_data(site_out=out, source=new)
    assert result.replaced and result.key_checked
    assert (out / "nfl-data.json").read_bytes() == load_nfl_site_payload(new)[1]


def test_refresh_failures_keep_previous(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = _site_with_nfl(tmp_path)
    previous = (out / "nfl-data.json").read_bytes()
    monkeypatch.setenv("CFBD_API_KEY", _CANARY)
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(SiteBuildError):
        refresh_nfl_data(site_out=out, source=bad)
    with pytest.raises(KeyLeakError):
        refresh_nfl_data(site_out=out, source=_planted(tmp_path))
    assert (out / "nfl-data.json").read_bytes() == previous
    assert not list(tmp_path.glob(".*nfl-refresh-*"))


def test_refresh_without_key_does_not_replace(tmp_path: Path) -> None:
    out = _site_with_nfl(tmp_path)
    previous = (out / "nfl-data.json").read_bytes()
    result = refresh_nfl_data(site_out=out, source=_new_source(tmp_path))
    assert not result.replaced
    assert not result.key_checked
    assert (out / "nfl-data.json").read_bytes() == previous


def test_refresh_refuses_unmarked_dir(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    with pytest.raises(SiteBuildError):
        refresh_nfl_data(site_out=tmp_path / "plain", source=NFL_FIXTURE)
    assert not (tmp_path / "plain" / BUILD_MARKER).exists()


def test_refresh_kill_leaves_site_dir_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _site_with_nfl(tmp_path)
    monkeypatch.setenv("CFBD_API_KEY", _CANARY)
    before = _site_files(out)

    def boom(self: Path, target: object) -> Path:
        raise OSError("simulated kill")

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(OSError, match="simulated"):
        refresh_nfl_data(site_out=out, source=_new_source(tmp_path))
    monkeypatch.undo()
    assert _site_files(out) == before
    assert not list(tmp_path.glob(".*nfl-refresh-*"))
    assert not list(tmp_path.glob(".*nfl-keycheck-*"))


def test_check_nfl_file_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert check_nfl_file_key(b"{}", scratch_parent=tmp_path) is False
    monkeypatch.setenv("CFBD_API_KEY", _CANARY)
    assert check_nfl_file_key(b"{}", scratch_parent=tmp_path) is True
    with pytest.raises(KeyLeakError):
        check_nfl_file_key(_CANARY.encode(), scratch_parent=tmp_path)
    assert not list(tmp_path.glob(".nfl-keycheck-*"))
