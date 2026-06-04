"""In-memory async job store for runs.

Runs execute on a background thread; clients poll for the whole result. Stateless
across the wire — the store holds only transient job state for the current process.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from typing import Any

from pathwise.logger import get_logger

logger = get_logger(__name__)

Job = Callable[[dict[str, Any]], dict[str, Any]]


class JobStore:
    """Tracks background run jobs by id."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def submit(self, fn: Job, payload: dict[str, Any]) -> str:
        """Start ``fn(payload)`` on a background thread; return the job id."""
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {"jobId": job_id, "status": "running", "result": None}

        def _work() -> None:
            try:
                result = fn(payload)
                self._set(job_id, status="done", result=result)
            except Exception as exc:
                logger.exception("job %s failed", job_id)
                self._set(job_id, status="error", error=str(exc))

        threading.Thread(target=_work, daemon=True).start()
        return job_id

    def _set(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(fields)

    def get(self, job_id: str) -> dict[str, Any] | None:
        """Return the current job state, or ``None`` if unknown."""
        with self._lock:
            state = self._jobs.get(job_id)
            return dict(state) if state is not None else None

    def cancel(self, job_id: str) -> bool:
        """Mark a job cancelled (best-effort; the thread is daemonic)."""
        with self._lock:
            if job_id not in self._jobs:
                return False
            self._jobs[job_id]["status"] = "cancelled"
            return True
