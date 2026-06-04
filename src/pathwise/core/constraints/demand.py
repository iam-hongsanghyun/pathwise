"""Activity / demand balance.

Implements ALGORITHM.md C1: the activity served by a group's assets must meet
that group's required activity each period. A non-negative slack absorbs any
shortfall (penalised heavily in the objective) so the model stays feasible and
the binding period/group is diagnosable.
"""

from __future__ import annotations

from pathwise.core.variables import BuildContext


def add_demand_constraints(ctx: BuildContext) -> None:
    """Add per-group, per-period activity-balance constraints.

    Args:
        ctx: The populated build context.
    """
    m = ctx.model
    problem = ctx.problem
    for g in ctx.group_index:
        assets = ctx.assets_in_group[g]
        if not assets:
            continue
        served = ctx.act.sel(asset=assets).sum(["asset", "technology"])  # (period)
        slack = ctx.slk_dem.sel(group=g)  # (period)
        for y in problem.years:
            required = problem.demand.get((g, y), 0.0)
            if required <= 0.0:
                continue
            m.add_constraints(
                served.sel(period=y) + slack.sel(period=y) >= required,
                name=f"demand[{g},{y}]",
            )
