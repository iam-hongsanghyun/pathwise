"""Server-side workbook file I/O (the browser never parses spreadsheets).

Mirrors what the frontend's old client-side ``workbook.ts`` did with SheetJS:
``.xlsx`` bytes ⇄ the ``{sheet: rows[]}`` model. Lives in the API layer (not
``data/``) because it exists purely to serve the HTTP file boundary.
"""

from __future__ import annotations

import io
import math
from typing import Any

import pandas as pd

from pathwise.data.workbook import Workbook


def _clean(v: Any) -> Any:
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def parse_xlsx(data: bytes) -> Workbook:
    """Parse ``.xlsx`` bytes into the ``{sheet: rows[]}`` model (NaN → None)."""
    frames = pd.read_excel(io.BytesIO(data), sheet_name=None)
    model: Workbook = {}
    for name, frame in frames.items():
        rows = frame.to_dict(orient="records")
        model[str(name)] = [{str(k): _clean(v) for k, v in r.items()} for r in rows]
    return model


def write_xlsx(model: Workbook) -> bytes:
    """Write the model to ``.xlsx`` bytes (one sheet per table)."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for sheet, rows in model.items():
            pd.DataFrame(rows).to_excel(xw, sheet_name=sheet[:31], index=False)
    return buf.getvalue()


def result_to_xlsx(result: dict[str, Any]) -> bytes:
    """Flatten a run result into ``.xlsx`` bytes (the old client-side export)."""
    outputs = result.get("outputs", {})
    summary = result.get("summary", {})
    sheets: Workbook = {}

    def add(name: str, rows: Any) -> None:
        if isinstance(rows, list) and rows:
            sheets[name] = rows

    add("Technology", outputs.get("technology"))
    add("Throughput", outputs.get("throughput"))
    add("Transitions", outputs.get("transitions"))
    add("Measures", outputs.get("measures"))
    add("Flows", outputs.get("flows"))
    add("Impacts", summary.get("impacts"))
    portfolio = outputs.get("portfolio")
    if isinstance(portfolio, dict) and portfolio.get("assets"):
        add("Portfolio", portfolio["assets"])
    sheets["Run"] = [{"status": result.get("status"), "objective": result.get("objective")}]
    return write_xlsx(sheets)
