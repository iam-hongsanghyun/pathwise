"""Export a result dict to a stakeholder-friendly Excel workbook.

Flattens the decision outputs and per-period summary into one sheet per
section, mirroring the legacy shipping output layout (renamed to the generic
vocabulary).
"""

from __future__ import annotations

import io
from typing import Any

import pandas as pd

_SECTION_SHEETS = {
    "chosen_technology": "Assignments",
    "carrier_energy": "Carrier_Energy",
    "transitions": "Transitions",
    "new_builds": "New_Builds",
    "measures": "Measures",
    "slack": "Slack",
}


def result_to_workbook(result: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Convert a result dict to a ``{sheet: rows[]}`` workbook."""
    outputs = result.get("outputs", {})
    workbook: dict[str, list[dict[str, Any]]] = {}
    for key, sheet in _SECTION_SHEETS.items():
        rows = outputs.get(key, [])
        if rows:
            workbook[sheet] = rows
    summary = result.get("summary", {}).get("periods", [])
    if summary:
        workbook["Period_Summary"] = summary
    workbook["Run_Info"] = [
        {
            "status": result.get("status"),
            "objective": result.get("objective"),
            "termination": result.get("termination"),
        }
    ]
    return workbook


def result_to_xlsx_bytes(result: dict[str, Any]) -> bytes:
    """Render a result dict as ``.xlsx`` bytes (one sheet per section)."""
    workbook = result_to_workbook(result)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet, rows in workbook.items():
            pd.DataFrame(rows).to_excel(writer, sheet_name=sheet[:31], index=False)
    return buffer.getvalue()
