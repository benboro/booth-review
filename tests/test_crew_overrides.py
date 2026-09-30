"""Crew override loader, apply post-pass, and gap rows (synthetic data only)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from booth_review.build.crew_overrides import (
    CREW_OVERRIDE_COLUMNS,
    CrewOverride,
    load_crew_overrides,
)
from booth_review.errors import ReferenceTableError

_SENTINEL = "ZZ-sentinel-cell"


def _row(**changes: object) -> dict[str, str]:
    base = {
        "cfbd_game_id": "1001",
        "network_id": "net-a",
        "crew_position": "0",
        "person_id": "p-a",
        "role": "pbp",
        "reason": "no-506-listing",
        "source_kind": "press-release",
        "source_name": "Example Press Room",
        "source_url": "https://example.com/pr/1",
    }
    base.update({key: str(value) for key, value in changes.items()})
    return base


def _write(
    tmp_path: Path, rows: list[dict[str, str]], header: tuple[str, ...] = CREW_OVERRIDE_COLUMNS
) -> Path:
    path = tmp_path / "crew_overrides.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(header), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return tmp_path


def _two_rows() -> list[dict[str, str]]:
    return [_row(), _row(crew_position=1, person_id="p-b", role="analyst")]


def test_columns_are_the_documented_header() -> None:
    assert ",".join(CREW_OVERRIDE_COLUMNS) == (
        "cfbd_game_id,network_id,crew_position,person_id,role,reason,"
        "source_kind,source_name,source_url"
    )


def test_valid_telecast_loads_as_one_override(tmp_path: Path) -> None:
    rows = list(reversed(_two_rows()))  # file order must not matter
    loaded = load_crew_overrides(_write(tmp_path, rows))
    assert loaded == {
        (1001, "net-a"): CrewOverride(
            cfbd_game_id=1001,
            network_id="net-a",
            people=(("p-a", "pbp"), ("p-b", "analyst")),
            reason="no-506-listing",
            source_kind="press-release",
            source_name="Example Press Room",
            source_url="https://example.com/pr/1",
        )
    }


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_crew_overrides(tmp_path) == {}


def test_extra_column_rejected(tmp_path: Path) -> None:
    reference = _write(tmp_path, [], header=(*CREW_OVERRIDE_COLUMNS, "extra"))
    with pytest.raises(ReferenceTableError):
        load_crew_overrides(reference)


def test_reordered_column_rejected(tmp_path: Path) -> None:
    header = (CREW_OVERRIDE_COLUMNS[1], CREW_OVERRIDE_COLUMNS[0], *CREW_OVERRIDE_COLUMNS[2:])
    with pytest.raises(ReferenceTableError):
        load_crew_overrides(_write(tmp_path, [], header=header))


_BAD_CELLS = [
    ("cfbd_game_id", _SENTINEL),
    ("crew_position", _SENTINEL),
    ("cfbd_game_id", "1_001"),
    ("cfbd_game_id", "\u0661\u0660\u0660\u0661"),  # Arabic-Indic digits for 1001
    ("cfbd_game_id", "+1001"),
    ("crew_position", "-1"),
    ("crew_position", "1_0"),
    ("crew_position", "\uff11"),  # fullwidth digit one
    ("network_id", f"Bad_{_SENTINEL}"),
    ("person_id", ""),
    ("role", _SENTINEL),
    ("role", "unknown"),
    ("reason", _SENTINEL),
    ("source_kind", _SENTINEL),
    ("source_url", ""),
    ("source_url", f"ftp://{_SENTINEL}"),
    ("source_url", f"https://example.com/{_SENTINEL} x"),
    ("source_url", "https://"),
    ("source_url", f"https:///{_SENTINEL}"),
    ("source_url", f"https://506sports.com/{_SENTINEL}"),
    ("source_url", f"https://www.506sports.com/{_SENTINEL}"),
    ("source_url", f"https://[{_SENTINEL}"),
    ("source_name", ""),
    ("source_name", _SENTINEL * 5),
    ("source_name", f"<b>{_SENTINEL}</b>"),
]


@pytest.mark.parametrize(("column", "value"), _BAD_CELLS)
def test_bad_cell_is_rejected_with_file_and_line_only(
    tmp_path: Path, column: str, value: str
) -> None:
    rows = _two_rows()
    rows[1][column] = value
    with pytest.raises(ReferenceTableError) as exc:
        load_crew_overrides(_write(tmp_path, rows))
    message = str(exc.value)
    assert "crew_overrides.csv: line" in message
    assert _SENTINEL not in message


@pytest.mark.parametrize(
    "url", ["https://506sports.com/wiki/x", "http://WWW.506Sports.com./wiki/x"]
)
def test_506_sports_source_is_rejected(tmp_path: Path, url: str) -> None:
    rows = _two_rows()
    for row in rows:
        row["source_url"] = url
    with pytest.raises(ReferenceTableError) as exc:
        load_crew_overrides(_write(tmp_path, rows))
    assert str(exc.value) == "crew_overrides.csv: line 2: source_url must not cite 506 Sports"


def test_lookalike_host_is_not_506_sports(tmp_path: Path) -> None:
    rows = _two_rows()
    for row in rows:
        row["source_url"] = "https://not506sports.com/pr/1"
    loaded = load_crew_overrides(_write(tmp_path, rows))
    assert loaded[(1001, "net-a")].source_url == "https://not506sports.com/pr/1"


def _sentinel_rows(**second: object) -> list[dict[str, str]]:
    first = _row(source_name=_SENTINEL[:20])
    return [first, _row(crew_position=1, person_id="p-b", role="analyst", **second)]


def test_duplicate_position_rejected(tmp_path: Path) -> None:
    rows = [_row(person_id=_SENTINEL), _row(person_id="p-b")]
    with pytest.raises(ReferenceTableError) as exc:
        load_crew_overrides(_write(tmp_path, rows))
    assert "crew_overrides.csv: line 3" in str(exc.value)
    assert _SENTINEL not in str(exc.value)


def test_same_person_twice_rejected(tmp_path: Path) -> None:
    rows = [_row(person_id=_SENTINEL), _row(crew_position=1, person_id=_SENTINEL, role="analyst")]
    with pytest.raises(ReferenceTableError) as exc:
        load_crew_overrides(_write(tmp_path, rows))
    assert "crew_overrides.csv: line" in str(exc.value)
    assert _SENTINEL not in str(exc.value)


@pytest.mark.parametrize(
    ("positions", "line"),
    [
        ((0, 2), 3),  # the gap is at the second row
        ((2, 1), 3),  # no position 0: the lowest position's row breaks the run
        ((0, 1, 3), 4),
    ],
)
def test_non_contiguous_positions_cite_the_breaking_row(
    tmp_path: Path, positions: tuple[int, ...], line: int
) -> None:
    rows = [
        _row(crew_position=position, person_id=f"p-{index}", role="analyst" if index else "pbp")
        for index, position in enumerate(positions)
    ]
    rows[0]["person_id"] = _SENTINEL
    with pytest.raises(ReferenceTableError) as exc:
        load_crew_overrides(_write(tmp_path, rows))
    assert str(exc.value) == (
        f"crew_overrides.csv: line {line}: crew_position must run contiguously from 0"
    )


@pytest.mark.parametrize(
    ("roles", "line"),
    [
        (("analyst", "analyst"), 2),  # no pbp: cite the telecast's first row
        (("analyst",), 2),
        (("pbp", "pbp"), 3),  # two pbp: cite the second
        (("pbp", "analyst", "pbp"), 4),
    ],
)
def test_telecast_must_have_exactly_one_pbp_row(
    tmp_path: Path, roles: tuple[str, ...], line: int
) -> None:
    rows = [
        _row(crew_position=index, person_id=f"p-{index}", role=role)
        for index, role in enumerate(roles)
    ]
    rows[0]["person_id"] = _SENTINEL
    with pytest.raises(ReferenceTableError) as exc:
        load_crew_overrides(_write(tmp_path, rows))
    assert str(exc.value) == (
        f"crew_overrides.csv: line {line}: each telecast must have exactly one pbp row"
    )


def test_pbp_need_not_be_first_position(tmp_path: Path) -> None:
    rows = [
        _row(role="analyst"),
        _row(crew_position=1, person_id="p-b", role="pbp"),
    ]
    loaded = load_crew_overrides(_write(tmp_path, rows))
    assert loaded[(1001, "net-a")].people == (("p-a", "analyst"), ("p-b", "pbp"))


def test_error_line_counts_blank_spacer_rows(tmp_path: Path) -> None:
    rows = _two_rows()
    rows[1]["source_url"] = f"https://506sports.com/{_SENTINEL}"
    rows[0]["source_url"] = rows[1]["source_url"]
    path = _write(tmp_path, rows) / "crew_overrides.csv"
    header, first, second = path.read_text(encoding="utf-8").splitlines()
    path.write_text(f"{header}\n\n\n{first}\n\n{second}\n", encoding="utf-8")
    with pytest.raises(ReferenceTableError) as exc:
        load_crew_overrides(tmp_path)
    assert str(exc.value) == "crew_overrides.csv: line 4: source_url must not cite 506 Sports"


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("reason", "correction"),
        ("source_kind", "school"),
        ("source_name", f"Other {_SENTINEL}"),
        ("source_url", f"https://example.com/{_SENTINEL}"),
    ],
)
def test_rows_of_one_telecast_must_agree_on_source(tmp_path: Path, column: str, value: str) -> None:
    rows = _two_rows()
    rows[1][column] = value
    with pytest.raises(ReferenceTableError) as exc:
        load_crew_overrides(_write(tmp_path, rows))
    assert "crew_overrides.csv: line" in str(exc.value)
    assert _SENTINEL not in str(exc.value)


# ---------------------------------------------------------------------------
# apply_crew_overrides and crew_gap_rows
# ---------------------------------------------------------------------------

import datetime as dt  # noqa: E402

import polars as pl  # noqa: E402

from booth_review.build.crew_overrides import (  # noqa: E402
    REVIEW_CREW_GAPS_COLUMNS,
    apply_crew_overrides,
    crew_gap_rows,
    unmatched_506_keys,
)
from booth_review.build.games import GAMES_SCHEMA  # noqa: E402
from booth_review.build.people_links import TELECAST_PEOPLE_SCHEMA  # noqa: E402
from booth_review.build.telecasts import TELECASTS_SCHEMA  # noqa: E402
from booth_review.errors import CrewOverrideError  # noqa: E402
from booth_review.people.registry import PeopleRegistry, Person  # noqa: E402
from booth_review.resolve.diagnose import UnmatchedRow  # noqa: E402
from booth_review.resolve.networks import NetworkRow, NetworkTable  # noqa: E402

_DATE = dt.date(2020, 1, 2)


def _registry(*ids: str) -> PeopleRegistry:
    return PeopleRegistry({pid: Person(pid, pid.upper(), (pid,), "unknown", None) for pid in ids})


def _tel(game_id: int, **changes: object) -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(TELECASTS_SCHEMA)
    row.update(
        telecast_id=f"{game_id}-net-a",
        game_id=game_id,
        season=2019,
        date_et=_DATE,
        network_id="net-a",
        feed_type="main",
        rated=True,
        rr_telecast_ids=["rr1", "rr2"],
        crew_matched=False,
        crew_patched=False,
        crew_network_mismatch=False,
        plotted=True,
    )
    row.update(changes)
    return row


def _tp(
    telecast_id: str, person_id: str, feed: str = "main", position: int = 0
) -> dict[str, object]:
    return {
        "telecast_id": telecast_id,
        "person_id": person_id,
        "role": "pbp",
        "feed_type": feed,
        "crew_position": position,
        "s506_pointer": "ptr",
        "source": "registered",
    }


def _frames(
    tels: list[dict[str, object]], people: list[dict[str, object]]
) -> tuple[pl.DataFrame, pl.DataFrame]:
    return (
        pl.DataFrame(tels, schema=TELECASTS_SCHEMA),
        pl.DataFrame(people, schema=TELECAST_PEOPLE_SCHEMA),
    )


def _override(game_id: int = 1001, reason: str = "no-506-listing", people=None) -> CrewOverride:
    return CrewOverride(
        game_id,
        "net-a",
        people or (("p-a", "pbp"), ("p-b", "analyst")),
        reason,
        "press-release",
        "Example Press Room",
        "https://example.com/pr/1",
    )


_COUNTS = {2019: {"rated_with_crew": 4, "records_with_crew": 9}}


def test_patch_on_telecast_without_506_crew() -> None:
    tels, people = _frames([_tel(1001)], [])
    before = tels.clone()
    counts_before = {2019: dict(_COUNTS[2019])}
    result = apply_crew_overrides(
        tels, people, {(1001, "net-a"): _override()}, _registry("p-a", "p-b"), counts_before
    )
    rows = result.telecast_people.to_dicts()
    assert [(r["person_id"], r["role"], r["crew_position"]) for r in rows] == [
        ("p-a", "pbp", 0),
        ("p-b", "analyst", 1),
    ]
    assert all(
        r["feed_type"] == "main" and r["s506_pointer"] is None and r["source"] == "crew_override"
        for r in rows
    )
    assert result.statuses == {"1001-net-a": "patched"}
    tel = result.telecasts.to_dicts()[0]
    assert tel["crew_matched"] is True
    assert tel["crew_patched"] is True
    assert tel["crew_source_url"] == "https://example.com/pr/1"
    assert tel["crew_source_label"] == "Example Press Room"
    assert result.season_counts[2019] == {"rated_with_crew": 5, "records_with_crew": 11}
    assert result.counts["patched"] == 1
    assert counts_before == {2019: {"rated_with_crew": 4, "records_with_crew": 9}}
    assert tels.equals(before)


def test_redundant_when_506_lists_same_people_and_alt_rows_kept() -> None:
    tels, people = _frames(
        [_tel(1001, crew_matched=True)],
        [
            _tp("1001-net-a", "p-a", position=0),
            _tp("1001-net-a", "p-b", position=1),
            _tp("1001-net-a", "p-x", feed="alt"),
        ],
    )
    result = apply_crew_overrides(
        tels, people, {(1001, "net-a"): _override()}, _registry("p-a", "p-b"), _COUNTS
    )
    assert result.statuses == {"1001-net-a": "redundant"}
    assert result.counts["redundant"] == 1
    assert result.counts["rows"] == 0
    assert result.season_counts == _COUNTS
    # 506 already lists this booth: its rows and 506 attribution stay untouched.
    assert result.telecast_people.equals(people)
    tel = result.telecasts.to_dicts()[0]
    assert tel["crew_matched"] is True
    assert tel["crew_patched"] is False
    assert tel["crew_source_url"] is None
    assert tel["crew_source_label"] is None


@pytest.mark.parametrize(
    ("reason", "status", "key"),
    [("no-506-crew", "differs", "differs"), ("correction", "correction", "corrections")],
)
def test_differing_506_crew_loses_to_override(reason: str, status: str, key: str) -> None:
    tels, people = _frames([_tel(1001, crew_matched=True)], [_tp("1001-net-a", "p-z")])
    result = apply_crew_overrides(
        tels, people, {(1001, "net-a"): _override(reason=reason)}, _registry("p-a", "p-b"), _COUNTS
    )
    assert result.statuses == {"1001-net-a": status}
    assert result.counts[key] == 1
    assert result.counts["patched"] == 0
    assert "p-z" not in result.telecast_people["person_id"].to_list()
    assert set(result.telecast_people["source"]) == {"crew_override"}
    assert result.season_counts == _COUNTS
    # 506 listed a crew, so this is not a patch; the shown crew still cites its source.
    tel = result.telecasts.to_dicts()[0]
    assert tel["crew_matched"] is True
    assert tel["crew_patched"] is False
    assert tel["crew_source_url"] == "https://example.com/pr/1"
    assert tel["crew_source_label"] == "Example Press Room"


def test_status_follows_the_pre_override_506_match() -> None:
    # 506 matched a crew but no main rows linked: not a patch, and no count bump.
    tels, people = _frames([_tel(1001, crew_matched=True)], [])
    result = apply_crew_overrides(
        tels, people, {(1001, "net-a"): _override()}, _registry("p-a", "p-b"), _COUNTS
    )
    assert result.statuses == {"1001-net-a": "differs"}
    assert result.season_counts == _COUNTS
    assert result.telecasts.to_dicts()[0]["crew_patched"] is False


def test_crew_matched_without_crew_patched_is_the_pre_override_506_match() -> None:
    tels, people = _frames(
        [
            _tel(1001),
            _tel(1002, telecast_id="1002-net-a", crew_matched=True),
            _tel(1003, telecast_id="1003-net-a", crew_matched=True),
            _tel(1004, telecast_id="1004-net-a", crew_matched=True),
        ],
        [
            _tp("1002-net-a", "p-a", position=0),
            _tp("1002-net-a", "p-b", position=1),
            _tp("1003-net-a", "p-z"),
            _tp("1004-net-a", "p-z"),
        ],
    )
    overrides = {
        (1001, "net-a"): _override(1001),
        (1002, "net-a"): _override(1002),
        (1003, "net-a"): _override(1003, reason="no-506-crew"),
        (1004, "net-a"): _override(1004, reason="correction"),
    }
    result = apply_crew_overrides(tels, people, overrides, _registry("p-a", "p-b"), _COUNTS)
    assert result.statuses == {
        "1001-net-a": "patched",
        "1002-net-a": "redundant",
        "1003-net-a": "differs",
        "1004-net-a": "correction",
    }
    out = result.telecasts.sort("telecast_id")
    assert out.select(pl.col("crew_matched") & ~pl.col("crew_patched")).to_series().to_list() == (
        tels.sort("telecast_id")["crew_matched"].to_list()
    )
    assert out["crew_patched"].to_list() == [True, False, False, False]
    assert out["crew_source_url"].is_null().to_list() == [False, True, False, False]


def test_unknown_person_is_a_count_only_failure() -> None:
    tels, people = _frames([_tel(1001)], [])
    override = _override(people=((_SENTINEL, "pbp"),))
    with pytest.raises(CrewOverrideError) as exc:
        apply_crew_overrides(tels, people, {(1001, "net-a"): override}, _registry("p-a"), _COUNTS)
    assert str(exc.value) == "crew_overrides.csv: 1 row(s) name an unknown person_id"


@pytest.mark.parametrize("plotted", [True, False])
def test_unplotted_or_missing_telecast_is_a_count_only_failure(plotted: bool) -> None:
    tels, people = _frames([_tel(2002, plotted=False)], [])
    key = (2002, "net-a") if not plotted else (9999, "net-a")
    override = _override(game_id=key[0])
    with pytest.raises(CrewOverrideError) as exc:
        apply_crew_overrides(tels, people, {key: override}, _registry("p-a", "p-b"), _COUNTS)
    assert str(exc.value) == "crew_overrides.csv: 2 row(s) name a telecast the build does not plot"


def test_no_overrides_returns_inputs_unchanged() -> None:
    tels, people = _frames([_tel(1001)], [_tp("1001-net-a", "p-a")])
    result = apply_crew_overrides(tels, people, {}, _registry("p-a"), _COUNTS)
    assert result.telecasts.equals(tels)
    assert result.telecast_people.equals(people)
    assert set(result.counts.values()) == {0}


def _games() -> pl.DataFrame:
    rows = []
    for game_id in (1, 2, 3, 4, 5, 6, 7, 8):
        row: dict[str, object] = dict.fromkeys(GAMES_SCHEMA)
        row.update(
            game_id=game_id,
            season=2019,
            date_et=_DATE,
            game_type="regular",
            away_team=_SENTINEL,
            home_team="Home",
        )
        rows.append(row)
    return pl.DataFrame(rows, schema=GAMES_SCHEMA)


def test_gap_rows_classify_every_plotted_crewless_main_telecast() -> None:
    tels, people = _frames(
        [
            _tel(1, s506_pointer="ptr"),
            _tel(2),
            _tel(3, date_et=dt.date(2020, 1, 3)),
            _tel(4),
            _tel(5, plotted=False),
            _tel(6, telecast_id="6-net-a-alt", feed_type="alt"),
            _tel(7, crew_matched=True),
            # Same date as an unmatched 506 listing, but that listing is on net-a.
            _tel(8, telecast_id="8-net-b", network_id="net-b", date_et=dt.date(2020, 1, 3)),
        ],
        [_tp("2-net-a", "p-x", feed="alt")],
    )
    rows = crew_gap_rows(tels, _games(), people, {}, {("2020-01-03", "net-a")})
    kinds = {row["cfbd_game_id"]: row["gap_kind"] for row in rows}
    assert kinds == {
        1: "no-506-crew",
        2: "main-crew-missing",
        3: "join-miss-suspect",
        4: "no-506-listing",
        8: "no-506-listing",
    }
    by_id = {row["cfbd_game_id"]: row for row in rows}
    assert by_id[2]["other_feed_crew"] is True
    assert by_id[4]["other_feed_crew"] is False
    assert all(row["override_status"] == "missing" for row in rows)
    assert all(tuple(row) == REVIEW_CREW_GAPS_COLUMNS for row in rows)


def test_gap_rows_carry_override_status_and_has_506_crew_lines() -> None:
    tels, people = _frames([_tel(1), _tel(7, crew_matched=True)], [])
    statuses = {"1-net-a": "patched", "7-net-a": "differs"}
    rows = crew_gap_rows(tels, _games(), people, statuses, set())
    assert [(r["cfbd_game_id"], r["gap_kind"], r["override_status"]) for r in rows] == [
        (1, "no-506-listing", "patched"),
        (7, "has-506-crew", "differs"),
    ]


def test_gap_rows_sorted_by_season_date_game_network() -> None:
    tels, people = _frames(
        [_tel(3, date_et=dt.date(2020, 1, 1)), _tel(2), _tel(1)],
        [],
    )
    rows = crew_gap_rows(tels, _games(), people, {}, set())
    assert [r["cfbd_game_id"] for r in rows] == [3, 1, 2]


def _unmatched(source: str, network_raw: str, date_et: str = "2020-01-03") -> UnmatchedRow:
    return UnmatchedRow(
        source=source,
        season=2019,
        pointer="ptr",
        date_et=date_et,
        away_raw=_SENTINEL,
        home_raw="Home",
        network_raw=network_raw,
        confidence="none",
        reason="none",
    )


def test_unmatched_506_keys_resolve_the_network_through_the_crosswalk() -> None:
    networks = NetworkTable(
        [
            NetworkRow(
                "Net A", "net-a", "Network A", "fam-a", "broadcast", "main", None, None, None
            ),
            NetworkRow(
                "NETA", "net-a", "Network A", "fam-a", "broadcast", "main", None, None, None
            ),
            NetworkRow("Net B", "net-b", "Network B", "fam-b", "cable", "main", None, None, None),
        ]
    )
    rows = [
        _unmatched("sports506", "NETA"),  # a variant spelling maps to net-a
        _unmatched("sports506", "Net B", date_et="2020-01-04"),
        _unmatched("sports506", _SENTINEL),  # unmapped network: no key, never a guess
        _unmatched("sports506", ""),
        _unmatched("ratingsref", "Net B"),  # only 506 listings count
    ]
    assert unmatched_506_keys(rows, networks) == {
        ("2020-01-03", "net-a"),
        ("2020-01-04", "net-b"),
    }
