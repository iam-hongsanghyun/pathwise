"""Config bundle served to the frontend, with a build-id cache key.

The bundle describes everything the UI needs to render: the registered sector
packs (their schema + terminology), the available solver backends, and runtime
defaults. ``build_id`` is a content hash so the frontend can cache the bundle
and invalidate it when the backend changes.
"""

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
    """Return the cached config bundle (schema, domains, backends, defaults, build_id)."""
    settings = get_settings()
    domains = available_domains()
    backends = available_backends()
    defaults = {
        "domain": settings.default_domain,
        "backend": settings.default_backend,
        "discountRate": settings.default_discount_rate,
        "carbonPrice": settings.default_carbon_price,
        "currency": settings.currency,
        "solver": {
            "name": settings.solver_name,
            "threads": settings.solver_threads,
            "timeLimitS": settings.solver_time_limit_s,
            "mipGap": settings.solver_mip_gap,
        },
    }
    bundle = {
        "schemaVersion": settings.schema_version,
        "version": __version__,
        "domains": domains,
        "backends": backends,
        "defaults": defaults,
    }
    bundle["buildId"] = _build_id(bundle)
    return bundle
