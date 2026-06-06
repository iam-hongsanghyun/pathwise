"""Portfolio optimisers against analytical / hand-computed cases."""

from __future__ import annotations

import numpy as np
import pytest

from pathwise.core.portfolio.methods import (
    PortfolioMethod,
    _cvar,
    optimise,
)


def _orthogonal_returns(means: list[float], variances: list[float]) -> tuple[list[str], np.ndarray]:
    """Returns with an EXACT diagonal sample covariance.

    Uses mutually orthogonal zero-sum ±1 columns (n = 4) scaled so the sample
    variance (ddof = 1) equals each target. Cross sample-covariances are zero.
    """
    patterns = np.array(
        [
            [1.0, -1.0, 1.0, -1.0],
            [1.0, 1.0, -1.0, -1.0],
            [1.0, -1.0, -1.0, 1.0],
        ]
    ).T  # shape (4 scenarios, 3 assets); columns orthogonal, zero-sum.
    n = patterns.shape[0]
    # sample var of a ±scale zero-sum column = scale^2 * sum(p^2)/(n-1) = scale^2 * n/(n-1).
    scales = np.sqrt(np.array(variances) * (n - 1) / n)
    cols = patterns * scales + np.array(means)
    ids = [f"a{i}" for i in range(len(means))]
    return ids, cols


def test_mvo_min_variance_matches_inverse_variance_weights() -> None:
    # Equal means ⇒ the return term mu·w is constant on the simplex, so the
    # mean-variance utility reduces to pure min-variance, which for a diagonal
    # covariance is w_j ∝ 1/var_j.
    ids, R = _orthogonal_returns(means=[0.1, 0.1, 0.1], variances=[1.0, 2.0, 4.0])
    sol = optimise(ids, R, PortfolioMethod.MVO, risk_aversion=5.0)
    inv = np.array([1.0, 0.5, 0.25])
    expected = inv / inv.sum()
    got = np.array([sol.weights[i] for i in ids])
    np.testing.assert_allclose(got, expected, rtol=2e-3, atol=2e-3)


def test_cvar_helper_matches_hand_value() -> None:
    # losses 1..10, beta = 0.8 → VaR = 8.2 (linear quantile), CVaR = mean(9, 10) = 9.5.
    returns = -np.arange(1, 11, dtype=float).reshape(10, 1)
    np.testing.assert_allclose(_cvar(returns, np.array([1.0]), 0.8), 9.5, rtol=0, atol=1e-9)


def test_hrp_two_blocks_split_evenly() -> None:
    rng = np.random.default_rng(0)
    n = 6000
    fa, fb = rng.standard_normal(n), rng.standard_normal(n)
    # Two correlated blocks (0,1) and (2,3), blocks mutually independent, equal var.
    cols = np.column_stack(
        [
            fa + 0.15 * rng.standard_normal(n),
            fa + 0.15 * rng.standard_normal(n),
            fb + 0.15 * rng.standard_normal(n),
            fb + 0.15 * rng.standard_normal(n),
        ]
    )
    ids = ["a", "b", "c", "d"]
    sol = optimise(ids, cols, PortfolioMethod.HRP)
    w = sol.weights
    # Each block ~ half the budget; equal variances ⇒ equal split within a block.
    np.testing.assert_allclose(w["a"] + w["b"], 0.5, rtol=0, atol=0.06)
    np.testing.assert_allclose(w["c"] + w["d"], 0.5, rtol=0, atol=0.06)


def test_black_litterman_without_views_recovers_prior() -> None:
    rng = np.random.default_rng(3)
    R = rng.normal(0.1, 0.2, size=(2000, 3))
    ids = ["a", "b", "c"]
    bl = optimise(ids, R, PortfolioMethod.BLACK_LITTERMAN, bl_views={}, risk_aversion=2.0)
    mvo = optimise(ids, R, PortfolioMethod.MVO, risk_aversion=2.0)
    got = np.array([bl.weights[i] for i in ids])
    ref = np.array([mvo.weights[i] for i in ids])
    np.testing.assert_allclose(got, ref, rtol=0, atol=1e-6)


@pytest.mark.parametrize(
    "method",
    [
        PortfolioMethod.MVO,
        PortfolioMethod.CVAR,
        PortfolioMethod.HRP,
        PortfolioMethod.BLACK_LITTERMAN,
    ],
)
def test_weights_are_long_only_and_sum_to_one(method: PortfolioMethod) -> None:
    rng = np.random.default_rng(11)
    R = rng.normal(0.1, 0.2, size=(1500, 4))
    ids = ["a", "b", "c", "d"]
    sol = optimise(ids, R, method)
    weights = np.array([sol.weights[i] for i in ids])
    assert (weights >= -1e-6).all()
    np.testing.assert_allclose(weights.sum(), 1.0, rtol=0, atol=1e-4)


def test_fewer_than_two_assets_raises() -> None:
    with pytest.raises(ValueError, match="at least two assets"):
        optimise(["only"], np.ones((10, 1)), PortfolioMethod.MVO)
