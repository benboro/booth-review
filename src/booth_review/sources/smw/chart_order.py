"""Chart order and kind from a hand-saved SMW season page (04.19 D-08).

The page is untrusted text: it is scanned with html.parser only, scripts are
never evaluated and no URL is followed.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

from booth_review.build.io import write_review_csv
from booth_review.errors import ReferenceTableError
from booth_review.reference import read_reference_csv_numbered
from booth_review.sources.second_rows import ChartKind

CHART_ORDER_COLUMNS = ("chart_file", "alt", "upload_month", "page_index", "chart_kind", "rank")

_CANONICAL_RE = re.compile(
    r"""<link[^>]*rel=["']canonical["'][^>]*href=["']https?://(?:www\.)?sportsmediawatch\.com"""
    r"""/college-football-tv-ratings/(\d{4})-season/?["']""",
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title>\s*(\d{4}) college football TV ratings", re.IGNORECASE)
_UPLOAD_RE = re.compile(
    r"/wp-content/uploads/(\d{4})/(\d{2})/([A-Za-z0-9._-]+?)(?:-\d+x\d+)?\.png(?![A-Za-z0-9])",
)
_CHART_FILE_RE = re.compile(r"^[A-Za-z0-9._-]+\.png$")
_KINDS = ("weekly", "postseason", "season_top", "post")


@dataclass(frozen=True)
class ChartOrderEntry:
    chart_file: str
    alt: str
    upload_month: str
    page_index: int
    chart_kind: ChartKind
    rank: int


@dataclass(frozen=True)
class ChartOrderResult:
    entries: dict[str, ChartOrderEntry]
    unreferenced: tuple[str, ...]


def identify_season_page(html: str) -> tuple[int, str] | None:
    """(season, canonical URL) when the canonical link and the title agree."""
    canonical = _CANONICAL_RE.search(html)
    title = _TITLE_RE.search(html)
    if canonical is None or title is None or canonical.group(1) != title.group(1):
        return None
    year = int(canonical.group(1))
    return (
        year,
        f"https://www.sportsmediawatch.com/college-football-tv-ratings/{year}-season/",
    )


def chart_kind_for(chart_file: str, alt: str) -> ChartKind:
    text = f"{chart_file} {alt}".lower()
    if (
        "most-watched" in text
        or "cfbtop25" in text
        or "topcfbseason" in text
        or ("top" in text and "season" in text)
    ):
        return "season_top"
    if any(word in text for word in ("bowl", "postseason", "champ", "title", "national")):
        return "postseason"
    return "weekly"


class _ImgScanner(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.imgs: list[tuple[str, str]] = []  # (candidate url text, alt)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "img":
            return
        a = {k: (v or "") for k, v in attrs}
        alt = a.get("alt", "")
        for key in ("data-src", "data-lazy-src", "src"):
            if _UPLOAD_RE.search(a.get(key, "")):
                self.imgs.append((a[key], alt))
                return
        for key in ("data-srcset", "data-lazy-srcset", "srcset"):
            value = a.get(key, "")
            if value:
                first = value.split(",")[0].strip().split(" ")[0]
                if _UPLOAD_RE.search(first):
                    self.imgs.append((first, alt))
                    return
        # Preloaded images keep only a local saved-page path; the upload URL
        # then appears elsewhere in the page (resolved by the caller).
        src = a.get("src", "")
        if src.lower().endswith(".png"):
            self.imgs.append((src, alt))


def parse_chart_order(html: str, local_files: Collection[str]) -> ChartOrderResult:
    """Rank the page's charts oldest first; report local PNGs the page never lists."""
    scanner = _ImgScanner()
    scanner.feed(html)
    local = set(local_files)
    found: dict[str, tuple[str, str, int]] = {}
    for index, (url, alt) in enumerate(scanner.imgs):
        match = _UPLOAD_RE.search(url)
        if match is not None:
            chart_file = f"{match.group(3)}.png"
            month = f"{match.group(1)}-{match.group(2)}"
        else:
            chart_file = unquote(url.rsplit("/", 1)[-1])
            by_name = re.search(
                r"/wp-content/uploads/(\d{4})/(\d{2})/"
                + re.escape(chart_file.removesuffix(".png"))
                + r"(?:-\d+x\d+)?\.png",
                html.replace("\\/", "/"),
            )
            # A saved page can lack the upload URL; the month is then taken
            # from the nearest chart above it (newer) in a second pass.
            month = f"{by_name.group(1)}-{by_name.group(2)}" if by_name else ""
        if chart_file not in local or chart_file in found:
            continue
        found[chart_file] = (month, alt, index)
    by_index = sorted(found.items(), key=lambda kv: kv[1][2])
    for pos, (chart_file, (month, alt, index)) in enumerate(by_index):
        if month:
            continue
        newer = [m for _, (m, _, _) in reversed(by_index[:pos]) if m]
        older = [m for _, (m, _, _) in by_index[pos + 1 :] if m]
        inherited = (newer or older or [""])[0]
        if not inherited:
            del found[chart_file]
            continue
        found[chart_file] = (inherited, alt, index)
    ordered = sorted(found.items(), key=lambda kv: (kv[1][0], -kv[1][2]))
    entries = {
        chart_file: ChartOrderEntry(
            chart_file=chart_file,
            alt=alt,
            upload_month=month,
            page_index=index,
            chart_kind=chart_kind_for(chart_file, alt),
            rank=rank,
        )
        for rank, (chart_file, (month, alt, index)) in enumerate(ordered, start=1)
    }
    unreferenced = tuple(sorted(local - set(found)))
    return ChartOrderResult(entries=entries, unreferenced=unreferenced)


def write_chart_order_csv(path: Path, result: ChartOrderResult) -> None:
    rows = [
        {
            "chart_file": e.chart_file,
            "alt": e.alt,
            "upload_month": e.upload_month,
            "page_index": str(e.page_index),
            "chart_kind": e.chart_kind,
            "rank": str(e.rank),
        }
        for e in sorted(result.entries.values(), key=lambda e: e.rank)
    ]
    write_review_csv(path, CHART_ORDER_COLUMNS, rows)


def load_chart_order_csv(path: Path) -> dict[str, ChartOrderEntry]:
    def fail(line_no: int, what: str) -> ReferenceTableError:
        return ReferenceTableError(f"{path.name}: line {line_no}: {what}")

    entries: dict[str, ChartOrderEntry] = {}
    for line_no, raw in read_reference_csv_numbered(path, CHART_ORDER_COLUMNS, required=True):
        chart_file = raw["chart_file"]
        if not _CHART_FILE_RE.match(chart_file):
            raise fail(line_no, "chart_file is not a plain .png name")
        if chart_file in entries:
            raise fail(line_no, "duplicate chart_file")
        for column in ("page_index", "rank"):
            cell = raw[column]
            if not (cell.isascii() and cell.isdecimal()):
                raise fail(line_no, f"{column} must be an integer")
        kind = raw["chart_kind"]
        if kind not in _KINDS:
            raise fail(line_no, "chart_kind is not a known kind")
        entries[chart_file] = ChartOrderEntry(
            chart_file=chart_file,
            alt=raw["alt"],
            upload_month=raw["upload_month"],
            page_index=int(raw["page_index"]),
            chart_kind=kind,  # type: ignore[arg-type]
            rank=int(raw["rank"]),
        )
    return entries
