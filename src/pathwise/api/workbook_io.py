"""Server-side workbook file I/O (the browser never parses spreadsheets).

Mirrors what the frontend's old client-side ``workbook.ts`` did with SheetJS:
``.xlsx`` bytes ⇄ the ``{sheet: rows[]}`` model. Lives in the API layer (not
``data/``) because it exists purely to serve the HTTP file boundary.
"""

from __future__ import annotations

import io
import math
import sqlite3
from typing import Any

import pandas as pd

from pathwise.data.workbook import Workbook


def _clean(v: Any) -> Any:
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


# ── Generic SQLite workbook I/O (one table per sheet) ─────────────────────────
# A workbook is ``{sheet: [row, …]}``; a SQLite example DB is the same shape —
# one table per sheet, one row per row, sparse cells stored as NULL and dropped
# on read. Completely generic: no sheet/column/sector is known here.


def _ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def parse_sqlite(data: bytes) -> Workbook:
    """Parse a SQLite database into the ``{sheet: rows[]}`` model.

    Every user table becomes a sheet; every row a dict of its non-NULL cells.
    """
    conn = sqlite3.connect(":memory:")
    try:
        conn.deserialize(data)
        model: Workbook = {}
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for table in tables:
            cur = conn.execute(f"SELECT * FROM {_ident(table)}")
            cols = [d[0] for d in cur.description]
            model[table] = [
                {cols[i]: rec[i] for i in range(len(cols)) if rec[i] is not None and cols[i] != "_"}
                for rec in cur.fetchall()
            ]
        return model
    finally:
        conn.close()


def write_sqlite(model: Workbook) -> bytes:
    """Write the model to SQLite bytes (one table per sheet)."""
    conn = sqlite3.connect(":memory:")
    try:
        for sheet, rows in model.items():
            cols: list[str] = []
            seen: set[str] = set()
            for r in rows:
                for k in r:
                    if str(k) not in seen:
                        seen.add(str(k))
                        cols.append(str(k))
            if not cols:  # an empty sheet — keep the table (no rows) via a sentinel column
                conn.execute(f"CREATE TABLE {_ident(sheet)} (_)")
                continue
            conn.execute(f"CREATE TABLE {_ident(sheet)} ({', '.join(_ident(c) for c in cols)})")
            ph = ", ".join("?" for _ in cols)
            conn.executemany(
                f"INSERT INTO {_ident(sheet)} ({', '.join(_ident(c) for c in cols)}) VALUES ({ph})",
                [[_sqlval(r.get(c)) for c in cols] for r in rows],
            )
        conn.commit()
        return bytes(conn.serialize())
    finally:
        conn.close()


def _sqlval(v: Any) -> Any:
    return (1 if v else 0) if isinstance(v, bool) else v  # sqlite has no bool type


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
