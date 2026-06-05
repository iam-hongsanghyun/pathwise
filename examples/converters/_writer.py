"""Shared helper: write a pathwise workbook (dict of tables) to an .xlsx file.

A *workbook* here is ``{sheet_name: list[dict]}`` — exactly the JSON the frontend
parses and POSTs to the backend. These converters turn real-world sector
datasets into that schema; the resulting .xlsx files are the *only* place sector
data lives (the engine and UI stay sector-agnostic).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

Workbook = dict[str, list[dict[str, Any]]]


def write_workbook(workbook: Workbook, path: Path) -> None:
    """Write ``{sheet: rows}`` to ``path`` as a multi-sheet .xlsx (header-first)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for sheet, rows in workbook.items():
            # Excel caps sheet names at 31 chars; pathwise sheet names fit.
            pd.DataFrame(rows).to_excel(xw, sheet_name=sheet[:31], index=False)


def verify(workbook: Workbook, name: str) -> None:
    """Assemble + solve the workbook through the real engine; assert optimal."""
    from pathwise.core import build, extract_results, solve
    from pathwise.data import ScenarioConfig, assemble_problem, validate

    report = validate(workbook)
    if not report.ok:
        raise SystemExit(f"[{name}] validation failed: {report.errors}")
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025}})
    res = extract_results(solve(build(assemble_problem(workbook, sc))))
    print(f"[{name}] status={res['status']} objective={res['objective']:,.0f}")
    if res["status"] != "optimal":
        raise SystemExit(f"[{name}] not optimal: {res['status']}")
