"""Back-compat name normalization for the generic-rename migration.

pathwise's domain vocabulary is being renamed to generic terms (machine→asset,
commodity→flow, connection→link, measure→lever, value chain→network). Models on
disk — the bundled example ``.sqlite`` files and any user model saved before the
rename — still carry the OLD sheet / column / enum names. Rather than migrate those
binaries, every model is passed through :func:`normalize_workbook` at the load
boundary, which renames OLD names to the current canonical (NEW) ones.

It is **idempotent**: a model already in new names passes through unchanged, so it
is safe to call on every load and on already-migrated models. The maps grow one
entry-group per rename term as the migration lands; only ``measure→lever`` is wired
so far.
"""

from __future__ import annotations

from typing import Any

#: OLD sheet name -> NEW sheet name.
SHEET_RENAMES: dict[str, str] = {
    "measures": "levers",
    "measure_blocks": "lever_blocks",
    "measure_blocks_t": "lever_blocks_t",
    "measure_links": "lever_links",
}

#: OLD column name -> NEW column name, applied to every row of every sheet (the
#: ids are globally unique enough that a blanket rename is safe).
COLUMN_RENAMES: dict[str, str] = {
    "measure_id": "lever_id",
}

#: (sheet, column) -> {OLD cell value -> NEW cell value} for enum-like columns
#: (e.g. ``nodes.kind`` "machine" -> "asset" once that term lands).
VALUE_RENAMES: dict[tuple[str, str], dict[str, str]] = {}


def normalize_workbook(wb: Any) -> Any:
    """Return ``wb`` with any OLD sheet/column/enum names renamed to the current ones.

    A shallow rebuild (does not mutate the input). Non-dict inputs and non-list
    sheet bodies pass through untouched.
    """
    if not isinstance(wb, dict):
        return wb
    out: dict[str, Any] = {}
    for sheet, rows in wb.items():
        key = str(sheet)
        new_sheet = SHEET_RENAMES.get(key, key)
        out[new_sheet] = (
            [_normalize_row(new_sheet, r) for r in rows] if isinstance(rows, list) else rows
        )
    return out


def _normalize_row(sheet: str, row: Any) -> Any:
    if not isinstance(row, dict):
        return row
    out: dict[str, Any] = {}
    for col, val in row.items():
        new_col = COLUMN_RENAMES.get(str(col), str(col))
        vmap = VALUE_RENAMES.get((sheet, new_col))
        out[new_col] = vmap[val] if (vmap and isinstance(val, str) and val in vmap) else val
    return out
