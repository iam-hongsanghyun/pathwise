"""Asynchronous solve-job store.

Runs solves on a bounded thread pool and tracks their status so the HTTP layer
can return immediately and let the client poll. HiGHS releases the GIL during
the solve, so threads give real concurrency while keeping the store simple and
robust (no inter-process import cost or spawn fragility).

Cancellation is best-effort: a queued job is cancelled outright; a running
job is flagged and its result discarded on completion. (Hard pre-emption would
require process isolation — a deliberate future enhancement.)
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from threading import Lock
from typing import Any

from pathwise.config import get_settings
from pathwise.logger import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class Job:
    """A single solve job and its lifecycle state."""

    id: str
    future: Future
    status: str = "running"  # running | done | error | cancelled
    result: dict[str, Any] | None = None
    error: str | None = None
    cancelled: bool = field(default=False)


class JobStore:
    """A bounded thread-pool store for solve jobs."""

    def __init__(self, max_workers: int | None = None) -> None:
        workers = max_workers or get_settings().max_jobs
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pathwise-solve")
        self._jobs: dict[str, Job] = {}
        self._lock = Lock()

    def submit(self, fn: Callable[..., dict[str, Any]], *args: Any) -> str:
        """Submit a solve callable; return the new job id."""
        self._prune()
        job_id = uuid.uuid4().hex[:12]
        future = self._pool.submit(fn, *args)
        job = Job(id=job_id, future=future)
        future.add_done_callback(partial(self._on_done, job_id))
        with self._lock:
            self._jobs[job_id] = job
        return job_id

    def _on_done(self, job_id: str, future: Future) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.cancelled:
                return
            if future.cancelled():
                job.status = "cancelled"
                return
            exc = future.exception()
            if exc is not None:
                job.status = "error"
                job.error = str(exc)
                logger.error("job %s failed: %s", job_id, exc)
            else:
                job.status = "done"
                job.result = future.result()

    def get(self, job_id: str) -> dict[str, Any] | None:
        """Return the current ``{status, result?, error?}`` for ``job_id``."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            payload: dict[str, Any] = {"jobId": job_id, "status": job.status}
            if job.status == "done":
                payload["result"] = job.result
            elif job.status == "error":
                payload["error"] = job.error
            return payload

    def cancel(self, job_id: str) -> bool:
        """Cancel a job (best-effort). Returns ``True`` if it was known."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            job.cancelled = True
            job.status = "cancelled"
            job.future.cancel()
            return True

    def _prune(self) -> None:
        with self._lock:
            stale = [
                j for j, job in self._jobs.items() if job.status in ("done", "error", "cancelled")
            ]
            for j in stale:
                self._jobs.pop(j, None)
