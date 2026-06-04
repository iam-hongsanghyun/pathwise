"""SolverOptions → HiGHS kwargs, incl. optional global scaling."""

from __future__ import annotations

from pathwise.core.solve import SolverOptions


def test_scaling_omitted_when_unset() -> None:
    kwargs = SolverOptions().as_highs_kwargs()
    assert "user_bound_scale" not in kwargs
    assert "user_objective_scale" not in kwargs


def test_scaling_forwarded_when_set() -> None:
    kwargs = SolverOptions(user_bound_scale=-8, user_objective_scale=-10).as_highs_kwargs()
    assert kwargs["user_bound_scale"] == -8
    assert kwargs["user_objective_scale"] == -10
