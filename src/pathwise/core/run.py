"""Unified run entry: one joint solve, or per-level partitioned optimisation.

``run_model`` is the single front door. With no node hierarchy (or
``optimisation_scope == "system"``, or a level that is the root / a single node)
it runs the ordinary joint solve and returns the standard
:func:`pathwise.core.extract.extract_results` dict. Otherwise it cuts the tree at
the chosen level into independent problems and couples them with the value-chain
cascade, returning that combined result (per-stage results + couplings).
"""

from __future__ import annotations

from typing import Any

from pathwise.core.build import build
from pathwise.core.extract import extract_results
from pathwise.core.partition import is_partitionable, partition
from pathwise.core.solve import solve
from pathwise.core.valuechain import run_value_chain
from pathwise.data.assemble import assemble_problem
from pathwise.data.hierarchy import load_hierarchy
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.workbook import Workbook


def run_model(workbook: Workbook, scenario: ScenarioConfig) -> dict[str, Any]:
    """Solve a model, jointly or partitioned at ``scenario.optimisation_scope``.

    Returns the standard result for a joint solve, or the value-chain combined
    result (``{"status", "stages", "couplings", ...}``) when partitioned.
    """
    hierarchy = load_hierarchy(workbook)
    level = scenario.optimisation_scope
    if hierarchy is None or level == "system" or not is_partitionable(hierarchy, level):
        return extract_results(solve(build(assemble_problem(workbook, scenario))))

    c = scenario.coupling
    spec, workbooks = partition(
        workbook, hierarchy, level, signals=c.signals, default_lag=c.default_lag
    )
    return run_value_chain(spec, workbooks, scenario, iterations=c.iterations, damping=c.damping)
