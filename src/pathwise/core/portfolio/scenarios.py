"""Monte-Carlo scenario generation for the portfolio backend.

pathwise stores only point estimates of prices and costs, so the *risk* of a
transition is not directly observable. We synthesise it by sampling
multiplicative shocks on each uncertain input category and re-pricing every
asset's reward under each shock. The shocks are reproducible from a seed.

Algorithm:
    Each input category ``c`` (commodity price, sale price, impact price, opex,
    capex) carries a lognormal volatility ``σ_c``. For scenario ``s`` we draw a
    multiplicative shock

    $$\\xi_{c,s} = \\exp\\!\\left(\\sigma_c Z_{c,s} - \\tfrac{1}{2}\\sigma_c^2\\right),
      \\qquad Z_{c,s}\\sim\\mathcal{N}(0,1)$$

    ASCII: xi[c,s] = exp(sigma_c * Z[c,s] - 0.5 * sigma_c^2),  Z ~ Normal(0,1)

    where ``xi[c,s]`` is the dimensionless multiplier applied to every base
    value in category ``c`` [—], ``sigma_c`` is that category's lognormal
    volatility [—], and ``Z[c,s]`` is a standard-normal draw. The ``-σ²/2`` term
    makes ``E[xi]=1`` so the *mean* scenario equals pathwise's point estimate
    (the sampling is unbiased about the deterministic case). Categories are
    sampled independently in v1.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

# Input categories whose point estimates the Monte-Carlo engine perturbs. These
# are the keys of the ``volatility`` mapping; any subset may be supplied.
COMMODITY_PRICE = "commodity_price"
SALE_PRICE = "sale_price"
IMPACT_PRICE = "impact_price"
OPEX = "opex"
CAPEX = "capex"

# Default per-category lognormal volatilities. Travel inside the scenario (not
# config.py) because they are user-definable model assumptions, not server
# settings; callers may override any subset.
DEFAULT_VOLATILITY: dict[str, float] = {
    COMMODITY_PRICE: 0.20,
    SALE_PRICE: 0.20,
    IMPACT_PRICE: 0.30,
    OPEX: 0.10,
    CAPEX: 0.10,
}


@dataclass(slots=True, frozen=True)
class ScenarioSet:
    """Reproducible Monte-Carlo shocks.

    Attributes:
        seed: RNG seed used.
        n_scenarios: Number of scenarios drawn.
        shocks: Per-category multiplier arrays, each shape ``(n_scenarios,)``.
            A category absent from the original ``volatility`` mapping (or with
            ``σ ≤ 0``) is omitted; :meth:`multiplier` then returns all-ones.
    """

    seed: int
    n_scenarios: int
    shocks: dict[str, npt.NDArray[np.float64]]

    def multiplier(self, category: str) -> npt.NDArray[np.float64]:
        """Shock multipliers for ``category`` (all-ones if not sampled)."""
        m = self.shocks.get(category)
        if m is None:
            return np.ones(self.n_scenarios, dtype=np.float64)
        return m


def generate_scenarios(
    seed: int,
    n_scenarios: int,
    volatility: dict[str, float] | None = None,
) -> ScenarioSet:
    """Draw reproducible multiplicative shocks per input category.

    Args:
        seed: RNG seed (reproducibility — same seed ⇒ identical draws).
        n_scenarios: Number of scenarios to draw (``≥ 1``).
        volatility: Per-category lognormal volatility ``σ_c`` [—]; defaults to
            :data:`DEFAULT_VOLATILITY`. Categories with ``σ ≤ 0`` are treated as
            certain (multiplier ≡ 1) and omitted.

    Returns:
        A :class:`ScenarioSet` of shock arrays.

    Raises:
        ValueError: If ``n_scenarios < 1``.
    """
    if n_scenarios < 1:
        raise ValueError(f"n_scenarios must be >= 1, got {n_scenarios}")
    vols = DEFAULT_VOLATILITY if volatility is None else volatility
    rng = np.random.default_rng(seed)
    shocks: dict[str, npt.NDArray[np.float64]] = {}
    for category, sigma in vols.items():
        if sigma <= 0.0:
            continue
        z = rng.standard_normal(n_scenarios)
        shocks[category] = np.exp(sigma * z - 0.5 * sigma * sigma)
    return ScenarioSet(seed=seed, n_scenarios=n_scenarios, shocks=shocks)
