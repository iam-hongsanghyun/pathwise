"""The hierarchy / network solve paths honour the scenario's solver config."""

from __future__ import annotations

from pathwise.core.solve import SolverOptions, options_from_scenario
from pathwise.data import ScenarioConfig


def test_options_from_scenario_threads_solver_config() -> None:
    sc = ScenarioConfig.from_dict(
        {"solver": {"name": "highs", "mip_gap": 0.07, "threads": 2, "time_limit_s": 123.0}}
    )
    opts = options_from_scenario(sc)
    assert opts.solver_name == "highs"
    assert opts.mip_rel_gap == 0.07
    assert opts.threads == 2
    assert opts.time_limit_s == 123.0


def test_options_from_scenario_falls_back_to_defaults() -> None:
    opts = options_from_scenario(object())  # no ``.solver`` attribute
    assert isinstance(opts, SolverOptions)
    assert opts.mip_rel_gap == SolverOptions().mip_rel_gap
