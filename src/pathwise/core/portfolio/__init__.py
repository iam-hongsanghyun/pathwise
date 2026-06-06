"""Portfolio framing of a process-network transition problem.

These modules treat candidate technology transitions as portfolio *assets* and
allocate weights across them by trading reward (profit or cost-reduction)
against risk (variance of the reward across Monte-Carlo scenarios). They are
**I/O-free** (per the ``core/`` convention); the orchestration and result
shaping live in :mod:`pathwise.backends.portfolio_backend`.
"""

from __future__ import annotations

from pathwise.core.portfolio.assets import Asset, AssetLevel, Candidate, enumerate_assets
from pathwise.core.portfolio.methods import PortfolioMethod, PortfolioSolution, optimise
from pathwise.core.portfolio.returns import RewardMode, returns_matrix
from pathwise.core.portfolio.scenarios import (
    DEFAULT_VOLATILITY,
    ScenarioSet,
    generate_scenarios,
)

__all__ = [
    "DEFAULT_VOLATILITY",
    "Asset",
    "AssetLevel",
    "Candidate",
    "PortfolioMethod",
    "PortfolioSolution",
    "RewardMode",
    "ScenarioSet",
    "enumerate_assets",
    "generate_scenarios",
    "optimise",
    "returns_matrix",
]
