"""Workbook transport type — the in-memory ``{sheet: rows[]}`` shape.

A *workbook* is the model's data tables held in memory as ``dict[str, list[dict]]``
(sheet name → row dicts) — exactly the JSON shape the web API exchanges with the
frontend, and a transient transport only. The model's persistent store is
**SQLite** (see :mod:`pathwise.api.workbook_io`: ``parse_sqlite`` / ``write_sqlite``);
``.xlsx`` is supported only as an import/export convenience there. NaN/empty cells
normalise to ``None``.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

#: In-memory workbook: sheet name → list of row dicts.
Workbook = dict[str, list[dict[str, Any]]]


def _clean(value: Any) -> Any:
    """Normalise a cell: NaN/NaT → ``None``; leave everything else."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def frames_to_workbook(frames: dict[str, pd.DataFrame]) -> Workbook:
    """Convert ``{sheet: DataFrame}`` to the ``{sheet: rows[]}`` form."""
    return {
        sheet: [{str(k): _clean(v) for k, v in row.items()} for row in df.to_dict(orient="records")]
        for sheet, df in frames.items()
    }


def workbook_to_frames(workbook: Workbook) -> dict[str, pd.DataFrame]:
    """Convert the ``{sheet: rows[]}`` form to ``{sheet: DataFrame}``."""
    return {sheet: pd.DataFrame(rows) for sheet, rows in workbook.items()}
