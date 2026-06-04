"""Emission-intensity and absolute-emission targets.

Implements ALGORITHM.md C10/C11. Net emissions are gross carrier emissions
minus adopted MACC abatement. Targets are softened with a non-negative slack so
an over-tight target produces a diagnosable violation rather than an infeasible
model.
"""

from __future__ import annotations

from pathwise.core.entities import TargetType
from pathwise.core.variables import G_PER_TONNE, BuildContext


def _group_emission_expressions(ctx: BuildContext, assets: list[str]):
    """Return ``(gross_gco2e, energy_mj, abatement_gco2e)`` expressions per period.

    Each is a ``linopy`` expression with a single ``period`` dimension, summed
    over the given assets.
    """
    ec = ctx.ec.sel(asset=assets)
    gross = (ec * ctx.intensity).sum(["asset", "technology", "carrier"])  # gCO2e
    energy = ec.sum(["asset", "technology", "carrier"])  # MJ
    if ctx.has_measures:
        assert ctx.z is not None
        z = ctx.z.sel(asset=assets)
        abatement = (z * ctx.abatement * G_PER_TONNE).sum(["asset", "measure", "block"])
    else:
        abatement = None
    return gross, energy, abatement


def add_emission_constraints(ctx: BuildContext) -> None:
    """Add per-group, per-period emission targets (intensity or absolute).

    Args:
        ctx: The populated build context.
    """
    m = ctx.model
    problem = ctx.problem
    for target in problem.targets:
        assets = ctx.assets_in_group.get(target.group, [])
        if not assets:
            continue
        gross, energy, abatement = _group_emission_expressions(ctx, assets)
        slack = ctx.slk_tgt.sel(group=target.group)
        for y in problem.years:
            limit = target.limit(y)
            if limit is None:
                continue
            net = gross.sel(period=y)
            if abatement is not None:
                net = net - abatement.sel(period=y)
            if target.target_type == TargetType.INTENSITY_CAP:
                # net <= limit * energy + slack   (gCO2e/MJ cap on fleet average)
                m.add_constraints(
                    net - limit * energy.sel(period=y) - slack.sel(period=y) <= 0,
                    name=f"intensity[{target.group},{y}]",
                )
            else:  # ABSOLUTE_CAP, limit in tCO2e
                m.add_constraints(
                    net - slack.sel(period=y) <= limit * G_PER_TONNE,
                    name=f"absolute[{target.group},{y}]",
                )
