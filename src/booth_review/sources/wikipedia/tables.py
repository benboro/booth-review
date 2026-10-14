"""Rectangular grid expansion for Wikipedia wikitables (rowspan/colspan), no pandas."""

from __future__ import annotations

import re

from bs4 import Tag

_FOOTNOTE = re.compile(r"\[\s*[\w ]{1,12}\s*\]")


def _cell_text(cell: Tag) -> str:
    for nested in cell.find_all("table"):
        nested.decompose()
    for sup in cell.find_all("sup", class_="reference"):
        sup.decompose()
    return re.sub(r"\s+", " ", _FOOTNOTE.sub("", cell.get_text(" "))).strip()


def _span(cell: Tag, attr: str, cap: int) -> int:
    raw = str(cell.get(attr, "1")).strip()
    value = int(raw) if raw.isdigit() else 1
    return max(1, min(value, cap))


def _drain_pending(row: list[str], pending: dict[int, tuple[str, int]]) -> None:
    while len(row) in pending:
        col = len(row)
        text, left = pending.pop(col)
        row.append(text)
        if left > 1:
            pending[col] = (text, left - 1)


def expand_wikitable(table: Tag) -> list[list[str]]:
    """Expand a table into rows of equal length, repeating spanned cells.

    Nested tables are ignored; spans are capped at the table's row and
    (cells-per-row) column counts so hostile markup cannot blow up memory.
    """
    rows = [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]
    cell_rows = [list(tr.find_all(["td", "th"], recursive=False)) for tr in rows]
    max_rows = len(rows)
    max_cols = max((len(cells) for cells in cell_rows), default=1) or 1
    pending: dict[int, tuple[str, int]] = {}
    grid: list[list[str]] = []
    for cells in cell_rows:
        row: list[str] = []
        for cell in cells:
            _drain_pending(row, pending)
            text = _cell_text(cell)
            colspan = _span(cell, "colspan", max_cols)
            rowspan = _span(cell, "rowspan", max_rows)
            for _ in range(colspan):
                if rowspan > 1:
                    pending[len(row)] = (text, rowspan - 1)
                row.append(text)
        _drain_pending(row, pending)
        grid.append(row)
    width = max((len(r) for r in grid), default=0)
    return [r + [""] * (width - len(r)) for r in grid]
