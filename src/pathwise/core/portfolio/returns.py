"""Per-asset reward under each Monte-Carlo scenario.

Builds the ``(n_scenarios × n_assets)`` reward matrix that feeds the portfolio
optimisers. The reward of switching a facility is computed from the *same* cost
terms as the deterministic objective (discounted opex + purchased inputs −
sales + priced impacts + one-off switch capex), re-priced under each scenario's
shocks.

Because the running cost is **linear** in each shocked input category, we
precompute four scenario-independent "cost bases" per technology and combine
them with the shock arrays — so the whole matrix is built with vectorised NumPy,
no per-scenario Python loop.

Algorithm:
    For technology ``k`` run at capacity ``Q`` over horizon years ``t`` with
    discount factor ``DF_t`` and duration ``d_t``, define the running cost

    $$C_k(\\xi) = \\xi^{op} O_k + \\xi^{cp} B_k - \\xi^{sp} S_k + \\xi^{ip} I_k$$

    ASCII: C_k = xi_op*O_k + xi_cp*B_k - xi_sp*S_k + xi_ip*I_k

    with bases (all [currency], summed over t as ``DF_t·d_t·(...)``):
      O_k = opex_k·Q ; B_k = Σ_r in_r·Q·price_r ; S_k = Σ_r out_r·Q·sale_r ;
      I_k = Σ_i (direct_i + Σ_r in_r·cf_{r,i})·Q·iprice_i
    and shocks ``xi_op, xi_cp, xi_sp, xi_ip`` [—] for opex / commodity price /
    sale price / impact price. The one-off switch cost is
    ``K = DF_{t0}·capex_per_capacity·Q`` scaled by the capex shock ``xi_cap``.

    Per asset ``a`` (a group of candidates) and scenario ``s`` the reward is:
      profit:          ``R_{a,s} = Σ_m (-C_{to}(ξ_s) - ξ^{cap}_s K_m)``
      cost_reduction:  ``R_{a,s} = Σ_m (C_{base}(ξ_s) - C_{to}(ξ_s) - ξ^{cap}_s K_m)``
    where ``m`` ranges over the asset's member candidates. With
    ``normalize_by_capex`` the asset reward is divided by ``Σ_m K_m`` (a
    return-on-capital), making rewards scale-comparable across assets.

    Output slate groups (``Technology.output_share_groups``) are valued at their
    **nominal** declared yields here: slate optimisation is a dispatch decision
    made inside the MILP, outside this portfolio approximation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import numpy.typing as npt

from pathwise.core.portfolio import scenarios as sc
from pathwise.core.portfolio.assets import Asset, Candidate
from pathwise.core.problem import Problem
from pathwise.progress import ProgressFn


class RewardMode(StrEnum):
    """What an asset's reward measures."""

    PROFIT = "profit"  # revenue − cost of running the target technology
    COST_REDUCTION = "cost_reduction"  # net-cost saving vs the baseline technology


@dataclass(slots=True, frozen=True)
class _CostBasis:
    """Scenario-independent running-cost components of one technology [currency]."""

    opex: float
    commodity: float
    sale: float
    impact: float


def _cost_basis(problem: Problem, technology_id: str, capacity: float) -> _CostBasis:
    """Discounted running-cost bases for a technology at ``capacity``.

    Each base is summed over horizon years as ``DF_t · duration_t · (...)`` so the
    per-scenario running cost is a linear combination with the shock multipliers.
    """
    tech = problem.technologies[technology_id]
    opex = commodity = sale = impact = 0.0
    for period in problem.periods:
        t = period.year
        weight = problem.discount_factor(t) * period.duration_years
        opex += weight * tech.opex(t) * capacity
        for r, intensity in tech.input_intensity.items():
            commodity += weight * intensity * capacity * problem.commodities[r].price(t)
        for r, yld in tech.output_yield.items():
            sale += weight * yld * capacity * problem.commodities[r].sale_price(t)
        for i, factor in tech.direct_impact.items():
            impact += weight * factor * capacity * problem.impacts[i].price(t)
        for r, intensity in tech.input_intensity.items():
            for i in problem.impacts:
                cf = problem.commodity_impacts.get((r, i), 0.0)
                if cf:
                    impact += weight * intensity * capacity * cf * problem.impacts[i].price(t)
    return _CostBasis(opex=opex, commodity=commodity, sale=sale, impact=impact)


def _running_cost(basis: _CostBasis, scen: sc.ScenarioSet) -> npt.NDArray[np.float64]:
    """Vectorised running cost ``C_k(ξ_s)`` over all scenarios [currency]."""
    return (
        basis.opex * scen.multiplier(sc.OPEX)
        + basis.commodity * scen.multiplier(sc.COMMODITY_PRICE)
        - basis.sale * scen.multiplier(sc.SALE_PRICE)
        + basis.impact * scen.multiplier(sc.IMPACT_PRICE)
    )


def _candidate_reward(
    problem: Problem,
    candidate: Candidate,
    scen: sc.ScenarioSet,
    mode: RewardMode,
    base_cache: dict[str, _CostBasis],
) -> npt.NDArray[np.float64]:
    """Reward vector for a single candidate switch over all scenarios [currency]."""
    # Key the cache on (technology, capacity): _cost_basis scales every running-cost
    # term by capacity, so two facilities switching to the same tech at different
    # sizes must NOT share a basis.
    to_key = f"{candidate.to_technology}@{candidate.capacity}"
    if to_key not in base_cache:
        base_cache[to_key] = _cost_basis(problem, candidate.to_technology, candidate.capacity)
    to_cost = _running_cost(base_cache[to_key], scen)

    first_year = min(problem.years) if problem.years else 0
    capex_term = problem.discount_factor(first_year) * candidate.transition_capex
    capex = capex_term * scen.multiplier(sc.CAPEX)

    if mode == RewardMode.PROFIT:
        return -to_cost - capex
    # cost_reduction: net-cost saving of switching from baseline to target.
    base_key = f"::baseline::{candidate.from_technology}@{candidate.capacity}"
    if base_key not in base_cache:
        base_cache[base_key] = _cost_basis(problem, candidate.from_technology, candidate.capacity)
    base_cost = _running_cost(base_cache[base_key], scen)
    return base_cost - to_cost - capex


def returns_matrix(
    problem: Problem,
    assets: list[Asset],
    scenarios: sc.ScenarioSet,
    mode: RewardMode,
    normalize_by_capex: bool = True,
    progress: ProgressFn | None = None,
) -> npt.NDArray[np.float64]:
    """Build the ``(n_scenarios × n_assets)`` reward matrix.

    Args:
        problem: The assembled optimisation instance.
        assets: Portfolio assets (each a group of candidate switches).
        scenarios: Monte-Carlo shock set.
        mode: Whether reward is profit or cost-reduction-vs-baseline.
        normalize_by_capex: If ``True`` divide each asset's reward by its total
            switch cost (return-on-capital); falls back to absolute currency for
            zero-capex assets.
        progress: Optional callback invoked once per asset as its reward column is
            built, with ``(done, len(assets), asset.label)`` for live UI counts.

    Returns:
        Float64 array ``R`` of shape ``(scenarios.n_scenarios, len(assets))``;
        column ``j`` is asset ``j``'s reward across scenarios.
    """
    n = scenarios.n_scenarios
    n_assets = len(assets)
    matrix = np.zeros((n, n_assets), dtype=np.float64)
    base_cache: dict[str, _CostBasis] = {}
    for j, asset in enumerate(assets):
        reward = np.zeros(n, dtype=np.float64)
        for member in asset.members:
            reward += _candidate_reward(problem, member, scenarios, mode, base_cache)
        if normalize_by_capex:
            capex = asset.transition_capex
            if capex > 0.0:
                reward = reward / capex
        matrix[:, j] = reward
        if progress is not None:
            progress(j + 1, n_assets, asset.label)
    return matrix
