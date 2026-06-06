r"""Portfolio optimisers over the Monte-Carlo reward matrix.

Thin wrappers over `PyPortfolioOpt <https://pyportfolioopt.readthedocs.io>`_ that
take the ``(n_scenarios × n_assets)`` reward matrix and return a uniform
:class:`PortfolioSolution`. Expected return, variance and CVaR are recomputed
here from the solved weights against the *sample* mean/covariance/losses, so the
reported numbers stay in the reward's own units (PyPortfolioOpt's
``portfolio_performance`` annualises by 252, which is meaningless for an NPV
reward).

Methods:
    - **MVO** (mean-variance) — trade expected reward against variance.
      $$\max_w\; \mu^\top w - \tfrac{\delta}{2} w^\top \Sigma w
        \quad\text{s.t.}\quad \mathbf{1}^\top w = 1,\; w \ge 0$$
      ASCII: max  mu'w - 0.5*delta*w'Sigma w   s.t. sum(w)=1, w>=0
    - **CVaR** — minimise the mean loss beyond the ``β`` quantile
      (Rockafellar–Uryasev) on the scenario losses ``L_s = -(R w)_s``.
    - **HRP** — hierarchical risk parity: cluster assets by correlation and
      allocate by recursive inverse-variance bisection (no matrix inversion).
    - **Black-Litterman** — blend the sample mean prior ``μ`` with absolute
      views, then run MVO on the posterior.

    Symbols: ``w`` weights [—]; ``mu`` mean reward per asset [reward unit];
    ``Sigma`` reward covariance [reward unit²]; ``delta`` risk aversion
    [1/reward unit]; ``beta`` CVaR confidence [—].
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
import numpy.typing as npt
import pandas as pd
from pypfopt import BlackLittermanModel, EfficientCVaR, EfficientFrontier, HRPOpt

_FRONTIER_POINTS = 25


class PortfolioMethod(StrEnum):
    """Selectable allocation algorithm."""

    MVO = "mvo"
    CVAR = "cvar"
    HRP = "hrp"
    BLACK_LITTERMAN = "black_litterman"


@dataclass(slots=True)
class PortfolioSolution:
    """A solved allocation and its risk/reward summary.

    Attributes:
        weights: Asset weight by ``asset_id`` [—], summing to 1.
        expected_return: ``w·μ`` [reward unit].
        variance: ``w'Σw`` [reward unit²].
        risk: ``sqrt(variance)`` [reward unit].
        cvar: Conditional value-at-risk of the loss ``-w·R`` [reward unit], or
            ``None`` when not computed.
        objective: The method's own risk-adjusted score [reward unit].
        frontier: Sampled efficient frontier as ``(return, risk)`` points (MVO /
            Black-Litterman only; empty otherwise).
    """

    weights: dict[str, float]
    expected_return: float
    variance: float
    risk: float
    cvar: float | None = None
    objective: float = 0.0
    frontier: list[tuple[float, float]] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class _Inputs:
    """Sample statistics derived from the reward matrix."""

    ids: list[str]
    mu: pd.Series
    cov: pd.DataFrame
    returns: pd.DataFrame


def _inputs(asset_ids: list[str], returns: npt.NDArray[np.float64]) -> _Inputs:
    """Sample mean, covariance and a returns frame indexed by asset id."""
    frame = pd.DataFrame(returns, columns=pd.Index(asset_ids))
    mu = frame.mean(axis=0)
    cov = frame.cov().fillna(0.0)
    # A single scenario (or identical draws) yields a zero/degenerate covariance;
    # nudge the diagonal so the QP stays well-posed.
    if len(frame) < 2 or not np.any(np.asarray(cov)):
        cov = cov + pd.DataFrame(
            np.eye(len(asset_ids)) * 1e-8, index=cov.index, columns=cov.columns
        )
    return _Inputs(ids=asset_ids, mu=mu, cov=cov, returns=frame)


def _cvar(returns: npt.NDArray[np.float64], weights: npt.NDArray[np.float64], beta: float) -> float:
    """Conditional value-at-risk of the portfolio loss at confidence ``beta``."""
    losses = -(returns @ weights)
    var = float(np.quantile(losses, beta))
    tail = losses[losses >= var]
    return float(tail.mean()) if tail.size else var


def _summary(
    weights: dict[str, float],
    inp: _Inputs,
    beta: float | None = None,
) -> tuple[float, float, float, float | None]:
    """Return ``(expected_return, variance, risk, cvar)`` for ``weights``."""
    w = np.array([weights[a] for a in inp.ids], dtype=np.float64)
    expected = float(w @ inp.mu.to_numpy())
    variance = float(w @ inp.cov.to_numpy() @ w)
    risk = float(np.sqrt(max(variance, 0.0)))
    cvar = _cvar(inp.returns.to_numpy(), w, beta) if beta is not None else None
    return expected, variance, risk, cvar


def _clean(weights: dict[str, float]) -> dict[str, float]:
    """Coerce solver weights to plain floats."""
    return {str(k): float(v) for k, v in weights.items()}


def _frontier(inp: _Inputs) -> list[tuple[float, float]]:
    """Sample the long-only mean-variance frontier as ``(return, risk)`` points."""
    lo, hi = float(inp.mu.min()), float(inp.mu.max())
    if not np.isfinite(lo) or not np.isfinite(hi) or hi - lo < 1e-12:
        return []
    points: list[tuple[float, float]] = []
    for target in np.linspace(lo, hi, _FRONTIER_POINTS):
        ef = EfficientFrontier(inp.mu, inp.cov, weight_bounds=(0.0, 1.0))
        try:
            ef.efficient_return(float(target))
        except Exception:
            continue
        _, _, risk, _ = _summary(_clean(ef.clean_weights()), inp)
        points.append((float(target), risk))
    return points


def _mvo(inp: _Inputs, risk_aversion: float, target_return: float | None) -> PortfolioSolution:
    """Mean-variance optimisation (long-only)."""
    ef = EfficientFrontier(inp.mu, inp.cov, weight_bounds=(0.0, 1.0))
    if target_return is not None:
        ef.efficient_return(target_return)
    else:
        ef.max_quadratic_utility(risk_aversion=risk_aversion)
    weights = _clean(ef.clean_weights())
    expected, variance, risk, _ = _summary(weights, inp)
    return PortfolioSolution(
        weights=weights,
        expected_return=expected,
        variance=variance,
        risk=risk,
        objective=expected - 0.5 * risk_aversion * variance,
        frontier=_frontier(inp),
    )


def _cvar_opt(inp: _Inputs, beta: float) -> PortfolioSolution:
    """Conditional value-at-risk minimisation (Rockafellar–Uryasev)."""
    ec = EfficientCVaR(inp.mu, inp.returns, beta=beta, weight_bounds=(0.0, 1.0))
    ec.min_cvar()
    weights = _clean(ec.clean_weights())
    expected, variance, risk, cvar = _summary(weights, inp, beta=beta)
    return PortfolioSolution(
        weights=weights,
        expected_return=expected,
        variance=variance,
        risk=risk,
        cvar=cvar,
        objective=-(cvar if cvar is not None else 0.0),
    )


def _hrp(inp: _Inputs, beta: float) -> PortfolioSolution:
    """Hierarchical risk parity."""
    hrp = HRPOpt(returns=inp.returns)
    hrp.optimize()
    weights = _clean(hrp.clean_weights())
    expected, variance, risk, cvar = _summary(weights, inp, beta=beta)
    return PortfolioSolution(
        weights=weights,
        expected_return=expected,
        variance=variance,
        risk=risk,
        cvar=cvar,
        objective=expected,
    )


def _black_litterman(
    inp: _Inputs,
    risk_aversion: float,
    target_return: float | None,
    views: dict[str, float],
    tau: float,
) -> PortfolioSolution:
    """Black-Litterman posterior mean, then MVO on the posterior."""
    if views:
        bl = BlackLittermanModel(inp.cov, pi=inp.mu, absolute_views=views, tau=tau)
        posterior_mu = bl.bl_returns()
        posterior_cov = bl.bl_cov()
    else:
        # No views ⇒ posterior equals the prior (the sample estimates).
        posterior_mu, posterior_cov = inp.mu, inp.cov
    posterior = _Inputs(ids=inp.ids, mu=posterior_mu, cov=posterior_cov, returns=inp.returns)
    return _mvo(posterior, risk_aversion, target_return)


def optimise(
    asset_ids: list[str],
    returns: npt.NDArray[np.float64],
    method: PortfolioMethod,
    *,
    risk_aversion: float = 1.0,
    target_return: float | None = None,
    cvar_alpha: float = 0.95,
    bl_views: dict[str, float] | None = None,
    bl_tau: float = 0.05,
) -> PortfolioSolution:
    """Allocate weights across assets by the chosen ``method``.

    Args:
        asset_ids: Asset identifiers, one per column of ``returns``.
        returns: ``(n_scenarios × n_assets)`` reward matrix.
        method: Allocation algorithm.
        risk_aversion: MVO/BL risk-aversion ``δ`` [1/reward unit].
        target_return: If set (MVO/BL), minimise risk subject to this return.
        cvar_alpha: CVaR confidence level ``β`` [—].
        bl_views: Black-Litterman absolute views ``{asset_id: expected reward}``.
        bl_tau: Black-Litterman prior-uncertainty scalar ``τ`` [—].

    Returns:
        The solved :class:`PortfolioSolution`.

    Raises:
        ValueError: If fewer than two assets are supplied.
    """
    if len(asset_ids) < 2:
        raise ValueError("portfolio optimisation needs at least two assets")
    inp = _inputs(asset_ids, returns)
    if method == PortfolioMethod.MVO:
        return _mvo(inp, risk_aversion, target_return)
    if method == PortfolioMethod.CVAR:
        return _cvar_opt(inp, cvar_alpha)
    if method == PortfolioMethod.HRP:
        return _hrp(inp, cvar_alpha)
    return _black_litterman(inp, risk_aversion, target_return, bl_views or {}, bl_tau)
