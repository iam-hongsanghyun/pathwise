"""Scenario configuration — the JSON *run definition*.

The workbook holds data tables; the scenario holds *what to do with them*:
economics, which cost components to price, solver tuning, and the horizon.
Validated with pydantic. It never contains tabular data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pathwise.core.entities import CapexConvention


class Economics(BaseModel):
    """Discounting / capital economics."""

    discount_rate: float = Field(default=0.08, ge=0.0, lt=1.0)
    base_year: int | None = None
    capex_convention: CapexConvention = CapexConvention.ANNUITY


class CostComponents(BaseModel):
    """Which additive cost components enter the objective."""

    capex: bool = True
    renewal: bool = True
    opex: bool = True
    commodity_cost: bool = True
    impact_price: bool = True
    measure_capex: bool = True


class SolverConfig(BaseModel):
    """Solver tuning forwarded to the backend."""

    name: str = "highs"
    threads: int = Field(default=4, ge=1)
    time_limit_s: float = Field(default=600.0, gt=0.0)
    mip_gap: float = Field(default=0.01, ge=0.0)
    seed: int = 42


class Horizon(BaseModel):
    """Modelled horizon bounds (inclusive). ``None`` ⇒ all workbook years."""

    start: int | None = None
    end: int | None = None


class ScenarioConfig(BaseModel):
    """A complete, validated run definition.

    Attributes:
        name: Human-readable scenario name.
        domain: Sector pack id (default ``"process"``).
        economics: Discounting / capital economics.
        cost_components: Cost components to price.
        solver: Solver tuning.
        horizon: Modelled horizon bounds.
        slack_penalty: Objective penalty per unit of demand/impact-cap violation.
    """

    name: str = "scenario"
    domain: str = "process"
    economics: Economics = Field(default_factory=Economics)
    cost_components: CostComponents = Field(default_factory=CostComponents)
    solver: SolverConfig = Field(default_factory=SolverConfig)
    horizon: Horizon = Field(default_factory=Horizon)
    slack_penalty: float = Field(default=1.0e9, ge=0.0)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScenarioConfig:
        """Build and validate a scenario from a plain dict."""
        return cls.model_validate(data)

    @classmethod
    def from_json(cls, path: str | Path) -> ScenarioConfig:
        """Load and validate a scenario from a JSON file."""
        with open(path, encoding="utf-8") as fh:
            return cls.model_validate(json.load(fh))
