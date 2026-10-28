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
    add_nfl_to_site,
    assemble_site,
    check_nfl_file_key,
    load_nfl_site_payload,
    nfl_site_enabled,
    refresh_nfl_data,
    site_sports,
)
from booth_review.deploy.publish import _site_files
from booth_review.errors import KeyLeakError, SiteBuildError

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_SRC = REPO_ROOT / "site"
DOCS = REPO_ROOT / "docs"
CFB_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "contract" / "site-data.fixture.json"
NFL_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "contract" / "nfl-data.fixture.json"

# Recorded from a fixture build at the commit before this plan; site-data and index digests
# re-pinned at 04.19 Plan 08 (contract 2.4.0: figure_source column and one SMW fixture row);
# index digest re-pinned at Plan 09 (band-note bullet reworded, D-21); site-data and index
# digests re-pinned at Plan 41 (contract 2.5.0: coverage matched_crew_backup 0 on every
# fixture row; the index moves only through its site-data cache-bust hash). All three
# re-pinned at Plan 49: fixture telecast 8 became an ESPN Press Room backup crew with
# matched_crew_backup 1 on its 2026 coverage rows (reverting those gives the Plan 41 site-data
# digest), coverage.html gained the "Of which ESPN Press Room backup" column (dropping it from
# the reverted build gives the Plan 41 digest), and the index moves only through its
# site-data cache-bust hash. Coverage re-pinned at Plan 43 (user decision): the column header
# shortened to "Of which ESPN backup" (restoring the old header text gives the Plan 49 digest).
# Site-data and index re-pinned at Phase 10 Plan 03 (contract 2.6.0: lookups.booths [] and a null
# booth column in both blocks; dropping them and setting the version back to 2.5.0 gives the
# old site-data digest, and the index moves only through its cache-bust hash).
# Index re-pinned at Phase 10 Plan 11: plans 10-06..10-09 added only markup (Booth trigger and
# popover, Crews tab and panel, Lead booth key; 21 added lines, none removed), then re-pinned
# once more for the 10-11 review: the Booth helper now ends "faded or hidden." (one reworded line).
# Index re-pinned at Phase 11 Plan 09: only added markup (Network colors toggle, later removed;
# map key overlay; 8 added lines, none removed).
# Index re-pinned at Phase 11 Plan 10: only the Matched games heading row, venue status and
# no-match line (4 added lines, 1 removed).
# Re-pinned at Phase 18 Plan 01: CFB contract 2.7.0 adds telecasts_scheduled, lookups.weeks,
# freshness.weekend.
# Re-pinned at Phase 18 Plan 13 (F1): the fixture gains the per-game week label column.
# Re-pinned at Phase 18 Plan 13 (F7): telecasts_scheduled gains empty crew columns.
_SITE_DATA_SHA256 = "cec8bf26b5e0f5b1aaa165cfe335d80582e308af4ceea75a3657ab4aad479b51"
# Re-pinned at Phase 13 Plan 01: footer RT-23/RT-24 lines, data-theme and color-scheme,
# new header with theme slot, site name.
# Re-pinned at Phase 17 Plan 06: inline hash-pinned theme-init.js script, sha256 CSP and
# #theme-slot toggle in the header.
# Re-pinned at Phase 17 review: theme-init.js re-applies the stored theme on a back/forward
# cache restore (pageshow), which changes the inlined script and its CSP hash.
# Re-pinned at Phase 26 Plan 12: the type credit names Latin Modern (footer line).
# Re-pinned at Phase 26 Plan 05: footer credit blocks, spaced nav, semicolon freshness, title.
# Re-pinned at Phase 26 Plan 10 (sign-off): the freshness line binds "Week" to its number and the
# last two words with no-break spaces.
_COVERAGE_SHA256 = "c0475d22f70cef579abe5008fa44e1f4996e12313a291e250ffbecc95dd720e6"
# Re-pinned at Phase 13 Plan 01: footer RT-23/RT-24 lines, data-theme and color-scheme,
# new header with theme slot, site name.
# Re-pinned at Phase 13 Plan 05: Plotly partial bundle src and SRI.
# Re-pinned at Phase 13 Plan 06: font preloads and load-error copy.
# Re-pinned at Phase 13 Plan 10: Clear all filters moved into the always-rendered
# selection row; Show games label.
# Re-pinned at Phase 13 Plan 11: module headers, tab hint moved into the module subtitle,
# compare note in the summary, Reset zoom slot.
# Re-pinned after the Phase 13 checkpoint: the Viewers head carries class="num" so it aligns
# right like its cells (1 changed line).
# Re-pinned after the Phase 13 panel review: #theme-slot drops aria-hidden (1 changed line).
# Re-pinned for the toolbar measuring script's preload in <head> (1 added line).
# Re-pinned at Phase 14 Plan 09: #pick-status and #matched-subtitle seats (crew pick).
# Re-pinned at Phase 17 Plan 06: theme-init.js head script and #theme-toggle button markup.
# Re-pinned at Phase 17.1 Plan 03: Network colors switch markup removed from #legend-row.
# Re-pinned at Phase 18 Plan 01: CFB contract 2.7.0 moves the index only through its site-data
# cache-bust hash.
# Re-pinned at Phase 18 Plan 10: This weekend tab button and #weekend-panel section (2 added lines).
# Re-pinned 2026-10-26 (18-13 F2): the two #table-empty paragraphs merged into one, requested and
# approved by the user at plan 12 sign-off ("Fix both items").
# Re-pinned at Phase 18 Plan 13 (F1): the week label column moves the index only through its
# site-data cache-bust hash. Re-pinned again for F7's scheduled crew columns, the same way.
# Re-pinned at Phase 26 Plan 12: Latin Modern preload replaces the old serif (1 changed line).
# Re-pinned at Phase 26 Plan 05: the page title takes a colon (1 changed line).
# Re-pinned at Phase 26 Plan 06: the ten CFB filter triggers move into three .fgroup wrappers.
# Re-pinned at Phase 26 Plan 07: the selection row goes, #summary gains .sum-left and .sum-right,
# and the phone changed-filter chips move into the Filters sheet.
# Re-pinned at Phase 26 Plan 08: the retired toolbar measuring script's preload and script tag
# removed (2 removed lines).
# Re-pinned at Phase 26 Plan 10 (sign-off): the footer freshness line takes no-break spaces.
_INDEX_PRE_PHASE_SHA256 = "11b5b64019f60fbdbb336b771c400e243a2dbaac8098c1445cc574f7dc9be767"

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


def test_theme_init_ships_and_sport_csp_unchanged(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = _build(out)
    assert "theme-init.js" in result.files

    def csp(text: str) -> str:
        line = next(ln for ln in text.splitlines() if "Content-Security-Policy" in ln)
        return line.strip()

    built = (out / "index.html").read_text(encoding="utf-8")
    source = (SITE_SRC / "index.html").read_text(encoding="utf-8")
    assert csp(built) == csp(source)


def test_flag_on_build(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = _build(out, nfl=True, nfl_payload=load_nfl_site_payload(NFL_FIXTURE))
    index = (out / "index.html").read_text(encoding="utf-8")
    assert '<meta name="booth-review-sports" content="cfb,nfl">' in index
    topbar = index.split('<header id="topbar" class="site-header">')[1].split("</header>")[0]
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


def test_flag_on_without_source_is_refused_and_keeps_out_dir(tmp_path: Path) -> None:
    # WR-01 / D-18: the NFL switch never ships without its data file.
    out = tmp_path / "out"
    _build(out)
    before = {p.name: _sha(p) for p in out.iterdir() if p.is_file()}
    with pytest.raises(SiteBuildError, match="no NFL data file"):
        _build(out, nfl=True)
    assert {p.name: _sha(p) for p in out.iterdir() if p.is_file()} == before
    assert "sport-switch" not in (out / "index.html").read_text(encoding="utf-8")


def test_source_while_off_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SiteBuildError, match="NFL is off"):
        _build(tmp_path / "out", nfl_payload=load_nfl_site_payload(NFL_FIXTURE))


def test_invalid_nfl_source_leaves_out_dir(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _build(out)
    before = {p.name: _sha(p) for p in out.iterdir() if p.is_file()}
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema_version": "9"}', encoding="utf-8")
    with pytest.raises(SiteBuildError):
        _build(out, nfl=True, nfl_payload=load_nfl_site_payload(bad))
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
        _build(tmp_path / "out2", nfl=True, nfl_payload=load_nfl_site_payload(_planted(tmp_path)))
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
    _build(out, nfl=True, nfl_payload=load_nfl_site_payload(NFL_FIXTURE))
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


# -- iter-2 WR-02: turning the switch on in a switch-less build ------------------------------


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _add(out: Path, source: Path = NFL_FIXTURE) -> sa.NflRefreshResult:
    return add_nfl_to_site(
        site_out=out, site_src=SITE_SRC, docs=DOCS, nfl_payload=load_nfl_site_payload(source)
    )


def _no_leftovers(tmp_path: Path) -> None:
    assert not [p.name for p in tmp_path.iterdir() if p.name.startswith(".")]


def test_site_sports_reads_the_built_meta(tmp_path: Path) -> None:
    off = tmp_path / "off"
    _build(off)
    assert site_sports(off) == ("cfb",)
    assert site_sports(_site_with_nfl(tmp_path)) == ("cfb", "nfl")
    assert site_sports(tmp_path / "missing") == ()
    (tmp_path / "plain").mkdir()
    (tmp_path / "plain" / "index.html").write_text("<html>", encoding="utf-8")
    assert site_sports(tmp_path / "plain") == ()


def test_add_nfl_equals_a_flag_on_build_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CFBD_API_KEY", _CANARY)
    out = tmp_path / "out"
    _build(out)
    nfl, _ = load_nfl_site_payload(NFL_FIXTURE)
    result = _add(out)
    assert (result.replaced, result.key_checked, result.games) == (
        True,
        True,
        len(nfl.games.season),
    )
    direct = tmp_path / "direct"
    _build(direct, nfl=True, nfl_payload=load_nfl_site_payload(NFL_FIXTURE))
    assert _tree(out) == _tree(direct)
    assert _sha(out / "site-data.json") == _SITE_DATA_SHA256
    assert _sha(out / "coverage.html") == _COVERAGE_SHA256
    assert site_sports(out) == ("cfb", "nfl")
    _no_leftovers(tmp_path)


def test_add_nfl_refuses_a_build_that_already_has_it_or_is_not_a_build(tmp_path: Path) -> None:
    with pytest.raises(SiteBuildError, match="not a build that can take it"):
        _add(_site_with_nfl(tmp_path))
    (tmp_path / "plain").mkdir()
    with pytest.raises(SiteBuildError, match="not a booth-review site build"):
        _add(tmp_path / "plain")
    assert not (tmp_path / "plain" / BUILD_MARKER).exists()


def test_add_nfl_failures_leave_the_cfb_site_exactly_as_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    _build(out)
    before = _tree(out)
    # No key configured: nothing is changed.
    result = _add(out)
    assert (result.replaced, result.key_checked) == (False, False)
    assert _tree(out) == before
    # A key hit anywhere in the NFL build: nothing is changed, nothing printed.
    monkeypatch.setenv("CFBD_API_KEY", _CANARY)
    with pytest.raises(KeyLeakError):
        _add(out, _planted(tmp_path))
    assert _tree(out) == before
    _no_leftovers(tmp_path)


def test_a_failed_move_puts_every_file_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    _build(out)
    before = _tree(out)
    monkeypatch.setenv("CFBD_API_KEY", _CANARY)
    real_replace = Path.replace
    moved: list[str] = []

    def fail_on_index(self: Path, target: Path) -> Path:  # type: ignore[override]
        if Path(target).name == "index.html" and Path(target).parent == out:
            raise OSError("simulated failure")
        moved.append(Path(target).name)
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_on_index)
    with pytest.raises(OSError, match="simulated"):
        _add(out)
    monkeypatch.undo()
    # The modules, the data file and the methodology page had moved in first.
    assert {"nfl-data.json", "methodology.html"} <= set(moved)
    assert _tree(out) == before
    assert not (out / "sports" / "nfl").exists()
    _no_leftovers(tmp_path)


def test_a_kill_before_the_last_move_still_leaves_a_whole_cfb_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A kill skips the rollback; index.html moves last, so the page still
    # lists CFB only and every CFB data file is as built.
    out = tmp_path / "out"
    _build(out)
    before = _tree(out)
    monkeypatch.setenv("CFBD_API_KEY", _CANARY)
    real_replace = Path.replace

    def kill_on_index(self: Path, target: Path) -> Path:  # type: ignore[override]
        if Path(target).name == "index.html" and Path(target).parent == out:
            raise KeyboardInterrupt
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", kill_on_index)
    with pytest.raises(KeyboardInterrupt):
        _add(out)
    monkeypatch.undo()
    after = _tree(out)
    assert site_sports(out) == ("cfb",)
    for name in ("index.html", "site-data.json", "coverage.html", "app.js"):
        assert after[name] == before[name]
    assert set(before) <= set(after)
