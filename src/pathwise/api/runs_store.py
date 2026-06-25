"""Persisted run-result store.

Run results used to live only in the in-memory :class:`~pathwise.api.jobs.JobStore`
(evicted over time, lost on restart). This store persists each completed run to a
single SQLite file (``<data_dir>/runs.db``) so a *run history* survives a refresh
and a "clear cache" can keep the runs the user **exported** while dropping the rest.

One row per run: its session, an ISO timestamp, light metadata (status / objective /
backend) for the history list, the full result JSON, and an ``exported`` flag set
when the user downloads it. ``clear(keep_exported=True)`` is the export-aware wipe.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pathwise.logger import get_logger

logger = get_logger(__name__)

#: Cap on retained runs; oldest NON-exported runs are evicted first on overflow so
#: exported (kept) history is never silently dropped.
_MAX_RUNS = 200


def _label(backend: str, status: str, objective: float | None) -> str:
    """A short human label for the history list (backend · status · objective)."""
    parts = [p for p in (backend or "run", status) if p]
    if objective is not None:
        parts.append(f"obj={objective:,.0f}")
    return " · ".join(parts)


class RunStore:
    """One SQLite file of persisted run results (bounded; exported runs kept)."""

    _COLS = ("run_id", "session_id", "created_at", "label", "backend", "status", "objective")

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS runs ("
            "run_id TEXT PRIMARY KEY, session_id TEXT, created_at TEXT, label TEXT, "
            "backend TEXT, status TEXT, objective REAL, exported INTEGER DEFAULT 0, result TEXT)"
        )
        return conn

    def save(self, session_id: str | None, result: dict[str, Any], *, backend: str = "") -> str:
        """Persist one completed run; return its new ``run_id``.

        Evicts the oldest non-exported runs when over :data:`_MAX_RUNS`.
        """
        run_id = uuid.uuid4().hex[:12]
        created = datetime.now(UTC).isoformat()
        status = str(result.get("status") or "")
        obj = result.get("objective")
        objective = float(obj) if isinstance(obj, int | float) else None
        conn = self._open()
        try:
            conn.execute(
                "INSERT INTO runs (run_id, session_id, created_at, label, backend, status, "
                "objective, exported, result) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
                (
                    run_id,
                    session_id or "",
                    created,
                    _label(backend, status, objective),
                    backend,
                    status,
                    objective,
                    json.dumps(result, ensure_ascii=False, default=str),
                ),
            )
            n = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            if n > _MAX_RUNS:
                conn.execute(
                    "DELETE FROM runs WHERE run_id IN ("
                    "SELECT run_id FROM runs WHERE exported = 0 ORDER BY created_at ASC LIMIT ?)",
                    (n - _MAX_RUNS,),
                )
            conn.commit()
        finally:
            conn.close()
        return run_id

    def list(self, session_id: str | None = None) -> list[dict[str, Any]]:
        """Light metadata for every run (newest first), optionally one session's."""
        cols = ", ".join(self._COLS) + ", exported"
        conn = self._open()
        try:
            if session_id is None:
                cur = conn.execute(f"SELECT {cols} FROM runs ORDER BY created_at DESC")
            else:
                cur = conn.execute(
                    f"SELECT {cols} FROM runs WHERE session_id = ? ORDER BY created_at DESC",
                    (session_id,),
                )
            rows = cur.fetchall()
        finally:
            conn.close()
        keys = ("runId", "sessionId", "createdAt", "label", "backend", "status", "objective")
        return [{**dict(zip(keys, r[:7], strict=True)), "exported": bool(r[7])} for r in rows]

    def get(self, run_id: str) -> dict[str, Any] | None:
        """The full result dict for one run, or ``None`` if unknown."""
        conn = self._open()
        try:
            hit = conn.execute("SELECT result FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        finally:
            conn.close()
        return json.loads(hit[0]) if hit else None

    def mark_exported(self, run_id: str) -> bool:
        """Flag a run as exported (so a clear keeps it); ``True`` if it existed."""
        conn = self._open()
        try:
            cur = conn.execute("UPDATE runs SET exported = 1 WHERE run_id = ?", (run_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def delete(self, run_id: str) -> bool:
        """Remove one run; ``True`` if it existed."""
        conn = self._open()
        try:
            cur = conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def clear(self, session_id: str | None = None, keep_exported: bool = True) -> int:
        """Delete runs; return how many were removed.

        Args:
            session_id: Limit to one session (``None`` ⇒ all sessions).
            keep_exported: Preserve runs the user exported (the default — this is
                the "clear cache except exported" semantics).
        """
        query = "DELETE FROM runs WHERE 1 = 1"
        params: list[Any] = []
        if keep_exported:
            query += " AND exported = 0"
        if session_id is not None:
            query += " AND session_id = ?"
            params.append(session_id)
        conn = self._open()
        try:
            cur = conn.execute(query, params)
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def clear_all(self) -> int:
        """Delete every run, exported or not."""
        return self.clear(keep_exported=False)
