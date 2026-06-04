"""pathwise.core — the generic, domain-agnostic optimisation model.

Public API:
    Entities: Asset, Technology, Carrier, Measure, MaccBlock, Transition,
        Period, Target, TargetType, CapexConvention.
    Problem: OptimisationProblem, CostToggles, SolveOptions.
    Solve: build, solve, SolveResult, SolveStatus, SolverOptions.
"""

from __future__ import annotations

from pathwise.core.builder import build
from pathwise.core.entities import (
    Asset,
    CapexConvention,
    Carrier,
    MaccBlock,
    Measure,
    Period,
    Target,
    TargetType,
    Technology,
    Transition,
)
from pathwise.core.problem import CostToggles, OptimisationProblem, SolveOptions
from pathwise.core.solve import SolveResult, SolverOptions, SolveStatus, solve

__all__ = [
    "Asset",
    "CapexConvention",
    "Carrier",
    "CostToggles",
    "MaccBlock",
    "Measure",
    "OptimisationProblem",
    "Period",
    "SolveOptions",
    "SolveResult",
    "SolveStatus",
    "SolverOptions",
    "Target",
    "TargetType",
    "Technology",
    "Transition",
    "build",
    "solve",
]
