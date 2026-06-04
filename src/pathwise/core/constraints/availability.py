"""Asset availability, technology selection, and capacity constraints.

Implements ALGORITHM.md C2 (capacity/availability), C3 (one technology per
asset per period), and the new-build commissioning logic of C7.
"""

from __future__ import annotations

import numpy as np
import xarray as xr

from pathwise.core.variables import BuildContext


def add_availability_constraints(ctx: BuildContext) -> None:
    """Add selection, capacity, and commissioning constraints.

    For existing assets the *alive* state is a parameter (built/retire window);
    exactly one technology is selected whenever alive. For candidate new-build
    assets the alive state is the cumulative (lead-shifted) build decision, and a
    candidate is commissioned at most once.

    Args:
        ctx: The populated build context (variables already created).
    """
    m = ctx.model
    problem = ctx.problem
    asset_by_id = {a.asset_id: a for a in problem.assets}
    years = problem.years

    # C2 capacity: activity under a technology cannot exceed an upper bound when
    # the technology is used: act[a,k,t] <= M[a,t] * u[a,k,t]. The big-M is the
    # *tightest* valid bound on served activity — the fixed workload for
    # fixed-activity assets, otherwise the nameplate capacity. A tight M keeps
    # the MILP well-conditioned (a loose M, e.g. 1e9, makes HiGHS mis-solve).
    bound = np.empty((len(ctx.assets), len(ctx.periods)))
    for ai, a_id in enumerate(ctx.assets):
        asset = asset_by_id[a_id]
        for ti, y in enumerate(years):
            bound[ai, ti] = asset.activity(y) if asset.has_fixed_activity else asset.capacity
    act_ub = xr.DataArray(bound, coords=[ctx.assets, ctx.periods])
    m.add_constraints(ctx.act <= act_ub * ctx.u, name="capacity")

    # C3 selection + availability — per asset (existing vs candidate differ).
    for a_id in ctx.assets:
        asset = asset_by_id[a_id]
        u_a = ctx.u.sel(asset=a_id)  # dims (technology, period)
        act_a = ctx.act.sel(asset=a_id)  # dims (technology, period)
        if not asset.is_candidate:
            # sum_k u = alive_param
            alive = ctx.existing_alive.sel(asset=a_id)  # (period)
            m.add_constraints(u_a.sum("technology") == alive, name=f"select[{a_id}]")
            # Fixed exogenous workload: served activity pinned while alive.
            if asset.has_fixed_activity:
                for y in years:
                    req = asset.activity(y) * float(alive.sel(period=y).item())
                    m.add_constraints(
                        act_a.sel(period=y).sum("technology") == req,
                        name=f"fixed_activity[{a_id},{y}]",
                    )
        else:
            # Commissioned at most once.
            if ctx.build is None:
                # New build disabled ⇒ candidate never online.
                m.add_constraints(u_a.sum("technology") == 0, name=f"select[{a_id}]")
                continue
            build_a = ctx.build.sel(asset=a_id)  # (period)
            m.add_constraints(build_a.sum("period") <= 1, name=f"build_once[{a_id}]")
            lead = asset.build_lead_years
            retire = asset.retire_year
            for y in years:
                # alive_t = sum_{τ <= y - lead} build[τ]
                online_years = [yy for yy in years if yy <= y - lead]
                alive_expr = build_a.sel(period=online_years).sum() if online_years else None
                lhs = u_a.sel(period=y).sum("technology")
                retired = retire is not None and y > retire
                if alive_expr is None or retired:
                    m.add_constraints(lhs == 0, name=f"select[{a_id},{y}]")
                else:
                    m.add_constraints(lhs == alive_expr, name=f"select[{a_id},{y}]")
                    # Fixed workload for a candidate scales with its online state.
                    if asset.has_fixed_activity and not retired:
                        served = act_a.sel(period=y).sum("technology")
                        m.add_constraints(
                            served - asset.activity(y) * alive_expr == 0,
                            name=f"fixed_activity[{a_id},{y}]",
                        )
