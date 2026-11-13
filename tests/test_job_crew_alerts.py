"""Missing-crew alerts: detection windows, coverage filter, dedupe ledger, reminders,
message links, fail-fast inputs, the vault commit, SMTP settings and the workflow step.

Synthetic site files only; no real SMTP connection is opened.
"""

from __future__ import annotations

import json
import runpy
import smtplib
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from booth_review import cli
from booth_review.config import DataPaths, read_env_value
from booth_review.errors import VaultCommitError, VaultStateError
from booth_review.job.crew_alerts import (
    EXIT_LEDGER_NOT_SAVED,
    LEDGER_NAME,
    AlertLedger,
    compose,
    find_cfb_missing,
    find_missing,
    find_nfl_missing,
    load_ledger,
    read_reminders,
    record_sent,
    run_crew_alerts,
)
from booth_review.notify.email import (
    EmailConfigError,
    EmailSendError,
    EmailSettings,
    send_email,
)

# Monday 2026-11-09 20:00 ET.
NOW = datetime(2026, 11, 10, 1, 0, tzinfo=UTC)

CREW = [{"feed": "main", "person": 0, "role": "pbp"}]

_CFB_NAMES = ["date", "kickoff", "season", "week", "away_team", "home_team", "network", "crew"]
PEACOCK, ESPN, ESPN_PLUS, CW, MWN = range(5)


def _cfb_block(rows: list[dict[str, Any]]) -> dict[str, list[Any]]:
    return {name: [row[name] for row in rows] for name in _CFB_NAMES}


def _cfb_site(rows: list[dict[str, Any]], *, season: int = 2026) -> dict[str, Any]:
    return {
        "freshness": {"season": season},
        "lookups": {
            "teams": [{"name": "Michigan State"}, {"name": "Michigan"}, {"name": "Ohio"}],
            "networks": [
                {"family": "nbc", "id": "peacock", "name": "Peacock"},
                {"family": "disney", "id": "espn", "name": "ESPN"},
                {"family": "disney", "id": "espn-plus", "name": "ESPN+"},
                {"family": "cw", "id": "cw", "name": "The CW"},
                {"family": "conference", "id": "mountain-west-network", "name": "MWN"},
            ],
        },
        "telecasts": _cfb_block([]),
        "telecasts_unrated": _cfb_block(rows),
        "telecasts_scheduled": _cfb_block([]),
    }


def _cfb_row(kickoff: str | None, *, crew: list[Any] | None = None, **kw: Any) -> dict[str, Any]:
    row = {
        "date": (kickoff or "2026-11-07")[:10],
        "kickoff": kickoff,
        "season": 2026,
        "week": "10",
        "away_team": 0,
        "home_team": 1,
        "network": PEACOCK,
        "crew": crew if crew is not None else [],
    }
    row.update(kw)
    return row


_NFL_NAMES = ["date", "kickoff", "season", "week", "away", "home", "away_name", "home_name"]
_NFL_NAMES += ["network", "slot", "crew"]
TNF, SNF, MNF, SUNDAY_EARLY, CHRISTMAS = range(5)


def _nfl_site(games: list[dict[str, Any]], upcoming: list[dict[str, Any]]) -> dict[str, Any]:
    def block(rows: list[dict[str, Any]]) -> dict[str, list[Any]]:
        return {name: [row[name] for row in rows] for name in _NFL_NAMES}

    return {
        "freshness": {"season": 2026},
        "lookups": {
            "franchises": [{"id": "bills"}, {"id": "vikings"}],
            "team_names": [{"name": "Buffalo Bills"}, {"name": "Minnesota Vikings"}],
            "networks": [{"family": "disney", "id": "espn", "name": "ESPN"}],
            "slots": ["TNF", "SNF", "MNF", "Sunday early", "Christmas"],
        },
        "games": block(games),
        "upcoming": block(upcoming),
    }


def _nfl_row(
    kickoff: str | None, *, network: int | None = None, slot: int = SUNDAY_EARLY, **kw: Any
) -> dict[str, Any]:
    row = {
        "date": kickoff[:10] if kickoff else None,
        "kickoff": kickoff,
        "season": 2026,
        "week": 9,
        "away": 0,
        "home": 1,
        "away_name": 0,
        "home_name": 1,
        "network": network,
        "slot": slot,
        "crew": [],
    }
    row.update(kw)
    return row


def _write_sites(tmp_path: Path, cfb: dict | None, nfl: dict | None) -> DataPaths:
    paths = DataPaths(vault=tmp_path)
    paths.processed.mkdir(parents=True, exist_ok=True)
    paths.ledger.mkdir(parents=True, exist_ok=True)
    if cfb is not None:
        (paths.processed / "site-data.json").write_text(json.dumps(cfb), encoding="utf-8")
    if nfl is not None:
        (paths.processed / "nfl-data.json").write_text(json.dumps(nfl), encoding="utf-8")
    return paths


# -- detection -------------------------------------------------------------------------------


def test_cfb_played_game_without_crew_is_flagged() -> None:
    site = _cfb_site([_cfb_row("2026-11-07T19:30:00-05:00")])
    [game] = find_cfb_missing(site, NOW)
    assert (game.stage, game.away, game.home, game.network) == (
        "played",
        "Michigan State",
        "Michigan",
        "Peacock",
    )
    assert game.families == ("nbc",)


def test_cfb_game_with_main_crew_is_not_flagged() -> None:
    site = _cfb_site([_cfb_row("2026-11-07T19:30:00-05:00", crew=CREW)])
    assert find_cfb_missing(site, NOW) == []


def test_cfb_alt_feed_crew_alone_still_counts_as_missing() -> None:
    alt = [{"feed": "alt", "person": 0, "role": "pbp"}]
    site = _cfb_site([_cfb_row("2026-11-07T19:30:00-05:00", crew=alt)])
    assert len(find_cfb_missing(site, NOW)) == 1


@pytest.mark.parametrize(
    ("kickoff", "stage"),
    [
        ("2026-11-10T19:00:00-05:00", "upcoming"),  # 23h ahead
        ("2026-11-12T19:00:00-05:00", None),  # 71h ahead: too early
        ("2026-11-09T18:00:00-05:00", None),  # 2h ago: still in progress
        ("2026-11-02T19:00:00-05:00", "played"),  # 7 days ago
        ("2026-10-31T19:00:00-05:00", None),  # 9 days ago: too old
    ],
)
def test_cfb_windows(kickoff: str, stage: str | None) -> None:
    site = _cfb_site([_cfb_row(kickoff)])
    found = find_cfb_missing(site, NOW)
    assert [g.stage for g in found] == ([stage] if stage else [])


def test_cfb_tba_kickoff_counts_from_noon_et() -> None:
    site = _cfb_site([_cfb_row(None, date="2026-11-11")])
    [game] = find_cfb_missing(site, NOW)
    assert game.stage == "upcoming"
    assert not game.timed


def test_cfb_other_season_ignored() -> None:
    site = _cfb_site([_cfb_row("2026-11-07T19:30:00-05:00", season=2025)])
    assert find_cfb_missing(site, NOW) == []


@pytest.mark.parametrize("network", [None, ESPN_PLUS, MWN])
def test_cfb_uncovered_networks_are_never_flagged(network: int | None) -> None:
    site = _cfb_site([_cfb_row("2026-11-07T19:30:00-05:00", network=network)])
    assert find_cfb_missing(site, NOW) == []


def test_cfb_cw_is_covered_but_has_no_press_link() -> None:
    site = _cfb_site([_cfb_row("2026-11-07T19:30:00-05:00", network=CW)])
    [game] = find_cfb_missing(site, NOW)
    assert game.families == ()


def test_cfb_null_week_in_december_points_at_the_bowl_page() -> None:
    site = _cfb_site([_cfb_row("2026-12-19T15:00:00-05:00", week=None)])
    now = datetime(2026, 12, 21, 12, tzinfo=UTC)
    [game] = find_cfb_missing(site, now)
    assert game.week == "postseason"
    _, body = compose([game], [], still_open=[], aa_weeks={})
    assert "College football 2026 bowls and playoff (1)" in body
    assert "https://506sports.com/ncaaf.php?yr=2026&wk=B" in body
    assert "wk=?" not in body
    assert " ? " not in body


def test_cfb_null_week_in_season_points_at_the_season_index() -> None:
    site = _cfb_site([_cfb_row("2026-11-07T19:30:00-05:00", week=None)])
    [game] = find_cfb_missing(site, NOW)
    _, body = compose([game], [], still_open=[], aa_weeks={})
    assert "week not listed" in body
    assert "506 Sports: https://506sports.com/ncaaf.php?yr=2026\n" in body


def test_nfl_unknown_network_uses_slot_families() -> None:
    site = _nfl_site([_nfl_row("2026-11-08T13:00:00-05:00")], [])
    [game] = find_nfl_missing(site, NOW)
    assert game.stage == "played"
    assert game.network is None
    assert game.families == ("fox", "cbs")


@pytest.mark.parametrize("slot", [TNF, CHRISTMAS])
def test_nfl_slots_without_a_known_network_get_no_press_link(slot: int) -> None:
    site = _nfl_site([_nfl_row("2026-11-08T13:00:00-05:00", slot=slot)], [])
    [game] = find_nfl_missing(site, NOW)
    assert game.families == ()


def test_nfl_game_in_both_blocks_is_listed_once() -> None:
    mnf = _nfl_row("2026-11-09T20:15:00-05:00", network=0, slot=MNF)
    site = _nfl_site([mnf], [mnf])
    [game] = find_nfl_missing(site, NOW)
    assert (game.stage, game.network, game.families) == ("upcoming", "ESPN", ("disney",))


def test_nfl_game_with_crew_is_not_flagged() -> None:
    row = _nfl_row("2026-11-08T13:00:00-05:00", crew=[{"person": 0, "role": "pbp"}])
    assert find_nfl_missing(_nfl_site([row], []), NOW) == []


def test_nfl_game_with_no_date_or_kickoff_is_skipped_not_fatal() -> None:
    played = _nfl_row("2026-11-08T13:00:00-05:00")
    tba = _nfl_row(None, week=10, away=1, home=0)
    found = find_nfl_missing(_nfl_site([played], [tba]), NOW)
    assert [g.week for g in found] == ["9"]


def test_nfl_contract_fixture_with_null_date_does_not_crash() -> None:
    # Real builder output: the NFL contract lets an upcoming game's date and kickoff be null.
    helpers = runpy.run_path("tests/test_nfl_site_data.py")
    site = helpers["_with_upcoming"](
        [
            helpers["_up"](
                game_date=None,
                kickoff_utc=None,
                slot_name=None,
                network_id=None,
                network_basis=None,
            )
        ]
    )
    data = site.model_dump(mode="json")
    find_nfl_missing(data, datetime(2024, 9, 14, 12, tzinfo=UTC))


# -- fail fast on missing or malformed inputs -------------------------------------------------


def test_missing_cfb_site_file_fails(tmp_path: Path) -> None:
    paths = _write_sites(tmp_path, None, None)
    with pytest.raises(VaultStateError, match=r"site-data\.json"):
        find_missing(paths, NOW, nfl_required=False)


def test_missing_nfl_site_file_fails_only_when_the_nfl_site_is_on(tmp_path: Path) -> None:
    paths = _write_sites(tmp_path, _cfb_site([]), None)
    assert find_missing(paths, NOW, nfl_required=False) == []
    with pytest.raises(VaultStateError, match=r"nfl-data\.json"):
        find_missing(paths, NOW, nfl_required=True)


@pytest.mark.parametrize(
    "breakage",
    [
        lambda site: site["freshness"].update(season="2026"),
        lambda site: site.pop("telecasts_scheduled"),
        lambda site: site["telecasts_unrated"].pop("crew"),
        lambda site: site.pop("lookups"),
    ],
    ids=["season-string", "block-missing", "column-missing", "lookups-missing"],
)
def test_malformed_cfb_site_file_fails(breakage: Any) -> None:
    site = _cfb_site([_cfb_row("2026-11-07T19:30:00-05:00")])
    breakage(site)
    with pytest.raises(VaultStateError):
        find_cfb_missing(site, NOW)


def test_malformed_nfl_site_file_fails() -> None:
    site = _nfl_site([], [])
    site["games"].pop("kickoff")
    with pytest.raises(VaultStateError, match="games lacks kickoff"):
        find_nfl_missing(site, NOW)


def test_find_missing_rejects_naive_now(tmp_path: Path) -> None:
    paths = _write_sites(tmp_path, _cfb_site([]), None)
    with pytest.raises(ValueError, match="aware"):
        find_missing(paths, NOW.replace(tzinfo=None), nfl_required=False)


# -- message ---------------------------------------------------------------------------------


def test_compose_lists_new_and_open_games_with_their_sources() -> None:
    cfb = find_cfb_missing(_cfb_site([_cfb_row("2026-11-07T19:30:00-05:00")]), NOW)
    nfl = find_nfl_missing(_nfl_site([_nfl_row("2026-11-08T13:00:00-05:00")], []), NOW)
    aa_post = "https://awfulannouncing.com/college-football/2026-week-10-schedule.html"
    subject, body = compose(cfb + nfl, [], still_open=cfb * 3, aa_weeks={"2026-10": aa_post})
    assert subject == "booth-review: 5 games with no crew"
    assert "https://506sports.com/ncaaf.php?yr=2026&wk=10" in body
    assert aa_post in body
    assert "https://www.nbcsports.com/pressbox" in body
    assert "https://506sports.com/nfl.php?yr=2026&wk=9" in body
    assert "https://awfulannouncing.com/category/schedules" in body
    assert "https://www.foxsports.com/presspass" in body
    assert "https://www.paramountpressexpress.com/cbs-sports/" in body
    assert "- Michigan State at Michigan" in body
    assert "Sat Nov 7, 7:30 PM ET, Peacock" in body
    assert "booth-review import 506 --season 2026 --league nfl" in body
    assert "gh workflow run collect.yml -R benboro/booth-review-data -f mode=rebuild" in body


def test_compose_reminders_only_lists_no_games() -> None:
    reminder = "reminder 2026 cfb week 11: save it https://x.test/"
    earlier = find_cfb_missing(_cfb_site([_cfb_row("2026-11-07T19:30:00-05:00")]), NOW)
    subject, body = compose([], [reminder], still_open=earlier, aa_weeks={})
    assert subject == "booth-review: 1 hand-save reminder"
    assert "Michigan" not in body


def test_compose_falls_back_to_aa_schedules_page() -> None:
    cfb = find_cfb_missing(_cfb_site([_cfb_row("2026-11-07T19:30:00-05:00")]), NOW)
    _, body = compose(cfb, [], still_open=[], aa_weeks={"2026-10": "reminded"})
    assert "Awful Announcing: https://awfulannouncing.com/category/schedules" in body


def test_compose_espn_cfb_links_the_commentators_page() -> None:
    site = _cfb_site([_cfb_row("2026-11-10T19:00:00-05:00", network=ESPN, week="11")])
    cfb = find_cfb_missing(site, NOW)
    _, body = compose(cfb, [], still_open=[], aa_weeks={})
    assert "2026-27-espn-college-football-commentators-schedule/" in body
    assert body.index("KICKING OFF") < body.index("week 11")


def test_compose_reminders_only() -> None:
    line = "reminder 2026 nfl week 10: save the 506 nfl week 10 page https://506sports.com/nfl.php"
    subject, body = compose([], [line], still_open=[], aa_weeks={})
    assert subject == "booth-review: 1 hand-save reminder"
    assert f"HAND-SAVE REMINDERS\n\n- {line}\n" in body
    assert "import 506" not in body


def test_read_reminders_keeps_item_lines_only(tmp_path: Path) -> None:
    path = tmp_path / "reminders.md"
    path.write_text(
        "Counts only. Updated 2026-11-10T00:00:00Z\n- reminder a\n- reminder b\n\nrun: https://x\n",
        encoding="utf-8",
    )
    assert read_reminders(path) == ["reminder a", "reminder b"]
    assert read_reminders(tmp_path / "absent.md") == []
    assert read_reminders(None) == []


# -- ledger and command ----------------------------------------------------------------------


class _Sent:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def __call__(self, settings: EmailSettings, subject: str, body: str) -> None:
        self.messages.append((subject, body))


def _settings() -> EmailSettings:
    return EmailSettings("smtp.example.test", 587, "u", "p", ("to@example.test",), "u")


def _kw(sent: _Sent, **extra: Any) -> dict[str, Any]:
    return {"commit": False, "load_settings": _settings, "send": sent, **extra}


def test_run_emails_once_per_game_and_stage(tmp_path: Path) -> None:
    paths = _write_sites(tmp_path, _cfb_site([_cfb_row("2026-11-10T19:00:00-05:00")]), None)
    sent = _Sent()

    assert run_crew_alerts(paths, NOW, **_kw(sent)) == 0
    assert len(sent.messages) == 1
    assert load_ledger(paths).sent

    # Same game, same stage, a later backup slot: nothing new.
    assert run_crew_alerts(paths, NOW + timedelta(hours=2), **_kw(sent)) == 0
    assert len(sent.messages) == 1

    # After the game: the played stage is new.
    assert run_crew_alerts(paths, NOW + timedelta(days=2), **_kw(sent)) == 0
    assert len(sent.messages) == 2
    assert "NO CREW, ALREADY PLAYED" in sent.messages[1][1]


def test_run_second_email_lists_every_open_game_in_one_list(tmp_path: Path) -> None:
    first = _cfb_row("2026-11-07T19:30:00-05:00")
    paths = _write_sites(tmp_path, _cfb_site([first]), None)
    sent = _Sent()
    run_crew_alerts(paths, NOW, **_kw(sent))
    second = _cfb_row("2026-11-07T12:00:00-05:00", away_team=2)
    _write_sites(tmp_path, _cfb_site([first, second]), None)
    run_crew_alerts(paths, NOW + timedelta(hours=1), **_kw(sent))
    body = sent.messages[1][1]
    assert "- Ohio at Michigan" in body
    assert "- Michigan State at Michigan" in body
    assert body.count("Sources:") == 1
    assert "college football 2026 week 10 (2)" in body.lower()
    assert "EARLIER" not in body


def test_run_emails_each_reminder_line_once(tmp_path: Path) -> None:
    paths = _write_sites(tmp_path, _cfb_site([]), None)
    reminders = tmp_path / "reminders.md"
    reminders.write_text("Counts only.\n- reminder 2026 cfb week 11: save x\n", encoding="utf-8")
    sent = _Sent()
    run_crew_alerts(paths, NOW, **_kw(sent, reminders_file=reminders))
    run_crew_alerts(paths, NOW + timedelta(hours=1), **_kw(sent, reminders_file=reminders))
    assert [subject for subject, _ in sent.messages] == ["booth-review: 1 hand-save reminder"]
    reminders.write_text(
        "- reminder 2026 cfb week 11: save x\n- reminder 2026 nfl week 10: y\n", encoding="utf-8"
    )
    run_crew_alerts(paths, NOW + timedelta(hours=2), **_kw(sent, reminders_file=reminders))
    assert len(sent.messages) == 2
    assert "save x" not in sent.messages[1][1]
    assert "nfl week 10: y" in sent.messages[1][1]


def test_run_dry_run_sends_and_records_nothing(tmp_path: Path) -> None:
    paths = _write_sites(tmp_path, _cfb_site([_cfb_row("2026-11-07T19:30:00-05:00")]), None)
    sent = _Sent()
    assert run_crew_alerts(paths, NOW, **_kw(sent, dry_run=True, commit=True)) == 0
    assert sent.messages == []
    assert not (paths.ledger / LEDGER_NAME).exists()


def test_run_without_new_items_needs_no_settings(tmp_path: Path) -> None:
    paths = _write_sites(tmp_path, _cfb_site([]), None)

    def no_settings() -> EmailSettings:
        raise AssertionError("settings must not be read")

    assert run_crew_alerts(paths, NOW, commit=False, load_settings=no_settings) == 0


def test_run_failed_send_records_nothing(tmp_path: Path) -> None:
    paths = _write_sites(tmp_path, _cfb_site([_cfb_row("2026-11-07T19:30:00-05:00")]), None)

    def fail(settings: EmailSettings, subject: str, body: str) -> None:
        raise EmailSendError("email not sent (SMTPAuthenticationError)")

    with pytest.raises(EmailSendError):
        run_crew_alerts(paths, NOW, commit=False, load_settings=_settings, send=fail)
    assert not (paths.ledger / LEDGER_NAME).exists()


def test_run_prints_counts_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    paths = _write_sites(tmp_path, _cfb_site([_cfb_row("2026-11-07T19:30:00-05:00")]), None)
    reminders = tmp_path / "reminders.md"
    reminders.write_text("- reminder private-looking line\n", encoding="utf-8")
    run_crew_alerts(paths, NOW, **_kw(_Sent(), reminders_file=reminders))
    out = capsys.readouterr().out
    assert "Michigan" not in out
    assert "private-looking" not in out
    assert "1 games with no crew" in out


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _vault_with_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    _git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    vault = tmp_path / "vault"
    _git("clone", str(remote), str(vault), cwd=tmp_path)
    _git("config", "user.name", "t", cwd=vault)
    _git("config", "user.email", "t@example.test", cwd=vault)
    (vault / "README.md").write_text("x\n", encoding="utf-8")
    _git("add", "README.md", cwd=vault)
    _git("commit", "-m", "init", cwd=vault)
    _git("push", "-u", "origin", "main", cwd=vault)
    return vault


def test_run_commits_only_the_ledger(tmp_path: Path) -> None:
    vault = _vault_with_remote(tmp_path)
    paths = _write_sites(vault, _cfb_site([_cfb_row("2026-11-07T19:30:00-05:00")]), None)
    sent = _Sent()
    assert run_crew_alerts(paths, NOW, load_settings=_settings, send=sent) == 0
    assert len(sent.messages) == 1
    subject, *files = _git("log", "-1", "--name-only", "--format=%s", cwd=vault).split("\n")
    assert subject.startswith("notify: crew alert email")
    assert [f for f in files if f] == [f"ledger/{LEDGER_NAME}"]
    # The site files stay uncommitted; only the ledger was staged, and it was pushed.
    assert "processed/" in _git("status", "--porcelain", cwd=vault)
    assert _git("rev-parse", "HEAD", cwd=vault) == _git("rev-parse", "origin/main", cwd=vault)


def test_run_reports_a_failed_ledger_commit_after_sending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault_with_remote(tmp_path)
    paths = _write_sites(vault, _cfb_site([_cfb_row("2026-11-07T19:30:00-05:00")]), None)

    def refuse(self: object, message: str, **kw: object) -> bool:
        raise VaultCommitError("git subcommand push exited 1")

    monkeypatch.setattr("booth_review.vault.VaultRepo.commit_batch", refuse)
    sent = _Sent()
    code = run_crew_alerts(paths, NOW, load_settings=_settings, send=sent)
    assert code == EXIT_LEDGER_NOT_SAVED
    assert len(sent.messages) == 1


def test_run_holds_the_vault_lock_while_sending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from booth_review.vault import _VAULT_LOCKS

    vault = _vault_with_remote(tmp_path)
    paths = _write_sites(vault, _cfb_site([_cfb_row("2026-11-07T19:30:00-05:00")]), None)
    held: list[bool] = []

    def send(settings: EmailSettings, subject: str, body: str) -> None:
        held.append(vault.resolve() in _VAULT_LOCKS)

    run_crew_alerts(paths, NOW, load_settings=_settings, send=send)
    assert held == [True]


def test_record_sent_prunes_old_entries() -> None:
    old = AlertLedger(sent={"cfb:x|played": "2026-09-01T00:00:00Z"})
    assert record_sent(old, [], NOW).sent == {}


def test_load_ledger_rejects_bad_shape(tmp_path: Path) -> None:
    paths = _write_sites(tmp_path, None, None)
    (paths.ledger / LEDGER_NAME).write_text('{"sent": [1]}', encoding="utf-8")
    with pytest.raises(VaultStateError):
        load_ledger(paths)


# -- CLI -------------------------------------------------------------------------------------


def test_cli_rejects_a_naive_now() -> None:
    assert cli.main(["job", "crew-alerts", "--now", "2026-11-10T01:00:00", "--dry-run"]) == 2


def test_cli_dry_run_reads_the_vault_and_the_nfl_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_sites(tmp_path, _cfb_site([_cfb_row("2026-11-07T19:30:00-05:00")]), None)
    monkeypatch.setenv("BOOTH_REVIEW_VAULT", str(tmp_path))
    monkeypatch.delenv("NFL_SITE_ENABLED", raising=False)
    argv = ["job", "crew-alerts", "--now", "2026-11-10T01:00:00+00:00", "--dry-run"]
    assert cli.main(argv) == 0
    assert "1 not emailed yet" in capsys.readouterr().out
    monkeypatch.setenv("NFL_SITE_ENABLED", "true")
    assert cli.main(argv) == 3  # nfl-data.json is required now


# -- email settings and SMTP -----------------------------------------------------------------

_ENV_NAMES = (
    "BOOTH_REVIEW_SMTP_HOST",
    "BOOTH_REVIEW_SMTP_PORT",
    "BOOTH_REVIEW_SMTP_USER",
    "BOOTH_REVIEW_SMTP_PASSWORD",
    "BOOTH_REVIEW_ALERT_TO",
    "BOOTH_REVIEW_ALERT_FROM",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_settings_missing_names_variables_only(
    clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_env.setenv("BOOTH_REVIEW_SMTP_PASSWORD", "hunter2")
    with pytest.raises(EmailConfigError) as excinfo:
        EmailSettings.from_env(tmp_path / ".env")
    message = str(excinfo.value)
    assert "BOOTH_REVIEW_SMTP_HOST" in message
    assert "BOOTH_REVIEW_SMTP_PASSWORD" not in message
    assert "hunter2" not in message


def test_settings_read_from_env_file(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "BOOTH_REVIEW_SMTP_HOST=smtp.example.test\n"
        "BOOTH_REVIEW_SMTP_USER=me@example.test\n"
        'BOOTH_REVIEW_SMTP_PASSWORD="app pass"\n'
        "BOOTH_REVIEW_ALERT_TO=a@example.test, b@example.test\n",
        encoding="utf-8",
    )
    settings = EmailSettings.from_env(env)
    assert settings.port == 587
    assert settings.password == "app pass"
    assert settings.to == ("a@example.test", "b@example.test")
    assert settings.sender == "me@example.test"
    assert "app pass" not in repr(settings)


def test_read_env_value_prefers_environment(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("BOOTH_REVIEW_SMTP_HOST=file\n", encoding="utf-8")
    clean_env.setenv("BOOTH_REVIEW_SMTP_HOST", "env")
    assert read_env_value("BOOTH_REVIEW_SMTP_HOST", env) == "env"
    assert read_env_value("BOOTH_REVIEW_SMTP_USER", env) is None


class _FakeSmtp:
    def __init__(self, fail: bool = False, refused: dict[str, Any] | None = None) -> None:
        self.fail = fail
        self.refused = refused or {}
        self.logged_in: tuple[str, str] | None = None
        self.sent: list[Any] = []

    def __enter__(self) -> _FakeSmtp:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def login(self, user: str, password: str) -> None:
        if self.fail:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
        self.logged_in = (user, password)

    def send_message(self, message: Any) -> dict[str, Any]:
        self.sent.append(message)
        return self.refused


def test_send_email_logs_in_and_sends() -> None:
    fake = _FakeSmtp()
    send_email(_settings(), "subject", "body\n", connect=lambda s: fake)  # type: ignore[arg-type,return-value]
    assert fake.logged_in == ("u", "p")
    [message] = fake.sent
    assert message["To"] == "to@example.test"
    assert message["Subject"] == "subject"


def test_send_email_wraps_smtp_errors() -> None:
    fake = _FakeSmtp(fail=True)
    with pytest.raises(EmailSendError, match="SMTPAuthenticationError"):
        send_email(_settings(), "s", "b", connect=lambda s: fake)  # type: ignore[arg-type,return-value]


def test_send_email_fails_when_a_recipient_is_refused() -> None:
    fake = _FakeSmtp(refused={"bad@example.test": (550, b"no such user")})
    with pytest.raises(EmailSendError, match="refused for 1 of 1"):
        send_email(_settings(), "s", "b", connect=lambda s: fake)  # type: ignore[arg-type,return-value]


# -- workflow template -----------------------------------------------------------------------

_STEP = "Email games with no crew and hand-save reminders"


def test_workflow_runs_crew_alerts_with_secrets_and_the_reminder_file() -> None:
    workflow = yaml.safe_load(Path("ops/vault/collect.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["collect"]["steps"]
    names = [step.get("name", "") for step in steps]
    step = steps[names.index(_STEP)]
    assert step["run"] == (
        'uv run booth-review job crew-alerts --reminders "$RUNNER_TEMP/reminders.md"'
    )
    assert "!cancelled()" in step["if"]
    for name in _ENV_NAMES:
        assert step["env"][name] == f"${{{{ secrets.{name} }}}}"
    assert step["env"]["NFL_SITE_ENABLED"] == "${{ vars.NFL_SITE_ENABLED }}"
    # After the attention issue (which also reads the reminder file), before the final gate.
    attention = names.index("Update the attention issue (count-only, one tracked issue)")
    assert attention < names.index(_STEP) < names.index("Fail the workflow on a hard failure")
