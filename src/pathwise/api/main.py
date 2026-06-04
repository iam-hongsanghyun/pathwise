"""FastAPI application for pathwise.

A deliberately minimal, **stateless** HTTP surface — the sole coupling between
any frontend and any backend:

* ``GET  /api/config``       — the backend handshake (one true source of
  server-side config + sector/solver capabilities).
* ``POST /api/run``          — send the entire model + scenario; get a job id.
* ``GET  /api/run/{id}``     — poll once the job is done to receive the entire
  result (validation included).
* ``DELETE /api/run/{id}``   — cancel a running job.

``/api/health`` and ``/api/status`` exist only for the launcher/ops.

The backend reads no files and owns no data: all data arrives in the request
body and the whole result is returned in the response. Any frontend that speaks
this contract can drive it; any backend that serves it can replace this one.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import pathwise.domains  # noqa: F401  (register built-in domains)
from pathwise import __version__
from pathwise.api.config_provider import get_config_bundle
from pathwise.api.jobs import JobStore
from pathwise.api.models import RunPayload
from pathwise.backends.registry import get_backend
from pathwise.logger import get_logger

logger = get_logger(__name__)

app = FastAPI(title="pathwise", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_jobs = JobStore()


def _solve(payload: dict[str, Any]) -> dict[str, Any]:
    """Job body: resolve the backend and run one case (validation included)."""
    options = payload.get("options") or {}
    backend = get_backend(options.get("backend"))
    return backend.run(payload["model"], payload.get("scenario", {}), options)


# ── Ops ────────────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
def status() -> dict[str, Any]:
    bundle = get_config_bundle()
    return {"ready": True, "buildId": bundle["buildId"], "version": __version__}


# ── Handshake (one true source of backend-side config) ──────────────────────────
@app.get("/api/config")
def config() -> dict[str, Any]:
    return get_config_bundle()


# ── Run: the only data exchange (send model → receive entire result) ────────────
@app.post("/api/run")
def run(payload: RunPayload) -> dict[str, Any]:
    job_id = _jobs.submit(_solve, payload.model_dump())
    return {"jobId": job_id, "status": "running"}


@app.get("/api/run/{job_id}")
def run_status(job_id: str) -> dict[str, Any]:
    state = _jobs.get(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"unknown job '{job_id}'")
    return state


@app.delete("/api/run/{job_id}")
def cancel(job_id: str) -> dict[str, Any]:
    if not _jobs.cancel(job_id):
        raise HTTPException(status_code=404, detail=f"unknown job '{job_id}'")
    return {"jobId": job_id, "status": "cancelled"}
