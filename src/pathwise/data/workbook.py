"""Workbook I/O — the ``{sheet: rows[]}`` transport format.

A *workbook* holds the model's data tables. In memory it is
``dict[str, list[dict]]`` (sheet name → row dicts), which is exactly the JSON
shape the web API exchanges with the frontend. This module converts between that
shape, pandas, and ``.xlsx``. NaN/empty cells normalise to ``None``.
"""

from __future__ import annotations

import math
from pathlib import Path
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


def read_workbook(path: str | Path) -> Workbook:
    """Read every sheet of an ``.xlsx`` file into the ``{sheet: rows[]}`` form."""
    frames = pd.read_excel(path, sheet_name=None, engine="openpyxl")
    return frames_to_workbook(frames)


def write_workbook(workbook: Workbook, path: str | Path) -> None:
    """Write an in-memory workbook to ``.xlsx`` (one sheet per table)."""
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet, rows in workbook.items():
            pd.DataFrame(rows).to_excel(writer, sheet_name=sheet[:31], index=False)
