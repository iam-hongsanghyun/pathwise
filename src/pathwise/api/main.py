"""FastAPI application for pathwise (stateless).

Scaffolding: exposes ``/api/health`` and ``/api/config``. The run endpoints
(``POST /api/run`` + polling) and domain/backend dispatch land in P3.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pathwise import __version__
from pathwise.config import get_settings

app = FastAPI(title="pathwise", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness probe used by the launcher."""
    return {"status": "ok"}


@app.get("/api/config")
def config() -> dict[str, Any]:
    """Handshake: server-side truths only (no model defaults).

    Domains and backends are added in P3 once they exist.
    """
    settings = get_settings()
    return {
        "schemaVersion": settings.schema_version,
        "version": __version__,
        "domains": [],
        "backends": [],
        "server": {
            "solver": settings.solver_name,
            "maxSolverTimeLimitS": settings.max_solver_time_limit_s,
            "defaultMipGap": settings.default_mip_gap,
        },
    }
