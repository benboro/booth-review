"""Awful Announcing crews pass (Phase 27, AAC-03): loaders and the decision table.
Synthetic data only: invented teams, people and posts."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from booth_review.build.crew_aa import (
    CREW_AA_LABEL,
    CREW_AA_SOURCE,
    REVIEW_CREW_AA_DISAGREEMENT_COLUMNS,
    AaPage,
    CrewAaResult,
    apply_crew_aa,
    load_506_times,
    load_aa_pages,
)
from booth_review.build.crew_backup import CREW_BACKUP_LABEL, ScheduledCrew
from booth_review.build.people_links import PEOPLE_SCHEMA, TELECAST_PEOPLE_SCHEMA
from booth_review.build.telecasts import TELECASTS_SCHEMA
from booth_review.config import DataPaths
from booth_review.people.registry import PeopleRegistry, Person
from booth_review.people.roles import Role
from booth_review.resolve.games import GameIndex
from booth_review.resolve.networks import NetworkRow, NetworkTable
from booth_review.resolve.teams import TeamResolver
from booth_review.sources.aa.crews import AaBooth, ParsedCrews
from booth_review.sources.cfbd.parser import CfbdGame

FIXTURE = Path(__file__).parent / "fixtures" / "aa" / "schedule_synthetic.html"
REL = "aa/crews/2026/wk-10.html"


def _paths(tmp_path: Path) -> DataPaths:
    paths = DataPaths(vault=tmp_path)
    paths.raw.mkdir(parents=True)
    return paths


def _manifest(paths: DataPaths, *lines: dict[str, object]) -> None:
    paths.manifest.parent.mkdir(parents=True, exist_ok=True)
    paths.manifest.write_text("\n".join(json.dumps(line) for line in lines) + "\n")


def _save(paths: DataPaths, html: str, rel: str = REL) -> None:
    target = paths.raw / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")


def _line(rel: str, status: int, fetched_at: str, **extra: object) -> dict[str, object]:
    return {"source": "aa", "path": rel, "status": status, "fetched_at": fetched_at, **extra}


def test_schema_has_crew_aa_boolean() -> None:
    assert "crew_aa" in TELECASTS_SCHEMA


def test_scheduled_crew_label_defaults_to_espn_and_can_be_overridden() -> None:
    assert ScheduledCrew((), "u").label == CREW_BACKUP_LABEL == "ESPN Press Room"
    assert ScheduledCrew((), "u", label="Awful Announcing").label == "Awful Announcing"


def test_modified_meta_is_the_page_time(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _save(paths, FIXTURE.read_text(encoding="utf-8"))
    _manifest(paths, _line(REL, 200, "2026-11-06T01:00:00Z"))
    loaded = load_aa_pages(paths)
    assert len(loaded.pages) == 1
    page = loaded.pages[0]
    assert page.aa_time == datetime(2026, 11, 5, 18, 30, tzinfo=UTC)
    assert page.aa_time_source == "modified"
    assert not loaded.rejected


def test_undated_page_uses_last_200_fetch_not_a_304(tmp_path: Path) -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    html = "\n".join(
        ln for ln in html.splitlines() if "modified_time" not in ln and "dateModified" not in ln
    )
    paths = _paths(tmp_path)
    _save(paths, html)
    _manifest(
        paths,
        _line(REL, 200, "2026-11-04T10:00:00Z"),
        _line(REL, 200, "2026-11-05T11:00:00Z"),
        _line(REL, 304, "2026-11-06T12:00:00Z"),
    )
    page = load_aa_pages(paths).pages[0]
    assert page.aa_time == datetime(2026, 11, 5, 11, 0, tzinfo=UTC)
    assert page.aa_time_source == "fetched"


def test_undated_page_without_manifest_has_no_time(tmp_path: Path) -> None:
    html = "\n".join(
        ln
        for ln in FIXTURE.read_text(encoding="utf-8").splitlines()
        if "modified_time" not in ln and "dateModified" not in ln
    )
    paths = _paths(tmp_path)
    _save(paths, html)
    page = load_aa_pages(paths).pages[0]
    assert page.aa_time is None
    assert page.aa_time_source == "none"


def test_bad_pages_are_rejected_not_loaded(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _save(paths, "<html><body>nothing</body></html>", "aa/crews/2026/wk-01.html")
    off = FIXTURE.read_text(encoding="utf-8").replace("awfulannouncing.com", "example.org")
    _save(paths, off, "aa/crews/2026/wk-02.html")
    nobody = FIXTURE.read_text(encoding="utf-8").replace("entry-content", "other")
    _save(paths, nobody, "aa/crews/2026/wk-03.html")
    loaded = load_aa_pages(paths)
    assert loaded.pages == []
    assert sorted((r.path, r.reason) for r in loaded.rejected) == [
        ("aa/crews/2026/wk-01.html", "no_canonical_url"),
        ("aa/crews/2026/wk-02.html", "off_host_url"),
        ("aa/crews/2026/wk-03.html", "parse_error"),
    ]


def test_only_2026_is_read(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _save(paths, FIXTURE.read_text(encoding="utf-8"), "aa/crews/2025/wk-10.html")
    assert load_aa_pages(paths).pages == []


def test_506_times_prefer_saved_at_and_normalise_labels(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _manifest(
        paths,
        {
            "source": "sports506",
            "path": "sports506/2026/wk-09.html",
            "status": 200,
            "fetched_at": "2026-11-02T00:00:00Z",
            "saved_at": "2026-11-01T09:00:00Z",
        },
        {
            "source": "sports506",
            "path": "sports506/2026/wk-10.html",
            "status": 200,
            "fetched_at": "2026-11-02T08:00:00Z",
        },
        {
            "source": "sports506",
            "path": "sports506/2026/wk-B.html",
            "status": 200,
            "fetched_at": "2026-12-20T08:00:00Z",
        },
    )
    times = load_506_times(paths)
    assert times[(2026, "9")] == datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
    assert times[(2026, "10")] == datetime(2026, 11, 2, 8, 0, tzinfo=UTC)
    assert times[(2026, "B")] == datetime(2026, 12, 20, 8, 0, tzinfo=UTC)


def test_missing_vault_pieces_are_empty(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    assert load_aa_pages(paths).pages == []
    assert load_506_times(paths) == {}


# -- The pass -----------------------------------------------------------------------------------

SEASON = 2026
TEAMS = {1: "Silverlake", 2: "Northfield", 3: "Riverbend", 4: "Lakeshore"}
URL = "https://awfulannouncing.com/college-football/invented-schedule.html"
PEOPLE_CSV = {
    "avery-lane": ("Avery Lane", "pbp"),
    "morgan-pike": ("Morgan Pike", "analyst"),
    "quinn-harrow": ("Quinn Harrow", "analyst"),
    "blair-tolley": ("Blair Tolley", "pbp"),
}
T_NEW = datetime(2026, 11, 5, 18, 0, tzinfo=UTC)
T_OLD = datetime(2026, 11, 2, 18, 0, tzinfo=UTC)


def _game(game_id: int, home: int, away: int) -> CfbdGame:
    return CfbdGame(
        id=game_id,
        season=SEASON,
        week=10,
        season_type="regular",
        start_date=datetime(SEASON, 11, 7, 20, 0, tzinfo=UTC),
        start_time_tbd=False,
        completed=False,
        neutral_site=False,
        conference_game=True,
        venue="Test Field",
        home_id=home,
        home_team=TEAMS[home],
        home_classification="fbs",
        home_conference="Test Conference",
        home_points=None,
        away_id=away,
        away_team=TEAMS[away],
        away_classification="fbs",
        away_conference="Test Conference",
        away_points=None,
        excitement_index=None,
        notes=None,
    )


GAMES = [_game(100, 2, 1), _game(101, 4, 3)]


def _networks() -> NetworkTable:
    def row(variant: str, network_id: str) -> NetworkRow:
        return NetworkRow(
            variant=variant,
            network_id=network_id,
            display_name=variant,
            family="disney",
            tier="cable",
            feed_type="main",
            season_from=None,
            season_to=None,
            priority=None,
        )

    return NetworkTable([row("ESPN", "espn"), row("ABC", "abc")])


def _registry() -> PeopleRegistry:
    return PeopleRegistry(
        {
            pid: Person(pid, name, (name,), role, None)  # type: ignore[arg-type]
            for pid, (name, role) in PEOPLE_CSV.items()
        }
    )


def _people_frame() -> pl.DataFrame:
    rows: list[dict[str, object]] = [
        {
            "person_id": pid,
            "canonical_name": name,
            "variants": [name],
            "usual_role": role,
            "registered": True,
        }
        for pid, (name, role) in PEOPLE_CSV.items()
    ]
    return pl.DataFrame(rows, schema=PEOPLE_SCHEMA).sort("person_id")


def _tel(game_id: int = 100, network_id: str = "espn", **changes: object) -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(TELECASTS_SCHEMA)
    row.update(
        telecast_id=f"{game_id}-{network_id}",
        game_id=game_id,
        season=SEASON,
        date_et=date(SEASON, 11, 7),
        network_id=network_id,
        feed_type="main",
        rated=True,
        rr_telecast_ids=["rr1", "rr2"],
        crew_matched=False,
        crew_patched=False,
        crew_backup=False,
        crew_aa=False,
        crew_network_mismatch=False,
        plotted=True,
        s506_week="10",
    )
    row.update(changes)
    return row


def _tp(telecast_id: str, person_id: str, position: int = 0, **changes: object) -> dict[str, Any]:
    row: dict[str, Any] = {
        "telecast_id": telecast_id,
        "person_id": person_id,
        "role": "pbp" if position == 0 else "analyst",
        "feed_type": "main",
        "crew_position": position,
        "s506_pointer": "10:1",
        "source": "registered",
    }
    row.update(changes)
    return row


def _booth(
    people: tuple[tuple[str, Role], ...],
    *,
    away: str = "Silverlake",
    home: str = "Northfield",
    network: str = "ESPN",
    url: str = URL,
    pointer: str = "invented:1",
) -> AaBooth:
    return AaBooth(
        season=SEASON,
        date_et=date(SEASON, 11, 7),
        kickoff="Noon",
        away_raw=away,
        home_raw=home,
        network_raw=network,
        people=people,
        source_url=url,
        pointer=pointer,
    )


def _page(booths: list[AaBooth], time: datetime | None = T_NEW, source: str = "modified") -> AaPage:
    parsed = ParsedCrews(
        url=URL, modified=time, published=None, booths=booths, unparsed=0, tbd=0, no_pbp=0
    )
    return AaPage(
        path="aa/crews/2026/wk-10.html", parsed=parsed, aa_time=time, aa_time_source=source
    )


PBP_ANALYST: tuple[tuple[str, Role], ...] = (("Avery Lane", "pbp"), ("Morgan Pike", "analyst"))
_COUNTS = {SEASON: {"rated_with_crew": 4, "records_with_crew": 9}}


def _run(
    tels: list[dict[str, object]],
    pages: list[AaPage],
    tp_rows: list[dict[str, Any]] | None = None,
    *,
    s506: dict[tuple[int, str], datetime] | None = None,
    season_counts: dict[int, dict[str, int]] | None = None,
    scheduled_networks: dict[int, str | None] | None = None,
) -> CrewAaResult:
    return apply_crew_aa(
        pl.DataFrame(tels, schema=TELECASTS_SCHEMA),
        pl.DataFrame(tp_rows or [], schema=TELECAST_PEOPLE_SCHEMA),
        _people_frame(),
        pages,
        resolver=TeamResolver({SEASON: GAMES}, []),
        index=GameIndex(GAMES),
        overrides={},
        networks=_networks(),
        registry=_registry(),
        season_counts=season_counts if season_counts is not None else _COUNTS,
        s506_times=s506 if s506 is not None else {(SEASON, "10"): T_OLD},
        current_season=SEASON,
        scheduled_networks=scheduled_networks,
    )


def _crew_of(result: CrewAaResult, telecast_id: str = "100-espn") -> list[tuple[str, str]]:
    frame = result.telecast_people.filter(pl.col("telecast_id") == telecast_id).sort(
        "crew_position"
    )
    return [(r["person_id"], r["role"]) for r in frame.to_dicts()]


def test_fills_a_crewless_rated_telecast_with_the_whole_booth() -> None:
    before = {SEASON: dict(_COUNTS[SEASON])}
    result = _run([_tel()], [_page([_booth(PBP_ANALYST)])], season_counts=before)
    rows = result.telecast_people.to_dicts()
    assert [(r["person_id"], r["role"], r["crew_position"]) for r in rows] == [
        ("avery-lane", "pbp", 0),
        ("morgan-pike", "analyst", 1),
    ]
    assert all(r["source"] == CREW_AA_SOURCE and r["s506_pointer"] is None for r in rows)
    tel = result.telecasts.to_dicts()[0]
    assert tel["crew_aa"] is True and tel["crew_matched"] is True
    assert tel["crew_patched"] is False and tel["crew_backup"] is False
    assert tel["crew_source_label"] == CREW_AA_LABEL == "Awful Announcing"
    assert tel["crew_source_url"] == URL
    assert result.statuses == {"100-espn": "filled"}
    assert result.filled_ids == {"100-espn"}
    assert result.season_counts[SEASON]["rated_with_crew"] == 5
    assert result.season_counts[SEASON]["records_with_crew"] == 11
    assert before == _COUNTS  # input not mutated
    assert result.counts["filled"] == 1 and result.counts["rows"] == 2


def test_fills_an_unrated_unplotted_telecast_without_touching_rated_counts() -> None:
    result = _run([_tel(rated=False, plotted=False)], [_page([_booth(PBP_ANALYST)])])
    assert result.statuses == {"100-espn": "filled"}
    assert result.telecasts.to_dicts()[0]["crew_aa"] is True
    assert result.season_counts == _COUNTS


def test_same_people_keep_506_and_count_an_agreement() -> None:
    tels = [_tel(crew_matched=True, crew_source_label="506 Sports")]
    tp = [_tp("100-espn", "avery-lane", 0), _tp("100-espn", "morgan-pike", 1)]
    result = _run(tels, [_page([_booth(PBP_ANALYST)])], tp)
    tel = result.telecasts.to_dicts()[0]
    assert tel["crew_aa"] is False and tel["crew_source_label"] == "506 Sports"
    assert result.statuses == {"100-espn": "agrees"}
    assert result.counts["agreements"] == 1 and result.review_rows == []
    assert result.telecast_people.height == 2


def test_strict_superset_wins_even_when_506_is_newer() -> None:
    tels = [_tel(crew_matched=True)]
    tp = [_tp("100-espn", "avery-lane", 0)]
    result = _run(
        tels,
        [_page([_booth(PBP_ANALYST)], time=T_OLD)],
        tp,
        s506={(SEASON, "10"): T_NEW},
    )
    assert result.statuses == {"100-espn": "superset"}
    assert result.won_ids == {"100-espn"}
    assert _crew_of(result) == [("avery-lane", "pbp"), ("morgan-pike", "analyst")]
    tel = result.telecasts.to_dicts()[0]
    assert tel["crew_aa"] is True and tel["crew_source_label"] == CREW_AA_LABEL
    assert tel["crew_patched"] is False
    (review,) = result.review_rows
    assert tuple(review) == REVIEW_CREW_AA_DISAGREEMENT_COLUMNS
    assert review["winner"] == "aa" and review["relation"] == "superset"
    assert result.counts["superset"] == 1
    assert result.season_counts == _COUNTS  # replacement is not a fill


def test_differing_people_newer_aa_replaces_the_whole_booth() -> None:
    tels = [_tel(crew_matched=True)]
    tp = [_tp("100-espn", "blair-tolley", 0), _tp("100-espn", "quinn-harrow", 1)]
    result = _run(tels, [_page([_booth(PBP_ANALYST)])], tp)
    assert result.statuses == {"100-espn": "aa_won"}
    assert _crew_of(result) == [("avery-lane", "pbp"), ("morgan-pike", "analyst")]
    tel = result.telecasts.to_dicts()[0]
    assert tel["crew_matched"] is True and tel["crew_aa"] is True
    (review,) = result.review_rows
    assert review["winner"] == "aa" and review["relation"] == "differs"
    assert review["aa_time_source"] == "modified"
    assert review["aa_time"] == "2026-11-05T18:00:00Z"
    assert review["s506_time"] == "2026-11-02T18:00:00Z"
    assert review["s506_person_ids"] == "blair-tolley|quinn-harrow"
    assert result.counts["aa_won"] == 1 and result.counts["disagreements"] == 1


@pytest.mark.parametrize(
    "s506_time",
    [T_NEW, datetime(2026, 11, 6, 0, 0, tzinfo=UTC), None],
    ids=["tie", "506-newer", "no-506-time"],
)
def test_differing_people_506_keeps_the_crew(s506_time: datetime | None) -> None:
    tels = [_tel(crew_matched=True)]
    tp = [_tp("100-espn", "blair-tolley", 0), _tp("100-espn", "quinn-harrow", 1)]
    s506 = {} if s506_time is None else {(SEASON, "10"): s506_time}
    result = _run(tels, [_page([_booth(PBP_ANALYST)])], tp, s506=s506)
    assert result.statuses == {"100-espn": "s506_won"}
    assert _crew_of(result) == [("blair-tolley", "pbp"), ("quinn-harrow", "analyst")]
    assert result.telecasts.to_dicts()[0]["crew_aa"] is False
    (review,) = result.review_rows
    assert review["winner"] == "506"
    assert review["s506_time"] == (
        "" if s506_time is None else s506_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    assert result.counts["s506_won"] == 1


def test_undated_page_with_newer_fetch_time_wins_and_says_so() -> None:
    tels = [_tel(crew_matched=True)]
    tp = [_tp("100-espn", "blair-tolley", 0), _tp("100-espn", "quinn-harrow", 1)]
    page = _page([_booth(PBP_ANALYST)], time=T_NEW, source="fetched")
    result = _run(tels, [page], tp)
    assert result.statuses == {"100-espn": "aa_won"}
    assert result.review_rows[0]["aa_time_source"] == "fetched"
    assert result.counts["undated_pages"] == 1


def test_override_telecast_is_never_changed() -> None:
    tels = [_tel(crew_matched=True, crew_patched=True)]
    tp = [_tp("100-espn", "blair-tolley", 0, source="crew_override")]
    result = _run(tels, [_page([_booth(PBP_ANALYST)])], tp)
    assert result.statuses == {"100-espn": "override"}
    assert result.counts["kept_override"] == 1 and result.review_rows == []
    assert _crew_of(result) == [("blair-tolley", "pbp")]
    assert result.telecasts.to_dicts()[0]["crew_aa"] is False


def test_override_rows_alone_also_protect_a_telecast() -> None:
    tp = [_tp("100-espn", "blair-tolley", 0, source="crew_override")]
    result = _run([_tel(crew_matched=False)], [_page([_booth(PBP_ANALYST)])], tp)
    assert result.statuses == {"100-espn": "override"}


def test_redundant_override_telecast_is_never_changed() -> None:
    """Phase 27 review CR-01: a `redundant` override (it equals 506's crew) leaves
    no marker on the frames, so the caller passes its id; AA never replaces it."""
    tels = [_tel(crew_matched=True, crew_source_label="506 Sports")]
    tp = [_tp("100-espn", "avery-lane", 0)]
    for booth in (PBP_ANALYST, (("Blair Tolley", "pbp"),)):
        result = apply_crew_aa(
            pl.DataFrame(tels, schema=TELECASTS_SCHEMA),
            pl.DataFrame(tp, schema=TELECAST_PEOPLE_SCHEMA),
            _people_frame(),
            [_page([_booth(booth)])],
            resolver=TeamResolver({SEASON: GAMES}, []),
            index=GameIndex(GAMES),
            overrides={},
            networks=_networks(),
            registry=_registry(),
            season_counts=_COUNTS,
            s506_times={(SEASON, "10"): T_OLD},
            current_season=SEASON,
            override_telecast_ids=frozenset({"100-espn"}),
        )
        assert result.statuses == {"100-espn": "override"}
        assert result.counts["kept_override"] == 1 and result.review_rows == []
        assert _crew_of(result) == [("avery-lane", "pbp")]
        tel = result.telecasts.to_dicts()[0]
        assert tel["crew_aa"] is False and tel["crew_source_label"] == "506 Sports"


def test_booth_on_another_network_is_skipped_and_counted() -> None:
    result = _run([_tel()], [_page([_booth(PBP_ANALYST, network="ABC")])])
    assert result.counts["network_mismatch"] == 1 and result.counts["filled"] == 0
    assert result.statuses == {}
    assert len(result.unmatched_rows) == 1


def test_unmatched_game_is_counted_with_a_reason() -> None:
    result = _run([_tel()], [_page([_booth(PBP_ANALYST, away="Nowhere State")])])
    assert result.counts["unmatched"] == 1
    assert len(result.unmatched_rows) == 1 and result.unmatched_rows[0].reason
    assert result.statuses == {}


def test_unknown_name_becomes_a_provisional_person() -> None:
    booth = _booth((("Avery Lane", "pbp"), ("Zed Zimmer", "analyst")))
    result = _run([_tel()], [_page([booth])])
    assert result.counts["provisional_persons"] == 1
    (new,) = result.new_name_rows
    assert new["name"] == "Zed Zimmer"
    assert new["provisional_id"] in set(result.people["person_id"].to_list())
    assert len(_crew_of(result)) == 2


def test_off_host_url_is_never_credited() -> None:
    booth = _booth(PBP_ANALYST, url="https://example.org/post/")
    result = _run([_tel()], [_page([booth])])
    assert result.counts["bad_url"] == 1 and result.statuses == {}
    assert result.telecasts.to_dicts()[0]["crew_aa"] is False


def test_scheduled_game_without_a_telecast_takes_the_booth() -> None:
    result = _run([], [_page([_booth(PBP_ANALYST)])], scheduled_networks={100: "espn"})
    crew = result.scheduled_crews[100]
    assert crew.label == CREW_AA_LABEL and crew.source_url == URL
    assert crew.entries == (("avery-lane", "pbp"), ("morgan-pike", "analyst"))
    assert result.counts["scheduled_filled"] == 1


def test_scheduled_game_on_another_network_is_not_filled() -> None:
    result = _run([], [_page([_booth(PBP_ANALYST)])], scheduled_networks={100: "abc"})
    assert result.scheduled_crews == {}
    assert result.counts["network_mismatch"] == 1


def test_two_pages_for_one_telecast_use_the_later_page() -> None:
    old = _page([_booth(PBP_ANALYST)], time=T_OLD)
    new = _page([_booth((("Blair Tolley", "pbp"), ("Quinn Harrow", "analyst")))], time=T_NEW)
    result = _run([_tel()], [old, new])
    assert _crew_of(result) == [("blair-tolley", "pbp"), ("quinn-harrow", "analyst")]
    assert result.counts["page_conflicts"] == 1


def test_no_pages_returns_inputs_unchanged() -> None:
    result = _run([_tel()], [])
    assert result.statuses == {} and result.telecast_people.height == 0
    assert result.telecasts.equals(pl.DataFrame([_tel()], schema=TELECASTS_SCHEMA))


def test_page_counts_are_summed() -> None:
    page = _page([_booth(PBP_ANALYST)])
    parsed = ParsedCrews(
        url=URL, modified=T_NEW, published=None, booths=[], unparsed=2, tbd=3, no_pbp=1
    )
    other = AaPage(path="x", parsed=parsed, aa_time=T_NEW, aa_time_source="modified")
    result = _run([_tel()], [page, other])
    assert (result.counts["unparsed_lines"], result.counts["tbd"], result.counts["no_pbp"]) == (
        2,
        3,
        1,
    )


def test_inputs_are_not_mutated_and_review_rows_hold_only_their_columns() -> None:
    tels = [_tel(crew_matched=True)]
    tp = [_tp("100-espn", "blair-tolley", 0)]
    tel_frame = pl.DataFrame(tels, schema=TELECASTS_SCHEMA)
    tp_frame = pl.DataFrame(tp, schema=TELECAST_PEOPLE_SCHEMA)
    result = apply_crew_aa(
        tel_frame,
        tp_frame,
        _people_frame(),
        [_page([_booth(PBP_ANALYST)])],
        resolver=TeamResolver({SEASON: GAMES}, []),
        index=GameIndex(GAMES),
        overrides={},
        networks=_networks(),
        registry=_registry(),
        season_counts=_COUNTS,
        s506_times={},
    )
    assert tel_frame.equals(pl.DataFrame(tels, schema=TELECASTS_SCHEMA))
    assert tp_frame.equals(pl.DataFrame(tp, schema=TELECAST_PEOPLE_SCHEMA))
    assert all(tuple(r) == REVIEW_CREW_AA_DISAGREEMENT_COLUMNS for r in result.review_rows)
