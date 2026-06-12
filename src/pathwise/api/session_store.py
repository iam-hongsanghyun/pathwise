"""Server-side working-model sessions (the ragnarok pattern).

The backend — not the browser — owns the model being edited. Each session is
one SQLite file under ``<data_dir>/sessions/<id>.db`` holding the workbook
(sheet name → JSON rows). The frontend ingests a model once, then reads pages
(``get_sheet``) and writes patches (``patch_sheet``); the heavy model never has
to live in browser memory, and a run can be submitted by session id alone.

Sheets in pathwise are small (tens–hundreds of rows), so rows are stored as one
JSON document per sheet — the *contract* (paged reads, patch writes, server-side
files) is what matters; the storage stays trivially simple.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from pathwise.data.workbook import Workbook
from pathwise.logger import get_logger

logger = get_logger(__name__)

Row = dict[str, Any]


class SessionNotFound(KeyError):
    """Raised when a session id does not exist on disk."""


class SessionStore:
    """One SQLite file per working session."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
        return self.root / f"{safe}.db"

    def _open(self, session_id: str, must_exist: bool = True) -> sqlite3.Connection:
        path = self._path(session_id)
        if must_exist and not path.exists():
            raise SessionNotFound(session_id)
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE IF NOT EXISTS sheets (name TEXT PRIMARY KEY, rows TEXT)")
        return conn

    def create(self, model: Workbook | None = None) -> str:
        """Create a session (optionally seeded with a model); return its id."""
        session_id = uuid.uuid4().hex[:12]
        with self._open(session_id, must_exist=False) as conn:
            conn.commit()
        if model:
            self.put_model(session_id, model)
        logger.info("session created: %s (%d sheets)", session_id, len(model or {}))
        return session_id

    def exists(self, session_id: str) -> bool:
        """Whether a session file exists."""
        return self._path(session_id).exists()

    def delete(self, session_id: str) -> None:
        """Remove a session file (no error if absent)."""
        self._path(session_id).unlink(missing_ok=True)

    def put_model(self, session_id: str, model: Workbook) -> dict[str, int]:
        """Replace the whole session model; returns per-sheet row counts."""
        with self._open(session_id) as conn:
            conn.execute("DELETE FROM sheets")
            for name, rows in model.items():
                conn.execute(
                    "INSERT INTO sheets (name, rows) VALUES (?, ?)",
                    (name, json.dumps(rows, ensure_ascii=False, default=str)),
                )
            conn.commit()
        return {name: len(rows) for name, rows in model.items()}

    def get_model(self, session_id: str) -> Workbook:
        """The full workbook of a session."""
        with self._open(session_id) as conn:
            cur = conn.execute("SELECT name, rows FROM sheets")
            return {name: json.loads(rows) for name, rows in cur.fetchall()}

    def _get_rows(self, conn: sqlite3.Connection, name: str) -> list[Row]:
        cur = conn.execute("SELECT rows FROM sheets WHERE name = ?", (name,))
        hit = cur.fetchone()
        return json.loads(hit[0]) if hit else []

    def _put_rows(self, conn: sqlite3.Connection, name: str, rows: list[Row]) -> None:
        conn.execute(
            "INSERT INTO sheets (name, rows) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET rows = excluded.rows",
            (name, json.dumps(rows, ensure_ascii=False, default=str)),
        )

    def get_sheet(
        self, session_id: str, name: str, offset: int = 0, limit: int = 1000
    ) -> dict[str, Any]:
        """A page of one sheet: ``{rows, total, columns, offset}``."""
        with self._open(session_id) as conn:
            rows = self._get_rows(conn, name)
        columns = sorted({k for r in rows for k in r})
        return {
            "name": name,
            "rows": rows[offset : offset + limit],
            "total": len(rows),
            "offset": offset,
            "columns": columns,
        }

    def patch_sheet(self, session_id: str, name: str, ops: list[dict[str, Any]]) -> int:
        """Apply batch edits to one sheet; returns the new row count.

        Supported ops (mirror the ragnarok session PATCH):
          - ``{"op": "set", "row": i, "column": c, "value": v}``
          - ``{"op": "addRow", "row": {...}}`` (row optional → empty)
          - ``{"op": "deleteRows", "rows": [i, ...]}``
          - ``{"op": "replace", "rows": [...]}`` (whole-sheet swap)
        """
        with self._open(session_id) as conn:
            rows = self._get_rows(conn, name)
            for op in ops:
                kind = op.get("op")
                if kind == "set":
                    i = int(op["row"])
                    if 0 <= i < len(rows):
                        rows[i] = {**rows[i], str(op["column"]): op.get("value")}
                elif kind == "addRow":
                    rows.append(dict(op.get("row") or {}))
                elif kind == "deleteRows":
                    drop = {int(i) for i in op.get("rows", [])}
                    rows = [r for i, r in enumerate(rows) if i not in drop]
                elif kind == "replace":
                    rows = [dict(r) for r in op.get("rows", [])]
                else:
                    raise ValueError(f"unknown patch op '{kind}'")
            self._put_rows(conn, name, rows)
            conn.commit()
        return len(rows)
