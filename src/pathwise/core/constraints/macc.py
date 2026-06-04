"""MACC measure adoption logic.

Implements ALGORITHM.md C9: adoption is non-decreasing over time (persistent),
cheaper blocks fill before dearer ones, and a measure can only be adopted while
its asset is alive. Block abatement potentials are parameters, so the model
stays linear (the adoption fraction ``z`` is the only variable).

Persistence and block-ordering are written over explicit consecutive
period/block pairs (rather than a ``shift``) so the first period/block is not
accidentally pinned to zero.
"""

from __future__ import annotations

from itertools import pairwise

from pathwise.core.variables import BuildContext


def add_macc_constraints(ctx: BuildContext) -> None:
    """Add measure persistence, block-ordering, and availability constraints.

    Args:
        ctx: The populated build context. No-op if measures are disabled.
    """
    if not ctx.has_measures:
        return
    m = ctx.model
    z = ctx.z
    assert z is not None and ctx.blocks is not None  # narrowed by has_measures
    years = ctx.problem.years
    blocks = list(ctx.blocks)

    # C9 persistence: once adopted, stays adopted (z non-decreasing in time).
    for prev_year, year in pairwise(years):
        m.add_constraints(
            z.sel(period=year) - z.sel(period=prev_year) >= 0, name=f"measure_persist[{year}]"
        )

    # C9 block ordering: block b cannot exceed block b-1 (fill cheapest first).
    for prev_b, b in pairwise(blocks):
        m.add_constraints(
            z.sel(block=b) - z.sel(block=prev_b) <= 0, name=f"measure_block_order[{b}]"
        )

    # C9 availability: measures only on assets that are alive that period.
    #   existing_alive is (asset, period); broadcasts over (measure, block).
    m.add_constraints(z <= ctx.existing_alive, name="measure_alive")
