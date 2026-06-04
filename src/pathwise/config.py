"""Application configuration loaded from environment / ``.env``.

All runtime knobs live here so that nothing is hardcoded elsewhere in the
package (per the project convention in ``CLAUDE.md``). Every field below has a
matching entry in ``.env.example``.

The values here are *server / runtime* defaults — they are not model data.
Per-run model parameters (discount rate, carbon price, solver tuning, ...) can
be overridden by a scenario JSON; the values here are the fallbacks used when a
scenario does not specify them.

Example:
    >>> from pathwise.config import get_settings
    >>> settings = get_settings()
    >>> settings.default_discount_rate
    0.08
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Repository root (…/pathwise), used to resolve default relative paths.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Typed application settings.

    Attributes are populated from environment variables prefixed with
    ``PATHWISE_`` (case-insensitive) or a local ``.env`` file. Unset attributes
    fall back to the defaults below.
    """

    model_config = SettingsConfigDict(
        env_prefix="PATHWISE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Paths ────────────────────────────────────────────────────────────────
    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    output_dir: Path = Field(default=PROJECT_ROOT / "output")
    scenario_dir: Path = Field(default=PROJECT_ROOT / "scenarios")
    output_pattern: str = Field(default="output/output_{timestamp}.xlsx")

    # ── Schema / domain ──────────────────────────────────────────────────────
    schema_version: str = Field(default="1.0")
    default_domain: str = Field(default="shipping")
    default_backend: str = Field(default="linopy")

    # ── Economics (CRF / discounting fallbacks) ──────────────────────────────
    default_discount_rate: float = Field(default=0.08, ge=0.0, lt=1.0)
    default_carbon_price: float = Field(default=0.0, ge=0.0)
    default_measure_lifetime_years: int = Field(default=15, ge=1)
    default_newbuild_lifetime_years: int = Field(default=25, ge=1)
    base_period: int = Field(default=2025)
    currency: str = Field(default="USD")
    noncompliance_rate: float = Field(default=380.0, ge=0.0)

    # ── Solver ───────────────────────────────────────────────────────────────
    solver_name: str = Field(default="highs")
    solver_threads: int = Field(default=4, ge=1)
    solver_time_limit_s: int = Field(default=600, ge=1)
    solver_mip_gap: float = Field(default=0.01, ge=0.0)

    # ── Runtime / behaviour ──────────────────────────────────────────────────
    random_seed: int = Field(default=42)
    impute_intensity: bool = Field(default=True)
    max_jobs: int = Field(default=4, ge=1)
    log_buffer_size: int = Field(default=2000, ge=1)
    log_level: str = Field(default="INFO")
    verbose: bool = Field(default=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton (cached).

    Returns:
        The cached settings instance built from the environment / ``.env``.
    """
    return Settings()
