"""Solve a built model with HiGHS (via ``linopy``) and report status.

Normalises the solver outcome into a small enum and forwards HiGHS tuning,
including the global scaling that keeps large-coefficient models stable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pathwise.logger import get_logger

if TYPE_CHECKING:
    from pathwise.core.variables import BuildContext

logger = get_logger(__name__)


class SolveStatus(StrEnum):
    """Normalised solve outcome."""

    OPTIMAL = "optimal"
    INFEASIBLE = "infeasible"
    UNBOUNDED = "unbounded"
    ERROR = "error"


@dataclass(slots=True)
class SolverOptions:
    """HiGHS tuning forwarded by ``linopy``.

    Attributes:
        solver_name: ``linopy`` solver backend name (e.g. ``"highs"``, ``"glpk"``).
        time_limit_s: Wall-clock limit [s].
        mip_rel_gap: Relative MIP optimality gap [—].
        threads: Solver threads.
        output_flag: If ``True``, HiGHS prints its log.
        user_bound_scale: HiGHS global bound scaling (log2 exponent); ``None``
            leaves the default. An exact, solution-preserving transform.
        user_objective_scale: HiGHS global objective scaling (log2 exponent);
            ``None`` leaves the default.
    """

    solver_name: str = "highs"
    time_limit_s: float = 600.0
    mip_rel_gap: float = 0.01
    threads: int = 4
    output_flag: bool = False
    user_bound_scale: int | None = None
    user_objective_scale: int | None = None

    def as_highs_kwargs(self) -> dict[str, Any]:
        """Return the HiGHS keyword arguments ``linopy`` forwards."""
        kwargs: dict[str, Any] = {
            "time_limit": float(self.time_limit_s),
            "mip_rel_gap": float(self.mip_rel_gap),
            "threads": int(self.threads),
            "output_flag": bool(self.output_flag),
        }
        if self.user_bound_scale is not None:
            kwargs["user_bound_scale"] = int(self.user_bound_scale)
        if self.user_objective_scale is not None:
            kwargs["user_objective_scale"] = int(self.user_objective_scale)
        return kwargs


def options_from_scenario(scenario: Any) -> SolverOptions:
    """Build :class:`SolverOptions` from a scenario's ``solver`` sub-config.

    Lets the hierarchy / network solve paths honour the scenario's solver
    tuning (name, MIP gap, threads, time limit) instead of always falling back to
    the defaults. Duck-typed (reads attributes, no import) to avoid a
    ``core → data`` dependency cycle; returns the defaults if no solver config.
    """
    s = getattr(scenario, "solver", None)
    if s is None:
        return SolverOptions()
    # Source the per-field fallbacks from the dataclass defaults (single source of
    # truth) rather than repeating the literals, so they can't silently drift.
    d = SolverOptions()
    return SolverOptions(
        solver_name=str(getattr(s, "name", d.solver_name)),
        time_limit_s=float(getattr(s, "time_limit_s", d.time_limit_s)),
        mip_rel_gap=float(getattr(s, "mip_gap", d.mip_rel_gap)),
        threads=int(getattr(s, "threads", d.threads)),
    )


@dataclass(slots=True)
class SolveResult:
    """Outcome of a solve.

    Attributes:
        status: Normalised status.
        objective: Objective value if solved, else ``None``.
        termination: Raw solver termination string.
        context: The build context (variable solutions live on its model).
    """

    status: SolveStatus
    objective: float | None
    termination: str
    context: BuildContext = field(repr=False)

    @property
    def ok(self) -> bool:
        """``True`` if an optimal solution was found."""
        return self.status == SolveStatus.OPTIMAL


_STATUS_MAP = {
    "optimal": SolveStatus.OPTIMAL,
    "infeasible": SolveStatus.INFEASIBLE,
    "unbounded": SolveStatus.UNBOUNDED,
    "infeasible_or_unbounded": SolveStatus.INFEASIBLE,
}


def solve(ctx: BuildContext, options: SolverOptions | None = None) -> SolveResult:
    """Solve the model in ``ctx`` with HiGHS.

    Args:
        ctx: The build context from :func:`pathwise.core.build.build`.
        options: Solver tuning; defaults to :class:`SolverOptions`.

    Returns:
        A :class:`SolveResult` (``objective`` is ``None`` on a non-optimal outcome).
    """
    options = options or SolverOptions()
    model = ctx.model
    status, termination = model.solve(solver_name=options.solver_name, **options.as_highs_kwargs())
    normalised = _STATUS_MAP.get(termination, _STATUS_MAP.get(status, SolveStatus.ERROR))
    objective: float | None = None
    if normalised == SolveStatus.OPTIMAL:
        objective = float(model.objective.value)  # type: ignore[arg-type]
        # A degenerate / ill-scaled model can terminate "optimal" with a non-finite
        # objective; treat that as a failure rather than reporting bogus success.
        if not math.isfinite(objective):
            logger.error("solver reported optimal but objective is non-finite: %s", objective)
            normalised, objective = SolveStatus.ERROR, None
    logger.info(
        "solve finished: status=%s termination=%s objective=%s", status, termination, objective
    )
    return SolveResult(
        status=normalised, objective=objective, termination=str(termination), context=ctx
    )
