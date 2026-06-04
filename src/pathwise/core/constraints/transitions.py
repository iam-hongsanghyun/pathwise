"""Retrofit (technology transition) event detection and limits.

Implements ALGORITHM.md C5 (linearised event detection) and C6 (transition
count limit). The event variable ``w[a,k,t]`` is forced to 1 exactly when an
asset adopts technology ``k`` it was not running in the previous period; it
drives the discounted retrofit CAPEX in the objective.

Event detection is applied only between *consecutive* periods (never at the
baseline period — there is no "previous" state to transition from), so the
baseline assignment does not spuriously consume the transition budget.
"""

from __future__ import annotations

from itertools import pairwise

from pathwise.core.variables import BuildContext


def add_transition_constraints(ctx: BuildContext) -> None:
    """Add retrofit event-detection and per-asset transition-count limits.

    Args:
        ctx: The populated build context. No-op if transitions are disabled.
    """
    if not ctx.has_transitions:
        return
    m = ctx.model
    opt = ctx.problem.options
    years = ctx.problem.years
    base_year = ctx.problem.base_year
    u = ctx.u
    w = ctx.w
    assert w is not None  # narrowed by has_transitions

    # No transition event at the baseline period.
    if base_year in years:
        m.add_constraints(w.sel(period=base_year) == 0, name="transition_baseline_zero")

    # C5 event detection between consecutive periods.
    for prev_year, year in pairwise(years):
        w_now = w.sel(period=year)
        u_now = u.sel(period=year)
        u_prev = u.sel(period=prev_year)
        m.add_constraints(w_now >= u_now - u_prev, name=f"transition_detect[{year}]")
        m.add_constraints(w_now <= u_now, name=f"transition_upper_now[{year}]")
        m.add_constraints(w_now <= 1 - u_prev, name=f"transition_upper_prev[{year}]")

    # C6 limit on retrofit events per asset over the horizon.
    m.add_constraints(
        w.sum(["technology", "period"]) <= opt.max_transitions_per_asset,  # type: ignore[arg-type]
        name="transition_count",
    )
