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
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

#: Bundled assets ship inside the backend package, so their default paths are
#: resolved relative to it (not the CWD) and survive an installed deployment.
_ASSETS = Path(__file__).resolve().parent / "assets"


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
    # Stream the HiGHS solver log to the server terminal (so the optimisation is
    # visible). Set PATHWISE_SOLVER_VERBOSE=false to silence it.
    solver_verbose: bool = True
    # HiGHS global scaling (log2 exponents). Real workbooks carry energy/material
    # flows that span many orders of magnitude; without scaling HiGHS can hit an
    # internal_solver_error. These are an exact, solution-preserving transform.
    highs_user_bound_scale: int = -8
    highs_user_objective_scale: int = -10

    # ── Portfolio backend (server-controlled; clamps user requests) ───────────
    max_portfolio_scenarios: int = 50000

    # ── Server-side data (ragnarok pattern: the backend owns the model) ───────
    # Working sessions (one SQLite file each) live under <data_dir>/sessions.
    data_dir: str = "data"
    # Bundled example workbooks + the facility-template library — static assets
    # that ship inside the backend package (read server-side; the frontend never
    # parses files itself and never serves them statically).
    examples_dir: str = str(_ASSETS / "examples")
    library_dir: str = str(_ASSETS / "library")
    # Value-chain specs (a DAG of coupled stage-models) + their stage workbooks.
    value_chains_dir: str = str(_ASSETS / "value_chains")
    # Read-only STARTER component libraries that ship with the package; copied
    # into the writable <data_dir>/component_libraries on first access so a fresh
    # install opens with real, editable content (see the component_libraries
    # router). User-created libraries never touch this directory.
    component_seeds_dir: str = str(_ASSETS / "component_libraries")
    # Paging cap for session sheet reads.
    max_sheet_page: int = 1000

    # ── Jobs / logging ───────────────────────────────────────────────────────
    max_jobs: int = 4
    log_level: str = "INFO"

    # ── Backend identity ─────────────────────────────────────────────────────
    schema_version: str = "1.0"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton (cached)."""
    return Settings()
