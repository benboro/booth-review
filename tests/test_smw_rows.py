from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from booth_review.errors import ReferenceTableError
from booth_review.sources.second_rows import host_matches
from booth_review.sources.smw.chart_order import ChartOrderEntry
from booth_review.sources.smw.rows import (
    PASS_COLUMNS,
    ROWS_COLUMNS,
    away_team_text,
    classify_row,
    load_pass_csv,
    load_rows_csv,
    parse_chart_date,
    parse_viewers,
    smw_second_rows,
)

HEADER = ",".join(PASS_COLUMNS)
ROWS_HEADER = ",".join(ROWS_COLUMNS)


def row(**kw: str) -> dict[str, str]:
    base = dict.fromkeys(PASS_COLUMNS, "")
    base.update(away="Silverlake", home="Northfield", network="ABC", viewers="5.83M")
    base.update(kw)
    return base


@pytest.mark.parametrize(
    ("printed", "expected"),
    [("5.83M", 5830000), ("904K", 904000), ("7.863M", 7863000), (" 1.2m ", 1200000)],
)
def test_parse_viewers(printed: str, expected: int) -> None:
    assert parse_viewers(printed) == expected


@pytest.mark.parametrize("printed", ["n/a", "", "-", "5.2f", "123"])
def test_parse_viewers_none(printed: str) -> None:
    assert parse_viewers(printed) is None


def test_parse_chart_date() -> None:
    assert parse_chart_date("10/1", 2022) == date(2022, 10, 1)
    assert parse_chart_date("1/9", 2022) == date(2023, 1, 9)
    assert parse_chart_date("13/40", 2022) is None
    assert parse_chart_date("", 2022) is None


@pytest.mark.parametrize(
    ("kw", "kind"),
    [
        ({"network": "ABC & ESPN2"}, "simulcast"),
        ({"network": "ABC, ESPN2"}, "simulcast"),
        ({"network": "ABC, ESPN2", "viewers": "2.10M"}, "simulcast"),
        ({"network": "ABC + ESPNU"}, "simulcast"),
        ({"network": "ABC + ESPNU", "viewers": "2.10M"}, "simulcast"),
        ({"network": "ESPN+"}, "figure"),
        ({"network": "Bally+ Ariz"}, "figure"),
        ({"network": "ESPN MEGA"}, "multi_feed"),
        ({"home": "Regional action"}, "regional"),
        ({"away": "Silverlake or Riverbend"}, "regional"),
        ({"away": "Silverlake Northfield", "note": "multi-game cell"}, "regional"),
        ({"away": "Silverlake Northfield", "note": "Multi-game cell"}, "regional"),
        ({"away": "Gridiron Awards Show", "home": ""}, "non_game"),
        ({"away": '"Saturday Studio Hour"', "home": " ", "viewers": "n/a"}, "non_game"),
        ({"away": "Silverlake / Northfield", "home": ""}, "figure"),
        ({"away": "Silverlake vs Northfield", "home": ""}, "figure"),
        ({"away": "Silverlake / Northfield or Riverbend / Eastport", "home": ""}, "regional"),
        ({"away": "Silverlake Northfield", "home": "", "note": "multi-game cell"}, "regional"),
        ({"note": "Not Nielsen"}, "non_nielsen"),
        ({"viewers": "n/a"}, "no_figure"),
        ({"viewers": ""}, "no_figure"),
        ({"viewers": "not disclosed"}, "no_figure"),
        ({"viewers": "-"}, "no_figure"),
        ({"viewers": "5.2f"}, "unknown_suffix"),
        ({}, "figure"),
        ({"network": "ABC & ESPN2", "viewers": "n/a"}, "simulcast"),
    ],
)
def test_classify_row(kw: dict[str, str], kind: str) -> None:
    assert classify_row(row(**kw)) == kind


def test_load_pass_csv_ok(tmp_path: Path) -> None:
    p = tmp_path / "week5cfb.csv"
    p.write_text(f"{HEADER}\nweek5cfb.png,1,Sat,10/1,,Silverlake,Northfield,ABC,2.1,5.83M,\n")
    assert load_pass_csv(p)[0]["viewers"] == "5.83M"


def test_wrong_header(tmp_path: Path) -> None:
    p = tmp_path / "a.csv"
    p.write_text("chart_file,row\n")
    with pytest.raises(ReferenceTableError, match="header"):
        load_pass_csv(p)


@pytest.mark.parametrize("bad_row", ["x", "0", "-1"])
def test_bad_row_number(tmp_path: Path, bad_row: str) -> None:
    p = tmp_path / "a.csv"
    p.write_text(f"{HEADER}\nweek5cfb.png,{bad_row},,,,Zephyrville,,,,,\n")
    with pytest.raises(ReferenceTableError, match="line 2") as exc:
        load_pass_csv(p)
    assert "Zephyrville" not in str(exc.value)


def test_duplicate_row(tmp_path: Path) -> None:
    p = tmp_path / "a.csv"
    p.write_text(f"{HEADER}\nw.png,1,,,,Zephyrville,,,,,\nw.png,1,,,,,,,,,\n")
    with pytest.raises(ReferenceTableError, match="line 3") as exc:
        load_pass_csv(p)
    assert "Zephyrville" not in str(exc.value)


def test_bad_chart_file(tmp_path: Path) -> None:
    p = tmp_path / "a.csv"
    p.write_text(f"{HEADER}\n../w.png,1,,,,,,,,,\n")
    with pytest.raises(ReferenceTableError, match="line 2"):
        load_pass_csv(p)


def test_superseded_by_must_exist(tmp_path: Path) -> None:
    p = tmp_path / "rows.csv"
    p.write_text(f"{ROWS_HEADER}\nw.png,1,,,,,,,,,,gone.png:9\n")
    with pytest.raises(ReferenceTableError, match="line 2"):
        load_rows_csv(p)


def test_smw_second_rows() -> None:
    order = {
        "w.png": ChartOrderEntry("w.png", "", "2022-10", 0, "weekly", 2),
    }
    rows = [
        {**row(date="10/1", row="1", chart_file="w.png"), "superseded_by": ""},
        {**row(row="2", chart_file="w.png", network="ABC & ESPN2"), "superseded_by": "w.png:1"},
    ]
    out = smw_second_rows(
        rows, order, season=2022, source_url="https://www.sportsmediawatch.com/x/"
    )
    assert out[0].source == "smw"
    assert out[0].pointer == "w.png:1"
    assert out[0].viewers == 5830000
    assert out[0].date_et == date(2022, 10, 1)
    assert out[0].rank == 2
    assert out[0].superseded is False
    assert out[1].viewers is None
    assert out[1].kind == "simulcast"
    assert out[1].superseded is True
    assert (out[0].superseded_by, out[1].superseded_by) == ("", "w.png:1")


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("Lakeshore Bowl: Silverlake", "Silverlake"),
        ("CONF Champ: NORTH ST", "NORTH ST"),
        ("Silverlake", "Silverlake"),
        ("Regional action:", "Regional action:"),
        ("Silverlake / Northfield", "Silverlake / Northfield"),
    ],
)
def test_away_team_text(printed: str, expected: str) -> None:
    assert away_team_text(printed) == expected


def test_smw_second_rows_strips_game_name_prefix_from_away() -> None:
    order = {"b.png": ChartOrderEntry("b.png", "", "2022-12", 0, "postseason", 2)}
    rows = [
        {**row(row="1", chart_file="b.png", away="Lakeshore Bowl: Silverlake"), "superseded_by": ""}
    ]
    out = smw_second_rows(rows, order, season=2022, source_url="u")
    assert out[0].away_raw == "Silverlake"
    assert out[0].home_raw == "Northfield"


def test_smw_second_rows_missing_chart() -> None:
    with pytest.raises(ReferenceTableError, match="1 chart"):
        smw_second_rows([row(chart_file="z.png")], {}, season=2022, source_url="u")


def test_host_matches() -> None:
    assert host_matches("smw", "https://www.sportsmediawatch.com/a")
    assert not host_matches("smw", "http://www.sportsmediawatch.com/a")
    assert not host_matches("smw", "https://evilsportsmediawatch.com/a")
