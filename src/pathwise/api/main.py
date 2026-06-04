"""FastAPI application for pathwise.

Exposes the config bundle, sector packs, solver backends, workbook
validation/parsing, and asynchronous solve jobs (submit → poll → result),
plus result export. One async API with ``options`` flags replaces the legacy
collection of near-duplicate entry scripts.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

import pathwise.domains  # noqa: F401  (register built-in domains)
from pathwise import __version__
from pathwise.api.config_provider import get_config_bundle
from pathwise.api.jobs import JobStore
from pathwise.api.models import RunPayload, ValidatePayload
from pathwise.backends.registry import available_backends, get_backend
from pathwise.data.workbook import read_workbook
from pathwise.domains.base import DomainError, available_domains, get_domain
from pathwise.logger import get_logger
from pathwise.results.export import result_to_xlsx_bytes

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
    """Job body: resolve the backend and run one case."""
    options = payload.get("options") or {}
    backend = get_backend(options.get("backend"))
    return backend.run(payload["model"], payload.get("scenario", {}), options)


# ── Meta / discovery ──────────────────────────────────────────────────────────
@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
def status() -> dict[str, Any]:
    bundle = get_config_bundle()
    return {"ready": True, "buildId": bundle["buildId"], "version": __version__}


@app.get("/api/config")
def config() -> dict[str, Any]:
    return get_config_bundle()


@app.get("/api/domains")
def domains() -> list[dict[str, Any]]:
    return available_domains()


@app.get("/api/domains/{domain_id}/schema")
def domain_schema(domain_id: str) -> dict[str, Any]:
    try:
        pack = get_domain(domain_id)
    except DomainError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "name": pack.name,
        "label": pack.label,
        "terminology": pack.terminology(),
        "requiredSheets": pack.required_sheets(),
        "schema": pack.schema(),
    }


@app.get("/api/backends")
def backends() -> list[dict[str, Any]]:
    return available_backends()


# ── Validation / workbook parse ────────────────────────────────────────────────
@app.post("/api/validate")
def validate(payload: ValidatePayload) -> dict[str, Any]:
    domain_id = payload.options.get("domain") or payload.scenario.get("domain")
    try:
        pack = get_domain(domain_id)
    except DomainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    report = pack.validate(payload.model)
    return {"ok": report.ok, **report.as_dict()}


@app.post("/api/workbook/parse")
async def parse_workbook(file: UploadFile) -> dict[str, Any]:
    data = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(data)
        path = Path(tmp.name)
    try:
        workbook = read_workbook(path)
    finally:
        path.unlink(missing_ok=True)
    return {"model": workbook}


# ── Run (async) ─────────────────────────────────────────────────────────────────
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


# ── Export ───────────────────────────────────────────────────────────────────────
@app.post("/api/export/xlsx")
def export_xlsx(result: dict[str, Any]) -> Response:
    content = result_to_xlsx_bytes(result)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=pathwise_result.xlsx"},
    )
