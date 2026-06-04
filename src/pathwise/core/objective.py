"""Discounted total-system-cost objective.

Implements ALGORITHM.md §4. Each cost component is gated by a toggle in
:class:`~pathwise.core.problem.CostToggles`; a disabled component contributes
nothing. Operational flows and annuitised CAPEX are weighted by ``DF·duration``;
NPV-convention lump sums carry their own discount factor inside the precomputed
coefficient arrays.
"""

from __future__ import annotations

from linopy.expressions import LinearExpression

from pathwise.core.variables import G_PER_TONNE, BuildContext


def _add(obj: LinearExpression | None, term: LinearExpression) -> LinearExpression:
    return term if obj is None else obj + term


def build_objective(ctx: BuildContext) -> None:
    """Assemble and attach the minimise-cost objective to the model.

    Args:
        ctx: The populated build context (variables + parameters ready).
    """
    problem = ctx.problem
    toggles = problem.toggles
    years = problem.years
    obj: LinearExpression | None = None

    # Fuel / energy cost: ec [MJ] * price [USD/MJ] * (DF·dur).
    if toggles.fuel:
        obj = _add(obj, (ctx.ec * ctx.price * ctx.dfw).sum())

    # Fixed O&M: opex [USD/(size·yr)] * size * u, weighted by (DF·dur).
    if toggles.fixed_opex:
        obj = _add(obj, (ctx.u * (ctx.fixed_opex * ctx.dfw) * ctx.size).sum())

    # Transition CAPEX (coefficient already amortised + discounted).
    if toggles.transition_capex and ctx.has_transitions:
        assert ctx.w is not None and ctx.transition_coef is not None
        obj = _add(obj, (ctx.w * ctx.transition_coef).sum())

    # New-build CAPEX.
    if toggles.newbuild_capex and ctx.has_newbuild:
        assert ctx.build is not None and ctx.build_coef is not None
        obj = _add(obj, (ctx.build * ctx.build_coef).sum())

    # Measure CAPEX — charged on adoption increments (Δz), per event year.
    if toggles.measure_capex and ctx.has_measures:
        z = ctx.z
        assert z is not None and ctx.measure_coef is not None
        for i, y in enumerate(years):
            coef_y = ctx.measure_coef.sel(period=y)
            term = (coef_y * z.sel(period=y)).sum()
            if i > 0:
                term = term - (coef_y * z.sel(period=years[i - 1])).sum()
            obj = _add(obj, term)

    # Carbon cost on net emissions: gross priced, abatement credited.
    if toggles.carbon_cost and bool((ctx.carbon_factor != 0).any()):
        obj = _add(obj, (ctx.ec * ctx.intensity * ctx.carbon_factor).sum())
        if ctx.has_measures:
            assert ctx.z is not None and ctx.abatement is not None
            obj = _add(
                obj,
                -((ctx.z * (ctx.abatement * G_PER_TONNE)) * ctx.carbon_factor).sum(),
            )

    # Slack penalty (always present — keeps the model well-posed and diagnosable).
    obj = _add(obj, (ctx.slk_dem * ctx.slack_weight).sum())
    obj = _add(obj, (ctx.slk_tgt * ctx.slack_weight).sum())

    ctx.model.add_objective(obj)
