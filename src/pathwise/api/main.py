"""FastAPI application for pathwise.

A deliberately minimal, **stateless** HTTP surface — the sole coupling between any
frontend and any backend:

* ``GET  /api/health``      — liveness for the launcher/ops.
* ``GET  /api/config``      — handshake: server-side config + domain/backend caps.
* ``POST /api/run``         — send the entire model + scenario; get a job id.
* ``GET  /api/run/{id}``    — poll until done to receive the entire result.
* ``DELETE /api/run/{id}``  — cancel.

The backend reads no files and owns no data: everything arrives in the request and
the whole result returns in the response.
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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
def config() -> dict[str, Any]:
    return get_config_bundle()


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
