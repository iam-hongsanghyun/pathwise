"""Server-side workbook file I/O (the browser never parses spreadsheets).

Mirrors what the frontend's old client-side ``workbook.ts`` did with SheetJS:
``.xlsx`` bytes ⇄ the ``{sheet: rows[]}`` model. Lives in the API layer (not
``data/``) because it exists purely to serve the HTTP file boundary.
"""

from __future__ import annotations

import io
import sqlite3
from typing import Any

import pandas as pd

from pathwise.data.workbook import Workbook, _clean

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


def write_template_xlsx(columns: dict[str, list[str]]) -> bytes:
    """A blank fill-in ``.xlsx``: one sheet per table with its column headers and no
    rows. ``columns`` is ``{sheet: [col, …]}`` (e.g. from ``schema.template_columns``)."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for sheet, cols in columns.items():
            pd.DataFrame(columns=list(cols)).to_excel(xw, sheet_name=str(sheet)[:31], index=False)
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
    add("Levers", outputs.get("levers"))
    add("Flows", outputs.get("flows"))
    add("Impacts", summary.get("impacts"))
    portfolio = outputs.get("portfolio")
    if isinstance(portfolio, dict) and portfolio.get("assets"):
        add("Portfolio", portfolio["assets"])
    sheets["Run"] = [{"status": result.get("status"), "objective": result.get("objective")}]
    return write_xlsx(sheets)


def result_to_tables(result: dict[str, Any]) -> Workbook:
    """Flatten a run (or cascade) result into ``{table: rows[]}`` — every output
    by year. A cascade (per-stage) result gets a ``stage`` column so the tables
    stay one-row-per-(stage, …)."""
    tables: Workbook = {}

    def collect(name: str, rows: Any, stage: str | None) -> None:
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            tables.setdefault(name, []).append({"stage": stage, **row} if stage else dict(row))

    stages = result.get("stages")
    pairs = list(stages.items()) if isinstance(stages, dict) else [(None, result)]
    for stage, r in pairs:
        out, summ = r.get("outputs", {}), r.get("summary", {})
        for key in (
            "technology",
            "throughput",
            "transitions",
            "renewals",
            "levers",
            "flows",
            "trade",
            "consumption",
            "demand_slack",
        ):
            collect(key, out.get(key), stage)
        collect("emissions", summ.get("impacts"), stage)
        collect("cost", summ.get("periods"), stage)
        collect("flow", summ.get("flow"), stage)
        # nested per-period blocks → flat rows
        for st in out.get("storage") or []:
            for bp in st.get("by_period", []):
                collect(
                    "storage",
                    [
                        {
                            "storage": st.get("storage"),
                            "flow": st.get("flow"),
                            "capacity": st.get("capacity"),
                            **bp,
                        }
                    ],
                    stage,
                )
        for mk in out.get("markets") or []:
            for bp in mk.get("by_period", []):
                collect(
                    "markets",
                    [
                        {
                            "market": mk.get("market"),
                            "flow": mk.get("flow"),
                            "tag": mk.get("tag"),
                            **bp,
                        }
                    ],
                    stage,
                )
        for mk in out.get("ets") or []:
            for bp in mk.get("by_period", []):
                row = {"market": mk.get("market"), "impact": mk.get("impact"), **bp}
                collect("ets", [row], stage)
        macc = out.get("macc")
        if isinstance(macc, dict):
            for row in macc.get("by_year", []):
                collect("macc", [{k: v for k, v in row.items() if k != "deployed"}], stage)
    tables["run"] = [
        {
            "status": result.get("status"),
            "termination": result.get("termination"),
            "objective": result.get("objective"),
        }
    ]
    return tables


def result_to_sqlite(result: dict[str, Any]) -> bytes:
    """Flatten a run result into a SQLite workbook (one table per output, by year)."""
    return write_sqlite(result_to_tables(result))
