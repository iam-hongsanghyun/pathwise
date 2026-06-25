"""Monte-Carlo scenario generation: reproducibility and unbiasedness."""

from __future__ import annotations

import numpy as np

from pathwise.core.portfolio.scenarios import (
    DEFAULT_VOLATILITY,
    FLOW_PRICE,
    generate_scenarios,
)


def test_same_seed_is_reproducible() -> None:
    a = generate_scenarios(7, 256)
    b = generate_scenarios(7, 256)
    for cat in DEFAULT_VOLATILITY:
        np.testing.assert_array_equal(a.multiplier(cat), b.multiplier(cat))


def test_different_seeds_differ() -> None:
    a = generate_scenarios(1, 256)
    b = generate_scenarios(2, 256)
    assert not np.array_equal(a.multiplier(FLOW_PRICE), b.multiplier(FLOW_PRICE))


def test_shock_mean_is_unbiased() -> None:
    # E[xi] = 1 by construction (the -sigma^2/2 drift correction).
    scen = generate_scenarios(0, 200_000, {FLOW_PRICE: 0.3})
    np.testing.assert_allclose(scen.multiplier(FLOW_PRICE).mean(), 1.0, rtol=0, atol=5e-3)


def test_zero_volatility_is_certain() -> None:
    scen = generate_scenarios(0, 16, {FLOW_PRICE: 0.0})
    np.testing.assert_array_equal(scen.multiplier(FLOW_PRICE), np.ones(16))
