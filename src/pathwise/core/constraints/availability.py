"""Asset availability, technology selection, and capacity constraints.

Implements ALGORITHM.md C2 (capacity/availability), C3 (one technology per
asset per period), and the new-build commissioning logic of C7.
"""

from __future__ import annotations

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

    # C2 capacity: activity under a technology cannot exceed capacity when used.
    #   act[a,k,t] <= cap[a] * u[a,k,t]   (vectorised over feasible (a,k,t))
    m.add_constraints(ctx.act <= ctx.cap * ctx.u, name="capacity")

    # C3 selection + availability — per asset (existing vs candidate differ).
    for a_id in ctx.assets:
        asset = asset_by_id[a_id]
        u_a = ctx.u.sel(asset=a_id)  # dims (technology, period)
        if not asset.is_candidate:
            # sum_k u = alive_param
            alive = ctx.existing_alive.sel(asset=a_id)  # (period)
            m.add_constraints(u_a.sum("technology") == alive, name=f"select[{a_id}]")
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
