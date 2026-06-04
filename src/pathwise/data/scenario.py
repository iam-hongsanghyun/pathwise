"""Scenario configuration — the JSON *run definition*.

The workbook holds data tables; the scenario holds *what to do with them*:
which named sets to select, which features to enable, the economics, which cost
components to price, solver tuning, and the horizon. This mirrors the ``ets``
scenario pattern and is validated with pydantic.

The scenario references data by *name* (e.g. ``target_set: "Tier1"``); it never
contains tabular data itself. Resolving those names against a workbook is the
job of a sector pack's ``build_problem``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pathwise.core.entities import CapexConvention


class Selection(BaseModel):
    """Named data sets to use for this run."""

    asset_group: str | None = None
    target_set: str | None = None
    bound_set: str | None = None
    carbon_price_set: str | None = None
    activity_scenario: str | None = None


class Features(BaseModel):
    """Feature switches that shape the model build."""

    include_measures: bool = True
    include_new_build: bool = True
    include_transitions: bool = True
    include_capex: bool = True
    include_carbon_price: bool = True
    include_blend_bounds: bool = True
    include_carrier_limits: bool = True


class Economics(BaseModel):
    """Discounting / lifetime economics."""

    discount_rate: float = Field(default=0.08, ge=0.0, lt=1.0)
    base_period: int | None = None
    capex_convention: CapexConvention = CapexConvention.ANNUITY
    default_measure_lifetime: int = Field(default=15, ge=1)
    default_newbuild_lifetime: int = Field(default=25, ge=1)
    currency: str = "USD"


class CostComponents(BaseModel):
    """Which additive cost components enter the objective."""

    carrier_cost: bool = True
    fixed_opex: bool = True
    transition_capex: bool = True
    measure_capex: bool = True
    newbuild_capex: bool = True
    carbon_cost: bool = True


class SolverConfig(BaseModel):
    """Solver tuning forwarded to the backend."""

    name: str = "highs"
    threads: int = Field(default=4, ge=1)
    time_limit_s: float = Field(default=600.0, gt=0.0)
    mip_gap: float = Field(default=0.01, ge=0.0)
    seed: int = 42


class Horizon(BaseModel):
    """Modelled horizon bounds (inclusive). ``None`` ⇒ use all workbook years."""

    start: int | None = None
    end: int | None = None


class ScenarioConfig(BaseModel):
    """A complete, validated run definition.

    Attributes:
        name: Human-readable scenario name.
        domain: Sector pack id (e.g. ``"shipping"``).
        workbook: Optional path to the data workbook (when run from disk).
        selection: Named data sets to use.
        features: Feature switches.
        economics: Discounting / lifetime economics.
        cost_components: Cost components to price.
        solver: Solver tuning.
        horizon: Modelled horizon bounds.
        max_transitions_per_asset: Retrofit-count cap per asset.
        min_dwell_years: Minimum asset age before a retrofit is allowed.
        slack_penalty: Objective penalty per unit of demand/target slack.
    """

    name: str = "scenario"
    domain: str = "shipping"
    workbook: str | None = None
    selection: Selection = Field(default_factory=Selection)
    features: Features = Field(default_factory=Features)
    economics: Economics = Field(default_factory=Economics)
    cost_components: CostComponents = Field(default_factory=CostComponents)
    solver: SolverConfig = Field(default_factory=SolverConfig)
    horizon: Horizon = Field(default_factory=Horizon)
    max_transitions_per_asset: int = Field(default=1, ge=0)
    min_dwell_years: int = Field(default=0, ge=0)
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
