"""The config-handshake bundle — the backend's single source of truth."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import Any

import pathwise.domains  # noqa: F401  (register built-in domains)
from pathwise import __version__
from pathwise.backends.registry import available_backends
from pathwise.config import get_settings
from pathwise.domains.base import available_domains


def _build_id(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


@lru_cache(maxsize=1)
def get_config_bundle() -> dict[str, Any]:
    """Return the cached handshake bundle (schema, domains, backends, server)."""
    settings = get_settings()
    bundle: dict[str, Any] = {
        "schemaVersion": settings.schema_version,
        "version": __version__,
        "domains": available_domains(),
        "backends": available_backends(),
        "server": {
            "solver": settings.solver_name,
            "maxSolverTimeLimitS": settings.max_solver_time_limit_s,
            "defaultMipGap": settings.default_mip_gap,
        },
    }
    bundle["buildId"] = _build_id(bundle)
    return bundle
