"""Translate an :class:`OptimisationProblem` into a ``linopy`` model.

This is the only place that wires the generic pieces together. A sector pack
hands over an :class:`OptimisationProblem`; :func:`build` returns a solvable
:class:`linopy.Model` plus the :class:`BuildContext` (needed later to read the
solution back). The core never sees sector vocabulary.
"""

from __future__ import annotations

from linopy import Model

from pathwise.core.constraints.availability import add_availability_constraints
from pathwise.core.constraints.demand import add_demand_constraints
from pathwise.core.constraints.emissions import add_emission_constraints
from pathwise.core.constraints.macc import add_macc_constraints
from pathwise.core.constraints.technology import add_technology_constraints
from pathwise.core.constraints.transitions import add_transition_constraints
from pathwise.core.objective import build_objective
from pathwise.core.problem import OptimisationProblem
from pathwise.core.variables import BuildContext, build_context
from pathwise.logger import get_logger

logger = get_logger(__name__)


def build(problem: OptimisationProblem) -> BuildContext:
    """Build the full ``linopy`` model for ``problem``.

    Args:
        problem: The optimisation instance (typically produced by a sector
            pack's ``build_problem``).

    Returns:
        The :class:`BuildContext` holding the model and all variables/parameters.
    """
    model = Model()
    ctx = build_context(model, problem)
    logger.info(
        "model built: %d assets, %d techs, %d carriers, %d periods "
        "(transitions=%s, newbuild=%s, measures=%s)",
        len(ctx.assets),
        len(ctx.techs),
        len(ctx.carriers),
        len(ctx.periods),
        ctx.has_transitions,
        ctx.has_newbuild,
        ctx.has_measures,
    )

    add_availability_constraints(ctx)
    add_technology_constraints(ctx)
    add_transition_constraints(ctx)
    add_macc_constraints(ctx)
    add_demand_constraints(ctx)
    add_emission_constraints(ctx)
    build_objective(ctx)

    logger.debug("constraints attached: %d", len(model.constraints))
    return ctx
