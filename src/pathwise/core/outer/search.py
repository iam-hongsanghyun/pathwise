"""Derivative-free optimisers for an outer (upper-level) search.

These are the *upper level* of a bilevel optimisation: each candidate vector is
scored by an injected ``evaluate`` callback that, in pathwise, runs a full
inner cost-minimisation solve. The optimisers here know nothing about pathwise
data types — they search a bounded real vector and call back for costs — so
they are unit-testable against synthetic objective functions.

Two methods are provided:

* :func:`anneal` — simulated annealing (stochastic, reproducible via an injected
  ``numpy.random.Generator``).
* :func:`sweep`  — a deterministic scalar-multiplier grid that traces a frontier.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from pathwise.logger import get_logger

logger = get_logger(__name__)

#: Cost returned for an evaluation that fails / is infeasible (so it is rejected).
INFEASIBLE_COST = math.inf

Evaluate = Callable[[list[float]], float]


@dataclass(slots=True)
class SearchResult:
    """Outcome of an outer search.

    Attributes:
        best_x: The lowest-cost vector found.
        best_cost: Objective value at :attr:`best_x` (``inf`` if none feasible).
        history: Per-evaluation log (dicts with at least ``cost``; SA adds
            ``iteration``/``accepted``/``temperature``, sweep adds ``alpha``).
        n_evals: Number of ``evaluate`` calls made.
        method: ``"anneal"`` or ``"sweep"``.
    """

    best_x: list[float]
    best_cost: float
    history: list[dict[str, Any]] = field(default_factory=list)
    n_evals: int = 0
    method: str = ""


def anneal(
    evaluate: Evaluate,
    x0: Sequence[float],
    lower: Sequence[float],
    upper: Sequence[float],
    *,
    max_iter: int,
    t0: float,
    t_min: float,
    cooling: float,
    rng: np.random.Generator,
    step_scale: float = 0.15,
) -> SearchResult:
    r"""Minimise ``evaluate`` over a box ``[lower, upper]`` by simulated annealing.

    A symmetric Gaussian proposal perturbs every coordinate, the proposal is
    clamped back into the box, and the Metropolis rule decides acceptance. The
    temperature cools geometrically; the search stops at ``max_iter`` or when the
    temperature falls below ``t_min``.

    Algorithm:
        Proposal (coordinate ``i`` of ``n``)::

            x'_i = clip(x_i + N(0, step_scale * (upper_i - lower_i)), lower_i, upper_i)

        Metropolis acceptance of the proposal against the *current* point::

        $$P_\text{accept} = \begin{cases} 1 & \Delta \le 0 \\
            \exp(-\Delta / T) & \Delta > 0 \end{cases},\quad
            \Delta = f(x') - f(x)$$

        Geometric cooling: ``T_{k+1} = cooling * T_k`` with ``0 < cooling < 1``.

        ASCII fallback::

            dx_i  = Normal(0, step_scale*(upper_i - lower_i))
            x'    = clip(x + dx, lower, upper)
            delta = f(x') - f(x_current)
            accept if delta <= 0 else  rand() < exp(-delta / T)
            T <- cooling * T   ; stop when T < t_min

    Args:
        evaluate: Objective; maps a vector (as a list) to a scalar cost
            [objective units]. May return ``inf`` for infeasible points.
        x0: Starting vector [decision units]; clamped into the box.
        lower: Per-coordinate lower bounds [decision units].
        upper: Per-coordinate upper bounds [decision units].
        max_iter: Maximum number of proposals (each is one ``evaluate`` call).
        t0: Initial temperature ``T`` [objective units]; controls early
            uphill-acceptance probability.
        t_min: Stop once ``T`` drops below this [objective units].
        cooling: Geometric cooling factor ``γ`` in ``(0, 1)`` [—].
        rng: Seeded ``numpy`` generator (reproducibility).
        step_scale: Gaussian step as a fraction of each coordinate's range [—].

    Returns:
        The :class:`SearchResult`.
    """
    lo = np.asarray(lower, dtype=float)
    hi = np.asarray(upper, dtype=float)
    span = np.where(hi > lo, hi - lo, 0.0)
    x = np.clip(np.asarray(x0, dtype=float), lo, hi)

    current_cost = evaluate(x.tolist())
    best_x = x.copy()
    best_cost = current_cost
    history: list[dict[str, Any]] = [
        {"iteration": 0, "cost": current_cost, "accepted": True, "temperature": t0}
    ]
    n_evals = 1

    temperature = t0
    for k in range(1, max_iter + 1):
        if temperature < t_min:
            logger.debug("anneal: stop at iter=%d, T=%.3g < t_min", k, temperature)
            break
        proposal = np.clip(x + rng.normal(0.0, step_scale * span), lo, hi)
        cost = evaluate(proposal.tolist())
        n_evals += 1

        delta = cost - current_cost
        accepted = False
        if delta <= 0:
            accepted = True
        elif math.isfinite(delta) and temperature > 0:
            accepted = rng.random() < math.exp(-delta / temperature)
        if accepted:
            x = proposal
            current_cost = cost
            if cost < best_cost:
                best_x = proposal.copy()
                best_cost = cost

        history.append(
            {"iteration": k, "cost": cost, "accepted": accepted, "temperature": temperature}
        )
        temperature *= cooling

    logger.info("anneal finished: evals=%d best_cost=%s", n_evals, best_cost)
    return SearchResult(
        best_x=best_x.tolist(),
        best_cost=best_cost,
        history=history,
        n_evals=n_evals,
        method="anneal",
    )


def sweep(
    evaluate: Evaluate,
    upper: Sequence[float],
    floor: Sequence[float],
    *,
    steps: int,
) -> SearchResult:
    r"""Minimise ``evaluate`` along a deterministic scalar-multiplier grid.

    Scales the ``upper`` vector by a multiplier ``α`` swept from ``1`` down to
    ``0`` and clamped to ``floor``, evaluating each rung. Deterministic and
    reproducible; the full ``history`` is a cost–multiplier frontier.

    Algorithm:
        For ``α`` over ``steps`` points linearly spaced on ``[1, 0]``::

            x(α) = clip(α * upper, floor, upper)
            cost(α) = f(x(α))

        Return ``argmin_α cost(α)``.

    Args:
        evaluate: Objective; maps a vector (as a list) to a scalar cost
            [objective units].
        upper: Per-coordinate upper bounds [decision units] (``α = 1``).
        floor: Per-coordinate lower clamp [decision units].
        steps: Number of multiplier rungs (``>= 2``).

    Returns:
        The :class:`SearchResult` (``best_x`` is the cheapest rung's vector).
    """
    hi = np.asarray(upper, dtype=float)
    lo = np.asarray(floor, dtype=float)
    best_x: list[float] | None = None
    best_cost = INFEASIBLE_COST
    history: list[dict[str, Any]] = []

    for alpha in np.linspace(1.0, 0.0, steps):
        x = np.clip(alpha * hi, lo, hi)
        cost = evaluate(x.tolist())
        history.append({"alpha": float(alpha), "cost": cost})
        if cost < best_cost:
            best_cost = cost
            best_x = x.tolist()

    if best_x is None:  # all rungs infeasible — return the loosest (α = 1).
        best_x = hi.tolist()

    logger.info("sweep finished: evals=%d best_cost=%s", len(history), best_cost)
    return SearchResult(
        best_x=best_x,
        best_cost=best_cost,
        history=history,
        n_evals=len(history),
        method="sweep",
    )
