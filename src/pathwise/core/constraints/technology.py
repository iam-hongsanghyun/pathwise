"""Technology energy balance, carrier-share bounds, and baseline lock.

Implements ALGORITHM.md C4 (baseline lock) and C8 (carrier-share balance and
bounds). Energy is carried at the carrier level (``ec``); a technology's total
energy use is its specific energy consumption times the activity it serves.
"""

from __future__ import annotations

from pathwise.core.variables import BuildContext


def add_technology_constraints(ctx: BuildContext) -> None:
    """Add energy-balance, carrier-share, and baseline-lock constraints.

    Args:
        ctx: The populated build context.
    """
    m = ctx.model
    problem = ctx.problem

    # C8 energy balance: sum_r ec[a,k,r,t] = SEC[k] * act[a,k,t]
    #   (masked-out (a,k) drop out on both sides).
    energy = ctx.ec.sum("carrier")  # (asset, technology, period)
    m.add_constraints(energy == ctx.sec * ctx.act, name="energy_balance")

    # C8 carrier-share bounds: s_min*SEC*act <= ec <= s_max*SEC*act
    #   share_min/share_max are (technology, carrier); SEC is (technology); act
    #   is (asset, technology, period) ⇒ broadcasts to (asset, tech, carrier, t).
    upper = (ctx.share_max * ctx.sec) * ctx.act
    lower = (ctx.share_min * ctx.sec) * ctx.act
    m.add_constraints(ctx.ec <= upper, name="carrier_share_max")
    m.add_constraints(ctx.ec >= lower, name="carrier_share_min")

    # C4 baseline lock: existing assets run their baseline technology in t0.
    base_year = problem.base_year
    for asset in problem.assets:
        if asset.is_candidate or asset.baseline_technology is None:
            continue
        k0 = asset.baseline_technology
        m.add_constraints(
            ctx.u.sel(asset=asset.asset_id, technology=k0, period=base_year) == 1,
            name=f"baseline[{asset.asset_id}]",
        )
