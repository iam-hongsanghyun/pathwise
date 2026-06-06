"""Portfolio backend: frame the transition problem as a risk-vs-reward allocation.

Reuses the front half of the deterministic pipeline (validate → assemble the
:class:`~pathwise.core.problem.Problem`), then — instead of building a MILP —
enumerates candidate transitions as portfolio *assets*, samples Monte-Carlo
rewards, and allocates weights with the chosen method (MVO / CVaR / HRP /
Black-Litterman). The result carries an ``outputs.portfolio`` block alongside the
(empty) MILP output arrays, so existing result consumers keep working.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from pathwise.config import get_settings
from pathwise.core.extract import empty_result, portfolio_result
from pathwise.core.portfolio import (
    AssetLevel,
    PortfolioMethod,
    RewardMode,
    enumerate_assets,
    generate_scenarios,
    optimise,
    returns_matrix,
)
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.workbook import Workbook
from pathwise.domains.base import get_domain
from pathwise.logger import get_logger

logger = get_logger(__name__)

# Cap the per-scenario reward distribution echoed to the client (histogram only
# needs a representative sample, not every draw).
_MAX_DISTRIBUTION = 2000


class PortfolioBackend:
    """Allocate transition capital across candidate switches by risk vs reward."""

    name = "portfolio"
    label = "Portfolio (risk vs reward)"

    def capabilities(self) -> dict[str, Any]:
        """Backend capability descriptor for the handshake."""
        return {
            "name": self.name,
            "label": self.label,
            "solver": "PyPortfolioOpt",
            "features": {
                "methods": ["mvo", "cvar", "hrp", "black_litterman"],
                "rewardModes": ["profit", "cost_reduction"],
                "assetLevels": ["facility", "technology", "company", "economy"],
                "monteCarlo": True,
                "efficientFrontier": True,
                "multiPeriod": True,
                "transitions": True,
                "network": False,
                "macc": False,
            },
        }

    def run(
        self,
        model: Workbook,
        scenario: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate, assemble, sample, and allocate.

        Args:
            model: The in-memory workbook.
            scenario: The run definition (a :class:`ScenarioConfig` as a dict).
            options: ``domain`` override.

        Returns:
            pathwise's result dict with an ``outputs.portfolio`` block.
        """
        options = options or {}
        settings = get_settings()
        sc = ScenarioConfig.from_dict(scenario)
        domain = get_domain(options.get("domain") or sc.domain)
        terminology = domain.terminology()
        logger.info("running domain=%s backend=%s", domain.name, self.name)

        report = domain.validate(model)
        if not report.ok:
            logger.warning("validation failed: %d error(s)", len(report.errors))
            return empty_result("invalid", terminology, report.as_dict())

        problem = domain.build_problem(model, sc)
        pf = sc.portfolio
        assets = enumerate_assets(problem, AssetLevel(pf.asset_level))
        if len(assets) < 2:
            report_dict = report.as_dict()
            report_dict["errors"].append(
                "Portfolio optimisation needs at least two candidate transitions "
                f"(found {len(assets)} at asset level '{pf.asset_level}'). Add "
                "transitions or choose a finer asset level."
            )
            return empty_result("invalid", terminology, report_dict)

        n = min(pf.n_scenarios, settings.max_portfolio_scenarios)
        scenarios = generate_scenarios(sc.solver.seed, n, pf.volatility or None)
        returns = returns_matrix(
            problem,
            assets,
            scenarios,
            RewardMode(pf.reward_mode),
            normalize_by_capex=pf.normalize_by_capex,
        )
        asset_ids = [a.asset_id for a in assets]
        logger.info(
            "portfolio: %d assets × %d scenarios (method=%s, reward=%s)",
            len(assets),
            n,
            pf.method,
            pf.reward_mode,
        )
        solution = optimise(
            asset_ids,
            returns,
            PortfolioMethod(pf.method),
            risk_aversion=pf.risk_aversion,
            target_return=pf.target_return,
            cvar_alpha=pf.cvar_alpha,
            bl_views=pf.bl_views,
            bl_tau=pf.bl_tau,
        )

        block = _build_block(assets, returns, solution, pf, n)
        return portfolio_result(block, terminology, report.as_dict())


def _build_block(
    assets: list[Any],
    returns: np.ndarray,
    solution: Any,
    pf: Any,
    n_scenarios: int,
) -> dict[str, Any]:
    """Shape the portfolio solution into a JSON-serialisable result block."""
    col_mean = returns.mean(axis=0)
    col_std = returns.std(axis=0)
    weights = np.array([solution.weights[a.asset_id] for a in assets], dtype=np.float64)
    distribution = returns @ weights
    if distribution.size > _MAX_DISTRIBUTION:
        step = int(np.ceil(distribution.size / _MAX_DISTRIBUTION))
        distribution = distribution[::step]

    return {
        "method": pf.method,
        "reward_mode": pf.reward_mode,
        "asset_level": pf.asset_level,
        "normalize_by_capex": pf.normalize_by_capex,
        "n_scenarios": n_scenarios,
        "expected_return": solution.expected_return,
        "variance": solution.variance,
        "risk": solution.risk,
        "cvar": solution.cvar,
        "objective": solution.objective,
        "chosen": {"return": solution.expected_return, "risk": solution.risk},
        "frontier": [{"return": r, "risk": k} for r, k in solution.frontier],
        "distribution": [float(v) for v in distribution],
        "assets": [
            {
                "asset_id": a.asset_id,
                "label": a.label,
                "company": a.company,
                "from_technology": a.from_technology,
                "to_technology": a.to_technology,
                "transition_capex": a.transition_capex,
                "weight": solution.weights[a.asset_id],
                "expected_return": float(col_mean[j]),
                "std": float(col_std[j]),
            }
            for j, a in enumerate(assets)
        ],
    }
