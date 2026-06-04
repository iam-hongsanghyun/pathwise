"""Coordinate sets, parameter arrays, masks, and decision variables.

This module turns an :class:`~pathwise.core.problem.OptimisationProblem` into

* coordinate :class:`pandas.Index` objects (the model dimensions),
* dense parameter :class:`xarray.DataArray` objects (costs, intensities, …),
* boolean masks marking the feasible combinations, and
* the ``linopy`` decision variables.

Everything is gathered into a :class:`BuildContext` that the constraint and
objective modules read. Keeping the parameter/mask construction in one place
keeps the constraint code declarative.

Variable summary (see ``docs/ALGORITHM.md`` §3):

============  ==========================  ==================================
variable      dims                        meaning
============  ==========================  ==================================
``u``         asset, technology, period   tech assignment (binary)
``act``       asset, technology, period   activity served under a tech
``ec``        asset, tech, carrier, per.   carrier energy [MJ]
``w``         asset, technology, period   retrofit event (binary)
``build``     asset, period               new-build commissioning (binary)
``z``         asset, measure, block, per.  MACC block adoption [0, 1]
``slk_dem``   group, period               demand slack
``slk_tgt``   group, period               target slack
============  ==========================  ==================================
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import xarray as xr
from linopy import Model, Variable

from pathwise.core.finance import capital_recovery_factor, discount_factor
from pathwise.core.problem import OptimisationProblem

#: Conversion factor gCO2e per tCO2e (1 t = 1e6 g).
G_PER_TONNE = 1.0e6


@dataclass(slots=True)
class BuildContext:
    """Everything the constraint/objective builders need, precomputed once.

    Constructed in a single shot by :func:`build_context`. Fields that only
    exist when their feature is enabled (``w``/``build``/``z`` and their masks
    and CAPEX coefficients) are optional; the ``has_*`` properties report which
    are present.
    """

    model: Model
    problem: OptimisationProblem

    # Coordinate indices
    assets: pd.Index
    techs: pd.Index
    carriers: pd.Index
    periods: pd.Index
    group_index: pd.Index
    assets_in_group: dict[str, list[str]]

    # Parameter arrays
    size: xr.DataArray
    cap: xr.DataArray
    sec: xr.DataArray
    price: xr.DataArray
    intensity: xr.DataArray
    fixed_opex: xr.DataArray
    share_min: xr.DataArray
    share_max: xr.DataArray

    # Objective weight arrays (per period)
    dfw: xr.DataArray  # DF * duration
    carbon_factor: xr.DataArray
    slack_weight: xr.DataArray

    # Availability + masks
    existing_alive: xr.DataArray
    feas_ak: xr.DataArray
    allowed_akr: xr.DataArray

    # Core variables (always present)
    u: Variable
    act: Variable
    ec: Variable
    slk_dem: Variable
    slk_tgt: Variable

    # Optional feature dimensions / variables
    measures: pd.Index | None = None
    blocks: pd.Index | None = None
    abatement: xr.DataArray | None = None
    transition_coef: xr.DataArray | None = None
    build_coef: xr.DataArray | None = None
    measure_coef: xr.DataArray | None = None
    w: Variable | None = None
    build: Variable | None = None
    z: Variable | None = None

    @property
    def has_measures(self) -> bool:
        return self.z is not None

    @property
    def has_transitions(self) -> bool:
        return self.w is not None

    @property
    def has_newbuild(self) -> bool:
        return self.build is not None


def _zeros(coords: list[pd.Index]) -> xr.DataArray:
    shape = tuple(len(c) for c in coords)
    return xr.DataArray(np.zeros(shape), coords=coords)


def _amortise_window(
    event_year: int,
    years: list[int],
    df: dict[int, float],
    dur: dict[int, float],
    discount_rate: float,
    lifetime: int,
    convention: str,
) -> float:
    r"""Objective coefficient for a unit lump-sum CAPEX incurred at ``event_year``.

    Algorithm:
        annuity::

            CRF(L) * sum_{t': event<=t'<event+L, t' in horizon} DF_t' * dur_t'

        npv::

            DF_event

    Args:
        event_year: Year the capital is committed.
        years: All modelled years.
        df: Discount factor by year.
        dur: Period duration by year.
        discount_rate: Discount rate for the capital recovery factor.
        lifetime: Economic lifetime ``L`` [yr].
        convention: ``"annuity"`` or ``"npv"``.

    Returns:
        The multiplier applied to the (unit) lump-sum in the objective.
    """
    if convention == "npv":
        return df[event_year]
    crf = capital_recovery_factor(discount_rate, lifetime)
    weight = sum(df[y] * dur[y] for y in years if event_year <= y < event_year + lifetime)
    return crf * weight


def build_context(model: Model, problem: OptimisationProblem) -> BuildContext:
    """Assemble coordinates, parameters, masks, and variables for ``problem``.

    Args:
        model: A fresh :class:`linopy.Model`.
        problem: The optimisation instance to translate.

    Returns:
        A fully-populated :class:`BuildContext`.
    """
    opt = problem.options
    years = problem.years
    base_year = problem.base_year
    conv = opt.capex_convention.value

    asset_by_id = {a.asset_id: a for a in problem.assets}
    tech_by_id = {t.technology_id: t for t in problem.technologies}
    carrier_by_id = {c.carrier_id: c for c in problem.carriers}
    measure_by_id = {m.measure_id: m for m in problem.measures}

    # ── Coordinate indices ───────────────────────────────────────────────────
    A = pd.Index([a.asset_id for a in problem.assets], name="asset")
    K = pd.Index([t.technology_id for t in problem.technologies], name="technology")
    R = pd.Index([c.carrier_id for c in problem.carriers], name="carrier")
    T = pd.Index(years, name="period")
    group_index = pd.Index(problem.groups, name="group")
    assets_in_group: dict[str, list[str]] = {g: [] for g in problem.groups}
    for a in problem.assets:
        assets_in_group[a.group].append(a.asset_id)

    # ── Parameter arrays ─────────────────────────────────────────────────────
    size = xr.DataArray([asset_by_id[a].size for a in A], coords=[A])
    cap = xr.DataArray([asset_by_id[a].capacity for a in A], coords=[A])
    sec = xr.DataArray([tech_by_id[k].specific_energy for k in K], coords=[K])
    price = xr.DataArray([[carrier_by_id[r].price(y) for y in years] for r in R], coords=[R, T])
    intensity = xr.DataArray(
        [[carrier_by_id[r].intensity(y) for y in years] for r in R], coords=[R, T]
    )
    fixed_opex = xr.DataArray(
        [[tech_by_id[k].fixed_opex(y) for y in years] for k in K], coords=[K, T]
    )
    share_min = xr.DataArray(
        [[tech_by_id[k].carrier_share_min.get(r, 0.0) for r in R] for k in K], coords=[K, R]
    )
    share_max = xr.DataArray(
        [[tech_by_id[k].carrier_share_max.get(r, 1.0) for r in R] for k in K], coords=[K, R]
    )

    # ── Objective weight arrays ──────────────────────────────────────────────
    dur = {p.year: p.duration_years for p in problem.periods}
    df = {y: discount_factor(y, base_year, opt.discount_rate) for y in years}
    dfw = xr.DataArray([df[y] * dur[y] for y in years], coords=[T])
    carbon_factor = xr.DataArray(
        [df[y] * dur[y] * opt.carbon_price(y) / G_PER_TONNE for y in years], coords=[T]
    )
    slack_weight = xr.DataArray([df[y] * dur[y] * opt.slack_penalty for y in years], coords=[T])

    # ── Availability (existing assets) ───────────────────────────────────────
    def alive(a_id: str, year: int) -> float:
        a = asset_by_id[a_id]
        if a.is_candidate:
            return 0.0
        if a.built_year is not None and year < a.built_year:
            return 0.0
        if a.retire_year is not None and year > a.retire_year:
            return 0.0
        return 1.0

    existing_alive = xr.DataArray([[alive(a, y) for y in years] for a in A], coords=[A, T])

    # ── Masks ────────────────────────────────────────────────────────────────
    feas = {a.asset_id: set(problem.feasible_technologies(a)) for a in problem.assets}
    # When transitions are disabled, existing assets are pinned to their baseline.
    if not opt.include_transitions:
        for a in problem.assets:
            if not a.is_candidate and a.baseline_technology is not None:
                feas[a.asset_id] = {a.baseline_technology}

    feas_ak = xr.DataArray([[k in feas[a] for k in K] for a in A], coords=[A, K])
    allowed = {
        k: (set(R) if not tech_by_id[k].allowed_carriers else set(tech_by_id[k].allowed_carriers))
        for k in K
    }
    allowed_akr = xr.DataArray(
        [[[(k in feas[a]) and (r in allowed[k]) for r in R] for k in K] for a in A],
        coords=[A, K, R],
    )

    # ── Core variables (always present) ──────────────────────────────────────
    u = model.add_variables(binary=True, coords=[A, K, T], name="u", mask=feas_ak)
    act = model.add_variables(lower=0.0, coords=[A, K, T], name="act", mask=feas_ak)
    ec = model.add_variables(lower=0.0, coords=[A, K, R, T], name="ec", mask=allowed_akr)
    slk_dem = model.add_variables(lower=0.0, coords=[group_index, T], name="slk_dem")
    slk_tgt = model.add_variables(lower=0.0, coords=[group_index, T], name="slk_tgt")

    # ── Transitions (optional) ───────────────────────────────────────────────
    w: Variable | None = None
    transition_coef: xr.DataArray | None = None
    if opt.include_transitions:

        def w_ok(a_id: str, k: str, year: int) -> bool:
            a = asset_by_id[a_id]
            if a.is_candidate or k not in feas[a_id]:
                return False
            if a.built_year is not None and (year - a.built_year) < opt.min_dwell_years:
                return False
            return True

        w_mask = xr.DataArray(
            [[[w_ok(a, k, y) for y in years] for k in K] for a in A], coords=[A, K, T]
        )
        if bool(w_mask.any()):
            w = model.add_variables(binary=True, coords=[A, K, T], name="w", mask=w_mask)
            # Destination-technology retrofit cost, amortised + discounted.
            to_capex: dict[str, tuple[float, int]] = {}
            for tr in problem.transitions:
                life = tr.lifetime_years or opt.default_lifetime_years
                to_capex[tr.to_technology] = (tr.capex_per_size, life)
            coef = _zeros([A, K, T])
            for ai, a_id in enumerate(A):
                asize = asset_by_id[a_id].size
                for ki, k in enumerate(K):
                    if k not in to_capex:
                        continue
                    capex_per_size, life = to_capex[k]
                    for ti, y in enumerate(T):
                        coef[ai, ki, ti] = (
                            capex_per_size
                            * asize
                            * _amortise_window(y, years, df, dur, opt.discount_rate, life, conv)
                        )
            transition_coef = coef

    # ── New build (optional) ─────────────────────────────────────────────────
    build: Variable | None = None
    build_coef: xr.DataArray | None = None
    if opt.include_new_build:
        build_mask = xr.DataArray(
            [[asset_by_id[a].is_candidate for _ in years] for a in A], coords=[A, T]
        )
        if bool(build_mask.any()):
            build = model.add_variables(binary=True, coords=[A, T], name="build", mask=build_mask)
            coef_b = _zeros([A, T])
            for ai, a_id in enumerate(A):
                a = asset_by_id[a_id]
                if not a.is_candidate:
                    continue
                life = a.build_lifetime_years or opt.default_newbuild_lifetime_years
                for ti, y in enumerate(T):
                    coef_b[ai, ti] = (
                        a.build_capex_per_size
                        * a.size
                        * _amortise_window(y, years, df, dur, opt.discount_rate, life, conv)
                    )
            build_coef = coef_b

    # ── Measures (optional) ──────────────────────────────────────────────────
    measures_idx: pd.Index | None = None
    blocks_idx: pd.Index | None = None
    abatement: xr.DataArray | None = None
    measure_coef: xr.DataArray | None = None
    z: Variable | None = None
    if opt.include_measures and problem.measures:
        max_blocks = max((len(m.blocks) for m in problem.measures), default=0)
        if max_blocks > 0:
            M = pd.Index([m.measure_id for m in problem.measures], name="measure")
            B = pd.Index(range(max_blocks), name="block")

            def z_ok(a_id: str, m_id: str, b: int, year: int) -> bool:
                meas = measure_by_id[m_id]
                if b >= len(meas.blocks):
                    return False
                if meas.applicable_assets and a_id not in meas.applicable_assets:
                    return False
                if meas.earliest_year is not None and year < meas.earliest_year:
                    return False
                return True

            z_mask = xr.DataArray(
                [[[[z_ok(a, m, b, y) for y in years] for b in B] for m in M] for a in A],
                coords=[A, M, B, T],
            )
            abatement = xr.DataArray(
                [
                    [b_.abatement for b_ in _padded_blocks(measure_by_id[m].blocks, max_blocks)]
                    for m in M
                ],
                coords=[M, B],
            )
            if bool(z_mask.any()):
                z = model.add_variables(
                    lower=0.0, upper=1.0, coords=[A, M, B, T], name="z", mask=z_mask
                )
                coef_m = _zeros([M, B, T])
                for mi, m_id in enumerate(M):
                    meas = measure_by_id[m_id]
                    life = meas.lifetime_years or opt.default_measure_lifetime_years
                    for bi in range(len(meas.blocks)):
                        capex = meas.blocks[bi].capex
                        for ti, y in enumerate(T):
                            coef_m[mi, bi, ti] = capex * _amortise_window(
                                y, years, df, dur, opt.discount_rate, life, conv
                            )
                measures_idx, blocks_idx, measure_coef = M, B, coef_m

    return BuildContext(
        model=model,
        problem=problem,
        assets=A,
        techs=K,
        carriers=R,
        periods=T,
        group_index=group_index,
        assets_in_group=assets_in_group,
        size=size,
        cap=cap,
        sec=sec,
        price=price,
        intensity=intensity,
        fixed_opex=fixed_opex,
        share_min=share_min,
        share_max=share_max,
        dfw=dfw,
        carbon_factor=carbon_factor,
        slack_weight=slack_weight,
        existing_alive=existing_alive,
        feas_ak=feas_ak,
        allowed_akr=allowed_akr,
        u=u,
        act=act,
        ec=ec,
        slk_dem=slk_dem,
        slk_tgt=slk_tgt,
        measures=measures_idx,
        blocks=blocks_idx,
        abatement=abatement,
        transition_coef=transition_coef,
        build_coef=build_coef,
        measure_coef=measure_coef,
        w=w,
        build=build,
        z=z,
    )


def _padded_blocks(blocks: tuple, n: int) -> list:
    """Return ``blocks`` padded to length ``n`` with zero-abatement placeholders."""
    from pathwise.core.entities import MaccBlock

    return list(blocks) + [MaccBlock() for _ in range(n - len(blocks))]
