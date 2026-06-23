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
from pathwise.progress import ProgressFn

logger = get_logger(__name__)

#: A job body: ``fn(payload, report)`` where ``report`` is the progress callback
#: it may call to publish completed / total counts as the run proceeds.
Job = Callable[[dict[str, Any], ProgressFn], dict[str, Any]]

#: Cap on retained jobs. Terminal (done/error/cancelled) jobs beyond this are
#: evicted oldest-first on submit so a long-running server doesn't grow without
#: bound (each finished job may hold a full result payload).
_MAX_JOBS = 256

_TERMINAL = frozenset({"done", "error", "cancelled"})


class JobStore:
    """Tracks background run jobs by id (bounded, oldest terminal jobs evicted)."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _evict_locked(self) -> None:
        """Drop oldest terminal jobs while over capacity (caller holds the lock)."""
        while len(self._jobs) > _MAX_JOBS:
            for jid, job in self._jobs.items():
                if job.get("status") in _TERMINAL:
                    del self._jobs[jid]
                    break
            else:
                break  # nothing terminal to evict (all still running)

    def submit(self, fn: Job, payload: dict[str, Any]) -> str:
        """Start ``fn(payload)`` on a background thread; return the job id."""
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {
                "jobId": job_id,
                "status": "running",
                "result": None,
                "progress": None,
            }
            self._evict_locked()

        def report(done: int, total: int, label: str = "") -> None:
            """Publish a completed/total snapshot for this job (best-effort)."""
            self._set(job_id, progress={"done": done, "total": total, "label": label})

        def _work() -> None:
            try:
                result = fn(payload, report)
                self._set(job_id, status="done", result=result)
            except Exception as exc:
                logger.exception("job %s failed", job_id)
                self._set(job_id, status="error", error=str(exc))

        threading.Thread(target=_work, daemon=True).start()
        return job_id

    def _set(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            # Don't resurrect a cancelled job: a worker finishing just after a
            # DELETE must not overwrite "cancelled" with "done"/"error".
            if job is not None and job.get("status") != "cancelled":
                job.update(fields)

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
