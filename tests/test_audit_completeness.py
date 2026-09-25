"""Tests for D-05 completeness (audit/completeness.py).

Every test builds synthetic 506 pages (reusing the week/bowls fixture
structure, D-07: never real 506 content), a synthetic RR sitemap/records, and
hand-written CFBD endpoint JSON files directly under `vault_paths.raw`, then
asserts on `build_completeness`'s report -- no HTTP client is ever built here.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from booth_review.audit.completeness import (
    CFBD_SEASON_ENDPOINTS,
    build_completeness,
    cfbd_ledger_months,
    check_506,
    check_cfbd,
    check_rr,
    write_completeness,
)
from booth_review.config import CFBD_FLOOR_DEFAULT, DataPaths
from booth_review.sources.ratingsref.sitemap import parse_sitemap

FIXTURES = Path(__file__).parent / "fixtures" / "sports506"
_WEEK_TEMPLATE = (FIXTURES / "week_synthetic.html").read_bytes()
_BOWLS_TEMPLATE = (FIXTURES / "bowls_synthetic.html").read_bytes()


def _page(season: int, label: str, *, nav_labels: list[str]) -> bytes:
    """A synthetic 506 page (good crew coverage, D-03 smoke-check passing)
    for (season, label), carrying a nav block listing `nav_labels`.
    """
    template = _BOWLS_TEMPLATE if label == "B" else _WEEK_TEMPLATE
    template_label = "B" if label == "B" else "5"
    text = template.decode("utf-8")
    text = text.replace(f"yr=2025&wk={template_label}", f"yr={season}&wk={label}")
    text = text.replace(f"Week {template_label}, 2025", f"Week {label}, {season}")
    anchors = "".join(
        f'<a href="ncaaf.php?yr={season}&wk={nav_label}">wk {nav_label}</a>'
        for nav_label in nav_labels
    )
    text = text.replace("<body>", f"<body><nav>{anchors}</nav>", 1)
    return text.encode("utf-8")


def _bad_crew_page(season: int, label: str, *, nav_labels: list[str]) -> bytes:
    """A synthetic page that discover_season_weeks can read (nav present) but
    smoke_check fails (1/4 games with crew, below the 50% floor).
    """
    rows = []
    for i in range(4):
        crew = "Pat Example, Jordan Sample" if i == 0 else ""
        rows.append(
            f'<div id="cgame"><div id="cmatchup">Team{i}A @ Team{i}B</div>'
            f'<div id="ctime">7:00 PM</div><div id="cntwk">ECN</div>'
            f'<div id="canncrs">{crew}</div></div>'
        )
    anchors = "".join(
        f'<a href="ncaaf.php?yr={season}&wk={nav_label}">wk {nav_label}</a>'
        for nav_label in nav_labels
    )
    body = f"<nav>{anchors}</nav><h3>SATURDAY, SEPTEMBER 6</h3>" + "".join(rows)
    return f"<html><body>{body}</body></html>".encode()


def _write_506_page(paths: DataPaths, season: int, label: str, content: bytes) -> None:
    name = label if label == "B" else label.zfill(2)
    path = paths.raw / "sports506" / str(season) / f"wk-{name}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _write_cfbd(paths: DataPaths, season: int, name: str, rows: list[dict]) -> None:
    path = paths.raw / "cfbd" / name / f"{season}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")


def _write_all_cfbd_endpoints(
    paths: DataPaths, season: int, *, empty: frozenset[str] = frozenset()
) -> None:
    for name in CFBD_SEASON_ENDPOINTS:
        rows = [] if name in empty else [{"id": 1}]
        _write_cfbd(paths, season, name, rows)


def _sitemap_xml(entries: list[tuple[str, str]]) -> bytes:
    urls = "".join(
        f"<url><loc>https://ratingsreference.com/telecast/{slug}</loc>"
        f"<lastmod>{lastmod}</lastmod></url>"
        for slug, lastmod in entries
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    ).encode()


def _write_sitemap(
    paths: DataPaths, entries: list[tuple[str, str]], *, day: str = "2026-09-25"
) -> None:
    path = paths.raw / "ratingsref" / "sitemap" / f"{day}.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_sitemap_xml(entries))


def _write_rr_record(paths: DataPaths, season: int, slug: str) -> None:
    path = paths.raw / "ratingsref" / "telecast" / str(season) / f"{slug}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")


def _write_lastmod(paths: DataPaths, entries: dict[str, str]) -> None:
    paths.rr_lastmod.write_text(
        json.dumps(
            {
                slug: {"lastmod": lastmod, "fetched_at": "2026-01-01T00:00:00Z", "record_url": "x"}
                for slug, lastmod in entries.items()
            }
        ),
        encoding="utf-8",
    )


def _append_cfbd_call(
    paths: DataPaths, *, month: str, endpoint: str, remaining: int, tag: str | None = None
) -> None:
    paths.cfbd_ledger.parent.mkdir(parents=True, exist_ok=True)
    with paths.cfbd_ledger.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "event": "call",
                    "endpoint": endpoint,
                    "month": month,
                    "call_limit_remaining_header": remaining,
                    "info_remaining_calls": None,
                    "counted_against_quota": True,
                    "tag": tag,
                }
            )
            + "\n"
        )


_NOW = datetime(2026, 9, 25, tzinfo=UTC)
_SLUG = "cfb-alpha-vs-beta-2025-09-06"


def _seed_complete_season(
    paths: DataPaths, season: int = 2025, nav: list[str] | None = None
) -> None:
    labels = nav if nav is not None else ["0", "1"]
    for label in labels:
        _write_506_page(paths, season, label, _page(season, label, nav_labels=labels))
    _write_all_cfbd_endpoints(paths, season)
    _write_sitemap(paths, [(_SLUG, "2026-01-01")])
    _write_rr_record(paths, season, _SLUG)
    _write_lastmod(paths, {_SLUG: "2026-01-01"})


# -- a fully complete season -----------------------------------------------------------------


def test_build_completeness_all_sources_complete(vault_paths: DataPaths) -> None:
    season = 2025
    _seed_complete_season(vault_paths, season)

    report = build_completeness(vault_paths, [season], now=_NOW)

    assert report.complete_for(season) is True
    assert report.incomplete_cells() == []
    assert {cell.source for cell in report.cells} == {"sports506", "cfbd", "ratingsref"}
    for cell in report.cells:
        assert cell.reasons == []


# -- 506 single-failure variants -------------------------------------------------------------


def test_check_506_no_cached_pages_is_incomplete() -> None:
    paths = DataPaths(vault=Path("/nonexistent-for-this-test"))
    cell = check_506(paths, 2025)
    assert cell.complete is False
    assert cell.reasons == ["no pages imported"]
    assert cell.counts == {"expected": 0, "cached": 0, "smoke_failed": 0, "missing": 0, "extra": 0}


def test_check_506_smoke_check_failure(vault_paths: DataPaths) -> None:
    season = 2025
    nav = ["0", "1"]
    _write_506_page(vault_paths, season, "0", _bad_crew_page(season, "0", nav_labels=nav))
    _write_506_page(vault_paths, season, "1", _page(season, "1", nav_labels=nav))

    cell = check_506(vault_paths, season)

    assert cell.complete is False
    assert cell.counts["smoke_failed"] == 1
    assert cell.details["smoke_failed"] == ["0"]
    assert any("smoke check failed" in reason for reason in cell.reasons)


def test_check_506_missing_nav_week(vault_paths: DataPaths) -> None:
    season = 2025
    nav = ["0", "1"]
    # Only week 0 is actually cached, but its own nav claims week 1 exists too.
    _write_506_page(vault_paths, season, "0", _page(season, "0", nav_labels=nav))

    cell = check_506(vault_paths, season)

    assert cell.complete is False
    assert cell.counts["missing"] == 1
    assert cell.details["missing"] == ["1"]
    assert any("missing weeks: 1" in reason for reason in cell.reasons)


def test_check_506_2020_style_short_nav_is_complete_when_fully_imported(
    vault_paths: DataPaths,
) -> None:
    season = 2020
    nav = [str(n) for n in range(12)]  # an irregular, 12-week season
    for label in nav:
        _write_506_page(vault_paths, season, label, _page(season, label, nav_labels=nav))

    cell = check_506(vault_paths, season)

    assert cell.complete is True
    assert cell.counts["expected"] == 12
    assert cell.counts["missing"] == 0


# -- CFBD single-failure variant --------------------------------------------------------------


def test_check_cfbd_all_present_is_complete(vault_paths: DataPaths) -> None:
    season = 2025
    _write_all_cfbd_endpoints(vault_paths, season)

    cell = check_cfbd(vault_paths, season)

    assert cell.complete is True
    assert cell.counts == {"total": 6, "present": 6, "missing": 0}


def test_check_cfbd_one_empty_endpoint_is_incomplete(vault_paths: DataPaths) -> None:
    season = 2025
    _write_all_cfbd_endpoints(vault_paths, season, empty=frozenset({"media"}))

    cell = check_cfbd(vault_paths, season)

    assert cell.complete is False
    assert cell.details["missing"] == ["media"]
    assert cell.counts["present"] == 5


def test_check_cfbd_missing_file_is_incomplete(vault_paths: DataPaths) -> None:
    season = 2025
    for name in CFBD_SEASON_ENDPOINTS:
        if name == "rankings":
            continue
        _write_cfbd(vault_paths, season, name, [{"id": 1}])

    cell = check_cfbd(vault_paths, season)

    assert cell.complete is False
    assert cell.details["missing"] == ["rankings"]


# -- RR single-failure variants ----------------------------------------------------------------


def test_check_rr_missing_record_is_incomplete(vault_paths: DataPaths) -> None:
    season = 2025
    _write_sitemap(vault_paths, [(_SLUG, "2026-01-01")])
    xml = (vault_paths.raw / "ratingsref" / "sitemap" / "2026-09-25.xml").read_bytes()
    entries, _skipped = parse_sitemap(xml)

    cell = check_rr(vault_paths, season, entries, lastmod_keys=set())

    assert cell.complete is False
    assert cell.counts == {"listed": 1, "cached": 0, "lastmod_recorded": 0, "missing": 1}
    assert cell.details["missing_telecast_ids"] == [_SLUG]


def test_check_rr_record_without_lastmod_is_incomplete(vault_paths: DataPaths) -> None:
    season = 2025
    _write_sitemap(vault_paths, [(_SLUG, "2026-01-01")])
    _write_rr_record(vault_paths, season, _SLUG)
    xml = (vault_paths.raw / "ratingsref" / "sitemap" / "2026-09-25.xml").read_bytes()
    entries, _skipped = parse_sitemap(xml)

    cell = check_rr(vault_paths, season, entries, lastmod_keys=set())

    assert cell.complete is False
    assert cell.counts == {"listed": 1, "cached": 1, "lastmod_recorded": 0, "missing": 1}


def test_check_rr_cached_and_lastmod_recorded_is_complete(vault_paths: DataPaths) -> None:
    season = 2025
    _write_sitemap(vault_paths, [(_SLUG, "2026-01-01")])
    _write_rr_record(vault_paths, season, _SLUG)
    xml = (vault_paths.raw / "ratingsref" / "sitemap" / "2026-09-25.xml").read_bytes()
    entries, _skipped = parse_sitemap(xml)

    cell = check_rr(vault_paths, season, entries, lastmod_keys={_SLUG})

    assert cell.complete is True
    assert cell.counts == {"listed": 1, "cached": 1, "lastmod_recorded": 1, "missing": 0}


# -- CFBD ledger month summary ------------------------------------------------------------------


def test_cfbd_ledger_months_reports_above_floor_true_and_false(vault_paths: DataPaths) -> None:
    _append_cfbd_call(
        vault_paths, month="2026-09", endpoint="/games", remaining=300, tag="backfill"
    )
    _append_cfbd_call(vault_paths, month="2026-10", endpoint="/games", remaining=100, tag="job")

    months = cfbd_ledger_months(vault_paths, floor=CFBD_FLOOR_DEFAULT)
    by_month = {entry["month"]: entry for entry in months}

    assert by_month["2026-09"]["above_floor"] is True
    assert by_month["2026-09"]["calls_counted"] == 1
    assert by_month["2026-09"]["by_tag"] == {"backfill": 1}
    assert by_month["2026-10"]["above_floor"] is False


# -- build_completeness/write_completeness end-to-end --------------------------------------------


def test_write_completeness_persists_json_and_markdown_no_urls_or_page_text(
    vault_paths: DataPaths,
) -> None:
    season = 2025
    _seed_complete_season(vault_paths, season)
    report = build_completeness(vault_paths, [season], now=_NOW)

    write_completeness(vault_paths, report)

    json_path = vault_paths.audit / "completeness.json"
    md_path = vault_paths.audit / "completeness.md"
    assert json_path.is_file()
    assert md_path.is_file()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["cells_complete"] == 3
    assert payload["summary"]["cells_incomplete"] == 0
    assert payload["seasons"] == [season]

    md_text = md_path.read_text(encoding="utf-8")
    assert "506sports.com" not in md_text
    assert "ratingsreference.com" not in md_text
    assert "http://" not in md_text
    assert "https://" not in md_text
    assert "| 2025 | sports506 | complete |" in md_text


def test_build_completeness_no_http_client_import() -> None:
    import inspect

    from booth_review.audit import completeness

    source = inspect.getsource(completeness)
    assert "transport.client" not in source
    assert "make_client" not in source
    assert "PoliteClient" not in source
