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
from pathwise.core.partition import is_partitionable, partition, subset_workbook
from pathwise.core.solve import solve
from pathwise.core.valuechain import run_value_chain
from pathwise.data.assemble import assemble_problem
from pathwise.data.hierarchy import load_hierarchy
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.workbook import Workbook


def run_model(
    workbook: Workbook,
    scenario: ScenarioConfig,
    *,
    terminology: dict[str, str] | None = None,
    report: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Solve a model, jointly or partitioned at ``scenario.optimisation_scope``.

    Returns the standard result for a joint solve, or the value-chain combined
    result (``{"status", "stages", "couplings", ...}``) when partitioned.
    ``terminology`` / ``report`` are folded into the joint result (the cascade
    result carries its own per-stage shape).
    """
    hierarchy = load_hierarchy(workbook)
    level = scenario.optimisation_scope
    targets = scenario.optimisation_targets or None

    # Whole-model joint solve (no hierarchy, or the root/system level).
    if hierarchy is None or level == "system":
        return extract_results(
            solve(build(assemble_problem(workbook, scenario))), terminology, report
        )

    units = [c for c in hierarchy.nodes_at_level(level) if not targets or c in set(targets)]
    if not units:  # nothing matched → fall back to the whole model
        return extract_results(
            solve(build(assemble_problem(workbook, scenario))), terminology, report
        )

    mode = scenario.optimisation_mode

    # JOINT (or a single unit, or a non-partitionable cut): the selected units'
    # subtrees solved together as one problem.
    if mode == "joint" or not is_partitionable(hierarchy, level, targets):
        sub = subset_workbook(workbook, hierarchy, units)
        return extract_results(solve(build(assemble_problem(sub, scenario))), terminology, report)

    # INDEPENDENT: each unit solved entirely on its own (no coupling; it trades
    # with the market). Reported in the same per-stage shape as the cascade.
    if mode == "independent":
        stages: dict[str, Any] = {}
        ok = True
        for u in units:
            r = extract_results(
                solve(build(assemble_problem(subset_workbook(workbook, hierarchy, [u]), scenario)))
            )
            stages[u] = {"status": r["status"], "objective": r["objective"]}
            ok = ok and r["status"] == "optimal"
        return {
            "status": "optimal" if ok else "mixed",
            "stages": stages,
            "couplings": [],
            "iterations": 1,
        }

    # VALUE CHAIN: in series, upstream → downstream, coupled (the cascade).
    c = scenario.coupling
    spec, workbooks = partition(
        workbook, hierarchy, level, signals=c.signals, default_lag=c.default_lag, targets=units
    )
    return run_value_chain(spec, workbooks, scenario, iterations=c.iterations, damping=c.damping)
