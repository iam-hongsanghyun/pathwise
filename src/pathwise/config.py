"""Backend (server-side) configuration loaded from environment / ``.env``.

Single source of truth for **server-side configuration only** — solver resource
limits, job concurrency, logging, and the serving host/port. It holds **no model
parameters** (prices, lifetimes, caps, discount rate, toggles): those are
user-definable and travel inside the scenario on every run, which keeps the
backend stateless and independently replaceable.

Every field has a matching entry in ``.env.example``.
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
    host: str = "127.0.0.1"
    port: int = 8077

    # ── Solver resource limits (server-controlled; clamp user requests) ───────
    solver_name: str = "highs"
    solver_threads: int = 4
    max_solver_time_limit_s: int = 1800
    default_mip_gap: float = 0.01
    # HiGHS global scaling (log2 exponents). Real workbooks carry energy/material
    # flows that span many orders of magnitude; without scaling HiGHS can hit an
    # internal_solver_error. These are an exact, solution-preserving transform.
    highs_user_bound_scale: int = -8
    highs_user_objective_scale: int = -10

    # ── Jobs / logging ───────────────────────────────────────────────────────
    max_jobs: int = 4
    log_level: str = "INFO"

    # ── Backend identity ─────────────────────────────────────────────────────
    schema_version: str = "1.0"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton (cached)."""
    return Settings()
