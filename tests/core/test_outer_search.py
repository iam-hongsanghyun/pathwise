"""Outer-search optimisers: convergence, reproducibility, bounds, frontier."""

from __future__ import annotations

import numpy as np

from pathwise.core.outer import anneal, sweep


def test_anneal_converges_to_interior_minimum() -> None:
    c = 3.0
    f = lambda x: float(sum((xi - c) ** 2 for xi in x))  # noqa: E731
    rng = np.random.default_rng(0)
    res = anneal(
        f,
        x0=[0.0, 0.0, 0.0],
        lower=[0.0, 0.0, 0.0],
        upper=[10.0, 10.0, 10.0],
        max_iter=800,
        t0=10.0,
        t_min=1e-4,
        cooling=0.99,
        rng=rng,
    )
    np.testing.assert_allclose(res.best_x, [c, c, c], atol=0.6)
    assert res.best_cost < 1.0
    assert res.method == "anneal"
    assert res.n_evals > 0


def test_anneal_is_reproducible_with_same_seed() -> None:
    f = lambda x: float(sum(xi * xi for xi in x))  # noqa: E731
    kwargs = dict(  # noqa: C408
        x0=[5.0, 5.0],
        lower=[0.0, 0.0],
        upper=[10.0, 10.0],
        max_iter=200,
        t0=5.0,
        t_min=1e-3,
        cooling=0.97,
    )
    a = anneal(f, rng=np.random.default_rng(123), **kwargs)
    b = anneal(f, rng=np.random.default_rng(123), **kwargs)
    assert a.best_x == b.best_x
    assert a.best_cost == b.best_cost


def test_anneal_respects_bounds_when_optimum_is_outside_box() -> None:
    # Minimum of (x-20)^2 is at 20, outside [0, 10]; the best feasible is 10.
    f = lambda x: float((x[0] - 20.0) ** 2)  # noqa: E731
    res = anneal(
        f,
        x0=[0.0],
        lower=[0.0],
        upper=[10.0],
        max_iter=400,
        t0=5.0,
        t_min=1e-4,
        cooling=0.98,
        rng=np.random.default_rng(7),
    )
    assert 0.0 <= res.best_x[0] <= 10.0
    np.testing.assert_allclose(res.best_x[0], 10.0, atol=0.5)


def test_sweep_traces_frontier_and_finds_grid_minimum() -> None:
    # cost = (sum(x) - 10)^2, with x = alpha*[10,10] ⇒ sum = 20*alpha;
    # minimised at alpha = 0.5 (a grid point for steps=11) ⇒ x = [5, 5].
    f = lambda x: float((sum(x) - 10.0) ** 2)  # noqa: E731
    res = sweep(f, upper=[10.0, 10.0], floor=[0.0, 0.0], steps=11)
    assert res.method == "sweep"
    assert len(res.history) == 11
    assert res.n_evals == 11
    np.testing.assert_allclose(res.best_x, [5.0, 5.0], atol=1e-9)
    np.testing.assert_allclose(res.best_cost, 0.0, atol=1e-9)


def test_sweep_picks_floor_for_monotone_decreasing_cost() -> None:
    f = lambda x: float(sum(x))  # noqa: E731  minimised by the smallest vector
    res = sweep(f, upper=[10.0, 10.0], floor=[0.0, 0.0], steps=6)
    np.testing.assert_allclose(res.best_x, [0.0, 0.0], atol=1e-9)
