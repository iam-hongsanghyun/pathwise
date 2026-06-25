"""Scenario configuration — the JSON *run definition*.

The workbook holds data tables; the scenario holds *what to do with them*:
economics, which cost components to price, solver tuning, and the horizon.
Validated with pydantic. It never contains tabular data.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from pathwise.core.entities import CapexConvention


class Economics(BaseModel):
    """Discounting / capital economics."""

    # Optional so the model's own `meta.discount_rate` can supply it when a run
    # doesn't override; assemble resolves None → meta → 0.08.
    discount_rate: float | None = Field(default=None, ge=0.0, lt=1.0)
    base_year: int | None = None
    # NPV (full discounted lump at the event year) is the engine's long-standing
    # behaviour and stays the default; ANNUITY (capital-recovery annuity over the
    # asset life) is opt-in — see ``Problem.capex_charge``.
    capex_convention: CapexConvention = CapexConvention.NPV


class CostComponents(BaseModel):
    """Which additive cost components enter the objective."""

    capex: bool = True
    renewal: bool = True
    opex: bool = True
    flow_cost: bool = True
    impact_price: bool = True
    lever_capex: bool = True


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


class PortfolioConfig(BaseModel):
    """Settings for the ``portfolio`` backend (risk-vs-reward allocation).

    Attributes:
        method: Allocation algorithm.
        reward_mode: Whether an asset's reward is profit or cost-reduction.
        asset_level: Granularity at which candidate transitions become assets.
        n_scenarios: Monte-Carlo sample size (clamped by the server cap).
        volatility: Per-category lognormal volatility ``σ`` [—]; empty ⇒ engine
            defaults.
        normalize_by_capex: Express rewards as return-on-capital.
        risk_aversion: MVO/Black-Litterman risk aversion ``δ`` [1/reward unit].
        target_return: If set (MVO/BL), minimise risk subject to this return.
        cvar_alpha: CVaR confidence level ``β`` [—].
        bl_views: Black-Litterman absolute views ``{asset_id: expected reward}``.
        bl_tau: Black-Litterman prior-uncertainty scalar ``τ`` [—].
    """

    method: str = Field(default="mvo", pattern="^(mvo|cvar|hrp|black_litterman)$")
    reward_mode: str = Field(default="cost_reduction", pattern="^(profit|cost_reduction)$")
    asset_level: str = Field(default="facility", pattern="^(facility|technology|company|economy)$")
    n_scenarios: int = Field(default=2000, ge=2)
    volatility: dict[str, float] = Field(default_factory=dict)
    normalize_by_capex: bool = True
    risk_aversion: float = Field(default=1.0, ge=0.0)
    target_return: float | None = None
    cvar_alpha: float = Field(default=0.95, gt=0.0, lt=1.0)
    bl_views: dict[str, float] = Field(default_factory=dict)
    bl_tau: float = Field(default=0.05, gt=0.0)


class Coupling(BaseModel):
    """How independently-optimised hierarchy nodes couple across their boundary.

    Used when ``optimisation_scope`` cuts a node tree into independent problems:
    cross-cut connections become value-chain coupling links carrying these
    signals, resolved by ``iterations`` of damped feedback.

    Attributes:
        signals: Subset of ``price`` / ``marginal_price`` / ``carbon_intensity``
            / ``volume``.
        iterations: Forward passes (``1`` = forward-only; ``>1`` enables feedback).
        damping: Relaxation on fed-back demand, ``0 < damping ≤ 1``.
        default_lag: Lag [yr] applied to a connection that does not set its own.
    """

    signals: list[str] = Field(default_factory=lambda: ["price"])
    iterations: int = Field(default=1, ge=1)
    damping: float = Field(default=0.5, gt=0.0, le=1.0)
    default_lag: int = Field(default=0, ge=0)


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
        portfolio: Settings for the ``portfolio`` backend (ignored by ``linopy``).
    """

    name: str = "scenario"
    domain: str = "process"
    economics: Economics = Field(default_factory=Economics)
    cost_components: CostComponents = Field(default_factory=CostComponents)
    solver: SolverConfig = Field(default_factory=SolverConfig)
    horizon: Horizon = Field(default_factory=Horizon)
    slack_penalty: float = Field(default=1.0e9, ge=0.0)
    portfolio: PortfolioConfig = Field(default_factory=PortfolioConfig)
    coupling: Coupling = Field(default_factory=Coupling)
    # The designed level the optimisation is performed at (a value-chain level
    # name, or ``system`` for the whole model). Each node at that level is an
    # optimisation *unit* carrying its whole subtree (downstream is part of its
    # problem; upper levels roll up the sum). Free text so any level is selectable.
    optimisation_scope: str = "company"
    # Which units (node ids) at ``optimisation_scope`` to optimise; empty ⇒ all.
    optimisation_targets: list[str] = Field(default_factory=list)
    # How the selected units are solved:
    #   ``valuechain``  — in series, upstream → downstream, coupled (the cascade:
    #                     a unit is optimised before the units it feeds);
    #   ``joint``       — all selected units solved together as one problem;
    #   ``independent`` — each unit solved on its own, no coupling (it trades with
    #                     the market). A single unit is always solved on its own.
    optimisation_mode: str = Field(default="valuechain", pattern="^(valuechain|joint|independent)$")
    # Default optimisation goal applied to every company that doesn't override it via
    # the ``company_config`` sheet: ``cost`` (minimise discounted cost) or ``profit``
    # (maximise revenue − cost). The Optimisation tab's "goal" selector sets this.
    objective: str = Field(default="cost", pattern="^(cost|profit)$")
    # LCIA-aware objective: minimise ``cost_weight·cost + impact_weight·Σ
    # emit[objective_impact]``. Defaults reproduce plain least-cost. Set
    # ``objective_impact`` (an impact/characterised-category id) with a positive
    # ``impact_weight`` to put a shadow price on that category; set ``cost_weight``
    # small (e.g. 0 or 1e-6) to minimise the impact directly with cost as a
    # tie-breaker. A cost-vs-impact Pareto frontier sweeps these (or the cap).
    objective_impact: str | None = None
    impact_weight: float = Field(default=0.0, ge=0.0)
    cost_weight: float = Field(default=1.0, ge=0.0)
    # Active model-resident variant (its ``variant_id``) to FORCE for an optimise
    # run: the optimiser pins that variant's interventions (a forced transition,
    # price/lever change) and optimises everything else. ``None`` ⇒ a plain
    # free optimisation. The simulator ignores this (it compares every variant).
    variant: str | None = None
    # Project-level unit-rate overrides, layered over the global ``units.yaml`` when
    # the model is assembled (the project beats the global rates). Same shape as
    # ``units.yaml``'s ``custom_units`` — either the list directly, or a dict
    # ``{"custom_units": [...]}`` — e.g. a project with its own FX rate sets
    # ``["KRW = USD / 1200"]``. Empty ⇒ use the global rates unchanged. Carried with
    # the project bundle so a project travels with its own conversion rates.
    unit_overrides: dict[str, Any] | list[Any] = Field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScenarioConfig:
        """Build and validate a scenario from a plain dict."""
        return cls.model_validate(data)
