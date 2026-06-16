"""FastAPI application for pathwise.

The backend is the single source of truth (the ragnarok pattern): the working
model lives in a server-side **session**, files are parsed/written here, and a
run is submitted by ``sessionId`` — the model never has to travel from the
browser.

* ``GET  /api/health``                — liveness for the launcher/ops.
* ``GET  /api/config``                — handshake: config + domain/backend caps.
* ``/api/session/*``                  — server-held working model (ingest, page,
  patch, upload/export xlsx, load example, insert library template).
* ``POST /api/run``                   — run by ``sessionId`` (or inline model).
* ``GET/DELETE /api/run/{id}``        — poll / cancel.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import pathwise.domains  # noqa: F401  (register built-in domains)
from pathwise import __version__
from pathwise.api.config_provider import get_config_bundle
from pathwise.api.jobs import JobStore
from pathwise.api.models import RunPayload
from pathwise.api.routers.component_libraries import router as component_libraries_router
from pathwise.api.routers.session import router as session_router
from pathwise.api.session_store import SessionStore
from pathwise.backends.registry import get_backend
from pathwise.config import get_settings
from pathwise.logger import get_logger

logger = get_logger(__name__)

app = FastAPI(title="pathwise", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(session_router)
app.include_router(component_libraries_router)

_jobs = JobStore()


def _solve(payload: dict[str, Any]) -> dict[str, Any]:
    """Job body: resolve the model (session or inline) and run one case."""
    options = payload.get("options") or {}
    model = payload.get("model") or {}
    session_id = payload.get("sessionId")
    if session_id and not model:
        store = SessionStore(Path(get_settings().data_dir) / "sessions")
        model = store.get_model(session_id)
    backend = get_backend(options.get("backend"))
    return backend.run(model, payload.get("scenario", {}), options)


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
