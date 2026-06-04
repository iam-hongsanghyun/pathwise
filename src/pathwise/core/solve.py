"""Solve a built model with HiGHS (via ``linopy``) and report status.

The solver options map straight onto HiGHS keyword arguments that ``linopy``
forwards. Status is normalised into a small enum so callers do not depend on
solver-specific strings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pathwise.core.variables import BuildContext
from pathwise.logger import get_logger

logger = get_logger(__name__)


class SolveStatus(StrEnum):
    """Normalised solve outcome."""

    OPTIMAL = "optimal"
    INFEASIBLE = "infeasible"
    UNBOUNDED = "unbounded"
    ERROR = "error"


@dataclass(slots=True)
class SolveResult:
    """Outcome of a solve.

    Attributes:
        status: Normalised status.
        objective: Objective value if a solution was found, else ``None``.
        termination: Raw solver termination string (for diagnostics).
        context: The :class:`BuildContext` (variable solutions live on it).
    """

    status: SolveStatus
    objective: float | None
    termination: str
    context: BuildContext = field(repr=False)

    @property
    def ok(self) -> bool:
        """``True`` if an optimal solution was found."""
        return self.status == SolveStatus.OPTIMAL


@dataclass(slots=True)
class SolverOptions:
    """HiGHS tuning forwarded by ``linopy``.

    Attributes:
        time_limit_s: Wall-clock limit [s].
        mip_rel_gap: Relative MIP optimality gap.
        threads: Solver threads.
        output_flag: If ``True``, HiGHS prints its log to stdout.
    """

    time_limit_s: float = 600.0
    mip_rel_gap: float = 0.01
    threads: int = 4
    output_flag: bool = False

    def as_highs_kwargs(self) -> dict[str, Any]:
        """Return the HiGHS keyword arguments ``linopy`` forwards."""
        return {
            "time_limit": float(self.time_limit_s),
            "mip_rel_gap": float(self.mip_rel_gap),
            "threads": int(self.threads),
            "output_flag": bool(self.output_flag),
        }


_STATUS_MAP = {
    "optimal": SolveStatus.OPTIMAL,
    "infeasible": SolveStatus.INFEASIBLE,
    "unbounded": SolveStatus.UNBOUNDED,
    "infeasible_or_unbounded": SolveStatus.INFEASIBLE,
}


def solve(ctx: BuildContext, options: SolverOptions | None = None) -> SolveResult:
    """Solve the model in ``ctx`` with HiGHS.

    Args:
        ctx: The build context returned by :func:`pathwise.core.builder.build`.
        options: Solver tuning; defaults to :class:`SolverOptions`.

    Returns:
        A :class:`SolveResult`. On a non-optimal outcome ``objective`` is
        ``None`` and variable solutions are absent.
    """
    options = options or SolverOptions()
    model = ctx.model
    status, termination = model.solve(solver_name="highs", **options.as_highs_kwargs())
    normalised = _STATUS_MAP.get(termination, _STATUS_MAP.get(status, SolveStatus.ERROR))
    objective = (
        float(model.objective.value)  # type: ignore[arg-type]
        if normalised == SolveStatus.OPTIMAL
        else None
    )
    logger.info(
        "solve finished: status=%s termination=%s objective=%s", status, termination, objective
    )
    return SolveResult(
        status=normalised, objective=objective, termination=str(termination), context=ctx
    )
