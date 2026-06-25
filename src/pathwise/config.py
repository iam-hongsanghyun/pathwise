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
    # Allowed CORS origins. Default ``["*"]`` suits local single-user development;
    # set an explicit list (JSON array in the env var) for a shared deployment.
    cors_origins: list[str] = ["*"]

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
    # Bundled static assets that ship inside the backend package (read server-side;
    # the frontend never parses files itself and never serves them statically).
    examples_dir: str = str(_ASSETS / "examples")
    # Importable libraries, auto-discovered: <libraries_dir>/<tier>/<id>.json, each
    # a workbook bundling components + a network. Tier = the subfolder name
    # (base / example / project). Dropping a JSON in here is enough — no index.
    libraries_dir: str = str(_ASSETS / "libraries")
    # Network specs (a DAG of coupled stage-models) + their stage workbooks.
    value_chains_dir: str = str(_ASSETS / "value_chains")
    # Read-only STARTER component libraries that ship with the package; copied
    # into the writable <data_dir>/component_libraries on first access so a fresh
    # install opens with real, editable content (see the component_libraries
    # router). User-created libraries never touch this directory.
    component_seeds_dir: str = str(_ASSETS / "component_seeds")
    # Bundled DEFAULT unit system (canonical bases, allowed picker units, custom
    # unit definitions). Copied to a writable <data_dir>/units.yaml on first edit;
    # reads fall back to this seed until then (see src/pathwise/units.py).
    units_seed: str = str(_ASSETS / "units.yaml")
    # Paging cap for session sheet reads.
    max_sheet_page: int = 1000

    # ── Logging ──────────────────────────────────────────────────────────────
    log_level: str = "INFO"

    # ── Backend identity ─────────────────────────────────────────────────────
    schema_version: str = "1.0"

    # ── Security ───────────────────────────────────────────────────────────────
    # Optional token guarding destructive global endpoints (e.g. POST
    # /api/cache/clear, which wipes ALL sessions). Empty (the default) leaves them
    # open — correct for the local-first single-user app. Set it in any shared /
    # multi-tenant deployment; callers must then send a matching ``X-Admin-Token``.
    admin_token: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton (cached)."""
    return Settings()
