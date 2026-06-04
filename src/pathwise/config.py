"""Backend (server-side) configuration loaded from environment / ``.env``.

This file is the **single source of truth for server-side configuration only** —
things the operator controls and the user cannot: solver resource limits, job
concurrency, logging, and the serving host/port.

It deliberately holds **no model parameters** (discount rate, carbon price,
lifetimes, currency, feature toggles, …). Those are *user-definable* and belong
to the frontend, which sends them inside the scenario on every run. Keeping the
two homes separate (server-side here, user-definable in the frontend) is what
lets the backend stay stateless and independently replaceable.

Every field below has a matching entry in ``.env.example``.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed server-side settings (env prefix ``PATHWISE_``)."""

    model_config = SettingsConfigDict(
        env_prefix="PATHWISE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Serving ──────────────────────────────────────────────────────────────
    # 8077 by default to avoid clashing with other local services (e.g. pypsa
    # on 8000). Override with PATHWISE_PORT; the launcher keeps the frontend
    # proxy in sync via PATHWISE_BACKEND_URL.
    host: str = "127.0.0.1"
    port: int = 8077

    # ── Solver resource limits (server-controlled; clamp user requests) ───────
    solver_name: str = "highs"
    solver_threads: int = 4
    max_solver_time_limit_s: int = 1800
    default_mip_gap: float = 0.01

    # ── Jobs / logging ───────────────────────────────────────────────────────
    max_jobs: int = 4
    log_buffer_size: int = 2000
    log_level: str = "INFO"

    # ── Backend identity ─────────────────────────────────────────────────────
    schema_version: str = "1.0"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton (cached)."""
    return Settings()
