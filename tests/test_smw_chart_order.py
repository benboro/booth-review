from __future__ import annotations

from pathlib import Path

import pytest

from booth_review.errors import ReferenceTableError
from booth_review.sources.smw.chart_order import (
    chart_kind_for,
    identify_season_page,
    load_chart_order_csv,
    parse_chart_order,
    write_chart_order_csv,
)

PAGE = (Path(__file__).parent / "fixtures" / "smw" / "season-page.synthetic.html").read_text(
    encoding="utf-8"
)
LOCAL = ["champweekcfb.png", "week5cfb.png", "week2cfb-1.png"]


def test_identify_season_page() -> None:
    assert identify_season_page(PAGE) == (
        2022,
        "https://www.sportsmediawatch.com/college-football-tv-ratings/2022-season/",
    )


def test_identify_rejects_missing_canonical_and_year_mismatch() -> None:
    assert identify_season_page("<title>2022 college football TV ratings</title>") is None
    assert identify_season_page(PAGE.replace("<title>2022", "<title>2021")) is None


def test_ranks_oldest_first_with_suffixes_mapped() -> None:
    result = parse_chart_order(PAGE, LOCAL)
    ranks = {k: v.rank for k, v in result.entries.items()}
    assert ranks == {"week2cfb-1.png": 1, "week5cfb.png": 2, "champweekcfb.png": 3}
    assert result.unreferenced == ()
    assert result.entries["champweekcfb.png"].chart_kind == "postseason"
    assert result.entries["week5cfb.png"].chart_kind == "weekly"


def test_same_month_keeps_reverse_page_order() -> None:
    html = (
        '<img src="https://x/wp-content/uploads/2022/10/b.png" alt="b">'
        '<img src="https://x/wp-content/uploads/2022/10/a.png" alt="a">'
    )
    result = parse_chart_order(html, ["a.png", "b.png"])
    assert result.entries["a.png"].rank == 1
    assert result.entries["b.png"].rank == 2


def test_unreferenced_local_file_reported() -> None:
    result = parse_chart_order(PAGE, [*LOCAL, "stray.png"])
    assert result.unreferenced == ("stray.png",)
    assert "stray.png" not in result.entries


def test_non_uploads_images_ignored() -> None:
    result = parse_chart_order(PAGE, ["logo.png"])
    assert result.entries == {}
    assert result.unreferenced == ("logo.png",)


@pytest.mark.parametrize(
    ("name", "alt", "kind"),
    [
        ("cfbtop25.png", "", "season_top"),
        ("topcfbseason-updated.png", "", "season_top"),
        ("bowlweek2cfb.png", "", "postseason"),
        ("nationaltitlegame.png", "", "postseason"),
        ("week3cfb.png", "week 3", "weekly"),
        ("x.png", "championship week", "postseason"),
    ],
)
def test_chart_kind(name: str, alt: str, kind: str) -> None:
    assert chart_kind_for(name, alt) == kind


def test_csv_round_trip_and_strict_load(tmp_path: Path) -> None:
    result = parse_chart_order(PAGE, LOCAL)
    path = tmp_path / "chart_order.csv"
    write_chart_order_csv(path, result)
    assert load_chart_order_csv(path) == result.entries
    path.write_text(path.read_text().replace("weekly", "bogus", 1), encoding="utf-8")
    with pytest.raises(ReferenceTableError, match="line"):
        load_chart_order_csv(path)


def test_preloaded_image_without_upload_url_inherits_neighbor_month() -> None:
    html = (
        '<img src="https://x/wp-content/uploads/2022/12/c.png" alt="c">'
        '<img src="./saved_files/b.png" alt="b">'
        '<img src="https://x/wp-content/uploads/2022/10/a.png" alt="a">'
    )
    result = parse_chart_order(html, ["a.png", "b.png", "c.png"])
    assert [e.chart_file for e in sorted(result.entries.values(), key=lambda e: e.rank)] == [
        "a.png",
        "b.png",
        "c.png",
    ]
    assert result.unreferenced == ()
