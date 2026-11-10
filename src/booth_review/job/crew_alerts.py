"""Missing-crew alerts and hand-save reminders, emailed to the user.

Reads only the built site files in the vault (`processed/site-data.json` for
college football and `processed/nfl-data.json` for the NFL), the AA feed watch
ledger (for that week's AA post link) and the job's reminder file. It sends no
request to any data source; the only network call is the SMTP send in
`notify.email`.

A game is flagged at two stages:
- upcoming: it kicks off within UPCOMING_WINDOW and has no main crew;
- played: it kicked off between PLAYED_WINDOW and GAME_LENGTH ago and still has
  no main crew.

College football games count only on networks a crew source covers (see
`_cfb_covered`): a game with no network yet, or on ESPN+ and the other
streaming-only or conference-digital outlets, is never flagged, since 506, AA
and the press pages almost never list those crews. Every NFL game counts.

Limit: bowls, the CFB playoff and the NFL playoffs reach the site files only
once their 506 page is imported, so until then neither stage can flag them.

`ledger/crew_alerts.json` records each (game, stage) and each reminder line
already emailed. An email goes out only when something is new, and it lists
only the new games and reminders, with a count of the games flagged earlier
that still have no crew.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from booth_review.config import DataPaths
from booth_review.errors import VaultCommitError, VaultStateError
from booth_review.job.attention import (
    REMINDER_AA_CFB_URL,
    REMINDER_AA_NFL_URL,
    espnpr_commentators_url,
)
from booth_review.job.gaps506 import GAME_LENGTH
from booth_review.nfl.layout import nfl_506_url
from booth_review.notify.email import EmailSettings, send_email
from booth_review.sources.aa.feed import load_feed_state, week_key
from booth_review.transport.cache import atomic_write_json
from booth_review.vault import VaultRepo

EASTERN = ZoneInfo("America/New_York")

UPCOMING_WINDOW = timedelta(hours=48)
PLAYED_WINDOW = timedelta(days=8)
LEDGER_NAME = "crew_alerts.json"
LEDGER_REL = f"ledger/{LEDGER_NAME}"
_LEDGER_KEEP = timedelta(days=45)
_REMINDER_PREFIX = "reminder:"

#: Exit code when the email went out but the ledger commit or push failed; the next
#: run will send the same items again (at-least-once delivery).
EXIT_LEDGER_NOT_SAVED = 4

CFB_SITE_DATA = "site-data.json"
NFL_SITE_DATA = "nfl-data.json"
_CFB_BLOCKS = ("telecasts", "telecasts_unrated", "telecasts_scheduled")
_CFB_COLUMNS = ("season", "date", "kickoff", "week", "away_team", "home_team", "network", "crew")
_NFL_BLOCKS = ("games", "upcoming")
_NFL_COLUMNS = ("season", "week", "date", "kickoff", "away", "home", "network", "slot", "crew")
_NFL_OPTIONAL_COLUMNS = ("away_name", "home_name")

League = Literal["cfb", "nfl"]
Stage = Literal["upcoming", "played"]

_LOG = logging.getLogger(__name__)

# Network press pages, by network family (lookups.networks[].family). Fixed public
# pages the user browses by hand; the job never fetches them.
_FOX_PRESS = ("FOX Sports PressPass", "https://www.foxsports.com/presspass")
_CBS_PRESS = ("CBS Sports press", "https://www.paramountpressexpress.com/cbs-sports/")
_NBC_PRESS = ("NBC Sports Pressbox", "https://www.nbcsports.com/pressbox")
_ESPN_NFL_PRESS = ("ESPN Press Room", "https://espnpressroom.com/")
_FAMILY_ORDER = ("disney", "fox", "cbs", "nbc")

# CFB networks whose crews 506, AA or a press page lists: these families, minus the
# streaming-only outlets below (Peacock and Paramount+ stay: they carry national
# packages that 506 and AA list).
_CFB_COVERED_FAMILIES = frozenset({"disney", "fox", "cbs", "nbc", "cw", "wbd"})
_CFB_UNCOVERED_NETWORKS = frozenset(
    {
        "espn-plus",
        "espn3",
        "espn-unlimited",
        "acc-network-extra",
        "sec-network-plus",
        "disney-plus",
        "cbs-sports-facebook",
    }
)

# An NFL game whose network is not known yet (506 not imported) takes its slot's
# usual press pages; a slot not listed here (TNF and Black Friday on Prime Video,
# Christmas, the late-season Saturday and Friday games, Other) gets none.
_NFL_SLOT_FAMILIES: Mapping[str, tuple[str, ...]] = {
    "SNF": ("nbc",),
    "MNF": ("disney",),
    "Sunday early": ("fox", "cbs"),
    "Sunday late": ("fox", "cbs"),
    "International": ("fox", "cbs"),
    "Thanksgiving": ("fox", "cbs", "nbc"),
}

# A CFB game with no week label in lookups.weeks: 506's bowl page in December and
# January, else the season index.
_POSTSEASON_MONTHS = frozenset({12, 1})
CFB_POSTSEASON = "postseason"
CFB_UNLISTED = "unlisted"


@dataclass(frozen=True)
class MissingCrew:
    league: League
    season: int
    week: str
    stage: Stage
    kickoff: datetime
    timed: bool
    away: str
    home: str
    network: str | None
    families: tuple[str, ...]
    game_key: str

    @property
    def alert_key(self) -> str:
        return f"{self.game_key}|{self.stage}"


@dataclass
class AlertLedger:
    sent: dict[str, str] = field(default_factory=dict)


# -- reading ---------------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VaultStateError(f"{path.name}: unreadable ({type(exc).__name__})") from exc
    if not isinstance(raw, dict):
        raise VaultStateError(f"{path.name}: top level must be an object")
    return raw


def _require_shape(
    data: Mapping[str, Any], name: str, blocks: Sequence[str], columns: Sequence[str]
) -> int:
    """The site file's season; raises VaultStateError when its shape is not the expected one,
    so a contract change can never read as "no game is missing a crew"."""
    season = (data.get("freshness") or {}).get("season")
    if not isinstance(season, int) or isinstance(season, bool):
        raise VaultStateError(f"{name}: freshness.season is not a year")
    if not isinstance(data.get("lookups"), dict):
        raise VaultStateError(f"{name}: lookups missing")
    for block_name in blocks:
        block = data.get(block_name)
        if not isinstance(block, dict):
            raise VaultStateError(f"{name}: block {block_name} missing")
        absent = [column for column in columns if column not in block]
        if absent:
            raise VaultStateError(f"{name}: {block_name} lacks {', '.join(absent)}")
        lengths = {len(block[column]) for column in columns}
        if len(lengths) > 1:
            raise VaultStateError(f"{name}: {block_name} columns differ in length")
    return season


def _kickoff(date: object, kickoff: object) -> tuple[datetime, bool] | None:
    """Aware kickoff; a TBA game counts from noon ET on its date; None with neither."""
    if isinstance(kickoff, str) and kickoff:
        moment = datetime.fromisoformat(kickoff)
        if moment.tzinfo is not None:
            return moment, True
    if not isinstance(date, str) or not date:
        return None
    day = datetime.fromisoformat(date)
    return day.replace(hour=12, tzinfo=EASTERN), False


def _stage(kickoff: datetime, now: datetime) -> Stage | None:
    if now < kickoff <= now + UPCOMING_WINDOW:
        return "upcoming"
    if kickoff + GAME_LENGTH <= now < kickoff + PLAYED_WINDOW:
        return "played"
    return None


def _has_main_crew(crew: object) -> bool:
    if not isinstance(crew, list):
        return False
    return any(isinstance(entry, dict) and entry.get("feed", "main") == "main" for entry in crew)


def _rows(block: Mapping[str, list[Any]]) -> Iterable[dict[str, Any]]:
    columns = list(block)
    if not columns:
        return
    for i in range(len(block[columns[0]])):
        yield {name: block[name][i] for name in columns}


def _lookup(items: Sequence[Mapping[str, Any]], index: object) -> Mapping[str, Any] | None:
    if isinstance(index, int) and 0 <= index < len(items):
        return items[index]
    return None


def _cfb_covered(net: Mapping[str, Any] | None) -> bool:
    if net is None:
        return False
    return net.get("family") in _CFB_COVERED_FAMILIES and net.get("id") not in (
        _CFB_UNCOVERED_NETWORKS
    )


def _cfb_week(raw: object, date: str) -> str:
    if isinstance(raw, str) and raw:
        return raw
    return CFB_POSTSEASON if int(date[5:7]) in _POSTSEASON_MONTHS else CFB_UNLISTED


def find_cfb_missing(data: Mapping[str, Any], now: datetime) -> list[MissingCrew]:
    """Current-season CFB telecasts on covered networks with no main crew, in a window."""
    season = _require_shape(data, CFB_SITE_DATA, _CFB_BLOCKS, _CFB_COLUMNS)
    lookups = data["lookups"]
    teams = lookups.get("teams") or []
    networks = lookups.get("networks") or []
    found: dict[str, MissingCrew] = {}
    for block_name in _CFB_BLOCKS:
        for row in _rows(data[block_name]):
            if row["season"] != season or _has_main_crew(row["crew"]):
                continue
            net = _lookup(networks, row["network"])
            if not _cfb_covered(net):
                continue
            assert net is not None
            when = _kickoff(row["date"], row["kickoff"])
            if when is None:
                continue
            kickoff, timed = when
            stage = _stage(kickoff, now)
            if stage is None:
                continue
            away = (_lookup(teams, row["away_team"]) or {}).get("name", "?")
            home = (_lookup(teams, row["home_team"]) or {}).get("name", "?")
            family = net.get("family")
            key = f"cfb:{season}:{row['date']}:{away}:{home}"
            found.setdefault(
                key,
                MissingCrew(
                    league="cfb",
                    season=season,
                    week=_cfb_week(row["week"], str(row["date"])),
                    stage=stage,
                    kickoff=kickoff,
                    timed=timed,
                    away=away,
                    home=home,
                    network=net.get("name"),
                    families=(family,) if family in _FAMILY_ORDER else (),
                    game_key=key,
                ),
            )
    return list(found.values())


def find_nfl_missing(data: Mapping[str, Any], now: datetime) -> list[MissingCrew]:
    """Current-season NFL games on the site with no crew, in a window."""
    season = _require_shape(data, NFL_SITE_DATA, _NFL_BLOCKS, _NFL_COLUMNS)
    lookups = data["lookups"]
    franchises = lookups.get("franchises") or []
    team_names = lookups.get("team_names") or []
    networks = lookups.get("networks") or []
    slots = lookups.get("slots") or []
    found: dict[str, MissingCrew] = {}
    for block_name in _NFL_BLOCKS:
        for row in _rows(data[block_name]):
            if row["season"] != season or row["crew"]:
                continue
            when = _kickoff(row["date"], row["kickoff"])
            if when is None:
                continue
            kickoff, timed = when
            stage = _stage(kickoff, now)
            if stage is None:
                continue
            away_id = (_lookup(franchises, row["away"]) or {}).get("id", "?")
            home_id = (_lookup(franchises, row["home"]) or {}).get("id", "?")
            away = (_lookup(team_names, row.get("away_name")) or {}).get("name", away_id)
            home = (_lookup(team_names, row.get("home_name")) or {}).get("name", home_id)
            net = _lookup(networks, row["network"])
            slot = row["slot"]
            slot_name = slots[slot] if isinstance(slot, int) and 0 <= slot < len(slots) else None
            families: tuple[str, ...]
            if net is not None:
                family = net.get("family")
                families = (family,) if family in _FAMILY_ORDER else ()
            else:
                families = _NFL_SLOT_FAMILIES.get(str(slot_name), ())
            key = f"nfl:{season}:{row['week']}:{away_id}:{home_id}"
            found.setdefault(
                key,
                MissingCrew(
                    league="nfl",
                    season=season,
                    week=str(row["week"]),
                    stage=stage,
                    kickoff=kickoff,
                    timed=timed,
                    away=away,
                    home=home,
                    network=net.get("name") if net else None,
                    families=families,
                    game_key=key,
                ),
            )
    return list(found.values())


def find_missing(paths: DataPaths, now: datetime, *, nfl_required: bool) -> list[MissingCrew]:
    """Flagged games from both site files. The CFB file must exist; the NFL file must
    exist when `nfl_required` (the NFL site is on), and is read whenever it exists."""
    if now.tzinfo is None:
        raise ValueError("find_missing needs an aware datetime")
    cfb_path = paths.processed / CFB_SITE_DATA
    if not cfb_path.is_file():
        raise VaultStateError(f"{CFB_SITE_DATA}: not built in the vault")
    missing = find_cfb_missing(_read_json(cfb_path), now)
    nfl_path = paths.processed / NFL_SITE_DATA
    if nfl_path.is_file():
        missing.extend(find_nfl_missing(_read_json(nfl_path), now))
    elif nfl_required:
        raise VaultStateError(f"{NFL_SITE_DATA}: not built in the vault")
    return missing


def read_reminders(path: Path | None) -> list[str]:
    """The reminder lines (`- ` items) the job wrote, without the bullet; [] when absent."""
    if path is None or not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line[2:].strip() for line in lines if line.startswith("- ") and line[2:].strip()]


# -- ledger ----------------------------------------------------------------------------------


def load_ledger(paths: DataPaths) -> AlertLedger:
    path = paths.ledger / LEDGER_NAME
    if not path.is_file():
        return AlertLedger()
    raw = _read_json(path)
    sent = raw.get("sent")
    if not isinstance(sent, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in sent.items()
    ):
        raise VaultStateError(f"{LEDGER_NAME}: sent must map strings to strings")
    return AlertLedger(sent=dict(sent))


def reminder_key(line: str) -> str:
    return f"{_REMINDER_PREFIX}{line}"


def record_sent(ledger: AlertLedger, keys: Iterable[str], now: datetime) -> AlertLedger:
    """The ledger with `keys` marked sent at `now` and entries past _LEDGER_KEEP pruned."""
    stamp = now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    cutoff = now - _LEDGER_KEEP
    kept = {
        key: when
        for key, when in ledger.sent.items()
        if datetime.fromisoformat(when.replace("Z", "+00:00")) >= cutoff
    }
    for key in keys:
        kept[key] = stamp
    return AlertLedger(sent=dict(sorted(kept.items())))


def write_ledger(paths: DataPaths, ledger: AlertLedger) -> None:
    atomic_write_json(paths.ledger / LEDGER_NAME, {"sent": ledger.sent})


def new_alerts(missing: Iterable[MissingCrew], ledger: AlertLedger) -> list[MissingCrew]:
    return [m for m in missing if m.alert_key not in ledger.sent]


def new_reminders(lines: Iterable[str], ledger: AlertLedger) -> list[str]:
    seen: set[str] = set()
    fresh: list[str] = []
    for line in lines:
        if reminder_key(line) not in ledger.sent and line not in seen:
            seen.add(line)
            fresh.append(line)
    return fresh


# -- message ---------------------------------------------------------------------------------


def _aa_cfb_link(aa_weeks: Mapping[str, str], season: int, week: str) -> str:
    url = aa_weeks.get(week_key(season, week), "")
    return url if url.startswith("https://awfulannouncing.com/") else REMINDER_AA_CFB_URL


def _press_link(league: League, family: str, season: int) -> tuple[str, str]:
    if family == "disney":
        if league == "cfb":
            return ("ESPN Press Room commentators", espnpr_commentators_url(season))
        return _ESPN_NFL_PRESS
    return {"fox": _FOX_PRESS, "cbs": _CBS_PRESS, "nbc": _NBC_PRESS}[family]


def _cfb_506_link(season: int, week: str) -> str:
    if week == CFB_POSTSEASON:
        return f"https://506sports.com/ncaaf.php?yr={season}&wk=B"
    if week == CFB_UNLISTED:
        return f"https://506sports.com/ncaaf.php?yr={season}"
    return f"https://506sports.com/ncaaf.php?yr={season}&wk={week}"


def _sources(
    league: League,
    season: int,
    week: str,
    games: Sequence[MissingCrew],
    aa_weeks: Mapping[str, str],
) -> list[tuple[str, str]]:
    if league == "cfb":
        links = [
            ("506 Sports", _cfb_506_link(season, week)),
            ("Awful Announcing", _aa_cfb_link(aa_weeks, season, week)),
        ]
    else:
        links = [("Awful Announcing", REMINDER_AA_NFL_URL)]
        if week.isdigit():
            links.insert(0, ("506 Sports", nfl_506_url(season, int(week))))
    families = {f for g in games for f in g.families}
    links.extend(_press_link(league, f, season) for f in _FAMILY_ORDER if f in families)
    return links


def _when(game: MissingCrew) -> str:
    local = game.kickoff.astimezone(EASTERN)
    day = f"{local:%a} {local:%b} {local.day}"
    if not game.timed:
        return f"{day}, time TBA"
    hour = local.hour % 12 or 12
    return f"{day}, {hour}:{local:%M} {'AM' if local.hour < 12 else 'PM'} ET"


def _week_heading(league: League, season: int, week: str) -> str:
    if week.isdigit():
        label = f"week {week}"
    elif week == CFB_POSTSEASON:
        label = "bowls and playoff"
    elif week == CFB_UNLISTED:
        label = "week not listed"
    else:
        label = week
    return f"{_LEAGUE_NAME[league]} {season} {label}"


_LEAGUE_NAME = {"cfb": "College football", "nfl": "NFL"}
_STAGE_TITLE = {"upcoming": "Kicking off in the next 48 hours", "played": "Played, still no crew"}
_IMPORT_HINT = {
    "cfb": "booth-review import 506 --season {season}",
    "nfl": "booth-review import 506 --season {season} --league nfl",
}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def compose(
    new: Sequence[MissingCrew],
    reminders: Sequence[str],
    *,
    still_open: int,
    aa_weeks: Mapping[str, str],
) -> tuple[str, str]:
    """(subject, plain-text body) for the new games and new reminder lines.

    `still_open` counts games flagged in an earlier email that still have no crew.
    """
    subject_parts: list[str] = []
    if new:
        subject_parts.append(f"{_plural(len(new), 'game')} with no crew")
    if reminders:
        subject_parts.append(_plural(len(reminders), "hand-save reminder"))
    subject = f"booth-review: {', '.join(subject_parts)}"

    lines: list[str] = []
    groups: dict[tuple[Stage, League, int, str], list[MissingCrew]] = {}
    for game in new:
        groups.setdefault((game.stage, game.league, game.season, game.week), []).append(game)

    def order(key: tuple[Stage, League, int, str]) -> tuple[int, int, int, int, str]:
        _, league, season, week = key
        return (0 if league == "cfb" else 1, season, int(week) if week.isdigit() else 99, 0, week)

    for stage in ("upcoming", "played"):
        keys = sorted((k for k in groups if k[0] == stage), key=order)
        if not keys:
            continue
        lines.append(_STAGE_TITLE[stage].upper())
        lines.append("")
        for key in keys:
            _, league, season, week = key
            games = sorted(groups[key], key=lambda g: (g.kickoff, g.away))
            lines.append(f"{_week_heading(league, season, week)} ({len(games)})")
            for game in games:
                network = game.network or "network not known yet"
                lines.append(f"- {game.away} at {game.home}")
                lines.append(f"  {_when(game)}, {network}")
            lines.append("Sources:")
            for name, url in _sources(league, season, week, games, aa_weeks):
                lines.append(f"- {name}: {url}")
            lines.append("")

    if still_open:
        lines.append(
            f"{_plural(still_open, 'game')} from earlier emails still "
            f"{'has' if still_open == 1 else 'have'} no crew."
        )
        lines.append("")

    if new:
        lines.append("After saving a page, import it, then dispatch the job with mode=rebuild:")
        seasons = sorted({(m.league, m.season) for m in new})
        lines.extend(f"  {_IMPORT_HINT[lg].format(season=season)}" for lg, season in seasons)
        if any(m.league == "cfb" for m in new):
            lines.append("  booth-review import espnpr")
        lines.append("")

    if reminders:
        lines.append("HAND-SAVE REMINDERS")
        lines.append("")
        lines.extend(f"- {line}" for line in reminders)
        lines.append("")

    if new:
        lines.append(
            "Each game is emailed once before kickoff and once after it is played. "
            "College football games with no network yet or on ESPN+ and other streaming-only "
            "outlets are left out. Bowls and playoffs show up only once their 506 page is "
            "imported."
        )
    return subject, "\n".join(lines).rstrip("\n") + "\n"


def aa_cfb_weeks(paths: DataPaths) -> dict[str, str]:
    """AA post links the feed watch recorded, keyed season-week; empty when unreadable."""
    try:
        return dict(load_feed_state(paths).weeks)
    except VaultStateError:
        _LOG.warning("crew alerts: aa feed watch ledger unreadable; using the schedules page")
        return {}


# -- command ---------------------------------------------------------------------------------


def run_crew_alerts(
    paths: DataPaths,
    now: datetime,
    *,
    nfl_required: bool = False,
    reminders_file: Path | None = None,
    dry_run: bool = False,
    show: bool = False,
    commit: bool = True,
    load_settings: Callable[[], EmailSettings] = EmailSettings.from_env,
    send: Callable[[EmailSettings, str, str], None] = send_email,
) -> int:
    """Email new flagged games and new reminder lines; 0 on success.

    With `commit`, the vault lock is held from reading the ledger to the commit, so
    two runs can never send the same item. Prints counts only unless `show`
    (local use): the body names games and is never written to a job log.
    Delivery is at least once: a send that succeeds and a ledger that fails to
    commit (EXIT_LEDGER_NOT_SAVED) sends the same items again on the next run.
    """
    options = _Options(nfl_required, reminders_file, dry_run, show, load_settings, send)
    if commit and not dry_run:
        vault = VaultRepo(paths.vault)
        with vault.lock():
            return _run(paths, now, options, vault)
    return _run(paths, now, options, None)


@dataclass(frozen=True)
class _Options:
    nfl_required: bool
    reminders_file: Path | None
    dry_run: bool
    show: bool
    load_settings: Callable[[], EmailSettings]
    send: Callable[[EmailSettings, str, str], None]


def _run(paths: DataPaths, now: datetime, options: _Options, vault: VaultRepo | None) -> int:
    nfl_required, reminders_file = options.nfl_required, options.reminders_file
    dry_run, show = options.dry_run, options.show
    load_settings, send = options.load_settings, options.send
    missing = find_missing(paths, now, nfl_required=nfl_required)
    ledger = load_ledger(paths)
    new = new_alerts(missing, ledger)
    reminders = new_reminders(read_reminders(reminders_file), ledger)
    n_cfb = sum(1 for m in missing if m.league == "cfb")
    print(
        f"crew alerts: {len(missing)} games with no crew "
        f"(cfb {n_cfb}, nfl {len(missing) - n_cfb}), {len(new)} not emailed yet; "
        f"{len(reminders)} new reminders"
    )
    if not new and not reminders:
        return 0
    subject, body = compose(
        new, reminders, still_open=len(missing) - len(new), aa_weeks=aa_cfb_weeks(paths)
    )
    if show:
        print(subject)
        print(body)
    if dry_run:
        print("crew alerts: dry run, no email sent")
        return 0
    settings = load_settings()
    send(settings, subject, body)
    print(f"crew alerts: emailed {len(new)} games and {len(reminders)} reminders")
    keys = [m.alert_key for m in new] + [reminder_key(line) for line in reminders]
    write_ledger(paths, record_sent(ledger, keys, now))
    if vault is not None:
        try:
            vault.commit_batch(
                f"notify: crew alert email (games {len(new)}, reminders {len(reminders)})",
                paths=[LEDGER_REL],
            )
        except VaultCommitError:
            print("crew alerts: email sent but the ledger was not saved; it will be sent again")
            return EXIT_LEDGER_NOT_SAVED
    return 0
